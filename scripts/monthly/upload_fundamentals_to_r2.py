"""
upload_fundamentals_to_r2.py

temp_fundamentals.json を年別構成でR2にアップロード
stocks/fundamentals/quarterly/{year}/{symbol}.json

デフォルト（引数なし・月次Actionの通常運用）は「year-freeze」:
  - 過去年ファイルは R2 に既に存在すれば上書きしない（凍結）
  - 当年（および未来日付）は常に上書き
--force-past を付けると全年を上書き（スキーマ変更やバックフィル時に使う）。
"""
import argparse
import boto3
import os
import logging
import json
from datetime import datetime
from dotenv import load_dotenv
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()

DATA_FOLDER = "data"
TEMP_FUNDAMENTALS_JSON = os.path.join(DATA_FOLDER, "temp_fundamentals.json")
R2_PREFIX = "stocks/fundamentals/quarterly/"

MAX_WORKERS = 10
CURRENT_YEAR = datetime.now().year

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def split_fundamentals_by_year(fundamentals_dict):
    """
    Fundamentals データを年別に分割

    Args:
        fundamentals_dict: {symbol: {ticker, data: [{date, eps, ...}]}}

    Returns:
        dict: {symbol: {year: [{date, eps, ...}]}}
    """
    logging.info("Splitting fundamentals data by year...")

    symbol_year_data = {}

    for symbol, info in fundamentals_dict.items():
        year_groups = defaultdict(list)

        for quarter in info['data']:
            # date: "2024-Q1" or "2024-03-31"
            date_str = quarter['date']

            # 年を抽出
            if 'Q' in date_str:
                year = int(date_str.split('-')[0])  # "2024-Q1" -> 2024
            else:
                year = int(date_str[:4])  # "2024-03-31" -> 2024

            year_groups[year].append(quarter)

        symbol_year_data[symbol] = dict(year_groups)

    # 統計
    total_years = set()
    for years in symbol_year_data.values():
        total_years.update(years.keys())

    logging.info(f"Split data into years: {sorted(total_years)}")
    logging.info(f"Total symbols: {len(symbol_year_data)}")

    return symbol_year_data


def list_existing_keys(endpoint, access_key, secret_key, bucket_name, prefix):
    """R2 上の既存キー集合を返す（year-freeze の存在判定用）。"""
    s3 = boto3.client('s3', endpoint_url=endpoint, aws_access_key_id=access_key,
                      aws_secret_access_key=secret_key, region_name='auto')
    keys = set()
    try:
        paginator = s3.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix):
            for obj in page.get('Contents', []):
                keys.add(obj['Key'])
    finally:
        s3.close()
    return keys


def upload_single_object(endpoint, access_key, secret_key, bucket_name, key, body_bytes, max_retries=3):
    """スレッドごとに独立したクライアントでput_object（Daily方式）"""
    s3_client = None
    try:
        s3_client = boto3.client(
            's3',
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name='auto'
        )

        for attempt in range(max_retries):
            try:
                s3_client.put_object(
                    Bucket=bucket_name,
                    Key=key,
                    Body=body_bytes,
                    ContentType='application/json',
                    CacheControl='public, max-age=2592000'  # 30日キャッシュ
                )
                return True
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                logging.warning(f"Retry {attempt + 1}/{max_retries} for {key}: {e}")
        return False
    finally:
        if s3_client:
            s3_client.close()


def upload_fundamentals_to_r2(force_past=False):
    """Fundamental データを年別にR2アップロード（並列処理）。

    force_past=False（既定）: 過去年は R2 に既存なら凍結（上書きしない）、当年は常に上書き。
    force_past=True: 全年を上書き（スキーマ変更・バックフィル用）。
    """

    required_env = ['R2_ENDPOINT', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET_NAME']
    missing = [env for env in required_env if not os.environ.get(env)]

    if missing:
        raise ValueError(f"Missing environment variables: {', '.join(missing)}")

    if not os.path.exists(TEMP_FUNDAMENTALS_JSON):
        raise FileNotFoundError(f"{TEMP_FUNDAMENTALS_JSON} does not exist")

    # データ読み込み
    with open(TEMP_FUNDAMENTALS_JSON, 'r') as f:
        fundamentals_dict = json.load(f)

    logging.info(f"Loaded {len(fundamentals_dict)} fundamental records")

    # 年別に分割
    symbol_year_data = split_fundamentals_by_year(fundamentals_dict)

    # 認証情報（スレッドに明示的に渡す）
    endpoint = os.environ['R2_ENDPOINT']
    access_key = os.environ['R2_ACCESS_KEY_ID']
    secret_key = os.environ['R2_SECRET_ACCESS_KEY']
    bucket_name = os.environ['R2_BUCKET_NAME']

    # year-freeze: 過去年の既存キーを取得（force_past 時はスキップ）
    existing_keys = set()
    if not force_past:
        logging.info("Listing existing R2 keys for year-freeze...")
        existing_keys = list_existing_keys(endpoint, access_key, secret_key, bucket_name, R2_PREFIX)
        logging.info(f"  existing objects under {R2_PREFIX}: {len(existing_keys)}")

    # アップロードタスクを事前構築（メインスレッドでJSON化）
    now_iso = datetime.now().isoformat()
    upload_tasks = []
    frozen_count = 0

    for symbol, year_data in symbol_year_data.items():
        for year, quarters in year_data.items():
            key = f"stocks/fundamentals/quarterly/{year}/{symbol}.json"
            # 過去年かつ既存 → 凍結（上書きしない）。当年・未来・force_past は常に投入。
            if not force_past and year < CURRENT_YEAR and key in existing_keys:
                frozen_count += 1
                continue
            output = {
                'ticker': symbol,
                'data': quarters,
                'lastUpdated': now_iso
            }
            body_bytes = json.dumps(output).encode('utf-8')
            upload_tasks.append((key, body_bytes))

    total_files = len(upload_tasks)
    if not force_past:
        logging.info(f"year-freeze: {frozen_count} past-year files frozen (skipped)")
    else:
        logging.info("force_past: overwriting ALL years")

    logging.info(f"\n{'='*60}")
    logging.info("UPLOADING FUNDAMENTALS TO R2")
    logging.info(f"{'='*60}")
    logging.info(f"Total files to upload: {total_files}")
    logging.info(f"Workers: {MAX_WORKERS}")
    logging.info(f"{'='*60}\n")

    success_count = 0
    fail_count = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(
                upload_single_object,
                endpoint, access_key, secret_key, bucket_name,
                key, body_bytes
            ): key
            for key, body_bytes in upload_tasks
        }

        for future in as_completed(futures):
            key = futures[future]
            try:
                if future.result():
                    success_count += 1
                    if success_count % 100 == 0:
                        logging.info(f"Progress: {success_count}/{total_files}")
                else:
                    fail_count += 1
                    logging.error(f"Failed: {key}")
            except Exception as e:
                fail_count += 1
                logging.error(f"Error uploading {key}: {e}")

    logging.info(f"\n{'='*60}")
    logging.info("✅ FUNDAMENTALS UPLOADED TO R2")
    logging.info(f"{'='*60}")
    logging.info(f"Uploaded: {success_count} files, Failed: {fail_count} files")
    logging.info(f"Structure: stocks/fundamentals/quarterly/{{year}}/{{symbol}}.json")
    logging.info(f"{'='*60}\n")

    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--force-past', action='store_true',
                        help='過去年も含め全年を上書き（スキーマ変更・バックフィル用）')
    args = parser.parse_args()
    try:
        return upload_fundamentals_to_r2(force_past=args.force_past)
    except Exception as e:
        logging.error(f"Upload failed: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)

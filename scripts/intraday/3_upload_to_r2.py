"""
3_upload_to_r2.py

5分足月別 JSON を Cloudflare R2 へアップロード

スマートスキップ戦略:
  - その月の末日が今日から 60 日以上前 → 取得上限を超えているため完結済み
    → R2 に存在すればスキップ
  - 直近 60 日以内の月 → 毎日データが追加される可能性あり → 常に上書き
"""
import os
import boto3
import logging
from datetime import date
from calendar import monthrange
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv()

R2_ENDPOINT = os.getenv('R2_ENDPOINT')
R2_ACCESS_KEY_ID = os.getenv('R2_ACCESS_KEY_ID')
R2_SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY')
R2_BUCKET_NAME = os.getenv('R2_BUCKET_NAME')

DATA_FOLDER = "data"
R2_OUTPUT = os.path.join(DATA_FOLDER, "intraday", "r2")
R2_PREFIX = "stocks/intraday/5min"

MAX_WORKERS = 10

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def create_s3_client():
    return boto3.client(
        's3',
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name='auto'
    )


def is_month_immutable(year, month):
    """
    その月のデータが完結しており変更不要かを判定

    月の末日が今日から 60 日以上前 → Yahoo Finance の取得上限外 → 完結済み
    """
    last_day = monthrange(year, month)[1]
    month_end = date(year, month, last_day)
    return (date.today() - month_end).days > 60


def extract_year_month_from_key(s3_key):
    """
    S3 キーから (year, month) を抽出

    例: stocks/intraday/5min/2026/03/AAPL.json → (2026, 3)
    """
    parts = s3_key.split('/')
    # parts: ['stocks', 'intraday', '5min', '{year}', '{month}', '{symbol}.json']
    try:
        year = int(parts[3])
        month = int(parts[4])
        return year, month
    except (IndexError, ValueError):
        return None, None


def get_existing_keys_in_r2(prefix):
    """R2 の指定プレフィックス配下の全キーを取得"""
    s3_client = create_s3_client()
    existing_keys = set()

    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=R2_BUCKET_NAME, Prefix=prefix)

        for page in pages:
            if 'Contents' in page:
                for obj in page['Contents']:
                    existing_keys.add(obj['Key'])

        logging.info(f"Found {len(existing_keys)} existing files in R2 under '{prefix}'")
    except Exception as e:
        logging.error(f"Error listing R2 objects: {e}")
    finally:
        s3_client.close()

    return existing_keys


def upload_single_file(endpoint, access_key, secret_key, bucket_name, file_path, key, max_retries=3):
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
                s3_client.upload_file(file_path, bucket_name, key)
                return True
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                logging.warning(f"Retry {attempt + 1}/{max_retries} for {key}: {e}")
        return False
    finally:
        if s3_client:
            s3_client.close()


def collect_all_files():
    """
    ローカルの R2 出力ディレクトリ配下の全 JSON ファイルを収集

    Returns:
        list of (local_path, s3_key)
    """
    intraday_dir = os.path.join(R2_OUTPUT, "stocks", "intraday", "5min")

    if not os.path.exists(intraday_dir):
        logging.warning(f"Directory not found: {intraday_dir}")
        return []

    all_files = []
    for root, dirs, files in os.walk(intraday_dir):
        for file in files:
            if not file.endswith('.json'):
                continue
            local_path = os.path.join(root, file)
            relative_path = os.path.relpath(local_path, R2_OUTPUT)
            s3_key = relative_path.replace('\\', '/')
            all_files.append((local_path, s3_key))

    return all_files


def filter_files_to_upload(all_files):
    """
    スマートスキップ: 完結済み月で R2 に既存のファイルは除外
    """
    # 完結済み月のファイルを分類
    immutable_files = []
    active_files = []

    for local_path, s3_key in all_files:
        year, month = extract_year_month_from_key(s3_key)
        if year and month and is_month_immutable(year, month):
            immutable_files.append((local_path, s3_key))
        else:
            active_files.append((local_path, s3_key))

    logging.info(f"Active months (always upload): {len(active_files)} files")
    logging.info(f"Immutable months (check R2):  {len(immutable_files)} files")

    files_to_upload = list(active_files)

    # 完結済み月: R2 に存在しないものだけアップロード
    if immutable_files:
        existing_keys = get_existing_keys_in_r2(R2_PREFIX)
        missing = [(lp, sk) for lp, sk in immutable_files if sk not in existing_keys]
        logging.info(f"  → Missing in R2: {len(missing)} files (will upload)")
        files_to_upload.extend(missing)

    return files_to_upload


def upload_parallel(files_to_upload):
    """並列アップロード"""
    if not files_to_upload:
        logging.info("No files to upload.")
        return 0

    logging.info(f"Uploading {len(files_to_upload)} files with {MAX_WORKERS} workers...")

    success_count = 0
    fail_count = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(
                upload_single_file,
                R2_ENDPOINT,
                R2_ACCESS_KEY_ID,
                R2_SECRET_ACCESS_KEY,
                R2_BUCKET_NAME,
                local_path,
                s3_key
            ): s3_key
            for local_path, s3_key in files_to_upload
        }

        for future in as_completed(futures):
            s3_key = futures[future]
            try:
                if future.result():
                    success_count += 1
                    if success_count % 500 == 0:
                        logging.info(f"Progress: {success_count}/{len(files_to_upload)}")
                else:
                    fail_count += 1
                    logging.error(f"Failed: {s3_key}")
            except Exception as e:
                fail_count += 1
                logging.error(f"Error uploading {s3_key}: {e}")

    logging.info(f"✅ Uploaded: {success_count}, ❌ Failed: {fail_count}")
    return success_count


def main():
    logging.info("=" * 60)
    logging.info("UPLOAD INTRADAY 5-MIN DATA TO R2")
    logging.info(f"Today: {date.today()} (immutable threshold: > 60 days before month-end)")
    logging.info("=" * 60)

    if not all([R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME]):
        logging.error("R2 credentials not found in environment variables")
        return False

    all_files = collect_all_files()
    logging.info(f"Total local files: {len(all_files)}")

    if not all_files:
        logging.warning("No local files found. Run 2_export_to_json.py first.")
        return False

    files_to_upload = filter_files_to_upload(all_files)
    upload_parallel(files_to_upload)

    logging.info("=" * 60)
    logging.info("✅ Intraday upload completed")
    logging.info("=" * 60)

    return True


if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)

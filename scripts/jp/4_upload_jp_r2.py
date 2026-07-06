"""
4_upload_jp_r2.py

日本株の年別 JSON を R2 (jp/ 名前空間) へアップロードする。
US の 5_upload_to_r2.py と同じ「過去年は凍結・当年は上書き」ロジック。
安全のため既定はドライラン（--execute で実投入）。

  過去年ファイル: R2 に無ければアップロード（--force-past で強制上書き）
  当年ファイル  : 常に上書き
  metadata      : 常に上書き

使い方:
  python scripts/jp/4_upload_jp_r2.py                 # ドライラン（何を上げるか表示のみ）
  python scripts/jp/4_upload_jp_r2.py --execute       # 実投入
  python scripts/jp/4_upload_jp_r2.py --execute --force-past  # 過去年も上書き（スキーマ変更時）
"""
import os
import sys
import argparse
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.r2 import create_s3_client

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

R2_BUCKET_NAME = os.getenv('R2_BUCKET_NAME')

DATA_FOLDER = "data"
R2_OUTPUT = os.path.join(DATA_FOLDER, "jp", "r2")
MAX_WORKERS = 10
CURRENT_YEAR = datetime.now().year


def get_existing_files_in_r2(prefix):
    s3 = create_s3_client()
    keys = set()
    try:
        paginator = s3.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=R2_BUCKET_NAME, Prefix=prefix):
            for obj in page.get('Contents', []):
                keys.add(obj['Key'])
        logging.info(f"Found {len(keys)} existing files in R2 under '{prefix}'")
    except Exception as e:
        logging.error(f"Error listing R2 objects: {e}")
    finally:
        s3.close()
    return keys


def extract_year_from_path(file_path):
    for part in file_path.split('/'):
        if part.isdigit() and len(part) == 4:
            return int(part)
    return None


def collect_files(local_dir):
    files = []
    for root, _, names in os.walk(local_dir):
        for name in names:
            if not name.endswith('.json'):
                continue
            local_path = os.path.join(root, name)
            s3_key = os.path.relpath(local_path, R2_OUTPUT).replace('\\', '/')
            files.append((local_path, s3_key))
    return files


def upload_single_file(file_path, key, max_retries=3):
    s3 = create_s3_client()
    try:
        for attempt in range(max_retries):
            try:
                s3.upload_file(file_path, R2_BUCKET_NAME, key)
                return True
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                logging.warning(f"Retry {attempt + 1}/{max_retries} for {key}: {e}")
        return False
    finally:
        s3.close()


def plan_uploads(local_dir, s3_prefix, filter_type, force_past):
    all_files = collect_files(local_dir)
    if not all_files:
        return []

    if filter_type == 'always':
        return all_files

    # filter_type == 'year'
    to_upload, past_files = [], []
    for local_path, s3_key in all_files:
        year = extract_year_from_path(s3_key)
        if year is None or year == CURRENT_YEAR:
            to_upload.append((local_path, s3_key))
        else:
            past_files.append((local_path, s3_key))

    if past_files:
        if force_past:
            to_upload.extend(past_files)
            logging.info(f"--force-past: {len(past_files)} 過去年ファイルも上書き対象")
        else:
            existing = get_existing_files_in_r2(s3_prefix)
            missing = [(lp, k) for lp, k in past_files if k not in existing]
            to_upload.extend(missing)
            logging.info(f"過去年: {len(past_files) - len(missing)} 既存 / {len(missing)} 新規")
    return to_upload


def run(local_dir, s3_prefix, filter_type, execute, force_past):
    if not os.path.exists(local_dir):
        logging.warning(f"Directory not found: {local_dir}")
        return 0

    files = plan_uploads(local_dir, s3_prefix, filter_type, force_past)
    if not files:
        logging.info(f"No files to upload in {local_dir}")
        return 0

    if not execute:
        logging.info(f"[DRY-RUN] {len(files)} files would upload from {local_dir}")
        for _, k in files[:5]:
            logging.info(f"    e.g. {k}")
        return len(files)

    logging.info(f"Uploading {len(files)} files from {local_dir} ({MAX_WORKERS} workers)...")
    ok = fail = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(upload_single_file, lp, k): k for lp, k in files}
        for fut in as_completed(futs):
            k = futs[fut]
            try:
                if fut.result():
                    ok += 1
                    if ok % 200 == 0:
                        logging.info(f"  progress: {ok}/{len(files)}")
                else:
                    fail += 1
                    logging.error(f"Failed: {k}")
            except Exception as e:
                fail += 1
                logging.error(f"Error uploading {k}: {e}")
    logging.info(f"✅ Uploaded {ok}, ❌ Failed {fail}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--execute', action='store_true', help='実投入（未指定はドライラン）')
    ap.add_argument('--force-past', action='store_true', help='過去年ファイルも上書き')
    args = ap.parse_args()

    if not R2_BUCKET_NAME:
        logging.error("R2_BUCKET_NAME not set")
        return False

    mode = "EXECUTE" if args.execute else "DRY-RUN"
    logging.info("=" * 60)
    logging.info(f"UPLOAD JP TO R2  [{mode}]  current_year={CURRENT_YEAR}")
    logging.info("=" * 60)

    total = 0
    logging.info("\n[1/3] jp/stocks/daily/core ...")
    total += run(os.path.join(R2_OUTPUT, "jp", "stocks", "daily", "core"),
                 "jp/stocks/daily/core", 'year', args.execute, args.force_past)

    logging.info("\n[2/3] jp/scores ...")
    total += run(os.path.join(R2_OUTPUT, "jp", "scores"),
                 "jp/scores", 'year', args.execute, args.force_past)

    logging.info("\n[3/3] jp/metadata ...")
    total += run(os.path.join(R2_OUTPUT, "jp", "metadata"),
                 "jp/metadata", 'always', args.execute, args.force_past)

    logging.info("=" * 60)
    verb = "uploaded" if args.execute else "would upload"
    logging.info(f"✅ {verb}: {total} files total")
    if not args.execute:
        logging.info("実投入は --execute を付けてください")
    logging.info("=" * 60)
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

"""
cleanup_deprecated_r2.py

廃止した系統のオブジェクトを R2 から削除する（スコープA）。

対象プレフィックス:
  - stocks/daily/indicators/   （indicators 系統の廃止）
  - scores/RRS_scores/         （RRS 廃止）
  - stocks/summary/            （summary 廃止）

安全設計:
  - 既定は dry-run（一覧と件数のみ表示、削除しない）
  - 実削除は --execute を付けたときのみ
  - input() を使わないため CI / workflow_dispatch でも動く

使い方:
  python scripts/maintenance/cleanup_deprecated_r2.py            # dry-run
  python scripts/maintenance/cleanup_deprecated_r2.py --execute  # 実削除
"""
import argparse
import os
import logging
import boto3
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DEPRECATED_PREFIXES = [
    "stocks/daily/indicators/",
    "scores/RRS_scores/",
    "stocks/summary/",
]

def create_s3_client():
    return boto3.client(
        's3',
        endpoint_url=os.environ['R2_ENDPOINT'],
        aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],
        region_name='auto'
    )

def list_keys(s3, bucket, prefix):
    keys = []
    paginator = s3.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get('Contents', []):
            keys.append(obj['Key'])
    return keys

def delete_keys(s3, bucket, keys):
    deleted = 0
    for i in range(0, len(keys), 1000):
        batch = [{'Key': k} for k in keys[i:i + 1000]]
        resp = s3.delete_objects(Bucket=bucket, Delete={'Objects': batch})
        deleted += len(resp.get('Deleted', []))
        logging.info(f"  Deleted {deleted}/{len(keys)}")
    return deleted

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true', help='実際に削除する（未指定は dry-run）')
    args = parser.parse_args()

    required_env = ['R2_ENDPOINT', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET_NAME']
    missing = [e for e in required_env if not os.environ.get(e)]
    if missing:
        logging.error(f"Missing environment variables: {', '.join(missing)}")
        return False

    s3 = create_s3_client()
    bucket = os.environ['R2_BUCKET_NAME']

    mode = "EXECUTE (DELETE)" if args.execute else "DRY-RUN (no deletion)"
    logging.info("=" * 60)
    logging.info(f"CLEANUP DEPRECATED R2 OBJECTS — {mode}")
    logging.info(f"Bucket: {bucket}")
    logging.info("=" * 60)

    grand_total = 0
    grand_deleted = 0

    for prefix in DEPRECATED_PREFIXES:
        logging.info(f"\nScanning: {prefix}")
        keys = list_keys(s3, bucket, prefix)
        grand_total += len(keys)
        logging.info(f"  Found {len(keys)} objects")

        if not keys:
            continue

        if args.execute:
            grand_deleted += delete_keys(s3, bucket, keys)
        else:
            for k in keys[:5]:
                logging.info(f"    e.g. {k}")
            if len(keys) > 5:
                logging.info(f"    ... and {len(keys) - 5} more")

    s3.close()

    logging.info("\n" + "=" * 60)
    if args.execute:
        logging.info(f"✅ Deleted {grand_deleted}/{grand_total} objects")
    else:
        logging.info(f"DRY-RUN: {grand_total} objects would be deleted")
        logging.info("Re-run with --execute to delete.")
    logging.info("=" * 60)
    return True

if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)

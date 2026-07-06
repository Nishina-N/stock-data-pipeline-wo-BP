"""
upload_market_to_r2.py

data/market/r2/market/ 配下の年別統合ファイル + metadata.json を R2 にアップロードする。

格納先:
  market/daily/{year}.json
  market/metadata.json

アップロード方針（core と同じ凍結流儀）:
  - 過去年ファイル … R2 に無い場合のみアップロード（既存は上書きしない）
  - 当年ファイル   … 常に上書き
  - metadata.json  … 常に上書き

安全設計:
  - 既定は dry-run（アップロード予定のみ表示）
  - 実書込は --execute のみ

使い方:
  python scripts/market/upload_market_to_r2.py            # dry-run
  python scripts/market/upload_market_to_r2.py --execute  # 実書込
"""
import os
import sys
import logging
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.r2 import create_s3_client
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DATA_FOLDER = "data"
LOCAL_ROOT = os.path.join(DATA_FOLDER, "market", "r2", "market")
DAILY_DIR = os.path.join(LOCAL_ROOT, "daily")
PREFIX = "market"
CURRENT_YEAR = datetime.now().year


def existing_keys(s3, bucket):
    keys = set()
    p = s3.get_paginator('list_objects_v2')
    for pg in p.paginate(Bucket=bucket, Prefix=f"{PREFIX}/"):
        for o in pg.get('Contents', []):
            keys.add(o['Key'])
    return keys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--execute', action='store_true', help='実際にアップロード（既定はdry-run）')
    ap.add_argument('--force-past', action='store_true',
                    help='過去年ファイルも上書き（シリーズ追加などスキーマ変更の再投入用）')
    args = ap.parse_args()

    if not os.path.isdir(DAILY_DIR):
        logging.error(f"Not found: {DAILY_DIR} (run build_market_by_year.py first)")
        return False

    bucket = os.environ['R2_BUCKET_NAME']
    s3 = create_s3_client()
    try:
        existing = existing_keys(s3, bucket)

        tasks = []  # (local_path, key, reason)

        # 年別ファイル
        for fn in sorted(os.listdir(DAILY_DIR)):
            if not fn.endswith('.json'):
                continue
            year = int(fn[:-5])
            key = f"{PREFIX}/daily/{fn}"
            local = os.path.join(DAILY_DIR, fn)
            if year == CURRENT_YEAR:
                tasks.append((local, key, "current-year overwrite"))
            elif key not in existing:
                tasks.append((local, key, "missing"))
            elif args.force_past:
                tasks.append((local, key, "force-past overwrite"))
            # それ以外の既存の過去年はスキップ（凍結）

        # metadata は常に
        meta_local = os.path.join(LOCAL_ROOT, "metadata.json")
        if os.path.exists(meta_local):
            tasks.append((meta_local, f"{PREFIX}/metadata.json", "always"))

        logging.info(f"Existing under {PREFIX}/: {len(existing)} objects")
        logging.info(f"Planned uploads: {len(tasks)}")
        for _, key, reason in tasks:
            logging.info(f"  {key:32} [{reason}]")

        if not args.execute:
            logging.info("DRY-RUN: 実書込は --execute を付けてください")
            return True

        ok = 0
        for local, key, _ in tasks:
            try:
                s3.upload_file(local, bucket, key)
                ok += 1
            except Exception as e:
                logging.error(f"upload fail {key}: {e}")
        logging.info(f"✅ Uploaded {ok}/{len(tasks)}")
        return True
    finally:
        s3.close()


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

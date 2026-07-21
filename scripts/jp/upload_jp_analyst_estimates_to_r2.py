"""
upload_jp_analyst_estimates_to_r2.py

data/temp_analyst_estimates_jp.json を R2 にアップロードする。
jp/stocks/analyst_estimates/{code}.json （年別パーティション無し、常に上書き）。
"""
import os
import json
import logging
import boto3
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DATA_FOLDER = "data"
TEMP_JSON = os.path.join(DATA_FOLDER, "temp_analyst_estimates_jp.json")
R2_PREFIX = "jp/stocks/analyst_estimates/"
MAX_WORKERS = 10


def upload_one(endpoint, access_key, secret_key, bucket, code, body_bytes):
    s3 = boto3.client('s3', endpoint_url=endpoint, aws_access_key_id=access_key,
                      aws_secret_access_key=secret_key, region_name='auto')
    try:
        s3.put_object(Bucket=bucket, Key=f"{R2_PREFIX}{code}.json",
                      Body=body_bytes, ContentType='application/json')
        return True
    finally:
        s3.close()


def main():
    required_env = ['R2_ENDPOINT', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET_NAME']
    missing = [e for e in required_env if not os.environ.get(e)]
    if missing:
        logging.error(f"Missing environment variables: {', '.join(missing)}")
        return False

    if not os.path.exists(TEMP_JSON):
        logging.error(f"{TEMP_JSON} not found")
        return False

    with open(TEMP_JSON, encoding='utf-8') as f:
        data = json.load(f)
    logging.info(f"Loaded {len(data)} symbols")

    endpoint = os.environ['R2_ENDPOINT']
    access_key = os.environ['R2_ACCESS_KEY_ID']
    secret_key = os.environ['R2_SECRET_ACCESS_KEY']
    bucket = os.environ['R2_BUCKET_NAME']

    success = fail = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(upload_one, endpoint, access_key, secret_key, bucket,
                           code, json.dumps(rec, ensure_ascii=False).encode('utf-8')): code
            for code, rec in data.items()
        }
        for future in as_completed(futures):
            code = futures[future]
            try:
                if future.result():
                    success += 1
                    if success % 200 == 0:
                        logging.info(f"Progress: {success}/{len(data)}")
            except Exception as e:
                fail += 1
                logging.error(f"✗ {code}: {e}")

    logging.info(f"✅ Uploaded {success} files, {fail} failed -> {R2_PREFIX}")
    return True


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)

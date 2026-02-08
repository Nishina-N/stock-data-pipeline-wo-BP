"""
5_upload_to_r2.py

R2へのアップロード（並列処理版）
- stocks/daily/core/{year}/{symbol}.json
- stocks/daily/indicators/standard/{year}/{symbol}.json
- stocks/summary/{date}.json  # 追加
- scores/RS_scores/{category}/{year}.json
- scores/RRS_scores/{category}/{year}.json
- metadata/last-updated.json
"""
import os
import boto3
import logging
from datetime import datetime
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()

# R2設定
R2_ENDPOINT = os.getenv('R2_ENDPOINT')
R2_ACCESS_KEY_ID = os.getenv('R2_ACCESS_KEY_ID')
R2_SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY')
R2_BUCKET_NAME = os.getenv('R2_BUCKET_NAME')

# ローカルディレクトリ
DATA_FOLDER = "data"
R2_OUTPUT = os.path.join(DATA_FOLDER, "daily", "r2")

# 並列処理設定
MAX_WORKERS = 10

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def upload_single_file_with_new_client(endpoint, access_key, secret_key, bucket_name, file_path, key, max_retries=3):
    """各スレッドで新しいS3クライアントを作成してアップロード"""
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
        if s3_client is not None:
            s3_client.close()

def upload_directory_parallel(local_dir, s3_prefix, workers=MAX_WORKERS):
    """ディレクトリ内の全ファイルを並列アップロード"""
    if not os.path.exists(local_dir):
        logging.warning(f"Directory not found: {local_dir}")
        return 0
    
    # アップロード対象ファイルを収集
    files_to_upload = []
    
    for root, dirs, files in os.walk(local_dir):
        for file in files:
            if not file.endswith('.json'):
                continue
            
            local_path = os.path.join(root, file)
            relative_path = os.path.relpath(local_path, R2_OUTPUT)
            s3_key = relative_path.replace('\\', '/')
            
            files_to_upload.append((local_path, s3_key))
    
    if not files_to_upload:
        logging.info(f"No files to upload in {local_dir}")
        return 0
    
    logging.info(f"Uploading {len(files_to_upload)} files from {local_dir} with {workers} workers...")
    
    success_count = 0
    fail_count = 0
    
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                upload_single_file_with_new_client,
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
                result = future.result()
                if result:
                    success_count += 1
                    if success_count % 100 == 0:
                        logging.info(f"Progress: {success_count}/{len(files_to_upload)}")
                else:
                    fail_count += 1
                    logging.error(f"Failed: {s3_key}")
            except Exception as e:
                fail_count += 1
                logging.error(f"Error uploading {s3_key}: {e}")
    
    logging.info(f"✅ Uploaded: {success_count} files, ❌ Failed: {fail_count} files")
    return success_count

def main():
    """メイン処理"""
    logging.info("="*60)
    logging.info("UPLOAD TO R2 (PARALLEL)")
    logging.info("="*60)
    
    if not all([R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME]):
        logging.error("R2 credentials not found in .env")
        return False
    
    total_uploaded = 0
    
    # 1. stocks/daily/core
    logging.info("\n[1/6] Uploading stocks/daily/core...")
    core_dir = os.path.join(R2_OUTPUT, "stocks", "daily", "core")
    total_uploaded += upload_directory_parallel(core_dir, "stocks/daily/core")
    
    # 2. stocks/daily/indicators
    logging.info("\n[2/6] Uploading stocks/daily/indicators...")
    indicators_dir = os.path.join(R2_OUTPUT, "stocks", "daily", "indicators")
    total_uploaded += upload_directory_parallel(indicators_dir, "stocks/daily/indicators")
    
    # 3. stocks/summary (新規追加)
    logging.info("\n[3/6] Uploading stocks/summary...")
    summary_dir = os.path.join(R2_OUTPUT, "stocks", "summary")
    total_uploaded += upload_directory_parallel(summary_dir, "stocks/summary")
    
    # 4. scores
    logging.info("\n[4/6] Uploading scores...")
    scores_dir = os.path.join(R2_OUTPUT, "scores")
    total_uploaded += upload_directory_parallel(scores_dir, "scores")
    
    # 5. metadata
    logging.info("\n[5/6] Uploading metadata...")
    metadata_dir = os.path.join(R2_OUTPUT, "metadata")
    total_uploaded += upload_directory_parallel(metadata_dir, "metadata")
    
    logging.info("="*60)
    logging.info(f"✅ Upload completed: {total_uploaded} files total")
    logging.info("="*60)
    
    return True

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)

"""
5_upload_to_r2.py

R2へのアップロード（list_objects使用で高速化）
"""
import os
import boto3
import logging
from datetime import datetime
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()

R2_ENDPOINT = os.getenv('R2_ENDPOINT')
R2_ACCESS_KEY_ID = os.getenv('R2_ACCESS_KEY_ID')
R2_SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY')
R2_BUCKET_NAME = os.getenv('R2_BUCKET_NAME')

DATA_FOLDER = "data"
R2_OUTPUT = os.path.join(DATA_FOLDER, "daily", "r2")

MAX_WORKERS = 10
CURRENT_YEAR = datetime.now().year

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_s3_client():
    return boto3.client(
        's3',
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,  # ← 修正
        region_name='auto'
    )

def get_existing_files_in_r2(prefix):
    """
    R2の指定プレフィックス配下の全ファイルをlist_objectsで取得（高速）
    """
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

def extract_year_from_path(file_path):
    parts = file_path.split('/')
    for part in parts:
        if part.isdigit() and len(part) == 4:
            return int(part)
    return None

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

def upload_directory_parallel(local_dir, s3_prefix, workers=MAX_WORKERS, filter_type='year', target_date=None):
    if not os.path.exists(local_dir):
        logging.warning(f"Directory not found: {local_dir}")
        return 0
    
    # 全ファイル収集
    all_files = []
    for root, dirs, files in os.walk(local_dir):
        for file in files:
            if not file.endswith('.json'):
                continue
            local_path = os.path.join(root, file)
            relative_path = os.path.relpath(local_path, R2_OUTPUT)
            s3_key = relative_path.replace('\\', '/')
            all_files.append((local_path, s3_key))
    
    if not all_files:
        logging.info(f"No files in {local_dir}")
        return 0
    
    # フィルタリング
    files_to_upload = []
    
    if filter_type == 'always':
        files_to_upload = all_files

    elif filter_type == 'year':
        current_year_files = []
        past_year_files = []
        
        for local_path, s3_key in all_files:
            year = extract_year_from_path(s3_key)
            if year is None or year == CURRENT_YEAR:
                current_year_files.append((local_path, s3_key))
            else:
                past_year_files.append((local_path, s3_key))
        
        # 過去年度ファイルの存在チェック（list_objectsで一括取得）
        if past_year_files:
            logging.info(f"Checking {len(past_year_files)} past year files in R2...")
            existing_keys = get_existing_files_in_r2(s3_prefix)
            
            missing_count = 0
            for local_path, s3_key in past_year_files:
                if s3_key not in existing_keys:
                    current_year_files.append((local_path, s3_key))
                    missing_count += 1
            
            logging.info(f"Found {len(past_year_files) - missing_count} existing, {missing_count} missing")
        
        files_to_upload = current_year_files
    
    if not files_to_upload:
        logging.info(f"No files to upload in {local_dir}")
        return 0
    
    logging.info(f"Uploading {len(files_to_upload)} files from {local_dir} with {workers} workers...")
    
    success_count = 0
    fail_count = 0
    
    with ThreadPoolExecutor(max_workers=workers) as executor:
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
    logging.info("="*60)
    logging.info("UPLOAD TO R2 (PARALLEL + LIST-BASED FILTERING)")
    logging.info(f"Current Year: {CURRENT_YEAR} (force overwrite)")
    logging.info("="*60)
    
    if not all([R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME]):
        logging.error("R2 credentials not found in .env")
        return False
    
    total_uploaded = 0

    logging.info("\n[1/3] Uploading stocks/daily/core...")
    core_dir = os.path.join(R2_OUTPUT, "stocks", "daily", "core")
    total_uploaded += upload_directory_parallel(core_dir, "stocks/daily/core", filter_type='year')

    logging.info("\n[2/3] Uploading scores...")
    scores_dir = os.path.join(R2_OUTPUT, "scores")
    total_uploaded += upload_directory_parallel(scores_dir, "scores", filter_type='year')

    logging.info("\n[3/3] Uploading metadata...")
    metadata_dir = os.path.join(R2_OUTPUT, "metadata")
    total_uploaded += upload_directory_parallel(metadata_dir, "metadata", filter_type='always')
    
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

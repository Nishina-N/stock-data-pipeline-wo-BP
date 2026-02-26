"""
5_upload_all_to_r2.py (Maintenance用)

全データをR2にアップロード（存在しないファイルのみ）
- list_objects使用で高速チェック
- 既存ファイルはスキップ
"""
import os
import boto3
import logging
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()

R2_ENDPOINT = os.getenv('R2_ENDPOINT')
R2_ACCESS_KEY_ID = os.getenv('R2_ACCESS_KEY_ID')
R2_SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY')
R2_BUCKET_NAME = os.getenv('R2_BUCKET_NAME')

DATA_FOLDER = "data"
MAINTENANCE_FOLDER = os.path.join(DATA_FOLDER, "maintenance")
R2_OUTPUT = os.path.join(MAINTENANCE_FOLDER, "r2")

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

def get_existing_files_in_r2(prefix):
    """R2の既存ファイル一覧を取得"""
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
                s3_client.upload_file(file_path, bucket_name, key, 
                                     ExtraArgs={'ContentType': 'application/json'})
                return True
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                logging.warning(f"Retry {attempt + 1}/{max_retries} for {key}: {e}")
        return False
    finally:
        if s3_client:
            s3_client.close()

def upload_directory(local_dir, s3_prefix, workers=MAX_WORKERS):
    """ディレクトリ内のファイルをアップロード（存在チェック付き）"""
    if not os.path.exists(local_dir):
        logging.warning(f"Directory not found: {local_dir}")
        return 0
    
    # ローカルファイル収集
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
    
    # R2の既存ファイルを取得
    logging.info(f"Checking existing files in R2 under '{s3_prefix}'...")
    existing_keys = get_existing_files_in_r2(s3_prefix)
    
    # 存在しないファイルのみアップロード対象
    files_to_upload = [(local_path, s3_key) for local_path, s3_key in all_files 
                       if s3_key not in existing_keys]
    
    if not files_to_upload:
        logging.info(f"All {len(all_files)} files already exist in R2. Nothing to upload.")
        return 0
    
    logging.info(f"Uploading {len(files_to_upload)}/{len(all_files)} files (skipping {len(all_files) - len(files_to_upload)} existing)...")
    
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
    logging.info("MAINTENANCE: UPLOAD ALL TO R2 (SKIP EXISTING)")
    logging.info("="*60)
    
    if not all([R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME]):
        logging.error("R2 credentials not found in .env")
        return False
    
    total_uploaded = 0
    
    # Individual RS
    logging.info("\n[1/9] Uploading Individual RS...")
    total_uploaded += upload_directory(
        os.path.join(R2_OUTPUT, "scores", "RS_scores", "individual"),
        "scores/RS_scores/individual"
    )
    
    # Individual RRS
    logging.info("\n[2/9] Uploading Individual RRS...")
    total_uploaded += upload_directory(
        os.path.join(R2_OUTPUT, "scores", "RRS_scores", "individual"),
        "scores/RRS_scores/individual"
    )
    
    # Sector RS
    logging.info("\n[3/9] Uploading Sector RS...")
    total_uploaded += upload_directory(
        os.path.join(R2_OUTPUT, "scores", "RS_scores", "sector"),
        "scores/RS_scores/sector"
    )
    
    # Sector RRS
    logging.info("\n[4/9] Uploading Sector RRS...")
    total_uploaded += upload_directory(
        os.path.join(R2_OUTPUT, "scores", "RRS_scores", "sector"),
        "scores/RRS_scores/sector"
    )
    
    # Industry RS
    logging.info("\n[5/9] Uploading Industry RS...")
    total_uploaded += upload_directory(
        os.path.join(R2_OUTPUT, "scores", "RS_scores", "industry"),
        "scores/RS_scores/industry"
    )
    
    # Industry RRS
    logging.info("\n[6/9] Uploading Industry RRS...")
    total_uploaded += upload_directory(
        os.path.join(R2_OUTPUT, "scores", "RRS_scores", "industry"),
        "scores/RRS_scores/industry"
    )
    
    
    logging.info("="*60)
    logging.info(f"✅ Total uploaded: {total_uploaded} files")
    logging.info("="*60)
    
    return True

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)

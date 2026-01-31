"""
5_upload_to_r2.py

data/r2/ 配下のJSONファイルをCloudflare R2にアップロード（並列版）
ThreadPoolExecutorで高速化
"""
import boto3
import os
from pathlib import Path
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

DATA_FOLDER = "data"
R2_OUTPUT = os.path.join(DATA_FOLDER, "r2")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def upload_single_file(s3_client, bucket_name, file_path, key):
    """
    単一ファイルをR2にアップロード
    
    Returns:
        tuple: (key, success, error_message)
    """
    try:
        with open(file_path, 'rb') as f:
            s3_client.put_object(
                Bucket=bucket_name,
                Key=key,
                Body=f,
                ContentType='application/json',
                CacheControl='public, max-age=3600'
            )
        return key, True, None
    except Exception as e:
        return key, False, str(e)

def upload_to_r2_parallel(max_workers=20):
    """
    data/r2/ 配下の全JSONファイルをR2に並列アップロード
    
    Args:
        max_workers: 並列度（デフォルト: 20）
    """
    # 環境変数確認
    required_env = ['R2_ENDPOINT', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET_NAME']
    missing = [env for env in required_env if not os.environ.get(env)]
    
    if missing:
        raise ValueError(f"Missing environment variables: {', '.join(missing)}")
    
    # S3互換クライアント作成
    s3 = boto3.client(
        's3',
        endpoint_url=os.environ['R2_ENDPOINT'],
        aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],
        region_name='auto'
    )
    
    bucket_name = os.environ['R2_BUCKET_NAME']
    r2_dir = Path(R2_OUTPUT)
    
    if not r2_dir.exists():
        raise FileNotFoundError(f"{r2_dir} does not exist")
    
    # 全JSONファイルをリストアップ
    json_files = list(r2_dir.glob('**/*.json'))
    csv_files = list(r2_dir.glob('**/*.csv'))
    all_files = json_files + csv_files
    
    total_files = len(all_files)
    
    if total_files == 0:
        logging.warning("No files to upload")
        return False
    
    logging.info(f"Found {total_files} files to upload")
    logging.info(f"Using {max_workers} parallel workers")
    
    uploaded_count = 0
    failed_count = 0
    failed_files = []
    
    start_time = time.time()
    
    # ThreadPoolExecutorで並列アップロード
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 全ファイルのアップロードタスクを投入
        future_to_file = {}
        
        for file_path in all_files:
            # R2のキー: stocks/daily/core/AAPL.json
            relative_path = file_path.relative_to(r2_dir)
            key = str(relative_path).replace('\\', '/')  # Windows対応
            
            future = executor.submit(upload_single_file, s3, bucket_name, file_path, key)
            future_to_file[future] = (file_path, key)
        
        # 完了したタスクから順次処理
        for i, future in enumerate(as_completed(future_to_file), 1):
            file_path, key = future_to_file[future]
            
            try:
                result_key, success, error_msg = future.result()
                
                if success:
                    uploaded_count += 1
                else:
                    failed_count += 1
                    failed_files.append((result_key, error_msg))
                
                # 進捗表示（100件ごと、または最後）
                if i % 100 == 0 or i == total_files:
                    elapsed = time.time() - start_time
                    rate = i / elapsed if elapsed > 0 else 0
                    remaining = (total_files - i) / rate if rate > 0 else 0
                    
                    logging.info(
                        f"Progress: {i}/{total_files} ({i/total_files*100:.1f}%) - "
                        f"Speed: {rate:.1f} files/sec, ETA: {remaining:.1f}s"
                    )
            
            except Exception as e:
                logging.error(f"Unexpected error for {key}: {e}")
                failed_count += 1
                failed_files.append((key, str(e)))
    
    elapsed = time.time() - start_time
    
    # サマリー表示
    logging.info(f"\n{'='*60}")
    logging.info("UPLOAD SUMMARY")
    logging.info(f"{'='*60}")
    logging.info(f"✅ Uploaded: {uploaded_count}/{total_files} files")
    logging.info(f"⏱️  Total time: {elapsed:.1f}s")
    logging.info(f"🚀 Speed: {total_files/elapsed:.1f} files/sec")
    
    if failed_count > 0:
        logging.warning(f"❌ Failed: {failed_count} files")
        logging.warning(f"Failed files (first 10):")
        for key, error in failed_files[:10]:
            logging.warning(f"  - {key}: {error}")
        if len(failed_files) > 10:
            logging.warning(f"  ... and {len(failed_files) - 10} more")
    
    logging.info(f"Bucket: {bucket_name}")
    logging.info(f"Endpoint: {os.environ['R2_ENDPOINT']}")
    logging.info(f"{'='*60}\n")
    
    return failed_count == 0

def main():
    """R2アップロードメイン処理"""
    logging.info("="*60)
    logging.info("UPLOAD TO CLOUDFLARE R2 (PARALLEL)")
    logging.info("="*60)
    
    try:
        success = upload_to_r2_parallel(max_workers=20)
        
        if success:
            logging.info("✅ All files uploaded successfully!")
            return True
        else:
            logging.warning("⚠️  Upload completed with some failures")
            return False
            
    except Exception as e:
        logging.error(f"Upload failed: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)

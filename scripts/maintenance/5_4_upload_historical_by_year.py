"""
5_4_upload_historical_by_year.py

指定年の historical data を R2 にアップロード
- stocks/daily/core/{year}/*.json
- stocks/daily/indicators/standard/{year}/*.json

Usage:
  python scripts/maintenance/5_4_upload_historical_by_year.py --year 2024
"""
import boto3
import os
import argparse
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from dotenv import load_dotenv

# .envファイルを読み込む
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
load_dotenv(dotenv_path=ENV_PATH)

DATA_FOLDER = "data"
MAINTENANCE_FOLDER = os.path.join(DATA_FOLDER, "maintenance")
R2_OUTPUT = os.path.join(MAINTENANCE_FOLDER, "r2")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def upload_single_file(s3_client, bucket_name, file_path, key, max_retries=3):
    """
    単一ファイルをR2にアップロード（リトライ機構付き）
    
    Returns:
        tuple: (key, success, error_message)
    """
    for attempt in range(max_retries):
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
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
            else:
                return key, False, str(e)

def upload_year_to_r2(year, max_workers=5):
    """
    指定年のデータをR2にアップロード
    
    Args:
        year: 年（例: 2024）
        max_workers: 並列度（デフォルト: 5、接続エラー回避）
    
    Returns:
        bool: 成功した場合 True
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
    
    # 指定年のファイルをリストアップ
    logging.info(f"Scanning files for year {year}...")
    
    year_files = []
    
    # core/{year}/*.json
    core_dir = r2_dir / "stocks" / "daily" / "core" / str(year)
    if core_dir.exists():
        year_files.extend(list(core_dir.glob("*.json")))
    
    # indicators/standard/{year}/*.json
    indicators_dir = r2_dir / "stocks" / "daily" / "indicators" / "standard" / str(year)
    if indicators_dir.exists():
        year_files.extend(list(indicators_dir.glob("*.json")))
    
    total_files = len(year_files)
    
    if total_files == 0:
        logging.warning(f"No files found for year {year}")
        return False
    
    logging.info(f"Found {total_files} files for year {year}")
    
    # アップロード対象を準備
    files_to_upload = []
    for file_path in year_files:
        relative_path = file_path.relative_to(r2_dir)
        key = str(relative_path).replace('\\', '/')
        files_to_upload.append((file_path, key))
    
    logging.info(f"\n{'='*60}")
    logging.info(f"UPLOAD PLAN FOR YEAR {year}")
    logging.info(f"{'='*60}")
    logging.info(f"Files to upload: {total_files}")
    logging.info(f"Parallel workers: {max_workers}")
    logging.info(f"{'='*60}\n")
    
    uploaded_count = 0
    failed_count = 0
    failed_files = []
    
    start_time = time.time()
    
    # ThreadPoolExecutorで並列アップロード
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {}
        
        for file_path, key in files_to_upload:
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
                        f"Progress: [{i}/{total_files}] ({i/total_files*100:.1f}%) - "
                        f"Speed: {rate:.1f} files/sec, ETA: {remaining:.1f}s"
                    )
            
            except Exception as e:
                logging.error(f"Unexpected error for {key}: {e}")
                failed_count += 1
                failed_files.append((key, str(e)))
    
    elapsed = time.time() - start_time
    
    # サマリー表示
    logging.info(f"\n{'='*60}")
    logging.info(f"UPLOAD SUMMARY FOR YEAR {year}")
    logging.info(f"{'='*60}")
    logging.info(f"✅ Uploaded: {uploaded_count}/{total_files} files")
    logging.info(f"⏱️  Total time: {elapsed:.1f}s")
    logging.info(f"🚀 Speed: {total_files/elapsed:.1f} files/sec")
    
    if failed_count > 0:
        logging.warning(f"\n❌ Failed: {failed_count} files")
        logging.warning(f"Failed files (first 10):")
        for key, error in failed_files[:10]:
            logging.warning(f"  - {key}: {error}")
        if len(failed_files) > 10:
            logging.warning(f"  ... and {len(failed_files) - 10} more")
    
    logging.info(f"\nBucket: {bucket_name}")
    logging.info(f"Endpoint: {os.environ['R2_ENDPOINT']}")
    logging.info(f"{'='*60}\n")
    
    return failed_count == 0

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--year', type=int, required=True, help='Year to upload (e.g., 2024)')
    parser.add_argument('--workers', type=int, default=20, help='Number of parallel workers (default: 5)')
    args = parser.parse_args()
    
    year = args.year
    
    logging.info("="*60)
    logging.info(f"UPLOAD HISTORICAL DATA FOR YEAR {year}")
    logging.info("="*60)
    
    try:
        success = upload_year_to_r2(year, max_workers=args.workers)
        
        if success:
            logging.info(f"✅ All files for year {year} uploaded successfully!")
            return True
        else:
            logging.warning(f"⚠️  Upload for year {year} completed with some failures")
            return False
    
    except Exception as e:
        logging.error(f"Upload failed for year {year}: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)
"""
5_upload_to_r2.py

data/daily/r2/ 配下のJSONファイルをCloudflare R2にアップロード（並列版 + メモリリーク対策）
- R2のファイルリストを一括取得してメモリ上で比較
- 過去年度: R2に既存の場合はスキップ
- 当年: 常に上書きアップロード
- ThreadPoolExecutorで高速化
- メモリリーク対策: 各スレッドで新しいS3クライアント作成
"""
import boto3
import os
from pathlib import Path
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from datetime import datetime
from dotenv import load_dotenv

# .envファイルを読み込む（プロジェクトルートの.env）
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
load_dotenv(dotenv_path=ENV_PATH)

DATA_FOLDER = "data"
R2_OUTPUT = os.path.join(DATA_FOLDER, "daily", "r2")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_existing_files_in_r2(endpoint, access_key, secret_key, bucket_name):
    """
    R2バケット内の全ファイルのキーをセットで取得（一括）
    
    Returns:
        set: R2に存在するファイルキーのセット
    """
    logging.info("Fetching existing files list from R2...")
    start_time = time.time()
    
    existing_files = set()
    s3_client = None
    
    try:
        s3_client = boto3.client(
            's3',
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name='auto'
        )
        
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=bucket_name)
        
        for page in pages:
            if 'Contents' in page:
                for obj in page['Contents']:
                    existing_files.add(obj['Key'])
        
        elapsed = time.time() - start_time
        logging.info(f"✅ Found {len(existing_files)} existing files in R2 ({elapsed:.1f}s)")
        
    except Exception as e:
        logging.warning(f"Failed to fetch existing files: {e}")
        return set()
    
    finally:
        if s3_client is not None:
            try:
                s3_client.close()
            except:
                pass
    
    return existing_files

def should_upload_file(key, current_year, existing_files):
    """
    アップロードすべきか判定（高速版）
    
    - 当年ディレクトリ: 常にアップロード
    - metadata: 常にアップロード
    - 過去年度: R2に存在しない場合のみアップロード
    
    Args:
        key: R2のオブジェクトキー
        current_year: 現在の年
        existing_files: R2に存在するファイルキーのセット
    
    Returns:
        bool: アップロードすべき場合 True
    """
    # 当年ディレクトリ（stocks/daily/core/2026/, scores/RS_scores/individual/2026.json等）
    if f'/{current_year}/' in key or f'/{current_year}.json' in key:
        return True
    
    # metadata は常にアップロード
    if key.startswith('metadata/'):
        return True
    
    # 過去年度: セット内検索（O(1)）
    return key not in existing_files

def upload_single_file_with_new_client(endpoint, access_key, secret_key, bucket_name, file_path, key, max_retries=3):
    """
    単一ファイルをR2にアップロード（各スレッドで新しいクライアント作成）
    メモリリーク対策: 各アップロードで新しいS3クライアントを作成・破棄
    
    Returns:
        tuple: (key, success, error_message)
    """
    s3_client = None
    
    try:
        # ★ 各スレッドで新しいクライアントを作成
        s3_client = boto3.client(
            's3',
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name='auto'
        )
        
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
    
    finally:
        # ★ 明示的にクライアントをクローズ（メモリ解放）
        if s3_client is not None:
            try:
                s3_client.close()
            except:
                pass

def upload_to_r2_parallel(max_workers=20):
    """
    data/daily/r2/ 配下の全JSONファイルをR2に並列アップロード
    過去年度は既存チェックでスキップ（最適化版 + メモリリーク対策）
    
    Args:
        max_workers: 並列度（デフォルト: 20）
    """
    # 環境変数確認
    required_env = ['R2_ENDPOINT', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET_NAME']
    missing = [env for env in required_env if not os.environ.get(env)]
    
    if missing:
        raise ValueError(f"Missing environment variables: {', '.join(missing)}")
    
    # ★ 認証情報を変数に保存（各スレッドで使用）
    endpoint = os.environ['R2_ENDPOINT']
    access_key = os.environ['R2_ACCESS_KEY_ID']
    secret_key = os.environ['R2_SECRET_ACCESS_KEY']
    bucket_name = os.environ['R2_BUCKET_NAME']
    
    r2_dir = Path(R2_OUTPUT)
    
    if not r2_dir.exists():
        raise FileNotFoundError(f"{r2_dir} does not exist")
    
    # 全JSONファイルをリストアップ
    logging.info("Scanning local files...")
    json_files = list(r2_dir.glob('**/*.json'))
    csv_files = list(r2_dir.glob('**/*.csv'))
    all_files = json_files + csv_files
    
    total_files = len(all_files)
    
    if total_files == 0:
        logging.warning("No files to upload")
        return False
    
    logging.info(f"Found {total_files} local files")
    
    # 現在の年を取得
    current_year = datetime.now().year
    
    # R2の既存ファイルリストを一括取得
    existing_files = get_existing_files_in_r2(endpoint, access_key, secret_key, bucket_name)
    
    # アップロード対象をフィルタリング
    logging.info(f"Filtering files to upload (current year: {current_year})...")
    files_to_upload = []
    skipped_count = 0
    
    for file_path in all_files:
        # R2のキー: stocks/daily/core/2026/AAPL.json
        relative_path = file_path.relative_to(r2_dir)
        key = str(relative_path).replace('\\', '/')  # Windows対応
        
        if should_upload_file(key, current_year, existing_files):
            files_to_upload.append((file_path, key))
        else:
            skipped_count += 1
    
    upload_count = len(files_to_upload)
    
    logging.info(f"\n{'='*60}")
    logging.info("UPLOAD PLAN")
    logging.info(f"{'='*60}")
    logging.info(f"Total files found: {total_files}")
    logging.info(f"Files to upload: {upload_count}")
    logging.info(f"Files to skip: {skipped_count} (already exist in R2)")
    logging.info(f"Parallel workers: {max_workers}")
    logging.info(f"{'='*60}\n")
    
    if upload_count == 0:
        logging.info("✅ No files need upload. All files are up to date.")
        return True
    
    uploaded_count = 0
    failed_count = 0
    failed_files = []
    
    start_time = time.time()
    
    # ThreadPoolExecutorで並列アップロード
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {}
        
        for file_path, key in files_to_upload:
            # ★ 認証情報を各スレッドに渡す
            future = executor.submit(
                upload_single_file_with_new_client,
                endpoint, access_key, secret_key, bucket_name,
                file_path, key
            )
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
                if i % 100 == 0 or i == upload_count:
                    elapsed = time.time() - start_time
                    rate = i / elapsed if elapsed > 0 else 0
                    remaining = (upload_count - i) / rate if rate > 0 else 0
                    
                    logging.info(
                        f"Progress: {i}/{upload_count} ({i/upload_count*100:.1f}%) - "
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
    logging.info(f"✅ Uploaded: {uploaded_count}/{upload_count} files")
    logging.info(f"⏱️  Total time: {elapsed:.1f}s")
    logging.info(f"🚀 Speed: {upload_count/elapsed:.1f} files/sec")
    
    if skipped_count > 0:
        logging.info(f"⏭️  Skipped: {skipped_count} files (already in R2)")
    
    if failed_count > 0:
        logging.warning(f"\n❌ Failed: {failed_count} files")
        logging.warning(f"Failed files (first 10):")
        for key, error in failed_files[:10]:
            logging.warning(f"  - {key}: {error}")
        if len(failed_files) > 10:
            logging.warning(f"  ... and {len(failed_files) - 10} more")
    
    logging.info(f"\nBucket: {bucket_name}")
    logging.info(f"Endpoint: {endpoint}")
    logging.info(f"{'='*60}\n")
    
    return failed_count == 0

def main():
    """R2アップロードメイン処理"""
    logging.info("="*60)
    logging.info("UPLOAD TO CLOUDFLARE R2 (PARALLEL + SMART SKIP)")
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
"""
upload_sector_industry_to_r2.py

Sector/Industry RS/RRS JSONファイルをR2にアップロード（並列処理版）
入力: data/maintenance/r2/scores/RS_scores/sector/{year}.json
      data/maintenance/r2/scores/RS_scores/industry/{year}.json
      data/maintenance/r2/scores/RRS_scores/sector/{year}.json
      data/maintenance/r2/scores/RRS_scores/industry/{year}.json
出力: R2 bucket
"""
import os
import sys
import boto3
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

# ★ .envファイルのパスを明示的に指定
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # stock-data-pipeline/
ENV_PATH = PROJECT_ROOT / '.env'

# .envファイルを読み込み
load_dotenv(dotenv_path=ENV_PATH)

DATA_FOLDER = "data"
MAINTENANCE_FOLDER = os.path.join(DATA_FOLDER, "maintenance")
R2_OUTPUT = os.path.join(MAINTENANCE_FOLDER, "r2")

# アップロード対象ディレクトリ
UPLOAD_DIRS = [
    ("scores/RS_scores/sector", os.path.join(R2_OUTPUT, "scores", "RS_scores", "sector")),
    ("scores/RS_scores/industry", os.path.join(R2_OUTPUT, "scores", "RS_scores", "industry")),
    ("scores/RRS_scores/sector", os.path.join(R2_OUTPUT, "scores", "RRS_scores", "sector")),
    ("scores/RRS_scores/industry", os.path.join(R2_OUTPUT, "scores", "RRS_scores", "industry")),
]

# R2設定（.envから取得）
R2_ENDPOINT = os.getenv('R2_ENDPOINT')
R2_ACCESS_KEY_ID = os.getenv('R2_ACCESS_KEY_ID')
R2_SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY')
R2_BUCKET_NAME = os.getenv('R2_BUCKET_NAME', 'stock-data')

# 並列処理設定
MAX_WORKERS = 5

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_s3_client():
    """S3クライアントを作成"""
    # デバッグ: 環境変数の確認
    if not all([R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY]):
        logging.error(f"Missing credentials:")
        logging.error(f"  .env path: {ENV_PATH}")
        logging.error(f"  .env exists: {ENV_PATH.exists()}")
        logging.error(f"  R2_ENDPOINT: {R2_ENDPOINT}")
        logging.error(f"  R2_ACCESS_KEY_ID: {'***' if R2_ACCESS_KEY_ID else 'None'}")
        logging.error(f"  R2_SECRET_ACCESS_KEY: {'***' if R2_SECRET_ACCESS_KEY else 'None'}")
        return None
    
    try:
        client = boto3.client(
            's3',
            endpoint_url=R2_ENDPOINT,
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            region_name='auto'
        )
        return client
    except Exception as e:
        logging.error(f"Failed to create S3 client: {e}")
        return None

def upload_file_to_r2(file_path, r2_key, max_retries=3):
    """
    1つのファイルをR2にアップロード（リトライ付き）
    
    Args:
        file_path: ローカルファイルパス
        r2_key: R2上のキー
        max_retries: 最大リトライ回数
    
    Returns:
        tuple: (success: bool, r2_key: str, error: str or None)
    """
    import time
    
    for attempt in range(max_retries):
        try:
            # 各試行ごとに新しいクライアントを作成
            s3_client = create_s3_client()
            
            if s3_client is None:
                return False, r2_key, "Failed to create S3 client"
            
            s3_client.upload_file(
                str(file_path),
                R2_BUCKET_NAME,
                r2_key,
                ExtraArgs={'ContentType': 'application/json'}
            )
            
            return True, r2_key, None
            
        except Exception as e:
            if attempt < max_retries - 1:
                # リトライ（1秒待機）
                time.sleep(1)
                continue
            else:
                # 最後の試行も失敗
                return False, r2_key, str(e)
    
    return False, r2_key, "Unknown error"

def upload_to_r2_parallel(local_dir, r2_prefix, max_workers=MAX_WORKERS):
    """
    ローカルディレクトリのファイルをR2に並列アップロード
    
    Args:
        local_dir: ローカルディレクトリパス
        r2_prefix: R2のプレフィックス
        max_workers: 並列数
    
    Returns:
        tuple: (uploaded_count, failed_count)
    """
    # アップロード対象ファイルを取得
    files = list(Path(local_dir).glob('*.json'))
    
    if not files:
        logging.warning(f"No JSON files found in {local_dir}")
        return 0, 0
    
    logging.info(f"Uploading {len(files)} files to {r2_prefix} with {max_workers} workers...")
    
    # アップロードタスクを準備
    tasks = []
    for file_path in files:
        r2_key = f"{r2_prefix}/{file_path.name}"
        tasks.append((file_path, r2_key))
    
    # 並列アップロード
    uploaded_count = 0
    failed_count = 0
    failed_files = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # タスクを投入
        future_to_task = {
            executor.submit(upload_file_to_r2, file_path, r2_key): (file_path, r2_key)
            for file_path, r2_key in tasks
        }
        
        # 結果を処理
        for future in as_completed(future_to_task):
            file_path, r2_key = future_to_task[future]
            
            try:
                success, uploaded_key, error = future.result()
                
                if success:
                    uploaded_count += 1
                    logging.info(f"  ✓ [{uploaded_count}/{len(files)}] Uploaded: {uploaded_key}")
                else:
                    failed_count += 1
                    failed_files.append((uploaded_key, error))
                    logging.error(f"  ✗ Failed: {uploaded_key} - {error}")
                    
            except Exception as e:
                failed_count += 1
                failed_files.append((r2_key, str(e)))
                logging.error(f"  ✗ Exception: {r2_key} - {e}")
    
    if failed_files:
        logging.warning(f"\nFailed files in {r2_prefix}:")
        for key, error in failed_files[:5]:  # 最大5件表示
            logging.warning(f"  - {key}: {error}")
        if len(failed_files) > 5:
            logging.warning(f"  ... and {len(failed_files) - 5} more")
    
    return uploaded_count, failed_count

def main():
    """メイン処理"""
    logging.info("="*60)
    logging.info("UPLOAD SECTOR/INDUSTRY TO R2 (PARALLEL)")
    logging.info("="*60)
    
    # .envファイルチェック
    if not all([R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY]):
        logging.error("R2 credentials not found in .env file")
        logging.error(f"  .env path: {ENV_PATH}")
        logging.error(f"  .env exists: {ENV_PATH.exists()}")
        logging.error("Required: R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY")
        return False
    
    # 各ディレクトリをアップロード
    total_uploaded = 0
    total_failed = 0
    
    for r2_prefix, local_dir in UPLOAD_DIRS:
        if not os.path.exists(local_dir):
            logging.warning(f"Directory not found: {local_dir}")
            continue
        
        logging.info(f"\n--- {r2_prefix} ---")
        uploaded, failed = upload_to_r2_parallel(local_dir, r2_prefix, max_workers=MAX_WORKERS)
        total_uploaded += uploaded
        total_failed += failed
    
    # 統計情報
    logging.info(f"\n{'='*60}")
    logging.info(f"Upload Summary (All)")
    logging.info(f"{'='*60}")
    logging.info(f"Total uploaded: {total_uploaded}")
    logging.info(f"Total failed: {total_failed}")
    logging.info(f"{'='*60}")
    
    logging.info("="*60)
    logging.info("✅ UPLOAD COMPLETED!")
    logging.info("="*60)
    logging.info("\nNext steps:")
    logging.info("1. Delete local files:")
    logging.info(f"   rm data/maintenance/temp_sector_*.pkl")
    logging.info(f"   rm data/maintenance/temp_industry_*.pkl")
    logging.info(f"   rm -r data/maintenance/r2/scores/")
    
    return True

if __name__ == "__main__":
    if main():
        sys.exit(0)
    else:
        sys.exit(1)
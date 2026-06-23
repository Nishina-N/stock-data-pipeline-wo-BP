"""
0_download_target_stocks.py

R2からtarget_stocks_latest.csvをダウンロード
存在しない場合は1_fetch_target_stocks.pyを実行
"""
import os
import logging
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.r2 import create_s3_client

# .envファイルを読み込む
load_dotenv()

DATA_FOLDER = "data"
TARGET_STOCKS_CSV = os.path.join(DATA_FOLDER, "target_stocks_latest.csv")
R2_KEY = "metadata/target_stocks_latest.csv"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def download_from_r2():
    """R2からtarget_stocks_latest.csvをダウンロード"""
    
    # 環境変数確認
    required_env = ['R2_ENDPOINT', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET_NAME']
    missing = [env for env in required_env if not os.environ.get(env)]
    
    if missing:
        logging.error(f"Missing environment variables: {', '.join(missing)}")
        return False
    
    # S3互換クライアント作成
    s3 = create_s3_client()
    
    bucket_name = os.environ['R2_BUCKET_NAME']
    
    try:
        logging.info(f"Checking R2 for {R2_KEY}...")
        
        # R2からダウンロード
        s3.download_file(bucket_name, R2_KEY, TARGET_STOCKS_CSV)
        
        file_size_kb = os.path.getsize(TARGET_STOCKS_CSV) / 1024
        
        logging.info(f"\n{'='*60}")
        logging.info("✅ TARGET STOCKS DOWNLOADED FROM R2")
        logging.info(f"{'='*60}")
        logging.info(f"File: {TARGET_STOCKS_CSV}")
        logging.info(f"Size: {file_size_kb:.2f} KB")
        logging.info(f"{'='*60}\n")
        
        return True
    
    except s3.exceptions.NoSuchKey:
        logging.warning(f"⚠️  {R2_KEY} not found in R2")
        return False
    
    except Exception as e:
        logging.error(f"Error downloading from R2: {e}")
        return False

def fetch_target_stocks():
    """1_fetch_target_stocks.pyを実行"""
    logging.info("Fetching target stocks from FMP API...")
    
    import subprocess
    result = subprocess.run(
        [sys.executable, 'scripts/daily/1_fetch_target_stocks.py'],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        logging.info("✅ Target stocks fetched successfully")
        return True
    else:
        logging.error("❌ Failed to fetch target stocks")
        logging.error(result.stderr)
        return False

def main():
    """メイン処理"""
    logging.info("="*60)
    logging.info("GET TARGET STOCKS")
    logging.info("="*60)
    
    # まずR2からダウンロードを試みる
    if download_from_r2():
        logging.info("Using target stocks from R2 (skipping FMP API)")
        return True
    
    # R2に存在しない場合はFMP APIから取得
    logging.info("Target stocks not found in R2, fetching from FMP API...")
    
    if fetch_target_stocks():
        logging.info("✅ Target stocks ready")
        return True
    else:
        logging.error("❌ Failed to get target stocks")
        return False

if __name__ == "__main__":
    if main():
        sys.exit(0)
    else:
        sys.exit(1)

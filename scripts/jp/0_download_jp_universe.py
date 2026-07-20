"""
0_download_jp_universe.py

R2からtarget_stocks_jp_latest.csvをダウンロード（US の 0_download_target_stocks.py 相当）。
存在しない場合は build_jp_universe.py --execute を実行してJPXから再構築する。

日次自動更新（GitHub Actions）は毎回チェックアウトが空なので、フェッチ前にこれで
ユニバースCSVを用意する。
"""
import os
import sys
import logging
import subprocess
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.r2 import create_s3_client

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DATA_FOLDER = "data"
JP_CSV = os.path.join(DATA_FOLDER, "target_stocks_jp_latest.csv")
R2_KEY = "jp/metadata/target_stocks_jp_latest.csv"


def download_from_r2():
    required_env = ['R2_ENDPOINT', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET_NAME']
    missing = [e for e in required_env if not os.environ.get(e)]
    if missing:
        logging.error(f"Missing environment variables: {', '.join(missing)}")
        return False

    s3 = create_s3_client()
    bucket_name = os.environ['R2_BUCKET_NAME']
    os.makedirs(DATA_FOLDER, exist_ok=True)
    try:
        logging.info(f"Checking R2 for {R2_KEY}...")
        s3.download_file(bucket_name, R2_KEY, JP_CSV)
        size_kb = os.path.getsize(JP_CSV) / 1024
        logging.info(f"✅ Downloaded {R2_KEY} ({size_kb:.1f} KB)")
        return True
    except s3.exceptions.NoSuchKey:
        logging.warning(f"⚠️ {R2_KEY} not found in R2")
        return False
    except Exception as e:
        logging.error(f"Error downloading from R2: {e}")
        return False
    finally:
        s3.close()


def build_universe():
    logging.info("Building JP universe from JPX (build_jp_universe.py --execute)...")
    result = subprocess.run(
        [sys.executable, 'scripts/jp/build_jp_universe.py', '--execute'],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        logging.info("✅ JP universe built successfully")
        return True
    logging.error("❌ Failed to build JP universe")
    logging.error(result.stderr)
    return False


def main():
    logging.info("=" * 60)
    logging.info("GET JP TARGET STOCKS")
    logging.info("=" * 60)

    if download_from_r2():
        logging.info("Using JP universe from R2 (skipping JPX rebuild)")
        return True

    logging.info("Not found in R2, building from JPX...")
    return build_universe()


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

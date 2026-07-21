"""
fetch_shares_float.py

FMP stable `shares-float` から浮動株情報（freeFloat/floatShares/outstandingShares）を
取得する。SEC提出書類ベースの最新スナップショットのみ（過去時系列は無い）。

年別パーティションはせず、銘柄ごとに1ファイルの現在値スナップショット（取得のたびに上書き）。

出力: data/temp_shares_float.json
  {symbol: {ticker, date, freeFloat, floatShares, outstandingShares, source, lastUpdated}}

使い方:
  python scripts/monthly/fetch_shares_float.py --limit 30   # 少数ドライラン
  python scripts/monthly/fetch_shares_float.py              # 全件
"""
import os
import argparse
import requests
import json
import logging
from datetime import datetime
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time

load_dotenv()

API_KEY = os.getenv('FMP_API_KEY')
BASE_URL = "https://financialmodelingprep.com/stable"

DATA_FOLDER = "data"
TARGET_STOCKS_CSV = os.path.join(DATA_FOLDER, "target_stocks_latest.csv")
TEMP_JSON = os.path.join(DATA_FOLDER, "temp_shares_float.json")

MAX_WORKERS = 3
REQUEST_DELAY = 0.5

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def create_session():
    session = requests.Session()
    retry_strategy = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=20)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


SESSION = create_session()


def fetch_one(symbol, session=None):
    if session is None:
        session = SESSION
    url = f"{BASE_URL}/shares-float"
    params = {'symbol': symbol, 'apikey': API_KEY}
    try:
        r = session.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list) or not data:
            return None
        item = data[0]
        if REQUEST_DELAY:
            time.sleep(REQUEST_DELAY)
        return {
            'ticker': symbol,
            'date': item.get('date'),
            'freeFloat': item.get('freeFloat'),
            'floatShares': item.get('floatShares'),
            'outstandingShares': item.get('outstandingShares'),
            'source': item.get('source'),
            'lastUpdated': datetime.now().isoformat(),
        }
    except Exception:
        return None


def load_target_stocks():
    if not os.path.exists(TARGET_STOCKS_CSV):
        logging.error(f"Target stocks file not found: {TARGET_STOCKS_CSV}")
        return []
    import pandas as pd
    df = pd.read_csv(TARGET_STOCKS_CSV)
    return df['Symbol'].tolist()


def main():
    global MAX_WORKERS, REQUEST_DELAY
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=None, help='先頭N銘柄だけ取得（ドライラン用）')
    parser.add_argument('--workers', type=int, default=MAX_WORKERS)
    parser.add_argument('--delay', type=float, default=REQUEST_DELAY)
    args = parser.parse_args()
    MAX_WORKERS = args.workers
    REQUEST_DELAY = args.delay

    logging.info("=" * 60)
    logging.info("FETCH SHARES FLOAT")
    logging.info("=" * 60)

    if not API_KEY:
        logging.error("FMP_API_KEY not found")
        return False

    symbols = load_target_stocks()
    if args.limit:
        symbols = symbols[:args.limit]
        logging.info(f"DRY-RUN: limited to first {len(symbols)} symbols")
    if not symbols:
        logging.error("No symbols found")
        return False

    logging.info(f"Fetching for {len(symbols)} symbols (workers={MAX_WORKERS}, delay={REQUEST_DELAY}s)...")

    result = {}
    success_count = fail_count = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_one, s): s for s in symbols}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                data = future.result()
                if data:
                    result[symbol] = data
                    success_count += 1
                else:
                    fail_count += 1
                if (success_count + fail_count) % 200 == 0:
                    logging.info(f"Progress: {success_count + fail_count}/{len(symbols)}")
            except Exception as e:
                fail_count += 1
                logging.error(f"✗ {symbol}: {e}")

    logging.info(f"Fetch completed: {success_count} success, {fail_count} failed")

    with open(TEMP_JSON, 'w') as f:
        json.dump(result, f)
    logging.info(f"✅ Saved {TEMP_JSON} ({len(result)} symbols)")
    return True


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)

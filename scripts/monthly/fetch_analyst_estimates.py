"""
fetch_analyst_estimates.py

FMP stable `analyst-estimates`（period=annual）から、各銘柄のアナリスト予想
（revenue/eps 等の low/high/avg、会計年度ごと）を取得する。

実測: 過去の確定年（例 AAPL 1996〜）＋将来数年分（例 2030）まで一括で返る。
四半期(period=quarter)も存在するが、まずは年次のみ対象（用途は長期の成長期待の把握）。

年別パーティションはせず、銘柄ごとに1ファイル（過去〜将来の全レコードをまとめて保持、
取得のたびに全体を上書き）。四半期ファンダのような year-freeze は行わない
（推定値は時間とともに改定されるため、常に最新の推定値セットで上書きするのが正しい）。

出力: data/temp_analyst_estimates.json
  {symbol: {ticker, data: [{date, revenueLow, revenueHigh, revenueAvg, epsLow, epsHigh, epsAvg, ...}], lastUpdated}}

使い方:
  python scripts/monthly/fetch_analyst_estimates.py --limit 30   # 少数ドライラン
  python scripts/monthly/fetch_analyst_estimates.py              # 全件
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
TEMP_JSON = os.path.join(DATA_FOLDER, "temp_analyst_estimates.json")

YEAR_LIMIT = 40
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

# 保存する主要フィールドのみ（FMPは項目数が多いため、成長期待の把握に使う主要指標に絞る）
KEEP_FIELDS = [
    'date', 'revenueLow', 'revenueHigh', 'revenueAvg',
    'ebitdaLow', 'ebitdaHigh', 'ebitdaAvg',
    'netIncomeLow', 'netIncomeHigh', 'netIncomeAvg',
    'epsLow', 'epsHigh', 'epsAvg',
    'numAnalystsRevenue', 'numAnalystsEps',
]


def fetch_one(symbol, session=None):
    if session is None:
        session = SESSION
    url = f"{BASE_URL}/analyst-estimates"
    params = {'symbol': symbol, 'period': 'annual', 'limit': YEAR_LIMIT, 'apikey': API_KEY}
    try:
        r = session.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list) or not data:
            return None
        data_sorted = sorted(data, key=lambda x: x.get('date', ''))
        rows = [{k: item.get(k) for k in KEEP_FIELDS} for item in data_sorted]
        if REQUEST_DELAY:
            time.sleep(REQUEST_DELAY)
        return {'ticker': symbol, 'data': rows, 'lastUpdated': datetime.now().isoformat()}
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
    logging.info("FETCH ANALYST ESTIMATES")
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

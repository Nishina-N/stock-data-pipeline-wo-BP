"""
fetch_jp_shares_float.py

日本株の浮動株情報を取得する。US版 scripts/monthly/fetch_shares_float.py の
fetch_one をそのまま再利用し、symbolだけ `.T` 付きで呼び出す。

出力: data/temp_shares_float_jp.json
  {code(純コード): {ticker: code, date, freeFloat, floatShares, outstandingShares, source, lastUpdated}}
"""
import os
import sys
import json
import logging
import argparse
import importlib.util
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.jp_market_symbols import JP_MARKET_SYMBOLS

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DATA_FOLDER = "data"
JP_CSV = os.path.join(DATA_FOLDER, "target_stocks_jp_latest.csv")
TEMP_JSON = os.path.join(DATA_FOLDER, "temp_shares_float_jp.json")

_US_PATH = os.path.join(os.path.dirname(__file__), '..', 'monthly', 'fetch_shares_float.py')
_spec = importlib.util.spec_from_file_location('us_fetch_shares_float', _US_PATH)
us_fsf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(us_fsf)


def load_jp_universe(csv_path=JP_CSV):
    if not os.path.exists(csv_path):
        logging.error(f"JP universe CSV not found: {csv_path}")
        return []
    df = pd.read_csv(csv_path, dtype={'Symbol': str})
    df['Symbol'] = df['Symbol'].str.strip()
    codes = [s for s in df['Symbol'].tolist() if s and s not in JP_MARKET_SYMBOLS]
    logging.info(f"Loaded {len(codes)} JP symbols (excluding benchmark tickers)")
    return codes


def fetch_one(code, session):
    data = us_fsf.fetch_one(f"{code}.T", session)
    if not data:
        return None
    data['ticker'] = code
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--workers', type=int, default=us_fsf.MAX_WORKERS)
    parser.add_argument('--delay', type=float, default=us_fsf.REQUEST_DELAY)
    args = parser.parse_args()
    us_fsf.MAX_WORKERS = args.workers
    us_fsf.REQUEST_DELAY = args.delay

    logging.info("=" * 60)
    logging.info("FETCH JP SHARES FLOAT")
    logging.info("=" * 60)

    if not us_fsf.API_KEY:
        logging.error("FMP_API_KEY not found")
        return False

    codes = load_jp_universe()
    if args.limit:
        codes = codes[:args.limit]
        logging.info(f"DRY-RUN: limited to first {len(codes)} symbols")
    if not codes:
        logging.error("No symbols found")
        return False

    logging.info(f"Fetching for {len(codes)} JP symbols (workers={us_fsf.MAX_WORKERS}, delay={us_fsf.REQUEST_DELAY}s)...")

    result = {}
    success_count = fail_count = 0
    with ThreadPoolExecutor(max_workers=us_fsf.MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_one, code, us_fsf.SESSION): code for code in codes}
        for future in as_completed(futures):
            code = futures[future]
            try:
                data = future.result()
                if data:
                    result[code] = data
                    success_count += 1
                else:
                    fail_count += 1
                if (success_count + fail_count) % 200 == 0:
                    logging.info(f"Progress: {success_count + fail_count}/{len(codes)}")
            except Exception as e:
                fail_count += 1
                logging.error(f"✗ {code}: {e}")

    logging.info(f"Fetch completed: {success_count} success, {fail_count} failed")

    with open(TEMP_JSON, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False)
    logging.info(f"✅ Saved {TEMP_JSON} ({len(result)} symbols)")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

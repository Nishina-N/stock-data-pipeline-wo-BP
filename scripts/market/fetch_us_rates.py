"""
fetch_us_rates.py

米国債利回り（2y/10y/30y）を FMP stable `treasury-rates` から取得する。
Yahoo Finance の `^TNX` 等は履歴を返さないため対象外にしていたが（README参照）、
FMP に日次フル履歴（1990-01-02〜）を持つエンドポイントがあることを確認できたため追加。

1リクエストあたり約60日分に制限されているため、日付範囲を分割して取得する。

fetch_market_series.py と同じ temp_market.json 形式で出力するため、
build_market_by_year.py --merge にそのまま渡せる（利回りを疑似OHLCVとして
open=high=low=close=利回り(%)、volume=null で格納）。

使い方:
  python scripts/market/fetch_us_rates.py
  python scripts/market/build_market_by_year.py --merge
  python scripts/market/upload_market_to_r2.py --force-past --execute
"""
import os
import sys
import json
import time
import logging
from datetime import date, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DATA_FOLDER = "data"
OUT_JSON = os.path.join(DATA_FOLDER, "temp_market.json")

BASE_URL = "https://financialmodelingprep.com/stable"
API_KEY = os.getenv('FMP_API_KEY')

START_DATE = date(1990, 1, 1)
CHUNK_DAYS = 55  # 実測で約60行/リクエストの上限があるため安全マージンを取って分割

# FMP のフィールド名 -> このパイプラインのティッカーキー
FIELD_TO_TICKER = {
    'year2':  {'ticker': 'UST2Y',  'name': 'US Treasury 2Y Yield'},
    'year10': {'ticker': 'UST10Y', 'name': 'US Treasury 10Y Yield'},
    'year30': {'ticker': 'UST30Y', 'name': 'US Treasury 30Y Yield'},
}
SERIES_META = {
    v['ticker']: {'name': v['name'], 'use': 'us_rate_regime', 'source': 'fmp_treasury_rates'}
    for v in FIELD_TO_TICKER.values()
}


def date_chunks(start, end, days):
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=days), end)
        yield cur, chunk_end
        cur = chunk_end + timedelta(days=1)


def fetch_range(start, end, max_retries=3):
    params = {'from': start.isoformat(), 'to': end.isoformat(), 'apikey': API_KEY}
    for attempt in range(max_retries):
        try:
            r = requests.get(f"{BASE_URL}/treasury-rates", params=params, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == max_retries - 1:
                logging.error(f"  {start}..{end}: failed after {max_retries}: {e}")
                return []
            time.sleep(2)
    return []


def main():
    if not API_KEY:
        logging.error("FMP_API_KEY not found")
        return False

    today = date.today()
    rows = {v['ticker']: {} for v in FIELD_TO_TICKER.values()}

    chunks = list(date_chunks(START_DATE, today, CHUNK_DAYS))
    logging.info(f"Fetching US treasury rates in {len(chunks)} chunks ({START_DATE}..{today})...")

    for i, (start, end) in enumerate(chunks, 1):
        data = fetch_range(start, end)
        for item in data:
            d = item.get('date')
            if not d:
                continue
            for field, meta in FIELD_TO_TICKER.items():
                v = item.get(field)
                if v is None:
                    continue
                rows[meta['ticker']][d] = {
                    'open': v, 'high': v, 'low': v, 'close': v, 'volume': None,
                }
        if i % 20 == 0 or i == len(chunks):
            logging.info(f"  progress: {i}/{len(chunks)} chunks")
        time.sleep(0.3)

    for ticker, r in rows.items():
        if r:
            dates = sorted(r.keys())
            logging.info(f"✓ {ticker:8} {len(r):5} rows  {dates[0]}..{dates[-1]}")
        else:
            logging.warning(f"✗ {ticker:8} no data")

    os.makedirs(DATA_FOLDER, exist_ok=True)
    with open(OUT_JSON, 'w') as f:
        json.dump({'series': SERIES_META, 'data': rows}, f)
    logging.info(f"✅ Saved {OUT_JSON}")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

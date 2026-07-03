"""
build_market_by_year.py

data/temp_market.json（fetch_market_series.py 出力）を
年別統合ファイル market/daily/{year}.json + market/metadata.json に変換する。

出力（ローカル、アップロード前段）:
  data/market/r2/market/daily/{year}.json
  data/market/r2/market/metadata.json

使い方:
  python scripts/market/build_market_by_year.py
"""
import os
import sys
import json
import logging
from datetime import datetime
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DATA_FOLDER = "data"
IN_JSON = os.path.join(DATA_FOLDER, "temp_market.json")
OUT_ROOT = os.path.join(DATA_FOLDER, "market", "r2", "market")
DAILY_DIR = os.path.join(OUT_ROOT, "daily")

# metadata に載せるカバレッジ開始（取得テストで確認済み）
COVERAGE_START = {
    "^VIX":   "2004-01",
    "^VIX3M": "2006-07",
    "HYG":    "2007-04",
    "JNK":    "2007-12",
    "LQD":    "2004-01",
    "IEI":    "2007-01",
    "IWM":    "2004-01",
    "SPY":    "2004-01",
}


def main():
    if not os.path.exists(IN_JSON):
        logging.error(f"Not found: {IN_JSON} (run fetch_market_series.py first)")
        return False

    with open(IN_JSON) as f:
        payload = json.load(f)

    series_meta = payload['series']
    data = payload['data']          # {ticker: {date: {ohlcv}}}
    tickers = list(series_meta.keys())

    # 日付 -> ticker -> ohlcv に転置し、年別にまとめる
    by_year = defaultdict(lambda: defaultdict(dict))  # year -> date -> {ticker: ohlcv}
    for ticker, rows in data.items():
        for date, ohlcv in rows.items():
            year = int(date[:4])
            by_year[year][date][ticker] = ohlcv

    os.makedirs(DAILY_DIR, exist_ok=True)

    years = sorted(by_year.keys())
    for year in years:
        # 日付昇順で dict を構築（JSONは順序保持）
        day_map = by_year[year]
        ordered = {d: day_map[d] for d in sorted(day_map.keys())}
        out = {
            'year': year,
            'adjust': 'auto_adjusted_close',
            'tickers': tickers,
            'data': ordered,
        }
        with open(os.path.join(DAILY_DIR, f"{year}.json"), 'w') as f:
            json.dump(out, f)

    # カバレッジ実測（各ティッカーの最初/最後の日付）
    actual_cov = {}
    for ticker, rows in data.items():
        if rows:
            ds = sorted(rows.keys())
            actual_cov[ticker] = {'first': ds[0], 'last': ds[-1], 'rows': len(rows)}
        else:
            actual_cov[ticker] = {'first': None, 'last': None, 'rows': 0}

    metadata = {
        'source': 'yahoo_finance',
        'adjust': 'auto',
        'updated': datetime.now().isoformat(),
        'years': years,
        'series': {
            t: {
                'name': series_meta[t]['name'],
                'use': series_meta[t]['use'],
                'coverage_start': COVERAGE_START.get(t),
                'actual_first': actual_cov[t]['first'],
                'actual_last': actual_cov[t]['last'],
                'rows': actual_cov[t]['rows'],
            }
            for t in tickers
        },
    }
    with open(os.path.join(OUT_ROOT, "metadata.json"), 'w') as f:
        json.dump(metadata, f, indent=2)

    logging.info(f"✅ Built {len(years)} year files: {years[0]}..{years[-1]}")
    for t in tickers:
        c = actual_cov[t]
        logging.info(f"   {t:8} rows={c['rows']:5} {c['first']}..{c['last']}")
    logging.info(f"   Local: {OUT_ROOT}")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

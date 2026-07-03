"""
fetch_market_series.py

リスク制御用のマクロ/マーケットシリーズを Yahoo Finance から取得する。
全て auto_adjust 済み OHLCV。取得結果を data/temp_market.json に保存。

シリーズ（market/metadata.json の series と対応）:
  ^VIX, ^VIX3M, HYG, JNK, LQD, IEI, IWM, SPY

使い方:
  python scripts/market/fetch_market_series.py                     # フル履歴
  python scripts/market/fetch_market_series.py --start 2022-01-01  # 期間指定（ドライラン用）
  python scripts/market/fetch_market_series.py --start 2022-01-01 --end 2024-12-31
"""
import os
import sys
import json
import time
import logging
import argparse

import pandas as pd
import yfinance as yf

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DATA_FOLDER = "data"
OUT_JSON = os.path.join(DATA_FOLDER, "temp_market.json")

# 取得対象と用途（metadata と一致させる）
SERIES = {
    "^VIX":   {"name": "VIX",            "use": "level+spike"},
    "^VIX3M": {"name": "VIX 3M",         "use": "term_structure"},
    "HYG":    {"name": "HY Bond ETF",    "use": "credit"},
    "JNK":    {"name": "HY Bond ETF",    "use": "credit_confirm"},
    "LQD":    {"name": "IG Bond ETF",    "use": "credit_ig"},
    "IEI":    {"name": "3-7Y UST ETF",   "use": "duration_hedge"},
    "IWM":    {"name": "Russell 2000",   "use": "risk_appetite"},
    "SPY":    {"name": "S&P 500 ETF",    "use": "benchmark"},
}


def fetch_one(ticker, start, end, max_retries=3):
    """1シリーズを取得し {date: {open,high,low,close,volume}} を返す"""
    for attempt in range(max_retries):
        try:
            if start:
                df = yf.download(ticker, start=start, end=end, auto_adjust=True,
                                 progress=False, threads=False)
            else:
                df = yf.download(ticker, period="max", end=end, auto_adjust=True,
                                 progress=False, threads=False)
            if df is None or df.empty:
                logging.warning(f"  {ticker}: empty")
                return {}
            # 単一ティッカーでも columns が MultiIndex になる場合がある
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            rows = {}
            for ts, r in df.iterrows():
                date = pd.Timestamp(ts).strftime('%Y-%m-%d')

                def g(col):
                    v = r.get(col)
                    return None if pd.isna(v) else float(v)

                vol = r.get('Volume')
                vol = None if (vol is None or pd.isna(vol) or vol == 0) else int(vol)
                rows[date] = {
                    'open': g('Open'), 'high': g('High'), 'low': g('Low'),
                    'close': g('Close'), 'volume': vol,
                }
            return rows
        except Exception as e:
            if attempt == max_retries - 1:
                logging.error(f"  {ticker}: failed after {max_retries}: {e}")
                return {}
            time.sleep(2)
    return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', default=None, help='開始日 YYYY-MM-DD（未指定=フル履歴）')
    ap.add_argument('--end', default=None, help='終了日 YYYY-MM-DD')
    args = ap.parse_args()

    logging.info("=" * 60)
    logging.info(f"FETCH MARKET SERIES (start={args.start or 'max'}, end={args.end or 'today'})")
    logging.info("=" * 60)

    result = {}
    for ticker in SERIES:
        rows = fetch_one(ticker, args.start, args.end)
        result[ticker] = rows
        if rows:
            dates = sorted(rows.keys())
            logging.info(f"✓ {ticker:8} {len(rows):5} rows  {dates[0]}..{dates[-1]}")
        else:
            logging.warning(f"✗ {ticker:8} no data")
        time.sleep(0.5)

    os.makedirs(DATA_FOLDER, exist_ok=True)
    with open(OUT_JSON, 'w') as f:
        json.dump({'series': SERIES, 'data': result}, f)
    logging.info(f"✅ Saved {OUT_JSON}")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

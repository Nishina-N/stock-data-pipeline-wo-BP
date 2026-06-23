"""
backfill_market_symbols.py

主要指数・ETF（MARKET_SYMBOLS）の「過去」OHLCV を core に補充する（スコープB2）。

方針:
  - yfinance で各シンボルの上場来 OHLCV を取得
  - 既存の (symbol, year) はスキップ（既存履歴を壊さない）
  - 欠けている年のみ core/{year}/{symbol}.json を生成
  - rs_percentile は null（過去分のRSは付与しない。今後の日次で現在年は付く）

安全設計:
  - 既定は dry-run（生成予定のみ表示）
  - 実書込は --execute のみ
  - input() 不使用（CI / workflow_dispatch でも動く）

使い方:
  python scripts/maintenance/backfill_market_symbols.py            # dry-run
  python scripts/maintenance/backfill_market_symbols.py --execute  # 実書込
"""
import argparse
import io
import json
import os
import sys
import logging
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.market_symbols import MARKET_SYMBOLS
from common.r2 import create_s3_client

load_dotenv(dotenv_path=".env")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

CORE_PREFIX = "stocks/daily/core"

def fetch_ohlcv(symbol):
    """yfinance で上場来 OHLCV を取得（単一銘柄）"""
    df = yf.download(symbol, period='max', progress=False, threads=False)
    if df is None or df.empty:
        return None
    # 単一銘柄でも MultiIndex になる版があるため平坦化
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    keep = [c for c in ['Open', 'High', 'Low', 'Close', 'Volume'] if c in df.columns]
    df = df[keep].dropna(how='all')
    return df

def df_to_year_records(df):
    """DataFrame を {year: [record,...]} に変換"""
    by_year = {}
    for idx, row in df.iterrows():
        date = pd.Timestamp(idx)
        year = date.year
        rec = {
            'date': date.strftime('%Y-%m-%d'),
            'open':  None if pd.isna(row.get('Open'))  else round(float(row['Open']),  2),
            'high':  None if pd.isna(row.get('High'))  else round(float(row['High']),  2),
            'low':   None if pd.isna(row.get('Low'))   else round(float(row['Low']),   2),
            'close': None if pd.isna(row.get('Close')) else round(float(row['Close']), 2),
            'volume': 0    if pd.isna(row.get('Volume')) else int(row['Volume']),
            'rs_percentile': None,
        }
        by_year.setdefault(year, []).append(rec)
    return by_year

def prefetch_existing_years(s3, bucket, symbols):
    """
    core 全体を1回走査し、対象シンボルごとの既存年集合を返す。
    （シンボル毎に走査すると 94k×回 になるため、1パスにまとめる）
    """
    targets = {f"{s}.json": s for s in symbols}
    result = {s: set() for s in symbols}
    paginator = s3.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{CORE_PREFIX}/"):
        for obj in page.get('Contents', []):
            parts = obj['Key'].split('/')
            # stocks/daily/core/{year}/{symbol}.json
            if len(parts) >= 5 and parts[3].isdigit():
                sym = targets.get(parts[4])
                if sym is not None:
                    result[sym].add(int(parts[3]))
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true', help='実際に書き込む（未指定は dry-run）')
    parser.add_argument('--only', nargs='*', help='対象シンボルを限定（省略時は全 MARKET_SYMBOLS）')
    args = parser.parse_args()

    required_env = ['R2_ENDPOINT', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET_NAME']
    missing = [e for e in required_env if not os.environ.get(e)]
    if missing:
        logging.error(f"Missing environment variables: {', '.join(missing)}")
        return False

    symbols = args.only if args.only else list(MARKET_SYMBOLS.keys())
    s3 = create_s3_client()
    bucket = os.environ['R2_BUCKET_NAME']

    mode = "EXECUTE (WRITE)" if args.execute else "DRY-RUN (no write)"
    logging.info("=" * 60)
    logging.info(f"BACKFILL MARKET SYMBOLS — {mode}")
    logging.info(f"Bucket: {bucket} / Symbols: {len(symbols)}")
    logging.info("=" * 60)

    total_written = 0      # execute 時に書いた数
    total_planned = 0      # dry-run 時に書く予定の数
    total_skipped = 0

    logging.info("Scanning existing core years (1 pass)...")
    existing_map = prefetch_existing_years(s3, bucket, symbols)

    for symbol in symbols:
        name, sector, industry = MARKET_SYMBOLS.get(symbol, (symbol, 'N/A', 'N/A'))
        logging.info(f"\n[{symbol}] fetching OHLCV...")

        df = fetch_ohlcv(symbol)
        if df is None:
            logging.warning(f"  no data from yfinance, skip")
            continue

        by_year = df_to_year_records(df)
        have = existing_map.get(symbol, set())
        new_years = sorted(y for y in by_year if y not in have)
        skip_years = sorted(y for y in by_year if y in have)

        logging.info(f"  data years: {min(by_year)}–{max(by_year)} | "
                     f"new: {len(new_years)} | already-exists(skip): {len(skip_years)}")

        for year in new_years:
            records = by_year[year]
            payload = {
                'ticker': symbol,
                'name': name,
                'sector': sector,
                'industry': industry,
                'data': records,
            }
            key = f"{CORE_PREFIX}/{year}/{symbol}.json"

            if args.execute:
                body = io.BytesIO(json.dumps(payload).encode('utf-8'))
                s3.upload_fileobj(body, bucket, key)
                total_written += 1

        total_skipped += len(skip_years)
        if not args.execute and new_years:
            total_planned += len(new_years)
            logging.info(f"    -> {len(new_years)} year-files would be written "
                         f"({new_years[0]}–{new_years[-1]})")

    s3.close()

    logging.info("\n" + "=" * 60)
    if args.execute:
        logging.info(f"✅ Wrote {total_written} core year-files (skipped existing: {total_skipped})")
    else:
        logging.info(f"DRY-RUN: {total_planned} year-files would be written "
                     f"(skipped existing: {total_skipped}). Re-run with --execute.")
    logging.info("=" * 60)
    return True

if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)

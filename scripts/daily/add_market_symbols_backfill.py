"""
add_market_symbols_backfill.py

common/market_symbols.py の MARKET_SYMBOLS に新規追加した銘柄だけを対象に、
(1) R2 の metadata/target_stocks_latest.csv に行を注入し、
(2) yfinance でフル履歴を取得して stocks/daily/core/{year}/{symbol}.json に投入する。

既存の~4600銘柄は一切再取得しない（1_fetch_target_stocks.pyのフルFMPスクリーナー
再実行を避けるための軽量スクリプト。scripts/jp/add_jp_benchmark_tickers.py と同じ設計思想）。

rs_percentile は null で格納する（個別RSはその日のユニバース全体のクロスセクション
percentileが必要で、この軽量スクリプト単体では正しく計算できないため）。当年分は
次回の daily-update.yml 実行時に本番の 3_calculate_rs.py が全ユニバースと合わせて
再計算し、実値で上書きする（過去年は year-freeze で null のまま残る）。

安全弁: 既定はドライラン。--execute で実投入。過去年は R2 に無い場合のみ書く
（--force-past で強制上書き）。当年は常に上書き。

使い方:
  python scripts/daily/add_market_symbols_backfill.py --symbols TMF,TMV,GLD,TECL
  python scripts/daily/add_market_symbols_backfill.py --symbols TMF,TMV,GLD,TECL --execute
"""
import os
import sys
import json
import logging
import argparse
from collections import defaultdict
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.r2 import create_s3_client
from common.market_symbols import MARKET_SYMBOLS

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

R2_CSV_KEY = "metadata/target_stocks_latest.csv"
R2_CORE_PREFIX = "stocks/daily/core"
CURRENT_YEAR = datetime.now().year
DEFAULT_START = "2000-01-01"


def update_universe_csv(symbols, bucket, execute):
    s3 = create_s3_client()
    try:
        obj = s3.get_object(Bucket=bucket, Key=R2_CSV_KEY)
        import io
        df = pd.read_csv(io.BytesIO(obj['Body'].read()))
    finally:
        s3.close()

    df = df[~df['Symbol'].isin(symbols)]
    rows = []
    for sym in symbols:
        name, sector, industry = MARKET_SYMBOLS[sym]
        rows.append({
            'Symbol': sym, 'Company Name': name, 'Sector': sector, 'Industry': industry,
            'Price': 0, 'Market_Cap': 0, 'IPO_Date': '', 'Exchange': 'INDEX/ETF'
        })
    df = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)

    local_path = os.path.join("data", "target_stocks_latest.csv")
    os.makedirs("data", exist_ok=True)
    df.to_csv(local_path, index=False)
    logging.info(f"Universe CSV: {len(df)} rows total (+{len(rows)} new)")

    if not execute:
        logging.info("[dry-run] would upload updated CSV to R2")
        return
    s3 = create_s3_client()
    try:
        s3.upload_file(local_path, bucket, R2_CSV_KEY)
        logging.info(f"✅ Uploaded {R2_CSV_KEY}")
    finally:
        s3.close()


def fetch_ticker(symbol, start=DEFAULT_START):
    logging.info(f"Fetching {symbol} from {start}...")
    df = yf.download(symbol, start=start, auto_adjust=True, progress=False)
    if df is None or df.empty:
        logging.warning(f"  no data for {symbol}")
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    logging.info(f"  {symbol}: {len(df)} rows, {df.index.min().date()}..{df.index.max().date()}")
    return df


def to_year_records(symbol, df, meta):
    rows_by_year = defaultdict(list)
    dates = df.index.strftime('%Y-%m-%d').tolist()
    years = df.index.year.tolist()
    o = np.round(df['Open'].to_numpy(dtype=float), 2).tolist()
    h = np.round(df['High'].to_numpy(dtype=float), 2).tolist()
    l = np.round(df['Low'].to_numpy(dtype=float), 2).tolist()
    c = np.round(df['Close'].to_numpy(dtype=float), 2).tolist()
    v = df['Volume'].to_numpy(dtype=float).tolist()

    for i in range(len(dates)):
        rows_by_year[years[i]].append({
            'date': dates[i],
            'open': None if o[i] != o[i] else o[i],
            'high': None if h[i] != h[i] else h[i],
            'low': None if l[i] != l[i] else l[i],
            'close': None if c[i] != c[i] else c[i],
            'volume': 0 if v[i] != v[i] else int(v[i]),
            'rs_percentile': None,
        })

    records = {}
    for year, rows in rows_by_year.items():
        records[year] = {
            'ticker': symbol,
            'name': meta[0],
            'sector': meta[1],
            'industry': meta[2],
            'data': rows,
        }
    return records


def list_existing_keys(bucket, prefix):
    s3 = create_s3_client()
    keys = set()
    try:
        paginator = s3.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get('Contents', []):
                keys.add(obj['Key'])
    finally:
        s3.close()
    return keys


def upload_records(bucket, symbol, year_records, existing_keys, execute, force_past):
    s3 = create_s3_client() if execute else None
    try:
        for year, record in sorted(year_records.items()):
            key = f"{R2_CORE_PREFIX}/{year}/{symbol}.json"
            is_past = year < CURRENT_YEAR
            if is_past and not force_past and key in existing_keys:
                logging.info(f"  [frozen] {key} (既存・skip)")
                continue
            body = json.dumps(record).encode('utf-8')
            if not execute:
                logging.info(f"  [dry-run] would upload {key} ({len(record['data'])} days)")
                continue
            s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType='application/json')
            logging.info(f"  ✅ uploaded {key} ({len(record['data'])} days)")
    finally:
        if s3:
            s3.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--symbols', required=True, help='カンマ区切り（例 TMF,TMV,GLD,TECL）。MARKET_SYMBOLSに登録済みであること')
    ap.add_argument('--execute', action='store_true', help='ドライランではなく実投入')
    ap.add_argument('--force-past', action='store_true', help='過去年も上書き（既定は凍結）')
    ap.add_argument('--start', default=DEFAULT_START)
    args = ap.parse_args()

    symbols = [s.strip() for s in args.symbols.split(',') if s.strip()]
    unknown = [s for s in symbols if s not in MARKET_SYMBOLS]
    if unknown:
        logging.error(f"MARKET_SYMBOLS未登録: {unknown}（先に common/market_symbols.py に追加してください）")
        return False

    bucket = os.environ['R2_BUCKET_NAME']
    logging.info(f"Mode: {'EXECUTE' if args.execute else 'DRY-RUN'} force_past={args.force_past}")

    update_universe_csv(symbols, bucket, args.execute)

    existing_keys = list_existing_keys(bucket, R2_CORE_PREFIX) if not args.force_past else set()
    logging.info(f"Existing keys under {R2_CORE_PREFIX}: {len(existing_keys)}")

    for symbol in symbols:
        df = fetch_ticker(symbol, args.start)
        if df is None:
            continue
        year_records = to_year_records(symbol, df, MARKET_SYMBOLS[symbol])
        upload_records(bucket, symbol, year_records, existing_keys, args.execute, args.force_past)

    if not args.execute:
        logging.info("DRY-RUN 完了。--execute を付けて実投入してください。")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

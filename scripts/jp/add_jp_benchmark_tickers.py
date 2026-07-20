"""
add_jp_benchmark_tickers.py

JP daily core にベンチマーク疑似ティッカー（1306=TOPIX ETF, ^N225=日経225）だけを
追加投入する。既存の3,700銘柄超のJP core再取得・再アップロードは一切行わない
（`common/jp_market_symbols.py` の JP_MARKET_SYMBOLS で定義した2銘柄のみが対象）。

rs_percentile は null（クロスセクション全銘柄に対する再計算が必要なため、
このスクリプト単体では計算しない。個別RSが要るならユニバース全体の
2_calculate_jp_rs.py 再実行が必要）。

出力形式は既存 core と同一:
  {"ticker":..,"name":..,"sector":"N/A","industry":"N/A",
   "data":[{"date","open","high","low","close","volume","rs_percentile":null}, ...]}

安全弁: 既定はドライラン。--execute で実投入。過去年は R2 に無い場合のみ書く
（--force-past で強制上書き）。当年は常に上書き。

使い方:
  python scripts/jp/add_jp_benchmark_tickers.py                 # dry-run
  python scripts/jp/add_jp_benchmark_tickers.py --execute       # 実投入
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
from common.jp_market_symbols import JP_MARKET_SYMBOLS

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

R2_PREFIX = "jp/stocks/daily/core"
CURRENT_YEAR = datetime.now().year
DEFAULT_START = "2004-01-01"


def fetch_ticker(code, start=DEFAULT_START):
    yf_symbol = code if code.startswith('^') else f"{code}.T"
    logging.info(f"Fetching {yf_symbol} from {start}...")
    df = yf.download(yf_symbol, start=start, auto_adjust=True, progress=False)
    if df is None or df.empty:
        logging.warning(f"  no data for {yf_symbol}")
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    logging.info(f"  {yf_symbol}: {len(df)} rows, {df.index.min().date()}..{df.index.max().date()}")
    return df


def to_year_records(code, df, meta):
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
            'ticker': code,
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


def upload_records(bucket, code, year_records, existing_keys, execute, force_past):
    s3 = create_s3_client() if execute else None
    try:
        for year, record in sorted(year_records.items()):
            key = f"{R2_PREFIX}/{year}/{code}.json"
            is_past = year < CURRENT_YEAR
            if is_past and not force_past and key in existing_keys:
                logging.info(f"  [frozen] {key} (既存・skip)")
                continue

            body = json.dumps(record, ensure_ascii=False).encode('utf-8')
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
    ap.add_argument('--execute', action='store_true', help='ドライランではなく実投入')
    ap.add_argument('--force-past', action='store_true', help='過去年も上書き（既定は凍結）')
    ap.add_argument('--start', default=DEFAULT_START, help='取得開始日（既定2004-01-01。銘柄毎の実データ開始はそれより後の場合あり）')
    args = ap.parse_args()

    bucket = os.environ['R2_BUCKET_NAME']
    logging.info(f"Mode: {'EXECUTE' if args.execute else 'DRY-RUN'} force_past={args.force_past}")

    existing_keys = list_existing_keys(bucket, R2_PREFIX) if not args.force_past else set()
    logging.info(f"Existing keys under {R2_PREFIX}: {len(existing_keys)}")

    for code, meta in JP_MARKET_SYMBOLS.items():
        df = fetch_ticker(code, args.start)
        if df is None:
            continue
        year_records = to_year_records(code, df, meta)
        upload_records(bucket, code, year_records, existing_keys, args.execute, args.force_past)

    if not args.execute:
        logging.info("DRY-RUN 完了。--execute を付けて実投入してください。")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

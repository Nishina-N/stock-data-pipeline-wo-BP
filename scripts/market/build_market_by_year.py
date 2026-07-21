"""
build_market_by_year.py

data/temp_market.json（fetch_market_series.py 出力）を
年別統合ファイル market/daily/{year}.json + market/metadata.json に変換する。

出力（ローカル、アップロード前段）:
  data/market/r2/market/daily/{year}.json
  data/market/r2/market/metadata.json

使い方:
  python scripts/market/build_market_by_year.py            # temp_market から全ファイル新規生成
  python scripts/market/build_market_by_year.py --merge    # 既存R2ファイルに取得ティッカーを重ねる
                                                           #（--only で一部シリーズだけ取得した場合に使用）
"""
import os
import sys
import json
import argparse
import logging
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.r2 import create_s3_client
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

PREFIX = "market"

DATA_FOLDER = "data"
IN_JSON = os.path.join(DATA_FOLDER, "temp_market.json")
OUT_ROOT = os.path.join(DATA_FOLDER, "market", "r2", "market")
DAILY_DIR = os.path.join(OUT_ROOT, "daily")

# metadata に載せるカバレッジ開始（取得テストで確認済み。実測は build 時に actual_first で上書き記録）
COVERAGE_START = {
    "^VIX":     "1990-01",
    "^VIX3M":   "2006-07",
    "HYG":      "2007-04",
    "JNK":      "2007-12",
    "LQD":      "2002-07",
    "IEI":      "2007-01",
    "IWM":      "2000-05",
    "SPY":      "1993-01",
    "HG=F":     "2004-01",
    "GC=F":     "2004-01",
    "CL=F":     "2004-01",
    "DX-Y.NYB": "1971-01",
    "TIP":      "2004-01",
    "IEF":      "2004-01",
    "DBC":      "2006-02",
    "DBB":      "2007-01",
    "USDJPY=X": "1996-10",
    "JGB10Y":   "1974-09",
    "UST2Y":    "1990-01",
    "UST10Y":   "1990-01",
    "UST30Y":   "1990-01",
}


def load_existing_year(s3, bucket, year):
    """R2 の market/daily/{year}.json を返す（無ければ None）"""
    try:
        obj = s3.get_object(Bucket=bucket, Key=f"{PREFIX}/daily/{year}.json")
        return json.loads(obj['Body'].read())
    except s3.exceptions.NoSuchKey:
        return None


def load_existing_metadata(s3, bucket):
    try:
        obj = s3.get_object(Bucket=bucket, Key=f"{PREFIX}/metadata.json")
        return json.loads(obj['Body'].read())
    except s3.exceptions.NoSuchKey:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--merge', action='store_true',
                    help='既存R2ファイルに取得ティッカーを重ねる（--only で一部だけ取得した場合）')
    args = ap.parse_args()

    if not os.path.exists(IN_JSON):
        logging.error(f"Not found: {IN_JSON} (run fetch_market_series.py first)")
        return False

    with open(IN_JSON) as f:
        payload = json.load(f)

    series_meta = payload['series']
    data = payload['data']              # {ticker: {date: {ohlcv}}}（取得したティッカーのみ）
    fetched = [t for t in data.keys()]  # 実際に取得したティッカー

    # 日付 -> ticker -> ohlcv に転置し、年別にまとめる
    by_year = defaultdict(lambda: defaultdict(dict))  # year -> date -> {ticker: ohlcv}
    for ticker, rows in data.items():
        for date, ohlcv in rows.items():
            by_year[year_of(date)][date][ticker] = ohlcv

    os.makedirs(DAILY_DIR, exist_ok=True)

    s3 = bucket = None
    if args.merge:
        s3 = create_s3_client()
        bucket = os.environ['R2_BUCKET_NAME']

    years = sorted(by_year.keys())
    try:
        for year in years:
            day_map = by_year[year]

            if args.merge:
                base = load_existing_year(s3, bucket, year) or {
                    'year': year, 'adjust': 'auto_adjusted_close', 'tickers': [], 'data': {}
                }
                base_data = base.get('data', {})
                # 取得ティッカーを各日付に重ねる（既存の他ティッカーは保全）
                for date, tvals in day_map.items():
                    base_data.setdefault(date, {})
                    for t, ohlcv in tvals.items():
                        base_data[date][t] = ohlcv
                ordered = {d: base_data[d] for d in sorted(base_data.keys())}
                # tickers = 既存 ∪ 取得（順序: 既存優先）
                merged_tickers = list(base.get('tickers', []))
                for t in fetched:
                    if t not in merged_tickers:
                        merged_tickers.append(t)
                out = {'year': year, 'adjust': 'auto_adjusted_close',
                       'tickers': merged_tickers, 'data': ordered}
            else:
                ordered = {d: day_map[d] for d in sorted(day_map.keys())}
                out = {'year': year, 'adjust': 'auto_adjusted_close',
                       'tickers': list(series_meta.keys()), 'data': ordered}

            with open(os.path.join(DAILY_DIR, f"{year}.json"), 'w') as f:
                json.dump(out, f)

        # カバレッジ実測（取得ティッカー）
        actual_cov = {}
        for ticker, rows in data.items():
            if rows:
                ds = sorted(rows.keys())
                actual_cov[ticker] = {'first': ds[0], 'last': ds[-1], 'rows': len(rows)}
            else:
                actual_cov[ticker] = {'first': None, 'last': None, 'rows': 0}

        # metadata（merge時は既存にマージ、そうでなければ全生成）
        new_series_entries = {
            t: {
                'name': series_meta[t]['name'],
                'use': series_meta[t]['use'],
                'source': series_meta[t].get('source', 'yahoo_finance'),
                'coverage_start': COVERAGE_START.get(t),
                'actual_first': actual_cov[t]['first'],
                'actual_last': actual_cov[t]['last'],
                'rows': actual_cov[t]['rows'],
            }
            for t in fetched
        }
        if args.merge:
            meta = load_existing_metadata(s3, bucket) or {
                'source': 'yahoo_finance', 'adjust': 'auto', 'years': [], 'series': {}
            }
            meta['updated'] = datetime.now().isoformat()
            meta['series'].update(new_series_entries)
            meta['years'] = sorted(set(meta.get('years', [])) | set(years))
        else:
            meta = {
                'source': 'yahoo_finance', 'adjust': 'auto',
                'updated': datetime.now().isoformat(), 'years': years,
                'series': {
                    t: {
                        'name': series_meta[t]['name'], 'use': series_meta[t]['use'],
                        'source': series_meta[t].get('source', 'yahoo_finance'),
                        'coverage_start': COVERAGE_START.get(t),
                        'actual_first': actual_cov.get(t, {}).get('first'),
                        'actual_last': actual_cov.get(t, {}).get('last'),
                        'rows': actual_cov.get(t, {}).get('rows', 0),
                    }
                    for t in series_meta.keys()
                },
            }
        with open(os.path.join(OUT_ROOT, "metadata.json"), 'w') as f:
            json.dump(meta, f, indent=2)
    finally:
        if s3:
            s3.close()

    mode = "MERGE" if args.merge else "FRESH"
    logging.info(f"✅ Built ({mode}) {len(years)} year files: {years[0]}..{years[-1]}")
    for t in fetched:
        c = actual_cov[t]
        logging.info(f"   {t:10} rows={c['rows']:5} {c['first']}..{c['last']}")
    logging.info(f"   Local: {OUT_ROOT}")
    return True


def year_of(date):
    return int(date[:4])


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

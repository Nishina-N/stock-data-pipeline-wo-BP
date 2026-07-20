"""
fetch_jp_macro_jgb.py

JGB（日本国債）10年物金利を財務省公式CSVから取得する。
Yahoo Finance には日本国債の利回りシリーズが存在しないため、別ソース（MOF）を使う
（US の 10y/2y と同じ理由で Yahoo 対象外。README 参照）。

出典: 財務省「国債金利情報」過去の金利情報（昭和49年(1974)〜）
  https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv
  列: 基準日(和暦), 1年,2年,...,10年,15年,20年,25年,30年,40年（単位:%）
  和暦（S=昭和/H=平成/R=令和）→ 西暦に変換。欠測は "-" で欠落行として扱う。

fetch_market_series.py と同じ temp_market.json 形式で出力するため、
build_market_by_year.py --merge にそのまま渡せる（利回りを疑似OHLCVとして
open=high=low=close=利回り、volume=null で格納。ティッカーキーは "JGB10Y"）。

使い方:
  python scripts/market/fetch_jp_macro_jgb.py
  python scripts/market/build_market_by_year.py --merge
  python scripts/market/upload_market_to_r2.py --execute
"""
import os
import sys
import json
import logging
import urllib.request as urlreq

import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DATA_FOLDER = "data"
OUT_JSON = os.path.join(DATA_FOLDER, "temp_market.json")

MOF_URL = "https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv"
TICKER = "JGB10Y"
SERIES_META = {
    TICKER: {"name": "JGB 10Y Yield", "use": "jp_rate_regime", "source": "mof_jgbcm"},
}

ERA_OFFSET = {'S': 1925, 'H': 1988, 'R': 2018}  # 和暦年 + offset = 西暦


def era_to_gregorian(date_str):
    """'S49.9.24' / 'H1.1.4' / 'R6.6.30' -> '1974-09-24' 等"""
    era = date_str[0]
    rest = date_str[1:]
    y, m, d = rest.split('.')
    year = int(y) + ERA_OFFSET[era]
    return f"{year:04d}-{int(m):02d}-{int(d):02d}"


def download_mof_csv():
    logging.info(f"Downloading {MOF_URL}")
    req = urlreq.Request(MOF_URL, headers={'User-Agent': 'Mozilla/5.0'})
    raw = urlreq.urlopen(req, timeout=30).read()
    text = raw.decode('cp932')
    logging.info(f"  downloaded {len(raw):,} bytes")
    return text


def parse_10y(text):
    lines = text.splitlines()
    # 1行目=タイトル, 2行目=ヘッダ（基準日,1年,2年,...,10年,...）
    header = lines[1].split(',')
    idx_10y = header.index('10年')

    rows = {}
    for line in lines[2:]:
        if not line.strip():
            continue
        parts = line.split(',')
        if len(parts) <= idx_10y:
            continue
        raw_val = parts[idx_10y].strip()
        if raw_val in ('', '-'):
            continue
        try:
            date = era_to_gregorian(parts[0].strip())
            val = float(raw_val)
        except (ValueError, IndexError, KeyError):
            continue
        rows[date] = {'open': val, 'high': val, 'low': val, 'close': val, 'volume': None}
    return rows


def main():
    text = download_mof_csv()
    rows = parse_10y(text)
    if not rows:
        logging.error("No JGB10Y rows parsed")
        return False

    dates = sorted(rows.keys())
    logging.info(f"✓ {TICKER:8} {len(rows):5} rows  {dates[0]}..{dates[-1]}")

    os.makedirs(DATA_FOLDER, exist_ok=True)
    with open(OUT_JSON, 'w') as f:
        json.dump({'series': SERIES_META, 'data': {TICKER: rows}}, f)
    logging.info(f"✅ Saved {OUT_JSON}")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

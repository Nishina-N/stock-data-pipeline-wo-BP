"""
build_jp_universe.py

JPX「東証上場銘柄一覧」(data_j.xls) から日本株ユニバースを構築する。

出力 CSV（US の target_stocks_latest.csv と同じ列思想。common.symbols で読める）:
  Symbol       : 銘柄コード（.T 抜きの純コード。例 7203）
  Company Name : 銘柄名
  Sector       : 17業種区分
  Industry     : 33業種区分
  Market       : 市場区分（プライム/スタンダード/グロース）
  Size         : 規模区分（TOPIX Core30 等）
  Exchange     : TSE

対象は内国株式（プライム/スタンダード/グロース）のみ。
ETF/ETN・REIT・PRO Market・外国株・出資証券は除外。

使い方:
  python scripts/jp/build_jp_universe.py            # ローカル生成のみ（dry-run）
  python scripts/jp/build_jp_universe.py --execute  # 生成 + R2(jp/metadata) へアップロード
"""
import os
import sys
import io
import logging
import argparse
import urllib.request as urlreq

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.r2 import create_s3_client
from common.jp_market_symbols import JP_MARKET_SYMBOLS
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

JPX_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"

DATA_FOLDER = "data"
OUT_CSV = os.path.join(DATA_FOLDER, "target_stocks_jp_latest.csv")
R2_KEY = "jp/metadata/target_stocks_jp_latest.csv"

# 採用する市場・商品区分（内国株式のみ）
KEEP_MARKETS = {
    "プライム（内国株式）":    "Prime",
    "スタンダード（内国株式）": "Standard",
    "グロース（内国株式）":    "Growth",
}


def download_jpx():
    logging.info(f"Downloading JPX list: {JPX_URL}")
    req = urlreq.Request(JPX_URL, headers={'User-Agent': 'Mozilla/5.0'})
    raw = urlreq.urlopen(req, timeout=30).read()
    logging.info(f"  downloaded {len(raw):,} bytes")
    return pd.read_excel(io.BytesIO(raw))


def build(df):
    df = df.copy()
    # 市場区分でフィルタ（内国株式のみ）
    df = df[df['市場・商品区分'].isin(KEEP_MARKETS.keys())].copy()

    out = pd.DataFrame({
        'Symbol': df['コード'].astype(str).str.strip(),
        'Company Name': df['銘柄名'].astype(str).str.strip(),
        'Sector': df['17業種区分'].astype(str).str.strip(),
        'Industry': df['33業種区分'].astype(str).str.strip(),
        'Market': df['市場・商品区分'].map(KEEP_MARKETS),
        'Size': df['規模区分'].astype(str).str.strip(),
        'Exchange': 'TSE',
    })
    # 業種が '-' の行（分類なし）は除外しておく
    out = out[(out['Sector'] != '-') & (out['Industry'] != '-')]
    out = out.drop_duplicates(subset=['Symbol']).sort_values('Symbol').reset_index(drop=True)
    return out


def inject_market_symbols(df):
    """
    TOPIX プロキシ(1306) / 日経225(^N225) を必ず最終CSVに含める（US の
    inject_market_symbols と同じ規約）。既存に同一シンボルがあれば保証行で上書き。
    """
    df = df[~df['Symbol'].isin(JP_MARKET_SYMBOLS)]
    rows = []
    for symbol, (name, sector, industry) in JP_MARKET_SYMBOLS.items():
        rows.append({
            'Symbol': symbol,
            'Company Name': name,
            'Sector': sector,
            'Industry': industry,
            'Market': 'INDEX/ETF',
            'Size': 'N/A',
            'Exchange': 'TSE' if symbol != '^N225' else 'OSE',
        })
    return pd.concat([df, pd.DataFrame(rows)], ignore_index=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--execute', action='store_true', help='R2(jp/metadata) へアップロード')
    args = ap.parse_args()

    df = download_jpx()
    logging.info(f"Raw rows: {len(df)}")

    uni = build(df)
    uni = inject_market_symbols(uni)
    os.makedirs(DATA_FOLDER, exist_ok=True)
    uni.to_csv(OUT_CSV, index=False, encoding='utf-8-sig')

    logging.info(f"✅ Universe: {len(uni)} symbols -> {OUT_CSV}")
    logging.info("[Market]\n" + uni['Market'].value_counts().to_string())
    logging.info(f"[Sector(17)] {uni['Sector'].nunique()} 種\n" + uni['Sector'].value_counts().to_string())
    logging.info(f"[Industry(33)] {uni['Industry'].nunique()} 種")
    logging.info("sample:\n" + uni.head(5).to_string())

    if not args.execute:
        logging.info("DRY-RUN: R2投入は --execute を付けてください")
        return True

    s3 = create_s3_client()
    try:
        bucket = os.environ['R2_BUCKET_NAME']
        s3.upload_file(OUT_CSV, bucket, R2_KEY)
        logging.info(f"✅ Uploaded -> {R2_KEY}")
    finally:
        s3.close()
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

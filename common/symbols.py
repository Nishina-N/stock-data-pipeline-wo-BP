"""
symbols.py

target_stocks_latest.csv から銘柄情報を読み込む共通関数。
"""
import os
import logging
import pandas as pd

# 🔴 pandas の既定 na_values は文字列 'NA' を欠損に変換する。
#    ティッカー **NA**（Nano Labs Ltd, NASDAQ）が実在するため、既定のまま読むと
#    1銘柄が黙って母集団から消える。さらに読んだものを to_csv で書き戻すと
#    Symbol が**空欄**になり、R2 の原本まで壊れる
#    （metadata/snapshots/target_stocks_2026-08-17.csv で実際に発生）。
#    空欄だけを欠損として扱い、'NA' / 'N/A' / 'null' は文字列のまま保つ。
READ_CSV_KWARGS = dict(keep_default_na=False, na_values=[''])


def read_target_stocks(src):
    """target_stocks CSV を読む。パスでも file-like でもよい。

    ここを通さずに pd.read_csv を直接呼ぶと NA が落ちる。
    """
    return pd.read_csv(src, **READ_CSV_KWARGS)


def load_symbols_info(csv_path):
    """target_stocks_latest.csv から銘柄情報 {symbol: {name, sector, industry}} を取得"""
    if not os.path.exists(csv_path):
        logging.error(f"Target stocks file not found: {csv_path}")
        return {}

    df = read_target_stocks(csv_path)

    symbols_info = {}
    for _, row in df.iterrows():
        symbol = row['Symbol']
        sector = row.get('Sector', 'N/A')
        industry = row.get('Industry', 'N/A')
        symbols_info[symbol] = {
            'name': row.get('Company Name', symbol),
            # 空欄セルは NaN(float) になるため 'N/A' に正規化
            # （NaN は Python では truthy かつ 'N/A' と非等価のため、
            #   下流のグループ除外フィルタを素通りしてしまう）
            'sector': sector if pd.notna(sector) else 'N/A',
            'industry': industry if pd.notna(industry) else 'N/A',
        }

    logging.info(f"Loaded info for {len(symbols_info)} symbols")
    return symbols_info

"""
symbols.py

target_stocks_latest.csv から銘柄情報を読み込む共通関数。
"""
import os
import logging
import pandas as pd

def load_symbols_info(csv_path):
    """target_stocks_latest.csv から銘柄情報 {symbol: {name, sector, industry}} を取得"""
    if not os.path.exists(csv_path):
        logging.error(f"Target stocks file not found: {csv_path}")
        return {}

    df = pd.read_csv(csv_path)

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

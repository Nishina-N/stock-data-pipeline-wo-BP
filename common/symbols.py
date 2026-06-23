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
        symbols_info[symbol] = {
            'name': row.get('Company Name', symbol),
            'sector': row.get('Sector', 'N/A'),
            'industry': row.get('Industry', 'N/A')
        }

    logging.info(f"Loaded info for {len(symbols_info)} symbols")
    return symbols_info

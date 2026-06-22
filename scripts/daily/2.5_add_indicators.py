"""
2.5_add_indicators.py

価格データ（pickle）を JSON 形式（OHLCV のみ）に変換する。

※ テクニカル指標（SMA/EMA/RSI/ATR/VWAP）の事前計算は廃止。
  指標はローソク情報（OHLCV）から利用側で再計算する方針に変更したため、
  このステップは pkl → json の変換のみを行う。
"""
import os
import pandas as pd
import numpy as np
from datetime import datetime
import logging
import json

DATA_FOLDER = "data"
TARGET_STOCKS_CSV = os.path.join(DATA_FOLDER, "target_stocks_latest.csv")
TEMP_PRICE_PKL = os.path.join(DATA_FOLDER, "temp_prices.pkl")
TEMP_PRICE_JSON = os.path.join(DATA_FOLDER, "temp_prices.json")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def convert_to_json(price_data, symbols_info):
    """
    MultiIndex DataFrame を OHLCV のみの JSON 形式に変換

    price_data: MultiIndex DataFrame, columns = (field, symbol)
    symbols_info: {symbol: {'name': ..., 'sector': ..., 'industry': ...}}
    """
    logging.info("Converting price data to JSON (OHLCV only)...")

    output = {
        'lastUpdated': datetime.now().isoformat(),
        'symbols': {}
    }

    symbols = price_data.columns.get_level_values(1).unique()

    for i, symbol in enumerate(symbols, 1):
        if i % 500 == 0:
            logging.info(f"Progress: {i}/{len(symbols)} symbols")

        if symbol not in symbols_info:
            continue

        try:
            df = pd.DataFrame({
                'open':   price_data['Open'][symbol],
                'high':   price_data['High'][symbol],
                'low':    price_data['Low'][symbol],
                'close':  price_data['Close'][symbol],
                'volume': price_data['Volume'][symbol],
            }).dropna(how='all')

            dates = df.index.strftime('%Y-%m-%d').tolist()
            open_vals   = df['open'].values
            high_vals   = df['high'].values
            low_vals    = df['low'].values
            close_vals  = df['close'].values
            volume_vals = df['volume'].values

            data_list = [
                {
                    'date':   dates[j],
                    'open':   None if np.isnan(open_vals[j])  else round(float(open_vals[j]),  2),
                    'high':   None if np.isnan(high_vals[j])  else round(float(high_vals[j]),  2),
                    'low':    None if np.isnan(low_vals[j])   else round(float(low_vals[j]),   2),
                    'close':  None if np.isnan(close_vals[j]) else round(float(close_vals[j]), 2),
                    'volume': 0    if np.isnan(volume_vals[j]) else int(volume_vals[j]),
                }
                for j in range(len(dates))
            ]

            output['symbols'][symbol] = {
                'name':     symbols_info[symbol]['name'],
                'sector':   symbols_info[symbol]['sector'],
                'industry': symbols_info[symbol]['industry'],
                'data':     data_list
            }

        except Exception as e:
            logging.warning(f"Failed to convert {symbol}: {e}")

    logging.info(f"✅ Converted {len(output['symbols'])} symbols to JSON")
    return output

def load_symbols_info():
    """target_stocks_latest.csvから銘柄情報を取得"""
    if not os.path.exists(TARGET_STOCKS_CSV):
        logging.error(f"Target stocks file not found: {TARGET_STOCKS_CSV}")
        return {}

    df = pd.read_csv(TARGET_STOCKS_CSV)

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

def main():
    """pkl → json 変換メイン処理"""
    logging.info("="*60)
    logging.info("CONVERT PRICE DATA TO JSON (OHLCV ONLY)")
    logging.info("="*60)

    if not os.path.exists(TEMP_PRICE_PKL):
        logging.error(f"Price data not found: {TEMP_PRICE_PKL}")
        return False

    logging.info(f"Loading price data from {TEMP_PRICE_PKL}...")
    price_data = pd.read_pickle(TEMP_PRICE_PKL)
    logging.info(f"Loaded: {price_data.shape}")

    symbols_info = load_symbols_info()

    if not symbols_info:
        logging.error("No symbols info found")
        return False

    json_output = convert_to_json(price_data, symbols_info)

    with open(TEMP_PRICE_JSON, 'w') as f:
        json.dump(json_output, f)

    file_size_mb = os.path.getsize(TEMP_PRICE_JSON) / 1024 / 1024

    logging.info(f"\n{'='*60}")
    logging.info("✓ JSON SAVED (OHLCV only)")
    logging.info(f"{'='*60}")
    logging.info(f"Path: {TEMP_PRICE_JSON}")
    logging.info(f"Symbols: {len(json_output['symbols'])}")
    logging.info(f"Size: {file_size_mb:.2f} MB")
    logging.info(f"{'='*60}\n")

    return True

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)

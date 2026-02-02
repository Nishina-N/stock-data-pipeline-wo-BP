"""
2.5_add_indicators.py

価格データ（pickle）にテクニカル指標を追加してJSON形式に変換
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

def calculate_sma(series, period):
    """単純移動平均"""
    return series.rolling(window=period, min_periods=period).mean()

def calculate_ema(series, period):
    """指数移動平均"""
    return series.ewm(span=period, adjust=False).mean()

def calculate_rsi(series, period=14):
    """RSI"""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_atr(high, low, close, period=14):
    """ATR"""
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr

def calculate_vwap(high, low, close, volume):
    """VWAP（当日のみ）"""
    typical_price = (high + low + close) / 3
    return (typical_price * volume).cumsum() / volume.cumsum()

def add_technical_indicators_vectorized(price_data):
    """
    MultiIndex DataFrameにテクニカル指標を追加（ベクトル化版）
    
    price_data: MultiIndex DataFrame with columns like ('Open', 'AAPL'), ('Close', 'AAPL'), ...
    """
    logging.info("Adding technical indicators (vectorized)...")
    
    # 各銘柄ごとに指標を計算
    symbols = price_data.columns.get_level_values(1).unique()
    
    results = {}
    
    for i, symbol in enumerate(symbols, 1):
        if i % 500 == 0:
            logging.info(f"Progress: {i}/{len(symbols)} symbols")
        
        try:
            # 各銘柄のデータを抽出
            close = price_data['Close'][symbol]
            open_p = price_data['Open'][symbol]
            high = price_data['High'][symbol]
            low = price_data['Low'][symbol]
            volume = price_data['Volume'][symbol]
            
            # 指標計算
            sma20 = calculate_sma(close, 20)
            sma50 = calculate_sma(close, 50)
            sma200 = calculate_sma(close, 200)
            ema21 = calculate_ema(close, 21)
            rsi14 = calculate_rsi(close, 14)
            atr14 = calculate_atr(high, low, close, 14)
            vwap = calculate_vwap(high, low, close, volume)
            
            results[symbol] = {
                'open': open_p,
                'high': high,
                'low': low,
                'close': close,
                'volume': volume,
                'sma20': sma20,
                'sma50': sma50,
                'sma200': sma200,
                'ema21': ema21,
                'rsi14': rsi14,
                'atr14': atr14,
                'vwap': vwap
            }
        
        except Exception as e:
            logging.warning(f"Failed to calculate indicators for {symbol}: {e}")
    
    logging.info(f"✅ Calculated indicators for {len(results)} symbols")
    return results

def convert_to_json(indicator_data, symbols_info):
    """
    指標データをJSON形式に変換
    
    indicator_data: {symbol: {indicator: Series}}
    symbols_info: {symbol: {'name': ..., 'sector': ..., 'industry': ...}}
    """
    logging.info("Converting to JSON format...")
    
    output = {
        'lastUpdated': datetime.now().isoformat(),
        'symbols': {}
    }
    
    for symbol, data_dict in indicator_data.items():
        if symbol not in symbols_info:
            continue
        
        # DataFrameに変換
        df = pd.DataFrame(data_dict)
        
        # JSON用のリストに変換
        data_list = []
        for date, row in df.iterrows():
            data_list.append({
                'date': date.strftime('%Y-%m-%d'),
                'open': round(float(row['open']), 2) if not pd.isna(row['open']) else None,
                'high': round(float(row['high']), 2) if not pd.isna(row['high']) else None,
                'low': round(float(row['low']), 2) if not pd.isna(row['low']) else None,
                'close': round(float(row['close']), 2) if not pd.isna(row['close']) else None,
                'volume': int(row['volume']) if not pd.isna(row['volume']) else 0,
                'sma20': round(float(row['sma20']), 2) if not pd.isna(row['sma20']) else None,
                'sma50': round(float(row['sma50']), 2) if not pd.isna(row['sma50']) else None,
                'sma200': round(float(row['sma200']), 2) if not pd.isna(row['sma200']) else None,
                'ema21': round(float(row['ema21']), 2) if not pd.isna(row['ema21']) else None,
                'rsi14': round(float(row['rsi14']), 2) if not pd.isna(row['rsi14']) else None,
                'atr14': round(float(row['atr14']), 2) if not pd.isna(row['atr14']) else None,
                'vwap': round(float(row['vwap']), 2) if not pd.isna(row['vwap']) else None
            })
        
        output['symbols'][symbol] = {
            'name': symbols_info[symbol]['name'],
            'sector': symbols_info[symbol]['sector'],
            'industry': symbols_info[symbol]['industry'],
            'data': data_list
        }
    
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


    # ★ 追加: S&P500情報を追加（RRS計算用）
    if '^GSPC' not in symbols_info:
        symbols_info['^GSPC'] = {
            'name': 'S&P 500',
            'sector': 'Index',
            'industry': 'Index'
        }
        logging.info("Added ^GSPC (S&P 500) info for RRS calculation")

    
    logging.info(f"Loaded info for {len(symbols_info)} symbols")
    return symbols_info

def main():
    """テクニカル指標追加メイン処理"""
    logging.info("="*60)
    logging.info("ADD TECHNICAL INDICATORS")
    logging.info("="*60)
    
    # 価格データ読み込み
    if not os.path.exists(TEMP_PRICE_PKL):
        logging.error(f"Price data not found: {TEMP_PRICE_PKL}")
        return False
    
    logging.info(f"Loading price data from {TEMP_PRICE_PKL}...")
    price_data = pd.read_pickle(TEMP_PRICE_PKL)
    logging.info(f"Loaded: {price_data.shape}")
    
    # 銘柄情報読み込み
    symbols_info = load_symbols_info()
    
    if not symbols_info:
        logging.error("No symbols info found")
        return False
    
    # テクニカル指標追加
    indicator_data = add_technical_indicators_vectorized(price_data)
    
    if not indicator_data:
        logging.error("Failed to calculate indicators")
        return False
    
    # JSON変換
    json_output = convert_to_json(indicator_data, symbols_info)
    
    # 保存
    with open(TEMP_PRICE_JSON, 'w') as f:
        json.dump(json_output, f)
    
    file_size_mb = os.path.getsize(TEMP_PRICE_JSON) / 1024 / 1024
    
    logging.info(f"\n{'='*60}")
    logging.info("✓ INDICATORS ADDED & JSON SAVED")
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

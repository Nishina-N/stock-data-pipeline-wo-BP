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
    指標データをJSON形式に変換（最適化版）
    
    indicator_data: {symbol: {indicator: Series}}
    symbols_info: {symbol: {'name': ..., 'sector': ..., 'industry': ...}}
    """
    logging.info("Converting to JSON format (optimized)...")
    
    output = {
        'lastUpdated': datetime.now().isoformat(),
        'symbols': {}
    }
    
    for symbol, data_dict in indicator_data.items():
        if symbol not in symbols_info:
            continue
        
        # ★ DataFrameに変換
        df = pd.DataFrame(data_dict)
        
        # ★ 日付を一括変換
        dates = df.index.strftime('%Y-%m-%d').tolist()
        
        # ★ NumPy配列として取得（高速アクセス）
        open_vals = df['open'].values
        high_vals = df['high'].values
        low_vals = df['low'].values
        close_vals = df['close'].values
        volume_vals = df['volume'].values
        sma20_vals = df['sma20'].values
        sma50_vals = df['sma50'].values
        sma200_vals = df['sma200'].values
        ema21_vals = df['ema21'].values
        rsi14_vals = df['rsi14'].values
        atr14_vals = df['atr14'].values
        vwap_vals = df['vwap'].values
        
        # ★ リスト内包表記で一括変換
        data_list = [
            {
                'date': dates[i],
                'open': None if np.isnan(open_vals[i]) else round(float(open_vals[i]), 2),
                'high': None if np.isnan(high_vals[i]) else round(float(high_vals[i]), 2),
                'low': None if np.isnan(low_vals[i]) else round(float(low_vals[i]), 2),
                'close': None if np.isnan(close_vals[i]) else round(float(close_vals[i]), 2),
                'volume': 0 if np.isnan(volume_vals[i]) else int(volume_vals[i]),
                'sma20': None if np.isnan(sma20_vals[i]) else round(float(sma20_vals[i]), 2),
                'sma50': None if np.isnan(sma50_vals[i]) else round(float(sma50_vals[i]), 2),
                'sma200': None if np.isnan(sma200_vals[i]) else round(float(sma200_vals[i]), 2),
                'ema21': None if np.isnan(ema21_vals[i]) else round(float(ema21_vals[i]), 2),
                'rsi14': None if np.isnan(rsi14_vals[i]) else round(float(rsi14_vals[i]), 2),
                'atr14': None if np.isnan(atr14_vals[i]) else round(float(atr14_vals[i]), 2),
                'vwap': None if np.isnan(vwap_vals[i]) else round(float(vwap_vals[i]), 2)
            }
            for i in range(len(dates))
        ]
        
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

"""
2_fetch_price_data.py

Yahoo Financeから直近1000日分の価格データを取得
テクニカル指標も計算してJSON化
"""
import pandas as pd
import yfinance as yf
import numpy as np
from datetime import datetime, timedelta
import logging
import json
import os

DATA_FOLDER = "data"
TARGET_STOCKS_CSV = os.path.join(DATA_FOLDER, "target_stocks_latest.csv")
TEMP_PRICE_JSON = os.path.join(DATA_FOLDER, "temp_prices.json")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def calculate_sma(prices, period):
    """単純移動平均"""
    if len(prices) < period:
        return None
    return round(np.mean(prices[-period:]), 2)

def calculate_ema(prices, period):
    """指数移動平均"""
    if len(prices) < period:
        return None
    df = pd.Series(prices)
    ema = df.ewm(span=period, adjust=False).mean()
    return round(ema.iloc[-1], 2)

def calculate_rsi(prices, period=14):
    """RSI（Relative Strength Index）"""
    if len(prices) < period + 1:
        return None
    
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    
    if avg_loss == 0:
        return 100
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 2)

def calculate_atr(high_prices, low_prices, close_prices, period=14):
    """ATR（Average True Range）"""
    if len(high_prices) < period + 1:
        return None
    
    true_ranges = []
    for i in range(1, len(high_prices)):
        tr = max(
            high_prices[i] - low_prices[i],
            abs(high_prices[i] - close_prices[i-1]),
            abs(low_prices[i] - close_prices[i-1])
        )
        true_ranges.append(tr)
    
    atr = np.mean(true_ranges[-period:])
    return round(atr, 2)

def calculate_vwap(high_prices, low_prices, close_prices, volumes):
    """VWAP（Volume Weighted Average Price）- 当日のみ"""
    if not volumes or sum(volumes) == 0:
        return None
    
    typical_prices = [(h + l + c) / 3 for h, l, c in zip(high_prices, low_prices, close_prices)]
    vwap = sum(tp * v for tp, v in zip(typical_prices, volumes)) / sum(volumes)
    return round(vwap, 2)

def add_technical_indicators(stock_data):
    """テクニカル指標を追加"""
    if not stock_data:
        return stock_data
    
    close_prices = [d['close'] for d in stock_data if d['close'] is not None]
    open_prices = [d['open'] for d in stock_data if d['open'] is not None]
    high_prices = [d['high'] for d in stock_data if d['high'] is not None]
    low_prices = [d['low'] for d in stock_data if d['low'] is not None]
    volumes = [d['volume'] for d in stock_data if d['volume'] is not None]
    
    for i, data_point in enumerate(stock_data):
        close_up_to_i = close_prices[:i+1]
        high_up_to_i = high_prices[:i+1]
        low_up_to_i = low_prices[:i+1]
        volume_up_to_i = volumes[:i+1]
        
        # 移動平均
        data_point['sma20'] = calculate_sma(close_up_to_i, 20)
        data_point['sma50'] = calculate_sma(close_up_to_i, 50)
        data_point['sma200'] = calculate_sma(close_up_to_i, 200)
        
        # 指数移動平均
        data_point['ema21'] = calculate_ema(close_up_to_i, 21)
        
        # RSI
        data_point['rsi14'] = calculate_rsi(close_up_to_i, 14)
        
        # ATR
        data_point['atr14'] = calculate_atr(high_up_to_i, low_up_to_i, close_up_to_i, 14)
        
        # VWAP（当日のみ）
        data_point['vwap'] = calculate_vwap([high_up_to_i[-1]], [low_up_to_i[-1]], [close_up_to_i[-1]], [volume_up_to_i[-1]])
    
    return stock_data

def get_symbols_from_csv():
    """target_stocks_latest.csvから銘柄取得"""
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
    
    logging.info(f"Loaded {len(symbols_info)} symbols from CSV")
    return symbols_info

def download_price_data_minimal(symbols, days=1000):
    """直近N日分のデータを取得"""
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')
    
    logging.info(f"Downloading {len(symbols)} symbols: {start_date} to {end_date}")
    
    all_data = {}
    chunk_size = 50
    symbol_list = list(symbols.keys())
    
    for i in range(0, len(symbol_list), chunk_size):
        chunk = symbol_list[i:i + chunk_size]
        chunk_num = i // chunk_size + 1
        total_chunks = (len(symbol_list) + chunk_size - 1) // chunk_size
        
        try:
            logging.info(f"Chunk {chunk_num}/{total_chunks}...")
            data = yf.download(chunk, start=start_date, end=end_date, threads=False, progress=False)
            
            if not data.empty:
                for symbol in chunk:
                    try:
                        if symbol in data['Close'].columns:
                            stock_data = []
                            for date, row in data.iterrows():
                                stock_data.append({
                                    'date': date.strftime('%Y-%m-%d'),
                                    'open': float(row['Open'][symbol]) if not pd.isna(row['Open'][symbol]) else None,
                                    'high': float(row['High'][symbol]) if not pd.isna(row['High'][symbol]) else None,
                                    'low': float(row['Low'][symbol]) if not pd.isna(row['Low'][symbol]) else None,
                                    'close': float(row['Close'][symbol]) if not pd.isna(row['Close'][symbol]) else None,
                                    'volume': int(row['Volume'][symbol]) if not pd.isna(row['Volume'][symbol]) else 0
                                })
                            all_data[symbol] = stock_data
                    except Exception as e:
                        logging.warning(f"Failed to process {symbol}: {e}")
                
                logging.info(f"✓ Chunk {chunk_num}: {len([s for s in chunk if s in all_data])} symbols")
        
        except Exception as e:
            logging.error(f"✗ Chunk {chunk_num} error: {e}")
    
    return all_data

def save_temp_json(price_data, symbols_info):
    """一時JSONファイルに保存"""
    output = {
        'lastUpdated': datetime.now().isoformat(),
        'symbols': {}
    }
    
    for symbol, price_list in price_data.items():
        if symbol in symbols_info:
            # テクニカル指標を追加
            price_list_with_indicators = add_technical_indicators(price_list)
            
            output['symbols'][symbol] = {
                'name': symbols_info[symbol]['name'],
                'sector': symbols_info[symbol]['sector'],
                'industry': symbols_info[symbol]['industry'],
                'data': price_list_with_indicators
            }
    
    with open(TEMP_PRICE_JSON, 'w') as f:
        json.dump(output, f)
    
    logging.info(f"✅ Saved {len(output['symbols'])} symbols to {TEMP_PRICE_JSON}")
    return True

def main():
    """価格データ取得メイン処理"""
    symbols_info = get_symbols_from_csv()
    
    if not symbols_info:
        logging.error("No symbols found")
        return False
    
    price_data = download_price_data_minimal(symbols_info, days=1000)
    
    if not price_data:
        logging.error("Failed to download price data")
        return False
    
    return save_temp_json(price_data, symbols_info)

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)

"""
2_add_indicators.py

テクニカル指標を計算
入力: data/maintenance/temp_prices.pkl
出力: data/maintenance/temp_prices_with_indicators.pkl
"""
import os
import pandas as pd
import numpy as np
import logging
import pickle

DATA_FOLDER = "data"
MAINTENANCE_FOLDER = os.path.join(DATA_FOLDER, "maintenance")
INPUT_PKL = os.path.join(MAINTENANCE_FOLDER, "temp_prices.pkl")
OUTPUT_PKL = os.path.join(MAINTENANCE_FOLDER, "temp_prices_with_indicators.pkl")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def add_indicators_to_df(df):
    """
    MultiIndex DataFrameにテクニカル指標を追加（最適化版・警告なし）
    DataFrame fragmentationを回避し、データ長チェックを追加
    
    Args:
        df: yfinanceから取得したMultiIndex DataFrame
    
    Returns:
        DataFrame with indicators
    """
    logging.info("Calculating technical indicators...")
    
    symbols = df.columns.levels[0] if isinstance(df.columns, pd.MultiIndex) else [df.columns[0]]
    
    # 指標を一時的に保存する辞書
    indicator_dict = {}
    
    for i, symbol in enumerate(symbols):
        try:
            if isinstance(df.columns, pd.MultiIndex):
                symbol_data = df[symbol]
            else:
                symbol_data = df
            
            close = symbol_data['Close']
            high = symbol_data['High']
            low = symbol_data['Low']
            volume = symbol_data['Volume']
            
            # データ長チェック
            data_len = len(close.dropna())
            
            # 各指標に必要な最小データ長
            required_lengths = {
                'sma20': 20,
                'sma50': 50,
                'sma200': 200,
                'ema21': 21,
                'rsi14': 14,
                'atr14': 14,
                'vwap': 1
            }
            
            # 指標を計算して一時保存
            indicators = {}
            
            # SMA
            if data_len >= required_lengths['sma20']:
                indicators['sma20'] = close.rolling(window=20).mean()
            else:
                indicators['sma20'] = pd.Series(index=close.index, dtype=float)
            
            if data_len >= required_lengths['sma50']:
                indicators['sma50'] = close.rolling(window=50).mean()
            else:
                indicators['sma50'] = pd.Series(index=close.index, dtype=float)
            
            if data_len >= required_lengths['sma200']:
                indicators['sma200'] = close.rolling(window=200).mean()
            else:
                indicators['sma200'] = pd.Series(index=close.index, dtype=float)
            
            # EMA
            if data_len >= required_lengths['ema21']:
                indicators['ema21'] = close.ewm(span=21, adjust=False).mean()
            else:
                indicators['ema21'] = pd.Series(index=close.index, dtype=float)
            
            # RSI
            if data_len >= required_lengths['rsi14']:
                delta = close.diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                indicators['rsi14'] = 100 - (100 / (1 + rs))
            else:
                indicators['rsi14'] = pd.Series(index=close.index, dtype=float)
            
            # ATR
            if data_len >= required_lengths['atr14']:
                high_low = high - low
                high_close = np.abs(high - close.shift())
                low_close = np.abs(low - close.shift())
                tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
                indicators['atr14'] = tr.rolling(window=14).mean()
            else:
                indicators['atr14'] = pd.Series(index=close.index, dtype=float)
            
            # VWAP
            if data_len >= required_lengths['vwap']:
                indicators['vwap'] = (close * volume).cumsum() / volume.cumsum()
            else:
                indicators['vwap'] = pd.Series(index=close.index, dtype=float)
            
            # 辞書に保存（後でまとめて結合）
            indicator_dict[symbol] = indicators
            
            if (i + 1) % 500 == 0:
                logging.info(f"  Progress: {i+1}/{len(symbols)}")
        
        except Exception as e:
            logging.error(f"Failed to calculate indicators for {symbol}: {e}")
    
    # ★ 修正: 全指標を一度に結合（pd.concat使用）
    logging.info("Combining all indicators...")
    
    # 新しい列をリストに集める
    new_columns = []
    
    for symbol, indicators in indicator_dict.items():
        for indicator_name, indicator_series in indicators.items():
            # MultiIndex形式で列を作成
            indicator_series.name = (symbol, indicator_name)
            new_columns.append(indicator_series)
    
    # 一度にすべての列を結合
    if new_columns:
        new_df = pd.concat(new_columns, axis=1)
        df = pd.concat([df, new_df], axis=1)
    
    logging.info("✅ Technical indicators calculated")
    
    return df

def main():
    """メイン処理"""
    logging.info("="*60)
    logging.info("STEP 2: ADD TECHNICAL INDICATORS")
    logging.info("="*60)
    
    # データ読み込み
    if not os.path.exists(INPUT_PKL):
        logging.error(f"Input file not found: {INPUT_PKL}")
        logging.error("Please run 1_fetch_historical_prices.py first")
        return False
    
    logging.info(f"Loading data from {INPUT_PKL}...")
    with open(INPUT_PKL, 'rb') as f:
        df = pickle.load(f)
    
    logging.info(f"Loaded DataFrame shape: {df.shape}")
    
    # テクニカル指標計算
    df = add_indicators_to_df(df)
    
    # Pickle形式で保存
    logging.info(f"Saving to {OUTPUT_PKL}...")
    with open(OUTPUT_PKL, 'wb') as f:
        pickle.dump(df, f)
    
    logging.info("="*60)
    logging.info("✅ STEP 2 COMPLETED!")
    logging.info(f"Output: {OUTPUT_PKL}")
    logging.info("="*60)
    
    return True

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)
"""
3_calculate_rs.py

完全なRS/RRS計算
既存のcalculate_rs_scores4.pyのロジックを使用
- 3ヶ月リターン × 0.4
- 6ヶ月リターン × 0.2
- 9ヶ月リターン × 0.2
- 12ヶ月リターン × 0.2
"""
import json
import pandas as pd
import numpy as np
from datetime import datetime
import logging
import os

DATA_FOLDER = "data"
TEMP_PRICE_JSON = os.path.join(DATA_FOLDER, "temp_prices.json")
TEMP_RS_JSON = os.path.join(DATA_FOLDER, "temp_rs.json")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def calculate_individual_rs_vectorized(price_data, min_days=252):
    """
    Individual RS計算（ベクトル化版）
    
    RS = 3ヶ月リターン × 0.4
       + 6ヶ月リターン × 0.2
       + 9ヶ月リターン × 0.2
       + 12ヶ月リターン × 0.2
    """
    logging.info("Calculating Individual RS (vectorized)...")
    
    # 価格データをDataFrameに変換
    close_dict = {}
    for symbol, info in price_data['symbols'].items():
        data = info['data']
        if len(data) < min_days:
            continue
        
        closes = [d['close'] for d in data if d['close'] is not None]
        dates = [d['date'] for d in data if d['close'] is not None]
        
        if len(closes) < min_days:
            continue
        
        close_dict[symbol] = pd.Series(closes, index=pd.to_datetime(dates))
    
    if not close_dict:
        logging.error("No sufficient data for RS calculation")
        return {}
    
    df_close = pd.DataFrame(close_dict)
    
    # リターン計算（営業日ベース）
    ret_3m = df_close.pct_change(periods=63).iloc[-1] * 100   # 約3ヶ月
    ret_6m = df_close.pct_change(periods=126).iloc[-1] * 100  # 約6ヶ月
    ret_9m = df_close.pct_change(periods=189).iloc[-1] * 100  # 約9ヶ月
    ret_12m = df_close.pct_change(periods=252).iloc[-1] * 100 # 約12ヶ月
    
    # RS計算（加重平均）
    rs = (ret_3m * 0.4 + ret_6m * 0.2 + ret_9m * 0.2 + ret_12m * 0.2)
    
    # 欠損値を除外
    rs = rs.dropna()
    
    logging.info(f"Calculated RS for {len(rs)} symbols")
    
    return rs.to_dict()

def calculate_percentiles_vectorized(rs_dict):
    """パーセンタイル化（1-99）"""
    if not rs_dict:
        return {}
    
    values = np.array(list(rs_dict.values()))
    
    percentiles = {}
    for symbol, value in rs_dict.items():
        percentile = (np.sum(values < value) / len(values)) * 98 + 1
        percentiles[symbol] = round(percentile, 2)
    
    logging.info(f"Converted to percentiles: {len(percentiles)} symbols")
    return percentiles

def calculate_atr(high_prices, low_prices, close_prices, period=14):
    """ATR計算"""
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
    return atr

def calculate_rrs_from_prices(price_data, atr_length=14, rrs_length=12):
    """
    RRS計算（Pine Scriptロジック）
    """
    logging.info("Calculating RRS (Pine Script logic)...")
    
    rrs_scores = {}
    
    # S&P500データを取得
    spy_symbol = '^GSPC'
    spy_data = price_data['symbols'].get(spy_symbol, {}).get('data', [])
    
    if not spy_data or len(spy_data) < rrs_length + atr_length:
        logging.warning("S&P500 data not available for RRS calculation")
        return {}
    
    spy_closes = [d['close'] for d in spy_data if d['close'] is not None]
    spy_highs = [d['high'] for d in spy_data if d['high'] is not None]
    spy_lows = [d['low'] for d in spy_data if d['low'] is not None]
    
    spy_atr = calculate_atr(spy_highs, spy_lows, spy_closes, atr_length)
    
    if not spy_atr or spy_atr == 0:
        logging.warning("S&P500 ATR is zero or None")
        return {}
    
    # 各銘柄のRRS計算
    for symbol, info in price_data['symbols'].items():
        if symbol == spy_symbol:
            continue
        
        data = info['data']
        
        if len(data) < rrs_length + atr_length:
            continue
        
        closes = [d['close'] for d in data if d['close'] is not None]
        highs = [d['high'] for d in data if d['high'] is not None]
        lows = [d['low'] for d in data if d['low'] is not None]
        
        if len(closes) < rrs_length + atr_length:
            continue
        
        stock_atr = calculate_atr(highs, lows, closes, atr_length)
        
        if not stock_atr or stock_atr == 0:
            continue
        
        # RRS Daily計算
        rrs_daily = []
        min_len = min(len(closes), len(spy_closes))
        
        for i in range(1, min_len):
            delta_stock = closes[i] - closes[i-1]
            delta_spy = spy_closes[i] - spy_closes[i-1]
            
            expected = delta_spy * (stock_atr / spy_atr)
            rrs_day = (delta_stock - expected) / stock_atr
            rrs_daily.append(rrs_day)
        
        # RRS = sum(rrs_daily, rrs_length)
        if len(rrs_daily) >= rrs_length:
            rrs = sum(rrs_daily[-rrs_length:])
            rrs_scores[symbol] = round(rrs, 2)
    
    logging.info(f"Calculated RRS for {len(rrs_scores)} symbols")
    return rrs_scores

def save_rs_json(rs_scores, rrs_scores, price_data):
    """RS + RRS結果をJSON保存"""
    output = {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'scores': []
    }
    
    for symbol in rs_scores.keys():
        if symbol in price_data['symbols']:
            info = price_data['symbols'][symbol]
            output['scores'].append({
                'ticker': symbol,
                'rs': rs_scores.get(symbol, 50),
                'rrs': rrs_scores.get(symbol, 0),
                'rank': 0,
                'sector': info['sector'],
                'industry': info['industry']
            })
    
    # ランク付け（RSベース）
    output['scores'].sort(key=lambda x: x['rs'], reverse=True)
    for i, score in enumerate(output['scores']):
        score['rank'] = i + 1
    
    output['totalStocks'] = len(output['scores'])
    
    with open(TEMP_RS_JSON, 'w') as f:
        json.dump(output, f, indent=2)
    
    logging.info(f"✅ Saved RS + RRS scores to {TEMP_RS_JSON}")
    logging.info(f"   Total stocks: {len(output['scores'])}")
    logging.info(f"   RS range: {min(rs_scores.values()):.2f} - {max(rs_scores.values()):.2f}")
    if rrs_scores:
        logging.info(f"   RRS range: {min(rrs_scores.values()):.2f} - {max(rrs_scores.values()):.2f}")
    
    return True

def main():
    """RS + RRS計算メイン処理"""
    logging.info("="*60)
    logging.info("RS/RRS CALCULATION")
    logging.info("="*60)
    
    if not os.path.exists(TEMP_PRICE_JSON):
        logging.error(f"Price data not found: {TEMP_PRICE_JSON}")
        return False
    
    with open(TEMP_PRICE_JSON, 'r') as f:
        price_data = json.load(f)
    
    logging.info(f"Loaded price data: {len(price_data['symbols'])} symbols")
    
    # Individual RS計算
    rs_raw = calculate_individual_rs_vectorized(price_data, min_days=252)
    
    if not rs_raw:
        logging.error("Failed to calculate RS")
        return False
    
    # パーセンタイル化
    rs_scores = calculate_percentiles_vectorized(rs_raw)
    
    # RRS計算
    rrs_scores = calculate_rrs_from_prices(price_data)
    
    # 保存
    if save_rs_json(rs_scores, rrs_scores, price_data):
        logging.info("="*60)
        logging.info("✅ RS/RRS calculation completed!")
        logging.info("="*60)
        return True
    else:
        return False

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)

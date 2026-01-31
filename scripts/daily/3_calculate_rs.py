"""
3_calculate_rs.py

完全なRS/RRS計算（Individual, Sector, Industry）
時系列データとして500日分を出力
"""
import json
import pandas as pd
import numpy as np
from datetime import datetime
import logging
import os

DATA_FOLDER = "data"
TARGET_STOCKS_CSV = os.path.join(DATA_FOLDER, "target_stocks_latest.csv")
TEMP_PRICE_JSON = os.path.join(DATA_FOLDER, "temp_prices.json")
TEMP_RS_INDIVIDUAL_JSON = os.path.join(DATA_FOLDER, "temp_rs_individual.json")
TEMP_RS_SECTOR_JSON = os.path.join(DATA_FOLDER, "temp_rs_sector.json")
TEMP_RS_INDUSTRY_JSON = os.path.join(DATA_FOLDER, "temp_rs_industry.json")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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

def calculate_individual_rs_vectorized(price_data, min_days=252):
    """
    Individual RS計算（ベクトル化版）
    全日付分のRSを計算
    
    RS = 3ヶ月リターン × 0.4
       + 6ヶ月リターン × 0.2
       + 9ヶ月リターン × 0.2
       + 12ヶ月リターン × 0.2
    """
    logging.info("Calculating Individual RS (vectorized, all dates)...")
    
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
        return None
    
    df_close = pd.DataFrame(close_dict)
    
    # リターン計算（各日付ごと）
    ret_3m = df_close.pct_change(periods=63) * 100   # 約3ヶ月
    ret_6m = df_close.pct_change(periods=126) * 100  # 約6ヶ月
    ret_9m = df_close.pct_change(periods=189) * 100  # 約9ヶ月
    ret_12m = df_close.pct_change(periods=252) * 100 # 約12ヶ月
    
    # RS計算（加重平均）
    rs = (ret_3m * 0.4 + ret_6m * 0.2 + ret_9m * 0.2 + ret_12m * 0.2)
    
    logging.info(f"Calculated RS for {len(rs.columns)} symbols, {len(rs)} dates")
    
    return rs

def calculate_percentiles_vectorized(rs_df):
    """
    パーセンタイル化（1-99）
    各日付ごとにパーセンタイル計算
    """
    logging.info("Converting to percentiles (all dates)...")
    
    percentiles_df = rs_df.copy()
    
    for date in rs_df.index:
        values = rs_df.loc[date].dropna().values
        
        if len(values) == 0:
            continue
        
        for symbol in rs_df.columns:
            value = rs_df.loc[date, symbol]
            
            if pd.isna(value):
                percentiles_df.loc[date, symbol] = np.nan
            else:
                percentile = (np.sum(values < value) / len(values)) * 98 + 1
                percentiles_df.loc[date, symbol] = round(percentile, 2)
    
    logging.info(f"Converted to percentiles: {percentiles_df.shape}")
    return percentiles_df

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
    RRS計算（全日付分）
    """
    logging.info("Calculating RRS (all dates)...")
    
    # S&P500データを取得
    spy_symbol = '^GSPC'
    spy_data = price_data['symbols'].get(spy_symbol, {}).get('data', [])
    
    if not spy_data or len(spy_data) < rrs_length + atr_length:
        logging.warning("S&P500 data not available for RRS calculation")
        return None
    
    spy_closes = [d['close'] for d in spy_data if d['close'] is not None]
    spy_highs = [d['high'] for d in spy_data if d['high'] is not None]
    spy_lows = [d['low'] for d in spy_data if d['low'] is not None]
    spy_dates = [d['date'] for d in spy_data if d['close'] is not None]
    
    spy_atr = calculate_atr(spy_highs, spy_lows, spy_closes, atr_length)
    
    if not spy_atr or spy_atr == 0:
        logging.warning("S&P500 ATR is zero or None")
        return None
    
    # 各銘柄のRRS計算（DataFrame形式で格納）
    rrs_dict = {}
    
    for symbol, info in price_data['symbols'].items():
        if symbol == spy_symbol:
            continue
        
        data = info['data']
        
        if len(data) < rrs_length + atr_length:
            continue
        
        closes = [d['close'] for d in data if d['close'] is not None]
        highs = [d['high'] for d in data if d['high'] is not None]
        lows = [d['low'] for d in data if d['low'] is not None]
        dates = [d['date'] for d in data if d['close'] is not None]
        
        if len(closes) < rrs_length + atr_length:
            continue
        
        stock_atr = calculate_atr(highs, lows, closes, atr_length)
        
        if not stock_atr or stock_atr == 0:
            continue
        
        # RRS Daily計算（時系列）
        rrs_values = []
        min_len = min(len(closes), len(spy_closes))
        
        for i in range(1, min_len):
            if i < rrs_length:
                rrs_values.append(np.nan)
                continue
            
            # 直近rrs_length日分のデイリーRRSを計算
            daily_rrs_sum = 0
            for j in range(i - rrs_length + 1, i + 1):
                delta_stock = closes[j] - closes[j-1]
                delta_spy = spy_closes[j] - spy_closes[j-1]
                
                expected = delta_spy * (stock_atr / spy_atr)
                rrs_day = (delta_stock - expected) / stock_atr
                daily_rrs_sum += rrs_day
            
            rrs_values.append(round(daily_rrs_sum, 2))
        
        # 最初の日は計算できないのでNaN
        rrs_values.insert(0, np.nan)
        
        rrs_dict[symbol] = pd.Series(rrs_values[:len(dates)], index=pd.to_datetime(dates[:len(rrs_values)]))
    
    if not rrs_dict:
        return None
    
    rrs_df = pd.DataFrame(rrs_dict)
    
    logging.info(f"Calculated RRS for {len(rrs_df.columns)} symbols, {len(rrs_df)} dates")
    return rrs_df

def calculate_sector_rs_weighted(rs_df, symbols_info, price_data):
    """
    Sector RS計算（時価総額加重平均）
    """
    logging.info("Calculating Sector RS (weighted)...")
    
    # セクター別にグループ化
    sector_symbols = {}
    for symbol in rs_df.columns:
        if symbol not in symbols_info:
            continue
        sector = symbols_info[symbol]['sector']
        if sector not in sector_symbols:
            sector_symbols[sector] = []
        sector_symbols[sector].append(symbol)
    
    # 各日付ごとにセクターRSを計算
    sector_rs_dict = {}
    
    for sector, symbols in sector_symbols.items():
        # 各銘柄の時価総額を取得（最新の価格 × volume を簡易的な重みとして使用）
        weights = {}
        for symbol in symbols:
            if symbol in price_data['symbols']:
                data = price_data['symbols'][symbol]['data']
                if data:
                    latest = data[-1]
                    weights[symbol] = latest.get('close', 1) * latest.get('volume', 1)
        
        # 加重平均でセクターRSを計算
        sector_rs_values = []
        for date in rs_df.index:
            weighted_sum = 0
            total_weight = 0
            
            for symbol in symbols:
                if symbol in rs_df.columns:
                    rs_value = rs_df.loc[date, symbol]
                    if not pd.isna(rs_value):
                        weight = weights.get(symbol, 1)
                        weighted_sum += rs_value * weight
                        total_weight += weight
            
            if total_weight > 0:
                sector_rs_values.append(round(weighted_sum / total_weight, 2))
            else:
                sector_rs_values.append(np.nan)
        
        sector_rs_dict[sector] = pd.Series(sector_rs_values, index=rs_df.index)
    
    sector_rs_df = pd.DataFrame(sector_rs_dict)
    
    # パーセンタイル化
    sector_rs_percentile = calculate_percentiles_vectorized(sector_rs_df)
    
    logging.info(f"Calculated Sector RS for {len(sector_rs_df.columns)} sectors")
    return sector_rs_percentile

def calculate_industry_rs_weighted(rs_df, symbols_info, price_data):
    """
    Industry RS計算（時価総額加重平均）
    """
    logging.info("Calculating Industry RS (weighted)...")
    
    # 業種別にグループ化
    industry_symbols = {}
    for symbol in rs_df.columns:
        if symbol not in symbols_info:
            continue
        industry = symbols_info[symbol]['industry']
        if industry not in industry_symbols:
            industry_symbols[industry] = []
        industry_symbols[industry].append(symbol)
    
    # 各日付ごとに業種RSを計算
    industry_rs_dict = {}
    
    for industry, symbols in industry_symbols.items():
        # 加重平均用の重み
        weights = {}
        for symbol in symbols:
            if symbol in price_data['symbols']:
                data = price_data['symbols'][symbol]['data']
                if data:
                    latest = data[-1]
                    weights[symbol] = latest.get('close', 1) * latest.get('volume', 1)
        
        industry_rs_values = []
        for date in rs_df.index:
            weighted_sum = 0
            total_weight = 0
            
            for symbol in symbols:
                if symbol in rs_df.columns:
                    rs_value = rs_df.loc[date, symbol]
                    if not pd.isna(rs_value):
                        weight = weights.get(symbol, 1)
                        weighted_sum += rs_value * weight
                        total_weight += weight
            
            if total_weight > 0:
                industry_rs_values.append(round(weighted_sum / total_weight, 2))
            else:
                industry_rs_values.append(np.nan)
        
        industry_rs_dict[industry] = pd.Series(industry_rs_values, index=rs_df.index)
    
    industry_rs_df = pd.DataFrame(industry_rs_dict)
    
    # パーセンタイル化
    industry_rs_percentile = calculate_percentiles_vectorized(industry_rs_df)
    
    logging.info(f"Calculated Industry RS for {len(industry_rs_df.columns)} industries")
    return industry_rs_percentile

def save_rs_json(rs_df, rrs_df, sector_rs_df, industry_rs_df, symbols_info, output_days=500):
    """
    RS/RRS結果をJSON保存（直近500日分）
    """
    logging.info(f"Saving RS/RRS data (last {output_days} days)...")
    
    # 直近500日分を抽出
    rs_recent = rs_df.tail(output_days)
    rrs_recent = rrs_df.tail(output_days) if rrs_df is not None else None
    sector_rs_recent = sector_rs_df.tail(output_days)
    industry_rs_recent = industry_rs_df.tail(output_days)
    
    # Individual RS/RRS
    individual_output = {
        'startDate': rs_recent.index[0].strftime('%Y-%m-%d'),
        'endDate': rs_recent.index[-1].strftime('%Y-%m-%d'),
        'days': len(rs_recent),
        'data': [],
        'totalStocks': len(rs_recent.columns)
    }
    
    for date in rs_recent.index:
        date_scores = []
        
        for symbol in rs_recent.columns:
            rs_value = rs_recent.loc[date, symbol]
            rrs_value = rrs_recent.loc[date, symbol] if rrs_recent is not None else 0
            
            if pd.isna(rs_value):
                continue
            
            # ランク計算（その日の順位）
            values_at_date = rs_recent.loc[date].dropna()
            rank = (values_at_date > rs_value).sum() + 1
            
            date_scores.append({
                'ticker': symbol,
                'rs': round(float(rs_value), 2),
                'rrs': round(float(rrs_value), 2) if not pd.isna(rrs_value) else 0,
                'rank': int(rank),
                'sector': symbols_info.get(symbol, {}).get('sector', 'N/A'),
                'industry': symbols_info.get(symbol, {}).get('industry', 'N/A')
            })
        
        individual_output['data'].append({
            'date': date.strftime('%Y-%m-%d'),
            'scores': sorted(date_scores, key=lambda x: x['rs'], reverse=True)
        })
    
    with open(TEMP_RS_INDIVIDUAL_JSON, 'w') as f:
        json.dump(individual_output, f)
    
    logging.info(f"✅ Saved Individual RS to {TEMP_RS_INDIVIDUAL_JSON}")
    
    # Sector RS
    sector_output = {
        'startDate': sector_rs_recent.index[0].strftime('%Y-%m-%d'),
        'endDate': sector_rs_recent.index[-1].strftime('%Y-%m-%d'),
        'days': len(sector_rs_recent),
        'data': [],
        'totalSectors': len(sector_rs_recent.columns)
    }
    
    for date in sector_rs_recent.index:
        date_scores = []
        
        for sector in sector_rs_recent.columns:
            rs_value = sector_rs_recent.loc[date, sector]
            
            if pd.isna(rs_value):
                continue
            
            values_at_date = sector_rs_recent.loc[date].dropna()
            rank = (values_at_date > rs_value).sum() + 1
            
            # 銘柄数カウント
            stock_count = sum(1 for s, info in symbols_info.items() if info.get('sector') == sector)
            
            date_scores.append({
                'sector': sector,
                'rs': round(float(rs_value), 2),
                'rank': int(rank),
                'stockCount': stock_count
            })
        
        sector_output['data'].append({
            'date': date.strftime('%Y-%m-%d'),
            'scores': sorted(date_scores, key=lambda x: x['rs'], reverse=True)
        })
    
    with open(TEMP_RS_SECTOR_JSON, 'w') as f:
        json.dump(sector_output, f)
    
    logging.info(f"✅ Saved Sector RS to {TEMP_RS_SECTOR_JSON}")
    
    # Industry RS
    industry_output = {
        'startDate': industry_rs_recent.index[0].strftime('%Y-%m-%d'),
        'endDate': industry_rs_recent.index[-1].strftime('%Y-%m-%d'),
        'days': len(industry_rs_recent),
        'data': [],
        'totalIndustries': len(industry_rs_recent.columns)
    }
    
    for date in industry_rs_recent.index:
        date_scores = []
        
        for industry in industry_rs_recent.columns:
            rs_value = industry_rs_recent.loc[date, industry]
            
            if pd.isna(rs_value):
                continue
            
            values_at_date = industry_rs_recent.loc[date].dropna()
            rank = (values_at_date > rs_value).sum() + 1
            
            # セクター特定
            sector = 'N/A'
            for s, info in symbols_info.items():
                if info.get('industry') == industry:
                    sector = info.get('sector', 'N/A')
                    break
            
            stock_count = sum(1 for s, info in symbols_info.items() if info.get('industry') == industry)
            
            date_scores.append({
                'industry': industry,
                'sector': sector,
                'rs': round(float(rs_value), 2),
                'rank': int(rank),
                'stockCount': stock_count
            })
        
        industry_output['data'].append({
            'date': date.strftime('%Y-%m-%d'),
            'scores': sorted(date_scores, key=lambda x: x['rs'], reverse=True)
        })
    
    with open(TEMP_RS_INDUSTRY_JSON, 'w') as f:
        json.dump(industry_output, f)
    
    logging.info(f"✅ Saved Industry RS to {TEMP_RS_INDUSTRY_JSON}")
    
    return True

def main():
    """RS/RRS計算メイン処理"""
    logging.info("="*60)
    logging.info("RS/RRS CALCULATION (ALL TYPES)")
    logging.info("="*60)
    
    # 価格データ読み込み
    if not os.path.exists(TEMP_PRICE_JSON):
        logging.error(f"Price data not found: {TEMP_PRICE_JSON}")
        return False
    
    with open(TEMP_PRICE_JSON, 'r') as f:
        price_data = json.load(f)
    
    logging.info(f"Loaded price data: {len(price_data['symbols'])} symbols")
    
    # 銘柄情報読み込み
    symbols_info = load_symbols_info()
    
    if not symbols_info:
        logging.error("No symbols info found")
        return False
    
    # Individual RS計算
    rs_raw = calculate_individual_rs_vectorized(price_data, min_days=252)
    
    if rs_raw is None or rs_raw.empty:
        logging.error("Failed to calculate Individual RS")
        return False
    
    # パーセンタイル化
    rs_percentile = calculate_percentiles_vectorized(rs_raw)
    
    # RRS計算
    rrs_df = calculate_rrs_from_prices(price_data)
    
    # Sector RS計算
    sector_rs_df = calculate_sector_rs_weighted(rs_percentile, symbols_info, price_data)
    
    # Industry RS計算
    industry_rs_df = calculate_industry_rs_weighted(rs_percentile, symbols_info, price_data)
    
    # 保存
    if save_rs_json(rs_percentile, rrs_df, sector_rs_df, industry_rs_df, symbols_info, output_days=500):
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

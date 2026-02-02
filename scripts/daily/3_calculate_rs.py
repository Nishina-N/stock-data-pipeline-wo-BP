"""
3_calculate_rs.py

完全なRS/RRS計算（Individual, Sector, Industry）
RRSパーセンタイル化、Sector/Industry RRS計算を含む完全版
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

# 出力ファイル（6種類）
TEMP_RS_INDIVIDUAL_JSON = os.path.join(DATA_FOLDER, "temp_rs_individual.json")
TEMP_RRS_INDIVIDUAL_JSON = os.path.join(DATA_FOLDER, "temp_rrs_individual.json")
TEMP_RS_SECTOR_JSON = os.path.join(DATA_FOLDER, "temp_rs_sector.json")
TEMP_RRS_SECTOR_JSON = os.path.join(DATA_FOLDER, "temp_rrs_sector.json")
TEMP_RS_INDUSTRY_JSON = os.path.join(DATA_FOLDER, "temp_rs_industry.json")
TEMP_RRS_INDUSTRY_JSON = os.path.join(DATA_FOLDER, "temp_rrs_industry.json")

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
    """Individual RS計算（生値）"""
    logging.info("Calculating Individual RS (raw)...")
    
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
    
    # リターン計算
    ret_3m = df_close.pct_change(periods=63, fill_method=None) * 100
    ret_6m = df_close.pct_change(periods=126, fill_method=None) * 100
    ret_9m = df_close.pct_change(periods=189, fill_method=None) * 100
    ret_12m = df_close.pct_change(periods=252, fill_method=None) * 100
    
    # RS計算
    rs_raw = (ret_3m * 0.4 + ret_6m * 0.2 + ret_9m * 0.2 + ret_12m * 0.2)
    
    logging.info(f"Calculated RS (raw) for {len(rs_raw.columns)} symbols, {len(rs_raw)} dates")
    return rs_raw

def calculate_percentiles_vectorized(df, name="data"):
    """パーセンタイル化（1-99）"""
    logging.info(f"Converting {name} to percentiles...")
    
    percentiles_df = df.rank(axis=1, pct=True) * 98 + 1
    
    logging.info(f"Converted {name} to percentiles: {percentiles_df.shape}")
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
    """RRS計算（生値）"""
    logging.info("Calculating RRS (raw)...")
    
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
    
    # 各銘柄のRRS計算
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
        
        # RRS Daily計算
        rrs_values = []
        min_len = min(len(closes), len(spy_closes))
        
        for i in range(1, min_len):
            if i < rrs_length:
                rrs_values.append(np.nan)
                continue
            
            daily_rrs_sum = 0
            for j in range(i - rrs_length + 1, i + 1):
                delta_stock = closes[j] - closes[j-1]
                delta_spy = spy_closes[j] - spy_closes[j-1]
                
                expected = delta_spy * (stock_atr / spy_atr)
                rrs_day = (delta_stock - expected) / stock_atr
                daily_rrs_sum += rrs_day
            
            rrs_values.append(daily_rrs_sum)
        
        rrs_values.insert(0, np.nan)
        
        rrs_dict[symbol] = pd.Series(rrs_values[:len(dates)], index=pd.to_datetime(dates[:len(rrs_values)]))
    
    if not rrs_dict:
        return None
    
    rrs_df = pd.DataFrame(rrs_dict)
    
    logging.info(f"Calculated RRS (raw) for {len(rrs_df.columns)} symbols, {len(rrs_df)} dates")
    return rrs_df

def calculate_sector_rrs_weighted(rrs_df, symbols_info, price_data):
    """Sector RRS計算（加重平均）"""
    logging.info("Calculating Sector RRS (weighted)...")
    
    # セクター別にグループ化
    sector_symbols = {}
    for symbol in rrs_df.columns:
        if symbol not in symbols_info:
            continue
        sector = symbols_info[symbol]['sector']
        if sector and sector != 'N/A':
            if sector not in sector_symbols:
                sector_symbols[sector] = []
            sector_symbols[sector].append(symbol)
    
    # 重み計算（最新の価格 × volume）
    weights = {}
    for symbol in rrs_df.columns:
        if symbol in price_data['symbols']:
            data = price_data['symbols'][symbol]['data']
            if data and len(data) > 0:
                latest = data[-1]
                close_price = latest.get('close')
                volume = latest.get('volume')
                
                if close_price is not None and volume is not None:
                    weights[symbol] = close_price * volume
                else:
                    weights[symbol] = 1
            else:
                weights[symbol] = 1
        else:
            weights[symbol] = 1
    
    # 加重平均でセクターRRSを計算
    sector_rrs_dict = {}
    
    for sector, symbols in sector_symbols.items():
        sector_rrs_values = []
        for date in rrs_df.index:
            weighted_sum = 0
            total_weight = 0
            
            for symbol in symbols:
                if symbol in rrs_df.columns:
                    rrs_value = rrs_df.loc[date, symbol]
                    if not pd.isna(rrs_value):
                        weight = weights.get(symbol, 1)
                        weighted_sum += rrs_value * weight
                        total_weight += weight
            
            if total_weight > 0:
                sector_rrs_values.append(weighted_sum / total_weight)
            else:
                sector_rrs_values.append(np.nan)
        
        sector_rrs_dict[sector] = pd.Series(sector_rrs_values, index=rrs_df.index)
    
    sector_rrs_df = pd.DataFrame(sector_rrs_dict)
    
    logging.info(f"Calculated Sector RRS (raw) for {len(sector_rrs_df.columns)} sectors")
    return sector_rrs_df

def calculate_industry_rrs_weighted(rrs_df, symbols_info, price_data):
    """Industry RRS計算（加重平均）"""
    logging.info("Calculating Industry RRS (weighted)...")
    
    # 業種別にグループ化
    industry_symbols = {}
    for symbol in rrs_df.columns:
        if symbol not in symbols_info:
            continue
        industry = symbols_info[symbol]['industry']
        if industry and industry != 'N/A':
            if industry not in industry_symbols:
                industry_symbols[industry] = []
            industry_symbols[industry].append(symbol)
    
    # 重み計算
    weights = {}
    for symbol in rrs_df.columns:
        if symbol in price_data['symbols']:
            data = price_data['symbols'][symbol]['data']
            if data and len(data) > 0:
                latest = data[-1]
                close_price = latest.get('close')
                volume = latest.get('volume')
                
                if close_price is not None and volume is not None:
                    weights[symbol] = close_price * volume
                else:
                    weights[symbol] = 1
            else:
                weights[symbol] = 1
        else:
            weights[symbol] = 1
    
    industry_rrs_dict = {}
    
    for industry, symbols in industry_symbols.items():
        industry_rrs_values = []
        for date in rrs_df.index:
            weighted_sum = 0
            total_weight = 0
            
            for symbol in symbols:
                if symbol in rrs_df.columns:
                    rrs_value = rrs_df.loc[date, symbol]
                    if not pd.isna(rrs_value):
                        weight = weights.get(symbol, 1)
                        weighted_sum += rrs_value * weight
                        total_weight += weight
            
            if total_weight > 0:
                industry_rrs_values.append(weighted_sum / total_weight)
            else:
                industry_rrs_values.append(np.nan)
        
        industry_rrs_dict[industry] = pd.Series(industry_rrs_values, index=rrs_df.index)
    
    industry_rrs_df = pd.DataFrame(industry_rrs_dict)
    
    logging.info(f"Calculated Industry RRS (raw) for {len(industry_rrs_df.columns)} industries")
    return industry_rrs_df

def calculate_sector_rs_weighted(rs_df, symbols_info, price_data):
    """Sector RS計算（加重平均）"""
    logging.info("Calculating Sector RS (weighted)...")
    
    # セクター別にグループ化
    sector_symbols = {}
    for symbol in rs_df.columns:
        if symbol not in symbols_info:
            continue
        sector = symbols_info[symbol]['sector']
        if sector and sector != 'N/A':
            if sector not in sector_symbols:
                sector_symbols[sector] = []
            sector_symbols[sector].append(symbol)
    
    # 重み計算
    weights = {}
    for symbol in rs_df.columns:
        if symbol in price_data['symbols']:
            data = price_data['symbols'][symbol]['data']
            if data and len(data) > 0:
                latest = data[-1]
                close_price = latest.get('close')
                volume = latest.get('volume')
                
                if close_price is not None and volume is not None:
                    weights[symbol] = close_price * volume
                else:
                    weights[symbol] = 1
            else:
                weights[symbol] = 1
        else:
            weights[symbol] = 1
    
    # 加重平均でセクターRSを計算
    sector_rs_dict = {}
    
    for sector, symbols in sector_symbols.items():
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
                sector_rs_values.append(weighted_sum / total_weight)
            else:
                sector_rs_values.append(np.nan)
        
        sector_rs_dict[sector] = pd.Series(sector_rs_values, index=rs_df.index)
    
    sector_rs_df = pd.DataFrame(sector_rs_dict)
    
    logging.info(f"Calculated Sector RS (raw) for {len(sector_rs_df.columns)} sectors")
    return sector_rs_df

def calculate_industry_rs_weighted(rs_df, symbols_info, price_data):
    """Industry RS計算（加重平均）"""
    logging.info("Calculating Industry RS (weighted)...")
    
    # 業種別にグループ化
    industry_symbols = {}
    for symbol in rs_df.columns:
        if symbol not in symbols_info:
            continue
        industry = symbols_info[symbol]['industry']
        if industry and industry != 'N/A':
            if industry not in industry_symbols:
                industry_symbols[industry] = []
            industry_symbols[industry].append(symbol)
    
    # 重み計算
    weights = {}
    for symbol in rs_df.columns:
        if symbol in price_data['symbols']:
            data = price_data['symbols'][symbol]['data']
            if data and len(data) > 0:
                latest = data[-1]
                close_price = latest.get('close')
                volume = latest.get('volume')
                
                if close_price is not None and volume is not None:
                    weights[symbol] = close_price * volume
                else:
                    weights[symbol] = 1
            else:
                weights[symbol] = 1
        else:
            weights[symbol] = 1
    
    industry_rs_dict = {}
    
    for industry, symbols in industry_symbols.items():
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
                industry_rs_values.append(weighted_sum / total_weight)
            else:
                industry_rs_values.append(np.nan)
        
        industry_rs_dict[industry] = pd.Series(industry_rs_values, index=rs_df.index)
    
    industry_rs_df = pd.DataFrame(industry_rs_dict)
    
    logging.info(f"Calculated Industry RS (raw) for {len(industry_rs_df.columns)} industries")
    return industry_rs_df

def save_results_json(rs_percentile, rrs_percentile, sector_rs_percentile, sector_rrs_percentile, 
                      industry_rs_percentile, industry_rrs_percentile, symbols_info, output_days=500):
    """
    結果を6つのJSONファイルに保存（直近500日分）
    """
    logging.info(f"Saving results (last {output_days} days)...")
    
    # 直近500日分を抽出
    rs_recent = rs_percentile.tail(output_days)
    rrs_recent = rrs_percentile.tail(output_days) if rrs_percentile is not None else None
    sector_rs_recent = sector_rs_percentile.tail(output_days)
    sector_rrs_recent = sector_rrs_percentile.tail(output_days) if sector_rrs_percentile is not None else None
    industry_rs_recent = industry_rs_percentile.tail(output_days)
    industry_rrs_recent = industry_rrs_percentile.tail(output_days) if industry_rrs_percentile is not None else None
    
    # 1. Individual RS
    individual_rs_output = []
    for date in rs_recent.index:
        for symbol in rs_recent.columns:
            rs_value = rs_recent.loc[date, symbol]
            if pd.isna(rs_value):
                continue
            
            values_at_date = rs_recent.loc[date].dropna()
            rank = (values_at_date > rs_value).sum() + 1
            
            individual_rs_output.append({
                'date': pd.Timestamp(date).strftime('%Y-%m-%d'),
                'ticker': symbol,
                'name': symbols_info.get(symbol, {}).get('name', symbol),
                'sector': symbols_info.get(symbol, {}).get('sector', 'N/A'),
                'industry': symbols_info.get(symbol, {}).get('industry', 'N/A'),
                'rs_raw': round(float(rs_value), 2),
                'rs_percentile': round(float(rs_value), 2),
                'rank': int(rank)
            })
    
    with open(TEMP_RS_INDIVIDUAL_JSON, 'w') as f:
        json.dump(individual_rs_output, f)
    logging.info(f"✅ Saved Individual RS: {len(individual_rs_output)} records")
    
    # 2. Individual RRS
    if rrs_recent is not None:
        individual_rrs_output = []
        for date in rrs_recent.index:
            for symbol in rrs_recent.columns:
                rrs_value = rrs_recent.loc[date, symbol]
                if pd.isna(rrs_value):
                    continue
                
                values_at_date = rrs_recent.loc[date].dropna()
                rank = (values_at_date > rrs_value).sum() + 1
                
                individual_rrs_output.append({
                    'date': pd.Timestamp(date).strftime('%Y-%m-%d'),
                    'ticker': symbol,
                    'name': symbols_info.get(symbol, {}).get('name', symbol),
                    'sector': symbols_info.get(symbol, {}).get('sector', 'N/A'),
                    'industry': symbols_info.get(symbol, {}).get('industry', 'N/A'),
                    'rrs_raw': round(float(rrs_value), 2),
                    'rrs_percentile': round(float(rrs_value), 2),
                    'rank': int(rank)
                })
        
        with open(TEMP_RRS_INDIVIDUAL_JSON, 'w') as f:
            json.dump(individual_rrs_output, f)
        logging.info(f"✅ Saved Individual RRS: {len(individual_rrs_output)} records")
    
    # 3. Sector RS
    sector_rs_output = []
    for date in sector_rs_recent.index:
        for sector in sector_rs_recent.columns:
            rs_value = sector_rs_recent.loc[date, sector]
            if pd.isna(rs_value):
                continue
            
            values_at_date = sector_rs_recent.loc[date].dropna()
            rank = (values_at_date > rs_value).sum() + 1
            stock_count = sum(1 for s, info in symbols_info.items() if info.get('sector') == sector)
            
            sector_rs_output.append({
                'date': pd.Timestamp(date).strftime('%Y-%m-%d'),
                'sector': sector,
                'rs_raw': round(float(rs_value), 2),
                'rs_percentile': round(float(rs_value), 2),
                'rank': int(rank),
                'stock_count': stock_count
            })
    
    with open(TEMP_RS_SECTOR_JSON, 'w') as f:
        json.dump(sector_rs_output, f)
    logging.info(f"✅ Saved Sector RS: {len(sector_rs_output)} records")
    
    # 4. Sector RRS
    if sector_rrs_recent is not None:
        sector_rrs_output = []
        for date in sector_rrs_recent.index:
            for sector in sector_rrs_recent.columns:
                rrs_value = sector_rrs_recent.loc[date, sector]
                if pd.isna(rrs_value):
                    continue
                
                values_at_date = sector_rrs_recent.loc[date].dropna()
                rank = (values_at_date > rrs_value).sum() + 1
                stock_count = sum(1 for s, info in symbols_info.items() if info.get('sector') == sector)
                
                sector_rrs_output.append({
                    'date': pd.Timestamp(date).strftime('%Y-%m-%d'),
                    'sector': sector,
                    'rrs_raw': round(float(rrs_value), 2),
                    'rrs_percentile': round(float(rrs_value), 2),
                    'rank': int(rank),
                    'stock_count': stock_count
                })
        
        with open(TEMP_RRS_SECTOR_JSON, 'w') as f:
            json.dump(sector_rrs_output, f)
        logging.info(f"✅ Saved Sector RRS: {len(sector_rrs_output)} records")
    
    # 5. Industry RS
    industry_rs_output = []
    for date in industry_rs_recent.index:
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
            
            industry_rs_output.append({
                'date': pd.Timestamp(date).strftime('%Y-%m-%d'),
                'industry': industry,
                'sector': sector,
                'rs_raw': round(float(rs_value), 2),
                'rs_percentile': round(float(rs_value), 2),
                'rank': int(rank),
                'stock_count': stock_count
            })
    
    with open(TEMP_RS_INDUSTRY_JSON, 'w') as f:
        json.dump(industry_rs_output, f)
    logging.info(f"✅ Saved Industry RS: {len(industry_rs_output)} records")
    
    # 6. Industry RRS
    if industry_rrs_recent is not None:
        industry_rrs_output = []
        for date in industry_rrs_recent.index:
            for industry in industry_rrs_recent.columns:
                rrs_value = industry_rrs_recent.loc[date, industry]
                if pd.isna(rrs_value):
                    continue
                
                values_at_date = industry_rrs_recent.loc[date].dropna()
                rank = (values_at_date > rrs_value).sum() + 1
                
                # セクター特定
                sector = 'N/A'
                for s, info in symbols_info.items():
                    if info.get('industry') == industry:
                        sector = info.get('sector', 'N/A')
                        break
                
                stock_count = sum(1 for s, info in symbols_info.items() if info.get('industry') == industry)
                
                industry_rrs_output.append({
                    'date': pd.Timestamp(date).strftime('%Y-%m-%d'),
                    'industry': industry,
                    'sector': sector,
                    'rrs_raw': round(float(rrs_value), 2),
                    'rrs_percentile': round(float(rrs_value), 2),
                    'rank': int(rank),
                    'stock_count': stock_count
                })
        
        with open(TEMP_RRS_INDUSTRY_JSON, 'w') as f:
            json.dump(industry_rrs_output, f)
        logging.info(f"✅ Saved Industry RRS: {len(industry_rrs_output)} records")
    
    return True

def main():
    """RS/RRS計算メイン処理"""
    logging.info("="*60)
    logging.info("RS/RRS CALCULATION (COMPLETE VERSION)")
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
    
    # ===== Individual RS/RRS =====
    rs_raw = calculate_individual_rs_vectorized(price_data, min_days=252)
    
    if rs_raw is None or rs_raw.empty:
        logging.error("Failed to calculate Individual RS")
        return False
    
    rs_percentile = calculate_percentiles_vectorized(rs_raw, "Individual RS")
    
    rrs_raw = calculate_rrs_from_prices(price_data)
    rrs_percentile = None
    if rrs_raw is not None:
        rrs_percentile = calculate_percentiles_vectorized(rrs_raw, "Individual RRS")
    
    # ===== Sector RS/RRS =====
    sector_rs_raw = calculate_sector_rs_weighted(rs_percentile, symbols_info, price_data)
    sector_rs_percentile = calculate_percentiles_vectorized(sector_rs_raw, "Sector RS")
    
    sector_rrs_percentile = None
    if rrs_raw is not None:
        sector_rrs_raw = calculate_sector_rrs_weighted(rrs_raw, symbols_info, price_data)
        sector_rrs_percentile = calculate_percentiles_vectorized(sector_rrs_raw, "Sector RRS")
    
    # ===== Industry RS/RRS =====
    industry_rs_raw = calculate_industry_rs_weighted(rs_percentile, symbols_info, price_data)
    industry_rs_percentile = calculate_percentiles_vectorized(industry_rs_raw, "Industry RS")
    
    industry_rrs_percentile = None
    if rrs_raw is not None:
        industry_rrs_raw = calculate_industry_rrs_weighted(rrs_raw, symbols_info, price_data)
        industry_rrs_percentile = calculate_percentiles_vectorized(industry_rrs_raw, "Industry RRS")
    
    # 保存
    if save_results_json(rs_percentile, rrs_percentile, sector_rs_percentile, sector_rrs_percentile,
                        industry_rs_percentile, industry_rrs_percentile, symbols_info, output_days=500):
        logging.info("="*60)
        logging.info("✅ RS/RRS calculation completed!")
        logging.info("="*60)
        logging.info("\nGenerated files:")
        logging.info(f"  - {TEMP_RS_INDIVIDUAL_JSON}")
        logging.info(f"  - {TEMP_RRS_INDIVIDUAL_JSON}")
        logging.info(f"  - {TEMP_RS_SECTOR_JSON}")
        logging.info(f"  - {TEMP_RRS_SECTOR_JSON}")
        logging.info(f"  - {TEMP_RS_INDUSTRY_JSON}")
        logging.info(f"  - {TEMP_RRS_INDUSTRY_JSON}")
        return True
    else:
        return False

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)
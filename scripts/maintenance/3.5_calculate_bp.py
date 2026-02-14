"""
3.5_calculate_bp.py

BuyPressure計算（RS/RRSと同じ形式で出力）
出力形式: 日付ごとの辞書リスト
"""
import os
import pandas as pd
import numpy as np
import logging
import pickle
from collections import defaultdict

DATA_FOLDER = "data"
MAINTENANCE_FOLDER = os.path.join(DATA_FOLDER, "maintenance")
TARGET_STOCKS_CSV = os.path.join(DATA_FOLDER, "target_stocks_latest.csv")

INPUT_PKL = os.path.join(MAINTENANCE_FOLDER, "temp_prices_with_indicators.pkl")

OUTPUT_BP_RAW = os.path.join(MAINTENANCE_FOLDER, "temp_bp_raw.pkl")
OUTPUT_SECTOR_BP_RAW = os.path.join(MAINTENANCE_FOLDER, "temp_sector_bp_raw.pkl")
OUTPUT_INDUSTRY_BP_RAW = os.path.join(MAINTENANCE_FOLDER, "temp_industry_bp_raw.pkl")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def calculate_atr(df, period=14):
    """ATR計算"""
    high = df['High']
    low = df['Low']
    close_prev = df['Close'].shift(1)
    
    tr1 = high - low
    tr2 = abs(high - close_prev)
    tr3 = abs(low - close_prev)
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    
    return atr

def calculate_individual_bp(df):
    """Individual BuyPressure計算"""
    logging.info("Calculating Individual BuyPressure...")
    
    symbols = df.columns.levels[0] if isinstance(df.columns, pd.MultiIndex) else [df.columns[0]]
    bp_list = []
    
    for symbol in symbols:
        try:
            symbol_df = df[symbol].copy()
            
            atr = calculate_atr(symbol_df, period=14)
            price_change = symbol_df['Close'].diff()
            significant_move = abs(price_change) >= (atr * 0.3)
            dollar_volume = symbol_df['Close'] * symbol_df['Volume']
            
            up_volume = np.where((price_change > 0) & significant_move, dollar_volume, 0)
            down_volume = np.where((price_change < 0) & significant_move, dollar_volume, 0)
            
            up_vol_sum = pd.Series(up_volume, index=symbol_df.index).rolling(window=20).sum()
            down_vol_sum = pd.Series(down_volume, index=symbol_df.index).rolling(window=20).sum()
            
            total_vol = up_vol_sum + down_vol_sum
            bp = np.where(total_vol > 0, up_vol_sum / total_vol, np.nan)
            
            bp_series = pd.Series(bp, index=symbol_df.index, name=symbol)
            bp_list.append(bp_series)
            
        except Exception as e:
            logging.warning(f"Failed to calculate BP for {symbol}: {e}")
            continue
    
    bp_raw = pd.concat(bp_list, axis=1)
    
    valid_count = bp_raw.notna().sum(axis=1).iloc[-1] if len(bp_raw) > 0 else 0
    logging.info(f"Calculated BuyPressure for {len(symbols)} symbols")
    logging.info(f"Latest date: {valid_count}/{len(symbols)} symbols have valid BP scores")
    
    return bp_raw

def calculate_sector_bp(df, symbols_info):
    """Sector BuyPressure計算（RS/RRSと同じ形式）"""
    logging.info("Calculating Sector BuyPressure...")
    
    symbols = df.columns.levels[0] if isinstance(df.columns, pd.MultiIndex) else [df.columns[0]]
    
    # セクターグループ化
    sector_groups = defaultdict(list)
    for symbol in symbols:
        if symbol == '^GSPC':
            continue
        info = symbols_info.get(symbol, {})
        sector = info.get('sector', 'Unknown')
        sector_groups[sector].append(symbol)
    
    # 配列化
    logging.info("Pre-calculating BP arrays...")
    bp_arr = {}
    close_arr = {}
    volume_arr = {}
    
    for symbol in symbols:
        if symbol == '^GSPC':
            continue
        try:
            # BP計算
            symbol_df = df[symbol].copy()
            atr = calculate_atr(symbol_df, period=14)
            price_change = symbol_df['Close'].diff()
            significant_move = abs(price_change) >= (atr * 0.3)
            dollar_volume = symbol_df['Close'] * symbol_df['Volume']
            
            up_volume = np.where((price_change > 0) & significant_move, dollar_volume, 0)
            down_volume = np.where((price_change < 0) & significant_move, dollar_volume, 0)
            
            up_vol_sum = pd.Series(up_volume, index=symbol_df.index).rolling(window=20).sum()
            down_vol_sum = pd.Series(down_volume, index=symbol_df.index).rolling(window=20).sum()
            
            total_vol = up_vol_sum + down_vol_sum
            bp = np.where(total_vol > 0, up_vol_sum / total_vol, np.nan)
            
            bp_arr[symbol] = bp
            close_arr[symbol] = symbol_df['Close'].values
            volume_arr[symbol] = symbol_df['Volume'].values
        except:
            pass
    
    dates = df.index.values
    
    # 日付ごとにセクターBP計算
    logging.info("Calculating sector-level BuyPressure...")
    sector_bp_raw_list = []
    
    total_dates = len(dates)
    processed_count = 0
    
    for date_idx in range(total_dates):
        processed_count += 1
        date = dates[date_idx]
        
        sector_bp_scores = {}
        
        for sector, sector_symbols in sector_groups.items():
            sector_bps = []
            sector_closes = []
            sector_volumes = []
            
            for symbol in sector_symbols:
                try:
                    bp_val = bp_arr[symbol][date_idx]
                    close_val = close_arr[symbol][date_idx]
                    volume_val = volume_arr[symbol][date_idx]
                    
                    if pd.notna(bp_val) and pd.notna(close_val) and pd.notna(volume_val):
                        sector_bps.append(bp_val)
                        sector_closes.append(close_val)
                        sector_volumes.append(volume_val)
                except:
                    pass
            
            if len(sector_bps) > 0:
                bps_np = np.array(sector_bps)
                closes_np = np.array(sector_closes)
                volumes_np = np.array(sector_volumes)
                
                weights = closes_np * volumes_np
                total_weight = weights.sum()
                
                if total_weight > 0:
                    weighted_bp = (weights * bps_np).sum() / total_weight
                    
                    sector_bp_scores[sector] = {
                        'bp_raw': weighted_bp,
                        'stock_count': len(sector_bps)
                    }
        
        if sector_bp_scores:
            sector_bp_raw_list.append((date, sector_bp_scores))
        
        if processed_count % 1000 == 0:
            logging.info(f"  Progress: {processed_count}/{total_dates} dates")
    
    logging.info(f"Calculated Sector BP for {len(sector_bp_raw_list)} dates")
    return sector_bp_raw_list

def calculate_industry_bp(df, symbols_info):
    """Industry BuyPressure計算（RS/RRSと同じ形式）"""
    logging.info("Calculating Industry BuyPressure...")
    
    symbols = df.columns.levels[0] if isinstance(df.columns, pd.MultiIndex) else [df.columns[0]]
    
    # 業種グループ化
    industry_groups = defaultdict(list)
    industry_to_sector = {}
    
    for symbol in symbols:
        if symbol == '^GSPC':
            continue
        info = symbols_info.get(symbol, {})
        industry = info.get('industry', 'Unknown')
        sector = info.get('sector', 'Unknown')
        industry_groups[industry].append(symbol)
        if industry not in industry_to_sector:
            industry_to_sector[industry] = sector
    
    # 配列化
    logging.info("Pre-calculating BP arrays...")
    bp_arr = {}
    close_arr = {}
    volume_arr = {}
    
    for symbol in symbols:
        if symbol == '^GSPC':
            continue
        try:
            symbol_df = df[symbol].copy()
            atr = calculate_atr(symbol_df, period=14)
            price_change = symbol_df['Close'].diff()
            significant_move = abs(price_change) >= (atr * 0.3)
            dollar_volume = symbol_df['Close'] * symbol_df['Volume']
            
            up_volume = np.where((price_change > 0) & significant_move, dollar_volume, 0)
            down_volume = np.where((price_change < 0) & significant_move, dollar_volume, 0)
            
            up_vol_sum = pd.Series(up_volume, index=symbol_df.index).rolling(window=20).sum()
            down_vol_sum = pd.Series(down_volume, index=symbol_df.index).rolling(window=20).sum()
            
            total_vol = up_vol_sum + down_vol_sum
            bp = np.where(total_vol > 0, up_vol_sum / total_vol, np.nan)
            
            bp_arr[symbol] = bp
            close_arr[symbol] = symbol_df['Close'].values
            volume_arr[symbol] = symbol_df['Volume'].values
        except:
            pass
    
    dates = df.index.values
    
    # 日付ごとに業種BP計算
    logging.info("Calculating industry-level BuyPressure...")
    industry_bp_raw_list = []
    
    total_dates = len(dates)
    processed_count = 0
    
    for date_idx in range(total_dates):
        processed_count += 1
        date = dates[date_idx]
        
        industry_bp_scores = {}
        
        for industry, industry_symbols in industry_groups.items():
            sector = industry_to_sector.get(industry, 'Unknown')
            
            industry_bps = []
            industry_closes = []
            industry_volumes = []
            
            for symbol in industry_symbols:
                try:
                    bp_val = bp_arr[symbol][date_idx]
                    close_val = close_arr[symbol][date_idx]
                    volume_val = volume_arr[symbol][date_idx]
                    
                    if pd.notna(bp_val) and pd.notna(close_val) and pd.notna(volume_val):
                        industry_bps.append(bp_val)
                        industry_closes.append(close_val)
                        industry_volumes.append(volume_val)
                except:
                    pass
            
            if len(industry_bps) > 0:
                bps_np = np.array(industry_bps)
                closes_np = np.array(industry_closes)
                volumes_np = np.array(industry_volumes)
                
                weights = closes_np * volumes_np
                total_weight = weights.sum()
                
                if total_weight > 0:
                    weighted_bp = (weights * bps_np).sum() / total_weight
                    
                    industry_bp_scores[industry] = {
                        'bp_raw': weighted_bp,
                        'sector': sector,
                        'stock_count': len(industry_bps)
                    }
        
        if industry_bp_scores:
            industry_bp_raw_list.append((date, industry_bp_scores))
        
        if processed_count % 1000 == 0:
            logging.info(f"  Progress: {processed_count}/{total_dates} dates")
    
    logging.info(f"Calculated Industry BP for {len(industry_bp_raw_list)} dates")
    return industry_bp_raw_list

def main():
    logging.info("=" * 60)
    logging.info("Starting BuyPressure Calculation")
    logging.info("=" * 60)
    
    # データ読み込み
    with open(INPUT_PKL, 'rb') as f:
        df = pickle.load(f)
    
    df_stocks = pd.read_csv(TARGET_STOCKS_CSV)
    
    symbols_info = {}
    for _, row in df_stocks.iterrows():
        symbol = row['Symbol']
        if not isinstance(symbol, str) or not symbol.strip():
            continue
        symbol = symbol.strip()
        symbols_info[symbol] = {
            'name': row.get('Company Name', symbol) if pd.notna(row.get('Company Name')) else symbol,
            'sector': row.get('Sector', 'N/A') if pd.notna(row.get('Sector')) else 'N/A',
            'industry': row.get('Industry', 'N/A') if pd.notna(row.get('Industry')) else 'N/A'
        }
    
    # Individual BP
    bp_raw = calculate_individual_bp(df)
    
    # Sector BP
    sector_bp_raw_list = calculate_sector_bp(df, symbols_info)
    
    # Industry BP
    industry_bp_raw_list = calculate_industry_bp(df, symbols_info)
    
    # 保存
    with open(OUTPUT_BP_RAW, 'wb') as f:
        pickle.dump(bp_raw, f)
    
    with open(OUTPUT_SECTOR_BP_RAW, 'wb') as f:
        pickle.dump(sector_bp_raw_list, f)
    
    with open(OUTPUT_INDUSTRY_BP_RAW, 'wb') as f:
        pickle.dump(industry_bp_raw_list, f)
    
    logging.info("=" * 60)
    logging.info("✅ BuyPressure Calculation Complete!")
    logging.info("=" * 60)

if __name__ == "__main__":
    main()

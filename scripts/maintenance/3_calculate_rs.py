"""
3_calculate_rs.py

RS/RRS計算（生値 + パーセンタイル + ランキング）
入力: data/maintenance/temp_prices_with_indicators.pkl
      data/target_stocks_latest.csv

出力: 
【Individual】
  data/maintenance/temp_rs_raw.pkl (RS生値)
  data/maintenance/temp_rs_percentile.pkl (RSパーセンタイル)
  data/maintenance/temp_rrs_raw.pkl (RRS生値)
  data/maintenance/temp_rrs_percentile.pkl (RRSパーセンタイル)

【Sector】
  data/maintenance/temp_sector_rs_raw.pkl (セクターRS生値)
  data/maintenance/temp_sector_rs_percentile.pkl (セクターRSパーセンタイル)
  data/maintenance/temp_sector_rrs_raw.pkl (セクターRRS生値)
  data/maintenance/temp_sector_rrs_percentile.pkl (セクターRRSパーセンタイル)

【Industry】
  data/maintenance/temp_industry_rs_raw.pkl (業種RS生値)
  data/maintenance/temp_industry_rs_percentile.pkl (業種RSパーセンタイル)
  data/maintenance/temp_industry_rrs_raw.pkl (業種RRS生値)
  data/maintenance/temp_industry_rrs_percentile.pkl (業種RRSパーセンタイル)
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

# Individual
OUTPUT_RS_RAW = os.path.join(MAINTENANCE_FOLDER, "temp_rs_raw.pkl")
OUTPUT_RS_PERCENTILE = os.path.join(MAINTENANCE_FOLDER, "temp_rs_percentile.pkl")
OUTPUT_RRS_RAW = os.path.join(MAINTENANCE_FOLDER, "temp_rrs_raw.pkl")
OUTPUT_RRS_PERCENTILE = os.path.join(MAINTENANCE_FOLDER, "temp_rrs_percentile.pkl")

# Sector
OUTPUT_SECTOR_RS_RAW = os.path.join(MAINTENANCE_FOLDER, "temp_sector_rs_raw.pkl")
OUTPUT_SECTOR_RS_PERCENTILE = os.path.join(MAINTENANCE_FOLDER, "temp_sector_rs_percentile.pkl")
OUTPUT_SECTOR_RRS_RAW = os.path.join(MAINTENANCE_FOLDER, "temp_sector_rrs_raw.pkl")
OUTPUT_SECTOR_RRS_PERCENTILE = os.path.join(MAINTENANCE_FOLDER, "temp_sector_rrs_percentile.pkl")

# Industry
OUTPUT_INDUSTRY_RS_RAW = os.path.join(MAINTENANCE_FOLDER, "temp_industry_rs_raw.pkl")
OUTPUT_INDUSTRY_RS_PERCENTILE = os.path.join(MAINTENANCE_FOLDER, "temp_industry_rs_percentile.pkl")
OUTPUT_INDUSTRY_RRS_RAW = os.path.join(MAINTENANCE_FOLDER, "temp_industry_rrs_raw.pkl")
OUTPUT_INDUSTRY_RRS_PERCENTILE = os.path.join(MAINTENANCE_FOLDER, "temp_industry_rrs_percentile.pkl")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def calculate_individual_rs(df):
    """
    Individual RS計算（生値 + パーセンタイル）
    
    Returns:
        tuple: (rs_raw, rs_percentile)
    """
    logging.info("Calculating Individual RS scores...")
    
    symbols = df.columns.levels[0] if isinstance(df.columns, pd.MultiIndex) else [df.columns[0]]
    
    # ★ 修正: Close価格を一度にまとめて抽出
    close_columns = []
    for symbol in symbols:
        try:
            close_series = df[symbol]['Close']
            close_series.name = symbol
            close_columns.append(close_series)
        except:
            pass
    
    # 一度にまとめて結合
    close_df = pd.concat(close_columns, axis=1)
    
    # リターン計算
    ret_3m = close_df.pct_change(periods=63, fill_method=None) * 100
    ret_6m = close_df.pct_change(periods=126, fill_method=None) * 100
    ret_9m = close_df.pct_change(periods=189, fill_method=None) * 100
    ret_12m = close_df.pct_change(periods=252, fill_method=None) * 100
    
    # RS計算（生値）
    rs_raw = (ret_3m * 0.4 + ret_6m * 0.2 + ret_9m * 0.2 + ret_12m * 0.2)
    
    # パーセンタイル化
    rs_percentile = rs_raw.rank(axis=1, pct=True) * 98 + 1
    
    # 統計情報
    valid_count = rs_percentile.notna().sum(axis=1).iloc[-1] if len(rs_percentile) > 0 else 0
    logging.info(f"Calculated RS for {len(symbols)} symbols")
    logging.info(f"Latest date: {valid_count}/{len(symbols)} symbols have valid RS scores")
    
    return rs_raw, rs_percentile

def calculate_individual_rrs(df):
    """
    Individual RRS計算（生値 + パーセンタイル）
    
    Returns:
        tuple: (rrs_raw, rrs_percentile)
    """
    logging.info("Calculating Individual RRS scores...")
    
    symbols = df.columns.levels[0] if isinstance(df.columns, pd.MultiIndex) else [df.columns[0]]
    
    # S&P500データ取得
    try:
        spy_data = df['^GSPC'] if '^GSPC' in symbols else None
        
        if spy_data is None or spy_data.empty:
            logging.warning("S&P500 data not available, RRS will be None")
            empty_df = pd.DataFrame(index=df.index, columns=symbols)
            return empty_df, empty_df
        
        spy_close = spy_data['Close']
        spy_atr = spy_data['atr14']
        
        # S&P500のATRデータが不足している場合
        if spy_atr.isna().all():
            logging.warning("S&P500 ATR data insufficient, RRS will be None")
            empty_df = pd.DataFrame(index=df.index, columns=symbols)
            return empty_df, empty_df
        
    except Exception as e:
        logging.warning(f"Failed to get S&P500 data: {e}")
        empty_df = pd.DataFrame(index=df.index, columns=symbols)
        return empty_df, empty_df
    
    # ★ 修正: RRS計算を一度にまとめて処理
    rrs_columns = []
    
    calculated_count = 0
    skipped_count = 0
    
    for symbol in symbols:
        try:
            if symbol == '^GSPC':
                continue
            
            stock_close = df[symbol]['Close']
            stock_atr = df[symbol]['atr14']
            
            # データ長チェック（ATRが計算されているか）
            if stock_atr.isna().all():
                skipped_count += 1
                continue
            
            # デイリー変化
            delta_stock = stock_close.diff()
            delta_spy = spy_close.diff()
            
            # 期待値
            expected = delta_spy * (stock_atr / spy_atr)
            
            # RRS daily
            rrs_daily = (delta_stock - expected) / stock_atr
            
            # 12日間のsum
            rrs_series = rrs_daily.rolling(window=12).sum()
            rrs_series.name = symbol
            rrs_columns.append(rrs_series)
            
            calculated_count += 1
            
        except Exception as e:
            logging.debug(f"RRS calculation failed for {symbol}: {e}")
            skipped_count += 1
    
    # 一度にまとめて結合
    if rrs_columns:
        rrs_raw = pd.concat(rrs_columns, axis=1)
    else:
        rrs_raw = pd.DataFrame(index=df.index, columns=symbols)
    
    # パーセンタイル化
    rrs_percentile = rrs_raw.rank(axis=1, pct=True) * 98 + 1
    
    logging.info(f"Calculated RRS for {calculated_count} symbols")
    logging.info(f"Skipped {skipped_count} symbols (insufficient data)")
    
    return rrs_raw, rrs_percentile

def calculate_sector_rs_rrs(df, symbols_info):
    """
    Sector RS/RRS計算（.loc最適化版）
    
    Returns:
        tuple: (sector_rs_raw_list, sector_rs_percentile_list, 
                sector_rrs_raw_list, sector_rrs_percentile_list)
    """
    logging.info("Calculating Sector RS/RRS...")
    
    symbols = df.columns.levels[0] if isinstance(df.columns, pd.MultiIndex) else [df.columns[0]]
    
    # セクターごとにグループ化
    sector_groups = defaultdict(list)
    
    for symbol in symbols:
        if symbol == '^GSPC':
            continue
        
        info = symbols_info.get(symbol, {})
        sector = info.get('sector', 'Unknown')
        
        sector_groups[sector].append(symbol)
    
    # ★ 最適化: 全データをNumPy配列化（.locアクセス不要）
    logging.info("Pre-calculating data arrays...")
    returns_3m_arr = {}
    close_arr = {}
    volume_arr = {}
    atr_arr = {}
    delta_arr = {}  # デルタも事前計算
    
    for symbol in symbols:
        if symbol == '^GSPC':
            continue
        try:
            close_arr[symbol] = df[symbol]['Close'].values
            volume_arr[symbol] = df[symbol]['Volume'].values
            atr_arr[symbol] = df[symbol]['atr14'].values
            returns_3m_arr[symbol] = df[symbol]['Close'].pct_change(periods=63, fill_method=None).values * 100
            
            # デルタを事前計算
            delta_arr[symbol] = df[symbol]['Close'].diff().values
        except:
            pass
    
    # S&P500データ（RRS用）を配列化
    spy_close_arr = None
    spy_atr_arr = None
    spy_delta_arr = None
    
    try:
        if '^GSPC' in symbols:
            spy_close_arr = df['^GSPC']['Close'].values
            spy_atr_arr = df['^GSPC']['atr14'].values
            spy_delta_arr = df['^GSPC']['Close'].diff().values
    except:
        pass
    
    # 日付インデックスを取得
    dates = df.index.values
    
    # ★ 高速化: セクターごとにベクトル化計算
    logging.info("Calculating sector-level metrics...")
    sector_rs_raw_list = []
    sector_rrs_raw_list = []
    
    total_dates = len(dates)
    processed_count = 0
    
    for date_idx in range(total_dates):  # ★ index で直接アクセス
        processed_count += 1
        date = dates[date_idx]
        
        sector_rs_scores = {}
        
        for sector, sector_symbols in sector_groups.items():
            # ベクトル化: 全銘柄を一度に取得
            sector_closes = []
            sector_volumes = []
            sector_returns = []
            sector_atrs = []
            sector_deltas = []
            
            for symbol in sector_symbols:
                try:
                    # ★ 最適化: 配列から直接取得（.loc不要）
                    close_val = close_arr[symbol][date_idx]
                    volume_val = volume_arr[symbol][date_idx]
                    return_val = returns_3m_arr[symbol][date_idx]
                    
                    if pd.notna(close_val) and pd.notna(volume_val) and pd.notna(return_val):
                        sector_closes.append(close_val)
                        sector_volumes.append(volume_val)
                        sector_returns.append(return_val)
                        
                        # RRS用
                        if spy_close_arr is not None:
                            atr_val = atr_arr[symbol][date_idx]
                            if pd.notna(atr_val):
                                sector_atrs.append(atr_val)
                                # デルタも配列から取得
                                delta_val = delta_arr[symbol][date_idx]
                                if pd.notna(delta_val):
                                    sector_deltas.append(delta_val)
                except:
                    pass
            
            # RS計算（ベクトル化）
            if len(sector_closes) > 0:
                # NumPy配列に変換して高速計算
                closes_arr_np = np.array(sector_closes)
                volumes_arr_np = np.array(sector_volumes)
                returns_arr_np = np.array(sector_returns)
                
                weights = closes_arr_np * volumes_arr_np
                total_weight = weights.sum()
                
                if total_weight > 0:
                    weighted_return = (weights * returns_arr_np).sum() / total_weight
                    
                    sector_rs_scores[sector] = {
                        'rs_raw': weighted_return,
                        'stock_count': len(sector_closes)
                    }
                    
                    # RRS計算（ベクトル化）
                    if spy_close_arr is not None and len(sector_atrs) > 0:
                        try:
                            atrs_arr_np = np.array(sector_atrs)
                            deltas_arr_np = np.array(sector_deltas)
                            
                            avg_atr = atrs_arr_np.mean()
                            avg_delta = deltas_arr_np.mean()
                            
                            # ★ 最適化: 配列から直接取得
                            spy_delta_val = spy_delta_arr[date_idx]
                            spy_atr_val = spy_atr_arr[date_idx]
                            
                            if pd.notna(spy_delta_val) and pd.notna(spy_atr_val) and spy_atr_val > 0 and avg_atr > 0:
                                expected = spy_delta_val * (avg_atr / spy_atr_val)
                                rrs_daily = (avg_delta - expected) / avg_atr
                                
                                sector_rs_scores[sector]['rrs_raw'] = rrs_daily
                        except:
                            pass
        
        # sector_rs_scoresからRSとRRSを分離して保存
        if sector_rs_scores:
            # RSデータを保存
            rs_only = {}
            rrs_only = {}
            
            for sector, data in sector_rs_scores.items():
                rs_only[sector] = {
                    'rs_raw': data['rs_raw'],
                    'stock_count': data['stock_count']
                }
                
                # RRSがあれば別リストに保存
                if 'rrs_raw' in data:
                    rrs_only[sector] = {
                        'rrs_raw': data['rrs_raw'],
                        'stock_count': data['stock_count']
                    }
            
            sector_rs_raw_list.append((date, rs_only))
            
            if rrs_only:
                sector_rrs_raw_list.append((date, rrs_only))
        
        # 進捗表示
        if processed_count % 1000 == 0:
            logging.info(f"  Progress: {processed_count}/{total_dates} dates")
    
    # パーセンタイル化（既存のまま）
    logging.info("Calculating percentiles...")
    sector_rs_percentile_list = []
    sector_rrs_percentile_list = []
    
    for date, sector_scores in sector_rs_raw_list:
        # RS パーセンタイル
        rs_data = []
        for sector, scores in sector_scores.items():
            rs_data.append({
                'sector': sector,
                'rs_raw': scores['rs_raw'],
                'stock_count': scores['stock_count']
            })
        
        if len(rs_data) > 1:
            rs_df_temp = pd.DataFrame(rs_data)
            rs_df_temp['rs_percentile'] = rs_df_temp['rs_raw'].rank(pct=True) * 98 + 1
            
            rs_percentile_dict = {}
            for _, row in rs_df_temp.iterrows():
                sector = row['sector']
                rs_percentile_dict[sector] = {
                    'rs_raw': row['rs_raw'],
                    'rs_percentile': row['rs_percentile'],
                    'stock_count': int(row['stock_count'])
                }
            
            sector_rs_percentile_list.append((date, rs_percentile_dict))
    
    # RRS パーセンタイルは sector_rrs_raw_list から計算
    for date, sector_scores in sector_rrs_raw_list:
        rrs_data = []
        for sector, scores in sector_scores.items():
            rrs_data.append({
                'sector': sector,
                'rrs_raw': scores['rrs_raw'],
                'stock_count': scores['stock_count']
            })
        
        if len(rrs_data) > 1:
            rrs_df_temp = pd.DataFrame(rrs_data)
            rrs_df_temp['rrs_percentile'] = rrs_df_temp['rrs_raw'].rank(pct=True) * 98 + 1
            
            rrs_percentile_dict = {}
            for _, row in rrs_df_temp.iterrows():
                sector = row['sector']
                rrs_percentile_dict[sector] = {
                    'rrs_raw': row['rrs_raw'],
                    'rrs_percentile': row['rrs_percentile'],
                    'stock_count': int(row['stock_count'])
                }
            
            sector_rrs_percentile_list.append((date, rrs_percentile_dict))
    
    logging.info(f"Calculated Sector RS for {len(sector_rs_percentile_list)} dates")
    logging.info(f"Calculated Sector RRS for {len(sector_rrs_percentile_list)} dates")
    
    return sector_rs_raw_list, sector_rs_percentile_list, sector_rrs_raw_list, sector_rrs_percentile_list



def calculate_industry_rs_rrs(df, symbols_info):
    """
    Industry RS/RRS計算（.loc最適化版）
    
    Returns:
        tuple: (industry_rs_raw_list, industry_rs_percentile_list,
                industry_rrs_raw_list, industry_rrs_percentile_list)
    """
    logging.info("Calculating Industry RS/RRS...")
    
    symbols = df.columns.levels[0] if isinstance(df.columns, pd.MultiIndex) else [df.columns[0]]
    
    # 業種ごとにグループ化
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
    
    # ★ 最適化: 全データをNumPy配列化
    logging.info("Pre-calculating data arrays...")
    returns_3m_arr = {}
    close_arr = {}
    volume_arr = {}
    atr_arr = {}
    delta_arr = {}
    
    for symbol in symbols:
        if symbol == '^GSPC':
            continue
        try:
            close_arr[symbol] = df[symbol]['Close'].values
            volume_arr[symbol] = df[symbol]['Volume'].values
            atr_arr[symbol] = df[symbol]['atr14'].values
            returns_3m_arr[symbol] = df[symbol]['Close'].pct_change(periods=63, fill_method=None).values * 100
            delta_arr[symbol] = df[symbol]['Close'].diff().values
        except:
            pass
    
    # S&P500データを配列化
    spy_close_arr = None
    spy_atr_arr = None
    spy_delta_arr = None
    
    try:
        if '^GSPC' in symbols:
            spy_close_arr = df['^GSPC']['Close'].values
            spy_atr_arr = df['^GSPC']['atr14'].values
            spy_delta_arr = df['^GSPC']['Close'].diff().values
    except:
        pass
    
    dates = df.index.values
    
    # ★ 高速化: 業種ごとにベクトル化計算
    logging.info("Calculating industry-level metrics...")
    industry_rs_raw_list = []
    industry_rrs_raw_list = []
    total_dates = len(dates)
    processed_count = 0
    
    for date_idx in range(total_dates):  # ★ index で直接アクセス
        processed_count += 1
        date = dates[date_idx]
        
        industry_rs_scores = {}
        
        for industry, industry_symbols in industry_groups.items():
            sector = industry_to_sector.get(industry, 'Unknown')
            
            # ベクトル化: 全銘柄を一度に取得
            industry_closes = []
            industry_volumes = []
            industry_returns = []
            industry_atrs = []
            industry_deltas = []
            
            for symbol in industry_symbols:
                try:
                    # ★ 最適化: 配列から直接取得
                    close_val = close_arr[symbol][date_idx]
                    volume_val = volume_arr[symbol][date_idx]
                    return_val = returns_3m_arr[symbol][date_idx]
                    
                    if pd.notna(close_val) and pd.notna(volume_val) and pd.notna(return_val):
                        industry_closes.append(close_val)
                        industry_volumes.append(volume_val)
                        industry_returns.append(return_val)
                        
                        # RRS用
                        if spy_close_arr is not None:
                            atr_val = atr_arr[symbol][date_idx]
                            if pd.notna(atr_val):
                                industry_atrs.append(atr_val)
                                delta_val = delta_arr[symbol][date_idx]
                                if pd.notna(delta_val):
                                    industry_deltas.append(delta_val)
                except:
                    pass
            
            # RS計算（ベクトル化）
            if len(industry_closes) > 0:
                closes_arr_np = np.array(industry_closes)
                volumes_arr_np = np.array(industry_volumes)
                returns_arr_np = np.array(industry_returns)
                
                weights = closes_arr_np * volumes_arr_np
                total_weight = weights.sum()
                
                if total_weight > 0:
                    weighted_return = (weights * returns_arr_np).sum() / total_weight
                    
                    industry_rs_scores[industry] = {
                        'rs_raw': weighted_return,
                        'sector': sector,
                        'stock_count': len(industry_closes)
                    }
                    
                    # RRS計算（ベクトル化）
                    if spy_close_arr is not None and len(industry_atrs) > 0:
                        try:
                            atrs_arr_np = np.array(industry_atrs)
                            deltas_arr_np = np.array(industry_deltas)
                            
                            avg_atr = atrs_arr_np.mean()
                            avg_delta = deltas_arr_np.mean()
                            
                            # ★ 最適化: 配列から直接取得
                            spy_delta_val = spy_delta_arr[date_idx]
                            spy_atr_val = spy_atr_arr[date_idx]
                            
                            if pd.notna(spy_delta_val) and pd.notna(spy_atr_val) and spy_atr_val > 0 and avg_atr > 0:
                                expected = spy_delta_val * (avg_atr / spy_atr_val)
                                rrs_daily = (avg_delta - expected) / avg_atr
                                
                                industry_rs_scores[industry]['rrs_raw'] = rrs_daily
                        except:
                            pass
        
        # industry_rs_scoresからRSとRRSを分離して保存
        if industry_rs_scores:
            rs_only = {}
            rrs_only = {}
            
            for industry, data in industry_rs_scores.items():
                rs_only[industry] = {
                    'rs_raw': data['rs_raw'],
                    'sector': data['sector'],
                    'stock_count': data['stock_count']
                }
                
                if 'rrs_raw' in data:
                    rrs_only[industry] = {
                        'rrs_raw': data['rrs_raw'],
                        'sector': data['sector'],
                        'stock_count': data['stock_count']
                    }
            
            industry_rs_raw_list.append((date, rs_only))
            
            if rrs_only:
                industry_rrs_raw_list.append((date, rrs_only))
        
        if processed_count % 1000 == 0:
            logging.info(f"  Progress: {processed_count}/{total_dates} dates")
    
    # パーセンタイル化
    logging.info("Calculating percentiles...")
    industry_rs_percentile_list = []
    industry_rrs_percentile_list = []
    
    for date, industry_scores in industry_rs_raw_list:
        rs_data = []
        for industry, scores in industry_scores.items():
            rs_data.append({
                'industry': industry,
                'rs_raw': scores['rs_raw'],
                'sector': scores['sector'],
                'stock_count': scores['stock_count']
            })
        
        if len(rs_data) > 1:
            rs_df_temp = pd.DataFrame(rs_data)
            rs_df_temp['rs_percentile'] = rs_df_temp['rs_raw'].rank(pct=True) * 98 + 1
            
            rs_percentile_dict = {}
            for _, row in rs_df_temp.iterrows():
                industry = row['industry']
                rs_percentile_dict[industry] = {
                    'rs_raw': row['rs_raw'],
                    'rs_percentile': row['rs_percentile'],
                    'sector': row['sector'],
                    'stock_count': int(row['stock_count'])
                }
            
            industry_rs_percentile_list.append((date, rs_percentile_dict))
    
    for date, industry_scores in industry_rrs_raw_list:
        rrs_data = []
        for industry, scores in industry_scores.items():
            rrs_data.append({
                'industry': industry,
                'rrs_raw': scores['rrs_raw'],
                'sector': scores['sector'],
                'stock_count': scores['stock_count']
            })
        
        if len(rrs_data) > 1:
            rrs_df_temp = pd.DataFrame(rrs_data)
            rrs_df_temp['rrs_percentile'] = rrs_df_temp['rrs_raw'].rank(pct=True) * 98 + 1
            
            rrs_percentile_dict = {}
            for _, row in rrs_df_temp.iterrows():
                industry = row['industry']
                rrs_percentile_dict[industry] = {
                    'rrs_raw': row['rrs_raw'],
                    'rrs_percentile': row['rrs_percentile'],
                    'sector': row['sector'],
                    'stock_count': int(row['stock_count'])
                }
            
            industry_rrs_percentile_list.append((date, rrs_percentile_dict))
    
    logging.info(f"Calculated Industry RS for {len(industry_rs_percentile_list)} dates")
    logging.info(f"Calculated Industry RRS for {len(industry_rrs_percentile_list)} dates")
    
    return industry_rs_raw_list, industry_rs_percentile_list, industry_rrs_raw_list, industry_rrs_percentile_list

    

def main():
    """メイン処理"""
    logging.info("="*60)
    logging.info("STEP 3: CALCULATE RS/RRS (RAW + PERCENTILE)")
    logging.info("="*60)
    
    # データ読み込み
    if not os.path.exists(INPUT_PKL):
        logging.error(f"Input file not found: {INPUT_PKL}")
        logging.error("Please run 2_add_indicators.py first")
        return False
    
    logging.info(f"Loading data from {INPUT_PKL}...")
    with open(INPUT_PKL, 'rb') as f:
        df = pickle.load(f)
    
    logging.info(f"Loaded DataFrame shape: {df.shape}")
    
    # 銘柄情報読み込み
    if not os.path.exists(TARGET_STOCKS_CSV):
        logging.error(f"Target stocks file not found: {TARGET_STOCKS_CSV}")
        return False
    
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
    
    # Individual RS/RRS計算
    rs_raw, rs_percentile = calculate_individual_rs(df)
    rrs_raw, rrs_percentile = calculate_individual_rrs(df)
    
    # Sector RS/RRS計算
    sector_rs_raw_list, sector_rs_percentile_list, sector_rrs_raw_list, sector_rrs_percentile_list = \
        calculate_sector_rs_rrs(df, symbols_info)
    
    # Industry RS/RRS計算
    industry_rs_raw_list, industry_rs_percentile_list, industry_rrs_raw_list, industry_rrs_percentile_list = \
        calculate_industry_rs_rrs(df, symbols_info)
    
    # 保存
    logging.info("Saving results...")
    
    with open(OUTPUT_RS_RAW, 'wb') as f:
        pickle.dump(rs_raw, f)
    
    with open(OUTPUT_RS_PERCENTILE, 'wb') as f:
        pickle.dump(rs_percentile, f)
    
    with open(OUTPUT_RRS_RAW, 'wb') as f:
        pickle.dump(rrs_raw, f)
    
    with open(OUTPUT_RRS_PERCENTILE, 'wb') as f:
        pickle.dump(rrs_percentile, f)
    
    with open(OUTPUT_SECTOR_RS_RAW, 'wb') as f:
        pickle.dump(sector_rs_raw_list, f)
    
    with open(OUTPUT_SECTOR_RS_PERCENTILE, 'wb') as f:
        pickle.dump(sector_rs_percentile_list, f)
    
    with open(OUTPUT_SECTOR_RRS_RAW, 'wb') as f:
        pickle.dump(sector_rrs_raw_list, f)
    
    with open(OUTPUT_SECTOR_RRS_PERCENTILE, 'wb') as f:
        pickle.dump(sector_rrs_percentile_list, f)
    
    with open(OUTPUT_INDUSTRY_RS_RAW, 'wb') as f:
        pickle.dump(industry_rs_raw_list, f)
    
    with open(OUTPUT_INDUSTRY_RS_PERCENTILE, 'wb') as f:
        pickle.dump(industry_rs_percentile_list, f)
    
    with open(OUTPUT_INDUSTRY_RRS_RAW, 'wb') as f:
        pickle.dump(industry_rrs_raw_list, f)
    
    with open(OUTPUT_INDUSTRY_RRS_PERCENTILE, 'wb') as f:
        pickle.dump(industry_rrs_percentile_list, f)
    
    logging.info("="*60)
    logging.info("✅ STEP 3 COMPLETED!")
    logging.info("="*60)
    
    return True

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)
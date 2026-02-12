"""
3.5_calculate_bp.py

BuyPressure計算（生値 + ランキングのみ、パーセンタイル計算なし）
入力: data/maintenance/temp_prices_with_indicators.pkl
      data/target_stocks_latest.csv

出力: 
【Individual】
  data/maintenance/temp_bp_raw.pkl (BP生値)

【Sector】
  data/maintenance/temp_sector_bp_raw.pkl (セクターBP生値)

【Industry】
  data/maintenance/temp_industry_bp_raw.pkl (業種BP生値)

計算方法:
1. ATR (14日) を使ったボラティリティフィルター
2. ATR × 0.3 以上の価格変動がある日のみ有効
3. 値上がり日: up_volume = close × volume
4. 値下がり日: down_volume = close × volume
5. 過去20日間のup/downを合計
6. Buy Pressure = up_vol_sum / (up_vol_sum + down_vol_sum)
7. Sector/Industry: 時価総額加重平均
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
OUTPUT_BP_RAW = os.path.join(MAINTENANCE_FOLDER, "temp_bp_raw.pkl")

# Sector
OUTPUT_SECTOR_BP_RAW = os.path.join(MAINTENANCE_FOLDER, "temp_sector_bp_raw.pkl")

# Industry
OUTPUT_INDUSTRY_BP_RAW = os.path.join(MAINTENANCE_FOLDER, "temp_industry_bp_raw.pkl")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def calculate_atr(df, period=14):
    """
    ATR (Average True Range) を計算
    """
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
    """
    Individual BuyPressure計算（生値のみ）
    
    ATR × 0.3 以上の価格変動がある日のみ有効として、
    過去20日間のup/down volume を集計
    
    Returns:
        pd.DataFrame: bp_raw (各銘柄のBuyPressure時系列)
    """
    logging.info("Calculating Individual BuyPressure scores...")
    
    symbols = df.columns.levels[0] if isinstance(df.columns, pd.MultiIndex) else [df.columns[0]]
    
    bp_list = []
    
    for symbol in symbols:
        try:
            symbol_df = df[symbol].copy()
            
            # ATR計算
            atr = calculate_atr(symbol_df, period=14)
            
            # 価格変動 (close - close.shift(1))
            price_change = symbol_df['Close'].diff()
            
            # ATR × 0.3 以上の変動がある日のみ有効
            significant_move = abs(price_change) >= (atr * 0.3)
            
            # ドル出来高
            dollar_volume = symbol_df['Close'] * symbol_df['Volume']
            
            # 値上がり/値下がり判定
            up_volume = np.where((price_change > 0) & significant_move, dollar_volume, 0)
            down_volume = np.where((price_change < 0) & significant_move, dollar_volume, 0)
            
            # 過去20日間の累積
            up_vol_sum = pd.Series(up_volume, index=symbol_df.index).rolling(window=20).sum()
            down_vol_sum = pd.Series(down_volume, index=symbol_df.index).rolling(window=20).sum()
            
            # Buy Pressure計算
            total_vol = up_vol_sum + down_vol_sum
            bp = np.where(total_vol > 0, up_vol_sum / total_vol, np.nan)
            
            bp_series = pd.Series(bp, index=symbol_df.index, name=symbol)
            bp_list.append(bp_series)
            
        except Exception as e:
            logging.warning(f"Failed to calculate BP for {symbol}: {e}")
            continue
    
    # 一度にまとめて結合
    bp_raw = pd.concat(bp_list, axis=1)
    
    # 統計情報
    valid_count = bp_raw.notna().sum(axis=1).iloc[-1] if len(bp_raw) > 0 else 0
    logging.info(f"Calculated BuyPressure for {len(symbols)} symbols")
    logging.info(f"Latest date: {valid_count}/{len(symbols)} symbols have valid BP scores")
    
    return bp_raw

def calculate_sector_industry_bp(df, target_stocks_df, bp_raw, group_by='sector'):
    """
    Sector/Industry レベルのBuyPressure計算（時価総額加重平均）
    
    Args:
        df: 価格データ
        target_stocks_df: 銘柄メタデータ
        bp_raw: Individual BuyPressure
        group_by: 'sector' or 'industry'
    
    Returns:
        pd.DataFrame: グループ別BuyPressure時系列
    """
    field_name = 'Sector' if group_by == 'sector' else 'Industry'
    logging.info(f"Calculating {field_name} BuyPressure scores...")
    
    # 銘柄→グループのマッピング
    symbol_to_group = dict(zip(target_stocks_df['Symbol'], target_stocks_df[field_name]))
    
    # 時価総額の取得（最新の終値 × 発行済株式数の代理として Volume を使用）
    # ※ 本来は market cap データが必要ですが、簡易的に最新の close * volume を使用
    market_caps = {}
    for symbol in bp_raw.columns:
        try:
            latest_close = df[symbol]['Close'].iloc[-1]
            latest_volume = df[symbol]['Volume'].iloc[-1]
            market_caps[symbol] = latest_close * latest_volume
        except:
            market_caps[symbol] = 1.0  # デフォルト
    
    # グループごとに集約
    groups = target_stocks_df[field_name].unique()
    group_bp_list = []
    
    for group in groups:
        symbols_in_group = target_stocks_df[target_stocks_df[field_name] == group]['Symbol'].tolist()
        symbols_in_group = [s for s in symbols_in_group if s in bp_raw.columns]
        
        if not symbols_in_group:
            continue
        
        # 各銘柄のウェイト
        weights = {s: market_caps.get(s, 1.0) for s in symbols_in_group}
        total_weight = sum(weights.values())
        
        # 時価総額加重平均
        weighted_bp = pd.Series(0.0, index=bp_raw.index)
        
        for symbol in symbols_in_group:
            weight = weights[symbol] / total_weight
            weighted_bp += bp_raw[symbol].fillna(0) * weight
        
        # NaNを適切に処理（全てNaNの場合はNaN）
        all_nan = bp_raw[symbols_in_group].isna().all(axis=1)
        weighted_bp = weighted_bp.where(~all_nan, np.nan)
        weighted_bp.name = group
        
        group_bp_list.append(weighted_bp)
    
    # 結合
    group_bp = pd.concat(group_bp_list, axis=1)
    
    logging.info(f"Calculated {field_name} BuyPressure for {len(groups)} {field_name.lower()}s")
    
    return group_bp

def main():
    logging.info("=" * 60)
    logging.info("Starting BuyPressure Calculation (Maintenance Mode)")
    logging.info("=" * 60)
    
    # 1. データ読み込み
    logging.info(f"Loading price data from {INPUT_PKL}...")
    with open(INPUT_PKL, 'rb') as f:
        df = pickle.load(f)
    
    logging.info(f"Loading target stocks from {TARGET_STOCKS_CSV}...")
    target_stocks_df = pd.read_csv(TARGET_STOCKS_CSV)
    
    # 2. Individual BuyPressure計算
    bp_raw = calculate_individual_bp(df)
    
    # 3. Sector BuyPressure計算
    sector_bp_raw = calculate_sector_industry_bp(df, target_stocks_df, bp_raw, group_by='sector')
    
    # 4. Industry BuyPressure計算
    industry_bp_raw = calculate_sector_industry_bp(df, target_stocks_df, bp_raw, group_by='industry')
    
    # 5. 保存
    logging.info(f"Saving Individual BP to {OUTPUT_BP_RAW}...")
    with open(OUTPUT_BP_RAW, 'wb') as f:
        pickle.dump(bp_raw, f)
    
    logging.info(f"Saving Sector BP to {OUTPUT_SECTOR_BP_RAW}...")
    with open(OUTPUT_SECTOR_BP_RAW, 'wb') as f:
        pickle.dump(sector_bp_raw, f)
    
    logging.info(f"Saving Industry BP to {OUTPUT_INDUSTRY_BP_RAW}...")
    with open(OUTPUT_INDUSTRY_BP_RAW, 'wb') as f:
        pickle.dump(industry_bp_raw, f)
    
    logging.info("=" * 60)
    logging.info("BuyPressure Calculation Complete!")
    logging.info("=" * 60)
    
    # サマリー表示
    print("\n📊 Summary:")
    print(f"  Individual BP: {bp_raw.shape}")
    print(f"  Sector BP: {sector_bp_raw.shape}")
    print(f"  Industry BP: {industry_bp_raw.shape}")
    
    # 最新日のサンプル
    if len(bp_raw) > 0:
        latest_date = bp_raw.index[-1]
        print(f"\n📅 Latest date: {latest_date}")
        print(f"  Sample Individual BP (top 5):")
        print(bp_raw.loc[latest_date].dropna().sort_values(ascending=False).head())

if __name__ == "__main__":
    main()

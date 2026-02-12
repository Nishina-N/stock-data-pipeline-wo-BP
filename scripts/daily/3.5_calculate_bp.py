"""
3.5_calculate_bp.py

Daily BuyPressure計算
入力: data/temp_prices.json
      data/target_stocks_latest.csv

出力: 
  data/temp_bp_individual.json
  data/temp_bp_sector.json
  data/temp_bp_industry.json
"""
import os
import json
import pandas as pd
import numpy as np
import logging
from collections import defaultdict

DATA_FOLDER = "data"
TEMP_PRICE_JSON = os.path.join(DATA_FOLDER, "temp_prices.json")
TARGET_STOCKS_CSV = os.path.join(DATA_FOLDER, "target_stocks_latest.csv")

OUTPUT_BP_INDIVIDUAL = os.path.join(DATA_FOLDER, "temp_bp_individual.json")
OUTPUT_BP_SECTOR = os.path.join(DATA_FOLDER, "temp_bp_sector.json")
OUTPUT_BP_INDUSTRY = os.path.join(DATA_FOLDER, "temp_bp_industry.json")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def calculate_atr(df, period=14):
    """ATR計算"""
    high = df['high']
    low = df['low']
    close_prev = df['close'].shift(1)
    
    tr1 = high - low
    tr2 = abs(high - close_prev)
    tr3 = abs(low - close_prev)
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    
    return atr

def calculate_individual_bp(price_data):
    """Individual BuyPressure計算"""
    logging.info("Calculating Individual BuyPressure...")
    
    results = []
    
    for symbol, info in price_data['symbols'].items():
        if symbol == '^GSPC':
            continue
        
        try:
            df = pd.DataFrame(info['data'])
            
            # ATR計算
            atr = calculate_atr(df, period=14)
            
            # 価格変動
            price_change = df['close'].diff()
            
            # ATR × 0.3 以上の変動
            significant_move = abs(price_change) >= (atr * 0.3)
            
            # ドル出来高
            dollar_volume = df['close'] * df['volume']
            
            # 値上がり/値下がり
            up_volume = np.where((price_change > 0) & significant_move, dollar_volume, 0)
            down_volume = np.where((price_change < 0) & significant_move, dollar_volume, 0)
            
            # 過去20日間の累積
            up_vol_sum = pd.Series(up_volume).rolling(window=20).sum()
            down_vol_sum = pd.Series(down_volume).rolling(window=20).sum()
            
            # Buy Pressure計算
            total_vol = up_vol_sum + down_vol_sum
            bp = np.where(total_vol > 0, up_vol_sum / total_vol, np.nan)
            
            # JSON出力用（numpy配列なので直接インデックス）
            for idx in range(len(df)):
                if not np.isnan(bp[idx]):
                    results.append({
                        'date': df.iloc[idx]['date'],
                        'symbol': symbol,
                        'bp_raw': round(float(bp[idx]), 6)
                    })
        
        except Exception as e:
            logging.warning(f"Failed to calculate BP for {symbol}: {e}")
    
    # ランク計算（日付ごと）
    date_groups = defaultdict(list)
    for item in results:
        date_groups[item['date']].append(item)
    
    for date, items in date_groups.items():
        sorted_items = sorted(items, key=lambda x: x['bp_raw'], reverse=True)
        for rank, item in enumerate(sorted_items, start=1):
            item['rank'] = rank
    
    logging.info(f"Calculated BP for {len(results)} records")
    return results

def calculate_sector_industry_bp(price_data, target_stocks_df, bp_individual, group_by='sector'):
    """Sector/Industry BuyPressure計算"""
    field_name = 'Sector' if group_by == 'sector' else 'Industry'
    logging.info(f"Calculating {field_name} BuyPressure...")
    
    # 銘柄→グループのマッピング
    symbol_to_group = dict(zip(target_stocks_df['Symbol'], target_stocks_df[field_name]))
    
    # 時価総額（簡易: 最新close × volume）
    market_caps = {}
    for symbol, info in price_data['symbols'].items():
        if symbol == '^GSPC':
            continue
        try:
            latest = info['data'][-1]
            market_caps[symbol] = latest['close'] * latest['volume']
        except:
            market_caps[symbol] = 1.0
    
    # 日付ごとにグループ化
    date_symbol_bp = defaultdict(dict)
    for item in bp_individual:
        date_symbol_bp[item['date']][item['symbol']] = item['bp_raw']
    
    # グループごとに集約
    results = []
    groups = target_stocks_df[field_name].unique()
    
    for date, symbol_bp_dict in date_symbol_bp.items():
        for group in groups:
            symbols_in_group = target_stocks_df[target_stocks_df[field_name] == group]['Symbol'].tolist()
            symbols_in_group = [s for s in symbols_in_group if s in symbol_bp_dict]
            
            if not symbols_in_group:
                continue
            
            # 時価総額加重平均
            weights = {s: market_caps.get(s, 1.0) for s in symbols_in_group}
            total_weight = sum(weights.values())
            
            weighted_bp = sum(symbol_bp_dict[s] * weights[s] / total_weight for s in symbols_in_group)
            
            results.append({
                'date': date,
                group_by: group,
                'bp_raw': round(float(weighted_bp), 6),
                'stock_count': len(symbols_in_group)
            })
    
    # ランク計算
    date_groups = defaultdict(list)
    for item in results:
        date_groups[item['date']].append(item)
    
    for date, items in date_groups.items():
        sorted_items = sorted(items, key=lambda x: x['bp_raw'], reverse=True)
        for rank, item in enumerate(sorted_items, start=1):
            item['rank'] = rank
    
    logging.info(f"Calculated {field_name} BP for {len(results)} records")
    return results

def main():
    logging.info("=" * 60)
    logging.info("Starting Daily BuyPressure Calculation")
    logging.info("=" * 60)
    
    # データ読み込み
    with open(TEMP_PRICE_JSON, 'r') as f:
        price_data = json.load(f)
    
    target_stocks_df = pd.read_csv(TARGET_STOCKS_CSV)
    
    # Individual BP
    bp_individual = calculate_individual_bp(price_data)
    
    with open(OUTPUT_BP_INDIVIDUAL, 'w') as f:
        json.dump(bp_individual, f, indent=2)
    logging.info(f"Saved: {OUTPUT_BP_INDIVIDUAL}")
    
    # Sector BP
    bp_sector = calculate_sector_industry_bp(price_data, target_stocks_df, bp_individual, group_by='sector')
    
    with open(OUTPUT_BP_SECTOR, 'w') as f:
        json.dump(bp_sector, f, indent=2)
    logging.info(f"Saved: {OUTPUT_BP_SECTOR}")
    
    # Industry BP
    bp_industry = calculate_sector_industry_bp(price_data, target_stocks_df, bp_individual, group_by='industry')
    
    with open(OUTPUT_BP_INDUSTRY, 'w') as f:
        json.dump(bp_industry, f, indent=2)
    logging.info(f"Saved: {OUTPUT_BP_INDUSTRY}")
    
    logging.info("=" * 60)
    logging.info("Daily BuyPressure Calculation Complete!")
    logging.info("=" * 60)

if __name__ == "__main__":
    main()

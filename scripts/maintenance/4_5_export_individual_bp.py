"""
4_5_export_individual_bp.py

Individual BuyPressure を年別JSONに出力
"""
import os
import pandas as pd
import logging
import pickle
import json
from collections import defaultdict

DATA_FOLDER = "data"
MAINTENANCE_FOLDER = os.path.join(DATA_FOLDER, "maintenance")
TARGET_STOCKS_CSV = os.path.join(DATA_FOLDER, "target_stocks_latest.csv")

INPUT_BP_RAW = os.path.join(MAINTENANCE_FOLDER, "temp_bp_raw.pkl")

R2_OUTPUT = os.path.join(MAINTENANCE_FOLDER, "r2")
SCORES_BP_INDIVIDUAL = os.path.join(R2_OUTPUT, "scores", "BuyPressure", "individual")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def export_individual_bp_to_json(bp_raw, symbols_info, output_dir):
    """Individual BuyPressure を年別JSONに出力"""
    logging.info("Exporting Individual BuyPressure to JSON...")
    
    os.makedirs(output_dir, exist_ok=True)
    
    data_by_year = defaultdict(list)
    
    for date_idx, date in enumerate(bp_raw.index):
        date_ts = pd.Timestamp(date)
        year = date_ts.year
        date_str = date_ts.strftime('%Y-%m-%d')
        
        # 各銘柄のBP値を取得
        bp_values = {}
        for symbol in bp_raw.columns:
            bp_val = bp_raw.iloc[date_idx][symbol]
            if pd.notna(bp_val):
                bp_values[symbol] = float(bp_val)
        
        # ランク計算
        sorted_items = sorted(bp_values.items(), key=lambda x: x[1], reverse=True)
        
        for rank, (symbol, bp_val) in enumerate(sorted_items, start=1):
            info = symbols_info.get(symbol, {})
            
            data_by_year[year].append({
                'date': date_str,
                'ticker': symbol,
                'bp_raw': round(bp_val, 6),
                'rank': rank
            })
        
        if (date_idx + 1) % 1000 == 0:
            logging.info(f"  Progress: {date_idx + 1}/{len(bp_raw)} dates")
    
    # 年ごとに保存
    for year, records in data_by_year.items():
        output_file = os.path.join(output_dir, f"{year}.json")
        with open(output_file, 'w') as f:
            json.dump(records, f, indent=2)
        logging.info(f"  {year}.json: {len(records)} records")

def main():
    logging.info("=" * 60)
    logging.info("Starting Individual BuyPressure JSON Export")
    logging.info("=" * 60)
    
    # データ読み込み
    with open(INPUT_BP_RAW, 'rb') as f:
        bp_raw = pickle.load(f)
    
    df_stocks = pd.read_csv(TARGET_STOCKS_CSV)
    
    symbols_info = {}
    for _, row in df_stocks.iterrows():
        symbol = row['Symbol']
        if not isinstance(symbol, str):
            continue
        symbol = symbol.strip()
        symbols_info[symbol] = {
            'name': row.get('Company Name', symbol),
            'sector': row.get('Sector', 'N/A'),
            'industry': row.get('Industry', 'N/A')
        }
    
    # エクスポート
    export_individual_bp_to_json(bp_raw, symbols_info, SCORES_BP_INDIVIDUAL)
    
    logging.info("=" * 60)
    logging.info("✅ Individual BuyPressure JSON Export Complete!")
    logging.info("=" * 60)

if __name__ == "__main__":
    main()

"""
4_2_export_individual_rrs.py

Individual RRS のみをJSONに出力
入力: data/maintenance/temp_rrs_raw.pkl
      data/maintenance/temp_rrs_percentile.pkl
      data/target_stocks_latest.csv
出力: data/maintenance/r2/scores/RRS_scores/individual/{year}.json
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

# 入力ファイル
INPUT_RRS_RAW = os.path.join(MAINTENANCE_FOLDER, "temp_rrs_raw.pkl")
INPUT_RRS_PERCENTILE = os.path.join(MAINTENANCE_FOLDER, "temp_rrs_percentile.pkl")

# 出力ディレクトリ
R2_OUTPUT = os.path.join(MAINTENANCE_FOLDER, "r2")
SCORES_RRS_INDIVIDUAL = os.path.join(R2_OUTPUT, "scores", "RRS_scores", "individual")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def export_individual_rrs_to_json(rrs_raw_df, rrs_percentile_df, symbols_info, output_dir):
    """
    Individual RRS を年別JSONに出力
    """
    logging.info("Exporting Individual RRS to JSON...")
    
    os.makedirs(output_dir, exist_ok=True)
    
    # 年ごとにデータをグループ化
    data_by_year = defaultdict(list)
    
    total_dates = len(rrs_raw_df.index)
    processed = 0
    
    for date in rrs_raw_df.index:
        processed += 1
        year = date.year
        
        # その日のRRS値を取得
        rrs_raw_series = rrs_raw_df.loc[date]
        rrs_percentile_series = rrs_percentile_df.loc[date]
        
        # 有効なデータのみ抽出
        valid_data = []
        for ticker in rrs_raw_series.index:
            rrs_raw_val = rrs_raw_series[ticker]
            rrs_percentile_val = rrs_percentile_series[ticker]
            
            if pd.notna(rrs_raw_val) and pd.notna(rrs_percentile_val):
                info = symbols_info.get(ticker, {})
                
                valid_data.append({
                    'ticker': ticker,
                    'rrs_raw': float(rrs_raw_val),
                    'rrs_percentile': float(rrs_percentile_val),
                    'name': info.get('name', ticker),
                    'sector': info.get('sector', 'N/A'),
                    'industry': info.get('industry', 'N/A')
                })
        
        # ランキング計算（rrs_percentile降順）
        valid_data.sort(key=lambda x: x['rrs_percentile'], reverse=True)
        
        for rank, item in enumerate(valid_data, start=1):
            data_by_year[year].append({
                'date': date.strftime('%Y-%m-%d'),
                'ticker': item['ticker'],
                'name': item['name'],
                'sector': item['sector'],
                'industry': item['industry'],
                'rrs_raw': item['rrs_raw'],
                'rrs_percentile': item['rrs_percentile'],
                'rank': rank
            })
        
        if processed % 1000 == 0:
            logging.info(f"  Progress: {processed}/{total_dates} dates")
    
    # 年ごとにJSONファイルに出力
    for year, records in data_by_year.items():
        output_file = os.path.join(output_dir, f"{year}.json")
        
        with open(output_file, 'w') as f:
            json.dump(records, f, indent=2)
        
        logging.info(f"  {year}.json: {len(records)} records")

def main():
    """メイン処理"""
    logging.info("="*60)
    logging.info("STEP 4-2: EXPORT INDIVIDUAL RRS TO JSON")
    logging.info("="*60)
    
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
    
    # Individual RRS
    logging.info("Loading RRS data...")
    with open(INPUT_RRS_RAW, 'rb') as f:
        rrs_raw_df = pickle.load(f)
    with open(INPUT_RRS_PERCENTILE, 'rb') as f:
        rrs_percentile_df = pickle.load(f)
    
    export_individual_rrs_to_json(rrs_raw_df, rrs_percentile_df, symbols_info, SCORES_RRS_INDIVIDUAL)
    
    logging.info("="*60)
    logging.info("✅ STEP 4-2 COMPLETED!")
    logging.info(f"Output: {SCORES_RRS_INDIVIDUAL}")
    logging.info("="*60)
    logging.info("\nNext steps:")
    logging.info("1. Upload to R2:")
    logging.info("   python scripts/maintenance/upload_individual_rrs_to_r2.py")
    logging.info("2. Delete local files:")
    logging.info("   rm data/maintenance/temp_rrs_*.pkl")
    logging.info("   rm -r data/maintenance/r2/scores/RRS_scores/individual/")
    
    return True

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)
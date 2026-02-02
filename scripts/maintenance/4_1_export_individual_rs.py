"""
4_1_export_individual_rs.py

Individual RS のみをJSONに出力
入力: data/maintenance/temp_rs_raw.pkl
      data/maintenance/temp_rs_percentile.pkl
      data/target_stocks_latest.csv
出力: data/maintenance/r2/scores/RS_scores/individual/{year}.json
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
INPUT_RS_RAW = os.path.join(MAINTENANCE_FOLDER, "temp_rs_raw.pkl")
INPUT_RS_PERCENTILE = os.path.join(MAINTENANCE_FOLDER, "temp_rs_percentile.pkl")

# 出力ディレクトリ
R2_OUTPUT = os.path.join(MAINTENANCE_FOLDER, "r2")
SCORES_RS_INDIVIDUAL = os.path.join(R2_OUTPUT, "scores", "RS_scores", "individual")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def export_individual_rs_to_json(rs_raw_df, rs_percentile_df, symbols_info, output_dir):
    """
    Individual RS を年別JSONに出力
    """
    logging.info("Exporting Individual RS to JSON...")
    
    os.makedirs(output_dir, exist_ok=True)
    
    # 年ごとにデータをグループ化
    data_by_year = defaultdict(list)
    
    total_dates = len(rs_raw_df.index)
    processed = 0
    
    for date in rs_raw_df.index:
        processed += 1
        year = date.year
        
        # その日のRS値を取得
        rs_raw_series = rs_raw_df.loc[date]
        rs_percentile_series = rs_percentile_df.loc[date]
        
        # 有効なデータのみ抽出
        valid_data = []
        for ticker in rs_raw_series.index:
            rs_raw_val = rs_raw_series[ticker]
            rs_percentile_val = rs_percentile_series[ticker]
            
            if pd.notna(rs_raw_val) and pd.notna(rs_percentile_val):
                info = symbols_info.get(ticker, {})
                
                valid_data.append({
                    'ticker': ticker,
                    'rs_raw': float(rs_raw_val),
                    'rs_percentile': float(rs_percentile_val),
                    'name': info.get('name', ticker),
                    'sector': info.get('sector', 'N/A'),
                    'industry': info.get('industry', 'N/A')
                })
        
        # ランキング計算（rs_percentile降順）
        valid_data.sort(key=lambda x: x['rs_percentile'], reverse=True)
        
        for rank, item in enumerate(valid_data, start=1):
            data_by_year[year].append({
                'date': date.strftime('%Y-%m-%d'),
                'ticker': item['ticker'],
                'name': item['name'],
                'sector': item['sector'],
                'industry': item['industry'],
                'rs_raw': item['rs_raw'],
                'rs_percentile': item['rs_percentile'],
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
    logging.info("STEP 4-1: EXPORT INDIVIDUAL RS TO JSON")
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
    
    # Individual RS
    logging.info("Loading RS data...")
    with open(INPUT_RS_RAW, 'rb') as f:
        rs_raw_df = pickle.load(f)
    with open(INPUT_RS_PERCENTILE, 'rb') as f:
        rs_percentile_df = pickle.load(f)
    
    export_individual_rs_to_json(rs_raw_df, rs_percentile_df, symbols_info, SCORES_RS_INDIVIDUAL)
    
    logging.info("="*60)
    logging.info("✅ STEP 4-1 COMPLETED!")
    logging.info(f"Output: {SCORES_RS_INDIVIDUAL}")
    logging.info("="*60)
    logging.info("\nNext steps:")
    logging.info("1. Upload to R2:")
    logging.info("   python scripts/maintenance/upload_individual_rs_to_r2.py")
    logging.info("2. Delete local files:")
    logging.info("   rm data/maintenance/temp_rs_*.pkl")
    logging.info("   rm -r data/maintenance/r2/scores/RS_scores/individual/")
    
    return True

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)
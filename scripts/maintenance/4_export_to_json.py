"""
4_export_to_json.py

RS/RRS データを年別JSONファイルに出力
入力: data/maintenance/temp_*.pkl (12個のpickleファイル)
      data/target_stocks_latest.csv
出力: data/maintenance/r2/scores/RS_scores/individual/{year}.json
      data/maintenance/r2/scores/RS_scores/sector/{year}.json
      data/maintenance/r2/scores/RS_scores/industry/{year}.json
      data/maintenance/r2/scores/RRS_scores/individual/{year}.json
      data/maintenance/r2/scores/RRS_scores/sector/{year}.json
      data/maintenance/r2/scores/RRS_scores/industry/{year}.json
"""
import os
import pandas as pd
import numpy as np
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
INPUT_RRS_RAW = os.path.join(MAINTENANCE_FOLDER, "temp_rrs_raw.pkl")
INPUT_RRS_PERCENTILE = os.path.join(MAINTENANCE_FOLDER, "temp_rrs_percentile.pkl")

INPUT_SECTOR_RS_RAW = os.path.join(MAINTENANCE_FOLDER, "temp_sector_rs_raw.pkl")
INPUT_SECTOR_RS_PERCENTILE = os.path.join(MAINTENANCE_FOLDER, "temp_sector_rs_percentile.pkl")
INPUT_SECTOR_RRS_RAW = os.path.join(MAINTENANCE_FOLDER, "temp_sector_rrs_raw.pkl")
INPUT_SECTOR_RRS_PERCENTILE = os.path.join(MAINTENANCE_FOLDER, "temp_sector_rrs_percentile.pkl")

INPUT_INDUSTRY_RS_RAW = os.path.join(MAINTENANCE_FOLDER, "temp_industry_rs_raw.pkl")
INPUT_INDUSTRY_RS_PERCENTILE = os.path.join(MAINTENANCE_FOLDER, "temp_industry_rs_percentile.pkl")
INPUT_INDUSTRY_RRS_RAW = os.path.join(MAINTENANCE_FOLDER, "temp_industry_rrs_raw.pkl")
INPUT_INDUSTRY_RRS_PERCENTILE = os.path.join(MAINTENANCE_FOLDER, "temp_industry_rrs_percentile.pkl")

# 出力ディレクトリ
R2_OUTPUT = os.path.join(MAINTENANCE_FOLDER, "r2")
SCORES_RS_INDIVIDUAL = os.path.join(R2_OUTPUT, "scores", "RS_scores", "individual")
SCORES_RS_SECTOR = os.path.join(R2_OUTPUT, "scores", "RS_scores", "sector")
SCORES_RS_INDUSTRY = os.path.join(R2_OUTPUT, "scores", "RS_scores", "industry")
SCORES_RRS_INDIVIDUAL = os.path.join(R2_OUTPUT, "scores", "RRS_scores", "individual")
SCORES_RRS_SECTOR = os.path.join(R2_OUTPUT, "scores", "RRS_scores", "sector")
SCORES_RRS_INDUSTRY = os.path.join(R2_OUTPUT, "scores", "RRS_scores", "industry")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_output_directories():
    """出力ディレクトリを作成"""
    for directory in [SCORES_RS_INDIVIDUAL, SCORES_RS_SECTOR, SCORES_RS_INDUSTRY,
                      SCORES_RRS_INDIVIDUAL, SCORES_RRS_SECTOR, SCORES_RRS_INDUSTRY]:
        os.makedirs(directory, exist_ok=True)

def export_individual_rs_to_json(rs_raw_df, rs_percentile_df, symbols_info, output_dir):
    """
    Individual RS を年別JSONに出力
    
    JSONフォーマット:
    [
        {
            "date": "2024-01-15",
            "ticker": "AAPL",
            "name": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "rs_raw": 12.5,
            "rs_percentile": 85.3,
            "rank": 234
        },
        ...
    ]
    """
    logging.info("Exporting Individual RS to JSON...")
    
    # 年ごとにデータをグループ化
    data_by_year = defaultdict(list)
    
    for date in rs_raw_df.index:
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
    
    # 年ごとにJSONファイルに出力
    for year, records in data_by_year.items():
        output_file = os.path.join(output_dir, f"{year}.json")
        
        with open(output_file, 'w') as f:
            json.dump(records, f, indent=2)
        
        logging.info(f"  {year}.json: {len(records)} records")

def export_individual_rrs_to_json(rrs_raw_df, rrs_percentile_df, symbols_info, output_dir):
    """
    Individual RRS を年別JSONに出力
    """
    logging.info("Exporting Individual RRS to JSON...")
    
    # 年ごとにデータをグループ化
    data_by_year = defaultdict(list)
    
    for date in rrs_raw_df.index:
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
    
    # 年ごとにJSONファイルに出力
    for year, records in data_by_year.items():
        output_file = os.path.join(output_dir, f"{year}.json")
        
        with open(output_file, 'w') as f:
            json.dump(records, f, indent=2)
        
        logging.info(f"  {year}.json: {len(records)} records")

def export_sector_rs_to_json(sector_rs_raw_list, sector_rs_percentile_list, output_dir):
    """
    Sector RS を年別JSONに出力
    
    JSONフォーマット:
    [
        {
            "date": "2024-01-15",
            "sector": "Technology",
            "rs_raw": 8.5,
            "rs_percentile": 92.1,
            "rank": 2,
            "stock_count": 450
        },
        ...
    ]
    """
    logging.info("Exporting Sector RS to JSON...")
    
    # raw_listとpercentile_listをマージ
    percentile_dict = {date: scores for date, scores in sector_rs_percentile_list}
    
    # 年ごとにデータをグループ化
    data_by_year = defaultdict(list)
    
    for date, sector_scores in sector_rs_raw_list:
        year = date.year
        
        # パーセンタイルデータを取得
        percentile_scores = percentile_dict.get(date, {})
        
        # 有効なデータのみ抽出
        valid_data = []
        for sector, scores in sector_scores.items():
            if sector in percentile_scores:
                valid_data.append({
                    'sector': sector,
                    'rs_raw': scores['rs_raw'],
                    'rs_percentile': percentile_scores[sector]['rs_percentile'],
                    'stock_count': scores['stock_count']
                })
        
        # ランキング計算（rs_percentile降順）
        valid_data.sort(key=lambda x: x['rs_percentile'], reverse=True)
        
        for rank, item in enumerate(valid_data, start=1):
            data_by_year[year].append({
                'date': date.strftime('%Y-%m-%d'),
                'sector': item['sector'],
                'rs_raw': float(item['rs_raw']),
                'rs_percentile': float(item['rs_percentile']),
                'rank': rank,
                'stock_count': item['stock_count']
            })
    
    # 年ごとにJSONファイルに出力
    for year, records in data_by_year.items():
        output_file = os.path.join(output_dir, f"{year}.json")
        
        with open(output_file, 'w') as f:
            json.dump(records, f, indent=2)
        
        logging.info(f"  {year}.json: {len(records)} records")

def export_sector_rrs_to_json(sector_rrs_raw_list, sector_rrs_percentile_list, output_dir):
    """
    Sector RRS を年別JSONに出力
    """
    logging.info("Exporting Sector RRS to JSON...")
    
    # raw_listとpercentile_listをマージ
    percentile_dict = {date: scores for date, scores in sector_rrs_percentile_list}
    
    # 年ごとにデータをグループ化
    data_by_year = defaultdict(list)
    
    for date, sector_scores in sector_rrs_raw_list:
        year = date.year
        
        # パーセンタイルデータを取得
        percentile_scores = percentile_dict.get(date, {})
        
        # 有効なデータのみ抽出
        valid_data = []
        for sector, scores in sector_scores.items():
            if 'rrs_raw' in scores and sector in percentile_scores:
                valid_data.append({
                    'sector': sector,
                    'rrs_raw': scores['rrs_raw'],
                    'rrs_percentile': percentile_scores[sector]['rrs_percentile'],
                    'stock_count': scores['stock_count']
                })
        
        # ランキング計算（rrs_percentile降順）
        valid_data.sort(key=lambda x: x['rrs_percentile'], reverse=True)
        
        for rank, item in enumerate(valid_data, start=1):
            data_by_year[year].append({
                'date': date.strftime('%Y-%m-%d'),
                'sector': item['sector'],
                'rrs_raw': float(item['rrs_raw']),
                'rrs_percentile': float(item['rrs_percentile']),
                'rank': rank,
                'stock_count': item['stock_count']
            })
    
    # 年ごとにJSONファイルに出力
    for year, records in data_by_year.items():
        output_file = os.path.join(output_dir, f"{year}.json")
        
        with open(output_file, 'w') as f:
            json.dump(records, f, indent=2)
        
        logging.info(f"  {year}.json: {len(records)} records")

def export_industry_rs_to_json(industry_rs_raw_list, industry_rs_percentile_list, output_dir):
    """
    Industry RS を年別JSONに出力
    
    JSONフォーマット:
    [
        {
            "date": "2024-01-15",
            "industry": "Semiconductors",
            "sector": "Technology",
            "rs_raw": 15.2,
            "rs_percentile": 88.5,
            "rank": 12,
            "stock_count": 85
        },
        ...
    ]
    """
    logging.info("Exporting Industry RS to JSON...")
    
    # raw_listとpercentile_listをマージ
    percentile_dict = {date: scores for date, scores in industry_rs_percentile_list}
    
    # 年ごとにデータをグループ化
    data_by_year = defaultdict(list)
    
    for date, industry_scores in industry_rs_raw_list:
        year = date.year
        
        # パーセンタイルデータを取得
        percentile_scores = percentile_dict.get(date, {})
        
        # 有効なデータのみ抽出
        valid_data = []
        for industry, scores in industry_scores.items():
            if industry in percentile_scores:
                valid_data.append({
                    'industry': industry,
                    'sector': scores['sector'],
                    'rs_raw': scores['rs_raw'],
                    'rs_percentile': percentile_scores[industry]['rs_percentile'],
                    'stock_count': scores['stock_count']
                })
        
        # ランキング計算（rs_percentile降順）
        valid_data.sort(key=lambda x: x['rs_percentile'], reverse=True)
        
        for rank, item in enumerate(valid_data, start=1):
            data_by_year[year].append({
                'date': date.strftime('%Y-%m-%d'),
                'industry': item['industry'],
                'sector': item['sector'],
                'rs_raw': float(item['rs_raw']),
                'rs_percentile': float(item['rs_percentile']),
                'rank': rank,
                'stock_count': item['stock_count']
            })
    
    # 年ごとにJSONファイルに出力
    for year, records in data_by_year.items():
        output_file = os.path.join(output_dir, f"{year}.json")
        
        with open(output_file, 'w') as f:
            json.dump(records, f, indent=2)
        
        logging.info(f"  {year}.json: {len(records)} records")

def export_industry_rrs_to_json(industry_rrs_raw_list, industry_rrs_percentile_list, output_dir):
    """
    Industry RRS を年別JSONに出力
    """
    logging.info("Exporting Industry RRS to JSON...")
    
    # raw_listとpercentile_listをマージ
    percentile_dict = {date: scores for date, scores in industry_rrs_percentile_list}
    
    # 年ごとにデータをグループ化
    data_by_year = defaultdict(list)
    
    for date, industry_scores in industry_rrs_raw_list:
        year = date.year
        
        # パーセンタイルデータを取得
        percentile_scores = percentile_dict.get(date, {})
        
        # 有効なデータのみ抽出
        valid_data = []
        for industry, scores in industry_scores.items():
            if 'rrs_raw' in scores and industry in percentile_scores:
                valid_data.append({
                    'industry': industry,
                    'sector': scores['sector'],
                    'rrs_raw': scores['rrs_raw'],
                    'rrs_percentile': percentile_scores[industry]['rrs_percentile'],
                    'stock_count': scores['stock_count']
                })
        
        # ランキング計算（rrs_percentile降順）
        valid_data.sort(key=lambda x: x['rrs_percentile'], reverse=True)
        
        for rank, item in enumerate(valid_data, start=1):
            data_by_year[year].append({
                'date': date.strftime('%Y-%m-%d'),
                'industry': item['industry'],
                'sector': item['sector'],
                'rrs_raw': float(item['rrs_raw']),
                'rrs_percentile': float(item['rrs_percentile']),
                'rank': rank,
                'stock_count': item['stock_count']
            })
    
    # 年ごとにJSONファイルに出力
    for year, records in data_by_year.items():
        output_file = os.path.join(output_dir, f"{year}.json")
        
        with open(output_file, 'w') as f:
            json.dump(records, f, indent=2)
        
        logging.info(f"  {year}.json: {len(records)} records")

def main():
    """メイン処理"""
    logging.info("="*60)
    logging.info("STEP 4: EXPORT TO JSON")
    logging.info("="*60)
    
    # 出力ディレクトリ作成
    create_output_directories()
    
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
    
    # Individual RS/RRS
    logging.info("\n--- Individual RS ---")
    with open(INPUT_RS_RAW, 'rb') as f:
        rs_raw_df = pickle.load(f)
    with open(INPUT_RS_PERCENTILE, 'rb') as f:
        rs_percentile_df = pickle.load(f)
    
    export_individual_rs_to_json(rs_raw_df, rs_percentile_df, symbols_info, SCORES_RS_INDIVIDUAL)
    
    logging.info("\n--- Individual RRS ---")
    with open(INPUT_RRS_RAW, 'rb') as f:
        rrs_raw_df = pickle.load(f)
    with open(INPUT_RRS_PERCENTILE, 'rb') as f:
        rrs_percentile_df = pickle.load(f)
    
    export_individual_rrs_to_json(rrs_raw_df, rrs_percentile_df, symbols_info, SCORES_RRS_INDIVIDUAL)
    
    # Sector RS/RRS
    logging.info("\n--- Sector RS ---")
    with open(INPUT_SECTOR_RS_RAW, 'rb') as f:
        sector_rs_raw_list = pickle.load(f)
    with open(INPUT_SECTOR_RS_PERCENTILE, 'rb') as f:
        sector_rs_percentile_list = pickle.load(f)
    
    export_sector_rs_to_json(sector_rs_raw_list, sector_rs_percentile_list, SCORES_RS_SECTOR)
    
    logging.info("\n--- Sector RRS ---")
    with open(INPUT_SECTOR_RRS_RAW, 'rb') as f:
        sector_rrs_raw_list = pickle.load(f)
    with open(INPUT_SECTOR_RRS_PERCENTILE, 'rb') as f:
        sector_rrs_percentile_list = pickle.load(f)
    
    export_sector_rrs_to_json(sector_rrs_raw_list, sector_rrs_percentile_list, SCORES_RRS_SECTOR)
    
    # Industry RS/RRS
    logging.info("\n--- Industry RS ---")
    with open(INPUT_INDUSTRY_RS_RAW, 'rb') as f:
        industry_rs_raw_list = pickle.load(f)
    with open(INPUT_INDUSTRY_RS_PERCENTILE, 'rb') as f:
        industry_rs_percentile_list = pickle.load(f)
    
    export_industry_rs_to_json(industry_rs_raw_list, industry_rs_percentile_list, SCORES_RS_INDUSTRY)
    
    logging.info("\n--- Industry RRS ---")
    with open(INPUT_INDUSTRY_RRS_RAW, 'rb') as f:
        industry_rrs_raw_list = pickle.load(f)
    with open(INPUT_INDUSTRY_RRS_PERCENTILE, 'rb') as f:
        industry_rrs_percentile_list = pickle.load(f)
    
    export_industry_rrs_to_json(industry_rrs_raw_list, industry_rrs_percentile_list, SCORES_RRS_INDUSTRY)
    
    logging.info("="*60)
    logging.info("✅ STEP 4 COMPLETED!")
    logging.info(f"Output: {R2_OUTPUT}")
    logging.info("="*60)
    
    return True

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)
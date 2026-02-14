"""
4_6_export_sector_industry_bp.py

Sector/Industry BuyPressure を年別JSONに出力
"""
import os
import pandas as pd
import logging
import pickle
import json
from collections import defaultdict

DATA_FOLDER = "data"
MAINTENANCE_FOLDER = os.path.join(DATA_FOLDER, "maintenance")

INPUT_SECTOR_BP_RAW = os.path.join(MAINTENANCE_FOLDER, "temp_sector_bp_raw.pkl")
INPUT_INDUSTRY_BP_RAW = os.path.join(MAINTENANCE_FOLDER, "temp_industry_bp_raw.pkl")

R2_OUTPUT = os.path.join(MAINTENANCE_FOLDER, "r2")
SCORES_BP_SECTOR = os.path.join(R2_OUTPUT, "scores", "BuyPressure", "sector")
SCORES_BP_INDUSTRY = os.path.join(R2_OUTPUT, "scores", "BuyPressure", "industry")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def export_sector_bp_to_json(sector_bp_raw_list, output_dir):
    """Sector BuyPressure を年別JSONに出力"""
    logging.info("Exporting Sector BuyPressure to JSON...")
    
    os.makedirs(output_dir, exist_ok=True)
    
    data_by_year = defaultdict(list)
    
    for date, sector_scores in sector_bp_raw_list:
        date_ts = pd.Timestamp(date)
        year = date_ts.year
        date_str = date_ts.strftime('%Y-%m-%d')
        
        # ランク計算
        valid_data = []
        for sector, scores in sector_scores.items():
            valid_data.append({
                'sector': sector,
                'bp_raw': scores['bp_raw'],
                'stock_count': scores['stock_count']
            })
        
        valid_data.sort(key=lambda x: x['bp_raw'], reverse=True)
        
        for rank, item in enumerate(valid_data, start=1):
            data_by_year[year].append({
                'date': date_str,
                'sector': item['sector'],
                'bp_raw': round(float(item['bp_raw']), 6),
                'rank': rank,
                'stock_count': item['stock_count']
            })
    
    # 年ごとに保存
    for year, records in data_by_year.items():
        output_file = os.path.join(output_dir, f"{year}.json")
        with open(output_file, 'w') as f:
            json.dump(records, f, indent=2)
        logging.info(f"  {year}.json: {len(records)} records")

def export_industry_bp_to_json(industry_bp_raw_list, output_dir):
    """Industry BuyPressure を年別JSONに出力"""
    logging.info("Exporting Industry BuyPressure to JSON...")
    
    os.makedirs(output_dir, exist_ok=True)
    
    data_by_year = defaultdict(list)
    
    for date, industry_scores in industry_bp_raw_list:
        date_ts = pd.Timestamp(date)
        year = date_ts.year
        date_str = date_ts.strftime('%Y-%m-%d')
        
        # ランク計算
        valid_data = []
        for industry, scores in industry_scores.items():
            valid_data.append({
                'industry': industry,
                'bp_raw': scores['bp_raw'],
                'sector': scores['sector'],
                'stock_count': scores['stock_count']
            })
        
        valid_data.sort(key=lambda x: x['bp_raw'], reverse=True)
        
        for rank, item in enumerate(valid_data, start=1):
            data_by_year[year].append({
                'date': date_str,
                'industry': item['industry'],
                'bp_raw': round(float(item['bp_raw']), 6),
                'rank': rank,
                'sector': item['sector'],
                'stock_count': item['stock_count']
            })
    
    # 年ごとに保存
    for year, records in data_by_year.items():
        output_file = os.path.join(output_dir, f"{year}.json")
        with open(output_file, 'w') as f:
            json.dump(records, f, indent=2)
        logging.info(f"  {year}.json: {len(records)} records")

def main():
    logging.info("=" * 60)
    logging.info("Starting Sector/Industry BuyPressure JSON Export")
    logging.info("=" * 60)
    
    # Sector BP
    with open(INPUT_SECTOR_BP_RAW, 'rb') as f:
        sector_bp_raw_list = pickle.load(f)
    
    export_sector_bp_to_json(sector_bp_raw_list, SCORES_BP_SECTOR)
    
    # Industry BP
    with open(INPUT_INDUSTRY_BP_RAW, 'rb') as f:
        industry_bp_raw_list = pickle.load(f)
    
    export_industry_bp_to_json(industry_bp_raw_list, SCORES_BP_INDUSTRY)
    
    logging.info("=" * 60)
    logging.info("✅ Sector/Industry BuyPressure JSON Export Complete!")
    logging.info("=" * 60)

if __name__ == "__main__":
    main()

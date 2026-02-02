"""
4_3_export_sector_industry.py

Sector/Industry RS/RRS をJSONに出力
入力: data/maintenance/temp_sector_*.pkl
      data/maintenance/temp_industry_*.pkl
出力: data/maintenance/r2/scores/RS_scores/sector/{year}.json
      data/maintenance/r2/scores/RS_scores/industry/{year}.json
      data/maintenance/r2/scores/RRS_scores/sector/{year}.json
      data/maintenance/r2/scores/RRS_scores/industry/{year}.json
"""
import os
import pandas as pd
import logging
import pickle
import json
from collections import defaultdict

DATA_FOLDER = "data"
MAINTENANCE_FOLDER = os.path.join(DATA_FOLDER, "maintenance")

# 入力ファイル
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
SCORES_RS_SECTOR = os.path.join(R2_OUTPUT, "scores", "RS_scores", "sector")
SCORES_RS_INDUSTRY = os.path.join(R2_OUTPUT, "scores", "RS_scores", "industry")
SCORES_RRS_SECTOR = os.path.join(R2_OUTPUT, "scores", "RRS_scores", "sector")
SCORES_RRS_INDUSTRY = os.path.join(R2_OUTPUT, "scores", "RRS_scores", "industry")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def export_sector_rs_to_json(sector_rs_raw_list, sector_rs_percentile_list, output_dir):
    """Sector RS を年別JSONに出力"""
    logging.info("Exporting Sector RS to JSON...")
    
    os.makedirs(output_dir, exist_ok=True)
    
    percentile_dict = {date: scores for date, scores in sector_rs_percentile_list}
    data_by_year = defaultdict(list)
    
    for date, sector_scores in sector_rs_raw_list:
        # ★ 修正: numpy.datetime64 を pandas.Timestamp に変換
        date_ts = pd.Timestamp(date)
        year = date_ts.year
        
        percentile_scores = percentile_dict.get(date, {})
        
        valid_data = []
        for sector, scores in sector_scores.items():
            if sector in percentile_scores:
                valid_data.append({
                    'sector': sector,
                    'rs_raw': scores['rs_raw'],
                    'rs_percentile': percentile_scores[sector]['rs_percentile'],
                    'stock_count': scores['stock_count']
                })
        
        valid_data.sort(key=lambda x: x['rs_percentile'], reverse=True)
        
        for rank, item in enumerate(valid_data, start=1):
            data_by_year[year].append({
                'date': date_ts.strftime('%Y-%m-%d'),  # ★ 修正: date_ts を使用
                'sector': item['sector'],
                'rs_raw': float(item['rs_raw']),
                'rs_percentile': float(item['rs_percentile']),
                'rank': rank,
                'stock_count': item['stock_count']
            })
    
    for year, records in data_by_year.items():
        output_file = os.path.join(output_dir, f"{year}.json")
        with open(output_file, 'w') as f:
            json.dump(records, f, indent=2)
        logging.info(f"  {year}.json: {len(records)} records")

def export_sector_rrs_to_json(sector_rrs_raw_list, sector_rrs_percentile_list, output_dir):
    """Sector RRS を年別JSONに出力"""
    logging.info("Exporting Sector RRS to JSON...")
    
    os.makedirs(output_dir, exist_ok=True)
    
    percentile_dict = {date: scores for date, scores in sector_rrs_percentile_list}
    data_by_year = defaultdict(list)
    
    for date, sector_scores in sector_rrs_raw_list:
        # ★ 修正: numpy.datetime64 を pandas.Timestamp に変換
        date_ts = pd.Timestamp(date)
        year = date_ts.year
        
        percentile_scores = percentile_dict.get(date, {})
        
        valid_data = []
        for sector, scores in sector_scores.items():
            if 'rrs_raw' in scores and sector in percentile_scores:
                valid_data.append({
                    'sector': sector,
                    'rrs_raw': scores['rrs_raw'],
                    'rrs_percentile': percentile_scores[sector]['rrs_percentile'],
                    'stock_count': scores['stock_count']
                })
        
        valid_data.sort(key=lambda x: x['rrs_percentile'], reverse=True)
        
        for rank, item in enumerate(valid_data, start=1):
            data_by_year[year].append({
                'date': date_ts.strftime('%Y-%m-%d'),  # ★ 修正
                'sector': item['sector'],
                'rrs_raw': float(item['rrs_raw']),
                'rrs_percentile': float(item['rrs_percentile']),
                'rank': rank,
                'stock_count': item['stock_count']
            })
    
    for year, records in data_by_year.items():
        output_file = os.path.join(output_dir, f"{year}.json")
        with open(output_file, 'w') as f:
            json.dump(records, f, indent=2)
        logging.info(f"  {year}.json: {len(records)} records")

def export_industry_rs_to_json(industry_rs_raw_list, industry_rs_percentile_list, output_dir):
    """Industry RS を年別JSONに出力"""
    logging.info("Exporting Industry RS to JSON...")
    
    os.makedirs(output_dir, exist_ok=True)
    
    percentile_dict = {date: scores for date, scores in industry_rs_percentile_list}
    data_by_year = defaultdict(list)
    
    for date, industry_scores in industry_rs_raw_list:
        # ★ 修正: numpy.datetime64 を pandas.Timestamp に変換
        date_ts = pd.Timestamp(date)
        year = date_ts.year
        
        percentile_scores = percentile_dict.get(date, {})
        
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
        
        valid_data.sort(key=lambda x: x['rs_percentile'], reverse=True)
        
        for rank, item in enumerate(valid_data, start=1):
            data_by_year[year].append({
                'date': date_ts.strftime('%Y-%m-%d'),  # ★ 修正
                'industry': item['industry'],
                'sector': item['sector'],
                'rs_raw': float(item['rs_raw']),
                'rs_percentile': float(item['rs_percentile']),
                'rank': rank,
                'stock_count': item['stock_count']
            })
    
    for year, records in data_by_year.items():
        output_file = os.path.join(output_dir, f"{year}.json")
        with open(output_file, 'w') as f:
            json.dump(records, f, indent=2)
        logging.info(f"  {year}.json: {len(records)} records")

def export_industry_rrs_to_json(industry_rrs_raw_list, industry_rrs_percentile_list, output_dir):
    """Industry RRS を年別JSONに出力"""
    logging.info("Exporting Industry RRS to JSON...")
    
    os.makedirs(output_dir, exist_ok=True)
    
    percentile_dict = {date: scores for date, scores in industry_rrs_percentile_list}
    data_by_year = defaultdict(list)
    
    for date, industry_scores in industry_rrs_raw_list:
        # ★ 修正: numpy.datetime64 を pandas.Timestamp に変換
        date_ts = pd.Timestamp(date)
        year = date_ts.year
        
        percentile_scores = percentile_dict.get(date, {})
        
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
        
        valid_data.sort(key=lambda x: x['rrs_percentile'], reverse=True)
        
        for rank, item in enumerate(valid_data, start=1):
            data_by_year[year].append({
                'date': date_ts.strftime('%Y-%m-%d'),  # ★ 修正
                'industry': item['industry'],
                'sector': item['sector'],
                'rrs_raw': float(item['rrs_raw']),
                'rrs_percentile': float(item['rrs_percentile']),
                'rank': rank,
                'stock_count': item['stock_count']
            })
    
    for year, records in data_by_year.items():
        output_file = os.path.join(output_dir, f"{year}.json")
        with open(output_file, 'w') as f:
            json.dump(records, f, indent=2)
        logging.info(f"  {year}.json: {len(records)} records")

def main():
    """メイン処理"""
    logging.info("="*60)
    logging.info("STEP 4-3: EXPORT SECTOR/INDUSTRY TO JSON")
    logging.info("="*60)
    
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
    logging.info("✅ STEP 4-3 COMPLETED!")
    logging.info("="*60)
    logging.info("\nNext steps:")
    logging.info("1. Upload to R2:")
    logging.info("   python scripts/maintenance/upload_sector_industry_to_r2.py")
    logging.info("2. Delete local files:")
    logging.info("   rm data/maintenance/temp_sector_*.pkl")
    logging.info("   rm data/maintenance/temp_industry_*.pkl")
    logging.info("   rm -r data/maintenance/r2/scores/")
    
    return True

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)
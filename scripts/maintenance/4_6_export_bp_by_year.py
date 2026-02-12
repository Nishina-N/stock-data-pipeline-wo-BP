"""
4_6_export_bp_by_year.py

BuyPressureデータを年別JSONファイルに分割してエクスポート
入力:
  data/maintenance/temp_bp_individual.json
  data/maintenance/temp_bp_sector.json
  data/maintenance/temp_bp_industry.json

出力:
  data/maintenance/r2/scores/BuyPressure/individual/{year}.json
  data/maintenance/r2/scores/BuyPressure/sector/{year}.json
  data/maintenance/r2/scores/BuyPressure/industry/{year}.json
"""
import os
import json
import logging
from collections import defaultdict

DATA_FOLDER = "data"
MAINTENANCE_FOLDER = os.path.join(DATA_FOLDER, "maintenance")
R2_FOLDER = os.path.join(MAINTENANCE_FOLDER, "r2")

INPUT_BP_INDIVIDUAL = os.path.join(MAINTENANCE_FOLDER, "temp_bp_individual.json")
INPUT_BP_SECTOR = os.path.join(MAINTENANCE_FOLDER, "temp_bp_sector.json")
INPUT_BP_INDUSTRY = os.path.join(MAINTENANCE_FOLDER, "temp_bp_industry.json")

OUTPUT_BASE = os.path.join(R2_FOLDER, "scores", "BuyPressure")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def split_by_year(input_file, output_dir, category_type='individual'):
    """JSONデータを年別に分割"""
    logging.info(f"Splitting {category_type} BuyPressure by year...")
    
    # データ読み込み
    with open(input_file, 'r') as f:
        data = json.load(f)
    
    # 年ごとに分類
    year_data = defaultdict(list)
    
    for record in data:
        year = record['date'][:4]  # YYYY-MM-DD から YYYY を抽出
        year_data[year].append(record)
    
    # 出力ディレクトリ作成
    os.makedirs(output_dir, exist_ok=True)
    
    # 年ごとに保存
    for year, records in sorted(year_data.items()):
        output_file = os.path.join(output_dir, f"{year}.json")
        
        with open(output_file, 'w') as f:
            json.dump(records, f, indent=2)
        
        logging.info(f"  {year}: {len(records)} records → {output_file}")
    
    logging.info(f"Split {category_type} BP into {len(year_data)} year files")

def main():
    logging.info("=" * 60)
    logging.info("Starting BuyPressure Year-based Export")
    logging.info("=" * 60)
    
    # Individual
    output_individual = os.path.join(OUTPUT_BASE, "individual")
    split_by_year(INPUT_BP_INDIVIDUAL, output_individual, category_type='individual')
    
    # Sector
    output_sector = os.path.join(OUTPUT_BASE, "sector")
    split_by_year(INPUT_BP_SECTOR, output_sector, category_type='sector')
    
    # Industry
    output_industry = os.path.join(OUTPUT_BASE, "industry")
    split_by_year(INPUT_BP_INDUSTRY, output_industry, category_type='industry')
    
    logging.info("=" * 60)
    logging.info("BuyPressure Year-based Export Complete!")
    logging.info("=" * 60)

if __name__ == "__main__":
    main()

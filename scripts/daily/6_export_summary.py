"""
6_export_summary.py

全銘柄の最新スコアをサマリーJSONとして出力
日付ごとに1ファイル生成: stocks/summary/{date}.json

出力内容:
- 日付、シンボル、銘柄名
- 銘柄RS、銘柄RRS
- セクター名、セクターRS、セクターRRS
- 業種名、業種RS、業種RRS
"""
import json
import os
import logging
from datetime import datetime
from collections import defaultdict

DATA_FOLDER = "data"
TARGET_STOCKS_CSV = os.path.join(DATA_FOLDER, "target_stocks_latest.csv")

# 入力ファイル（6種類のスコアデータ）
TEMP_RS_INDIVIDUAL_JSON = os.path.join(DATA_FOLDER, "temp_rs_individual.json")
TEMP_RRS_INDIVIDUAL_JSON = os.path.join(DATA_FOLDER, "temp_rrs_individual.json")
TEMP_RS_SECTOR_JSON = os.path.join(DATA_FOLDER, "temp_rs_sector.json")
TEMP_RRS_SECTOR_JSON = os.path.join(DATA_FOLDER, "temp_rrs_sector.json")
TEMP_RS_INDUSTRY_JSON = os.path.join(DATA_FOLDER, "temp_rs_industry.json")
TEMP_RRS_INDUSTRY_JSON = os.path.join(DATA_FOLDER, "temp_rrs_industry.json")

# 出力ディレクトリ
R2_OUTPUT = os.path.join(DATA_FOLDER, "daily", "r2")
R2_SUMMARY = os.path.join(R2_OUTPUT, "stocks", "summary")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def load_symbols_info():
    """銘柄情報（名前、セクター、業種）を取得"""
    import pandas as pd
    
    if not os.path.exists(TARGET_STOCKS_CSV):
        logging.error(f"Target stocks file not found: {TARGET_STOCKS_CSV}")
        return {}
    
    df = pd.read_csv(TARGET_STOCKS_CSV)
    
    symbols_info = {}
    for _, row in df.iterrows():
        symbol = row['Symbol']
        symbols_info[symbol] = {
            'name': row.get('Company Name', symbol),
            'sector': row.get('Sector', 'N/A'),
            'industry': row.get('Industry', 'N/A')
        }
    
    # ^GSPC を追加
    if '^GSPC' not in symbols_info:
        symbols_info['^GSPC'] = {
            'name': 'S&P 500',
            'sector': 'Index',
            'industry': 'Index'
        }
    
    logging.info(f"Loaded info for {len(symbols_info)} symbols")
    return symbols_info

def load_json_file(filepath):
    """JSONファイルを読み込み"""
    if not os.path.exists(filepath):
        logging.warning(f"File not found: {filepath}")
        return []
    
    with open(filepath, 'r') as f:
        data = json.load(f)
    
    return data

def create_date_indexed_dict(data, key_field, value_fields):
    """
    データを {date: {key: {values}}} の形式に変換
    
    Args:
        data: リスト形式のデータ
        key_field: キーとなるフィールド名（例: 'ticker', 'sector', 'industry'）
        value_fields: 抽出する値のフィールド名リスト
    
    Returns:
        dict: {date: {key: {field1: value1, field2: value2, ...}}}
    """
    result = defaultdict(lambda: defaultdict(dict))
    
    for item in data:
        date = item.get('date')
        key = item.get(key_field)
        
        if not date or not key:
            continue
        
        for field in value_fields:
            if field in item:
                result[date][key][field] = item[field]
    
    return dict(result)

def merge_all_scores(symbols_info):
    """全スコアデータを統合"""
    logging.info("Loading all score files...")
    
    # 各スコアデータを読み込み
    rs_individual = load_json_file(TEMP_RS_INDIVIDUAL_JSON)
    rrs_individual = load_json_file(TEMP_RRS_INDIVIDUAL_JSON)
    rs_sector = load_json_file(TEMP_RS_SECTOR_JSON)
    rrs_sector = load_json_file(TEMP_RRS_SECTOR_JSON)
    rs_industry = load_json_file(TEMP_RS_INDUSTRY_JSON)
    rrs_industry = load_json_file(TEMP_RRS_INDUSTRY_JSON)
    
    logging.info(f"Loaded: Individual RS={len(rs_individual)}, RRS={len(rrs_individual)}")
    logging.info(f"Loaded: Sector RS={len(rs_sector)}, RRS={len(rrs_sector)}")
    logging.info(f"Loaded: Industry RS={len(rs_industry)}, RRS={len(rrs_industry)}")
    
    # 日付別インデックス作成
    logging.info("Creating date-indexed dictionaries...")
    
    individual_rs_by_date = create_date_indexed_dict(
        rs_individual, 'ticker', ['rs_raw', 'rs_percentile']
    )
    individual_rrs_by_date = create_date_indexed_dict(
        rrs_individual, 'ticker', ['rrs_raw', 'rrs_percentile']
    )
    sector_rs_by_date = create_date_indexed_dict(
        rs_sector, 'sector', ['rs_raw', 'rs_percentile']
    )
    sector_rrs_by_date = create_date_indexed_dict(
        rrs_sector, 'sector', ['rrs_raw', 'rrs_percentile']
    )
    industry_rs_by_date = create_date_indexed_dict(
        rs_industry, 'industry', ['rs_raw', 'rs_percentile']
    )
    industry_rrs_by_date = create_date_indexed_dict(
        rrs_industry, 'industry', ['rrs_raw', 'rrs_percentile']
    )
    
    # 全日付を取得
    all_dates = set()
    all_dates.update(individual_rs_by_date.keys())
    all_dates.update(individual_rrs_by_date.keys())
    
    all_dates = sorted(all_dates)
    logging.info(f"Found {len(all_dates)} unique dates")
    
    # 日付ごとに全銘柄データを統合
    summary_by_date = {}
    
    for date in all_dates:
        stocks_data = []
        
        # 各銘柄のデータを統合
        symbols_on_date = set()
        if date in individual_rs_by_date:
            symbols_on_date.update(individual_rs_by_date[date].keys())
        if date in individual_rrs_by_date:
            symbols_on_date.update(individual_rrs_by_date[date].keys())
        
        for symbol in symbols_on_date:
            info = symbols_info.get(symbol, {})
            sector = info.get('sector', 'N/A')
            industry = info.get('industry', 'N/A')
            
            # 銘柄スコア
            stock_rs = individual_rs_by_date.get(date, {}).get(symbol, {})
            stock_rrs = individual_rrs_by_date.get(date, {}).get(symbol, {})
            
            # セクタースコア
            sector_rs_scores = sector_rs_by_date.get(date, {}).get(sector, {})
            sector_rrs_scores = sector_rrs_by_date.get(date, {}).get(sector, {})
            
            # 業種スコア
            industry_rs_scores = industry_rs_by_date.get(date, {}).get(industry, {})
            industry_rrs_scores = industry_rrs_by_date.get(date, {}).get(industry, {})
            
            stock_data = {
                'date': date,
                'symbol': symbol,
                'name': info.get('name', symbol),
                'sector': sector,
                'sector_rs': sector_rs_scores.get('rs_percentile'),
                'sector_rrs': sector_rrs_scores.get('rrs_percentile'),
                'industry': industry,
                'industry_rs': industry_rs_scores.get('rs_percentile'),
                'industry_rrs': industry_rrs_scores.get('rrs_percentile'),
                'rs': stock_rs.get('rs_percentile'),
                'rrs': stock_rrs.get('rrs_percentile'),
            }
            
            stocks_data.append(stock_data)
        
        summary_by_date[date] = stocks_data
        logging.info(f"  {date}: {len(stocks_data)} stocks")
    
    return summary_by_date

def export_summary_files(summary_by_date):
    """日付ごとにサマリーファイルを出力"""
    logging.info("Exporting summary files...")
    
    # 出力ディレクトリ作成
    os.makedirs(R2_SUMMARY, exist_ok=True)
    
    exported_count = 0
    
    for date, stocks_data in summary_by_date.items():
        # ファイル名: YYYY-MM-DD.json
        filename = f"{date}.json"
        filepath = os.path.join(R2_SUMMARY, filename)
        
        output_data = {
            'date': date,
            'count': len(stocks_data),
            'stocks': stocks_data
        }
        
        with open(filepath, 'w') as f:
            json.dump(output_data, f, separators=(',', ':'))
        
        exported_count += 1
    
    logging.info(f"✅ Exported {exported_count} summary files to {R2_SUMMARY}")
    return exported_count

def main():
    """メイン処理"""
    logging.info("="*60)
    logging.info("EXPORT SUMMARY (ALL STOCKS WITH ALL SCORES)")
    logging.info("="*60)
    
    # 銘柄情報読み込み
    symbols_info = load_symbols_info()
    
    if not symbols_info:
        logging.error("No symbols info found")
        return False
    
    # 全スコアデータを統合
    summary_by_date = merge_all_scores(symbols_info)
    
    if not summary_by_date:
        logging.error("No summary data generated")
        return False
    
    # ファイル出力
    exported_count = export_summary_files(summary_by_date)
    
    logging.info("="*60)
    logging.info(f"✅ Summary export completed: {exported_count} files")
    logging.info("="*60)
    
    return True

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)

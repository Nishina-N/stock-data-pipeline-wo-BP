"""
4_export_to_json.py

新形式に対応: RS/RRS を6種類のファイルから読み込み、年別JSONを生成
入力:
  - temp_rs_individual.json, temp_rrs_individual.json
  - temp_rs_sector.json, temp_rrs_sector.json
  - temp_rs_industry.json, temp_rrs_industry.json

出力:
  - stocks/daily/core/{year}/{symbol}.json: OHLCV + RS/RRS
  - stocks/daily/indicators/standard/{year}/{symbol}.json: テクニカル指標
  - scores/RS_scores/individual/{year}.json
  - scores/RRS_scores/individual/{year}.json
  - scores/RS_scores/sector/{year}.json
  - scores/RRS_scores/sector/{year}.json
  - scores/RS_scores/industry/{year}.json
  - scores/RRS_scores/industry/{year}.json
"""
import json
import os
import logging
from datetime import datetime
from collections import defaultdict

DATA_FOLDER = "data"
TEMP_PRICE_JSON = os.path.join(DATA_FOLDER, "temp_prices.json")

# 6つの入力ファイル
TEMP_RS_INDIVIDUAL_JSON = os.path.join(DATA_FOLDER, "temp_rs_individual.json")
TEMP_RRS_INDIVIDUAL_JSON = os.path.join(DATA_FOLDER, "temp_rrs_individual.json")
TEMP_RS_SECTOR_JSON = os.path.join(DATA_FOLDER, "temp_rs_sector.json")
TEMP_RRS_SECTOR_JSON = os.path.join(DATA_FOLDER, "temp_rrs_sector.json")
TEMP_RS_INDUSTRY_JSON = os.path.join(DATA_FOLDER, "temp_rs_industry.json")
TEMP_RRS_INDUSTRY_JSON = os.path.join(DATA_FOLDER, "temp_rrs_industry.json")

# R2アップロード用ディレクトリ
R2_OUTPUT = os.path.join(DATA_FOLDER, "daily", "r2")
R2_STOCKS_CORE = os.path.join(R2_OUTPUT, "stocks", "daily", "core")
R2_STOCKS_INDICATORS = os.path.join(R2_OUTPUT, "stocks", "daily", "indicators", "standard")
R2_SCORES_RS = os.path.join(R2_OUTPUT, "scores", "RS_scores")
R2_SCORES_RRS = os.path.join(R2_OUTPUT, "scores", "RRS_scores")
R2_METADATA = os.path.join(R2_OUTPUT, "metadata")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_rs_rrs_dict(rs_data, rrs_data):
    """
    RS/RRSデータを日付→銘柄→値の辞書に変換
    
    Returns:
        dict: {date: {symbol: {'rs': ..., 'rrs': ...}}}
    """
    rs_rrs_dict = {}
    
    # RS データ
    for item in rs_data:
        date = item['date']
        symbol = item['ticker']
        
        if date not in rs_rrs_dict:
            rs_rrs_dict[date] = {}
        
        if symbol not in rs_rrs_dict[date]:
            rs_rrs_dict[date][symbol] = {}
        
        rs_rrs_dict[date][symbol]['rs_raw'] = item.get('rs_raw')
        rs_rrs_dict[date][symbol]['rs_percentile'] = item.get('rs_percentile')
    
    # RRS データ
    if rrs_data:
        for item in rrs_data:
            date = item['date']
            symbol = item['ticker']
            
            if date not in rs_rrs_dict:
                rs_rrs_dict[date] = {}
            
            if symbol not in rs_rrs_dict[date]:
                rs_rrs_dict[date][symbol] = {}
            
            rs_rrs_dict[date][symbol]['rrs_raw'] = item.get('rrs_raw')
            rs_rrs_dict[date][symbol]['rrs_percentile'] = item.get('rrs_percentile')
    
    return rs_rrs_dict

def group_data_by_year(data_list, date_key='date'):
    """データを年別にグループ化"""
    year_groups = defaultdict(list)
    
    for item in data_list:
        year = int(item[date_key][:4])
        year_groups[year].append(item)
    
    return dict(year_groups)

def export_core_files(price_data, rs_rrs_dict):
    """core/{year}/{symbol}.json を年別に生成"""
    logging.info("Exporting core files (OHLCV + RS/RRS, by year)...")
    
    count = 0
    failed = []
    
    for symbol, info in price_data['symbols'].items():
        
        try:
            # データを年別にグループ化
            year_groups = group_data_by_year(info['data'])
            
            # 各年ごとにファイル作成
            for year, year_data in year_groups.items():
                year_dir = os.path.join(R2_STOCKS_CORE, str(year))
                os.makedirs(year_dir, exist_ok=True)
                
                # RS/RRSを統合
                data_with_rs = []
                for data_point in year_data:
                    date = data_point['date']
                    rs_rrs = rs_rrs_dict.get(date, {}).get(symbol, {})
                    
                    data_with_rs.append({
                        'date': date,
                        'open': data_point.get('open'),
                        'high': data_point.get('high'),
                        'low': data_point.get('low'),
                        'close': data_point.get('close'),
                        'volume': data_point.get('volume'),
                        'rs_raw': rs_rrs.get('rs_raw'),
                        'rs_percentile': rs_rrs.get('rs_percentile'),
                        'rrs_raw': rs_rrs.get('rrs_raw'),
                        'rrs_percentile': rs_rrs.get('rrs_percentile')
                    })
                
                output = {
                    'ticker': symbol,
                    'name': info['name'],
                    'sector': info['sector'],
                    'industry': info['industry'],
                    'data': data_with_rs
                }
                
                output_path = os.path.join(year_dir, f"{symbol}.json")
                with open(output_path, 'w') as f:
                    json.dump(output, f)
            
            count += 1
            
            if count % 500 == 0:
                logging.info(f"  Progress: {count} symbols")
            
        except Exception as e:
            logging.error(f"Failed to export core for {symbol}: {e}")
            failed.append(symbol)
    
    logging.info(f"✅ Exported {count} symbols to core/")
    if failed:
        logging.warning(f"⚠️  Failed: {len(failed)} symbols")
    
    return count > 0

def export_indicator_files(price_data):
    """indicators/standard/{year}/{symbol}.json を年別に生成"""
    logging.info("Exporting indicator files (by year)...")
    
    count = 0
    failed = []
    
    for symbol, info in price_data['symbols'].items():

        try:
            year_groups = group_data_by_year(info['data'])
            
            for year, year_data in year_groups.items():
                year_dir = os.path.join(R2_STOCKS_INDICATORS, str(year))
                os.makedirs(year_dir, exist_ok=True)
                
                indicator_data = []
                for data_point in year_data:
                    indicator_data.append({
                        'date': data_point['date'],
                        'sma20': data_point.get('sma20'),
                        'sma50': data_point.get('sma50'),
                        'sma200': data_point.get('sma200'),
                        'ema21': data_point.get('ema21'),
                        'rsi14': data_point.get('rsi14'),
                        'atr14': data_point.get('atr14'),
                        'vwap': data_point.get('vwap')
                    })
                
                output = {
                    'ticker': symbol,
                    'indicators': ['sma20', 'sma50', 'sma200', 'ema21', 'rsi14', 'atr14', 'vwap'],
                    'data': indicator_data
                }
                
                output_path = os.path.join(year_dir, f"{symbol}.json")
                with open(output_path, 'w') as f:
                    json.dump(output, f)
            
            count += 1
            
            if count % 500 == 0:
                logging.info(f"  Progress: {count} symbols")
            
        except Exception as e:
            logging.error(f"Failed to export indicators for {symbol}: {e}")
            failed.append(symbol)
    
    logging.info(f"✅ Exported {count} symbols to indicators/")
    if failed:
        logging.warning(f"⚠️  Failed: {len(failed)} symbols")
    
    return count > 0

def export_scores_by_year(score_data, output_dir, score_type):
    """scoresファイルを年別に生成"""
    logging.info(f"Exporting {score_type} scores (by year)...")
    
    if not score_data:
        logging.warning(f"No {score_type} data to export")
        return False
    
    os.makedirs(output_dir, exist_ok=True)
    
    # 年別にグループ化
    year_groups = group_data_by_year(score_data)
    
    for year, data in year_groups.items():
        output_path = os.path.join(output_dir, f"{year}.json")
        with open(output_path, 'w') as f:
            json.dump(data, f)
        
        logging.info(f"  ✅ {score_type} {year}: {len(data)} records")
    
    return True

def export_metadata(price_data, rs_individual_data):
    """メタデータJSONを生成"""
    os.makedirs(R2_METADATA, exist_ok=True)
    
    # 日付範囲を取得
    dates = sorted(set(item['date'] for item in rs_individual_data))
    
    metadata = {
        'lastUpdated': datetime.now().isoformat(),
        'priceDataStartDate': dates[0] if dates else None,
        'priceDataEndDate': dates[-1] if dates else None,
        'totalSymbols': len([s for s in price_data['symbols'].keys() if s != '^GSPC']),
        'dataRetentionDays': len(dates),
        'pipeline': {
            'version': '3.0.0',
            'status': 'success',
            'structure': 'year-based-archive-with-rrs'
        }
    }
    
    output_path = os.path.join(R2_METADATA, "last-updated.json")
    with open(output_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    logging.info(f"✅ Exported metadata to {output_path}")
    
    return True

def main():
    """JSON変換メイン処理"""
    logging.info("="*60)
    logging.info("EXPORT TO JSON (NEW FORMAT)")
    logging.info("="*60)
    
    # データ読み込み
    if not os.path.exists(TEMP_PRICE_JSON):
        logging.error(f"Price data not found: {TEMP_PRICE_JSON}")
        return False
    
    with open(TEMP_PRICE_JSON, 'r') as f:
        price_data = json.load(f)
    
    # RS/RRS Individual
    rs_individual_data = []
    rrs_individual_data = []
    
    if os.path.exists(TEMP_RS_INDIVIDUAL_JSON):
        with open(TEMP_RS_INDIVIDUAL_JSON, 'r') as f:
            rs_individual_data = json.load(f)
    else:
        logging.warning("RS Individual data not found")
    
    if os.path.exists(TEMP_RRS_INDIVIDUAL_JSON):
        with open(TEMP_RRS_INDIVIDUAL_JSON, 'r') as f:
            rrs_individual_data = json.load(f)
    else:
        logging.warning("RRS Individual data not found")
    
    # RS/RRS Sector
    rs_sector_data = []
    rrs_sector_data = []
    
    if os.path.exists(TEMP_RS_SECTOR_JSON):
        with open(TEMP_RS_SECTOR_JSON, 'r') as f:
            rs_sector_data = json.load(f)
    
    if os.path.exists(TEMP_RRS_SECTOR_JSON):
        with open(TEMP_RRS_SECTOR_JSON, 'r') as f:
            rrs_sector_data = json.load(f)
    
    # RS/RRS Industry
    rs_industry_data = []
    rrs_industry_data = []
    
    if os.path.exists(TEMP_RS_INDUSTRY_JSON):
        with open(TEMP_RS_INDUSTRY_JSON, 'r') as f:
            rs_industry_data = json.load(f)
    
    if os.path.exists(TEMP_RRS_INDUSTRY_JSON):
        with open(TEMP_RRS_INDUSTRY_JSON, 'r') as f:
            rrs_industry_data = json.load(f)
    
    logging.info(f"Loaded: {len(price_data['symbols'])} symbols")
    logging.info(f"Loaded: {len(rs_individual_data)} Individual RS records")
    logging.info(f"Loaded: {len(rrs_individual_data)} Individual RRS records")
    logging.info(f"Loaded: {len(rs_sector_data)} Sector RS records")
    logging.info(f"Loaded: {len(rrs_sector_data)} Sector RRS records")
    logging.info(f"Loaded: {len(rs_industry_data)} Industry RS records")
    logging.info(f"Loaded: {len(rrs_industry_data)} Industry RRS records")
    
    # RS/RRSを日付ベースの辞書に変換
    rs_rrs_dict = create_rs_rrs_dict(rs_individual_data, rrs_individual_data)
    
    # Core ファイル生成
    if not export_core_files(price_data, rs_rrs_dict):
        logging.error("Failed to export core files")
        return False
    
    # Indicator ファイル生成
    if not export_indicator_files(price_data):
        logging.error("Failed to export indicator files")
        return False
    
    # Score ファイル生成（6種類）
    export_scores_by_year(rs_individual_data, os.path.join(R2_SCORES_RS, "individual"), "Individual RS")
    export_scores_by_year(rrs_individual_data, os.path.join(R2_SCORES_RRS, "individual"), "Individual RRS")
    export_scores_by_year(rs_sector_data, os.path.join(R2_SCORES_RS, "sector"), "Sector RS")
    export_scores_by_year(rrs_sector_data, os.path.join(R2_SCORES_RRS, "sector"), "Sector RRS")
    export_scores_by_year(rs_industry_data, os.path.join(R2_SCORES_RS, "industry"), "Industry RS")
    export_scores_by_year(rrs_industry_data, os.path.join(R2_SCORES_RRS, "industry"), "Industry RRS")
    
    # メタデータ生成
    if not export_metadata(price_data, rs_individual_data):
        logging.error("Failed to export metadata")
        return False
    
    logging.info("="*60)
    logging.info("✅ All JSON files exported successfully!")
    logging.info("="*60)
    
    return True

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)
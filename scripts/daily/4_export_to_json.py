"""
4_export_to_json.py

Lazy Loading構成でJSONファイルを生成
- stocks/daily/core/{symbol}.json: OHLCV + RS/RRS（時系列）
- stocks/daily/indicators/standard/{symbol}.json: テクニカル指標（時系列）
- scores/individual/latest.json: 個別銘柄RS/RRS（500日分）
- scores/sector/latest.json: セクターRS（500日分）
- scores/industry/latest.json: 業種RS（500日分）
"""
import json
import os
import logging
from datetime import datetime

DATA_FOLDER = "data"
TEMP_PRICE_JSON = os.path.join(DATA_FOLDER, "temp_prices.json")
TEMP_RS_INDIVIDUAL_JSON = os.path.join(DATA_FOLDER, "temp_rs_individual.json")
TEMP_RS_SECTOR_JSON = os.path.join(DATA_FOLDER, "temp_rs_sector.json")
TEMP_RS_INDUSTRY_JSON = os.path.join(DATA_FOLDER, "temp_rs_industry.json")

# R2アップロード用ディレクトリ
R2_OUTPUT = os.path.join(DATA_FOLDER, "r2")
R2_STOCKS_CORE = os.path.join(R2_OUTPUT, "stocks", "daily", "core")
R2_STOCKS_INDICATORS = os.path.join(R2_OUTPUT, "stocks", "daily", "indicators", "standard")
R2_SCORES_INDIVIDUAL = os.path.join(R2_OUTPUT, "scores", "individual")
R2_SCORES_SECTOR = os.path.join(R2_OUTPUT, "scores", "sector")
R2_SCORES_INDUSTRY = os.path.join(R2_OUTPUT, "scores", "industry")
R2_METADATA = os.path.join(R2_OUTPUT, "metadata")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_rs_rrs_dict(rs_data):
    """
    RS/RRSデータを日付→銘柄→値の辞書に変換
    
    Returns:
        dict: {date: {symbol: {'rs': ..., 'rrs': ...}}}
    """
    rs_dict = {}
    
    for date_entry in rs_data['data']:
        date = date_entry['date']
        rs_dict[date] = {}
        
        for score in date_entry['scores']:
            symbol = score['ticker']
            rs_dict[date][symbol] = {
                'rs': score['rs'],
                'rrs': score['rrs']
            }
    
    return rs_dict

def export_core_files(price_data, rs_rrs_dict):
    """
    core/{symbol}.json を生成
    OHLCV + RS/RRS（時系列）
    """
    os.makedirs(R2_STOCKS_CORE, exist_ok=True)
    
    logging.info("Exporting core files (OHLCV + RS/RRS)...")
    
    count = 0
    failed = []
    
    for symbol, info in price_data['symbols'].items():
        try:
            # OHLCV + RS/RRS を統合
            data_with_rs = []
            
            for data_point in info['data']:
                date = data_point['date']
                
                # RS/RRSを取得
                rs_rrs = rs_rrs_dict.get(date, {}).get(symbol, {'rs': None, 'rrs': None})
                
                data_with_rs.append({
                    'date': date,
                    'open': data_point.get('open'),
                    'high': data_point.get('high'),
                    'low': data_point.get('low'),
                    'close': data_point.get('close'),
                    'volume': data_point.get('volume'),
                    'rs': rs_rrs['rs'],
                    'rrs': rs_rrs['rrs']
                })
            
            output = {
                'ticker': symbol,
                'name': info['name'],
                'sector': info['sector'],
                'industry': info['industry'],
                'data': data_with_rs,
                'lastUpdated': price_data['lastUpdated']
            }
            
            output_path = os.path.join(R2_STOCKS_CORE, f"{symbol}.json")
            with open(output_path, 'w') as f:
                json.dump(output, f)
            
            count += 1
            
            if count % 500 == 0:
                logging.info(f"  Progress: {count}/{len(price_data['symbols'])}")
            
        except Exception as e:
            logging.error(f"Failed to export core for {symbol}: {e}")
            failed.append(symbol)
    
    logging.info(f"✅ Exported {count} core files to {R2_STOCKS_CORE}")
    if failed:
        logging.warning(f"⚠️  Failed: {len(failed)} symbols")
    
    return count > 0

def export_indicator_files(price_data):
    """
    indicators/standard/{symbol}.json を生成
    テクニカル指標のみ
    """
    os.makedirs(R2_STOCKS_INDICATORS, exist_ok=True)
    
    logging.info("Exporting indicator files (standard)...")
    
    count = 0
    failed = []
    
    for symbol, info in price_data['symbols'].items():
        try:
            # 指標データのみ抽出
            indicator_data = []
            
            for data_point in info['data']:
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
                'data': indicator_data,
                'lastUpdated': price_data['lastUpdated']
            }
            
            output_path = os.path.join(R2_STOCKS_INDICATORS, f"{symbol}.json")
            with open(output_path, 'w') as f:
                json.dump(output, f)
            
            count += 1
            
            if count % 500 == 0:
                logging.info(f"  Progress: {count}/{len(price_data['symbols'])}")
            
        except Exception as e:
            logging.error(f"Failed to export indicators for {symbol}: {e}")
            failed.append(symbol)
    
    logging.info(f"✅ Exported {count} indicator files to {R2_STOCKS_INDICATORS}")
    if failed:
        logging.warning(f"⚠️  Failed: {len(failed)} symbols")
    
    return count > 0

def export_scores(rs_individual, rs_sector, rs_industry):
    """
    scoresファイルを生成（そのままコピー）
    """
    os.makedirs(R2_SCORES_INDIVIDUAL, exist_ok=True)
    os.makedirs(R2_SCORES_SECTOR, exist_ok=True)
    os.makedirs(R2_SCORES_INDUSTRY, exist_ok=True)
    
    logging.info("Exporting score files...")
    
    # Individual
    individual_path = os.path.join(R2_SCORES_INDIVIDUAL, "latest.json")
    with open(individual_path, 'w') as f:
        json.dump(rs_individual, f)
    logging.info(f"✅ Exported Individual scores: {individual_path}")
    
    # Sector
    sector_path = os.path.join(R2_SCORES_SECTOR, "latest.json")
    with open(sector_path, 'w') as f:
        json.dump(rs_sector, f)
    logging.info(f"✅ Exported Sector scores: {sector_path}")
    
    # Industry
    industry_path = os.path.join(R2_SCORES_INDUSTRY, "latest.json")
    with open(industry_path, 'w') as f:
        json.dump(rs_industry, f)
    logging.info(f"✅ Exported Industry scores: {industry_path}")
    
    return True

def export_metadata(price_data, rs_individual):
    """メタデータJSONを生成"""
    os.makedirs(R2_METADATA, exist_ok=True)
    
    metadata = {
        'lastUpdated': datetime.now().isoformat(),
        'priceDataDate': rs_individual['endDate'],
        'totalSymbols': len(price_data['symbols']),
        'rsScoresCount': rs_individual['totalStocks'],
        'dataRetentionDays': 1000,
        'rsDays': rs_individual['days'],
        'pipeline': {
            'version': '2.0.0',
            'status': 'success',
            'structure': 'lazy-loading'
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
    logging.info("EXPORT TO JSON (LAZY LOADING STRUCTURE)")
    logging.info("="*60)
    
    # データ読み込み
    if not os.path.exists(TEMP_PRICE_JSON):
        logging.error(f"Price data not found: {TEMP_PRICE_JSON}")
        return False
    
    if not os.path.exists(TEMP_RS_INDIVIDUAL_JSON):
        logging.error(f"RS Individual data not found: {TEMP_RS_INDIVIDUAL_JSON}")
        return False
    
    if not os.path.exists(TEMP_RS_SECTOR_JSON):
        logging.error(f"RS Sector data not found: {TEMP_RS_SECTOR_JSON}")
        return False
    
    if not os.path.exists(TEMP_RS_INDUSTRY_JSON):
        logging.error(f"RS Industry data not found: {TEMP_RS_INDUSTRY_JSON}")
        return False
    
    with open(TEMP_PRICE_JSON, 'r') as f:
        price_data = json.load(f)
    
    with open(TEMP_RS_INDIVIDUAL_JSON, 'r') as f:
        rs_individual = json.load(f)
    
    with open(TEMP_RS_SECTOR_JSON, 'r') as f:
        rs_sector = json.load(f)
    
    with open(TEMP_RS_INDUSTRY_JSON, 'r') as f:
        rs_industry = json.load(f)
    
    logging.info(f"Loaded: {len(price_data['symbols'])} price records")
    logging.info(f"Loaded: {rs_individual['totalStocks']} Individual RS scores ({rs_individual['days']} days)")
    logging.info(f"Loaded: {rs_sector['totalSectors']} Sector RS scores ({rs_sector['days']} days)")
    logging.info(f"Loaded: {rs_industry['totalIndustries']} Industry RS scores ({rs_industry['days']} days)")
    
    # RS/RRSを日付ベースの辞書に変換
    rs_rrs_dict = create_rs_rrs_dict(rs_individual)
    
    # Core ファイル生成
    if not export_core_files(price_data, rs_rrs_dict):
        logging.error("Failed to export core files")
        return False
    
    # Indicator ファイル生成
    if not export_indicator_files(price_data):
        logging.error("Failed to export indicator files")
        return False
    
    # Score ファイル生成
    if not export_scores(rs_individual, rs_sector, rs_industry):
        logging.error("Failed to export score files")
        return False
    
    # メタデータ生成
    if not export_metadata(price_data, rs_individual):
        logging.error("Failed to export metadata")
        return False
    
    logging.info("="*60)
    logging.info("✅ All JSON files exported successfully!")
    logging.info("="*60)
    
    # サマリー
    total_files = len(price_data['symbols']) * 2 + 4  # core + indicators + 3 scores + metadata
    logging.info(f"Total files: {total_files}")
    logging.info(f"  - Core: {len(price_data['symbols'])}")
    logging.info(f"  - Indicators: {len(price_data['symbols'])}")
    logging.info(f"  - Scores: 3")
    logging.info(f"  - Metadata: 1")
    logging.info(f"Output directory: {R2_OUTPUT}")
    
    return True

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)

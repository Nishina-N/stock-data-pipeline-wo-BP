"""
4_export_to_json.py

temp_prices.json と temp_rs.json を R2アップロード形式に変換
- 個別銘柄JSON: stocks/daily/{symbol}.json
- RSスコアJSON: scores/individual/latest.json
"""
import json
import os
import logging
from datetime import datetime

DATA_FOLDER = "data"
TEMP_PRICE_JSON = os.path.join(DATA_FOLDER, "temp_prices.json")
TEMP_RS_JSON = os.path.join(DATA_FOLDER, "temp_rs.json")

# R2アップロード用ディレクトリ
R2_OUTPUT = os.path.join(DATA_FOLDER, "r2")
R2_STOCKS = os.path.join(R2_OUTPUT, "stocks", "daily")
R2_SCORES = os.path.join(R2_OUTPUT, "scores", "individual")
R2_METADATA = os.path.join(R2_OUTPUT, "metadata")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def export_individual_stocks(price_data, rs_scores_dict):
    """個別銘柄JSONを生成"""
    os.makedirs(R2_STOCKS, exist_ok=True)
    
    count = 0
    failed = []
    
    for symbol, info in price_data['symbols'].items():
        try:
            output = {
                'ticker': symbol,
                'name': info['name'],
                'sector': info['sector'],
                'industry': info['industry'],
                'data': info['data'],
                'rs': rs_scores_dict.get(symbol, 50),
                'rrs': rs_scores_dict.get(f"{symbol}_rrs", 0),
                'lastUpdated': price_data['lastUpdated']
            }
            
            output_path = os.path.join(R2_STOCKS, f"{symbol}.json")
            with open(output_path, 'w') as f:
                json.dump(output, f, indent=2)
            
            count += 1
            
        except Exception as e:
            logging.error(f"Failed to export {symbol}: {e}")
            failed.append(symbol)
    
    logging.info(f"✅ Exported {count} individual stock files to {R2_STOCKS}")
    if failed:
        logging.warning(f"⚠️  Failed to export {len(failed)} symbols: {failed[:10]}")
    
    return count > 0

def export_rs_scores(rs_data):
    """RSスコアJSONを生成"""
    os.makedirs(R2_SCORES, exist_ok=True)
    
    output_path = os.path.join(R2_SCORES, "latest.json")
    with open(output_path, 'w') as f:
        json.dump(rs_data, f, indent=2)
    
    logging.info(f"✅ Exported RS scores to {output_path}")
    logging.info(f"   Total stocks: {rs_data['totalStocks']}")
    logging.info(f"   Date: {rs_data['date']}")
    
    return True

def export_metadata(price_data, rs_data):
    """メタデータJSONを生成"""
    os.makedirs(R2_METADATA, exist_ok=True)
    
    metadata = {
        'lastUpdated': datetime.now().isoformat(),
        'priceDataDate': rs_data['date'],
        'totalSymbols': len(price_data['symbols']),
        'rsScoresCount': rs_data['totalStocks'],
        'dataRetentionDays': 1000,
        'pipeline': {
            'version': '1.0.0',
            'status': 'success'
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
    logging.info("EXPORT TO JSON (R2 FORMAT)")
    logging.info("="*60)
    
    # データ読み込み
    if not os.path.exists(TEMP_PRICE_JSON):
        logging.error(f"Price data not found: {TEMP_PRICE_JSON}")
        return False
    
    if not os.path.exists(TEMP_RS_JSON):
        logging.error(f"RS data not found: {TEMP_RS_JSON}")
        return False
    
    with open(TEMP_PRICE_JSON, 'r') as f:
        price_data = json.load(f)
    
    with open(TEMP_RS_JSON, 'r') as f:
        rs_data = json.load(f)
    
    logging.info(f"Loaded: {len(price_data['symbols'])} price records")
    logging.info(f"Loaded: {len(rs_data['scores'])} RS scores")
    
    # RS/RRS辞書作成
    rs_scores_dict = {}
    for score in rs_data['scores']:
        symbol = score['ticker']
        rs_scores_dict[symbol] = score['rs']
        rs_scores_dict[f"{symbol}_rrs"] = score['rrs']
    
    # 個別銘柄JSON生成
    if not export_individual_stocks(price_data, rs_scores_dict):
        logging.error("Failed to export individual stocks")
        return False
    
    # RSスコアJSON生成
    if not export_rs_scores(rs_data):
        logging.error("Failed to export RS scores")
        return False
    
    # メタデータJSON生成
    if not export_metadata(price_data, rs_data):
        logging.error("Failed to export metadata")
        return False
    
    logging.info("="*60)
    logging.info("✅ All JSON files exported successfully!")
    logging.info("="*60)
    
    # サマリー
    total_files = len(price_data['symbols']) + 2  # 個別銘柄 + latest.json + metadata
    logging.info(f"Total files: {total_files}")
    logging.info(f"Output directory: {R2_OUTPUT}")
    
    return True

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)

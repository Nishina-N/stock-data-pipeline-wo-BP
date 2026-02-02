"""
upload_fundamentals_to_r2.py

temp_fundamentals.json を年別構成でR2にアップロード
stocks/fundamentals/quarterly/{year}/{symbol}.json
"""
import boto3
import os
import logging
import json
from datetime import datetime
from dotenv import load_dotenv
from collections import defaultdict

load_dotenv()

DATA_FOLDER = "data"
TEMP_FUNDAMENTALS_JSON = os.path.join(DATA_FOLDER, "temp_fundamentals.json")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def split_fundamentals_by_year(fundamentals_dict):
    """
    Fundamentals データを年別に分割
    
    Args:
        fundamentals_dict: {symbol: {ticker, data: [{date, eps, ...}]}}
    
    Returns:
        dict: {symbol: {year: [{date, eps, ...}]}}
    """
    logging.info("Splitting fundamentals data by year...")
    
    symbol_year_data = {}
    
    for symbol, info in fundamentals_dict.items():
        year_groups = defaultdict(list)
        
        for quarter in info['data']:
            # date: "2024-Q1" or "2024-03-31"
            date_str = quarter['date']
            
            # 年を抽出
            if 'Q' in date_str:
                year = int(date_str.split('-')[0])  # "2024-Q1" -> 2024
            else:
                year = int(date_str[:4])  # "2024-03-31" -> 2024
            
            year_groups[year].append(quarter)
        
        symbol_year_data[symbol] = dict(year_groups)
    
    # 統計
    total_years = set()
    for years in symbol_year_data.values():
        total_years.update(years.keys())
    
    logging.info(f"Split data into years: {sorted(total_years)}")
    logging.info(f"Total symbols: {len(symbol_year_data)}")
    
    return symbol_year_data

def upload_fundamentals_to_r2():
    """Fundamental データを年別にR2アップロード"""
    
    required_env = ['R2_ENDPOINT', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET_NAME']
    missing = [env for env in required_env if not os.environ.get(env)]
    
    if missing:
        raise ValueError(f"Missing environment variables: {', '.join(missing)}")
    
    if not os.path.exists(TEMP_FUNDAMENTALS_JSON):
        raise FileNotFoundError(f"{TEMP_FUNDAMENTALS_JSON} does not exist")
    
    # データ読み込み
    with open(TEMP_FUNDAMENTALS_JSON, 'r') as f:
        fundamentals_dict = json.load(f)
    
    logging.info(f"Loaded {len(fundamentals_dict)} fundamental records")
    
    # 年別に分割
    symbol_year_data = split_fundamentals_by_year(fundamentals_dict)
    
    # S3クライアント作成
    s3 = boto3.client(
        's3',
        endpoint_url=os.environ['R2_ENDPOINT'],
        aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],
        region_name='auto'
    )
    
    bucket_name = os.environ['R2_BUCKET_NAME']
    
    # 各銘柄・各年ごとにアップロード
    uploaded_count = 0
    total_files = sum(len(years) for years in symbol_year_data.values())
    
    logging.info(f"\n{'='*60}")
    logging.info("UPLOADING FUNDAMENTALS TO R2")
    logging.info(f"{'='*60}")
    logging.info(f"Total files to upload: {total_files}")
    logging.info(f"{'='*60}\n")
    
    for symbol, year_data in symbol_year_data.items():
        for year, quarters in year_data.items():
            key = f"stocks/fundamentals/quarterly/{year}/{symbol}.json"
            
            # JSON構造
            output = {
                'ticker': symbol,
                'data': quarters,
                'lastUpdated': datetime.now().isoformat()
            }
            
            try:
                s3.put_object(
                    Bucket=bucket_name,
                    Key=key,
                    Body=json.dumps(output),
                    ContentType='application/json',
                    CacheControl='public, max-age=2592000'  # 30日キャッシュ
                )
                uploaded_count += 1
                
                if uploaded_count % 100 == 0:
                    logging.info(f"Progress: {uploaded_count}/{total_files}")
            
            except Exception as e:
                logging.error(f"Failed to upload {symbol}/{year}: {e}")
    
    logging.info(f"\n{'='*60}")
    logging.info("✅ FUNDAMENTALS UPLOADED TO R2")
    logging.info(f"{'='*60}")
    logging.info(f"Total: {uploaded_count}/{total_files}")
    logging.info(f"Structure: stocks/fundamentals/quarterly/{{year}}/{{symbol}}.json")
    logging.info(f"{'='*60}\n")
    
    return True

def main():
    try:
        return upload_fundamentals_to_r2()
    except Exception as e:
        logging.error(f"Upload failed: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)
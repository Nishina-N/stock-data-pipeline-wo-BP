"""
5_5_upload_bp_to_r2.py

BuyPressureデータをCloudflare R2にアップロード
入力:
  data/maintenance/r2/scores/BuyPressure/individual/{year}.json
  data/maintenance/r2/scores/BuyPressure/sector/{year}.json
  data/maintenance/r2/scores/BuyPressure/industry/{year}.json

出力:
  R2: scores/BuyPressure/individual/{year}.json
  R2: scores/BuyPressure/sector/{year}.json
  R2: scores/BuyPressure/industry/{year}.json
"""
import os
import boto3
import logging
from botocore.exceptions import ClientError
from dotenv import load_dotenv

# 環境変数読み込み
load_dotenv()

DATA_FOLDER = "data"
MAINTENANCE_FOLDER = os.path.join(DATA_FOLDER, "maintenance")
R2_FOLDER = os.path.join(MAINTENANCE_FOLDER, "r2")
LOCAL_BP_BASE = os.path.join(R2_FOLDER, "scores", "BuyPressure")

# R2設定
R2_ENDPOINT_URL = os.getenv('R2_ENDPOINT')
R2_ACCESS_KEY_ID = os.getenv('R2_ACCESS_KEY_ID')
R2_SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY')
R2_BUCKET_NAME = os.getenv('R2_BUCKET_NAME', 'stock-data')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_r2_client():
    """R2クライアントを取得"""
    if not all([R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY]):
        logging.error("Missing R2 credentials in .env file")
        return None
    
    s3_client = boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto"
    )
    
    return s3_client

def upload_directory_to_r2(s3_client, local_dir, r2_prefix):
    """ディレクトリ内の全ファイルをR2にアップロード"""
    if not os.path.exists(local_dir):
        logging.warning(f"Directory not found: {local_dir}")
        return 0
    
    upload_count = 0
    
    for filename in os.listdir(local_dir):
        if not filename.endswith('.json'):
            continue
        
        local_path = os.path.join(local_dir, filename)
        r2_key = f"{r2_prefix}/{filename}"
        
        try:
            s3_client.upload_file(
                local_path,
                R2_BUCKET_NAME,
                r2_key,
                ExtraArgs={'ContentType': 'application/json'}
            )
            logging.info(f"  ✅ Uploaded: {r2_key}")
            upload_count += 1
            
        except ClientError as e:
            logging.error(f"  ❌ Failed to upload {r2_key}: {e}")
    
    return upload_count

def main():
    logging.info("=" * 60)
    logging.info("Starting BuyPressure Upload to R2")
    logging.info("=" * 60)
    
    # R2クライアント取得
    s3_client = get_r2_client()
    if not s3_client:
        logging.error("Failed to create R2 client. Exiting.")
        return
    
    total_uploaded = 0
    
    # Individual BuyPressure
    logging.info("Uploading Individual BuyPressure...")
    local_individual = os.path.join(LOCAL_BP_BASE, "individual")
    count = upload_directory_to_r2(s3_client, local_individual, "scores/BuyPressure/individual")
    total_uploaded += count
    logging.info(f"Individual BP: {count} files uploaded")
    
    # Sector BuyPressure
    logging.info("Uploading Sector BuyPressure...")
    local_sector = os.path.join(LOCAL_BP_BASE, "sector")
    count = upload_directory_to_r2(s3_client, local_sector, "scores/BuyPressure/sector")
    total_uploaded += count
    logging.info(f"Sector BP: {count} files uploaded")
    
    # Industry BuyPressure
    logging.info("Uploading Industry BuyPressure...")
    local_industry = os.path.join(LOCAL_BP_BASE, "industry")
    count = upload_directory_to_r2(s3_client, local_industry, "scores/BuyPressure/industry")
    total_uploaded += count
    logging.info(f"Industry BP: {count} files uploaded")
    
    logging.info("=" * 60)
    logging.info(f"BuyPressure Upload Complete! Total: {total_uploaded} files")
    logging.info("=" * 60)

if __name__ == "__main__":
    main()

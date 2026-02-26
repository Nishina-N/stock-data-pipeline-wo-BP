"""
delete_scores_years.py

R2から特定年度のscoresファイルを削除
"""
import os
import boto3
import logging
from dotenv import load_dotenv

load_dotenv()

R2_ENDPOINT = os.getenv('R2_ENDPOINT')
R2_ACCESS_KEY_ID = os.getenv('R2_ACCESS_KEY_ID')
R2_SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY')
R2_BUCKET_NAME = os.getenv('R2_BUCKET_NAME')

# 削除対象年度
YEARS_TO_DELETE = [2022, 2023, 2024, 2025]

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_s3_client():
    return boto3.client(
        's3',
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name='auto'
    )

def delete_files_by_year(prefix, years):
    """指定年度のファイルを削除"""
    s3_client = create_s3_client()
    
    # R2のファイル一覧取得
    logging.info(f"Listing files under '{prefix}'...")
    keys_to_delete = []
    
    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=R2_BUCKET_NAME, Prefix=prefix)
        
        for page in pages:
            if 'Contents' in page:
                for obj in page['Contents']:
                    key = obj['Key']
                    # ファイル名から年度抽出（例: 2024.json）
                    filename = os.path.basename(key)
                    year_str = filename.replace('.json', '')
                    
                    try:
                        year = int(year_str)
                        if year in years:
                            keys_to_delete.append(key)
                    except ValueError:
                        # 年度でないファイル名はスキップ
                        pass
        
        logging.info(f"Found {len(keys_to_delete)} files to delete")
        
        # 削除実行
        if keys_to_delete:
            for key in keys_to_delete:
                logging.info(f"Deleting: {key}")
                s3_client.delete_object(Bucket=R2_BUCKET_NAME, Key=key)
            
            logging.info(f"✅ Deleted {len(keys_to_delete)} files")
        else:
            logging.info("No files to delete")
        
        return len(keys_to_delete)
        
    except Exception as e:
        logging.error(f"Error deleting files: {e}")
        return 0
    finally:
        s3_client.close()

def main():
    logging.info("="*60)
    logging.info(f"DELETE SCORES FILES FOR YEARS: {YEARS_TO_DELETE}")
    logging.info("="*60)
    
    if not all([R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME]):
        logging.error("R2 credentials not found in .env")
        return False
    
    # 確認プロンプト
    response = input(f"\n⚠️  This will DELETE all scores files for years {YEARS_TO_DELETE}.\nAre you sure? (yes/no): ")
    if response.lower() != 'yes':
        logging.info("Cancelled by user")
        return False
    
    total_deleted = 0
    
    # RS_scores (既存)
    logging.info("\n[1/9] Deleting RS_scores/individual...")
    total_deleted += delete_files_by_year("scores/RS_scores/individual", YEARS_TO_DELETE)
    
    logging.info("\n[2/9] Deleting RS_scores/sector...")
    total_deleted += delete_files_by_year("scores/RS_scores/sector", YEARS_TO_DELETE)
    
    logging.info("\n[3/9] Deleting RS_scores/industry...")
    total_deleted += delete_files_by_year("scores/RS_scores/industry", YEARS_TO_DELETE)
    
    # RRS_scores (既存)
    logging.info("\n[4/9] Deleting RRS_scores/individual...")
    total_deleted += delete_files_by_year("scores/RRS_scores/individual", YEARS_TO_DELETE)
    
    logging.info("\n[5/9] Deleting RRS_scores/sector...")
    total_deleted += delete_files_by_year("scores/RRS_scores/sector", YEARS_TO_DELETE)
    
    logging.info("\n[6/9] Deleting RRS_scores/industry...")
    total_deleted += delete_files_by_year("scores/RRS_scores/industry", YEARS_TO_DELETE)
    
    
    logging.info("="*60)
    logging.info(f"✅ Total deleted: {total_deleted} files")
    logging.info("="*60)
    
    return True

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)

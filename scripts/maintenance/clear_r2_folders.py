"""
clear_r2_folders.py

R2の特定フォルダ配下のオブジェクトを削除
"""
import boto3
import os
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def delete_folder_in_r2(s3_client, bucket_name, prefix):
    """
    R2の特定プレフィックス配下のオブジェクトを削除
    
    Args:
        s3_client: boto3 S3クライアント
        bucket_name: R2バケット名
        prefix: 削除対象のプレフィックス（例: "stocks/daily/core/2023/"）
    """
    logging.info(f"Listing objects under: {prefix}")
    
    # オブジェクトリストを取得
    objects_to_delete = []
    
    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=bucket_name, Prefix=prefix)
        
        for page in pages:
            if 'Contents' in page:
                for obj in page['Contents']:
                    objects_to_delete.append({'Key': obj['Key']})
        
        if len(objects_to_delete) == 0:
            logging.info(f"No objects found under {prefix}")
            return 0
        
        logging.info(f"Found {len(objects_to_delete)} objects to delete")
        
        # 1000件ずつバッチ削除
        deleted_count = 0
        batch_size = 1000
        
        for i in range(0, len(objects_to_delete), batch_size):
            batch = objects_to_delete[i:i+batch_size]
            
            response = s3_client.delete_objects(
                Bucket=bucket_name,
                Delete={'Objects': batch}
            )
            
            deleted = len(response.get('Deleted', []))
            deleted_count += deleted
            
            logging.info(f"Deleted {deleted_count}/{len(objects_to_delete)} objects")
        
        logging.info(f"✅ Successfully deleted {deleted_count} objects from {prefix}")
        return deleted_count
        
    except Exception as e:
        logging.error(f"Failed to delete objects under {prefix}: {e}")
        return 0

def main():
    """メイン処理"""
    # 環境変数確認
    required_env = ['R2_ENDPOINT', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET_NAME']
    missing = [env for env in required_env if not os.environ.get(env)]
    
    if missing:
        raise ValueError(f"Missing environment variables: {', '.join(missing)}")
    
    # S3クライアント作成
    s3 = boto3.client(
        's3',
        endpoint_url=os.environ['R2_ENDPOINT'],
        aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],
        region_name='auto'
    )
    
    bucket_name = os.environ['R2_BUCKET_NAME']
    
    # 削除対象フォルダ
    folders_to_clear = [
        "stocks/daily/core/1927/",
        "stocks/daily/core/1928/",
        "stocks/daily/core/1929/",
        "stocks/daily/core/1930/",
        "stocks/daily/indicators/standard/1927/",
        "stocks/daily/indicators/standard/1928/",
        "stocks/daily/indicators/standard/1929/",
        "stocks/daily/indicators/standard/1930/"
    ]
    
    logging.info("="*60)
    logging.info("CLEAR R2 FOLDERS")
    logging.info("="*60)
    logging.info(f"Bucket: {bucket_name}")
    logging.info(f"Folders to clear:")
    for folder in folders_to_clear:
        logging.info(f"  - {folder}")
    logging.info("="*60)
    
    # 確認プロンプト
    confirm = input("\nAre you sure you want to delete these folders? Type 'yes' to confirm: ")
    
    if confirm.lower() != 'yes':
        logging.info("Cancelled.")
        return False
    
    # 各フォルダを削除
    total_deleted = 0
    
    for folder in folders_to_clear:
        logging.info(f"\nProcessing: {folder}")
        deleted = delete_folder_in_r2(s3, bucket_name, folder)
        total_deleted += deleted
    
    logging.info(f"\n{'='*60}")
    logging.info("✅ CLEANUP COMPLETED")
    logging.info(f"{'='*60}")
    logging.info(f"Total objects deleted: {total_deleted}")
    logging.info(f"{'='*60}\n")
    
    return True

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)
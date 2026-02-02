"""
clear_r2.py

R2バケット内の全ファイルを削除（クリーンアップ用）
"""
import boto3
import os
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def clear_r2_bucket():
    """R2バケット内の全オブジェクトを削除"""
    
    # 環境変数確認
    required_env = ['R2_ENDPOINT', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET_NAME']
    missing = [env for env in required_env if not os.environ.get(env)]
    
    if missing:
        raise ValueError(f"Missing environment variables: {', '.join(missing)}")
    
    # S3互換クライアント作成
    s3 = boto3.client(
        's3',
        endpoint_url=os.environ['R2_ENDPOINT'],
        aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],
        region_name='auto'
    )
    
    bucket_name = os.environ['R2_BUCKET_NAME']
    
    logging.info(f"Listing all objects in bucket: {bucket_name}")
    
    # 全オブジェクトをリスト
    paginator = s3.get_paginator('list_objects_v2')
    pages = paginator.paginate(Bucket=bucket_name)
    
    delete_count = 0
    
    for page in pages:
        if 'Contents' not in page:
            continue
        
        # 削除対象のキーをリスト化
        objects_to_delete = [{'Key': obj['Key']} for obj in page['Contents']]
        
        if objects_to_delete:
            # バッチ削除
            response = s3.delete_objects(
                Bucket=bucket_name,
                Delete={'Objects': objects_to_delete}
            )
            
            deleted = len(response.get('Deleted', []))
            delete_count += deleted
            
            logging.info(f"Deleted {deleted} objects (total: {delete_count})")
    
    logging.info(f"\n{'='*60}")
    logging.info(f"✅ Cleared R2 bucket: {bucket_name}")
    logging.info(f"   Total deleted: {delete_count} objects")
    logging.info(f"{'='*60}\n")
    
    return True

def main():
    """メイン処理"""
    logging.info("="*60)
    logging.info("CLEAR R2 BUCKET")
    logging.info("="*60)
    logging.warning("⚠️  This will delete ALL files in the R2 bucket!")
    
    # 確認プロンプト
    response = input("Are you sure you want to continue? (yes/no): ")
    
    if response.lower() != 'yes':
        logging.info("Cancelled.")
        return False
    
    try:
        return clear_r2_bucket()
    except Exception as e:
        logging.error(f"Failed to clear R2: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)

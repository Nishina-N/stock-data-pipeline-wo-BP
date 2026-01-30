"""
5_upload_to_r2.py

data/r2/ 配下のJSONファイルをCloudflare R2にアップロード
"""
import boto3
import os
from pathlib import Path
import logging

DATA_FOLDER = "data"
R2_OUTPUT = os.path.join(DATA_FOLDER, "r2")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def upload_to_r2():
    """
    data/r2/ 配下の全JSONファイルをR2にアップロード
    """
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
    r2_dir = Path(R2_OUTPUT)
    
    if not r2_dir.exists():
        raise FileNotFoundError(f"{r2_dir} does not exist")
    
    uploaded_count = 0
    failed_count = 0
    failed_files = []
    
    # 全JSONファイルをアップロード
    json_files = list(r2_dir.glob('**/*.json'))
    total_files = len(json_files)
    
    logging.info(f"Found {total_files} JSON files to upload")
    
    for i, file_path in enumerate(json_files, 1):
        # R2のキー: stocks/daily/AAPL.json
        relative_path = file_path.relative_to(r2_dir)
        key = str(relative_path).replace('\\', '/')  # Windows対応
        
        try:
            if i % 100 == 0 or i == total_files:
                logging.info(f"Progress: {i}/{total_files} ({(i/total_files)*100:.1f}%)")
            
            with open(file_path, 'rb') as f:
                s3.put_object(
                    Bucket=bucket_name,
                    Key=key,
                    Body=f,
                    ContentType='application/json',
                    CacheControl='public, max-age=3600'
                )
            
            uploaded_count += 1
            
        except Exception as e:
            logging.error(f"Failed to upload {key}: {e}")
            failed_count += 1
            failed_files.append(key)
    
    # サマリー表示
    logging.info(f"\n{'='*60}")
    logging.info("UPLOAD SUMMARY")
    logging.info(f"{'='*60}")
    logging.info(f"✅ Uploaded: {uploaded_count}/{total_files} files")
    
    if failed_count > 0:
        logging.warning(f"❌ Failed: {failed_count} files")
        logging.warning(f"Failed files: {failed_files[:10]}")
        if len(failed_files) > 10:
            logging.warning(f"... and {len(failed_files) - 10} more")
    
    logging.info(f"Bucket: {bucket_name}")
    logging.info(f"Endpoint: {os.environ['R2_ENDPOINT']}")
    logging.info(f"{'='*60}\n")
    
    return failed_count == 0

def main():
    """R2アップロードメイン処理"""
    logging.info("="*60)
    logging.info("UPLOAD TO CLOUDFLARE R2")
    logging.info("="*60)
    
    try:
        success = upload_to_r2()
        
        if success:
            logging.info("✅ All files uploaded successfully!")
            return True
        else:
            logging.warning("⚠️  Upload completed with some failures")
            return False
            
    except Exception as e:
        logging.error(f"Upload failed: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)

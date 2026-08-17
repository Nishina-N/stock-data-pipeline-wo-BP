"""
upload_target_stocks_to_r2.py

target_stocks_latest.csv をCloudflare R2にアップロード
"""
import boto3
import os
import logging
from datetime import datetime

DATA_FOLDER = "data"
TARGET_STOCKS_CSV = os.path.join(DATA_FOLDER, "target_stocks_latest.csv")
R2_KEY = "metadata/target_stocks_latest.csv"

# 🔴 日付付きスナップショットを併せて保存する（2026-08-17 追加）。
#
# latest は上書き運用なので、過去のユニバースがどこにも残っていなかった。
# これは実害を出している:
#   - sector/industry RS はグループの構成銘柄＝このCSVに依存するため、
#     ヴィンテージを再現するには生成時のCSVが要る
#   - 銘柄の sector/industry は事業転換で実際に変わる（JP は J-Quants の
#     月次マスタ実測で18年に 1.3〜1.5%）。過去版が無いと、歴史日付に
#     現在の分類を当てている誤差を**測ることすらできない**
# US は過去分が失われているので遡れないが、ここから先は積み上げる。
SNAPSHOT_KEY = "metadata/snapshots/target_stocks_{stamp}.csv"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def upload_target_stocks_to_r2():
    """target_stocks_latest.csv をR2にアップロード"""

    # 環境変数確認
    required_env = ['R2_ENDPOINT', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET_NAME']
    missing = [env for env in required_env if not os.environ.get(env)]

    if missing:
        raise ValueError(f"Missing environment variables: {', '.join(missing)}")

    # ファイル存在確認
    if not os.path.exists(TARGET_STOCKS_CSV):
        raise FileNotFoundError(f"{TARGET_STOCKS_CSV} does not exist")

    endpoint = os.environ['R2_ENDPOINT']
    access_key = os.environ['R2_ACCESS_KEY_ID']
    secret_key = os.environ['R2_SECRET_ACCESS_KEY']
    bucket_name = os.environ['R2_BUCKET_NAME']

    logging.info(f"Uploading {TARGET_STOCKS_CSV} to R2...")
    logging.info(f"Bucket: {bucket_name}")
    logging.info(f"Key: {R2_KEY}")

    # Daily方式: クライアントをスコープ内で生成・finally でclose
    s3_client = None
    try:
        s3_client = boto3.client(
            's3',
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name='auto'
        )
        extra = {
            'ContentType': 'text/csv',
            'CacheControl': 'public, max-age=2592000',  # 30日キャッシュ
            'Metadata': {
                'uploaded_at': datetime.now().isoformat(),
                'source': 'monthly-fetch-stocks workflow'
            }
        }
        s3_client.upload_file(TARGET_STOCKS_CSV, bucket_name, R2_KEY,
                              ExtraArgs=extra)

        # スナップショットを先に消さず、同じ内容を日付キーで残す。
        # 同月に2回走っても同じキーを上書きするだけで増殖しない。
        snapshot_key = SNAPSHOT_KEY.format(
            stamp=datetime.now().strftime('%Y-%m-%d'))
        s3_client.upload_file(TARGET_STOCKS_CSV, bucket_name, snapshot_key,
                              ExtraArgs=extra)
        logging.info(f"Snapshot: {snapshot_key}")
    finally:
        if s3_client:
            s3_client.close()

    file_size_kb = os.path.getsize(TARGET_STOCKS_CSV) / 1024

    logging.info(f"\n{'='*60}")
    logging.info("✅ TARGET STOCKS UPLOADED TO R2")
    logging.info(f"{'='*60}")
    logging.info(f"File: {TARGET_STOCKS_CSV}")
    logging.info(f"Size: {file_size_kb:.2f} KB")
    logging.info(f"R2 Key: {R2_KEY}")
    logging.info(f"{'='*60}\n")

    return True


def main():
    """メイン処理"""
    try:
        return upload_target_stocks_to_r2()
    except Exception as e:
        logging.error(f"Upload failed: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)

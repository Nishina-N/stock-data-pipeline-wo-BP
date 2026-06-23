"""
r2.py

Cloudflare R2（S3互換）クライアント生成の共通関数。
"""
import os
import boto3

def create_s3_client():
    """環境変数から R2(S3互換) クライアントを生成する。

    必要な環境変数:
      R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY
    （バケット名 R2_BUCKET_NAME は呼び出し側で使用）
    """
    return boto3.client(
        's3',
        endpoint_url=os.environ['R2_ENDPOINT'],
        aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],
        region_name='auto'
    )

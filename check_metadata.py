import boto3
import os
from dotenv import load_dotenv

load_dotenv()

s3 = boto3.client(
    's3',
    endpoint_url=os.environ['R2_ENDPOINT'],
    aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
    aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],
    region_name='auto'
)

bucket = os.environ['R2_BUCKET_NAME']

print("Checking metadata directory...")
response = s3.list_objects_v2(Bucket=bucket, Prefix='metadata/')

if 'Contents' in response:
    for obj in response['Contents']:
        print(f"  {obj['Key']}")
        content = s3.get_object(Bucket=bucket, Key=obj['Key'])
        data = content['Body'].read().decode('utf-8')
        print(f"    Content preview: {data[:200]}")
        print()
else:
    print("  No files found in metadata/")

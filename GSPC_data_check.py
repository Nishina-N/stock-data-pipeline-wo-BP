import boto3
import os
import json
from dotenv import load_dotenv

load_dotenv()

s3 = boto3.client(
    's3',
    endpoint_url=os.environ['R2_ENDPOINT'],
    aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
    aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],
    region_name='auto'
)

response = s3.get_object(Bucket=os.environ['R2_BUCKET_NAME'], Key='stocks/daily/core/2026/^GSPC.json')
data = json.loads(response['Body'].read())

print(f"Total data points: {len(data['data'])}")
print("\n最新10日分:")
for item in data['data'][-10:]:
    print(f"  {item['date']}: Close={item['close']}")

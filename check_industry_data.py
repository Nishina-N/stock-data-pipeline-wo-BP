import boto3
import os
import json
import re
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

print("="*60)
print("CHECKING INDUSTRY RS DATA")
print("="*60)

# Industry RS データを取得
response = s3.get_object(Bucket=bucket, Key='scores/RS_scores/industry/2026.json')
data = json.loads(response['Body'].read().decode('utf-8'))

print(f"\nTotal records: {len(data)}")

# industry フィールドの型をチェック
print("\nChecking industry field types:")
type_counts = {}
invalid_industries = []

for i, item in enumerate(data):
    industry = item.get('industry')
    industry_type = type(industry).__name__
    
    if industry_type not in type_counts:
        type_counts[industry_type] = 0
    type_counts[industry_type] += 1
    
    # 文字列以外の場合
    if not isinstance(industry, str):
        invalid_industries.append({
            'index': i,
            'industry': industry,
            'type': industry_type,
            'full_record': item
        })

print(f"\nIndustry field types:")
for typ, count in type_counts.items():
    print(f"  {typ}: {count}")

if invalid_industries:
    print(f"\n⚠️ Found {len(invalid_industries)} records with non-string industry:")
    for item in invalid_industries[:10]:  # 最初の10件
        print(f"\n  Index: {item['index']}")
        print(f"  Industry: {item['industry']} (type: {item['type']})")
        print(f"  Full record: {json.dumps(item['full_record'], indent=4, ensure_ascii=False)}")
else:
    print(f"\n✅ All industry fields are strings")

# 日付検証
print("\n" + "="*60)
print("DATE VALIDATION")
print("="*60)

unique_dates = sorted(set(item['date'] for item in data))
print(f"Unique dates: {len(unique_dates)}")
print(f"First date: {unique_dates[0]}")
print(f"Last date: {unique_dates[-1]}")

# 不正な日付形式をチェック
date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')
invalid_dates = [item['date'] for item in data if not date_pattern.match(item['date'])]

if invalid_dates:
    print(f"\n⚠️ Invalid date formats found: {len(invalid_dates)}")
    for date in set(invalid_dates)[:10]:
        print(f"  {repr(date)}")
else:
    print(f"\n✅ All dates are in valid YYYY-MM-DD format")

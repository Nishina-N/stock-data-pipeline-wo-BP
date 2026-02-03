"""
check_r2_files.py

R2バケット内のファイル数をフォルダごとに集計
"""
import boto3
import os
from collections import defaultdict
from dotenv import load_dotenv

# .envファイルを読み込む
load_dotenv()

def count_files_in_r2():
    """R2バケット内のファイル数をフォルダごとにカウント"""
    
    # 環境変数確認
    required_env = ['R2_ENDPOINT', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET_NAME']
    missing = [env for env in required_env if not os.environ.get(env)]
    
    if missing:
        print(f"❌ Missing environment variables: {', '.join(missing)}")
        return False
    
    # S3クライアント作成
    s3 = boto3.client(
        's3',
        endpoint_url=os.environ['R2_ENDPOINT'],
        aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],
        region_name='auto'
    )
    
    bucket_name = os.environ['R2_BUCKET_NAME']
    
    print("="*80)
    print("R2 BUCKET FILE COUNT")
    print("="*80)
    print(f"Bucket: {bucket_name}")
    print(f"Endpoint: {os.environ['R2_ENDPOINT']}")
    print("="*80)
    print("\nScanning files...")
    
    # ファイル数をカウント
    folder_counts = defaultdict(int)
    year_counts = defaultdict(lambda: defaultdict(int))
    total_count = 0
    
    try:
        paginator = s3.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=bucket_name)
        
        for page in pages:
            if 'Contents' in page:
                for obj in page['Contents']:
                    key = obj['Key']
                    total_count += 1
                    
                    # フォルダパスを抽出
                    parts = key.split('/')
                    
                    if len(parts) >= 2:
                        # メインフォルダ (stocks, scores, metadata)
                        main_folder = parts[0]
                        folder_counts[main_folder] += 1
                        
                        # 詳細なパス分類
                        if main_folder == 'stocks':
                            # stocks/daily/core/{year}/
                            if len(parts) >= 4 and parts[1] == 'daily':
                                sub_type = parts[2]  # core or indicators
                                if len(parts) >= 5:
                                    year = parts[3]
                                    year_counts[f"stocks/daily/{sub_type}"][year] += 1
                        
                        elif main_folder == 'scores':
                            # scores/RS_scores/individual/{year}.json
                            if len(parts) >= 3:
                                score_type = parts[1]  # RS_scores or RRS_scores
                                category = parts[2]  # individual, sector, industry
                                year_counts[f"scores/{score_type}/{category}"]["files"] += 1
                        
                        elif main_folder == 'metadata':
                            year_counts["metadata"]["files"] += 1
    
    except Exception as e:
        print(f"❌ Error: {e}")
        return False
    
    finally:
        try:
            s3.close()
        except:
            pass
    
    # 結果表示
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"Total files: {total_count:,}")
    print()
    
    # メインフォルダごとの集計
    print("Main Folders:")
    print("-" * 80)
    for folder in sorted(folder_counts.keys()):
        print(f"  {folder:30s} {folder_counts[folder]:>10,} files")
    print()
    
    # 詳細集計
    print("Detailed Breakdown:")
    print("-" * 80)
    
    # stocks/daily/core by year
    if "stocks/daily/core" in year_counts:
        print("\n  stocks/daily/core/ (by year):")
        years = sorted(year_counts["stocks/daily/core"].keys())
        for year in years:
            count = year_counts["stocks/daily/core"][year]
            print(f"    {year}: {count:>6,} files")
        print(f"    {'Total':6s}  {sum(year_counts['stocks/daily/core'].values()):>6,} files")
    
    # stocks/daily/indicators by year
    if "stocks/daily/indicators/standard" in year_counts:
        print("\n  stocks/daily/indicators/standard/ (by year):")
        years = sorted(year_counts["stocks/daily/indicators/standard"].keys())
        for year in years:
            count = year_counts["stocks/daily/indicators/standard"][year]
            print(f"    {year}: {count:>6,} files")
        print(f"    {'Total':6s}  {sum(year_counts['stocks/daily/indicators/standard'].values()):>6,} files")
    
    # scores
    print("\n  scores/:")
    for score_path in sorted([k for k in year_counts.keys() if k.startswith("scores/")]):
        count = year_counts[score_path].get("files", 0)
        print(f"    {score_path:50s} {count:>6,} files")
    
    # metadata
    if "metadata" in year_counts:
        count = year_counts["metadata"].get("files", 0)
        print(f"\n  metadata/: {count:>6,} files")
    
    print("\n" + "="*80)
    
    return True

if __name__ == "__main__":
    import sys
    if count_files_in_r2():
        sys.exit(0)
    else:
        sys.exit(1)
"""
check_r2_files.py

R2 バケット内のオブジェクトをプレフィックス別に集計する（棚卸し・容量確認用）。

現行の格納モデル:
  - stocks/daily/core/{year}/{symbol}.json   … OHLCV + rs_percentile
  - scores/RS_scores/{individual,sector,industry}/{year}.json
  - stocks/intraday/...                        … 5分足
  - fundamentals/...                           … 月次ファンダ
  - metadata/...

※ 廃止済み（本来は存在しないはず）の系統も検出して警告表示する:
  - stocks/daily/indicators/   （indicators 廃止）
  - scores/RRS_scores/         （RRS 廃止）
  - stocks/summary/            （summary 廃止）
  - scores/BuyPressure/        （wo-BP 版では不要）

使い方:
  python scripts/maintenance/check_r2_files.py
"""
import os
import sys
import logging
from collections import defaultdict
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.r2 import create_s3_client

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 存在していたら警告するプレフィックス（掃除漏れ検出）
DEPRECATED_PREFIXES = [
    "stocks/daily/indicators/",
    "scores/RRS_scores/",
    "stocks/summary/",
    "scores/BuyPressure/",
]


def human_size(num_bytes):
    """バイト数を読みやすい単位に変換"""
    size = float(num_bytes)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024 or unit == 'TB':
            return f"{size:.2f} {unit}"
        size /= 1024


# 本リポジトリが管理する系統（詳細に3階層まで表示）
MANAGED_ROOTS = {'stocks', 'scores', 'metadata', 'fundamentals'}


def top_prefix(key):
    """集計キー: ファイル名を除いたディレクトリで束ねる。

    本リポジトリ管理系統は先頭3階層まで、それ以外（gex/iv_history/options等の
    別パイプライン）はトップ階層でロールアップする（シンボル単位の氾濫を防ぐ）。

    例:
      stocks/daily/core/2020/AAPL.json -> stocks/daily/core
      scores/RS_scores/individual/...  -> scores/RS_scores/individual
      iv_history/NXPI/2024.json        -> iv_history
      metadata/target_stocks.csv       -> metadata
    """
    parts = key.split('/')
    dirs = parts[:-1]  # 末尾のファイル名を除外
    if not dirs:
        return '(root)'
    if dirs[0] in MANAGED_ROOTS:
        return '/'.join(dirs[:3])
    return dirs[0]


def main():
    required_env = ['R2_ENDPOINT', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET_NAME']
    missing = [e for e in required_env if not os.environ.get(e)]
    if missing:
        logging.error(f"Missing environment variables: {', '.join(missing)}")
        return False

    s3 = create_s3_client()
    bucket = os.environ['R2_BUCKET_NAME']

    print("=" * 80)
    print("R2 BUCKET INVENTORY")
    print(f"Bucket: {bucket}")
    print("=" * 80)
    print("Scanning...")

    counts = defaultdict(int)
    sizes = defaultdict(int)
    deprecated_hits = defaultdict(int)
    total_count = 0
    total_size = 0

    paginator = s3.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get('Contents', []):
            key = obj['Key']
            size = obj.get('Size', 0)
            total_count += 1
            total_size += size

            grp = top_prefix(key)
            counts[grp] += 1
            sizes[grp] += size

            for dep in DEPRECATED_PREFIXES:
                if key.startswith(dep):
                    deprecated_hits[dep] += 1

    s3.close()

    print(f"\n{'='*80}")
    print("SUMMARY (by prefix)")
    print("=" * 80)
    print(f"{'prefix':45s} {'files':>10s} {'size':>14s}")
    print("-" * 80)
    for grp in sorted(sizes.keys(), key=lambda g: sizes[g], reverse=True):
        print(f"{grp:45s} {counts[grp]:>10,} {human_size(sizes[grp]):>14s}")
    print("-" * 80)
    print(f"{'TOTAL':45s} {total_count:>10,} {human_size(total_size):>14s}")

    if deprecated_hits:
        print(f"\n{'='*80}")
        print("⚠️  DEPRECATED PREFIXES STILL PRESENT (should be empty)")
        print("=" * 80)
        for dep, n in deprecated_hits.items():
            print(f"  {dep:40s} {n:>10,} objects")
        print("\n  → Run: python scripts/maintenance/cleanup_deprecated_r2.py --execute")
    else:
        print("\n✅ No deprecated prefixes found (clean).")

    print("=" * 80)
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

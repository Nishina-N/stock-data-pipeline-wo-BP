"""
diagnose_gap.py

core/{year}/{symbol}.json のレコード数・日付レンジを年別に集計し、
どの期間にどれだけ欠損があるかを可視化する診断スクリプト（読み取りのみ）。

使い方:
  python scripts/maintenance/diagnose_gap.py                 # サンプル銘柄で概況
  python scripts/maintenance/diagnose_gap.py AAPL MSFT NVDA  # 指定銘柄を詳細表示
"""
import os
import sys
import json
import logging
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.r2 import create_s3_client
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

CORE_PREFIX = "stocks/daily/core/"


def list_years(s3, bucket):
    """core 配下の年ディレクトリ一覧"""
    resp = s3.list_objects_v2(Bucket=bucket, Prefix=CORE_PREFIX, Delimiter='/')
    years = []
    for cp in resp.get('CommonPrefixes', []):
        p = cp['Prefix'].rstrip('/').split('/')[-1]
        if p.isdigit():
            years.append(int(p))
    return sorted(years)


def sample_symbols(s3, bucket, year, n=30):
    """指定年の core からファイル名（=シンボル）をサンプル取得"""
    resp = s3.list_objects_v2(Bucket=bucket, Prefix=f"{CORE_PREFIX}{year}/", MaxKeys=n)
    syms = []
    for obj in resp.get('Contents', []):
        name = obj['Key'].split('/')[-1]
        if name.endswith('.json'):
            syms.append(name[:-5])
    return syms


def analyze_symbol(s3, bucket, years, symbol):
    """1銘柄について、年別レコード数・日付レンジ・RS埋まり数を返す"""
    stats = {}
    for year in years:
        key = f"{CORE_PREFIX}{year}/{symbol}.json"
        try:
            obj = s3.get_object(Bucket=bucket, Key=key)
            data = json.loads(obj['Body'].read())
            rows = data.get('data', [])
            dates = [r['date'] for r in rows]
            rs_filled = sum(1 for r in rows if r.get('rs_percentile') is not None)
            vol_filled = sum(1 for r in rows if r.get('volume') is not None)
            stats[year] = {
                'records': len(rows),
                'first': min(dates) if dates else None,
                'last': max(dates) if dates else None,
                'rs_filled': rs_filled,
                'vol_filled': vol_filled,
            }
        except s3.exceptions.NoSuchKey:
            stats[year] = None
        except Exception as e:
            stats[year] = {'error': str(e)}
    return stats


# US 株の年間立会日数はおよそ 250〜252 日
EXPECTED_TRADING_DAYS = 251


def main():
    s3 = create_s3_client()
    bucket = os.environ['R2_BUCKET_NAME']

    years = list_years(s3, bucket)
    print("=" * 90)
    print(f"core years found: {years}")
    print("=" * 90)

    symbols = sys.argv[1:]
    if not symbols:
        # 各年からサンプルを取り、共通して存在しそうな銘柄を集める
        pool = set()
        for y in years:
            pool.update(sample_symbols(s3, bucket, y, n=40))
        symbols = sorted(pool)[:15]
        print(f"(no symbols given — sampling {len(symbols)}: {symbols})\n")

    # 年別・全銘柄集計
    agg = defaultdict(lambda: {'records': 0, 'rs_filled': 0, 'vol_filled': 0, 'n': 0})

    for sym in symbols:
        stats = analyze_symbol(s3, bucket, years, sym)
        print(f"\n### {sym}")
        print(f"{'year':>6} {'records':>8} {'expect':>7} {'rs_fill':>8} {'vol_fill':>9}  range")
        for y in years:
            st = stats[y]
            if st is None:
                print(f"{y:>6} {'(none)':>8}")
                continue
            if 'error' in st:
                print(f"{y:>6}  ERROR {st['error']}")
                continue
            flag = '  <-- LOW' if st['records'] < EXPECTED_TRADING_DAYS * 0.9 else ''
            print(f"{y:>6} {st['records']:>8} {EXPECTED_TRADING_DAYS:>7} "
                  f"{st['rs_filled']:>8} {st['vol_filled']:>9}  "
                  f"{st['first']}..{st['last']}{flag}")
            a = agg[y]
            a['records'] += st['records']
            a['rs_filled'] += st['rs_filled']
            a['vol_filled'] += st['vol_filled']
            a['n'] += 1

    print("\n" + "=" * 90)
    print("AGGREGATE (avg per symbol, by year)")
    print("=" * 90)
    print(f"{'year':>6} {'n':>4} {'avg_rec':>9} {'expect':>7} {'avg_rs':>8} {'avg_vol':>8}")
    for y in years:
        a = agg[y]
        if a['n'] == 0:
            continue
        print(f"{y:>6} {a['n']:>4} {a['records']/a['n']:>9.1f} {EXPECTED_TRADING_DAYS:>7} "
              f"{a['rs_filled']/a['n']:>8.1f} {a['vol_filled']/a['n']:>8.1f}")

    s3.close()
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

"""5_upload_jquants_r2.py

J-Quants 由来のデータを R2 の `jp/jquants/` 名前空間に載せる。

既存の JP パイプラインと同じ流儀:
  - **既定はドライラン**。実投入は `--execute`。
  - boto3 クライアントは**呼び出しごとに新規生成**する（再利用は過去に不具合を
    起こしているため。README の安全規約を参照）。
  - 部分失敗は成功として扱わない（1件でも失敗したら終了コード1）。

year-freeze は掛けていない。この取得は定期実行ではなく一回きりの履歴投入で、
上書き対象になる「過去年の既存ファイル」がそもそも存在しないため。
再投入時に既存を消したくない場合は `--skip-existing` を使う。

R2 レイアウト:
  jp/jquants/calendar.json                取引カレンダー（HolDiv 付き）
  jp/jquants/delisted_codes.json          master から導出した廃止銘柄一覧
  jp/jquants/master_monthly.parquet       月末営業日の上場銘柄一覧（積み上げ）
  jp/jquants/delisted_bars.parquet        廃止銘柄の日次4本値
  jp/jquants/fins_summary/{year}.parquet  財務情報（DiscDate=実発表日）
  jp/jquants/breakdown/{year}.parquet     売買内訳

使い方:
  python scripts/jp/jquants/5_upload_jquants_r2.py             # ドライラン
  python scripts/jp/jquants/5_upload_jquants_r2.py --execute
"""
import os
import sys
import glob
import argparse
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
from common.r2 import create_s3_client

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

DATA_ROOT = os.path.join('data', 'jquants')
PARQUET_ROOT = os.path.join(DATA_ROOT, '_parquet')
PREFIX = 'jp/jquants'


def collect():
    """(ローカルパス, R2キー) の一覧を作る。"""
    items = []
    for name in ('calendar.json', 'delisted_codes.json'):
        p = os.path.join(DATA_ROOT, name)
        if os.path.exists(p):
            items.append((p, f'{PREFIX}/{name}'))

    for p in sorted(glob.glob(os.path.join(PARQUET_ROOT, '**', '*.parquet'),
                              recursive=True)):
        rel = os.path.relpath(p, PARQUET_ROOT).replace(os.sep, '/')
        items.append((p, f'{PREFIX}/{rel}'))
    return items


def existing_keys(bucket):
    """R2 側の既存キー集合。

    listing の失敗を握りつぶすと「全部が新規」に見えて --skip-existing が
    無意味になるため、例外はそのまま呼び出し元へ投げる。
    """
    s3 = create_s3_client()
    keys = set()
    token = None
    while True:
        kw = {'Bucket': bucket, 'Prefix': PREFIX + '/'}
        if token:
            kw['ContinuationToken'] = token
        resp = s3.list_objects_v2(**kw)
        for o in resp.get('Contents', []):
            keys.add(o['Key'])
        if not resp.get('IsTruncated'):
            return keys
        token = resp['NextContinuationToken']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--execute', action='store_true', help='実際に投入する')
    ap.add_argument('--skip-existing', action='store_true',
                    help='R2 に既にあるキーは上書きしない')
    ap.add_argument('--only', default=None,
                    help='特定データセットのみ投入（カンマ区切り。再圧縮後の差し替え用）')
    args = ap.parse_args()

    bucket = os.environ.get('R2_BUCKET_NAME', 'stock-data')
    items = collect()
    if args.only:
        want = {n.strip() for n in args.only.split(',') if n.strip()}
        items = [(p, k) for p, k in items
                 if k.split('/')[2].split('.')[0] in want]
        logging.info(f'--only {sorted(want)} → {len(items)} ファイル')
    if not items:
        logging.error(f'投入対象がありません。先に 4_compact_to_parquet.py を実行してください')
        return False

    skip = set()
    if args.skip_existing:
        skip = existing_keys(bucket)
        logging.info(f'R2 既存キー {len(skip):,} 件')

    total_mb = 0.0
    plan = []
    for path, key in items:
        if key in skip:
            logging.info(f'  skip (既存)  {key}')
            continue
        mb = os.path.getsize(path) / 1024 / 1024
        total_mb += mb
        plan.append((path, key, mb))
        logging.info(f'  {"投入" if args.execute else "予定"}  {key}  {mb:.1f}MB')

    logging.info(f'{len(plan)} ファイル / {total_mb:.1f}MB')
    if not args.execute:
        logging.info('DRY-RUN でした。実投入は --execute を付けてください')
        return True

    ok = fail = 0
    for path, key, _ in plan:
        try:
            s3 = create_s3_client()      # 都度生成（再利用しない）
            s3.upload_file(path, bucket, key)
            ok += 1
        except Exception as e:
            logging.error(f'  ✗ {key}: {e}')
            fail += 1

    logging.info(f'✅ 成功{ok} / 失敗{fail}')
    return fail == 0


if __name__ == '__main__':
    sys.exit(0 if main() else 1)

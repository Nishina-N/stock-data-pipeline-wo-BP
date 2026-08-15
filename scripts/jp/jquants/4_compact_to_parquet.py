"""4_compact_to_parquet.py

取得した1日1ファイル / 1銘柄1ファイルの JSON を、年次 parquet にまとめる。

取得（3秒間隔で数時間）と変換を分離してあるので、変換のやり直しは何度でも安全にできる。
JSON のままにしないのは規模のため（breakdown は 1日約4,000行 × 11年で 1,000万行超）。
研究側は parquet を R2 から直接読む。

出力: data/jquants/_parquet/... （そのまま 5_upload_jquants_r2.py が R2 に載せる）

使い方:
  python scripts/jp/jquants/4_compact_to_parquet.py            # 全部
  python scripts/jp/jquants/4_compact_to_parquet.py --only breakdown
"""
import os
import sys
import json
import glob
import argparse
import logging

import pandas as pd

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

DATA_ROOT = os.path.join('data', 'jquants')
OUT_ROOT = os.path.join(DATA_ROOT, '_parquet')

BYDATE_DATASETS = ['fins_summary', 'breakdown']


def _write(df, rel_path):
    out = os.path.join(OUT_ROOT, rel_path)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    df.to_parquet(out, index=False)
    mb = os.path.getsize(out) / 1024 / 1024
    logging.info(f'  → {rel_path}  {len(df):,}行 × {len(df.columns)}列  {mb:.1f}MB')
    return len(df)


def compact_bydate(dataset):
    """{dataset}/{YYYY}/{YYYY-MM-DD}.json → _parquet/{dataset}/{YYYY}.parquet"""
    src = os.path.join(DATA_ROOT, dataset)
    if not os.path.isdir(src):
        logging.warning(f'{dataset}: 取得データがありません（スキップ）')
        return 0

    total = 0
    for year in sorted(os.listdir(src)):
        files = sorted(glob.glob(os.path.join(src, year, '*.json')))
        if not files:
            continue
        rows = []
        for fn in files:
            with open(fn, encoding='utf-8') as f:
                rows.extend(json.load(f))
        if not rows:
            logging.info(f'  {dataset}/{year}: 全日0件（parquet は作らない）')
            continue
        total += _write(pd.DataFrame(rows), os.path.join(dataset, f'{year}.parquet'))
    return total


def compact_master():
    """master/{YYYY-MM}.json → _parquet/master_monthly.parquet"""
    files = sorted(glob.glob(os.path.join(DATA_ROOT, 'master', '*.json')))
    if not files:
        logging.warning('master: 取得データがありません（スキップ）')
        return 0
    rows = []
    for fn in files:
        with open(fn, encoding='utf-8') as f:
            rows.extend(json.load(f))
    return _write(pd.DataFrame(rows), 'master_monthly.parquet')


def compact_delisted_bars():
    """delisted_bars/{code}.json → _parquet/delisted_bars.parquet"""
    files = sorted(glob.glob(os.path.join(DATA_ROOT, 'delisted_bars', '*.json')))
    if not files:
        logging.warning('delisted_bars: 取得データがありません（スキップ）')
        return 0
    rows = []
    for fn in files:
        with open(fn, encoding='utf-8') as f:
            r = json.load(f)
        if not r:
            continue
        # code 指定で引いているのでレスポンスに Code が無い場合の保険
        code = os.path.splitext(os.path.basename(fn))[0]
        for x in r:
            x.setdefault('Code', code)
        rows.extend(r)
    if not rows:
        logging.warning('delisted_bars: 全銘柄0件')
        return 0
    return _write(pd.DataFrame(rows), 'delisted_bars.parquet')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default=None,
                    help='master / delisted_bars / fins_summary / breakdown')
    args = ap.parse_args()

    jobs = {
        'master': compact_master,
        'delisted_bars': compact_delisted_bars,
    }
    for ds in BYDATE_DATASETS:
        jobs[ds] = (lambda d=ds: compact_bydate(d))

    targets = [args.only] if args.only else list(jobs)
    unknown = [t for t in targets if t not in jobs]
    if unknown:
        logging.error(f'未知のデータセット: {unknown}（選べるのは {list(jobs)}）')
        return False

    logging.info('=' * 60)
    logging.info('JSON → 年次 parquet 圧縮')
    logging.info('=' * 60)
    for t in targets:
        logging.info(f'{t}:')
        jobs[t]()
    return True


if __name__ == '__main__':
    sys.exit(0 if main() else 1)

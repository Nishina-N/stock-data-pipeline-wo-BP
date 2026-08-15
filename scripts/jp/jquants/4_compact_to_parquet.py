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

def discover_bydate_datasets():
    """日付単位で取得したデータセットを **ディレクトリ構造から自動検出** する。

    ここに名前を列挙すると 3_fetch_bydate_series.py の DATASETS との二重管理になり、
    片方に追加したときにもう片方が取りこぼす（実際に short_ratio で踏んだ）。
    `data/jquants/{dataset}/{YYYY}/` という形をしているものを拾う。
    """
    if not os.path.isdir(DATA_ROOT):
        return []
    out = []
    for name in sorted(os.listdir(DATA_ROOT)):
        d = os.path.join(DATA_ROOT, name)
        if name.startswith('_') or not os.path.isdir(d):
            continue
        # 年ディレクトリ（4桁）を持つものだけ
        if any(sub.isdigit() and len(sub) == 4 for sub in os.listdir(d)):
            out.append(name)
    return out


def discover_range_datasets():
    """range モードで取得したデータセット（年ディレクトリを持たず、
    直下に {start}_{end}.json を置くもの。investor_types）を検出する。"""
    if not os.path.isdir(DATA_ROOT):
        return []
    out = []
    for name in sorted(os.listdir(DATA_ROOT)):
        d = os.path.join(DATA_ROOT, name)
        if name.startswith('_') or not os.path.isdir(d):
            continue
        subs = os.listdir(d)
        if any(s.isdigit() and len(s) == 4 for s in subs):
            continue                      # by-date 側で拾う
        if any(s.endswith('.json') for s in subs):
            out.append(name)
    return out


def compact_range(dataset):
    """{dataset}/*.json → _parquet/{dataset}.parquet（年分割しない）"""
    files = sorted(glob.glob(os.path.join(DATA_ROOT, dataset, '*.json')))
    rows = []
    for fn in files:
        with open(fn, encoding='utf-8') as f:
            rows.extend(json.load(f))
    if not rows:
        logging.warning(f'{dataset}: 0件')
        return 0
    return _write(pd.DataFrame(rows), f'{dataset}.parquet')


def _flatten_nested(df):
    """dict / list を値に持つ列を JSON 文字列にする。

    /fins/details の `FS` は 125 要素の入れ子辞書で、キーが XBRL のラベル文字列。
    文書型ごとにキー集合が変わるため列に展開すると数千列のスパースになる。
    JSON 文字列で 1 列に保持すれば欠落なく parquet に載り、
    研究側は `json.loads` で必要な要素だけ取り出せる。
    """
    for col in df.columns:
        s = df[col]
        if s.dtype != object:
            continue
        sample = s.dropna()
        if sample.empty:
            continue
        if isinstance(sample.iloc[0], (dict, list)):
            df[col] = s.map(lambda v: json.dumps(v, ensure_ascii=False)
                            if isinstance(v, (dict, list)) else v)
            logging.info(f'    {col}: 入れ子 → JSON 文字列')
            continue

        # 数値と文字列が混在する列（/fins/dividend の DivRate は
        # 数値と '-'(該当なし) が混ざる）。pyarrow が変換に失敗するため文字列へ統一する。
        # '-' を null に潰すと「該当なし」と「欠測」の区別が消えるので潰さない。
        # 研究側は pd.to_numeric(errors='coerce') で数値化する
        types = set(sample.map(type))
        if len(types) > 1:
            df[col] = s.map(lambda v: v if v is None else str(v))
            logging.info(f'    {col}: 型混在 {sorted(t.__name__ for t in types)} → 文字列')
    return df


def _write(df, rel_path):
    df = _flatten_nested(df)
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
    for ds in discover_bydate_datasets():
        jobs[ds] = (lambda d=ds: compact_bydate(d))
    for ds in discover_range_datasets():
        jobs[ds] = (lambda d=ds: compact_range(d))

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

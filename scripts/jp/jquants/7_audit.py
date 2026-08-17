"""7_audit.py

取得済みデータの完全性を機械的に検証する。

「たぶん取り切った」を潰すための監査。今回の取得で実際に踏んだ抜けを
全て検出できる項目を並べてある:

  A. 日付被覆   … 営業日に対して取得漏れの日が無いか
                  （取得スクリプトは例外で止まるが、途中終了に気づかない可能性がある）
  B. 行数保存   … JSON のレコード数と parquet の行数が一致するか
                  （圧縮でこぼしていないか）
  C. 列の一致   … parquet の列が API の返す列を全て含むか
                  🔴 /equities/bars/daily の bulk が Adj* 15列を落としていたのを
                     行数一致で見逃した実績があるため、列は必ず突き合わせる
  D. R2 との一致 … ローカル parquet と R2 のキー・サイズが一致するか
  E. 値の一致   … 同じ日を API でも引いて全セルを突き合わせる
                  🔴 列も件数も合っていて値だけ壊れる経路がある。実際、bulk CSV の
                     数値化でゼロ埋めコードの先頭0を落としていた
                     （earnings_date.FYE '0120'→120、EmMrgnTrgDiv '002'→2）

使い方:
  python scripts/jp/jquants/7_audit.py              # 全項目
  python scripts/jp/jquants/7_audit.py --skip-rows  # B を省略（重い）
"""
import os
import sys
import json
import glob
import argparse
import logging

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from _jq_client import Client, JQuantsError
from _jq_bydate import load_business_days
import importlib.util

_spec = importlib.util.spec_from_file_location(
    '_ds', os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        '3_fetch_bydate_series.py'))
_ds = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ds)
DATASETS = _ds.DATASETS

logging.basicConfig(level=logging.INFO, format='%(message)s')

DATA_ROOT = os.path.join('data', 'jquants')
PARQUET_ROOT = os.path.join(DATA_ROOT, '_parquet')
PREFIX = 'jp/jquants'

# 列比較に使う「その日ならデータがあるはず」の日付とパラメータ名
COLUMN_PROBE = {
    'bars_daily':        ('/equities/bars/daily',        {'date': '2017-11-29'}),
    'fins_summary':      ('/fins/summary',               {'date': '2017-11-14'}),
    'fins_details':      ('/fins/details',               {'date': '2017-11-14'}),
    'dividend':          ('/fins/dividend',              {'date': '2017-11-14'}),
    'breakdown':         ('/markets/breakdown',          {'date': '2017-11-29'}),
    'short_ratio':       ('/markets/short-ratio',        {'date': '2017-11-29'}),
    'margin_interest':   ('/markets/margin-interest',    {'date': '2017-11-24'}),
    'margin_alert':      ('/markets/margin-alert',       {'date': '2017-11-29'}),
    'investor_types':    ('/equities/investor-types',    {'from': '2017-11-01',
                                                          'to': '2017-11-30'}),
    'edinet_major':      ('/edinet/major-shareholders',  {'date': '2025-06-27'}),
    'edinet_cross':      ('/edinet/cross-shareholdings', {'date': '2025-06-27'}),
    'edinet_large':      ('/edinet/large-volume-shareholders', {'date': '2025-06-27'}),
    'options225':        ('/derivatives/bars/daily/options/225', {'date': '2017-11-29'}),
    'futures':           ('/derivatives/bars/daily/futures', {'date': '2017-11-29'}),
    'indices':           ('/indices/bars/daily',         {'date': '2017-11-29'}),
    'short_sale_report': ('/markets/short-sale-report',  {'disc_date': '2020-08-05'}),
    'earnings_date':     ('/fins/earnings-date',         {'date': '2021-01-06'}),
    'master_monthly':    ('/equities/master',            {'date': '2017-11-30'}),
    'delisted_bars':     ('/equities/bars/daily',        {'code': '13010'}),
}

problems = []


def fail(msg):
    problems.append(msg)
    logging.error(f'  ✗ {msg}')


def audit_day_coverage():
    """A. 日付単位で取った系統に取得漏れの日が無いか。"""
    logging.info('\n=== A. 日付被覆 ===')
    for ds, (path, date_param, start, mode) in sorted(DATASETS.items()):
        if mode == 'range':
            continue
        src = os.path.join(DATA_ROOT, ds)
        if not os.path.isdir(src):
            fail(f'{ds}: ディレクトリが無い')
            continue

        have = {os.path.basename(f)[:-5]
                for f in glob.glob(os.path.join(src, '*', '*.json'))}
        if not have:
            fail(f'{ds}: ファイルが無い')
            continue

        # 実際に取れた範囲だけを対象にする（開始年より前は元々データが無い）
        lo, hi = min(have), max(have)
        expect = set(load_business_days(lo, hi))
        if mode == 'friday':
            from datetime import datetime
            expect = {d for d in expect
                      if datetime.strptime(d, '%Y-%m-%d').weekday() == 4}

        missing = sorted(expect - have)
        extra = sorted(have - expect)
        if missing:
            fail(f'{ds}: 取得漏れ {len(missing)}日  例 {missing[:5]}')
        elif extra:
            fail(f'{ds}: 営業日でない日が {len(extra)}件  例 {extra[:5]}')
        else:
            logging.info(f'  ✓ {ds:18} {len(have):>5}日  {lo}..{hi}  漏れなし')


def audit_row_conservation():
    """B. JSON のレコード数と parquet の行数が一致するか。"""
    logging.info('\n=== B. 行数保存（JSON → parquet）===')
    for ds in sorted(DATASETS):
        src = os.path.join(DATA_ROOT, ds)
        if not os.path.isdir(src):
            continue
        files = glob.glob(os.path.join(src, '*', '*.json')) or \
            glob.glob(os.path.join(src, '*.json'))
        if not files:
            continue

        n_json = 0
        for f in files:
            with open(f, encoding='utf-8') as fh:
                n_json += len(json.load(fh))

        pq = glob.glob(os.path.join(PARQUET_ROOT, ds, '*.parquet')) or \
            glob.glob(os.path.join(PARQUET_ROOT, f'{ds}.parquet'))
        if not pq:
            fail(f'{ds}: parquet が無い（JSON {n_json:,}件）')
            continue
        # 🔴 pd.read_parquet(columns=[]) は 0 行を返す。
        #    行数はフッタのメタデータから取る（全読みも不要で速い）
        import pyarrow.parquet as pyq
        n_pq = sum(pyq.ParquetFile(p).metadata.num_rows for p in pq)

        if n_json != n_pq:
            fail(f'{ds}: JSON {n_json:,}件 ≠ parquet {n_pq:,}行')
        else:
            logging.info(f'  ✓ {ds:18} {n_pq:>12,} 行  一致')


def audit_columns(client):
    """C. parquet の列が API の返す列を全て含むか。"""
    logging.info('\n=== C. 列の一致（parquet vs API）===')
    for ds, (path, params) in sorted(COLUMN_PROBE.items()):
        pq = sorted(glob.glob(os.path.join(PARQUET_ROOT, ds, '*.parquet'))) or \
            glob.glob(os.path.join(PARQUET_ROOT, f'{ds}.parquet'))
        if not pq:
            fail(f'{ds}: parquet が無い')
            continue
        import pyarrow.parquet as pyq
        cols = set(pyq.ParquetFile(pq[len(pq) // 2]).schema.names)

        try:
            rows = client.get(path, params)
        except JQuantsError as e:
            fail(f'{ds}: API 照会に失敗 {e}')
            continue
        if not rows:
            fail(f'{ds}: API が 0 件（プローブ日を見直すこと）')
            continue

        api_cols = set(rows[0])
        missing = sorted(api_cols - cols)
        if missing:
            fail(f'{ds}: 列の欠落 {len(missing)}  {missing}')
        else:
            logging.info(f'  ✓ {ds:18} {len(api_cols):>3}列  欠落なし')


def audit_values(client):
    """E. 同じ日を API でも引いて全セルを突き合わせる。

    入れ子(dict/list)は保存時に JSON 文字列化しているため、比較前に
    こちらも json.dumps して揃える（表現差を不一致と誤判定しないため）。
    """
    logging.info('\n=== E. 値の一致（parquet vs API）===')
    for ds, (path, params) in sorted(COLUMN_PROBE.items()):
        if ds in ('master_monthly', 'delisted_bars'):
            continue                      # 日付で絞れないので対象外
        pq = sorted(glob.glob(os.path.join(PARQUET_ROOT, ds, '*.parquet'))) or             glob.glob(os.path.join(PARQUET_ROOT, f'{ds}.parquet'))
        if not pq:
            continue
        day = params.get('date') or params.get('disc_date')
        if not day:
            continue
        try:
            rows = client.get(path, params)
        except JQuantsError:
            continue
        if not rows:
            continue
        api = pd.DataFrame(rows)

        # 日付列を特定（Date / DiscDate / PubDate / SubDate …）
        cand = [c for c in api.columns
                if c.endswith('Date') and api[c].astype(str).eq(day).any()]
        if not cand:
            fail(f'{ds}: 日付列を特定できない {list(api.columns)[:8]}')
            continue
        dc = cand[0]

        # 年次分割されていればその年のファイルだけ読む
        same_year = [f for f in pq if f'{day[:4]}.parquet' in f.replace(os.sep, '/')]
        df = pd.concat([pd.read_parquet(f) for f in (same_year or pq)],
                       ignore_index=True)
        df = df[df[dc].astype(str) == day]

        cols = [c for c in api.columns if c in df.columns]
        a = api[cols].map(_norm)
        b = df[cols].map(_norm)
        a = a.sort_values(cols).reset_index(drop=True)
        b = b.sort_values(cols).reset_index(drop=True)
        if len(a) != len(b):
            fail(f'{ds}: {day} の行数 API {len(a)} ≠ parquet {len(b)}')
        elif not a.equals(b):
            bad = [c for c in cols if not a[c].equals(b[c])]
            fail(f'{ds}: {day} の値が不一致 列={bad}')
        else:
            logging.info(f'  ✓ {ds:18} {day} {len(b):>6}行 × {len(cols)}列  全セル一致')


def _norm(v):
    """比較用に表現差を吸収する。**値の欠落は吸収しない。**

    吸収するのは以下の3つだけ:
      1. 入れ子(dict/list) … 保存時に JSON 文字列化しているため揃える
      2. 空の表現         … API は欠損を空文字 '' で返すが、bulk CSV 経由では
                            NaN になる（例: futures の MO/SQD＝前場なし・SQ未設定）
      3. 数値の型         … null を含む列は pandas が int64→float64 に昇格するため
                            30503310 と 30503310.0 が別物に見える
    """
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    if v is None or (isinstance(v, float) and v != v):
        return ''
    s = str(v).strip()
    if s in ('', 'None', 'nan', 'NaT'):
        return ''
    # 末尾 .0 の float 表現を整数に寄せる（先頭ゼロのコードは float にならない）
    if s.endswith('.0') and s[:-2].lstrip('-').isdigit():
        return s[:-2]
    return s


def audit_r2():
    """D. ローカル parquet と R2 のキー・サイズが一致するか。"""
    logging.info('\n=== D. R2 との一致 ===')
    from common.r2 import create_s3_client
    bucket = os.environ.get('R2_BUCKET_NAME', 'stock-data')

    remote = {}
    token = None
    while True:
        kw = {'Bucket': bucket, 'Prefix': PREFIX + '/'}
        if token:
            kw['ContinuationToken'] = token
        resp = create_s3_client().list_objects_v2(**kw)
        for o in resp.get('Contents', []):
            remote[o['Key']] = o['Size']
        if not resp.get('IsTruncated'):
            break
        token = resp['NextContinuationToken']

    local = {}
    for p in glob.glob(os.path.join(PARQUET_ROOT, '**', '*.parquet'), recursive=True):
        rel = os.path.relpath(p, PARQUET_ROOT).replace(os.sep, '/')
        local[f'{PREFIX}/{rel}'] = os.path.getsize(p)
    for name in ('calendar.json', 'delisted_codes.json'):
        p = os.path.join(DATA_ROOT, name)
        if os.path.exists(p):
            local[f'{PREFIX}/{name}'] = os.path.getsize(p)

    only_local = sorted(set(local) - set(remote))
    only_remote = sorted(set(remote) - set(local))
    size_diff = [k for k in set(local) & set(remote) if local[k] != remote[k]]

    if only_local:
        fail(f'R2 に無いキー {len(only_local)}: {only_local[:5]}')
    if only_remote:
        fail(f'ローカルに無いキー {len(only_remote)}: {only_remote[:5]}')
    if size_diff:
        fail(f'サイズ不一致 {len(size_diff)}: {size_diff[:5]}')
    if not (only_local or only_remote or size_diff):
        logging.info(f'  ✓ {len(remote)} オブジェクト  キー・サイズとも一致')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--skip-rows', action='store_true', help='B を省略（重い）')
    args = ap.parse_args()

    logging.info('=' * 60)
    logging.info('J-QUANTS 取得データ 完全性監査')
    logging.info('=' * 60)

    audit_day_coverage()
    if not args.skip_rows:
        audit_row_conservation()
    client = Client(min_interval=1.0)
    audit_columns(client)
    audit_values(client)
    audit_r2()

    logging.info('\n' + '=' * 60)
    if problems:
        logging.error(f'🛑 問題 {len(problems)} 件')
        for p in problems:
            logging.error(f'  - {p}')
        return False
    logging.info('✅ 全項目パス')
    return True


if __name__ == '__main__':
    sys.exit(0 if main() else 1)

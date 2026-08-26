"""9_fetch_addon_bulk.py

分足・ティック（アドオン）を bulk 経由で取得し、parquet 化する。

🔴 1〜7 と別スクリプトにしてある理由:
  - 規模が2桁違う（ティックは gz で 20.5GB / 展開 100GB 級）。
    6_fetch_bulk.py の download() は本文を丸ごとメモリに載せて
    gzip.decompress するので 1GB の月次ファイルでは持たない。ここは
    ダウンロードも変換もストリーミングで行う。
  - 4_compact_to_parquet.py の compact_bulk() は年次で pd.concat するため、
    ティックでは年に数十GBを1枚に積むことになり成立しない。
  - 出力の粒度が系統ごとに違う（分足=月次 / ティック=日次）。

契約とデータ期間（2026-08-26 実測・Light + 分足/ティックアドオン）:
  - 窓は **2024-08-26 以降のローリング2年**。それより前は 400 が返る
    （"Your subscription covers the following dates: 2024-08-26 ~ ."）。
    🔴 窓は前へ動く。**取らずに放置した古い月は二度と取れない**。
  - `/equities/trades` は API パスが存在しない（403 "endpoint does not exist"）。
    ティックは **bulk のみ**。分足は API も bulk も可。
  - bulk のキーは月次 `.../historical/{YYYY}/..._{YYYYMM}.csv.gz` と
    当月ぶんの日次 `.../live/..._{YYYYMMDD}.csv.gz` の2階層。

レート: アドオンはプラン上限とは独立に 60 req/分（_jq_rates.py 参照）。
ここが投げるのは list/get だけで、実データは署名付き URL（認証不要）から落ちる。

出力:
  data/jquants/_bulk/{bars_minute,trades}/*.csv.gz        ダウンロード原本（キャッシュ）
  data/jquants/_parquet/bars_minute/{YYYYMM}.parquet      分足（月次）
  data/jquants/_parquet/trades/{YYYY}/{YYYYMMDD}.parquet  ティック（日次）
  → そのまま 5_upload_jquants_r2.py が jp/jquants/ 配下に載せる

使い方:
  python scripts/jp/jquants/9_fetch_addon_bulk.py --dataset bars_minute --list
  python scripts/jp/jquants/9_fetch_addon_bulk.py --dataset bars_minute --verify
  python scripts/jp/jquants/9_fetch_addon_bulk.py --dataset trades
  python scripts/jp/jquants/9_fetch_addon_bulk.py --all
"""
import os
import re
import sys
import gzip
import shutil
import time
import argparse
import logging

import requests
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _jq_client import Client, JQuantsError

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

DATA_ROOT = os.path.join('data', 'jquants')
BULK_ROOT = os.path.join(DATA_ROOT, '_bulk')
PARQUET_ROOT = os.path.join(DATA_ROOT, '_parquet')

CHUNK_ROWS = 1_000_000

# 🔴 全列を文字列で読む。bulk CSV の数値化はゼロ埋めの先頭0を落とす実績があり
#    （FYE '0120' → 120）、ここでも SessionDistinction '01'、
#    TransactionId '000000000008'、Code '13010' が同じ罠を踏む。
#    数値として持つ列だけ numeric で明示的に戻す。
DATASETS = {
    'bars_minute': {
        'endpoint': '/equities/bars/minute',
        'grain': 'month',
        'numeric': ['O', 'H', 'L', 'C', 'Vo', 'Va'],
    },
    'trades': {
        'endpoint': '/equities/trades',
        'grain': 'day',
        'numeric': ['Price', 'TradingVolume'],
    },
}

STEM_DATE = re.compile(r'_(\d{6,8})\.csv\.gz$')


def stem_key(name):
    """ファイル名末尾の YYYYMM / YYYYMMDD を返す。"""
    m = STEM_DATE.search(name)
    if not m:
        raise ValueError(f'日付を読み取れないファイル名: {name}')
    return m.group(1)


def list_files(client, endpoint):
    return client.get('/bulk/list', {'endpoint': endpoint})


DOWNLOAD_RETRIES = 5


def download(client, key, out_path):
    """署名付き URL を取得してストリーミングで落とす。

    .part に書いてから rename する。途中で切れたファイルを「取得済み」として
    キャッシュすると、次回スキップされて静かに欠測が残るため。

    🔴 ここは自前でリトライする。_jq_client の再試行は API 呼び出しにしか
       効かず、実体を落とす署名付き URL は素の requests で叩いている。
       ティックは1本 1GB・全体で20GBを数十分かけて流すので、
       RemoteDisconnected は「起きるかもしれない」ではなく起きる
       （実際に 202602 の途中で落ちてジョブごと死んだ）。
       毎回 URL を取り直す（署名の有効期限が切れている可能性があるため）。
    """
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    tmp = out_path + '.part'
    last = None

    for attempt in range(DOWNLOAD_RETRIES):
        body = client._get_once('/bulk/get', {'key': key})
        url = body.get('url')
        if not url:
            raise JQuantsError(f'bulk/get が url を返しませんでした: {key}')
        try:
            with requests.get(url, stream=True, timeout=600) as r:
                r.raise_for_status()
                r.raw.decode_content = False
                with open(tmp, 'wb') as f:
                    shutil.copyfileobj(r.raw, f, length=1 << 20)

            # gzip として最後まで読めるか確認（切れたダウンロードを検出する）
            size = 0
            with gzip.open(tmp, 'rb') as f:
                while True:
                    b = f.read(1 << 22)
                    if not b:
                        break
                    size += len(b)
        except (requests.RequestException, OSError, EOFError) as e:
            last = f'{type(e).__name__}: {e}'
            if os.path.exists(tmp):
                os.remove(tmp)          # 中途半端な .part を残さない
            wait = min(120, 10 * (2 ** attempt))
            logging.warning(f'  再試行 {attempt + 1}/{DOWNLOAD_RETRIES} '
                            f'{os.path.basename(key)} ({last}) -> {wait}s 待機')
            time.sleep(wait)
            continue

        os.replace(tmp, out_path)
        return os.path.getsize(out_path), size

    raise JQuantsError(f'{key} のダウンロードに失敗しました: {last}')


class DayWriter:
    """日付 -> ParquetWriter。月次 CSV を日次 parquet に切り分ける。

    月内の日数ぶん（〜23）しかハンドルを開かないので保持して問題ない。
    """

    def __init__(self, root, schema):
        self.root = root
        self.schema = schema
        self.writers = {}
        self.rows = {}

    def path_for(self, day):
        d = day.replace('-', '')
        return os.path.join(self.root, d[:4], f'{d}.parquet')

    def write(self, day, table):
        w = self.writers.get(day)
        if w is None:
            path = self.path_for(day)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            w = pq.ParquetWriter(path + '.part', self.schema, compression='zstd')
            self.writers[day] = w
            self.rows[day] = 0
        w.write_table(table)
        self.rows[day] += table.num_rows

    def close(self):
        for day, w in self.writers.items():
            w.close()
            path = self.path_for(day)
            os.replace(path + '.part', path)
        return dict(self.rows)


def build_table(df, numeric, schema=None):
    for c in numeric:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    t = pa.Table.from_pandas(df, preserve_index=False)
    if schema is not None:
        t = t.cast(schema)
    return t


def infer_schema(path, numeric):
    head = pd.read_csv(path, compression='gzip', dtype=str, nrows=1000)
    return build_table(head, numeric).schema


def convert_month(dataset, files, out_month, schema):
    """分足: 月に属する csv.gz 群 → 1枚の月次 parquet。"""
    cfg = DATASETS[dataset]
    os.makedirs(os.path.dirname(out_month), exist_ok=True)
    tmp = out_month + '.part'
    n = 0
    w = pq.ParquetWriter(tmp, schema, compression='zstd')
    try:
        for fn in files:
            for chunk in pd.read_csv(fn, compression='gzip', dtype=str,
                                     chunksize=CHUNK_ROWS):
                t = build_table(chunk, cfg['numeric'], schema)
                w.write_table(t)
                n += t.num_rows
    finally:
        w.close()
    os.replace(tmp, out_month)
    return n


def convert_days(dataset, fn, out_root, schema):
    """ティック: 1本の csv.gz（月次 or 日次）→ 日ごとの parquet。"""
    cfg = DATASETS[dataset]
    dw = DayWriter(out_root, schema)
    try:
        for chunk in pd.read_csv(fn, compression='gzip', dtype=str,
                                 chunksize=CHUNK_ROWS):
            for day, part in chunk.groupby('Date', sort=True):
                dw.write(day, build_table(part.copy(), cfg['numeric'], schema))
    finally:
        rows = dw.close()
    return rows


def convert(dataset):
    cfg = DATASETS[dataset]
    src = os.path.join(BULK_ROOT, dataset)
    files = sorted(f for f in os.listdir(src)
                   if f.endswith('.csv.gz')) if os.path.isdir(src) else []
    if not files:
        logging.warning(f'{dataset}: bulk データがありません（スキップ）')
        return 0

    schema = infer_schema(os.path.join(src, files[0]), cfg['numeric'])
    out_root = os.path.join(PARQUET_ROOT, dataset)
    total = 0

    if cfg['grain'] == 'month':
        by_month = {}
        for f in files:
            by_month.setdefault(stem_key(f)[:6], []).append(os.path.join(src, f))
        for ym in sorted(by_month):
            out = os.path.join(out_root, f'{ym}.parquet')
            if os.path.exists(out):
                continue
            n = convert_month(dataset, sorted(by_month[ym]), out, schema)
            total += n
            logging.info(f'  {dataset} {ym}: {n:,}行 '
                         f'{os.path.getsize(out) / 1e6:.0f}MB')
    else:
        for f in files:
            key = stem_key(f)
            if len(key) == 8:
                # 日次ファイルは出力先が確定するので、あれば飛ばせる
                if os.path.exists(os.path.join(out_root, key[:4], f'{key}.parquet')):
                    continue
                done = None
            else:
                # 月次ファイルは中身を見るまで日が分からない。月内の1日でも
                # 未変換なら丸ごとやり直す（.part を使うので中断は残らない）
                done = os.path.join(out_root, '_done', f'{key}.ok')
                if os.path.exists(done):
                    continue
            rows = convert_days(dataset, os.path.join(src, f), out_root, schema)
            total += sum(rows.values())
            logging.info(f'  {dataset} {key}: {len(rows)}日 / '
                         f'{sum(rows.values()):,}行')
            if done:
                os.makedirs(os.path.dirname(done), exist_ok=True)
                open(done, 'w').close()

    logging.info(f'✅ {dataset}: 変換 {total:,}行')
    return total


def verify_minute(client):
    """分足 bulk を日次 API と突き合わせる（行数と列）。"""
    src = os.path.join(BULK_ROOT, 'bars_minute')
    files = sorted(f for f in os.listdir(src)
                   if f.endswith('.csv.gz')) if os.path.isdir(src) else []
    if not files:
        logging.warning('  分足の bulk がありません（取得前）')
        return True
    target = os.path.join(src, files[len(files) // 2])
    df = pd.read_csv(target, compression='gzip', dtype=str)
    day = df['Date'].value_counts().idxmax()
    n_bulk = int((df['Date'] == day).sum())

    api = client.get('/equities/bars/minute', {'date': day})
    n_api = len(api)
    ok = n_bulk == n_api
    logging.info(f'  {"✓" if ok else "✗"} 分足 {day}: bulk {n_bulk:,}行 / '
                 f'API {n_api:,}行')
    if api:
        missing = sorted(set(api[0]) - set(df.columns))
        if missing:
            ok = False
            logging.error(f'  ✗ 列の欠落: {missing}')
        else:
            logging.info(f'  ✓ 列一致 {len(api[0])}列')
    return ok


def verify_trades(client):
    """ティックは突き合わせる API が無いので、日次4本値の出来高と照合する。

    /equities/trades に対応する API パスが存在しない以上、bulk の欠落は
    外部から検出するしかない。同じ日の /equities/bars/daily の Vo と
    ティックの TradingVolume 合計が銘柄ごとに一致するかを見る。
    """
    root = os.path.join(PARQUET_ROOT, 'trades')
    days = sorted(os.path.join(r, f)
                  for r, _, fs in os.walk(root) for f in fs
                  if f.endswith('.parquet'))
    if not days:
        logging.warning('  ティックの parquet がありません（変換前）')
        return True
    target = days[len(days) // 2]
    day = os.path.basename(target)[:8]
    day_iso = f'{day[:4]}-{day[4:6]}-{day[6:]}'

    t = pq.read_table(target, columns=['Code', 'TradingVolume'])
    tick = t.to_pandas().groupby('Code')['TradingVolume'].sum()

    bars = pd.DataFrame(client.get('/equities/bars/daily', {'date': day_iso}))
    if bars.empty:
        logging.warning(f'  {day_iso} の日次4本値が空。検証を省略')
        return True
    bars['Vo'] = pd.to_numeric(bars['Vo'], errors='coerce')
    bars = bars[bars['Vo'].fillna(0) > 0]

    j = bars.set_index('Code')['Vo'].to_frame('daily').join(
        tick.to_frame('tick'), how='inner')
    if j.empty:
        logging.error('  ✗ 銘柄コードが1件も突き合わない（Code の桁揃えを確認）')
        return False
    match = int((j['daily'] == j['tick']).sum())
    rate = match / len(j)
    # 立会外取引などが日次側に含まれるため完全一致は期待しない。
    # 大半がズレるなら bulk の欠落を疑う
    ok = rate >= 0.90
    logging.info(f'  {"✓" if ok else "✗"} ティック {day_iso}: '
                 f'出来高一致 {match:,}/{len(j):,} 銘柄 ({rate:.1%})')
    return ok


def fetch(client, dataset):
    cfg = DATASETS[dataset]
    files = list_files(client, cfg['endpoint'])
    total_gb = sum(f['Size'] for f in files) / 1e9
    logging.info(f'{dataset}: {len(files)} ファイル / {total_gb:.2f} GB(gz)')

    got = skipped = 0
    for i, f in enumerate(files, 1):
        key = f['Key']
        out = os.path.join(BULK_ROOT, dataset, os.path.basename(key))
        if os.path.exists(out):
            skipped += 1
            continue
        gz, raw = download(client, key, out)
        got += 1
        logging.info(f'  [{i}/{len(files)}] {os.path.basename(key)} '
                     f'{gz / 1e6:.0f}MB(gz) → 展開 {raw / 1e6:.0f}MB')
    logging.info(f'✅ {dataset}: 取得{got} / キャッシュ{skipped}')


def show_list(client, dataset):
    cfg = DATASETS[dataset]
    files = list_files(client, cfg['endpoint'])
    for f in files:
        logging.info(f"  {f['Key']}  {f['Size'] / 1e6:.0f}MB  {f['LastModified']}")
    logging.info(f"{dataset}: {len(files)} ファイル / "
                 f"{sum(f['Size'] for f in files) / 1e9:.2f} GB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dataset', choices=sorted(DATASETS))
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--list', action='store_true', help='一覧だけ出して終わる')
    ap.add_argument('--no-convert', action='store_true', help='取得だけ行う')
    ap.add_argument('--convert-only', action='store_true', help='変換だけ行う')
    ap.add_argument('--verify', action='store_true', help='取得後に検証する')
    args = ap.parse_args()

    if not args.dataset and not args.all:
        ap.error('--dataset か --all を指定してください')
    targets = sorted(DATASETS) if args.all else [args.dataset]

    client = Client(min_interval=1.0)   # アドオンは 60 req/分
    ok = True
    for ds in targets:
        if args.list:
            show_list(client, ds)
            continue
        if not args.convert_only:
            fetch(client, ds)
        if not args.no_convert:
            convert(ds)
        if args.verify:
            ok &= (verify_minute(client) if ds == 'bars_minute'
                   else verify_trades(client))
    return ok


if __name__ == '__main__':
    sys.exit(0 if main() else 1)

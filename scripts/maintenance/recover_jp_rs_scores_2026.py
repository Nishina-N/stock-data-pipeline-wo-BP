"""
recover_jp_rs_scores_2026.py

jp/scores/RS_scores/{sector,industry}/2026.json の復旧。

背景:
  US側障害報告（2026-08-13）を受けた横展開調査で、JP側にも
  2_calculate_jp_rs.py の null グループ混入（read_csv が "N/A" を NaN 化 →
  `if s and s != 'N/A'` を NaN が素通り）を確認。汚染は 2026 のみ
  （sector 17→18, industry 33→34 グループ、2026-01-05..08-10 の全147日）。
  2023-2025 は JP 側の year-freeze が正しく機能していたため無傷。
  混入源は 1306/^N225 ベンチマーク疑似ティッカー（Sector/Industry='N/A'）。

方法（US 版 recover_rs_scores_2024_2026.py と同じ）:
  jp/stocks/daily/core/ 側の individual rs_percentile は無傷なので、
  core の 2026 年ファイルから rs/close/volume を読み、修正後のロジック
  （null/N/A/'-' グループ除外）で sector/industry の加重集計のみやり直す。
  重み = 銘柄ごとの最新 close×volume（2_calculate_jp_rs.py と同一方式）。
  stock_count / industry->sector 対応は 3_export_jp_json.py と同一ロジック。

使い方:
  python scripts/maintenance/recover_jp_rs_scores_2026.py --build     # ローカル生成のみ
  python scripts/maintenance/recover_jp_rs_scores_2026.py --execute   # 生成 + R2アップロード
"""
import os
import sys
import json
import logging
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.r2 import create_s3_client

from dotenv import load_dotenv
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DATA_FOLDER = "data"
OUT_ROOT = os.path.join(DATA_FOLDER, "recover_jp_rs_scores")
CORE_PREFIX = "jp/stocks/daily/core"
SCORES_PREFIX = "jp/scores/RS_scores"
CSV_KEY = "jp/metadata/target_stocks_jp_latest.csv"

TARGET_YEAR = 2026
MAX_READ_WORKERS = 16


def load_universe_info(bucket):
    """R2 のユニバースCSVから {code: {sector, industry}} を取得（NaN は 'N/A' に正規化）"""
    s3 = create_s3_client()
    try:
        obj = s3.get_object(Bucket=bucket, Key=CSV_KEY)
        import io
        df = pd.read_csv(io.BytesIO(obj['Body'].read()), dtype={'Symbol': str})
    finally:
        s3.close()
    info = {}
    for _, row in df.iterrows():
        code = str(row['Symbol']).strip()
        sector = row.get('Sector', 'N/A')
        industry = row.get('Industry', 'N/A')
        info[code] = {
            'sector': sector if pd.notna(sector) else 'N/A',
            'industry': industry if pd.notna(industry) else 'N/A',
        }
    logging.info(f"Universe: {len(info)} symbols")
    return info


def list_core_symbols(bucket, year):
    s3 = create_s3_client()
    codes = []
    try:
        paginator = s3.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=bucket, Prefix=f"{CORE_PREFIX}/{year}/"):
            for obj in page.get('Contents', []):
                fn = obj['Key'].rsplit('/', 1)[-1]
                if fn.endswith('.json'):
                    codes.append(fn[:-5])
    finally:
        s3.close()
    return codes


def load_core_year(codes, bucket, year):
    """
    per_symbol[code] = {date: rs_percentile}
    latest_weight[code] = 最新日の close×volume（無ければ1）
    """
    per_symbol = {}
    latest_weight = {}

    def _load(code):
        s3 = create_s3_client()
        try:
            obj = s3.get_object(Bucket=bucket, Key=f"{CORE_PREFIX}/{year}/{code}.json")
            data = json.loads(obj['Body'].read())
            rows = {r['date']: r.get('rs_percentile') for r in data.get('data', [])}
            last = data['data'][-1] if data.get('data') else {}
            return code, rows, last.get('close'), last.get('volume')
        except Exception:
            return code, None, None, None
        finally:
            s3.close()

    with ThreadPoolExecutor(max_workers=MAX_READ_WORKERS) as ex:
        futs = [ex.submit(_load, c) for c in codes]
        done = 0
        for fut in as_completed(futs):
            code, rows, close, volume = fut.result()
            if rows:
                per_symbol[code] = rows
                if close is not None and volume is not None and close * volume > 0:
                    latest_weight[code] = close * volume
                else:
                    latest_weight[code] = 1.0
            done += 1
            if done % 500 == 0:
                logging.info(f"  read core: {done}/{len(codes)}")
    return per_symbol, latest_weight


def valid_group(g):
    return bool(g) and pd.notna(g) and g != 'N/A' and g != '-'


def build_group_scores(per_symbol, latest_weight, info, group_key):
    """2_calculate_jp_rs.py（bugfix後）+ 3_export_jp_json.py と同一ロジックで再集計"""
    group_symbols = defaultdict(list)
    for code in per_symbol.keys():
        meta = info.get(code)
        if not meta:
            continue
        g = meta.get(group_key)
        if valid_group(g):
            group_symbols[g].append(code)

    all_dates = sorted(set(d for rows in per_symbol.values() for d in rows.keys()))

    group_raw = defaultdict(dict)
    for g, syms in group_symbols.items():
        for date in all_dates:
            weighted_sum = 0.0
            total_weight = 0.0
            for code in syms:
                rs = per_symbol[code].get(date)
                if rs is None:
                    continue
                w = latest_weight.get(code, 1.0)
                weighted_sum += rs * w
                total_weight += w
            if total_weight > 0:
                group_raw[g][date] = weighted_sum / total_weight

    df = pd.DataFrame(group_raw).reindex(all_dates)
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    pct = df.rank(axis=1, pct=True) * 98 + 1

    # stock_count: 3_export_jp_json.py と同一（CSV全体からカウント）
    stock_count = defaultdict(int)
    for meta in info.values():
        g = meta.get(group_key)
        if valid_group(g):
            stock_count[g] += 1

    sector_of_industry = {}
    if group_key == 'industry':
        for meta in info.values():
            ind, sec = meta.get('industry'), meta.get('sector')
            if ind and ind not in sector_of_industry:
                sector_of_industry[ind] = sec if sec else 'N/A'

    records = []
    for ts in pct.index:
        row = pct.loc[ts].dropna()
        if row.empty:
            continue
        date_str = ts.strftime('%Y-%m-%d')
        for g, rs_value in row.items():
            rank = int((row > rs_value).sum() + 1)
            rec = {
                'date': date_str,
                group_key: g,
                'rs_percentile': round(float(rs_value), 2),
                'rank': rank,
                'stock_count': stock_count.get(g, 0),
            }
            if group_key == 'industry':
                rec['sector'] = sector_of_industry.get(g, 'N/A')
            records.append(rec)

    return records, len(group_symbols)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', action='store_true', help='ローカル生成のみ（R2書込なし）')
    ap.add_argument('--execute', action='store_true', help='生成 + R2アップロード')
    args = ap.parse_args()
    if not (args.build or args.execute):
        ap.error("--build / --execute のいずれかを指定")

    bucket = os.environ['R2_BUCKET_NAME']

    logging.info("[1/4] Loading universe CSV from R2...")
    info = load_universe_info(bucket)

    logging.info(f"[2/4] Listing + reading jp core {TARGET_YEAR}...")
    codes = list_core_symbols(bucket, TARGET_YEAR)
    logging.info(f"  {len(codes)} core files")
    per_symbol, latest_weight = load_core_year(codes, bucket, TARGET_YEAR)
    logging.info(f"  loaded {len(per_symbol)} symbols")

    for group_key in ('sector', 'industry'):
        logging.info(f"[3/4] Building {group_key} RS...")
        records, n_groups = build_group_scores(per_symbol, latest_weight, info, group_key)
        dates = sorted(set(r['date'] for r in records))
        logging.info(f"  {group_key}: {n_groups} groups (null excluded), "
                     f"{len(records)} records, {len(dates)} dates ({dates[0]}..{dates[-1]})")

        out_dir = os.path.join(OUT_ROOT, SCORES_PREFIX, group_key)
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{TARGET_YEAR}.json")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False)

        if args.execute:
            key = f"{SCORES_PREFIX}/{group_key}/{TARGET_YEAR}.json"
            s3 = create_s3_client()
            try:
                s3.upload_file(path, bucket, key)
                logging.info(f"  ✅ uploaded {key}")
            finally:
                s3.close()

    if args.build:
        logging.info(f"[4/4] BUILD only. Local: {os.path.join(OUT_ROOT, SCORES_PREFIX)} (R2未書込)")
    else:
        logging.info("[4/4] Upload complete")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

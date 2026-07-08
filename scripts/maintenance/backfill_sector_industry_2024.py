"""
backfill_sector_industry_2024.py

scores/RS_scores/{sector,industry}/2024.json の欠損（2024-01-02..2024-10-07）を埋める。

背景:
  個別RS(core) は backfill 済みだが、sector/industry の年別スコアは 2024 が
  2024-10-08 以降しか無い（59日）。前半 ~192営業日が欠損。

方針（本番 3_calculate_rs.py と同一ロジック）:
  1. core/2024/{symbol}.json から個別 rs_percentile（date×symbol）と
     加重（各銘柄の最新 close×volume）を読む
  2. sector/industry ごとに rs_percentile を加重平均 → グループ間で再percentile(rank*98+1)
  3. save 形式（date, sector|industry, rs_percentile, rank, stock_count[, sector]）で
     欠損日のレコードを生成
  4. 既存の 2024.json（Oct–Dec）とマージし、日付順で書き戻し
  5. 2ファイルのみアップロード

使い方:
  python scripts/maintenance/backfill_sector_industry_2024.py --build        # ローカル生成のみ
  python scripts/maintenance/backfill_sector_industry_2024.py --execute       # 生成 + R2アップロード
  python scripts/maintenance/backfill_sector_industry_2024.py --upload-only   # 生成済みをアップロード
"""
import os
import sys
import json
import logging
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.r2 import create_s3_client
from common.symbols import load_symbols_info
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DATA_FOLDER = "data"
TARGET_STOCKS_CSV = os.path.join(DATA_FOLDER, "target_stocks_latest.csv")
OUT_DIR = os.path.join(DATA_FOLDER, "backfill", "r2", "scores", "RS_scores")

YEAR = 2024
GAP_END = "2025-01-01"           # 2024全体を再生成（既存とマージせず全期間を上書き）
CORE_PREFIX = "stocks/daily/core"
SCORES_PREFIX = "scores/RS_scores"
MAX_READ_WORKERS = 16


def read_core_2024(symbols, bucket):
    """
    core/2024/{symbol}.json から
      rs_by_sym[symbol] = Series(index=date, rs_percentile)
      weight[symbol]    = 最新 close*volume（無ければ1）
    を返す。
    """
    rs_by_sym = {}
    weight = {}

    def _load(sym):
        s3 = create_s3_client()
        try:
            key = f"{CORE_PREFIX}/{YEAR}/{sym}.json"
            try:
                data = json.loads(s3.get_object(Bucket=bucket, Key=key)['Body'].read())
            except s3.exceptions.NoSuchKey:
                return sym, None, 1
            rows = data.get('data', [])
            ser = {r['date']: r['rs_percentile'] for r in rows if r.get('rs_percentile') is not None}
            # 最新の close*volume を重みに
            w = 1
            for r in reversed(rows):
                c, v = r.get('close'), r.get('volume')
                if c is not None and v is not None:
                    w = c * v
                    break
            return sym, (ser if ser else None), w
        finally:
            s3.close()

    with ThreadPoolExecutor(max_workers=MAX_READ_WORKERS) as ex:
        futs = {ex.submit(_load, s): s for s in symbols}
        done = 0
        for fut in as_completed(futs):
            sym, ser, w = fut.result()
            weight[sym] = w
            if ser:
                rs_by_sym[sym] = pd.Series(ser)
            done += 1
            if done % 500 == 0:
                logging.info(f"  read core/2024: {done}/{len(symbols)}")
    return rs_by_sym, weight


def weighted_group_rs(rs_df, group_symbols, weights):
    """グループごとに rs_percentile を加重平均 → DataFrame(date×group)"""
    out = {}
    for group, syms in group_symbols.items():
        cols = [s for s in syms if s in rs_df.columns]
        if not cols:
            continue
        sub = rs_df[cols]
        w = np.array([weights.get(s, 1) for s in cols], dtype=float)
        # 各日: sum(rs*w) / sum(w over non-nan)
        mask = sub.notna()
        wsum = (sub.fillna(0).values * w).sum(axis=1)
        wtot = (mask.values * w).sum(axis=1)
        vals = np.where(wtot > 0, wsum / wtot, np.nan)
        out[group] = pd.Series(vals, index=rs_df.index)
    return pd.DataFrame(out)


def to_percentile(df):
    return df.rank(axis=1, pct=True) * 98 + 1


def build_records(group_pct, group_key, symbols_info, industry_to_sector):
    """save_group_rs と同じ形式のレコードを生成"""
    stock_count = defaultdict(int)
    for info in symbols_info.values():
        g = info.get(group_key)
        if g:
            stock_count[g] += 1

    records = []
    for date in group_pct.index:
        row = group_pct.loc[date].dropna()
        for group, v in row.items():
            rank = int((row > v).sum() + 1)
            rec = {
                'date': date,
                group_key: group,
                'rs_percentile': round(float(v), 2),
                'rank': rank,
                'stock_count': stock_count.get(group, 0),
            }
            if group_key == 'industry':
                rec['sector'] = industry_to_sector.get(group, 'N/A')
            records.append(rec)
    return records


def load_existing(bucket, kind):
    s3 = create_s3_client()
    try:
        key = f"{SCORES_PREFIX}/{kind}/{YEAR}.json"
        try:
            return json.loads(s3.get_object(Bucket=bucket, Key=key)['Body'].read())
        except s3.exceptions.NoSuchKey:
            return []
    finally:
        s3.close()


def merge_and_write(kind, new_records, existing):
    """欠損日(<GAP_END)の新レコード + 既存レコードを日付順に結合して書き出し"""
    existing_dates = set(r['date'] for r in existing)
    added = [r for r in new_records if r['date'] < GAP_END and r['date'] not in existing_dates]
    merged = existing + added
    merged.sort(key=lambda r: r['date'])

    os.makedirs(os.path.join(OUT_DIR, kind), exist_ok=True)
    path = os.path.join(OUT_DIR, kind, f"{YEAR}.json")
    with open(path, 'w') as f:
        json.dump(merged, f)

    dates = sorted(set(r['date'] for r in merged))
    logging.info(f"  {kind}: existing={len(existing)} +added={len(added)} "
                 f"-> total={len(merged)} dates={len(dates)} "
                 f"{dates[0]}..{dates[-1]}")
    return path


def upload(bucket):
    s3 = create_s3_client()
    try:
        for kind in ('sector', 'industry'):
            path = os.path.join(OUT_DIR, kind, f"{YEAR}.json")
            if not os.path.exists(path):
                logging.warning(f"missing local {path}")
                continue
            key = f"{SCORES_PREFIX}/{kind}/{YEAR}.json"
            s3.upload_file(path, bucket, key)
            logging.info(f"  uploaded {key}")
    finally:
        s3.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', action='store_true')
    ap.add_argument('--execute', action='store_true')
    ap.add_argument('--upload-only', action='store_true')
    args = ap.parse_args()
    if not (args.build or args.execute or args.upload_only):
        ap.error("--build / --execute / --upload-only のいずれかを指定")

    bucket = os.environ['R2_BUCKET_NAME']

    if args.upload_only:
        logging.info("UPLOAD-ONLY")
        upload(bucket)
        return True

    symbols_info = load_symbols_info(TARGET_STOCKS_CSV)
    universe = sorted(s for s in symbols_info.keys() if isinstance(s, str) and s)

    logging.info(f"[1/4] Reading core/2024 individual RS for {len(universe)} symbols...")
    rs_by_sym, weights = read_core_2024(universe, bucket)
    rs_df = pd.DataFrame(rs_by_sym).sort_index()
    logging.info(f"  rs matrix: {rs_df.shape} ({rs_df.index.min()}..{rs_df.index.max()})")

    # グループ→銘柄
    sector_syms = defaultdict(list)
    industry_syms = defaultdict(list)
    industry_to_sector = {}
    for sym, info in symbols_info.items():
        if not (isinstance(sym, str) and sym in rs_df.columns):
            continue
        sec = info.get('sector')
        ind = info.get('industry')
        if sec and sec != 'N/A':
            sector_syms[sec].append(sym)
        if ind and ind != 'N/A':
            industry_syms[ind].append(sym)
            if sec:
                industry_to_sector.setdefault(ind, sec)

    logging.info("[2/4] Computing weighted group RS + re-percentile...")
    sector_pct = to_percentile(weighted_group_rs(rs_df, sector_syms, weights))
    industry_pct = to_percentile(weighted_group_rs(rs_df, industry_syms, weights))

    logging.info("[3/4] Building records + merging with existing...")
    sector_recs = build_records(sector_pct, 'sector', symbols_info, industry_to_sector)
    industry_recs = build_records(industry_pct, 'industry', symbols_info, industry_to_sector)

    # 2024 全体を再生成し丸ごと置換（既存とはマージしない）
    merge_and_write('sector', sector_recs, [])
    merge_and_write('industry', industry_recs, [])

    if args.build:
        logging.info(f"[4/4] BUILD only. Local: {OUT_DIR} (R2未書込)")
        return True

    logging.info("[4/4] Uploading 2 files to R2...")
    upload(bucket)
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

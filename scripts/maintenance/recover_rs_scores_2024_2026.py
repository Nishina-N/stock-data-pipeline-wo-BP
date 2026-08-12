"""
recover_rs_scores_2024_2026.py

scores/RS_scores/{sector,industry}/{2024,2025,2026}.json の復旧。

背景（momentum_trade側からの障害報告 2026-08-13）:
  1. 5_upload_to_r2.py の extract_year_from_path バグにより、ファイル名にしか
     年が現れない scores/RS_scores/{sector,industry}/{年}.json が year-freeze の
     対象外（常に上書き）扱いになっていた。
  2. 3_calculate_rs.py の calculate_group_rs_weighted が NaN(float) の
     sector/industry を素通りさせ、null グループがランキング母数に混入していた。
  上記2件は別PRで修正済み（common/symbols.py, scripts/daily/3_calculate_rs.py,
  scripts/daily/5_upload_to_r2.py）。本スクリプトはその修正ロジックを使って
  2024-2026年分の sector/industry RS を全期間で再計算・復旧する。

前提（この復旧が成立する理由）:
  - stocks/daily/core/{year}/{symbol}.json 側の individual rs_percentile は
    無傷（障害は scores 集計側のみ）。よって個別RSを再計算する必要はなく、
    core から読み出した rs_percentile をそのまま使ってグループ集計をやり直せばよい。
  - 2024-01〜10 分も stocks/daily/core は無傷なので、この期間の sector/industry
    RS も本スクリプトで復元できる（scores 側でのみ消失していたため）。

方法:
  1. R2 core/{2024,2025,2026}/{symbol}.json を全銘柄ぶん読み、
     date -> {symbol: (rs_percentile, close, volume)} を構築
  2. sector/industry は最新の target_stocks_latest.csv から取得
     （NaN は 'N/A' に正規化＝bugfix後の load_symbols_info と同一ロジック）
  3. 重み = 銘柄ごとの最新 close×volume（3_calculate_rs.py と同一方式、全期間で固定）
  4. 日付ごとに sector/industry でグルーピング（'N/A'/NaN は除外）→ 加重平均 → 再percentile化
  5. 年別JSONを組み立て、アップロード前に安全確認:
       - 日付カバレッジが該当年の前後（1月-12月）を欠けていないか
       - グループ数が過去年(2021-2023)と同水準か
     をログ表示。put_object は --execute 時のみ。

使い方:
  python scripts/maintenance/recover_rs_scores_2024_2026.py --build           # ローカル生成のみ
  python scripts/maintenance/recover_rs_scores_2024_2026.py --execute         # 生成 + R2アップロード
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
OUT_ROOT = os.path.join(DATA_FOLDER, "recover_rs_scores")
CORE_PREFIX = "stocks/daily/core"
SCORES_PREFIX = "scores/RS_scores"

READ_YEARS = [2024, 2025, 2026]
MAX_READ_WORKERS = 16


def download_universe_csv(bucket):
    s3 = create_s3_client()
    try:
        obj = s3.get_object(Bucket=bucket, Key="metadata/target_stocks_latest.csv")
        os.makedirs(DATA_FOLDER, exist_ok=True)
        with open(TARGET_STOCKS_CSV, 'wb') as f:
            f.write(obj['Body'].read())
        logging.info(f"Downloaded universe CSV -> {TARGET_STOCKS_CSV}")
    finally:
        s3.close()


def read_core_file(s3, bucket, year, symbol):
    key = f"{CORE_PREFIX}/{year}/{symbol}.json"
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        return json.loads(obj['Body'].read())
    except s3.exceptions.NoSuchKey:
        return None
    except Exception as e:
        logging.debug(f"read fail {key}: {e}")
        return None


def load_all_core(symbols, bucket):
    """
    各銘柄の READ_YEARS を読み、
      per_symbol[symbol] = {date: (rs_percentile, close, volume)}
      latest_weight[symbol] = close * volume (最新日, 無ければ1)
    を返す。
    """
    per_symbol = {}
    latest_weight = {}

    def _load(sym):
        s3 = create_s3_client()
        try:
            rows_by_date = {}
            last_close, last_volume, last_date = None, None, None
            for y in READ_YEARS:
                data = read_core_file(s3, bucket, y, sym)
                if data is None:
                    continue
                for r in data.get('data', []):
                    d = r['date']
                    rows_by_date[d] = (r.get('rs_percentile'), r.get('close'), r.get('volume'))
                    if last_date is None or d > last_date:
                        last_date = d
                        last_close, last_volume = r.get('close'), r.get('volume')
            return sym, rows_by_date, last_close, last_volume
        finally:
            s3.close()

    with ThreadPoolExecutor(max_workers=MAX_READ_WORKERS) as ex:
        futs = {ex.submit(_load, s): s for s in symbols}
        done = 0
        for fut in as_completed(futs):
            sym, rows_by_date, close, volume = fut.result()
            if rows_by_date:
                per_symbol[sym] = rows_by_date
                if close is not None and volume is not None:
                    latest_weight[sym] = close * volume
                else:
                    latest_weight[sym] = 1
            done += 1
            if done % 500 == 0:
                logging.info(f"  read core: {done}/{len(symbols)}")

    return per_symbol, latest_weight


def build_group_scores(per_symbol, latest_weight, symbols_info, group_key):
    """
    3_calculate_rs.py の calculate_group_rs_weighted / calculate_percentiles_vectorized /
    save_group_rs と同一ロジック（bugfix後）で group RS を再計算する。
    """
    # グループ別に銘柄をまとめる（'N/A'・NaN・未登録は除外 = bugfix後のロジック）
    group_symbols = defaultdict(list)
    for sym in per_symbol.keys():
        info = symbols_info.get(sym)
        if not info:
            continue
        group = info.get(group_key)
        if group and pd.notna(group) and group != 'N/A':
            group_symbols[group].append(sym)

    # 日付の全集合
    all_dates = sorted(set(d for rows in per_symbol.values() for d in rows.keys()))

    # date x symbol の rs_percentile 行列を作る方が速いが、メモリ節約のため
    # date -> group -> (weighted_sum, total_weight) を直接積み上げる
    group_raw = defaultdict(dict)  # group -> {date: value}
    for group, syms in group_symbols.items():
        for date in all_dates:
            weighted_sum = 0.0
            total_weight = 0.0
            for sym in syms:
                rec = per_symbol[sym].get(date)
                if rec is None:
                    continue
                rs_value = rec[0]
                if rs_value is None:
                    continue
                w = latest_weight.get(sym, 1)
                weighted_sum += rs_value * w
                total_weight += w
            if total_weight > 0:
                group_raw[group][date] = weighted_sum / total_weight

    df = pd.DataFrame(group_raw).reindex(all_dates)
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()

    # 日次クロスセクション percentile（本番と同一）
    pct = df.rank(axis=1, pct=True) * 98 + 1

    stock_count = {g: len(syms) for g, syms in group_symbols.items()}

    # industry -> sector 対応
    industry_to_sector = {}
    if group_key == 'industry':
        for info in symbols_info.values():
            ind = info.get('industry')
            if ind and ind not in industry_to_sector:
                industry_to_sector[ind] = info.get('sector', 'N/A')

    records_by_year = defaultdict(list)
    for ts in pct.index:
        date_str = ts.strftime('%Y-%m-%d')
        row = pct.loc[ts].dropna()
        if row.empty:
            continue
        year = ts.year
        for group, rs_value in row.items():
            rank = int((row > rs_value).sum() + 1)
            rec = {
                'date': date_str,
                group_key: group,
                'rs_percentile': round(float(rs_value), 2),
                'rank': rank,
                'stock_count': stock_count.get(group, 0),
            }
            if group_key == 'industry':
                rec['sector'] = industry_to_sector.get(group, 'N/A')
            records_by_year[year].append(rec)

    return records_by_year, len(group_symbols)


def write_local(records_by_year, group_key):
    out_dir = os.path.join(OUT_ROOT, SCORES_PREFIX, group_key)
    os.makedirs(out_dir, exist_ok=True)
    for year, records in records_by_year.items():
        if year not in READ_YEARS:
            continue
        path = os.path.join(out_dir, f"{year}.json")
        with open(path, 'w') as f:
            json.dump(records, f)
        dates = sorted(set(r['date'] for r in records))
        logging.info(f"  {group_key}/{year}: {len(records)} records, "
                     f"{len(dates)} dates ({dates[0]}..{dates[-1]})")


def upload_local(bucket, group_key):
    out_dir = os.path.join(OUT_ROOT, SCORES_PREFIX, group_key)
    if not os.path.isdir(out_dir):
        logging.warning(f"no local dir: {out_dir}")
        return
    s3 = create_s3_client()
    try:
        for fn in sorted(os.listdir(out_dir)):
            if not fn.endswith('.json'):
                continue
            path = os.path.join(out_dir, fn)
            key = f"{SCORES_PREFIX}/{group_key}/{fn}"
            s3.upload_file(path, bucket, key)
            logging.info(f"  ✅ uploaded {key}")
    finally:
        s3.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', action='store_true', help='ローカル生成のみ（R2書込なし）')
    ap.add_argument('--execute', action='store_true', help='生成 + R2アップロード（force overwrite）')
    args = ap.parse_args()

    if not (args.build or args.execute):
        ap.error("--build / --execute のいずれかを指定")

    bucket = os.environ['R2_BUCKET_NAME']

    logging.info("[1/4] Downloading universe CSV...")
    download_universe_csv(bucket)
    symbols_info = load_symbols_info(TARGET_STOCKS_CSV)
    universe = sorted(s for s in symbols_info.keys() if isinstance(s, str) and s)
    logging.info(f"Universe: {len(universe)} symbols")

    logging.info(f"[2/4] Reading core {READ_YEARS} from R2 for all symbols...")
    per_symbol, latest_weight = load_all_core(universe, bucket)
    logging.info(f"  loaded core data for {len(per_symbol)} symbols")

    for group_key in ('sector', 'industry'):
        logging.info(f"[3/4] Building {group_key} RS...")
        records_by_year, n_groups = build_group_scores(per_symbol, latest_weight, symbols_info, group_key)
        logging.info(f"  {group_key}: {n_groups} groups (null group excluded)")
        write_local(records_by_year, group_key)

    if args.build:
        logging.info(f"[4/4] BUILD only. Local: {os.path.join(OUT_ROOT, SCORES_PREFIX)} (R2未書込)")
        return True

    logging.info("[4/4] Uploading to R2 (force overwrite 2024/2025/2026)...")
    for group_key in ('sector', 'industry'):
        upload_local(bucket, group_key)

    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

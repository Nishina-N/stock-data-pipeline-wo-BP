"""
backfill_gap_2023_2024.py

2023前半の価格/出来高欠損 と 2023全体+2024前半のRS欠損 を埋め戻す。

構造的原因:
  - 過去年ファイルは「R2に無ければ書く」で凍結（5_upload_to_r2.py）
  - パイプライン初回作成時の直近1000日窓が 2023-05-22 起点だったため
    2023-01..05 の価格行が書かれず truncated のまま凍結
  - RS 出力窓(500日)が ~2024-05 までしか届かず 2023全体+2024前半のRSが欠損

方針（Yahoo再取得を最小化）:
  1. R2 core(2022,2023,2024) から全銘柄の OHLCV を読む（既存行の保全にも使用）
  2. Yahoo取得は不足分（2023-01-02..2023-05-19）だけ
  3. 本番と同一ロジックで RS を横断再計算
  4. マージ書き戻し（既存OHLCV行は保全、欠損だけ補充/RS付与）
  5. アップロードは 2023/2024 のみ強制上書き（--execute 時）

使い方:
  python scripts/maintenance/backfill_gap_2023_2024.py --dry-run            # 数銘柄で検証JSON生成のみ
  python scripts/maintenance/backfill_gap_2023_2024.py --dry-run AAPL MSFT  # 指定銘柄で検証
  python scripts/maintenance/backfill_gap_2023_2024.py --build              # 全銘柄ローカル生成（R2書込なし）
  python scripts/maintenance/backfill_gap_2023_2024.py --execute            # 全銘柄生成 + R2アップロード
"""
import os
import sys
import json
import time
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
OUT_ROOT = os.path.join(DATA_FOLDER, "backfill", "r2")
CORE_LOCAL = os.path.join(OUT_ROOT, "stocks", "daily", "core")
CORE_PREFIX = "stocks/daily/core"

# RS lookback を賄うため 2022 から読み込む。RS gap は 2023全体 + 2024前半。
READ_YEARS = [2022, 2023, 2024]
GAP_PRICE_START = "2023-01-01"   # Yahoo で取り直す価格欠損レンジ（2023前半）
GAP_PRICE_END = "2023-05-22"     # 既存が始まる直前まで（end は排他）
WRITE_YEARS = [2023, 2024]       # 書き戻す年

MAX_READ_WORKERS = 16
MIN_DAYS = 252


# ----------------------------------------------------------------------------
# R2 read
# ----------------------------------------------------------------------------
def read_core_file(s3, bucket, year, symbol):
    """R2 の core/{year}/{symbol}.json を返す（無ければ None）"""
    key = f"{CORE_PREFIX}/{year}/{symbol}.json"
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        return json.loads(obj['Body'].read())
    except s3.exceptions.NoSuchKey:
        return None
    except Exception as e:
        logging.debug(f"read fail {key}: {e}")
        return None


def load_existing_core(symbols, bucket):
    """
    各銘柄の READ_YEARS を読み、
      existing[symbol][year] = {'meta': {...}, 'rows': {date: row}}
    を返す（rows は date -> OHLCV+rs の dict）。
    """
    existing = defaultdict(dict)

    def _load(sym):
        s3 = create_s3_client()
        try:
            per = {}
            for y in READ_YEARS:
                data = read_core_file(s3, bucket, y, sym)
                if data is None:
                    continue
                rows = {r['date']: r for r in data.get('data', [])}
                per[y] = {
                    'meta': {k: data.get(k) for k in ('ticker', 'name', 'sector', 'industry')},
                    'rows': rows,
                }
            return sym, per
        finally:
            s3.close()

    with ThreadPoolExecutor(max_workers=MAX_READ_WORKERS) as ex:
        futs = {ex.submit(_load, s): s for s in symbols}
        done = 0
        for fut in as_completed(futs):
            sym, per = fut.result()
            if per:
                existing[sym] = per
            done += 1
            if done % 500 == 0:
                logging.info(f"  read core: {done}/{len(symbols)}")
    return existing


# ----------------------------------------------------------------------------
# Yahoo fetch (gap only)
# ----------------------------------------------------------------------------
def fetch_gap_prices(symbols, start, end, chunk_size=50, delay=1.0, max_retries=3):
    """欠損レンジのみ Yahoo から取得。 {symbol: DataFrame(OHLCV)} を返す。"""
    import yfinance as yf
    logging.info(f"Fetching gap prices {start}..{end} for {len(symbols)} symbols")
    out = {}
    total = (len(symbols) + chunk_size - 1) // chunk_size
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i + chunk_size]
        cn = i // chunk_size + 1
        for attempt in range(max_retries):
            try:
                df = yf.download(chunk, start=start, end=end, threads=False,
                                 progress=False, group_by='ticker', auto_adjust=True)
                if df is None or df.empty:
                    logging.warning(f"  chunk {cn}/{total}: empty")
                    break
                for sym in chunk:
                    try:
                        sub = df[sym] if len(chunk) > 1 else df
                        sub = sub.dropna(how='all')
                        if not sub.empty:
                            out[sym] = sub
                    except Exception:
                        pass
                logging.info(f"  chunk {cn}/{total}: ok ({len(chunk)} syms)")
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    logging.error(f"  chunk {cn} failed: {e}")
                else:
                    time.sleep(delay * 2)
        time.sleep(delay)
    logging.info(f"Fetched gap data for {len(out)} symbols")
    return out


def gapdf_to_rows(sub):
    """Yahoo DataFrame を {date: {open,high,low,close,volume}} に変換"""
    rows = {}
    for ts, r in sub.iterrows():
        date = pd.Timestamp(ts).strftime('%Y-%m-%d')
        def g(col):
            v = r.get(col)
            return None if pd.isna(v) else float(v)
        vol = r.get('Volume')
        rows[date] = {
            'open': g('Open'), 'high': g('High'), 'low': g('Low'),
            'close': g('Close'),
            'volume': None if pd.isna(vol) else int(vol),
        }
    return rows


# ----------------------------------------------------------------------------
# RS 再計算（本番 3_calculate_rs.py と同一ロジック）
# ----------------------------------------------------------------------------
def build_close_matrix(existing, gap_rows):
    """
    existing(R2) + gap_rows(Yahoo) を統合して close の DataFrame を作る。
    index=日付, columns=symbol。
    """
    close_by_sym = {}
    for sym, per in existing.items():
        merged = {}
        for y in READ_YEARS:
            if y in per:
                for date, row in per[y]['rows'].items():
                    if row.get('close') is not None:
                        merged[date] = row['close']
        # gap 補充（既存に無い日付のみ）
        for date, row in gap_rows.get(sym, {}).items():
            if row.get('close') is not None:
                merged.setdefault(date, row['close'])
        if merged:
            close_by_sym[sym] = pd.Series(merged)

    df = pd.DataFrame(close_by_sym)
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    return df


def calculate_rs_percentile(df_close):
    """本番と同一: 63/126/189/252日リターンの加重 → percentile(rank*98+1)"""
    # min_days フィルタ（本番同様、252日未満の銘柄は除外）
    valid_cols = [c for c in df_close.columns if df_close[c].notna().sum() >= MIN_DAYS]
    df = df_close[valid_cols]

    ret_3m = df.pct_change(periods=63, fill_method=None) * 100
    ret_6m = df.pct_change(periods=126, fill_method=None) * 100
    ret_9m = df.pct_change(periods=189, fill_method=None) * 100
    ret_12m = df.pct_change(periods=252, fill_method=None) * 100
    rs_raw = ret_3m * 0.4 + ret_6m * 0.2 + ret_9m * 0.2 + ret_12m * 0.2

    rs_pct = rs_raw.rank(axis=1, pct=True) * 98 + 1
    return rs_pct


def rs_lookup(rs_pct):
    """rs_pct(DataFrame) を {date_str: {symbol: value}} に変換（NaN除外）"""
    out = defaultdict(dict)
    for ts in rs_pct.index:
        date = pd.Timestamp(ts).strftime('%Y-%m-%d')
        row = rs_pct.loc[ts].dropna()
        for sym, v in row.items():
            out[date][sym] = round(float(v), 2)
    return out


# ----------------------------------------------------------------------------
# マージ & 書き戻し
# ----------------------------------------------------------------------------
def build_year_file(sym, year, existing, gap_rows, rs_map, symbols_info):
    """
    指定年の core JSON を構築。既存OHLCV行は保全し、欠損補充とRS付与のみ行う。
    変更が無ければ None を返す。
    """
    per = existing.get(sym, {})
    year_existing = per.get(year, {})
    # deep copy（行オブジェクトを共有すると既存データを破壊するため）
    rows_by_date = {d: dict(r) for d, r in year_existing.get('rows', {}).items()} if year_existing else {}

    changed = False

    # 2023: 欠損価格行を追加
    if year == 2023:
        for date, row in gap_rows.get(sym, {}).items():
            if not date.startswith('2023'):
                continue
            if date not in rows_by_date:
                rows_by_date[date] = {
                    'date': date,
                    'open': row['open'], 'high': row['high'], 'low': row['low'],
                    'close': row['close'], 'volume': row['volume'],
                    'rs_percentile': None,
                }
                changed = True

    # RS 付与（空の行を埋める。既存の非空RSは尊重）
    for date, row in rows_by_date.items():
        if row.get('rs_percentile') is None:
            v = rs_map.get(date, {}).get(sym)
            if v is not None:
                row['rs_percentile'] = v
                changed = True

    if not rows_by_date or not changed:
        return None

    # メタデータ（既存優先、無ければ csv から）
    meta = year_existing.get('meta') if year_existing else None
    info = symbols_info.get(sym, {})
    if not meta or not meta.get('ticker'):
        meta = {
            'ticker': sym,
            'name': info.get('name', sym),
            'sector': info.get('sector', 'N/A'),
            'industry': info.get('industry', 'N/A'),
        }

    ordered = sorted(rows_by_date.values(), key=lambda r: r['date'])
    return {
        'ticker': meta.get('ticker', sym),
        'name': meta.get('name'),
        'sector': meta.get('sector'),
        'industry': meta.get('industry'),
        'data': ordered,
    }


def write_local(out, sym, year):
    year_dir = os.path.join(CORE_LOCAL, str(year))
    os.makedirs(year_dir, exist_ok=True)
    with open(os.path.join(year_dir, f"{sym}.json"), 'w') as f:
        json.dump(out, f)


# ----------------------------------------------------------------------------
# 検証出力
# ----------------------------------------------------------------------------
def verify_symbol(sym, existing, built):
    """1銘柄の before/after を要約表示"""
    print(f"\n### {sym}")
    for year in WRITE_YEARS:
        before = existing.get(sym, {}).get(year, {}).get('rows', {})
        b_rec = len(before)
        b_rs = sum(1 for r in before.values() if r.get('rs_percentile') is not None)
        out = built.get((sym, year))
        if out is None:
            print(f"  {year}: before rec={b_rec} rs={b_rs}  -> (no change)")
            continue
        a_rec = len(out['data'])
        a_rs = sum(1 for r in out['data'] if r.get('rs_percentile') is not None)
        first = out['data'][0]['date'] if out['data'] else None
        last = out['data'][-1]['date'] if out['data'] else None
        sample = next((r for r in out['data'] if r['date'].startswith(str(year))
                       and r.get('rs_percentile') is not None), None)
        s = f" e.g. {sample['date']} rs={sample['rs_percentile']}" if sample else ""
        print(f"  {year}: rec {b_rec}->{a_rec}  rs {b_rs}->{a_rs}  range {first}..{last}{s}")


# ----------------------------------------------------------------------------
# Upload
# ----------------------------------------------------------------------------
def upload_written(bucket):
    """data/backfill/r2/stocks/daily/core/{2023,2024}/ を R2 へ強制上書き"""
    files = []
    for year in WRITE_YEARS:
        d = os.path.join(CORE_LOCAL, str(year))
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if fn.endswith('.json'):
                files.append((os.path.join(d, fn), f"{CORE_PREFIX}/{year}/{fn}"))
    logging.info(f"Uploading {len(files)} files to R2 (force overwrite)...")

    def _up(item):
        path, key = item
        s3 = create_s3_client()
        try:
            s3.upload_file(path, bucket, key)
            return True
        except Exception as e:
            logging.error(f"upload fail {key}: {e}")
            return False
        finally:
            s3.close()

    ok = 0
    with ThreadPoolExecutor(max_workers=10) as ex:
        for r in ex.map(_up, files):
            if r:
                ok += 1
                if ok % 500 == 0:
                    logging.info(f"  uploaded {ok}/{len(files)}")
    logging.info(f"✅ Uploaded {ok}/{len(files)} files")


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='数銘柄で検証のみ')
    ap.add_argument('--build', action='store_true', help='全銘柄ローカル生成（R2書込なし）')
    ap.add_argument('--execute', action='store_true', help='全銘柄生成 + R2アップロード')
    ap.add_argument('--upload-only', action='store_true', help='生成済みローカルファイルを再計算せずR2へ上書き')
    ap.add_argument('symbols', nargs='*', help='対象銘柄（dry-run時）')
    args = ap.parse_args()

    if not (args.dry_run or args.build or args.execute or args.upload_only):
        ap.error("--dry-run / --build / --execute / --upload-only のいずれかを指定")

    bucket = os.environ['R2_BUCKET_NAME']

    if args.upload_only:
        logging.info("UPLOAD-ONLY: 生成済みローカルを R2 へ強制上書き")
        upload_written(bucket)
        return True

    symbols_info = load_symbols_info(TARGET_STOCKS_CSV)
    universe = sorted(s for s in symbols_info.keys() if isinstance(s, str) and s)

    if args.dry_run:
        subset = args.symbols or ['AAPL', 'MSFT', 'NVDA', 'AMD', 'TSLA']
        # RS を正しくランクするには全ユニバースの close が必要。
        # dry-run では RS の絶対値検証はできないため、価格補充とRS付与フローの健全性のみ検証。
        # ただし少数銘柄だけだと percentile が歪むので、RS 値は「全銘柄実行時に確定」と明示。
        logging.info("DRY-RUN: 価格補充+マージのフローを検証（RS値は全銘柄実行時に確定）")
        logging.info(f"Reading existing core for {len(subset)} symbols...")
        existing = load_existing_core(subset, bucket)
        gap = fetch_gap_prices(subset, GAP_PRICE_START, GAP_PRICE_END)
        gap_rows = {s: gapdf_to_rows(df) for s, df in gap.items()}
        df_close = build_close_matrix(existing, gap_rows)
        rs_pct = calculate_rs_percentile(df_close)
        rs_map = rs_lookup(rs_pct)

        built = {}
        for sym in subset:
            for year in WRITE_YEARS:
                out = build_year_file(sym, year, existing, gap_rows, rs_map, symbols_info)
                if out is not None:
                    built[(sym, year)] = out
                    write_local(out, sym, year)
        for sym in subset:
            verify_symbol(sym, existing, built)
        print("\n※ RS の絶対値は少数銘柄では歪みます。正しい percentile は --build/--execute（全ユニバース）で確定します。")
        print(f"※ ローカル出力: {CORE_LOCAL}")
        return True

    # 全ユニバース
    logging.info(f"Universe: {len(universe)} symbols")
    logging.info("[1/5] Reading existing core from R2...")
    existing = load_existing_core(universe, bucket)

    logging.info("[2/5] Fetching gap prices from Yahoo (2023-01..05)...")
    gap = fetch_gap_prices(universe, GAP_PRICE_START, GAP_PRICE_END)
    gap_rows = {s: gapdf_to_rows(df) for s, df in gap.items()}

    logging.info("[3/5] Building close matrix + RS (cross-sectional)...")
    df_close = build_close_matrix(existing, gap_rows)
    logging.info(f"  close matrix: {df_close.shape} ({df_close.index.min().date()}..{df_close.index.max().date()})")
    rs_pct = calculate_rs_percentile(df_close)
    rs_map = rs_lookup(rs_pct)

    logging.info("[4/5] Merging + writing local files...")
    n_written = defaultdict(int)
    for sym in universe:
        for year in WRITE_YEARS:
            out = build_year_file(sym, year, existing, gap_rows, rs_map, symbols_info)
            if out is not None:
                write_local(out, sym, year)
                n_written[year] += 1
    for y in WRITE_YEARS:
        logging.info(f"  {y}: wrote {n_written[y]} files")

    if args.build:
        logging.info(f"[5/5] BUILD only. Local: {CORE_LOCAL} (R2未書込)")
        return True

    logging.info("[5/5] Uploading to R2 (force overwrite 2023/2024)...")
    upload_written(bucket)
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

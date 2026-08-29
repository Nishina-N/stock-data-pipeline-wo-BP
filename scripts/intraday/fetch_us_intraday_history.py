"""
fetch_us_intraday_history.py

FMP stable/historical-chart から米国株の分足（30min / 15min）履歴を
**ローカルに**取得する。R2 には上げない（J-Quants のティックと同じ扱い）。

保存先: data/intraday/us/{interval}/{SYMBOL}.parquet
        data/intraday/us/{interval}/{SYMBOL}.manifest.json

## 実測した API の癖（2026-08-30）

- `stable/historical-chart/{interval}?symbol=&from=&to=` で取れる。v3 は 403 Legacy。
- 🔴 **1回の応答は約1か月で頭打ち**。from/to に1年を渡しても
  「範囲の末尾から約1か月ぶん」しか返らない（30min で 2015-01-01..12-31 → 12月のみ）。
  静かに切り詰められて**エラーにはならない**ので、必ず月単位で回すこと。
- データ下限は銘柄ごとに違う。AAPL は 2003-10 まであるが 2003-06 は 0 件。
  上場前の月は 200 + 空配列で返る（異常ではない）。
- レート制限のヘッダは返ってこない。超過は 429 でしか判断できない。

## レート

Ultimate は 3,000 req/分。既定は**その半分の 1,500 req/分**（`--rpm`）。
グローバルなトークンバケットで全ワーカーを束ねて律速する。
"""
import argparse
import json
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv('FMP_API_KEY')
BASE_URL = "https://financialmodelingprep.com/stable/historical-chart"

DATA_FOLDER = "data"
OUT_ROOT = os.path.join(DATA_FOLDER, "intraday", "us")
TARGET_STOCKS_CSV = os.path.join(DATA_FOLDER, "target_stocks_latest.csv")

COLUMNS = ['date', 'open', 'high', 'low', 'close', 'volume']

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)


class RateLimiter:
    """全スレッド共通の送信間隔。rpm を超えないようにリクエスト開始をずらす。"""

    def __init__(self, rpm):
        self.interval = 60.0 / rpm
        self._lock = threading.Lock()
        self._next = time.monotonic()

    def acquire(self):
        with self._lock:
            now = time.monotonic()
            wait = self._next - now
            if wait < 0:
                wait = 0.0
                self._next = now
            self._next += self.interval
        if wait > 0:
            time.sleep(wait)


def months_between(start, end):
    """'YYYY-MM' の並びを返す（両端を含む）。"""
    y, m = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    out = []
    while (y, m) <= (ey, em):
        out.append("%04d-%02d" % (y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def month_bounds(month):
    y, m = int(month[:4]), int(month[5:7])
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    last = (date(ny, nm, 1) - timedelta(days=1)).isoformat()
    return "%s-01" % month, last


def fetch_month(session, limiter, symbol, interval, month, max_retries=5):
    """1銘柄1か月ぶん。空配列は正常（上場前・データ無し）として [] を返す。"""
    frm, to = month_bounds(month)
    params = {'symbol': symbol, 'from': frm, 'to': to, 'apikey': API_KEY}
    url = "%s/%s" % (BASE_URL, interval)

    for attempt in range(max_retries):
        limiter.acquire()
        try:
            r = session.get(url, params=params, timeout=60)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(min(2 ** attempt, 30))
                continue
            if r.status_code != 200:
                logging.warning("%s %s %s: HTTP %s", symbol, interval, month, r.status_code)
                return None
            data = r.json()
            if not isinstance(data, list):
                logging.warning("%s %s %s: unexpected payload", symbol, interval, month)
                return None
            return data
        except Exception as e:
            if attempt == max_retries - 1:
                logging.error("%s %s %s: %s", symbol, interval, month, e)
                return None
            time.sleep(min(2 ** attempt, 30))
    return None


def parquet_path(interval, symbol):
    return os.path.join(OUT_ROOT, interval, "%s.parquet" % symbol)


def manifest_path(interval, symbol):
    return os.path.join(OUT_ROOT, interval, "%s.manifest.json" % symbol)


def load_manifest(interval, symbol):
    p = manifest_path(interval, symbol)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def save_manifest(interval, symbol, months, failed, rows, first, last):
    man = {
        'symbol': symbol,
        'interval': interval,
        'source': 'fmp:stable/historical-chart',
        'months': sorted(months),
        'failed_months': sorted(failed),
        'rows': rows,
        'first': first,
        'last': last,
        'fetched_at': pd.Timestamp.utcnow().isoformat(),
    }
    p = manifest_path(interval, symbol)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(man, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def write_atomic(df, path):
    """temp + os.replace。並行実行で書きかけのファイルを壊した過去があるため必須。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    df.to_parquet(tmp, index=False, compression='zstd')
    os.replace(tmp, path)


def fetch_symbol(session, limiter, symbol, interval, months, resume, counters):
    """1銘柄1インターバル。取得済みの月は resume でスキップし、差分だけ足す。"""
    existing = None
    done_months = set()
    if resume:
        man = load_manifest(interval, symbol)
        if man is not None:
            done = set(man.get('months') or [])
            pq = parquet_path(interval, symbol)
            if done.issuperset(months) and (man.get('rows') == 0 or os.path.exists(pq)):
                with counters['lock']:
                    counters['skipped'] += 1
                return 0
            if done and os.path.exists(pq):
                try:
                    existing = pd.read_parquet(pq)
                    done_months = done
                except Exception as e:
                    logging.warning("%s %s: 既存 parquet 読み込み失敗 (%s)。取り直す", symbol, interval, e)

    todo = [m for m in months if m not in done_months]
    frames = [existing] if existing is not None else []
    failed = []

    for month in todo:
        rows = fetch_month(session, limiter, symbol, interval, month)
        if rows is None:
            failed.append(month)
            continue
        if rows:
            frames.append(pd.DataFrame(rows))

    fetched = sorted(done_months | (set(todo) - set(failed)))

    if not frames:
        # 全期間で1行も無い（未上場・FMP に分足が無い）。空でも manifest を残して
        # 次回スキップできるようにする
        with counters['lock']:
            counters['empty'] += 1
        save_manifest(interval, symbol, fetched, failed, 0, None, None)
        return 0

    df = pd.concat(frames, ignore_index=True)
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = None
    df = df[COLUMNS]
    df['date'] = df['date'].astype(str)
    df = df.drop_duplicates(subset=['date']).sort_values('date').reset_index(drop=True)

    write_atomic(df, parquet_path(interval, symbol))
    save_manifest(interval, symbol, fetched, failed, len(df),
                  df['date'].iloc[0], df['date'].iloc[-1])

    with counters['lock']:
        counters['ok'] += 1
        counters['rows'] += len(df)
        if failed:
            counters['partial'] += 1
    return len(df)


def get_symbols(args):
    if args.symbols:
        return sorted({s.strip().upper() for s in args.symbols.split(',') if s.strip()})
    if not os.path.exists(TARGET_STOCKS_CSV):
        logging.error("Universe CSV not found: %s", TARGET_STOCKS_CSV)
        return []
    df = pd.read_csv(TARGET_STOCKS_CSV)
    df = df.dropna(subset=['Symbol']).drop_duplicates('Symbol')
    if args.limit and 'Market_Cap' in df.columns:
        # 時価総額の大きい順に絞る
        df = df.sort_values('Market_Cap', ascending=False)
    syms = [s for s in df['Symbol'].tolist() if isinstance(s, str)]
    if args.limit:
        syms = syms[:args.limit]
    return sorted(set(syms))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--intervals', default='30min,15min')
    ap.add_argument('--from', dest='start', default='2010-01', help='YYYY-MM')
    ap.add_argument('--to', dest='end', default=None, help='YYYY-MM（既定は当月）')
    ap.add_argument('--symbols', default=None, help='カンマ区切り。省略時はユニバースCSV')
    ap.add_argument('--limit', type=int, default=None, help='時価総額上位N銘柄に絞る')
    ap.add_argument('--rpm', type=int, default=1500, help='req/分。Ultimate 3000 の半分が既定')
    ap.add_argument('--workers', type=int, default=40)
    ap.add_argument('--no-resume', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    if not API_KEY:
        logging.error("FMP_API_KEY not found")
        return False

    end = args.end or pd.Timestamp.today().strftime('%Y-%m')
    months = months_between(args.start, end)
    intervals = [s.strip() for s in args.intervals.split(',') if s.strip()]
    symbols = get_symbols(args)
    if not symbols:
        return False

    total_req = len(symbols) * len(months) * len(intervals)
    logging.info("symbols=%d months=%d (%s..%s) intervals=%s",
                 len(symbols), len(months), months[0], months[-1], intervals)
    logging.info("最大リクエスト数 %s / rpm=%d → 約 %.1f 時間",
                 format(total_req, ','), args.rpm, total_req / args.rpm / 60)
    if args.dry_run:
        return True

    limiter = RateLimiter(args.rpm)
    resume = not args.no_resume

    for interval in intervals:
        os.makedirs(os.path.join(OUT_ROOT, interval), exist_ok=True)
        counters = {'lock': threading.Lock(), 'ok': 0, 'empty': 0,
                    'skipped': 0, 'partial': 0, 'rows': 0}
        t0 = time.time()

        def run(sym, _iv=interval, _c=counters):
            # requests.Session はスレッドごとに作る（使い回さない）
            session = requests.Session()
            try:
                return fetch_symbol(session, limiter, sym, _iv, months, resume, _c)
            finally:
                session.close()

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(run, s): s for s in symbols}
            for i, fut in enumerate(as_completed(futures), 1):
                sym = futures[fut]
                try:
                    fut.result()
                except Exception as e:
                    logging.error("%s %s: %s", sym, interval, e)
                if i % 50 == 0 or i == len(symbols):
                    el = time.time() - t0
                    rate = (i / el * 3600) if el > 0 else 0
                    remain = ((len(symbols) - i) / rate) if rate > 0 else float('nan')
                    logging.info("[%s] %d/%d ok=%d empty=%d skip=%d partial=%d rows=%s "
                                 "(%.0f sym/h, 残り約 %.1fh)",
                                 interval, i, len(symbols), counters['ok'], counters['empty'],
                                 counters['skipped'], counters['partial'],
                                 format(counters['rows'], ','), rate, remain)

        logging.info("[%s] 完了 ok=%d empty=%d skip=%d partial=%d rows=%s 所要 %.2fh",
                     interval, counters['ok'], counters['empty'], counters['skipped'],
                     counters['partial'], format(counters['rows'], ','),
                     (time.time() - t0) / 3600)

    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

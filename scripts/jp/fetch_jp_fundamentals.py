"""
fetch_jp_fundamentals.py

日本株の「四半期」財務データを FMP stable API から取得する（period=quarter のみ。
TTM/annual/bulk は使わない）。US 版 scripts/monthly/fetch_fundamentals.py と
完全同一のフィールド定義・取得ロジック（fetch_income_statement 等）をそのまま再利用し、
シンボルだけ JP 形式（`{code}.T`）で呼び出す。

FMP は日本株を `{code}.T`（例 7203.T）で保有しており、財務3表・key-metrics・ratios・
earnings のいずれも実測でカバレッジを確認済み（income-statement は銘柄により1988年〜、
一般的には2008〜2012年〜、earnings(決算サプライズ)は2014年〜が目安）。
JPの決算発表ラグは期末後 約32〜44日（45日開示ルールに整合）で、US版の
`_match_earnings_idx(max_days=120)` のウィンドウ内に収まるため変更不要。

出力: data/temp_fundamentals_jp.json
  {code(純コード): {ticker: code, data: [...], lastUpdated}}
  ticker は US 版と異なり `.T` を抜いた純コード（daily core 等 JP 既存規約に合わせる）

使い方:
  python scripts/jp/fetch_jp_fundamentals.py --limit 30           # 少数ドライラン
  python scripts/jp/fetch_jp_fundamentals.py                      # 全件
  python scripts/jp/fetch_jp_fundamentals.py --workers 3 --delay 0.5
"""
import os
import sys
import json
import logging
import argparse
import importlib.util
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.jp_market_symbols import JP_MARKET_SYMBOLS

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DATA_FOLDER = "data"
JP_CSV = os.path.join(DATA_FOLDER, "target_stocks_jp_latest.csv")
TEMP_FUNDAMENTALS_JSON = os.path.join(DATA_FOLDER, "temp_fundamentals_jp.json")

# US版と同じ取得ロジックをそのまま再利用（symbol はただの文字列パラメータなので
# ".T" 付きで渡せばJPも同じ関数で取得できる）
_US_PATH = os.path.join(os.path.dirname(__file__), '..', 'monthly', 'fetch_fundamentals.py')
_spec = importlib.util.spec_from_file_location('us_fetch_fundamentals', _US_PATH)
us_ff = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(us_ff)


def load_jp_universe(csv_path=JP_CSV):
    if not os.path.exists(csv_path):
        logging.error(f"JP universe CSV not found: {csv_path}")
        return []
    df = pd.read_csv(csv_path, dtype={'Symbol': str})
    df['Symbol'] = df['Symbol'].str.strip()
    codes = [s for s in df['Symbol'].tolist() if s and s not in JP_MARKET_SYMBOLS]
    logging.info(f"Loaded {len(codes)} JP symbols (excluding benchmark tickers)")
    return codes


def fetch_one(code, session):
    """US版 fetch_fundamental_data を `.T` 付きシンボルで呼び、純コードで結果を返す"""
    data = us_ff.fetch_fundamental_data(f"{code}.T", session)
    if not data:
        return None
    data['ticker'] = code  # JP既存規約: `.T` を抜いた純コードで格納
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=None, help='先頭N銘柄だけ取得（ドライラン用）')
    parser.add_argument('--workers', type=int, default=us_ff.MAX_WORKERS)
    parser.add_argument('--delay', type=float, default=us_ff.REQUEST_DELAY)
    args = parser.parse_args()
    us_ff.MAX_WORKERS = args.workers
    us_ff.REQUEST_DELAY = args.delay

    logging.info("=" * 60)
    logging.info("FETCH JP FUNDAMENTAL DATA")
    logging.info("=" * 60)

    if not us_ff.API_KEY:
        logging.error("FMP_API_KEY not found")
        return False

    codes = load_jp_universe()
    if args.limit:
        codes = codes[:args.limit]
        logging.info(f"DRY-RUN: limited to first {len(codes)} symbols")
    if not codes:
        logging.error("No symbols found")
        return False

    logging.info(f"Fetching fundamentals for {len(codes)} JP symbols "
                 f"(workers={us_ff.MAX_WORKERS}, delay={us_ff.REQUEST_DELAY}s)...")

    fundamentals_dict = {}
    success_count = fail_count = 0

    with ThreadPoolExecutor(max_workers=us_ff.MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_one, code, us_ff.SESSION): code for code in codes}
        for future in as_completed(futures):
            code = futures[future]
            try:
                data = future.result()
                if data:
                    fundamentals_dict[code] = data
                    success_count += 1
                    logging.info(f"✓ {code}: {len(data['data'])} quarters")
                else:
                    fail_count += 1
                    logging.debug(f"✗ {code}: No data")
                if (success_count + fail_count) % 100 == 0:
                    logging.info(f"Progress: {success_count + fail_count}/{len(codes)}")
            except Exception as e:
                fail_count += 1
                logging.error(f"✗ {code}: {e}")

    logging.info(f"\n{'='*60}")
    logging.info(f"Fetch completed: {success_count} success, {fail_count} failed")
    logging.info(f"{'='*60}")

    with open(TEMP_FUNDAMENTALS_JSON, 'w', encoding='utf-8') as f:
        json.dump(fundamentals_dict, f, ensure_ascii=False)

    logging.info(f"✅ Saved fundamentals to {TEMP_FUNDAMENTALS_JSON}")
    logging.info(f"   Total symbols: {len(fundamentals_dict)}")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

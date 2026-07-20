"""
1_fetch_jp_prices.py

日本株の価格データを Yahoo Finance から取得し、OHLCV のみの JSON に変換する。
US の scripts/daily/2_fetch_price_data.py + 2.5_add_indicators.py 相当を JP 用に統合。

- ユニバース: data/target_stocks_jp_latest.csv（純コード。例 7203, 130A）
- yfinance 取得時のみ `.T` を付与（7203 -> 7203.T）。出力の ticker は純コード
- 通貨 JPY・auto_adjust=True（調整後 OHLC）
- 初期シードはフル履歴（--start 既定 2004-01-01）。日次運用は直近のみ取得する想定

出力: data/temp_prices_jp.json
  {'lastUpdated', 'symbols': {code: {name, sector, industry, data:[{date,open,high,low,close,volume}]}}}

使い方:
  python scripts/jp/1_fetch_jp_prices.py --limit 30          # 少数ドライラン
  python scripts/jp/1_fetch_jp_prices.py                     # 全件・フル履歴
  python scripts/jp/1_fetch_jp_prices.py --start 2015-01-01  # 履歴開始日を指定
"""
import os
import sys
import json
import time
import argparse
import logging
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DATA_FOLDER = "data"
JP_CSV = os.path.join(DATA_FOLDER, "target_stocks_jp_latest.csv")
TEMP_PRICE_JSON = os.path.join(DATA_FOLDER, "temp_prices_jp.json")
TEMP_PRICE_PKL = os.path.join(DATA_FOLDER, "temp_prices_jp.pkl")

DEFAULT_START = "2004-01-01"


def load_jp_universe(csv_path=JP_CSV):
    """JP ユニバース CSV を読み込む。Symbol は英数字コードのため必ず文字列で扱う。"""
    if not os.path.exists(csv_path):
        logging.error(f"JP universe CSV not found: {csv_path}")
        return None

    df = pd.read_csv(csv_path, dtype={'Symbol': str})
    df['Symbol'] = df['Symbol'].str.strip()
    df = df[df['Symbol'].notna() & (df['Symbol'] != '')]
    df = df.drop_duplicates(subset=['Symbol'])
    logging.info(f"Loaded JP universe: {len(df)} symbols")
    return df


def download_price_data(yf_symbols, start_date, end_date=None,
                        chunk_size=50, delay=1, max_retries=3):
    """チャンク単位で yfinance からダウンロード（US 版と同じ堅牢化ロジック）"""
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')

    logging.info("=" * 60)
    logging.info("DOWNLOADING JP PRICE DATA")
    logging.info(f"  symbols={len(yf_symbols)}  period={start_date}..{end_date}")
    logging.info(f"  chunk_size={chunk_size} delay={delay}s")
    logging.info("=" * 60)

    all_data = []
    failed = []
    total_chunks = (len(yf_symbols) + chunk_size - 1) // chunk_size

    for i in range(0, len(yf_symbols), chunk_size):
        chunk = yf_symbols[i:i + chunk_size]
        chunk_num = i // chunk_size + 1
        success = False

        for retry in range(max_retries):
            try:
                logging.info(f"Chunk {chunk_num}/{total_chunks} ({len(chunk)} symbols, retry {retry + 1})...")
                data = yf.download(
                    chunk,
                    start=start_date,
                    end=end_date,
                    auto_adjust=True,
                    threads=False,
                    progress=False,
                )
                if data is not None and not data.empty:
                    all_data.append(data)
                    got = data.columns.get_level_values(1).unique().tolist() if len(chunk) > 1 else chunk
                    logging.info(f"  ✓ chunk {chunk_num}: {len(got)}/{len(chunk)} symbols, {len(data)} rows")
                    success = True
                    break
                logging.warning(f"  ⚠ chunk {chunk_num} returned empty")
            except Exception as e:
                logging.error(f"  ✗ chunk {chunk_num} error (retry {retry + 1}): {e}")
                if retry < max_retries - 1:
                    time.sleep(delay * 2)

        if not success:
            failed.extend(chunk)
        time.sleep(delay)

    if failed:
        logging.warning(f"⚠ {len(failed)} symbols failed")
        with open(os.path.join(DATA_FOLDER, 'failed_symbols_jp.txt'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(failed))

    if not all_data:
        logging.error("No data downloaded!")
        return None

    merged = pd.concat(all_data, axis=1)
    logging.info(f"Merged shape: {merged.shape}  "
                 f"{merged.index.min().date()}..{merged.index.max().date()}")
    return merged


def convert_to_json(price_data, info_by_code):
    """MultiIndex DataFrame（yf symbol 列）を純コード基準の OHLCV JSON に変換"""
    logging.info("Converting to JSON (OHLCV only)...")
    output = {'lastUpdated': datetime.now().isoformat(), 'symbols': {}}

    yf_symbols = price_data.columns.get_level_values(1).unique()
    for n, yf_sym in enumerate(yf_symbols, 1):
        if n % 500 == 0:
            logging.info(f"  progress: {n}/{len(yf_symbols)}")

        code = yf_sym[:-2] if yf_sym.endswith('.T') else yf_sym
        info = info_by_code.get(code)
        if info is None:
            continue

        try:
            df = pd.DataFrame({
                'open':   price_data['Open'][yf_sym],
                'high':   price_data['High'][yf_sym],
                'low':    price_data['Low'][yf_sym],
                'close':  price_data['Close'][yf_sym],
                'volume': price_data['Volume'][yf_sym],
            }).dropna(how='all')

            dates = df.index.strftime('%Y-%m-%d').tolist()
            # tolist() + zip は per-element の numpy 添字/np.isnan より大幅に速い。
            # NaN は float 特性 (x != x) で判定し None 化。
            o = np.round(df['open'].to_numpy(dtype=float), 2).tolist()
            h = np.round(df['high'].to_numpy(dtype=float), 2).tolist()
            l = np.round(df['low'].to_numpy(dtype=float), 2).tolist()
            c = np.round(df['close'].to_numpy(dtype=float), 2).tolist()
            v = df['volume'].to_numpy(dtype=float).tolist()

            data_list = [
                {
                    'date':   dt,
                    'open':   None if oo != oo else oo,
                    'high':   None if hh != hh else hh,
                    'low':    None if ll != ll else ll,
                    'close':  None if cc != cc else cc,
                    'volume': 0 if vv != vv else int(vv),
                }
                for dt, oo, hh, ll, cc, vv in zip(dates, o, h, l, c, v)
            ]

            output['symbols'][code] = {
                'name':     info['name'],
                'sector':   info['sector'],
                'industry': info['industry'],
                'data':     data_list,
            }
        except Exception as e:
            logging.warning(f"Failed to convert {yf_sym}: {e}")

    logging.info(f"✅ Converted {len(output['symbols'])} symbols")
    return output


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', default=DEFAULT_START, help='履歴開始日 (YYYY-MM-DD)')
    ap.add_argument('--end', default=None, help='履歴終了日 (既定=今日)')
    ap.add_argument('--limit', type=int, default=None, help='先頭N銘柄だけ取得（ドライラン用）')
    ap.add_argument('--chunk-size', type=int, default=50)
    ap.add_argument('--from-cache', action='store_true',
                    help='ダウンロードを省略し temp_prices_jp.pkl から変換のみ再実行')
    args = ap.parse_args()

    df = load_jp_universe()
    if df is None or df.empty:
        return False

    if args.limit:
        df = df.head(args.limit)
        logging.info(f"DRY-RUN: limited to first {len(df)} symbols")

    info_by_code = {
        row['Symbol']: {
            'name': row.get('Company Name', row['Symbol']),
            'sector': row.get('Sector', 'N/A'),
            'industry': row.get('Industry', 'N/A'),
        }
        for _, row in df.iterrows()
    }

    if args.from_cache:
        if not os.path.exists(TEMP_PRICE_PKL):
            logging.error(f"cache not found: {TEMP_PRICE_PKL}")
            return False
        logging.info(f"Loading cached download from {TEMP_PRICE_PKL}...")
        price_data = pd.read_pickle(TEMP_PRICE_PKL)
        logging.info(f"  loaded shape {price_data.shape}")
    else:
        # ^N225 のような指数コードは '.T' を付けない（common/jp_market_symbols.py 参照）
        yf_symbols = [code if code.startswith('^') else f"{code}.T" for code in df['Symbol'].tolist()]
        price_data = download_price_data(yf_symbols, args.start, args.end,
                                         chunk_size=args.chunk_size)
        if price_data is None:
            return False
        # 高価なダウンロードは変換前に必ずチェックポイント保存（中断しても捨てない）
        price_data.to_pickle(TEMP_PRICE_PKL)
        logging.info(f"💾 Cached raw download -> {TEMP_PRICE_PKL} "
                     f"({os.path.getsize(TEMP_PRICE_PKL) / 1024 / 1024:.1f} MB)")

    # pkl が本体（下流はこれを直接読む）。フル履歴×全銘柄の巨大 JSON は
    # メモリに載らず OOM するため、JSON はドライラン(--limit)時のみ書き出す。
    if args.limit:
        output = convert_to_json(price_data, info_by_code)
        if not output['symbols']:
            logging.error("No symbols converted")
            return False
        with open(TEMP_PRICE_JSON, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False)
        size_mb = os.path.getsize(TEMP_PRICE_JSON) / 1024 / 1024
        logging.info(f"✅ [dry-run] Saved {len(output['symbols'])} symbols -> "
                     f"{TEMP_PRICE_JSON} ({size_mb:.2f} MB)")
    else:
        logging.info("フル取得: 本体は pkl。RS/export は 2/3 スクリプトが pkl から直接処理する。")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

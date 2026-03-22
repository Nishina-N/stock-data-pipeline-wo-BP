"""
1_fetch_5min.py

Yahoo Finance から直近60日分の5分足データ（OHLCV）を取得し pickle 保存
"""
import os
import pandas as pd
import yfinance as yf
from datetime import datetime
import time
import logging

DATA_FOLDER = "data"
TARGET_STOCKS_CSV = os.path.join(DATA_FOLDER, "target_stocks_latest.csv")
TEMP_5MIN_PKL = os.path.join(DATA_FOLDER, "intraday", "temp_5min.pkl")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def get_symbols_from_csv():
    """target_stocks_latest.csv から銘柄取得"""
    if not os.path.exists(TARGET_STOCKS_CSV):
        logging.error(f"Target stocks file not found: {TARGET_STOCKS_CSV}")
        return []

    df = pd.read_csv(TARGET_STOCKS_CSV)

    if 'Symbol' not in df.columns:
        logging.error("'Symbol' column not found in CSV")
        return []

    symbols = df['Symbol'].dropna().unique().tolist()
    symbols = sorted(list(set(symbols)))

    logging.info(f"Loaded {len(symbols)} unique symbols from CSV")
    return symbols


def download_5min_data(symbols, chunk_size=100, delay=2, max_retries=3):
    """
    チャンク単位で5分足データを取得
    - period="60d": Yahoo Finance の5分足取得上限
    - interval="5m": 5分足
    - threads=False: レート制限対策
    """
    if not symbols:
        logging.error("Symbol list is empty.")
        return None

    logging.info(f"\n{'='*60}")
    logging.info("DOWNLOADING 5-MIN INTRADAY DATA")
    logging.info(f"{'='*60}")
    logging.info(f"Symbols: {len(symbols)}")
    logging.info(f"Period: 60 days, Interval: 5min")
    logging.info(f"Chunk size: {chunk_size}, Delay: {delay}s")
    logging.info(f"{'='*60}\n")

    all_data = []
    failed_symbols = []
    total_chunks = (len(symbols) + chunk_size - 1) // chunk_size

    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i + chunk_size]
        chunk_num = i // chunk_size + 1

        success = False
        for retry in range(max_retries):
            try:
                logging.info(f"Chunk {chunk_num}/{total_chunks} ({len(chunk)} symbols, retry {retry + 1})...")

                data = yf.download(
                    chunk,
                    period="60d",
                    interval="5m",
                    threads=False,
                    progress=False
                )

                if not data.empty:
                    all_data.append(data)
                    if len(chunk) > 1:
                        successful = data.columns.get_level_values(1).unique().tolist()
                    else:
                        successful = chunk
                    logging.info(f"✓ Chunk {chunk_num}: {len(successful)}/{len(chunk)} symbols, {len(data)} rows")
                    success = True
                    break
                else:
                    logging.warning(f"⚠ Chunk {chunk_num} returned empty data")

            except Exception as e:
                logging.error(f"✗ Chunk {chunk_num} error (retry {retry + 1}): {e}")
                if retry < max_retries - 1:
                    time.sleep(delay * 2)

        if not success:
            failed_symbols.extend(chunk)

        time.sleep(delay)

    if failed_symbols:
        logging.warning(f"\n⚠ {len(failed_symbols)} symbols failed")
        failed_path = os.path.join(DATA_FOLDER, "intraday", "failed_symbols.txt")
        with open(failed_path, 'w') as f:
            f.write('\n'.join(failed_symbols))
        logging.info(f"Failed symbols saved to: {failed_path}")

    if not all_data:
        logging.error("No data downloaded!")
        return None

    logging.info("\n✓ Merging chunks...")
    merged = pd.concat(all_data, axis=1)

    # 重複カラムを除去（同一銘柄が複数チャンクに入った場合）
    merged = merged.loc[:, ~merged.columns.duplicated()]

    logging.info(f"Final shape: {merged.shape}")
    logging.info(f"Datetime range: {merged.index.min()} to {merged.index.max()}")
    if hasattr(merged.columns, 'levels'):
        logging.info(f"Symbols: {len(merged.columns.get_level_values(1).unique())}")

    return merged


def save_data(data):
    """5分足データを pickle 保存"""
    os.makedirs(os.path.dirname(TEMP_5MIN_PKL), exist_ok=True)

    try:
        data.to_pickle(TEMP_5MIN_PKL)
        file_size_mb = os.path.getsize(TEMP_5MIN_PKL) / 1024 / 1024

        logging.info(f"\n{'='*60}")
        logging.info("✓ 5-MIN DATA SAVED")
        logging.info(f"{'='*60}")
        logging.info(f"Path: {TEMP_5MIN_PKL}")
        logging.info(f"Shape: {data.shape}")
        logging.info(f"Size: {file_size_mb:.2f} MB")
        logging.info(f"{'='*60}\n")

        return True
    except Exception as e:
        logging.error(f"Error saving: {e}")
        return False


def main():
    """5分足データ取得メイン処理"""
    symbols = get_symbols_from_csv()

    if not symbols:
        logging.error("No symbols found")
        return False

    # S&P500 も取得（ベンチマーク用途を想定）
    if '^GSPC' not in symbols:
        symbols.append('^GSPC')
        logging.info("Added ^GSPC (S&P 500)")

    data = download_5min_data(symbols, chunk_size=100, delay=2)

    if data is None:
        logging.error("Failed to download 5-min data")
        return False

    return save_data(data)


if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)

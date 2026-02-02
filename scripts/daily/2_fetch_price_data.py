"""
2_fetch_price_data.py

Yahoo Financeから直近1000日分の価格データを取得
既存のfetch_price_data2.pyのロジックを使用（チャンクダウンロード）
"""
import os
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import time
import logging

DATA_FOLDER = "data"
TARGET_STOCKS_CSV = os.path.join(DATA_FOLDER, "target_stocks_latest.csv")
TEMP_PRICE_PKL = os.path.join(DATA_FOLDER, "temp_prices.pkl")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_symbols_from_csv():
    """target_stocks_latest.csvから銘柄取得"""
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

def download_price_data(symbols, start_date, end_date=None, chunk_size=50, delay=1, max_retries=3):
    """
    チャンク単位でYahoo Financeからデータ取得
    既存のfetch_price_data2.pyと同じロジック
    """
    if not symbols or not start_date:
        logging.error("Symbol list or start date is empty.")
        return None

    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')

    logging.info(f"\n{'='*60}")
    logging.info("DOWNLOADING PRICE DATA")
    logging.info(f"{'='*60}")
    logging.info(f"Symbols: {len(symbols)}")
    logging.info(f"Period: {start_date} to {end_date}")
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
                    start=start_date,
                    end=end_date,
                    threads=False,
                    progress=False
                )
                
                if not data.empty:
                    all_data.append(data)
                    successful = data.columns.get_level_values(1).unique().tolist() if len(chunk) > 1 else chunk
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
        failed_path = os.path.join(DATA_FOLDER, 'failed_symbols.txt')
        with open(failed_path, 'w') as f:
            f.write('\n'.join(failed_symbols))
        logging.info(f"Failed symbols saved to: {failed_path}")

    if not all_data:
        logging.error("No data downloaded!")
        return None

    logging.info("\n✓ Merging chunks...")
    merged = pd.concat(all_data, axis=1)
    
    logging.info(f"Final shape: {merged.shape}")
    logging.info(f"Date range: {merged.index.min().date()} to {merged.index.max().date()}")
    logging.info(f"Symbols: {len(merged.columns.get_level_values(1).unique())}")
    
    return merged

def save_price_data(price_data):
    """価格データをpickle形式で保存"""
    try:
        price_data.to_pickle(TEMP_PRICE_PKL)
        file_size_mb = os.path.getsize(TEMP_PRICE_PKL) / 1024 / 1024
        
        logging.info(f"\n{'='*60}")
        logging.info("✓ PRICE DATA SAVED")
        logging.info(f"{'='*60}")
        logging.info(f"Path: {TEMP_PRICE_PKL}")
        logging.info(f"Shape: {price_data.shape}")
        logging.info(f"Size: {file_size_mb:.2f} MB")
        logging.info(f"{'='*60}\n")
        
        return True
    except Exception as e:
        logging.error(f"Error saving: {e}")
        return False

def main():
    """価格データ取得メイン処理"""
    symbols = get_symbols_from_csv()
    
    if not symbols:
        logging.error("No symbols found")
        return False
        
    # ★ 追加: S&P500を追加（RRS計算用）
    if '^GSPC' not in symbols:
        symbols.append('^GSPC')
        logging.info("Added ^GSPC (S&P 500) for RRS calculation")

    # 1000日前から取得
    start_date = (datetime.now() - timedelta(days=1000)).strftime('%Y-%m-%d')
    
    price_data = download_price_data(symbols, start_date, chunk_size=50, delay=1)
    
    if price_data is None:
        logging.error("Failed to download price data")
        return False
    
    return save_price_data(price_data)

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)

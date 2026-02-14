"""
1_fetch_historical_prices.py

yfinanceで過去価格データを取得（開始日指定可能）
出力: data/maintenance/temp_prices.pkl

使い方:
  python 1_fetch_historical_prices.py              # maxデータ取得
  python 1_fetch_historical_prices.py 2020-01-01  # 2020年以降のデータ取得
"""
import os
import sys
import pandas as pd
import yfinance as yf
import logging
import pickle
import time
from datetime import datetime

DATA_FOLDER = "data"
MAINTENANCE_FOLDER = os.path.join(DATA_FOLDER, "maintenance")
TARGET_STOCKS_CSV = os.path.join(DATA_FOLDER, "target_stocks_latest.csv")
OUTPUT_PKL = os.path.join(MAINTENANCE_FOLDER, "temp_prices.pkl")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def fetch_historical_prices(symbols, start_date=None, end_date=None, chunk_size=10, max_retries=3):
    """
    yfinanceで価格データを取得
    
    Args:
        symbols: 銘柄リスト
        start_date: 開始日（例: "2020-01-01"）None の場合は max
        end_date: 終了日（例: "2025-12-31"）
        chunk_size: 一度に取得する銘柄数
        max_retries: リトライ回数
    """
    if start_date:
        logging.info(f"Fetching price data: {start_date} to {end_date or 'today'}")
    else:
        logging.info(f"Fetching price data: MAX period to {end_date or 'today'}")
    
    logging.info(f"Target symbols: {len(symbols)}")
    logging.info(f"Chunk size: {chunk_size}")
    
    all_data = []
    successful_symbols = []
    failed_symbols = []
    
    # チャンクに分割
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i+chunk_size]
        chunk_num = i // chunk_size + 1
        total_chunks = (len(symbols) + chunk_size - 1) // chunk_size
        
        logging.info(f"Fetching chunk {chunk_num}/{total_chunks} ({len(chunk)} symbols)...")
        
        # リトライ機構
        for attempt in range(max_retries):
            try:
                chunk_data = {}
                
                for symbol in chunk:
                    try:
                        ticker = yf.Ticker(symbol)
                        
                        if start_date:
                            df = ticker.history(start=start_date, end=end_date)
                        else:
                            df = ticker.history(period="max", end=end_date)
                        
                        if not df.empty:
                            chunk_data[symbol] = df
                            successful_symbols.append(symbol)
                        else:
                            failed_symbols.append(symbol)
                    
                    except Exception as e:
                        logging.debug(f"  Failed {symbol}: {e}")
                        failed_symbols.append(symbol)
                
                # MultiIndex DataFrameに変換
                if chunk_data:
                    combined = pd.concat(chunk_data, axis=1)
                    all_data.append(combined)
                    logging.info(f"  ✓ Chunk {chunk_num}: {len(chunk_data)} symbols succeeded")
                else:
                    logging.warning(f"  ⚠ Chunk {chunk_num}: No data returned")
                
                break
                
            except Exception as e:
                if attempt < max_retries - 1:
                    logging.warning(f"  Chunk {chunk_num} attempt {attempt + 1} failed: {e}")
                    time.sleep(2)
                else:
                    logging.error(f"  Chunk {chunk_num} failed after {max_retries} attempts")
        
        time.sleep(0.5)
    
    # 全データ結合
    if all_data:
        final_df = pd.concat(all_data, axis=1)
        logging.info(f"✅ Successfully fetched {len(successful_symbols)} symbols")
        if failed_symbols:
            logging.warning(f"⚠️  Failed to fetch {len(failed_symbols)} symbols")
        return final_df
    else:
        logging.error("❌ No data fetched")
        return None

def main():
    logging.info("="*60)
    logging.info("FETCH HISTORICAL PRICES")
    logging.info("="*60)
    
    # コマンドライン引数から開始日を取得
    start_date = None
    if len(sys.argv) > 1:
        start_date = sys.argv[1]
        logging.info(f"Start date specified: {start_date}")
    
    # 銘柄リスト読み込み
    if not os.path.exists(TARGET_STOCKS_CSV):
        logging.error(f"Target stocks file not found: {TARGET_STOCKS_CSV}")
        return False
    
    target_stocks = pd.read_csv(TARGET_STOCKS_CSV)
    symbols = target_stocks['Symbol'].tolist()
    
    # S&P500インデックス追加
    symbols.append('^GSPC')
    
    logging.info(f"Total symbols to fetch: {len(symbols)}")
    
    # データ取得
    df = fetch_historical_prices(symbols, start_date=start_date)
    
    if df is None or df.empty:
        logging.error("Failed to fetch price data")
        return False
    
    # 保存
    os.makedirs(MAINTENANCE_FOLDER, exist_ok=True)
    
    with open(OUTPUT_PKL, 'wb') as f:
        pickle.dump(df, f)
    
    logging.info(f"Saved to: {OUTPUT_PKL}")
    logging.info(f"Data shape: {df.shape}")
    logging.info(f"Date range: {df.index[0]} to {df.index[-1]}")
    
    logging.info("="*60)
    logging.info("✅ Historical price data fetch complete!")
    logging.info("="*60)
    
    return True

if __name__ == "__main__":
    if main():
        sys.exit(0)
    else:
        sys.exit(1)

"""
1_fetch_historical_prices.py

yfinanceで過去最大期間の価格データを取得
出力: data/maintenance/temp_prices.pkl
"""
import os
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

def fetch_historical_prices_max(symbols, end_date, chunk_size=10, max_retries=3):
    """
    yfinanceで取得可能な最大期間の価格データを取得（安定版）
    
    Args:
        symbols: 銘柄リスト
        end_date: 終了日（例: "2024-12-31"）
        chunk_size: 一度に取得する銘柄数（デフォルト: 10）
        max_retries: リトライ回数（デフォルト: 3）
    """
    logging.info(f"Fetching price data: MAX period to {end_date}")
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
                # 個別銘柄で取得（エラー回避）
                chunk_data = {}
                
                for symbol in chunk:
                    try:
                        ticker = yf.Ticker(symbol)
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
                    # 各銘柄のDataFrameを結合
                    combined = pd.concat(chunk_data, axis=1)
                    all_data.append(combined)
                    logging.info(f"  ✓ Chunk {chunk_num}: {len(chunk_data)} symbols succeeded")
                else:
                    logging.warning(f"  ⚠ Chunk {chunk_num}: No data returned")
                
                break  # 成功したらリトライ不要
                
            except Exception as e:
                if attempt < max_retries - 1:
                    logging.warning(f"  Chunk {chunk_num} attempt {attempt+1} failed, retrying...")
                    time.sleep(2)
                else:
                    logging.error(f"  ✗ Chunk {chunk_num} failed after {max_retries} attempts: {e}")
    
    if len(all_data) == 0:
        raise ValueError("No data downloaded from any chunk")
    
    # 全チャンクを結合
    logging.info("Combining all chunks...")
    df = pd.concat(all_data, axis=1)
    
    logging.info(f"\n{'='*60}")
    logging.info(f"✅ Download completed")
    logging.info(f"{'='*60}")
    logging.info(f"Total symbols requested: {len(symbols)}")
    logging.info(f"Successful: {len(successful_symbols)}")
    logging.info(f"Failed: {len(failed_symbols)}")
    logging.info(f"Success rate: {len(successful_symbols)/len(symbols)*100:.1f}%")
    logging.info(f"Date range: {df.index.min()} to {df.index.max()}")
    logging.info(f"{'='*60}\n")
    
    return df

def main():
    """メイン処理"""
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--end', type=str, default='2024-12-31',
                       help='End date (YYYY-MM-DD)')
    args = parser.parse_args()
    
    logging.info("="*60)
    logging.info("STEP 1: FETCH HISTORICAL PRICES")
    logging.info("="*60)
    
    # 出力ディレクトリ作成
    os.makedirs(MAINTENANCE_FOLDER, exist_ok=True)
    
    # 銘柄リスト読み込み
    if not os.path.exists(TARGET_STOCKS_CSV):
        logging.error(f"Target stocks file not found: {TARGET_STOCKS_CSV}")
        return False
    
    df_stocks = pd.read_csv(TARGET_STOCKS_CSV)
    
    # シンボルリストを取得（クリーニング）
    symbols = []
    
    for _, row in df_stocks.iterrows():
        symbol = row['Symbol']
        
        # 無効なシンボルをスキップ
        if not isinstance(symbol, str) or not symbol.strip():
            continue
        
        symbol = symbol.strip()
        symbols.append(symbol)
    
    # S&P500を追加（RRS計算用）
    if '^GSPC' not in symbols:
        symbols.append('^GSPC')
    
    logging.info(f"Target symbols: {len(symbols)}")
    
    # 価格データ取得
    df = fetch_historical_prices_max(symbols, args.end)
    
    # Pickle形式で保存
    logging.info(f"Saving to {OUTPUT_PKL}...")
    with open(OUTPUT_PKL, 'wb') as f:
        pickle.dump(df, f)
    
    logging.info("="*60)
    logging.info("✅ STEP 1 COMPLETED!")
    logging.info(f"Output: {OUTPUT_PKL}")
    logging.info("="*60)
    
    return True

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)
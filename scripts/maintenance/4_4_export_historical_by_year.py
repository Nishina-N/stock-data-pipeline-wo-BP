"""
export_historical_by_year.py

指定年の historical data を JSON に export
- stocks/daily/core/{year}/{symbol}.json
- stocks/daily/indicators/standard/{year}/{symbol}.json

Usage:
  python export_historical_by_year.py --year 2024
"""
import os
import pickle
import json
import argparse
import logging
import pandas as pd
from pathlib import Path

DATA_FOLDER = "data"
MAINTENANCE_FOLDER = os.path.join(DATA_FOLDER, "maintenance")
INPUT_PKL = os.path.join(MAINTENANCE_FOLDER, "temp_prices_with_indicators.pkl")
TARGET_STOCKS_CSV = os.path.join(DATA_FOLDER, "target_stocks_latest.csv")

# RS/RRS データ
INPUT_RS_RAW = os.path.join(MAINTENANCE_FOLDER, "temp_rs_raw.pkl")
INPUT_RRS_RAW = os.path.join(MAINTENANCE_FOLDER, "temp_rrs_raw.pkl")
INPUT_RS_PERCENTILE = os.path.join(MAINTENANCE_FOLDER, "temp_rs_percentile.pkl")
INPUT_RRS_PERCENTILE = os.path.join(MAINTENANCE_FOLDER, "temp_rrs_percentile.pkl")

# 出力先
R2_OUTPUT = os.path.join(MAINTENANCE_FOLDER, "r2")
R2_STOCKS_CORE = os.path.join(R2_OUTPUT, "stocks", "daily", "core")
R2_STOCKS_INDICATORS = os.path.join(R2_OUTPUT, "stocks", "daily", "indicators", "standard")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def load_symbols_info():
    """銘柄情報を読み込み"""
    if not os.path.exists(TARGET_STOCKS_CSV):
        logging.error(f"Target stocks file not found: {TARGET_STOCKS_CSV}")
        return {}
    
    df = pd.read_csv(TARGET_STOCKS_CSV)
    
    symbols_info = {}
    for _, row in df.iterrows():
        symbol = row['Symbol']
        if not isinstance(symbol, str) or not symbol.strip():
            continue
        
        symbol = symbol.strip()
        symbols_info[symbol] = {
            'name': row.get('Company Name', symbol) if pd.notna(row.get('Company Name')) else symbol,
            'sector': row.get('Sector', 'N/A') if pd.notna(row.get('Sector')) else 'N/A',
            'industry': row.get('Industry', 'N/A') if pd.notna(row.get('Industry')) else 'N/A'
        }
    
    # ★ 追加: S&P500情報を追加（RRS計算用）
    if '^GSPC' not in symbols_info:
        symbols_info['^GSPC'] = {
            'name': 'S&P 500',
            'sector': 'Index',
            'industry': 'Index'
        }
        logging.info("Added ^GSPC (S&P 500) info")
    
    logging.info(f"Loaded info for {len(symbols_info)} symbols")
    return symbols_info

def export_year_data_optimized(df, year, symbols_info, rs_dict, rrs_dict, rs_percentile_dict, rrs_percentile_dict):
    """
    指定年のデータを export（最適化版）
    
    - .iterrows() → .values で高速化
    - 日付変換を一括処理
    - RS/RRS を事前に配列化
    - 価格データが全て null の銘柄はスキップ
    """
    import numpy as np
    
    logging.info(f"="*60)
    logging.info(f"EXPORTING YEAR: {year}")
    logging.info(f"="*60)
    
    # 指定年のデータをフィルタ
    year_data = df[df.index.year == year]
    
    if year_data.empty:
        logging.warning(f"No data for year {year}")
        return 0
    
    logging.info(f"Year {year}: {len(year_data)} days, {year_data.index.min()} to {year_data.index.max()}")
    
    # 出力ディレクトリ作成
    core_dir = os.path.join(R2_STOCKS_CORE, str(year))
    indicators_dir = os.path.join(R2_STOCKS_INDICATORS, str(year))
    os.makedirs(core_dir, exist_ok=True)
    os.makedirs(indicators_dir, exist_ok=True)
    
    # ★ 日付を一括変換（高速化）
    dates_str = year_data.index.strftime('%Y-%m-%d').tolist()
    dates_index = year_data.index
    
    symbols = df.columns.levels[0] if isinstance(df.columns, pd.MultiIndex) else [df.columns[0]]
    
    count = 0
    skipped_null = 0
    failed = []
    
    for symbol in symbols:
        # if symbol == '^GSPC':  # コメントアウト
        #     continue
        
        if symbol not in symbols_info:
            continue
        
        try:
            symbol_data = year_data[symbol]
            
            if symbol_data.empty:
                continue
            
            # ★ NumPy配列として取得（高速アクセス）
            open_vals = symbol_data['Open'].values
            high_vals = symbol_data['High'].values
            low_vals = symbol_data['Low'].values
            close_vals = symbol_data['Close'].values
            volume_vals = symbol_data['Volume'].values
            
            # ★ 価格データが全て null かチェック
            if (np.all(np.isnan(open_vals)) and 
                np.all(np.isnan(high_vals)) and 
                np.all(np.isnan(low_vals)) and 
                np.all(np.isnan(close_vals))):
                logging.debug(f"Skipping {symbol} for year {year}: All price data is null")
                skipped_null += 1
                continue
            
            sma20_vals = symbol_data['sma20'].values
            sma50_vals = symbol_data['sma50'].values
            sma200_vals = symbol_data['sma200'].values
            ema21_vals = symbol_data['ema21'].values
            rsi14_vals = symbol_data['rsi14'].values
            atr14_vals = symbol_data['atr14'].values
            vwap_vals = symbol_data['vwap'].values
            
            # ★ RS/RRS を事前に配列化（この銘柄の全日付分）
            rs_raw_vals = np.array([
                rs_dict.get(date, pd.Series()).get(symbol) if date in rs_dict else None
                for date in dates_index
            ])
            rrs_raw_vals = np.array([
                rrs_dict.get(date, pd.Series()).get(symbol) if date in rrs_dict else None
                for date in dates_index
            ])
            rs_percentile_vals = np.array([
                rs_percentile_dict.get(date, pd.Series()).get(symbol) if date in rs_percentile_dict else None
                for date in dates_index
            ])
            rrs_percentile_vals = np.array([
                rrs_percentile_dict.get(date, pd.Series()).get(symbol) if date in rrs_percentile_dict else None
                for date in dates_index
            ])
            
            # ★ リスト内包表記で一括変換（Core data）
            core_list = [
                {
                    'date': dates_str[i],
                    'open': None if np.isnan(open_vals[i]) else round(float(open_vals[i]), 2),
                    'high': None if np.isnan(high_vals[i]) else round(float(high_vals[i]), 2),
                    'low': None if np.isnan(low_vals[i]) else round(float(low_vals[i]), 2),
                    'close': None if np.isnan(close_vals[i]) else round(float(close_vals[i]), 2),
                    'volume': 0 if np.isnan(volume_vals[i]) else int(volume_vals[i]),
                    'rs_raw': None if (rs_raw_vals[i] is None or (isinstance(rs_raw_vals[i], float) and np.isnan(rs_raw_vals[i]))) else round(float(rs_raw_vals[i]), 2),
                    'rs_percentile': None if (rs_percentile_vals[i] is None or (isinstance(rs_percentile_vals[i], float) and np.isnan(rs_percentile_vals[i]))) else round(float(rs_percentile_vals[i]), 2),
                    'rrs_raw': None if (rrs_raw_vals[i] is None or (isinstance(rrs_raw_vals[i], float) and np.isnan(rrs_raw_vals[i]))) else round(float(rrs_raw_vals[i]), 2),
                    'rrs_percentile': None if (rrs_percentile_vals[i] is None or (isinstance(rrs_percentile_vals[i], float) and np.isnan(rrs_percentile_vals[i]))) else round(float(rrs_percentile_vals[i]), 2)
                }
                for i in range(len(dates_str))
            ]
            
            core_output = {
                'ticker': symbol,
                'name': symbols_info[symbol]['name'],
                'sector': symbols_info[symbol]['sector'],
                'industry': symbols_info[symbol]['industry'],
                'data': core_list
            }
            
            core_path = os.path.join(core_dir, f"{symbol}.json")
            with open(core_path, 'w') as f:
                json.dump(core_output, f)
            
            # ★ リスト内包表記で一括変換（Indicators data）
            indicator_list = [
                {
                    'date': dates_str[i],
                    'sma20': None if np.isnan(sma20_vals[i]) else round(float(sma20_vals[i]), 2),
                    'sma50': None if np.isnan(sma50_vals[i]) else round(float(sma50_vals[i]), 2),
                    'sma200': None if np.isnan(sma200_vals[i]) else round(float(sma200_vals[i]), 2),
                    'ema21': None if np.isnan(ema21_vals[i]) else round(float(ema21_vals[i]), 2),
                    'rsi14': None if np.isnan(rsi14_vals[i]) else round(float(rsi14_vals[i]), 2),
                    'atr14': None if np.isnan(atr14_vals[i]) else round(float(atr14_vals[i]), 2),
                    'vwap': None if np.isnan(vwap_vals[i]) else round(float(vwap_vals[i]), 2)
                }
                for i in range(len(dates_str))
            ]
            
            indicators_output = {
                'ticker': symbol,
                'indicators': ['sma20', 'sma50', 'sma200', 'ema21', 'rsi14', 'atr14', 'vwap'],
                'data': indicator_list
            }
            
            indicators_path = os.path.join(indicators_dir, f"{symbol}.json")
            with open(indicators_path, 'w') as f:
                json.dump(indicators_output, f)
            
            count += 1
            
            if count % 500 == 0:
                logging.info(f"  Progress: {count} symbols")
        
        except Exception as e:
            logging.error(f"Failed to export {symbol}: {e}")
            failed.append(symbol)
    
    logging.info(f"✅ Exported {count} symbols for year {year}")
    if skipped_null > 0:
        logging.info(f"⏭️  Skipped {skipped_null} symbols (all price data null)")
    if failed:
        logging.warning(f"⚠️  Failed: {len(failed)} symbols")
    
    return count

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--year', type=int, required=True, help='Year to export (e.g., 2024)')
    args = parser.parse_args()
    
    year = args.year
    
    logging.info("="*60)
    logging.info(f"EXPORT HISTORICAL DATA FOR YEAR {year}")
    logging.info("="*60)
    
    # データ読み込み
    if not os.path.exists(INPUT_PKL):
        logging.error(f"Input file not found: {INPUT_PKL}")
        return False
    
    logging.info(f"Loading data from {INPUT_PKL}...")
    with open(INPUT_PKL, 'rb') as f:
        df = pickle.load(f)
    
    logging.info(f"Loaded DataFrame: {df.shape}, {df.index.min()} to {df.index.max()}")
    
    # 銘柄情報読み込み
    symbols_info = load_symbols_info()
    
    # RS/RRS データ読み込み
    with open(INPUT_RS_RAW, 'rb') as f:
        rs_raw = pickle.load(f)
    with open(INPUT_RRS_RAW, 'rb') as f:
        rrs_raw = pickle.load(f)
    with open(INPUT_RS_PERCENTILE, 'rb') as f:
        rs_percentile = pickle.load(f)
    with open(INPUT_RRS_PERCENTILE, 'rb') as f:
        rrs_percentile = pickle.load(f)
    
    # DataFrameを辞書に変換（日付でアクセス）
    rs_dict = {date: rs_raw.loc[date] for date in rs_raw.index}
    rrs_dict = {date: rrs_raw.loc[date] for date in rrs_raw.index}
    rs_percentile_dict = {date: rs_percentile.loc[date] for date in rs_percentile.index}
    rrs_percentile_dict = {date: rrs_percentile.loc[date] for date in rrs_percentile.index}
    
    # Export
    count = export_year_data_optimized(df, year, symbols_info, rs_dict, rrs_dict, rs_percentile_dict, rrs_percentile_dict)
    
    if count > 0:
        logging.info("="*60)
        logging.info(f"✅ EXPORT COMPLETED FOR YEAR {year}")
        logging.info("="*60)
        return True
    else:
        logging.error(f"No data exported for year {year}")
        return False

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)
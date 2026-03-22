"""
2_export_to_json.py

5分足データ（OHLCV）を月別 JSON に変換

入力:
  - data/intraday/temp_5min.pkl

出力:
  - data/intraday/r2/stocks/intraday/5min/{year}/{month:02d}/{symbol}.json
"""
import os
import json
import pandas as pd
import logging
from collections import defaultdict

DATA_FOLDER = "data"
TEMP_5MIN_PKL = os.path.join(DATA_FOLDER, "intraday", "temp_5min.pkl")
R2_OUTPUT = os.path.join(DATA_FOLDER, "intraday", "r2")
R2_INTRADAY_5MIN = os.path.join(R2_OUTPUT, "stocks", "intraday", "5min")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def extract_ticker_data(df, ticker):
    """
    MultiIndex DataFrame から1銘柄分の OHLCV DataFrame を取得

    yfinance のデフォルト列構造: MultiIndex (field, ticker)
    例: ('Close', 'AAPL'), ('Open', 'AAPL'), ...
    """
    try:
        if isinstance(df.columns, pd.MultiIndex):
            ticker_df = df.xs(ticker, level=1, axis=1)
        else:
            # 単一銘柄の場合（MultiIndex なし）
            ticker_df = df.copy()

        # 必要カラムのみ保持
        required = ['Open', 'High', 'Low', 'Close', 'Volume']
        ticker_df = ticker_df[[c for c in required if c in ticker_df.columns]]

        # 全 NaN 行を除去
        ticker_df = ticker_df.dropna(how='all')

        return ticker_df

    except KeyError:
        return None


def build_monthly_records(ticker_df):
    """
    DataFrame を年月別にグループ化し、OHLCVレコードのリストを返す

    Returns:
        dict: {(year, month): [{'datetime': ..., 'open': ..., ...}, ...]}
    """
    monthly = defaultdict(list)

    # datetime index のタイムゾーンを除去（NYSE 現地時刻として扱う）
    if ticker_df.index.tz is not None:
        ticker_df = ticker_df.copy()
        ticker_df.index = ticker_df.index.tz_convert('America/New_York').tz_localize(None)

    for dt, row in zip(ticker_df.index, ticker_df.itertuples(index=False)):
        year = dt.year
        month = dt.month

        record = {
            'datetime': dt.strftime('%Y-%m-%dT%H:%M:%S'),
            'open':   round(float(row.Open),   4) if pd.notna(row.Open)   else None,
            'high':   round(float(row.High),   4) if pd.notna(row.High)   else None,
            'low':    round(float(row.Low),    4) if pd.notna(row.Low)    else None,
            'close':  round(float(row.Close),  4) if pd.notna(row.Close)  else None,
            'volume': int(row.Volume)              if pd.notna(row.Volume) else None,
        }
        monthly[(year, month)].append(record)

    return monthly


def export_ticker(df, ticker):
    """1銘柄分の月別 JSON ファイルを出力"""
    ticker_df = extract_ticker_data(df, ticker)

    if ticker_df is None or ticker_df.empty:
        return 0

    monthly = build_monthly_records(ticker_df)
    count = 0

    for (year, month), records in monthly.items():
        if not records:
            continue

        year_dir = os.path.join(R2_INTRADAY_5MIN, str(year), f"{month:02d}")
        os.makedirs(year_dir, exist_ok=True)

        output = {
            'ticker':   ticker,
            'interval': '5min',
            'year':     year,
            'month':    month,
            'timezone': 'America/New_York',
            'data':     records,
        }

        output_path = os.path.join(year_dir, f"{ticker}.json")
        with open(output_path, 'w') as f:
            json.dump(output, f)

        count += 1

    return count


def main():
    """JSON 変換メイン処理"""
    logging.info("=" * 60)
    logging.info("EXPORT 5-MIN DATA TO JSON (BY MONTH)")
    logging.info("=" * 60)

    if not os.path.exists(TEMP_5MIN_PKL):
        logging.error(f"5-min data not found: {TEMP_5MIN_PKL}")
        return False

    logging.info(f"Loading {TEMP_5MIN_PKL} ...")
    df = pd.read_pickle(TEMP_5MIN_PKL)
    logging.info(f"Loaded: shape={df.shape}")

    # 銘柄一覧取得
    if isinstance(df.columns, pd.MultiIndex):
        tickers = sorted(df.columns.get_level_values(1).unique().tolist())
    else:
        logging.error("Unexpected DataFrame structure (no MultiIndex)")
        return False

    logging.info(f"Tickers to export: {len(tickers)}")

    total_files = 0
    failed = []

    for i, ticker in enumerate(tickers, 1):
        try:
            n = export_ticker(df, ticker)
            total_files += n

            if i % 500 == 0:
                logging.info(f"  Progress: {i}/{len(tickers)} tickers, {total_files} files")

        except Exception as e:
            logging.error(f"Failed to export {ticker}: {e}")
            failed.append(ticker)

    logging.info("=" * 60)
    logging.info(f"✅ Exported {len(tickers) - len(failed)} tickers → {total_files} monthly files")
    if failed:
        logging.warning(f"⚠  Failed: {len(failed)} tickers: {failed[:10]}")
    logging.info("=" * 60)

    return total_files > 0


if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)

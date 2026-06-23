"""
3_calculate_rs.py

RS 計算（Individual / Sector / Industry）。
出力は percentile のみ。

※ RRS 計算は廃止。raw 値の出力も廃止（percentile のみ保持）。

出力ファイル（3種類）:
  - temp_rs_individual.json
  - temp_rs_sector.json
  - temp_rs_industry.json
"""
import json
import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.symbols import load_symbols_info

DATA_FOLDER = "data"
TARGET_STOCKS_CSV = os.path.join(DATA_FOLDER, "target_stocks_latest.csv")
TEMP_PRICE_JSON = os.path.join(DATA_FOLDER, "temp_prices.json")

TEMP_RS_INDIVIDUAL_JSON = os.path.join(DATA_FOLDER, "temp_rs_individual.json")
TEMP_RS_SECTOR_JSON = os.path.join(DATA_FOLDER, "temp_rs_sector.json")
TEMP_RS_INDUSTRY_JSON = os.path.join(DATA_FOLDER, "temp_rs_industry.json")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def calculate_individual_rs_vectorized(price_data, min_days=252):
    """Individual RS（生値）を計算"""
    logging.info("Calculating Individual RS (raw)...")

    close_dict = {}
    for symbol, info in price_data['symbols'].items():
        data = info['data']
        if len(data) < min_days:
            continue

        closes = [d['close'] for d in data if d['close'] is not None]
        dates = [d['date'] for d in data if d['close'] is not None]

        if len(closes) < min_days:
            continue

        close_dict[symbol] = pd.Series(closes, index=pd.to_datetime(dates))

    if not close_dict:
        logging.error("No sufficient data for RS calculation")
        return None

    df_close = pd.DataFrame(close_dict)

    ret_3m = df_close.pct_change(periods=63, fill_method=None) * 100
    ret_6m = df_close.pct_change(periods=126, fill_method=None) * 100
    ret_9m = df_close.pct_change(periods=189, fill_method=None) * 100
    ret_12m = df_close.pct_change(periods=252, fill_method=None) * 100

    rs_raw = (ret_3m * 0.4 + ret_6m * 0.2 + ret_9m * 0.2 + ret_12m * 0.2)

    logging.info(f"Calculated RS (raw) for {len(rs_raw.columns)} symbols, {len(rs_raw)} dates")
    return rs_raw

def calculate_percentiles_vectorized(df, name="data"):
    """パーセンタイル化（1-99）"""
    logging.info(f"Converting {name} to percentiles...")
    percentiles_df = df.rank(axis=1, pct=True) * 98 + 1
    logging.info(f"Converted {name} to percentiles: {percentiles_df.shape}")
    return percentiles_df

def calculate_group_rs_weighted(rs_df, symbols_info, price_data, group_key):
    """
    Sector / Industry の RS を加重平均（Close × Volume）で計算

    group_key: 'sector' or 'industry'
    """
    logging.info(f"Calculating {group_key} RS (weighted)...")

    # グループ別に銘柄をまとめる
    group_symbols = {}
    for symbol in rs_df.columns:
        if symbol not in symbols_info:
            continue
        group = symbols_info[symbol][group_key]
        if group and group != 'N/A':
            group_symbols.setdefault(group, []).append(symbol)

    # 重み（最新日の Close × Volume）
    weights = {}
    for symbol in rs_df.columns:
        weight = 1
        sym_data = price_data['symbols'].get(symbol, {}).get('data')
        if sym_data:
            latest = sym_data[-1]
            close_price = latest.get('close')
            volume = latest.get('volume')
            if close_price is not None and volume is not None:
                weight = close_price * volume
        weights[symbol] = weight

    group_rs_dict = {}
    for group, symbols in group_symbols.items():
        values = []
        for date in rs_df.index:
            weighted_sum = 0
            total_weight = 0
            for symbol in symbols:
                rs_value = rs_df.loc[date, symbol]
                if not pd.isna(rs_value):
                    w = weights.get(symbol, 1)
                    weighted_sum += rs_value * w
                    total_weight += w
            values.append(weighted_sum / total_weight if total_weight > 0 else np.nan)
        group_rs_dict[group] = pd.Series(values, index=rs_df.index)

    group_rs_df = pd.DataFrame(group_rs_dict)
    logging.info(f"Calculated {group_key} RS (raw) for {len(group_rs_df.columns)} groups")
    return group_rs_df

def save_individual_rs(rs_percentile, symbols_info, output_days=500):
    """Individual RS を保存（percentile のみ）"""
    rs_recent = rs_percentile.tail(output_days)

    output = []
    for date in rs_recent.index:
        values_at_date = rs_recent.loc[date].dropna()
        for symbol in rs_recent.columns:
            rs_value = rs_recent.loc[date, symbol]
            if pd.isna(rs_value):
                continue
            rank = int((values_at_date > rs_value).sum() + 1)
            output.append({
                'date': pd.Timestamp(date).strftime('%Y-%m-%d'),
                'ticker': symbol,
                'name': symbols_info.get(symbol, {}).get('name', symbol),
                'sector': symbols_info.get(symbol, {}).get('sector', 'N/A'),
                'industry': symbols_info.get(symbol, {}).get('industry', 'N/A'),
                'rs_percentile': round(float(rs_value), 2),
                'rank': rank
            })

    with open(TEMP_RS_INDIVIDUAL_JSON, 'w') as f:
        json.dump(output, f)
    logging.info(f"✅ Saved Individual RS: {len(output)} records")

def save_group_rs(group_rs_percentile, symbols_info, group_key, out_path, output_days=500):
    """Sector / Industry RS を保存（percentile のみ）"""
    recent = group_rs_percentile.tail(output_days)

    output = []
    for date in recent.index:
        values_at_date = recent.loc[date].dropna()
        for group in recent.columns:
            rs_value = recent.loc[date, group]
            if pd.isna(rs_value):
                continue
            rank = int((values_at_date > rs_value).sum() + 1)
            stock_count = sum(1 for info in symbols_info.values() if info.get(group_key) == group)

            record = {
                'date': pd.Timestamp(date).strftime('%Y-%m-%d'),
                group_key: group,
                'rs_percentile': round(float(rs_value), 2),
                'rank': rank,
                'stock_count': stock_count
            }

            if group_key == 'industry':
                # 業種が属するセクターを付与
                sector = 'N/A'
                for info in symbols_info.values():
                    if info.get('industry') == group:
                        sector = info.get('sector', 'N/A')
                        break
                record['sector'] = sector

            output.append(record)

    with open(out_path, 'w') as f:
        json.dump(output, f)
    logging.info(f"✅ Saved {group_key} RS: {len(output)} records")

def main():
    """RS 計算メイン処理"""
    logging.info("="*60)
    logging.info("RS CALCULATION (percentile only)")
    logging.info("="*60)

    if not os.path.exists(TEMP_PRICE_JSON):
        logging.error(f"Price data not found: {TEMP_PRICE_JSON}")
        return False

    with open(TEMP_PRICE_JSON, 'r') as f:
        price_data = json.load(f)

    logging.info(f"Loaded price data: {len(price_data['symbols'])} symbols")

    symbols_info = load_symbols_info(TARGET_STOCKS_CSV)
    if not symbols_info:
        logging.error("No symbols info found")
        return False

    # Individual RS
    rs_raw = calculate_individual_rs_vectorized(price_data, min_days=252)
    if rs_raw is None or rs_raw.empty:
        logging.error("Failed to calculate Individual RS")
        return False

    rs_percentile = calculate_percentiles_vectorized(rs_raw, "Individual RS")

    # Sector / Industry RS（percentile を加重平均 → 再パーセンタイル化）
    sector_rs_raw = calculate_group_rs_weighted(rs_percentile, symbols_info, price_data, 'sector')
    sector_rs_percentile = calculate_percentiles_vectorized(sector_rs_raw, "Sector RS")

    industry_rs_raw = calculate_group_rs_weighted(rs_percentile, symbols_info, price_data, 'industry')
    industry_rs_percentile = calculate_percentiles_vectorized(industry_rs_raw, "Industry RS")

    # 保存
    save_individual_rs(rs_percentile, symbols_info, output_days=500)
    save_group_rs(sector_rs_percentile, symbols_info, 'sector', TEMP_RS_SECTOR_JSON, output_days=500)
    save_group_rs(industry_rs_percentile, symbols_info, 'industry', TEMP_RS_INDUSTRY_JSON, output_days=500)

    logging.info("="*60)
    logging.info("✅ RS calculation completed!")
    logging.info("="*60)
    return True

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)

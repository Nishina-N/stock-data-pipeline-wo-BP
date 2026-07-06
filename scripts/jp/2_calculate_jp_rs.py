"""
2_calculate_jp_rs.py

日本株の RS（Individual / Sector / Industry）を計算する。
US の 3_calculate_rs.py と同一定義だが、フル履歴×全銘柄でも OOM しないよう
**pkl の価格行列から直接** float 行列（DataFrame）として計算し、結果も pkl 保存する
（巨大 JSON レコードは作らない）。

入力:  data/temp_prices_jp.pkl（1_fetch が保存する yfinance MultiIndex DataFrame）
       data/target_stocks_jp_latest.csv
出力:  data/temp_rs_individual_jp.pkl  (dates × code, rs_percentile 1-99)
       data/temp_rs_sector_jp.pkl      (dates × 17業種, rs_percentile)
       data/temp_rs_industry_jp.pkl    (dates × 33業種, rs_percentile)

RS 定義:
  individual raw = 3/6/9/12か月リターン(0.4/0.2/0.2/0.2 加重) → クロスセクション percentile(1-99)
  group     raw = individual percentile を Close×Volume 加重平均 → グループ間で再 percentile
"""
import os
import sys
import logging

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DATA_FOLDER = "data"
JP_CSV = os.path.join(DATA_FOLDER, "target_stocks_jp_latest.csv")
TEMP_PRICE_PKL = os.path.join(DATA_FOLDER, "temp_prices_jp.pkl")

OUT_INDIVIDUAL = os.path.join(DATA_FOLDER, "temp_rs_individual_jp.pkl")
OUT_SECTOR = os.path.join(DATA_FOLDER, "temp_rs_sector_jp.pkl")
OUT_INDUSTRY = os.path.join(DATA_FOLDER, "temp_rs_industry_jp.pkl")

MIN_DAYS = 252


def strip_t(col):
    return col[:-2] if isinstance(col, str) and col.endswith('.T') else col


def load_symbols_info_jp(csv_path=JP_CSV):
    df = pd.read_csv(csv_path, dtype={'Symbol': str})
    info = {}
    for _, row in df.iterrows():
        code = str(row['Symbol']).strip()
        info[code] = {
            'name': row.get('Company Name', code),
            'sector': row.get('Sector', 'N/A'),
            'industry': row.get('Industry', 'N/A'),
        }
    logging.info(f"Loaded info for {len(info)} symbols")
    return info


def to_code_matrix(price_data, field):
    """price_data[field] を pure-code 列の DataFrame に変換"""
    mat = price_data[field].copy()
    mat.columns = [strip_t(c) for c in mat.columns]
    return mat


def calc_individual_percentile(close, min_days=MIN_DAYS):
    """個別 RS percentile 行列（dates × code）"""
    logging.info("Calculating Individual RS (matrix)...")
    # min_days 未満しか有効終値が無い銘柄は除外（US と同じ方針）
    valid = close.count() >= min_days
    close = close.loc[:, valid[valid].index]
    logging.info(f"  symbols with >= {min_days} closes: {close.shape[1]}")

    ret_3m = close.pct_change(periods=63, fill_method=None) * 100
    ret_6m = close.pct_change(periods=126, fill_method=None) * 100
    ret_9m = close.pct_change(periods=189, fill_method=None) * 100
    ret_12m = close.pct_change(periods=252, fill_method=None) * 100
    rs_raw = ret_3m * 0.4 + ret_6m * 0.2 + ret_9m * 0.2 + ret_12m * 0.2

    pct = rs_raw.rank(axis=1, pct=True) * 98 + 1
    logging.info(f"  individual percentile: {pct.shape[0]} dates x {pct.shape[1]} symbols")
    return pct


def calc_group_percentile(indiv_pct, weights, groups_of, group_name):
    """
    グループ RS percentile 行列（dates × group）をベクトル化で計算。
    group_rs[date,g] = Σ_{s∈g} pct[date,s]*w[s] / Σ_{s∈g, pct非NaN} w[s]
    """
    logging.info(f"Calculating {group_name} RS (matrix, weighted)...")
    cols = indiv_pct.columns
    w = pd.Series({c: weights.get(c, 1.0) for c in cols})

    group_series = {}
    for g, members in groups_of.items():
        gcols = [c for c in members if c in indiv_pct.columns]
        if not gcols:
            continue
        sub = indiv_pct[gcols]
        wg = w[gcols]
        numer = sub.multiply(wg, axis=1).sum(axis=1, skipna=True)
        denom = sub.notna().multiply(wg, axis=1).sum(axis=1)
        group_series[g] = numer / denom.replace(0, np.nan)

    group_raw = pd.DataFrame(group_series)
    pct = group_raw.rank(axis=1, pct=True) * 98 + 1
    logging.info(f"  {group_name} percentile: {pct.shape[1]} groups")
    return pct


def main():
    logging.info("=" * 60)
    logging.info("JP RS CALCULATION (pkl matrix, streaming-safe)")
    logging.info("=" * 60)

    if not os.path.exists(TEMP_PRICE_PKL):
        logging.error(f"Price pkl not found: {TEMP_PRICE_PKL}")
        return False

    logging.info(f"Loading {TEMP_PRICE_PKL}...")
    price_data = pd.read_pickle(TEMP_PRICE_PKL)
    logging.info(f"  shape {price_data.shape}")

    info = load_symbols_info_jp()

    close = to_code_matrix(price_data, 'Close')
    volume = to_code_matrix(price_data, 'Volume')

    indiv_pct = calc_individual_percentile(close)

    # 重み = 最新日の Close × Volume（US と同じ）
    last_close = close.ffill().iloc[-1]
    last_vol = volume.ffill().iloc[-1]
    weights = {}
    for c in indiv_pct.columns:
        cp, vv = last_close.get(c), last_vol.get(c)
        weights[c] = float(cp * vv) if pd.notna(cp) and pd.notna(vv) and cp * vv > 0 else 1.0

    # グループ構成
    sectors_of, industries_of = {}, {}
    for code in indiv_pct.columns:
        meta = info.get(code)
        if not meta:
            continue
        s, ind = meta.get('sector'), meta.get('industry')
        if s and s != 'N/A' and s != '-':
            sectors_of.setdefault(s, []).append(code)
        if ind and ind != 'N/A' and ind != '-':
            industries_of.setdefault(ind, []).append(code)

    sector_pct = calc_group_percentile(indiv_pct, weights, sectors_of, 'sector')
    industry_pct = calc_group_percentile(indiv_pct, weights, industries_of, 'industry')

    indiv_pct.to_pickle(OUT_INDIVIDUAL)
    sector_pct.to_pickle(OUT_SECTOR)
    industry_pct.to_pickle(OUT_INDUSTRY)
    logging.info(f"✅ Saved RS matrices: individual({indiv_pct.shape}), "
                 f"sector({sector_pct.shape}), industry({industry_pct.shape})")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

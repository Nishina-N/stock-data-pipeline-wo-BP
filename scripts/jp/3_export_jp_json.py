"""
3_export_jp_json.py

日本株の価格(pkl) + RS(pkl 行列) から年別 JSON を生成する。
US の 4_export_to_json.py 相当だが、フル履歴×全銘柄でも OOM しないよう
**銘柄を1つずつストリーム**して core を書き出す（全銘柄の JSON を同時に保持しない）。

入力:  data/temp_prices_jp.pkl
       data/temp_rs_individual_jp.pkl / _sector_jp.pkl / _industry_jp.pkl
       data/target_stocks_jp_latest.csv
出力（data/jp/r2/ 配下。相対パス = R2 キー。全て jp/ プレフィックス）:
       jp/stocks/daily/core/{year}/{code}.json   : OHLCV + rs_percentile
       jp/scores/RS_scores/sector/{year}.json
       jp/scores/RS_scores/industry/{year}.json
       jp/metadata/last-updated.json
"""
import os
import sys
import json
import logging
from datetime import datetime
from collections import defaultdict

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DATA_FOLDER = "data"
JP_CSV = os.path.join(DATA_FOLDER, "target_stocks_jp_latest.csv")
TEMP_PRICE_PKL = os.path.join(DATA_FOLDER, "temp_prices_jp.pkl")
RS_INDIVIDUAL = os.path.join(DATA_FOLDER, "temp_rs_individual_jp.pkl")
RS_SECTOR = os.path.join(DATA_FOLDER, "temp_rs_sector_jp.pkl")
RS_INDUSTRY = os.path.join(DATA_FOLDER, "temp_rs_industry_jp.pkl")

R2_OUTPUT = os.path.join(DATA_FOLDER, "jp", "r2")
R2_STOCKS_CORE = os.path.join(R2_OUTPUT, "jp", "stocks", "daily", "core")
R2_SCORES_RS = os.path.join(R2_OUTPUT, "jp", "scores", "RS_scores")
R2_METADATA = os.path.join(R2_OUTPUT, "jp", "metadata")


def load_info(csv_path=JP_CSV):
    df = pd.read_csv(csv_path, dtype={'Symbol': str})
    info = {}
    for _, row in df.iterrows():
        code = str(row['Symbol']).strip()
        info[code] = {
            'name': row.get('Company Name', code),
            'sector': row.get('Sector', 'N/A'),
            'industry': row.get('Industry', 'N/A'),
        }
    return info


def export_core_streaming(price_data, indiv_pct, info):
    """銘柄を1つずつ処理して core/{year}/{code}.json を書き出す"""
    logging.info("Exporting JP core files (streaming per symbol)...")
    yf_symbols = price_data['Close'].columns
    count, failed = 0, []

    for yf_sym in yf_symbols:
        code = yf_sym[:-2] if isinstance(yf_sym, str) and yf_sym.endswith('.T') else yf_sym
        meta = info.get(code)
        if meta is None:
            continue
        try:
            df = pd.DataFrame({
                'open':   price_data['Open'][yf_sym],
                'high':   price_data['High'][yf_sym],
                'low':    price_data['Low'][yf_sym],
                'close':  price_data['Close'][yf_sym],
                'volume': price_data['Volume'][yf_sym],
            }).dropna(how='all')
            if df.empty:
                continue

            rs_series = indiv_pct[code] if code in indiv_pct.columns else None

            dates = df.index.strftime('%Y-%m-%d').tolist()
            years = df.index.year.tolist()
            o = np.round(df['open'].to_numpy(dtype=float), 2).tolist()
            h = np.round(df['high'].to_numpy(dtype=float), 2).tolist()
            l = np.round(df['low'].to_numpy(dtype=float), 2).tolist()
            c = np.round(df['close'].to_numpy(dtype=float), 2).tolist()
            v = df['volume'].to_numpy(dtype=float).tolist()
            if rs_series is not None:
                rs = rs_series.reindex(df.index).to_numpy(dtype=float)
                rs = [None if x != x else round(float(x), 2) for x in rs]
            else:
                rs = [None] * len(dates)

            rows_by_year = defaultdict(list)
            for j in range(len(dates)):
                rows_by_year[years[j]].append({
                    'date': dates[j],
                    'open': None if o[j] != o[j] else o[j],
                    'high': None if h[j] != h[j] else h[j],
                    'low':  None if l[j] != l[j] else l[j],
                    'close': None if c[j] != c[j] else c[j],
                    'volume': 0 if v[j] != v[j] else int(v[j]),
                    'rs_percentile': rs[j],
                })

            for year, rows in rows_by_year.items():
                year_dir = os.path.join(R2_STOCKS_CORE, str(year))
                os.makedirs(year_dir, exist_ok=True)
                out = {
                    'ticker': code,
                    'name': meta['name'],
                    'sector': meta['sector'],
                    'industry': meta['industry'],
                    'data': rows,
                }
                with open(os.path.join(year_dir, f"{code}.json"), 'w', encoding='utf-8') as f:
                    json.dump(out, f, ensure_ascii=False)

            count += 1
            if count % 500 == 0:
                logging.info(f"  progress: {count} symbols")
        except Exception as e:
            logging.error(f"Failed core for {code}: {e}")
            failed.append(code)

    logging.info(f"✅ Exported {count} symbols to jp/stocks/daily/core/")
    if failed:
        logging.warning(f"⚠️  Failed: {len(failed)} symbols")
    return count > 0


def export_group_scores(group_pct, group_key, info, out_dir):
    """percentile 行列(dates × group) から年別 scores JSON を書き出す"""
    logging.info(f"Exporting {group_key} scores (by year)...")
    os.makedirs(out_dir, exist_ok=True)

    stock_count = defaultdict(int)
    for meta in info.values():
        g = meta.get(group_key)
        if g and g != 'N/A' and g != '-':
            stock_count[g] += 1

    # industry -> その業種が属する sector（代表）
    sector_of_industry = {}
    if group_key == 'industry':
        for meta in info.values():
            ind, sec = meta.get('industry'), meta.get('sector')
            if ind and ind not in sector_of_industry:
                sector_of_industry[ind] = sec if sec else 'N/A'

    by_year = defaultdict(list)
    for date, row in group_pct.iterrows():
        valid = row.dropna()
        if valid.empty:
            continue
        date_str = pd.Timestamp(date).strftime('%Y-%m-%d')
        year = int(date_str[:4])
        for group, rs_value in valid.items():
            rank = int((valid > rs_value).sum() + 1)
            rec = {
                'date': date_str,
                group_key: group,
                'rs_percentile': round(float(rs_value), 2),
                'rank': rank,
                'stock_count': stock_count.get(group, 0),
            }
            if group_key == 'industry':
                rec['sector'] = sector_of_industry.get(group, 'N/A')
            by_year[year].append(rec)

    total = 0
    for year, recs in by_year.items():
        with open(os.path.join(out_dir, f"{year}.json"), 'w', encoding='utf-8') as f:
            json.dump(recs, f, ensure_ascii=False)
        total += len(recs)
    logging.info(f"✅ {group_key}: {total} records across {len(by_year)} years")


def export_metadata(indiv_pct, total_symbols):
    os.makedirs(R2_METADATA, exist_ok=True)
    dates = indiv_pct.dropna(how='all').index
    start = pd.Timestamp(dates.min()).strftime('%Y-%m-%d') if len(dates) else None
    end = pd.Timestamp(dates.max()).strftime('%Y-%m-%d') if len(dates) else None
    metadata = {
        'lastUpdated': datetime.now().isoformat(),
        'market': 'JP',
        'priceDataStartDate': start,
        'priceDataEndDate': end,
        'totalSymbols': int(total_symbols),
        'dataRetentionDays': int(len(dates)),
        'pipeline': {'version': '1.0.0', 'status': 'success',
                     'structure': 'year-based-archive-rs-only'},
    }
    with open(os.path.join(R2_METADATA, "last-updated.json"), 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    logging.info("✅ Exported metadata")


def main():
    logging.info("=" * 60)
    logging.info("EXPORT JP TO JSON (streaming from pkl)")
    logging.info("=" * 60)

    for p in (TEMP_PRICE_PKL, RS_INDIVIDUAL, RS_SECTOR, RS_INDUSTRY):
        if not os.path.exists(p):
            logging.error(f"Required input not found: {p}")
            return False

    logging.info("Loading pkl inputs...")
    price_data = pd.read_pickle(TEMP_PRICE_PKL)
    indiv_pct = pd.read_pickle(RS_INDIVIDUAL)
    sector_pct = pd.read_pickle(RS_SECTOR)
    industry_pct = pd.read_pickle(RS_INDUSTRY)
    info = load_info()
    logging.info(f"  price {price_data.shape}, indiv {indiv_pct.shape}, "
                 f"sector {sector_pct.shape}, industry {industry_pct.shape}")

    if not export_core_streaming(price_data, indiv_pct, info):
        return False

    export_group_scores(sector_pct, 'sector', info, os.path.join(R2_SCORES_RS, "sector"))
    export_group_scores(industry_pct, 'industry', info, os.path.join(R2_SCORES_RS, "industry"))
    export_metadata(indiv_pct, len(price_data['Close'].columns))

    logging.info("✅ All JP JSON files exported successfully!")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

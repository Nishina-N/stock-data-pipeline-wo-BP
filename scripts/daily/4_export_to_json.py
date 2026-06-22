"""
4_export_to_json.py

RS（individual/sector/industry）と価格データから年別 JSON を生成する。

※ RRS・indicators・raw 値の出力は廃止。
  - core は OHLCV + rs_percentile のみ
  - scores は RS のみ（percentile）
  - indicators 系統は出力しない（OHLCV から利用側で再計算する方針）

入力:
  - temp_prices.json
  - temp_rs_individual.json, temp_rs_sector.json, temp_rs_industry.json

出力:
  - stocks/daily/core/{year}/{symbol}.json      : OHLCV + rs_percentile
  - scores/RS_scores/individual/{year}.json
  - scores/RS_scores/sector/{year}.json
  - scores/RS_scores/industry/{year}.json
  - metadata/last-updated.json
"""
import json
import os
import logging
from datetime import datetime
from collections import defaultdict

DATA_FOLDER = "data"
TEMP_PRICE_JSON = os.path.join(DATA_FOLDER, "temp_prices.json")

TEMP_RS_INDIVIDUAL_JSON = os.path.join(DATA_FOLDER, "temp_rs_individual.json")
TEMP_RS_SECTOR_JSON = os.path.join(DATA_FOLDER, "temp_rs_sector.json")
TEMP_RS_INDUSTRY_JSON = os.path.join(DATA_FOLDER, "temp_rs_industry.json")

# R2アップロード用ディレクトリ
R2_OUTPUT = os.path.join(DATA_FOLDER, "daily", "r2")
R2_STOCKS_CORE = os.path.join(R2_OUTPUT, "stocks", "daily", "core")
R2_SCORES_RS = os.path.join(R2_OUTPUT, "scores", "RS_scores")
R2_METADATA = os.path.join(R2_OUTPUT, "metadata")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_rs_dict(rs_data):
    """RSデータを {date: {symbol: rs_percentile}} に変換"""
    rs_dict = defaultdict(dict)
    for item in rs_data:
        rs_dict[item['date']][item['ticker']] = item.get('rs_percentile')
    return rs_dict

def group_data_by_year(data_list, date_key='date'):
    """データを年別にグループ化"""
    year_groups = defaultdict(list)
    for item in data_list:
        year = int(item[date_key][:4])
        year_groups[year].append(item)
    return dict(year_groups)

def export_core_files(price_data, rs_dict):
    """core/{year}/{symbol}.json を年別に生成（OHLCV + rs_percentile）"""
    logging.info("Exporting core files (OHLCV + RS, by year)...")

    count = 0
    failed = []

    for symbol, info in price_data['symbols'].items():
        try:
            year_groups = group_data_by_year(info['data'])

            for year, year_data in year_groups.items():
                year_dir = os.path.join(R2_STOCKS_CORE, str(year))
                os.makedirs(year_dir, exist_ok=True)

                data_with_rs = []
                for data_point in year_data:
                    date = data_point['date']
                    rs_percentile = rs_dict.get(date, {}).get(symbol)
                    data_with_rs.append({
                        'date': date,
                        'open': data_point.get('open'),
                        'high': data_point.get('high'),
                        'low': data_point.get('low'),
                        'close': data_point.get('close'),
                        'volume': data_point.get('volume'),
                        'rs_percentile': rs_percentile,
                    })

                output = {
                    'ticker': symbol,
                    'name': info['name'],
                    'sector': info['sector'],
                    'industry': info['industry'],
                    'data': data_with_rs
                }

                with open(os.path.join(year_dir, f"{symbol}.json"), 'w') as f:
                    json.dump(output, f)

            count += 1
            if count % 500 == 0:
                logging.info(f"  Progress: {count} symbols")

        except Exception as e:
            logging.error(f"Failed to export core for {symbol}: {e}")
            failed.append(symbol)

    logging.info(f"✅ Exported {count} symbols to core/")
    if failed:
        logging.warning(f"⚠️  Failed: {len(failed)} symbols")

    return count > 0

def export_scores_by_year(score_data, output_dir, score_type):
    """scoresファイルを年別に生成"""
    logging.info(f"Exporting {score_type} scores (by year)...")

    if not score_data:
        logging.warning(f"No {score_type} data to export")
        return False

    os.makedirs(output_dir, exist_ok=True)

    year_groups = group_data_by_year(score_data)
    for year, data in year_groups.items():
        with open(os.path.join(output_dir, f"{year}.json"), 'w') as f:
            json.dump(data, f)
        logging.info(f"  ✅ {score_type} {year}: {len(data)} records")

    return True

def export_metadata(price_data, rs_individual_data):
    """メタデータJSONを生成"""
    os.makedirs(R2_METADATA, exist_ok=True)

    dates = sorted(set(item['date'] for item in rs_individual_data))

    metadata = {
        'lastUpdated': datetime.now().isoformat(),
        'priceDataStartDate': dates[0] if dates else None,
        'priceDataEndDate': dates[-1] if dates else None,
        'totalSymbols': len(price_data['symbols']),
        'dataRetentionDays': len(dates),
        'pipeline': {
            'version': '4.0.0',
            'status': 'success',
            'structure': 'year-based-archive-rs-only'
        }
    }

    with open(os.path.join(R2_METADATA, "last-updated.json"), 'w') as f:
        json.dump(metadata, f, indent=2)

    logging.info("✅ Exported metadata")
    return True

def load_json(path, label):
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    logging.warning(f"{label} not found: {path}")
    return []

def main():
    """JSON変換メイン処理"""
    logging.info("="*60)
    logging.info("EXPORT TO JSON (RS only)")
    logging.info("="*60)

    if not os.path.exists(TEMP_PRICE_JSON):
        logging.error(f"Price data not found: {TEMP_PRICE_JSON}")
        return False

    with open(TEMP_PRICE_JSON, 'r') as f:
        price_data = json.load(f)

    rs_individual_data = load_json(TEMP_RS_INDIVIDUAL_JSON, "RS Individual")
    rs_sector_data = load_json(TEMP_RS_SECTOR_JSON, "RS Sector")
    rs_industry_data = load_json(TEMP_RS_INDUSTRY_JSON, "RS Industry")

    logging.info(f"Loaded: {len(price_data['symbols'])} symbols")
    logging.info(f"Loaded: {len(rs_individual_data)} Individual RS records")
    logging.info(f"Loaded: {len(rs_sector_data)} Sector RS records")
    logging.info(f"Loaded: {len(rs_industry_data)} Industry RS records")

    rs_dict = create_rs_dict(rs_individual_data)

    if not export_core_files(price_data, rs_dict):
        logging.error("Failed to export core files")
        return False

    export_scores_by_year(rs_individual_data, os.path.join(R2_SCORES_RS, "individual"), "Individual RS")
    export_scores_by_year(rs_sector_data, os.path.join(R2_SCORES_RS, "sector"), "Sector RS")
    export_scores_by_year(rs_industry_data, os.path.join(R2_SCORES_RS, "industry"), "Industry RS")

    if not export_metadata(price_data, rs_individual_data):
        logging.error("Failed to export metadata")
        return False

    logging.info("="*60)
    logging.info("✅ All JSON files exported successfully!")
    logging.info("="*60)
    return True

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)

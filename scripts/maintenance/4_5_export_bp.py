"""
4_5_export_bp.py (高速化版)

BuyPressureデータをJSON形式でエクスポート
"""
import os
import pandas as pd
import numpy as np
import logging
import pickle
import json

DATA_FOLDER = "data"
MAINTENANCE_FOLDER = os.path.join(DATA_FOLDER, "maintenance")
TARGET_STOCKS_CSV = os.path.join(DATA_FOLDER, "target_stocks_latest.csv")

INPUT_BP_RAW = os.path.join(MAINTENANCE_FOLDER, "temp_bp_raw.pkl")
INPUT_SECTOR_BP_RAW = os.path.join(MAINTENANCE_FOLDER, "temp_sector_bp_raw.pkl")
INPUT_INDUSTRY_BP_RAW = os.path.join(MAINTENANCE_FOLDER, "temp_industry_bp_raw.pkl")

OUTPUT_BP_INDIVIDUAL = os.path.join(MAINTENANCE_FOLDER, "temp_bp_individual.json")
OUTPUT_BP_SECTOR = os.path.join(MAINTENANCE_FOLDER, "temp_bp_sector.json")
OUTPUT_BP_INDUSTRY = os.path.join(MAINTENANCE_FOLDER, "temp_bp_industry.json")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def export_individual_bp_fast(bp_raw):
    """Individual BuyPressureをJSON形式でエクスポート（高速版）"""
    logging.info("Exporting Individual BuyPressure to JSON (fast)...")
    
    # 一度にランク計算（各行ごとに降順でランク付け）
    ranks = bp_raw.rank(axis=1, method='min', ascending=False, na_option='keep')
    
    # DataFrameを長形式に変換
    bp_long = bp_raw.stack().reset_index()
    bp_long.columns = ['date', 'symbol', 'bp_raw']
    
    ranks_long = ranks.stack().reset_index()
    ranks_long.columns = ['date', 'symbol', 'rank']
    
    # 結合
    df = bp_long.merge(ranks_long, on=['date', 'symbol'])
    
    # 日付を文字列化
    df['date'] = df['date'].dt.strftime('%Y-%m-%d')
    
    # 数値を適切な型に変換
    df['bp_raw'] = df['bp_raw'].round(6)
    df['rank'] = df['rank'].astype(int)
    
    # 辞書リストに変換
    results = df.to_dict('records')
    
    logging.info(f"Exported {len(results)} individual BP records")
    return results

def export_sector_industry_bp_fast(bp_raw, category_type='sector'):
    """Sector/Industry BuyPressureをJSON形式でエクスポート（高速版）"""
    field_name = category_type.capitalize()
    logging.info(f"Exporting {field_name} BuyPressure to JSON (fast)...")
    
    # ランク計算
    ranks = bp_raw.rank(axis=1, method='min', ascending=False, na_option='keep')
    
    # stock_count計算（各行の非NaN数）
    stock_counts = bp_raw.notna().sum(axis=1)
    
    # 長形式に変換
    bp_long = bp_raw.stack().reset_index()
    bp_long.columns = ['date', category_type, 'bp_raw']
    
    ranks_long = ranks.stack().reset_index()
    ranks_long.columns = ['date', category_type, 'rank']
    
    # 結合
    df = bp_long.merge(ranks_long, on=['date', category_type])
    
    # stock_countを追加（日付でマージ）
    stock_count_df = pd.DataFrame({
        'date': stock_counts.index,
        'stock_count': stock_counts.values
    })
    df = df.merge(stock_count_df, on='date')
    
    # 日付を文字列化
    df['date'] = df['date'].dt.strftime('%Y-%m-%d')
    
    # 数値を適切な型に変換
    df['bp_raw'] = df['bp_raw'].round(6)
    df['rank'] = df['rank'].astype(int)
    df['stock_count'] = df['stock_count'].astype(int)
    
    # 辞書リストに変換
    results = df.to_dict('records')
    
    logging.info(f"Exported {len(results)} {category_type} BP records")
    return results

def main():
    logging.info("=" * 60)
    logging.info("Starting BuyPressure JSON Export (Fast Version)")
    logging.info("=" * 60)
    
    # 1. データ読み込み
    logging.info(f"Loading Individual BP from {INPUT_BP_RAW}...")
    with open(INPUT_BP_RAW, 'rb') as f:
        bp_raw = pickle.load(f)
    
    logging.info(f"Loading Sector BP from {INPUT_SECTOR_BP_RAW}...")
    with open(INPUT_SECTOR_BP_RAW, 'rb') as f:
        sector_bp_raw = pickle.load(f)
    
    logging.info(f"Loading Industry BP from {INPUT_INDUSTRY_BP_RAW}...")
    with open(INPUT_INDUSTRY_BP_RAW, 'rb') as f:
        industry_bp_raw = pickle.load(f)
    
    # 2. Individual BuyPressure エクスポート
    individual_data = export_individual_bp_fast(bp_raw)
    
    logging.info(f"Saving Individual BP to {OUTPUT_BP_INDIVIDUAL}...")
    with open(OUTPUT_BP_INDIVIDUAL, 'w') as f:
        json.dump(individual_data, f, indent=2)
    
    # 3. Sector BuyPressure エクスポート
    sector_data = export_sector_industry_bp_fast(sector_bp_raw, category_type='sector')
    
    logging.info(f"Saving Sector BP to {OUTPUT_BP_SECTOR}...")
    with open(OUTPUT_BP_SECTOR, 'w') as f:
        json.dump(sector_data, f, indent=2)
    
    # 4. Industry BuyPressure エクスポート
    industry_data = export_sector_industry_bp_fast(industry_bp_raw, category_type='industry')
    
    logging.info(f"Saving Industry BP to {OUTPUT_BP_INDUSTRY}...")
    with open(OUTPUT_BP_INDUSTRY, 'w') as f:
        json.dump(industry_data, f, indent=2)
    
    logging.info("=" * 60)
    logging.info("BuyPressure JSON Export Complete!")
    logging.info("=" * 60)
    
    # サマリー表示
    print("\n📊 Summary:")
    print(f"  Individual BP records: {len(individual_data)}")
    print(f"  Sector BP records: {len(sector_data)}")
    print(f"  Industry BP records: {len(industry_data)}")
    
    # サンプル表示
    if individual_data:
        print(f"\n📅 Sample Individual BP (latest 5):")
        for record in individual_data[-5:]:
            print(f"  {record['date']} {record['symbol']}: {record['bp_raw']:.3f} (rank {record['rank']})")

if __name__ == "__main__":
    main()

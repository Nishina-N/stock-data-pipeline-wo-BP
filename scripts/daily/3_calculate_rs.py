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
        if group and pd.notna(group) and group != 'N/A':
            group_symbols.setdefault(group, []).append(symbol)

    # 重み = **その日の** Close × Volume（時点重み）
    #
    # 🔴 2026-08-17 変更。以前は「最新日の Close × Volume」を全期間に当てていたが、
    #    これは歴史日付に将来の売買代金を当てる look-ahead だった。500日窓の
    #    日次運用では影響が小さくても、同じ定義で全期間（1988-）を再生成すると
    #    「1988年のセクターRS を、2026年までに最大になった銘柄の売買代金で
    #    重み付けする」ことになる。
    #    scripts/maintenance/regenerate_rs_scores_full.py の
    #    --weight-mode pointintime と**同一定義**にしてある。
    #    片方だけ変えると当年の境目で系列の意味が変わるので、必ず両方直すこと。
    dv = {}
    for symbol in rs_df.columns:
        sym_data = price_data['symbols'].get(symbol, {}).get('data')
        if not sym_data:
            continue
        s = {}
        for r in sym_data:
            c, v = r.get('close'), r.get('volume')
            if c is not None and v is not None:
                s[r['date']] = c * v
        if s:
            dv[symbol] = pd.Series(s)
    weight_df = pd.DataFrame(dv)
    if not weight_df.empty:
        weight_df.index = pd.to_datetime(weight_df.index)
    weight_df = weight_df.reindex(index=rs_df.index, columns=rs_df.columns)

    # numer = Σ_{s∈g} rs[d,s] * w[d,s] 、denom = Σ_{s∈g} w[d,s]
    #   rs か w のどちらかが欠けている銘柄はその日だけ分子・分母とも除外する
    #   （重み1で混ぜると売買代金加重の中に等加重が紛れて定義が濁る）
    #   denom==0（該当銘柄0件）→ NaN → その日の順位付けに参加しない
    group_rs_dict = {}
    for group, symbols in group_symbols.items():
        sub = rs_df[symbols]
        wg = weight_df[symbols]
        valid = sub.notna() & wg.notna()
        numer = (sub * wg).where(valid).sum(axis=1)
        denom = wg.where(valid).sum(axis=1)
        group_rs_dict[group] = numer / denom.replace(0, np.nan)

    group_rs_df = pd.DataFrame(group_rs_dict)
    logging.info(f"Calculated {group_key} RS (raw) for {len(group_rs_df.columns)} groups")
    return group_rs_df

def save_individual_rs(rs_percentile, symbols_info, output_days=500):
    """Individual RS を保存（percentile のみ）"""
    rs_recent = rs_percentile.tail(output_days)

    # rank をベクトル化: 「自分より大きい値の個数 + 1」は
    # rank(ascending=False, method='min') とタイ処理含め完全一致
    rank_df = rs_recent.rank(axis=1, ascending=False, method='min')

    # メタデータをループ外で確定（レコード毎の dict 引き直しを避ける）
    meta = {
        s: (symbols_info.get(s, {}).get('name', s),
            symbols_info.get(s, {}).get('sector', 'N/A'),
            symbols_info.get(s, {}).get('industry', 'N/A'))
        for s in rs_recent.columns
    }

    output = []
    columns = rs_recent.columns
    for date, row in rs_recent.iterrows():
        date_str = pd.Timestamp(date).strftime('%Y-%m-%d')
        rank_row = rank_df.loc[date]
        vals = row.to_numpy()
        ranks = rank_row.to_numpy()
        for i, symbol in enumerate(columns):
            rs_value = vals[i]
            if rs_value != rs_value:  # NaN
                continue
            name, sector, industry = meta[symbol]
            output.append({
                'date': date_str,
                'ticker': symbol,
                'name': name,
                'sector': sector,
                'industry': industry,
                'rs_percentile': round(float(rs_value), 2),
                'rank': int(ranks[i])
            })

    with open(TEMP_RS_INDIVIDUAL_JSON, 'w') as f:
        json.dump(output, f)
    logging.info(f"✅ Saved Individual RS: {len(output)} records")

def save_group_rs(group_rs_percentile, symbols_info, group_key, out_path, output_days=500):
    """Sector / Industry RS を保存（percentile のみ）"""
    recent = group_rs_percentile.tail(output_days)

    # rank をベクトル化（save_individual_rs と同じ同値変換）
    rank_df = recent.rank(axis=1, ascending=False, method='min')

    # stock_count / industry→sector 対応をループ外で一度だけ構築
    # （旧実装はレコード毎に全 symbols_info を走査していた。値は同一）
    stock_count = {}
    for info in symbols_info.values():
        g = info.get(group_key)
        if g is not None:
            stock_count[g] = stock_count.get(g, 0) + 1

    sector_of_industry = {}
    if group_key == 'industry':
        # 旧実装の「最初に見つかった sector」と同じ選定（挿入順で最初を保持）
        for info in symbols_info.values():
            ind = info.get('industry')
            if ind is not None and ind not in sector_of_industry:
                sector_of_industry[ind] = info.get('sector', 'N/A')

    output = []
    columns = recent.columns
    for date, row in recent.iterrows():
        date_str = pd.Timestamp(date).strftime('%Y-%m-%d')
        rank_row = rank_df.loc[date]
        vals = row.to_numpy()
        ranks = rank_row.to_numpy()
        for i, group in enumerate(columns):
            rs_value = vals[i]
            if rs_value != rs_value:  # NaN
                continue
            record = {
                'date': date_str,
                group_key: group,
                'rs_percentile': round(float(rs_value), 2),
                'rank': int(ranks[i]),
                'stock_count': stock_count.get(group, 0)
            }
            if group_key == 'industry':
                record['sector'] = sector_of_industry.get(group, 'N/A')
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

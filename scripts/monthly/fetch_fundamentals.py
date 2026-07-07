"""
fetch_fundamentals.py

FMP stable API から「四半期」財務データを取得する（period=quarter のみ。TTM/annual は使わない）。
すべて当該四半期に帰属する値のみを格納し、将来情報のリークを避ける。

格納フィールドと定義（すべて period=quarter 由来）:
  date               会計四半期末日
  eps / epsDiluted   当四半期の基本 / 希薄化EPS（フロー）
  revenue            当四半期 売上（フロー）
  netIncome          当四半期 純利益（フロー）
  operatingCashFlow  当四半期 営業CF（フロー）
  freeCashFlow       当四半期 FCF（フロー）
  stockholdersEquity 期末 自己資本（スナップショット）
  bookValuePerShare  期末 BPS = 自己資本/株式数（スナップショット）
  roeQuarterly       生の四半期ROE(%) = netIncome / stockholdersEquity × 100
  roe                年率ROE(%)       = roeQuarterly × 4
  roicQuarterly      生の四半期ROIC(%) = FMP returnOnInvestedCapital × 100（単一四半期スケール）
  roic               年率ROIC(%)       = roicQuarterly × 4
  earningsDate       決算発表日（情報公開日 = point-in-time 用。stable/earnings 由来）
  epsActual/epsEstimated/epsSurprisePct    当四半期のEPS実績/予想/サプライズ率(%)
  revenueEstimated/revenueSurprisePct      当四半期の売上予想/サプライズ率(%)

年率化(×4)は単一四半期を4倍する規約（TTM合算ではない＝リーク無し）。ROE と ROIC で単位統一。

廃止: priceToSalesRatio（2026-07-08）。stable quarterly ratios の P/S は分母が単一四半期売上で
標準P/Sの約4倍・季節歪みがあり誤解を生むため保存しない。P/S が必要なら利用側で
marketCap ÷（直近4四半期 revenue 合算）で算出する。

FMP stable API 使用（2025-08-31 以降の新プランは legacy /api/v3 が 403 になるため）。
財務3表・key-metrics・ratios・earnings はすべて /stable、symbol はクエリパラメータ。
"""
import os
import argparse
import requests
import json
import logging
from bisect import bisect_right
from datetime import datetime
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time

load_dotenv()

API_KEY = os.getenv('FMP_API_KEY')
BASE_URL = "https://financialmodelingprep.com/stable"

DATA_FOLDER = "data"
TARGET_STOCKS_CSV = os.path.join(DATA_FOLDER, "target_stocks_latest.csv")
TEMP_FUNDAMENTALS_JSON = os.path.join(DATA_FOLDER, "temp_fundamentals.json")

START_DATE = '2000-01-01'
QUARTER_LIMIT = 120
# レート制限回避のため既定は控えめ（並列3・銘柄ごと0.5秒ウェイト）。
# フルフェッチはこの既定で十分ゆっくり。CLI で上書き可。
MAX_WORKERS = 3
REQUEST_DELAY = 0.5

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_session():
    """HTTPセッション作成"""
    session = requests.Session()
    
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,
        pool_maxsize=20
    )
    
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    return session

SESSION = create_session()

def fetch_income_statement(symbol, session=None, limit=QUARTER_LIMIT):
    """損益計算書取得"""
    if session is None:
        session = SESSION
    
    url = f"{BASE_URL}/income-statement"
    params = {'symbol': symbol, 'period': 'quarter', 'limit': limit, 'apikey': API_KEY}

    try:
        response = session.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        data_sorted = sorted(data, key=lambda x: x.get('date', ''))

        return {
            'dates': [item.get('date') for item in data_sorted],
            'eps': [item.get('eps') for item in data_sorted],
            'epsDiluted': [item.get('epsDiluted') for item in data_sorted],
            'revenue': [item.get('revenue') for item in data_sorted],
            'netIncome': [item.get('netIncome') for item in data_sorted]
        }
    except:
        return None

def fetch_cash_flow_statement(symbol, session=None, limit=QUARTER_LIMIT):
    """キャッシュフロー計算書取得"""
    if session is None:
        session = SESSION
    
    url = f"{BASE_URL}/cash-flow-statement"
    params = {'symbol': symbol, 'period': 'quarter', 'limit': limit, 'apikey': API_KEY}
    
    try:
        response = session.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        data_sorted = sorted(data, key=lambda x: x.get('date', ''))
        
        return {
            'dates': [item.get('date') for item in data_sorted],
            'freeCashFlow': [item.get('freeCashFlow') for item in data_sorted],
            'operatingCashFlow': [item.get('operatingCashFlow') for item in data_sorted]
        }
    except:
        return None

def fetch_balance_sheet(symbol, session=None, limit=QUARTER_LIMIT):
    """貸借対照表取得"""
    if session is None:
        session = SESSION
    
    url = f"{BASE_URL}/balance-sheet-statement"
    params = {'symbol': symbol, 'period': 'quarter', 'limit': limit, 'apikey': API_KEY}
    
    try:
        response = session.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        data_sorted = sorted(data, key=lambda x: x.get('date', ''))
        
        return {
            'dates': [item.get('date') for item in data_sorted],
            'stockholdersEquity': [item.get('totalStockholdersEquity') for item in data_sorted]
        }
    except:
        return None

def fetch_key_metrics(symbol, session=None, limit=QUARTER_LIMIT):
    """主要指標取得（ROIC）。stable では roic が returnOnInvestedCapital に改称。"""
    if session is None:
        session = SESSION

    url = f"{BASE_URL}/key-metrics"
    params = {'symbol': symbol, 'period': 'quarter', 'limit': limit, 'apikey': API_KEY}

    try:
        response = session.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        data_sorted = sorted(data, key=lambda x: x.get('date', ''))

        return {
            'dates': [item.get('date') for item in data_sorted],
            # returnOnInvestedCapital は小数比率（例 0.58）。後段でパーセント換算する。
            'roic': [item.get('returnOnInvestedCapital') for item in data_sorted]
        }
    except:
        return None

def fetch_ratios(symbol, session=None, limit=QUARTER_LIMIT):
    """財務比率取得（BPS/PSR）。stable では key-metrics から ratios に移動。"""
    if session is None:
        session = SESSION

    url = f"{BASE_URL}/ratios"
    params = {'symbol': symbol, 'period': 'quarter', 'limit': limit, 'apikey': API_KEY}

    try:
        response = session.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        data_sorted = sorted(data, key=lambda x: x.get('date', ''))

        return {
            'dates': [item.get('date') for item in data_sorted],
            'bookValuePerShare': [item.get('bookValuePerShare') for item in data_sorted],
        }
    except:
        return None

def fetch_earnings(symbol, session=None, limit=QUARTER_LIMIT):
    """決算サプライズ取得（stable/earnings）。

    返す date は「決算発表日（announcement date）」で、財務3表の会計期末日とは異なる。
    epsActual/epsEstimated/revenueActual/revenueEstimated を保持し、後段で
    会計期末の各四半期に「その期を報告した発表」を突き合わせる。
    """
    if session is None:
        session = SESSION

    url = f"{BASE_URL}/earnings"
    params = {'symbol': symbol, 'limit': limit, 'apikey': API_KEY}

    try:
        response = session.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        data_sorted = sorted(data, key=lambda x: x.get('date', ''))

        return {
            'dates': [item.get('date') for item in data_sorted],
            'epsActual': [item.get('epsActual') for item in data_sorted],
            'epsEstimated': [item.get('epsEstimated') for item in data_sorted],
            'revenueActual': [item.get('revenueActual') for item in data_sorted],
            'revenueEstimated': [item.get('revenueEstimated') for item in data_sorted],
        }
    except:
        return None

def _build_earnings_pairs(earnings_data):
    """(announce_date, idx) を日付昇順で返す。ISO日付なので文字列ソート＝時系列。"""
    if not earnings_data or not earnings_data.get('dates'):
        return None
    pairs = sorted((d, i) for i, d in enumerate(earnings_data['dates']) if d)
    return pairs or None

def _match_earnings_idx(period_end, pairs, max_days=120):
    """会計期末 period_end を報告した決算発表（期末の直後・max_days以内の最初の発表）の idx。

    発表は会計期末の後（数週間〜2か月）に出るため、period_end より後で最初の発表を採る。
    """
    if not pairs:
        return None
    dates = [p[0] for p in pairs]
    j = bisect_right(dates, period_end)  # period_end より後で最初の発表
    if j >= len(pairs):
        return None
    adate, idx = pairs[j]
    try:
        pe = datetime.strptime(period_end, '%Y-%m-%d')
        ad = datetime.strptime(adate, '%Y-%m-%d')
    except (ValueError, TypeError):
        return None
    return idx if (ad - pe).days <= max_days else None

def merge_quarterly_data(income_data, cashflow_data, balance_data, metrics_data, ratios_data, earnings_data=None, start_date=START_DATE):
    """5つのデータソースをマージ"""
    if not all([income_data, cashflow_data, balance_data, metrics_data, ratios_data]):
        return None

    dates_income = set(income_data['dates'])
    dates_cashflow = set(cashflow_data['dates'])
    dates_balance = set(balance_data['dates'])
    dates_metrics = set(metrics_data['dates'])
    dates_ratios = set(ratios_data['dates'])

    common_dates = dates_income & dates_cashflow & dates_balance & dates_metrics & dates_ratios
    common_dates = sorted([d for d in common_dates if d >= start_date])

    if not common_dates:
        return None

    income_idx = {date: i for i, date in enumerate(income_data['dates'])}
    cashflow_idx = {date: i for i, date in enumerate(cashflow_data['dates'])}
    balance_idx = {date: i for i, date in enumerate(balance_data['dates'])}
    metrics_idx = {date: i for i, date in enumerate(metrics_data['dates'])}
    ratios_idx = {date: i for i, date in enumerate(ratios_data['dates'])}
    
    # ROE計算（当該四半期の純利益 / 当該四半期末の自己資本。将来リーク・TTM不使用）
    #   roeQuarterly = NI / 自己資本 × 100   … 生の四半期ROE(%)
    #   roe          = roeQuarterly × 4      … 年率ROE(%, ROIC と単位を揃える)
    roe_values = []      # 年率化(×4)
    roe_q_values = []    # 生の四半期
    for d in common_dates:
        net_income = income_data['netIncome'][income_idx[d]]
        equity = balance_data['stockholdersEquity'][balance_idx[d]]

        if equity and equity != 0 and net_income is not None:
            roe_q = (net_income / equity) * 100
            roe = roe_q * 4
        else:
            roe_q = None
            roe = None
        roe_values.append(roe)
        roe_q_values.append(roe_q)

    earnings_pairs = _build_earnings_pairs(earnings_data)

    result = []
    for i, d in enumerate(common_dates):
        # ROIC: FMP quarterly returnOnInvestedCapital は「単一四半期」の小数比率（TTMではない）。
        #   roicQuarterly = raw × 100          … 生の四半期ROIC(%)
        #   roic          = roicQuarterly × 4  … 年率ROIC(%, ROE と単位を揃える)
        roic_raw = metrics_data['roic'][metrics_idx[d]]
        roic_q = roic_raw * 100 if roic_raw is not None else None
        roic = roic_raw * 4 * 100 if roic_raw is not None else None

        # 決算サプライズ: この会計期末 d を報告した発表を突き合わせる（無ければ null）。
        earnings_date = eps_actual = eps_estimated = None
        revenue_estimated = eps_surprise_pct = revenue_surprise_pct = None
        eidx = _match_earnings_idx(d, earnings_pairs)
        if eidx is not None:
            earnings_date = earnings_data['dates'][eidx]
            eps_actual = earnings_data['epsActual'][eidx]
            eps_estimated = earnings_data['epsEstimated'][eidx]
            revenue_estimated = earnings_data['revenueEstimated'][eidx]
            rev_actual = earnings_data['revenueActual'][eidx]
            if eps_actual is not None and eps_estimated not in (None, 0):
                eps_surprise_pct = round((eps_actual - eps_estimated) / abs(eps_estimated) * 100, 2)
            if rev_actual is not None and revenue_estimated not in (None, 0):
                revenue_surprise_pct = round((rev_actual - revenue_estimated) / abs(revenue_estimated) * 100, 2)

        result.append({
            'date': d,
            'eps': income_data['eps'][income_idx[d]],
            'epsDiluted': income_data['epsDiluted'][income_idx[d]],
            'revenue': income_data['revenue'][income_idx[d]],
            'netIncome': income_data['netIncome'][income_idx[d]],
            'freeCashFlow': cashflow_data['freeCashFlow'][cashflow_idx[d]],
            'operatingCashFlow': cashflow_data['operatingCashFlow'][cashflow_idx[d]],
            'stockholdersEquity': balance_data['stockholdersEquity'][balance_idx[d]],
            'bookValuePerShare': ratios_data['bookValuePerShare'][ratios_idx[d]],
            'roeQuarterly': roe_q_values[i],   # 生の四半期ROE(%) = NI/自己資本×100
            'roe': roe_values[i],              # 年率ROE(%) = roeQuarterly×4
            'roicQuarterly': roic_q,           # 生の四半期ROIC(%)
            'roic': roic,                      # 年率ROIC(%) = roicQuarterly×4
            # 決算サプライズ（announcement 基準）。earningsDate はバックテストの
            # point-in-time（情報公開日）判定に使える。
            'earningsDate': earnings_date,
            'epsActual': eps_actual,
            'epsEstimated': eps_estimated,
            'epsSurprisePct': eps_surprise_pct,
            'revenueEstimated': revenue_estimated,
            'revenueSurprisePct': revenue_surprise_pct,
        })

    return result

def fetch_fundamental_data(symbol, session=None):
    """指定銘柄の財務データ取得"""
    if session is None:
        session = SESSION
    
    income_data = fetch_income_statement(symbol, session)
    if not income_data:
        return None
    
    cashflow_data = fetch_cash_flow_statement(symbol, session)
    if not cashflow_data:
        return None
    
    balance_data = fetch_balance_sheet(symbol, session)
    if not balance_data:
        return None
    
    metrics_data = fetch_key_metrics(symbol, session)
    if not metrics_data:
        return None

    ratios_data = fetch_ratios(symbol, session)
    if not ratios_data:
        return None

    # 決算サプライズは任意。取得失敗してもファンダ本体は生成する（サプライズは null）。
    earnings_data = fetch_earnings(symbol, session)

    quarterly_data = merge_quarterly_data(income_data, cashflow_data, balance_data, metrics_data, ratios_data, earnings_data)

    if not quarterly_data:
        return None

    # レート制限回避: 銘柄処理ごとに軽くウェイト（並列ワーカー内で分散される）。
    if REQUEST_DELAY:
        time.sleep(REQUEST_DELAY)
    
    return {
        'ticker': symbol,
        'data': quarterly_data,
        'lastUpdated': datetime.now().isoformat()
    }

def load_target_stocks():
    """対象銘柄リスト取得"""
    if not os.path.exists(TARGET_STOCKS_CSV):
        logging.error(f"Target stocks file not found: {TARGET_STOCKS_CSV}")
        return []
    
    import pandas as pd
    df = pd.read_csv(TARGET_STOCKS_CSV)
    
    symbols = df['Symbol'].tolist()
    logging.info(f"Loaded {len(symbols)} symbols from CSV")
    
    return symbols

def main():
    """メイン処理"""
    global MAX_WORKERS, REQUEST_DELAY

    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=None, help='先頭N銘柄だけ取得（ドライラン用）')
    parser.add_argument('--workers', type=int, default=MAX_WORKERS, help=f'並列数（既定 {MAX_WORKERS}）')
    parser.add_argument('--delay', type=float, default=REQUEST_DELAY,
                        help=f'銘柄ごとのウェイト秒（既定 {REQUEST_DELAY}）')
    args = parser.parse_args()
    MAX_WORKERS = args.workers
    REQUEST_DELAY = args.delay

    logging.info("="*60)
    logging.info("FETCH FUNDAMENTAL DATA")
    logging.info("="*60)

    if not API_KEY:
        logging.error("FMP_API_KEY not found")
        return False

    symbols = load_target_stocks()

    # Core ETFs typically don't have standard fundamentals, so exclude them
    CORE_ETFS = ['DIA', 'SPY', 'SOXX', 'IWM', 'QQQ', '^GSPC']
    symbols = [s for s in symbols if s not in CORE_ETFS]

    if args.limit:
        symbols = symbols[:args.limit]
        logging.info(f"DRY-RUN: limited to first {len(symbols)} symbols")

    if not symbols:
        logging.error("No symbols found")
        return False

    fundamentals_dict = {}
    success_count = 0
    fail_count = 0

    logging.info(f"Fetching fundamental data for {len(symbols)} symbols...")
    logging.info(f"Parallel workers: {MAX_WORKERS}, per-symbol delay: {REQUEST_DELAY}s")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_fundamental_data, symbol): symbol for symbol in symbols}
        
        for future in as_completed(futures):
            symbol = futures[future]
            
            try:
                data = future.result()
                
                if data:
                    fundamentals_dict[symbol] = data
                    success_count += 1
                    logging.info(f"✓ {symbol}: {len(data['data'])} quarters")
                else:
                    fail_count += 1
                    logging.debug(f"✗ {symbol}: No data")
                
                if (success_count + fail_count) % 100 == 0:
                    logging.info(f"Progress: {success_count + fail_count}/{len(symbols)}")
                
            except Exception as e:
                fail_count += 1
                logging.error(f"✗ {symbol}: {e}")
    
    logging.info(f"\n{'='*60}")
    logging.info(f"Fetch completed: {success_count} success, {fail_count} failed")
    logging.info(f"{'='*60}")
    
    # 保存
    with open(TEMP_FUNDAMENTALS_JSON, 'w') as f:
        json.dump(fundamentals_dict, f)
    
    logging.info(f"✅ Saved fundamentals to {TEMP_FUNDAMENTALS_JSON}")
    logging.info(f"   Total symbols: {len(fundamentals_dict)}")
    
    return True

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)

"""
fetch_fundamentals.py

FMP APIから四半期財務データを取得
- EPS, Revenue, Net Income
- Free Cash Flow, Operating Cash Flow
- Stockholders Equity, BPS, PSR
- ROE（自動計算）
- ROIC（FMP key-metrics の returnOnInvestedCapital をパーセント換算して格納）

FMP stable API 使用（2025-08-31 以降の新プランは legacy /api/v3 が 403 になるため）。
- 財務3表・key-metrics・ratios はすべて /stable、symbol はクエリパラメータ
- BPS/PSR は /stable/ratios、ROIC は /stable/key-metrics の returnOnInvestedCapital
"""
import os
import requests
import json
import logging
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
MAX_WORKERS = 5

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
            'priceToSalesRatio': [item.get('priceToSalesRatio') for item in data_sorted]
        }
    except:
        return None

def merge_quarterly_data(income_data, cashflow_data, balance_data, metrics_data, ratios_data, start_date=START_DATE):
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
    
    # ROE計算
    roe_values = []
    for d in common_dates:
        net_income = income_data['netIncome'][income_idx[d]]
        equity = balance_data['stockholdersEquity'][balance_idx[d]]
        
        if equity and equity != 0 and net_income is not None:
            roe = (net_income / equity) * 4 * 100
        else:
            roe = None
        roe_values.append(roe)
    
    result = []
    for d in common_dates:
        # ROIC: FMP の returnOnInvestedCapital は四半期スケールの小数比率。
        # roe（四半期純利益/自己資本×4×100の年率%）と単位を揃えるため ×4×100 で年率化。
        roic_raw = metrics_data['roic'][metrics_idx[d]]
        roic = roic_raw * 4 * 100 if roic_raw is not None else None

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
            'priceToSalesRatio': ratios_data['priceToSalesRatio'][ratios_idx[d]],
            'roe': roe_values[common_dates.index(d)],
            'roic': roic
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

    quarterly_data = merge_quarterly_data(income_data, cashflow_data, balance_data, metrics_data, ratios_data)
    
    if not quarterly_data:
        return None
    
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
    
    if not symbols:
        logging.error("No symbols found")
        return False
    
    fundamentals_dict = {}
    success_count = 0
    fail_count = 0
    
    logging.info(f"Fetching fundamental data for {len(symbols)} symbols...")
    logging.info(f"Parallel workers: {MAX_WORKERS}")
    
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

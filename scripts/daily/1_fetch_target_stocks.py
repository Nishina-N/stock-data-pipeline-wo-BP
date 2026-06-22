"""
1_fetch_target_stocks.py

Financial Modeling Prep APIから対象銘柄を取得
既存のget_target_stocks.pyのロジックを使用
"""
import requests
import pandas as pd
from datetime import datetime, timedelta
import time
import logging
import re
import os
from dotenv import load_dotenv

# .envファイルを読み込む
load_dotenv()

# APIキーを設定
API_KEY = os.getenv('FMP_API_KEY')

DATA_FOLDER = "data"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 市場全体・主要指数・セクターETF
# フィルタリングで脱落させず、必ず最終CSVに含める「保証銘柄」。
# value = (Company Name, Sector, Industry)
# ※ Sector/Industry は 'N/A' とし、セクター/業種RSの集計には混ぜない
#    （個別RSと core OHLCV としては取得・保存される）
MARKET_SYMBOLS = {
    # 主要指数（Yahoo Finance ティッカー）
    '^GSPC': ('S&P 500', 'N/A', 'N/A'),
    '^IXIC': ('NASDAQ Composite', 'N/A', 'N/A'),
    '^DJI':  ('Dow Jones Industrial Average', 'N/A', 'N/A'),
    '^RUT':  ('Russell 2000', 'N/A', 'N/A'),
    # 主要ブロードETF
    'SPY':   ('SPDR S&P 500 ETF', 'N/A', 'N/A'),
    'QQQ':   ('Invesco QQQ Trust (NASDAQ100)', 'N/A', 'N/A'),
    'DIA':   ('SPDR Dow Jones Industrial Average ETF', 'N/A', 'N/A'),
    'IWM':   ('iShares Russell 2000 ETF', 'N/A', 'N/A'),
    'SMH':   ('VanEck Semiconductor ETF', 'N/A', 'N/A'),
    'SOXX':  ('iShares Semiconductor ETF', 'N/A', 'N/A'),
    # 11 セクター SPDR ETF
    'XLK':   ('Technology Select Sector SPDR', 'N/A', 'N/A'),
    'XLF':   ('Financial Select Sector SPDR', 'N/A', 'N/A'),
    'XLV':   ('Health Care Select Sector SPDR', 'N/A', 'N/A'),
    'XLE':   ('Energy Select Sector SPDR', 'N/A', 'N/A'),
    'XLI':   ('Industrial Select Sector SPDR', 'N/A', 'N/A'),
    'XLY':   ('Consumer Discretionary Select Sector SPDR', 'N/A', 'N/A'),
    'XLP':   ('Consumer Staples Select Sector SPDR', 'N/A', 'N/A'),
    'XLU':   ('Utilities Select Sector SPDR', 'N/A', 'N/A'),
    'XLB':   ('Materials Select Sector SPDR', 'N/A', 'N/A'),
    'XLRE':  ('Real Estate Select Sector SPDR', 'N/A', 'N/A'),
    'XLC':   ('Communication Services Select Sector SPDR', 'N/A', 'N/A'),
}

# 後方互換: IPO日チェックなどをバイパスする対象
CORE_ETFS = list(MARKET_SYMBOLS.keys())

def get_us_stocks():
    """NYSE・NASDAQ銘柄一覧を取得"""
    url = f"https://financialmodelingprep.com/api/v3/stock/list?apikey={API_KEY}"
    response = requests.get(url)
    data = response.json()
    return [s for s in data if s.get('exchangeShortName') in ['NYSE', 'NASDAQ']]

def is_common_stock_strict(symbol, name=""):
    """普通株式判定（厳密版）"""
    symbol_upper = symbol.upper()
    name_upper = name.upper() if name else ""
    
    if len(symbol_upper) < 1 or len(symbol_upper) > 5:
        return False
    
    if any(char in symbol_upper for char in ['.', '-', '/', ' ']):
        return False
    
    if any(char.isdigit() for char in symbol_upper):
        return False
    
    suspicious_endings = ['U', 'W', 'R']
    if len(symbol_upper) >= 5 and symbol_upper[-1] in suspicious_endings:
        return False
    
    if len(symbol_upper) == 5 and symbol_upper[-1] == 'X':
        return False
    
    exclude_names = [
        'ETF', 'FUND', 'TRUST', 'INDEX', 'REIT', 
        'UNIT', 'WARRANT', 'RIGHT', 'ACQUISITION',
        'SPAC', 'PREFERRED', 'NOTE', 'BOND',
        'BULL', 'BEAR', '2X', '3X', 'LEVERAGE', 
        'DIREXION', 'PROSHARES', 'ULTRA', 'INVERSE'
    ]
    if any(pattern in name_upper for pattern in exclude_names):
        return False
    
    return True

def is_old_ipo(ipo_date_str):
    """IPO2年以上経過判定"""
    if not ipo_date_str:
        return False
    try:
        ipo_date = datetime.strptime(ipo_date_str, '%Y-%m-%d')
        return ipo_date <= datetime.now() - timedelta(days=730)
    except:
        return False

def get_batch_quotes(symbols, batch_size=100):
    """バッチで株価を取得"""
    results = {}
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        symbols_str = ','.join(batch)
        url = f"https://financialmodelingprep.com/api/v3/quote/{symbols_str}?apikey={API_KEY}"
        
        try:
            response = requests.get(url, timeout=20)
            if response.status_code == 200:
                data = response.json()
                for item in data:
                    sym = item.get('symbol')
                    price = item.get('price')
                    if sym and price is not None and price > 0:
                        results[sym] = price
            time.sleep(0.15)
        except Exception as e:
            logger.error(f"バッチ取得エラー: {e}")
            time.sleep(1)
    
    return results

def get_batch_profiles(symbols, batch_size=3):
    """バッチでプロファイルを取得"""
    results = {}
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        
        for symbol in batch:
            url = f"https://financialmodelingprep.com/api/v3/profile/{symbol}?apikey={API_KEY}"
            try:
                response = requests.get(url, timeout=15)
                if response.status_code == 200:
                    data = response.json()
                    if data and len(data) > 0:
                        profile = data[0]
                        
                        is_active = profile.get('isActivelyTrading')
                        if is_active is False:
                            continue
                        
                        company_name = profile.get('companyName', '').upper()
                        delisting_keywords = ['OLD', 'DELISTED', 'DEFUNCT', 'BANKRUPTCY', 'LIQUIDATION']
                        delisting_pattern = r'\b(' + '|'.join(delisting_keywords) + r')\b'
                        
                        if re.search(delisting_pattern, company_name):
                            logger.info(f"{symbol}: 除外 - 社名に上場廃止関連キーワード検出")
                            continue
                        
                        exchange = profile.get('exchangeShortName', '')
                        if exchange not in ['NYSE', 'NASDAQ']:
                            continue
                        
                        results[symbol] = profile
                time.sleep(0.05)
            except:
                pass
    
    return results

def filter_stocks():
    """株式フィルタリング実行"""
    logger.info("NYSE・NASDAQ銘柄を取得中...")
    stocks = get_us_stocks()
    logger.info(f"取得完了: {len(stocks)}銘柄")
    
    logger.info("事前フィルタリング中...")
    pre_filtered = [s for s in stocks if s.get('symbol', '') in CORE_ETFS or is_common_stock_strict(s.get('symbol', ''), s.get('name', ''))]
    logger.info(f"フィルタリング後: {len(pre_filtered)}銘柄")
    
    logger.info("株価を一括取得中...")
    symbols = [s['symbol'] for s in pre_filtered]
    prices = get_batch_quotes(symbols, batch_size=100)
    logger.info(f"株価取得完了: {len(prices)}銘柄")
    
    price_filtered = [s for s in pre_filtered if s['symbol'] in prices]
    logger.info(f"株価取得済み銘柄: {len(price_filtered)}銘柄")
    
    logger.info("プロファイルを取得中...")
    filtered_symbols = [s['symbol'] for s in price_filtered]
    
    profiles = {}
    chunk_size = 50
    for i in range(0, len(filtered_symbols), chunk_size):
        chunk = filtered_symbols[i:i + chunk_size]
        chunk_profiles = get_batch_profiles(chunk, 3)
        profiles.update(chunk_profiles)
        
        if (i // chunk_size + 1) % 10 == 0:
            logger.info(f"進捗: {min(i + chunk_size, len(filtered_symbols))}/{len(filtered_symbols)}")
    
    logger.info(f"プロファイル取得完了: {len(profiles)}銘柄")
    
    logger.info("最終フィルタリング中...")
    filtered_stocks = []
    for stock in price_filtered:
        symbol = stock['symbol']
        if symbol in profiles and symbol in prices:
            profile = profiles[symbol]
            # Core ETFs bypass the IPO date check
            if symbol not in CORE_ETFS and not is_old_ipo(profile.get('ipoDate')):
                continue
            
            filtered_stocks.append({
                'Symbol': symbol,
                'Company Name': stock.get('name', ''),
                'Sector': profile.get('sector', ''),
                'Industry': profile.get('industry', ''),
                'Price': prices[symbol],
                'Market_Cap': profile.get('mktCap', 0),
                'IPO_Date': profile.get('ipoDate', ''),
                'Exchange': stock.get('exchangeShortName', '')
            })
    
    logger.info(f"条件通過: {len(filtered_stocks)}銘柄")
    
    return pd.DataFrame(filtered_stocks) if filtered_stocks else None

def inject_market_symbols(df):
    """
    主要指数・ブロードETF・セクターETF を必ず最終CSVに含める。
    通常のフィルタ結果に同一シンボルがあれば取り除き、保証行で上書きする。
    （価格・時価総額は yfinance 側で別途取得するため 0 でよい）
    """
    if df is not None and len(df) > 0:
        df = df[~df['Symbol'].isin(MARKET_SYMBOLS)]

    rows = []
    for symbol, (name, sector, industry) in MARKET_SYMBOLS.items():
        rows.append({
            'Symbol': symbol,
            'Company Name': name,
            'Sector': sector,
            'Industry': industry,
            'Price': 0,
            'Market_Cap': 0,
            'IPO_Date': '',
            'Exchange': 'INDEX/ETF'
        })

    market_df = pd.DataFrame(rows)
    combined = pd.concat([df, market_df], ignore_index=True) if df is not None else market_df
    logger.info(f"保証銘柄を注入: {len(market_df)}件（指数・ETF）")
    return combined

def main():
    """対象銘柄を取得してdata/target_stocks_latest.csvに保存"""
    if not API_KEY:
        logger.error("エラー: FMP_API_KEYが設定されていません")
        return False
    
    try:
        os.makedirs(DATA_FOLDER, exist_ok=True)
        
        logger.info("\n" + "="*60)
        logger.info("対象銘柄の取得を開始します")
        logger.info("="*60)
        
        df = filter_stocks()

        if df is None or len(df) == 0:
            logger.warning("通常銘柄の取得に失敗。保証銘柄（指数・ETF）のみで継続します")

        # 主要指数・ETF を必ず含める
        df = inject_market_symbols(df)

        if df is None or len(df) == 0:
            logger.error("銘柄の取得に失敗しました")
            return False

        output_path = os.path.join(DATA_FOLDER, 'target_stocks_latest.csv')
        df.to_csv(output_path, index=False, encoding='utf-8-sig')
        
        logger.info(f"\n✅ {len(df)}銘柄を {output_path} に保存しました")
        
        # セクター別集計
        sector_counts = df['Sector'].value_counts()
        logger.info(f"\nセクター別銘柄数（上位10）:")
        for sector, count in sector_counts.head(10).items():
            logger.info(f"  {sector}: {count}銘柄")
        
        return True
        
    except Exception as e:
        logger.error(f"予期しないエラー: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    import sys
    if main():
        sys.exit(0)
    else:
        sys.exit(1)

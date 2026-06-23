"""
market_symbols.py

市場全体・主要指数・セクターETF の「保証銘柄」定義（単一の真実の情報源）。

フィルタリングで脱落させず、必ず取得・保存する銘柄。
value = (Company Name, Sector, Industry)
※ Sector/Industry は 'N/A' とし、セクター/業種RSの集計には混ぜない
   （個別RS と core OHLCV としては取得・保存される）
"""

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

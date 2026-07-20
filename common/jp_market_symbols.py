"""
jp_market_symbols.py

日本株版の「保証銘柄」定義（common/market_symbols.py の JP 版）。
JPX ユニバース（内国株式のみ）には含まれない指数・ETF を、
daily core パイプラインに疑似ティッカーとして必ず含める。

value = (Company Name, Sector, Industry)
※ Sector/Industry は 'N/A' とし、セクター/業種RSの集計には混ぜない
   （US の MARKET_SYMBOLS と同じ規約）

yfinance シンボルの扱い:
  - '1306'（TOPIX ETF, NEXT FUNDS）は通常の JP コードと同じく取得時に '.T' を付与
  - '^N225'（日経225指数）は '^' 始まりなのでそのまま（.T を付けない）
  ※ TOPIX 指数そのもの（^TOPX 等）は yfinance に存在しないため、
     1306.T をプロキシとして採用（データは 2009-01-05〜）。
"""

JP_MARKET_SYMBOLS = {
    '1306':  ('NEXT FUNDS TOPIX Exchange Traded Fund', 'N/A', 'N/A'),
    '^N225': ('Nikkei 225', 'N/A', 'N/A'),
}

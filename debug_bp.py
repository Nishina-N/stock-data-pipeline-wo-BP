import pickle
import pandas as pd
import numpy as np

# データ読み込み
with open('data/maintenance/temp_prices_with_indicators.pkl', 'rb') as f:
    df = pickle.load(f)

# 1銘柄でテスト（例: AAPL）
symbol = 'AAPL'
symbol_df = df[symbol].copy()

print(f"Symbol: {symbol}")
print(f"Date range: {symbol_df.index[0]} to {symbol_df.index[-1]}")
print(f"Total days: {len(symbol_df)}")

# ATR計算
high = symbol_df['High']
low = symbol_df['Low']
close_prev = symbol_df['Close'].shift(1)

tr1 = high - low
tr2 = abs(high - close_prev)
tr3 = abs(low - close_prev)

tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
atr = tr.rolling(window=14).mean()

# 価格変動
price_change = symbol_df['Close'].diff()

# ATR × 0.3 以上の変動
threshold = atr * 0.3
significant_move = abs(price_change) >= threshold

print(f"\n最新30日のデータ:")
print(pd.DataFrame({
    'Close': symbol_df['Close'].tail(30),
    'Price_Change': price_change.tail(30),
    'ATR': atr.tail(30),
    'Threshold': threshold.tail(30),
    'Significant': significant_move.tail(30)
}))

# ドル出来高
dollar_volume = symbol_df['Close'] * symbol_df['Volume']

# 値上がり/値下がり
up_volume = np.where((price_change > 0) & significant_move, dollar_volume, 0)
down_volume = np.where((price_change < 0) & significant_move, dollar_volume, 0)

up_vol_sum = pd.Series(up_volume, index=symbol_df.index).rolling(window=20).sum()
down_vol_sum = pd.Series(down_volume, index=symbol_df.index).rolling(window=20).sum()

print(f"\n最新20日のup/down volume:")
print(pd.DataFrame({
    'Up_Vol': up_vol_sum.tail(20),
    'Down_Vol': down_vol_sum.tail(20),
    'Total': (up_vol_sum + down_vol_sum).tail(20)
}))

# BP計算
total_vol = up_vol_sum + down_vol_sum
bp = np.where(total_vol > 0, up_vol_sum / total_vol, np.nan)

print(f"\n最新10日のBP:")
print(pd.Series(bp, index=symbol_df.index).tail(10))

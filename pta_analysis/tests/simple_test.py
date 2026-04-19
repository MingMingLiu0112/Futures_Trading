import akshare as ak, pandas as pd, warnings
warnings.filterwarnings('ignore')

df = ak.futures_zh_minute_sina(symbol='TA0', period='1')
df.columns = [c.strip() for c in df.columns]
df['datetime'] = pd.to_datetime(df['datetime'])
df = df.sort_values('datetime').tail(800).reset_index(drop=True)
print('Loaded:', len(df), 'bars')
print('Time range:', df['datetime'].iloc[0], '~', df['datetime'].iloc[-1])

close = df['close']
ema_fast = close.ewm(span=12, adjust=False).mean()
ema_slow = close.ewm(span=26, adjust=False).mean()
dif = ema_fast - ema_slow
dea = dif.ewm(span=9, adjust=False).mean()
macd = (dif - dea) * 2
print('Latest MACD:', round(float(macd.iloc[-1]), 4))

low_n = df['low'].rolling(9).min()
high_n = df['high'].rolling(9).max()
rsv = (df['close'] - low_n) / (high_n - low_n) * 100
rsv = rsv.fillna(50)
K = rsv.ewm(com=3-1, adjust=False).mean()
D = K.ewm(com=3-1, adjust=False).mean()
J = 3 * K - 2 * D
print('Latest KDJ:', round(float(K.iloc[-1]), 1), round(float(D.iloc[-1]), 1), round(float(J.iloc[-1]), 1))

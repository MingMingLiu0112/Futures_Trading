#!/usr/bin/env python3
from tqsdk import TqApi, TqAuth, TqKq
import pandas as pd
import time
import sys

print("Starting...", flush=True)
sys.stdout.flush()

api = TqApi(TqKq(), auth=TqAuth('test', 'test'))
print("API created", flush=True)

klines = api.get_kline_serial('CZCE.TA509', 86400, data_length=300)
print("Requesting data...", flush=True)

# Wait for data
for i in range(15):
    time.sleep(1)
    if len(klines) > 100:
        print(f"Data loaded: {len(klines)} bars", flush=True)
        break

print("Processing...", flush=True)
df = klines.to_pandas()
df['datetime'] = pd.to_datetime(df['datetime'], unit='ns')
df = df.sort_values('datetime').reset_index(drop=True)

# Calculate MACD
close = df['close']
ema12 = close.ewm(span=12, adjust=False).mean()
ema26 = close.ewm(span=26, adjust=False).mean()
df['diff'] = ema12 - ema26
df['dea'] = df['diff'].ewm(span=9, adjust=False).mean()
df['macd'] = (df['diff'] - df['dea']) * 2

# Signals
df['goldencross'] = (df['diff'] > df['dea']) & (df['diff'].shift(1) <= df['dea'].shift(1))
df['deadcross'] = (df['diff'] < df['dea']) & (df['diff'].shift(1) >= df['dea'].shift(1))

goldens = df['goldencross'].sum()
deads = df['deadcross'].sum()

print(f"Period: {str(df.iloc[0]['datetime'])[:10]} ~ {str(df.iloc[-1]['datetime'])[:10]}", flush=True)
print(f"Bars: {len(df)}", flush=True)
print(f"Golden Crosses: {goldens}", flush=True)
print(f"Dead Crosses: {deads}", flush=True)

# Save
df.to_csv('/home/admin/.openclaw/workspace/codeman/pta_analysis/ta509_daily.csv', index=False)
print("Data saved to ta509_daily.csv", flush=True)

api.close()
print("Done!", flush=True)
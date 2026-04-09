#!/usr/bin/env python3
"""
PTA MACD策略回测 - CZCE.TA509
"""
from tqsdk import TqApi, TqAuth, TqKq
import pandas as pd
import time

print("=" * 60)
print("PTA MACD策略回测 - CZCE.TA509")
print("=" * 60)

api = TqApi(TqKq(), auth=TqAuth('test', 'test'))

# 获取日K线
print("\n[1] 获取日K线数据...")
klines = api.get_kline_serial('CZCE.TA509', 86400, data_length=300)

# 等待数据加载
for i in range(20):
    time.sleep(1)
    if len(klines) >= 100 and klines.iloc[-1]['close'] > 0:
        break
    print(f"    等待加载... {i+1}/20")

print(f"    加载完成: {len(klines)} 根K线")

# 转换为pandas DataFrame
df = pd.DataFrame(klines)
df['datetime'] = pd.to_datetime(df['datetime'], unit='ns')
df = df.sort_values('datetime').reset_index(drop=True)
df = df[df['close'] > 0]  # 过滤无效数据

start_date = str(df.iloc[0]['datetime'])[:10]
end_date = str(df.iloc[-1]['datetime'])[:10]

print(f"\n[2] 数据范围: {start_date} ~ {end_date}")
print(f"    有效K线: {len(df)} 根")

# 计算MACD
print("\n[3] 计算MACD指标...")
close = df['close']
ema12 = close.ewm(span=12, adjust=False).mean()
ema26 = close.ewm(span=26, adjust=False).mean()
df['diff'] = ema12 - ema26
df['dea'] = df['diff'].ewm(span=9, adjust=False).mean()
df['macd'] = (df['diff'] - df['dea']) * 2

# 交易信号
df['goldencross'] = (df['diff'] > df['dea']) & (df['diff'].shift(1) <= df['dea'].shift(1))
df['deadcross'] = (df['diff'] < df['dea']) & (df['diff'].shift(1) >= df['dea'].shift(1))

goldens = df['goldencross'].sum()
deads = df['deadcross'].sum()
print(f"    金叉信号: {goldens} 次")
print(f"    死叉信号: {deads} 次")

# 回测
print("\n[4] 执行回测...")
position = 0
trades = []
entry_price = 0
entry_date = None

for i in range(1, len(df)):
    if df['goldencross'].iloc[i] and position == 0:
        position = 1
        entry_price = df['close'].iloc[i]
        entry_date = df['datetime'].iloc[i]
    elif df['deadcross'].iloc[i] and position == 1:
        exit_price = df['close'].iloc[i]
        profit = (exit_price - entry_price) * 10  # PTA每手10吨
        trades.append({
            'entry_date': str(entry_date)[:10],
            'exit_date': str(df['datetime'].iloc[i])[:10],
            'entry_price': entry_price,
            'exit_price': exit_price,
            'profit': profit
        })
        position = 0

# 结果
print("\n" + "=" * 60)
print("回测结果")
print("=" * 60)
print(f"回测周期: {start_date} ~ {end_date}")
print(f"总K线数: {len(df)}")
print(f"总交易次数: {len(trades)}")

if trades:
    df_trades = pd.DataFrame(trades)
    total = df_trades['profit'].sum()
    wins = len(df_trades[df_trades['profit'] > 0])
    losses = len(df_trades[df_trades['profit'] <= 0])
    wr = wins / len(trades) * 100
    
    print(f"盈利次数: {wins}")
    print(f"亏损次数: {losses}")
    print(f"胜率: {wr:.1f}%")
    print(f"总收益: {total:.0f} 元")
    print(f"平均收益: {df_trades['profit'].mean():.0f} 元")
    print(f"最大盈利: {df_trades['profit'].max():.0f} 元")
    print(f"最大亏损: {df_trades['profit'].min():.0f} 元")
    
    print("\n交易明细:")
    for i, t in enumerate(trades, 1):
        p = f"+{t['profit']:.0f}" if t['profit'] >= 0 else f"{t['profit']:.0f}"
        print(f"  {i}. {t['entry_date']} -> {t['exit_date']}: {t['entry_price']} -> {t['exit_price']}, {p}元")
else:
    print("无交易信号!")

api.close()
print("\n完成!")
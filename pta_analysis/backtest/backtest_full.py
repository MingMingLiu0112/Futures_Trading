#!/usr/bin/env python3
"""
PTA MACD策略回测 - 使用TqSdk数据
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
loaded = False
for i in range(20):
    time.sleep(1)
    if len(klines) >= 100:
        # 检查是否有实际数据
        if klines.iloc[-1]['close'] > 0:
            loaded = True
            print(f"    数据加载完成: {len(klines)} 根K线")
            break
    print(f"    等待数据... ({i+1}/20)")

if not loaded:
    print("    数据加载超时!")
    api.close()
    exit(1)

# 转换数据
print("\n[2] 处理数据...")
df = klines.to_pandas()
df['datetime'] = pd.to_datetime(df['datetime'], unit='ns')
df = df[df['close'] > 0]  # 过滤无效数据
df = df.sort_values('datetime').reset_index(drop=True)

print(f"    有效K线: {len(df)} 根")
print(f"    时间范围: {str(df.iloc[0]['datetime'])[:10]} ~ {str(df.iloc[-1]['datetime'])[:10]}")

# 计算MACD
print("\n[3] 计算MACD指标...")
close = df['close']
ema12 = close.ewm(span=12, adjust=False).mean()
ema26 = close.ewm(span=26, adjust=False).mean()
df['diff'] = ema12 - ema26
df['dea'] = df['diff'].ewm(span=9, adjust=False).mean()
df['macd'] = (df['diff'] - df['dea']) * 2

# 生成交易信号
print("\n[4] 生成交易信号...")
df['goldencross'] = (df['diff'] > df['dea']) & (df['diff'].shift(1) <= df['dea'].shift(1))
df['deadcross'] = (df['diff'] < df['dea']) & (df['diff'].shift(1) >= df['dea'].shift(1))

goldens = df['goldencross'].sum()
deads = df['deadcross'].sum()
print(f"    金叉信号: {goldens} 次")
print(f"    死叉信号: {deads} 次")

# 模拟交易回测
print("\n[5] 模拟交易回测...")
position = 0
trades = []
entry_price = 0
entry_date = None

for i in range(1, len(df)):
    if df['goldencross'].iloc[i] and position == 0:
        # 金叉买入
        position = 1
        entry_price = df['close'].iloc[i]
        entry_date = df['datetime'].iloc[i]
    elif df['deadcross'].iloc[i] and position == 1:
        # 死叉卖出
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

# 统计分析
print("\n" + "=" * 60)
print("回测结果")
print("=" * 60)

if trades:
    df_trades = pd.DataFrame(trades)
    total_profit = df_trades['profit'].sum()
    win_count = len(df_trades[df_trades['profit'] > 0])
    loss_count = len(df_trades[df_trades['profit'] <= 0])
    win_rate = win_count / len(df_trades) * 100
    
    print(f"回测周期: {str(df.iloc[0]['datetime'])[:10]} ~ {str(df.iloc[-1]['datetime'])[:10]}")
    print(f"总交易次数: {len(trades)}")
    print(f"盈利次数: {win_count}")
    print(f"亏损次数: {loss_count}")
    print(f"胜率: {win_rate:.1f}%")
    print(f"总收益: {total_profit:.0f} 元")
    print(f"平均收益: {df_trades['profit'].mean():.0f} 元")
    print(f"最大单笔盈利: {df_trades['profit'].max():.0f} 元")
    print(f"最大单笔亏损: {df_trades['profit'].min():.0f} 元")
    
    print("\n交易明细:")
    for i, t in enumerate(trades, 1):
        profit_str = f"+{t['profit']:.0f}" if t['profit'] >= 0 else f"{t['profit']:.0f}"
        print(f"  {i}. {t['entry_date']} -> {t['exit_date']}: {t['entry_price']} -> {t['exit_price']}, 盈亏: {profit_str}元")
else:
    print("无交易信号!")

api.close()
print("\n回测完成!")
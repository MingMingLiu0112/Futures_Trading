#!/usr/bin/env python3
"""
PTA三维度策略回测 - 基于futures-trading skill
维度一：技术面（MACD + 成交量验证）
维度二：缠论简化版（分型停顿）
维度三：趋势确认（MA均线）
"""
from tqsdk import TqApi, TqAuth, TqKq
import pandas as pd
import numpy as np
import time

def calculate_indicators(df):
    """计算技术指标"""
    close = df['close']
    volume = df['volume']
    
    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df['diff'] = ema12 - ema26
    df['dea'] = df['diff'].ewm(span=9, adjust=False).mean()
    df['macd'] = (df['diff'] - df['dea']) * 2
    
    # MA均线
    df['ma5'] = close.rolling(5).mean()
    df['ma20'] = close.rolling(20).mean()
    df['ma60'] = close.rolling(60).mean()
    
    # 成交量均线
    df['vol_ma5'] = volume.rolling(5).mean()
    
    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # 布林带
    df['bb_mid'] = close.rolling(20).mean()
    df['bb_std'] = close.rolling(20).std()
    df['bb_upper'] = df['bb_mid'] + 2 * df['bb_std']
    df['bb_lower'] = df['bb_mid'] - 2 * df['bb_std']
    
    return df

def generate_signals(df):
    """生成交易信号"""
    df = df.copy()
    
    # 1. MACD金叉死叉
    df['macd_golden'] = (df['diff'] > df['dea']) & (df['diff'].shift(1) <= df['dea'].shift(1))
    df['macd_dead'] = (df['diff'] < df['dea']) & (df['diff'].shift(1) >= df['dea'].shift(1))
    
    # 2. 量价配合验证（放量上涨/缩量下跌）
    df['volume_up'] = df['volume'] > df['vol_ma5'] * 1.2  # 放量
    df['volume_down'] = df['volume'] < df['vol_ma5'] * 0.8  # 缩量
    
    # 3. 趋势确认（多头排列：MA5 > MA20 > MA60）
    df['trend_up'] = (df['ma5'] > df['ma20']) & (df['ma20'] > df['ma60'])
    df['trend_down'] = (df['ma5'] < df['ma20']) & (df['ma20'] < df['ma60'])
    
    # 4. RSI超买超卖
    df['rsi_overbought'] = df['rsi'] > 70
    df['rsi_oversold'] = df['rsi'] < 30
    
    # 5. 布林带支撑压力
    df['bb_touch_upper'] = df['close'] >= df['bb_upper']
    df['bb_touch_lower'] = df['close'] <= df['bb_lower']
    
    # 综合信号
    # 做多信号：MACD金叉 + 量价配合 + 趋势向上
    df['buy_signal'] = (df['macd_golden'] & df['volume_up'] & df['trend_up'])
    
    # 做空信号：MACD死叉 + 量价配合 + 趋势向下
    df['sell_signal'] = (df['macd_dead'] & df['volume_down'] & df['trend_down'])
    
    # 止损信号：RSI超买 + 布林带上轨
    df['stop_buy'] = df['rsi_overbought'] & df['bb_touch_upper']
    
    # 止损信号：RSI超卖 + 布林带下轨
    df['stop_sell'] = df['rsi_oversold'] & df['bb_touch_lower']
    
    return df

def backtest_strategy(df):
    """执行回测"""
    position = 0  # 0=空仓, 1=多头, -1=空头
    trades = []
    entry_price = 0
    entry_date = None
    
    for i in range(60, len(df)):  # 至少60根K线计算指标
        row = df.iloc[i]
        
        if position == 0:  # 空仓
            # 做多
            if row['buy_signal']:
                position = 1
                entry_price = row['close']
                entry_date = row['datetime']
        
        elif position == 1:  # 持有多头
            # 止损
            if row['stop_buy'] or row['bb_touch_upper']:
                exit_price = row['close']
                profit = (exit_price - entry_price) * 10
                trades.append({
                    'direction': 'Long',
                    'entry_date': str(entry_date)[:10],
                    'exit_date': str(row['datetime'])[:10],
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'profit': profit,
                    'exit_reason': 'RSI_Overbought' if row['rsi_overbought'] else 'BB_Upper'
                })
                position = 0
            # 做空止损（反手）
            elif row['sell_signal'] and row['trend_down']:
                # 平多开空
                exit_price = row['close']
                profit = (exit_price - entry_price) * 10
                trades.append({
                    'direction': 'Long->Short',
                    'entry_date': str(entry_date)[:10],
                    'exit_date': str(row['datetime'])[:10],
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'profit': profit,
                    'exit_reason': 'Reverse_Short'
                })
                position = -1
                entry_price = row['close']
                entry_date = row['datetime']
            # 死叉平多
            elif row['macd_dead'] and not row['trend_up']:
                exit_price = row['close']
                profit = (exit_price - entry_price) * 10
                trades.append({
                    'direction': 'Long',
                    'entry_date': str(entry_date)[:10],
                    'exit_date': str(row['datetime'])[:10],
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'profit': profit,
                    'exit_reason': 'MACD_Dead'
                })
                position = 0
        
        elif position == -1:  # 持有空头
            # 止损
            if row['stop_sell'] or row['bb_touch_lower']:
                exit_price = row['close']
                profit = (entry_price - exit_price) * 10
                trades.append({
                    'direction': 'Short',
                    'entry_date': str(entry_date)[:10],
                    'exit_date': str(row['datetime'])[:10],
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'profit': profit,
                    'exit_reason': 'RSI_Oversold' if row['rsi_oversold'] else 'BB_Lower'
                })
                position = 0
            # 金叉平空（反手）
            elif row['buy_signal'] and row['trend_up']:
                exit_price = row['close']
                profit = (entry_price - exit_price) * 10
                trades.append({
                    'direction': 'Short->Long',
                    'entry_date': str(entry_date)[:10],
                    'exit_date': str(row['datetime'])[:10],
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'profit': profit,
                    'exit_reason': 'Reverse_Long'
                })
                position = 1
                entry_price = row['close']
                entry_date = row['datetime']
            # 金叉平空
            elif row['macd_golden'] and not row['trend_down']:
                exit_price = row['close']
                profit = (entry_price - exit_price) * 10
                trades.append({
                    'direction': 'Short',
                    'entry_date': str(entry_date)[:10],
                    'exit_date': str(row['datetime'])[:10],
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'profit': profit,
                    'exit_reason': 'MACD_Golden'
                })
                position = 0
    
    # 平仓
    if position != 0:
        final_row = df.iloc[-1]
        if position == 1:
            profit = (final_row['close'] - entry_price) * 10
            trades.append({
                'direction': 'Long(Close)',
                'entry_date': str(entry_date)[:10],
                'exit_date': str(final_row['datetime'])[:10],
                'entry_price': entry_price,
                'exit_price': final_row['close'],
                'profit': profit,
                'exit_reason': 'End_Position'
            })
        elif position == -1:
            profit = (entry_price - final_row['close']) * 10
            trades.append({
                'direction': 'Short(Close)',
                'entry_date': str(entry_date)[:10],
                'exit_date': str(final_row['datetime'])[:10],
                'entry_price': entry_price,
                'exit_price': final_row['close'],
                'profit': profit,
                'exit_reason': 'End_Position'
            })
    
    return trades

def main():
    print("=" * 70)
    print("PTA三维度策略回测 - 基于futures-trading skill")
    print("策略：MACD + 成交量验证 + 趋势确认 + RSI + 布林带")
    print("=" * 70)
    
    api = TqApi(TqKq(), auth=TqAuth('test', 'test'))
    
    # 获取日K线
    print("\n[1] 获取日K线数据...")
    klines = api.get_kline_serial('CZCE.TA509', 86400, data_length=400)
    
    for i in range(25):
        time.sleep(1)
        if len(klines) >= 200 and klines.iloc[-1]['close'] > 0:
            break
        print(f"    等待加载... {i+1}/25")
    
    df = pd.DataFrame(klines)
    df['datetime'] = pd.to_datetime(df['datetime'], unit='ns')
    df = df.sort_values('datetime').reset_index(drop=True)
    df = df[df['close'] > 0]
    
    start_date = str(df.iloc[0]['datetime'])[:10]
    end_date = str(df.iloc[-1]['datetime'])[:10]
    
    print(f"    数据范围: {start_date} ~ {end_date}")
    print(f"    有效K线: {len(df)} 根")
    
    # 计算指标
    print("\n[2] 计算技术指标...")
    df = calculate_indicators(df)
    df = generate_signals(df)
    
    # 统计信号
    buy_signals = df['buy_signal'].sum()
    sell_signals = df['sell_signal'].sum()
    print(f"    买入信号: {buy_signals} 次")
    print(f"    卖出信号: {sell_signals} 次")
    
    # 回测
    print("\n[3] 执行回测...")
    trades = backtest_strategy(df)
    
    # 结果
    print("\n" + "=" * 70)
    print("回测结果")
    print("=" * 70)
    print(f"回测周期: {start_date} ~ {end_date}")
    print(f"总K线数: {len(df)}")
    
    if trades:
        df_trades = pd.DataFrame(trades)
        total = df_trades['profit'].sum()
        wins = df_trades[df_trades['profit'] > 0]
        losses = df_trades[df_trades['profit'] <= 0]
        wr = len(wins) / len(df_trades) * 100
        
        print(f"总交易次数: {len(trades)}")
        print(f"盈利次数: {len(wins)}")
        print(f"亏损次数: {len(losses)}")
        print(f"胜率: {wr:.1f}%")
        print(f"总收益: {total:.0f} 元")
        
        if len(trades) > 0:
            print(f"平均收益: {df_trades['profit'].mean():.0f} 元")
            print(f"最大盈利: {df_trades['profit'].max():.0f} 元")
            print(f"最大亏损: {df_trades['profit'].min():.0f} 元")
        
        # 收益曲线
        df_trades['cumsum'] = df_trades['profit'].cumsum()
        print(f"\n最终累计收益: {df_trades['cumsum'].iloc[-1]:.0f} 元")
        
        print("\n交易明细:")
        print("-" * 70)
        print(f"{'方向':<15} {'入场日期':<12} {'出场日期':<12} {'入场价':<8} {'出场价':<8} {'盈亏':<10} {'出场原因'}")
        print("-" * 70)
        for t in trades:
            p = f"+{t['profit']:.0f}" if t['profit'] >= 0 else f"{t['profit']:.0f}"
            print(f"{t['direction']:<15} {t['entry_date']:<12} {t['exit_date']:<12} {t['entry_price']:<8.0f} {t['exit_price']:<8.0f} {p:<10} {t['exit_reason']}")
    else:
        print("无交易!")
    
    api.close()
    print("\n完成!")

if __name__ == '__main__':
    main()
#!/usr/bin/env python3
"""
PTA三维度策略回测 - 基于futures-trading skill简化版
"""
import pandas as pd
import numpy as np

INIT_CAPITAL = 100000
MAX_LOSS_RATIO = 0.02
STOP_LOSS_RATIO = 0.02
TAKE_PROFIT_RATIO = 0.05

def calculate_indicators(df):
    close = df['close']
    volume = df['volume']
    
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df['diff'] = ema12 - ema26
    df['dea'] = df['diff'].ewm(span=9, adjust=False).mean()
    
    df['ma10'] = close.rolling(10).mean()
    
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-10)
    df['rsi'] = 100 - (100 / (1 + rs))
    
    return df

def generate_signals(df):
    df = df.copy()
    df['macd_golden'] = (df['diff'] > df['dea']) & (df['diff'].shift(1) <= df['dea'].shift(1))
    df['macd_dead'] = (df['diff'] < df['dea']) & (df['diff'].shift(1) >= df['dea'].shift(1))
    df['price_above_ma'] = df['close'] > df['ma10']
    df['rsi_overbought'] = df['rsi'] > 70
    df['rsi_oversold'] = df['rsi'] < 30
    df['buy_signal'] = df['macd_golden'] & df['price_above_ma']
    df['sell_signal'] = df['macd_dead'] & (~df['price_above_ma'])
    return df

def calculate_position(entry_price, stop_loss_price, max_loss, contract_size=10):
    stop_loss_ratio = abs(entry_price - stop_loss_price) / entry_price
    if stop_loss_ratio == 0:
        return 1
    position = min(max_loss / (stop_loss_ratio * contract_size), 10)
    return int(position)

def backtest(df, initial_capital=INIT_CAPITAL):
    capital = initial_capital
    position = 0
    trades = []
    entry_price = 0
    entry_date = None
    position_size = 0
    
    for i in range(30, len(df)):
        row = df.iloc[i]
        
        if position == 0:
            if row['buy_signal']:
                position = 1
                entry_price = row['close']
                entry_date = row['datetime']
                entry_reason = f"MACD金叉+价格>{row['ma10']:.0f}"
                stop_loss_price = entry_price * (1 - STOP_LOSS_RATIO)
                max_loss = capital * MAX_LOSS_RATIO
                position_size = calculate_position(entry_price, stop_loss_price, max_loss)
        
        elif position == 1:
            stop_loss = entry_price * (1 - STOP_LOSS_RATIO)
            take_profit = entry_price * (1 + TAKE_PROFIT_RATIO)
            exit_reason = None
            exit_price = row['close']
            
            if row['rsi_overbought'] or exit_price >= take_profit:
                exit_reason = '止盈' if exit_price >= take_profit else 'RSI超买'
            elif exit_price <= stop_loss:
                exit_reason = '止损'
            elif row['sell_signal']:
                exit_reason = '死叉反手'
            
            if exit_reason:
                profit = (exit_price - entry_price) * position_size * 10
                capital += profit
                trades.append({
                    'direction': 'Long',
                    'entry_date': str(entry_date)[:10],
                    'exit_date': str(row['datetime'])[:10],
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'position_size': position_size,
                    'profit': profit,
                    'capital_after': capital,
                    'exit_reason': exit_reason,
                    'entry_reason': entry_reason
                })
                position = 0
                
                if row['sell_signal']:
                    position = -1
                    entry_price = row['close']
                    entry_date = row['datetime']
                    entry_reason = f"MACD死叉+价格<{row['ma10']:.0f}"
                    stop_loss_price = entry_price * (1 + STOP_LOSS_RATIO)
                    max_loss = capital * MAX_LOSS_RATIO
                    position_size = calculate_position(entry_price, stop_loss_price, max_loss)
        
        elif position == -1:
            stop_loss = entry_price * (1 + STOP_LOSS_RATIO)
            take_profit = entry_price * (1 - TAKE_PROFIT_RATIO)
            exit_reason = None
            exit_price = row['close']
            
            if row['rsi_oversold'] or exit_price <= take_profit:
                exit_reason = '止盈' if exit_price <= take_profit else 'RSI超卖'
            elif exit_price >= stop_loss:
                exit_reason = '止损'
            elif row['buy_signal']:
                exit_reason = '金叉反手'
            
            if exit_reason:
                profit = (entry_price - exit_price) * position_size * 10
                capital += profit
                trades.append({
                    'direction': 'Short',
                    'entry_date': str(entry_date)[:10],
                    'exit_date': str(row['datetime'])[:10],
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'position_size': position_size,
                    'profit': profit,
                    'capital_after': capital,
                    'exit_reason': exit_reason,
                    'entry_reason': entry_reason
                })
                position = 0
                
                if row['buy_signal']:
                    position = 1
                    entry_price = row['close']
                    entry_date = row['datetime']
                    entry_reason = f"MACD金叉+价格>{row['ma10']:.0f}"
                    stop_loss_price = entry_price * (1 - STOP_LOSS_RATIO)
                    max_loss = capital * MAX_LOSS_RATIO
                    position_size = calculate_position(entry_price, stop_loss_price, max_loss)
    
    return capital, trades

def main():
    print("=" * 80)
    print("PTA三维度策略回测 - futures-trading skill")
    print("信号：MACD + MA10趋势 + RSI超买超卖 + 2%止损5%止盈 + 以损定量")
    print("=" * 80)
    
    print("\n[1] 加载数据...")
    df = pd.read_csv('/home/admin/.openclaw/workspace/codeman/pta_analysis/pta_real_history.csv')
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.sort_values('datetime').reset_index(drop=True)
    
    start_date = str(df.iloc[0]['datetime'])[:10]
    end_date = str(df.iloc[-1]['datetime'])[:10]
    print(f"    {start_date} ~ {end_date}, {len(df)}根K线")
    
    print("\n[2] 计算指标...")
    df = calculate_indicators(df)
    df = generate_signals(df)
    print(f"    买入信号: {df['buy_signal'].sum()}")
    print(f"    卖出信号: {df['sell_signal'].sum()}")
    
    print("\n[3] 回测...")
    final_capital, trades = backtest(df)
    
    print("\n" + "=" * 80)
    print("回测结果")
    print("=" * 80)
    
    if trades:
        df_trades = pd.DataFrame(trades)
        total_profit = final_capital - INIT_CAPITAL
        profit_rate = total_profit / INIT_CAPITAL * 100
        wins = df_trades[df_trades['profit'] > 0]
        losses = df_trades[df_trades['profit'] <= 0]
        wr = len(wins) / len(trades) * 100
        
        print(f"周期: {start_date} ~ {end_date}")
        print(f"初始资金: {INIT_CAPITAL}元")
        print(f"最终资金: {final_capital:.0f}元")
        print(f"总收益: {total_profit:.0f}元 ({profit_rate:+.1f}%)")
        print(f"交易次数: {len(trades)}")
        print(f"盈利: {len(wins)}, 亏损: {len(losses)}")
        print(f"胜率: {wr:.1f}%")
        print(f"平均收益: {df_trades['profit'].mean():.0f}元")
        print(f"最大盈利: {df_trades['profit'].max():.0f}元")
        print(f"最大亏损: {df_trades['profit'].min():.0f}元")
        
        print("\n" + "-" * 80)
        print("交易明细")
        print("-" * 80)
        for i, t in enumerate(trades, 1):
            p = f"+{t['profit']:.0f}" if t['profit'] >= 0 else f"{t['profit']:.0f}"
            print(f"{i:3}. {t['direction']:<6} {t['entry_date']} {t['entry_price']:.0f}->{t['exit_price']:.0f} 手数{t['position_size']} {p:>10}元 [{t['exit_reason']}]")
        
        print("\n" + "-" * 80)
        print("开仓逻辑")
        print("-" * 80)
        for i, t in enumerate(trades, 1):
            print(f"{i}. [{t['direction']}] {t['entry_date']} @ {t['entry_price']:.0f} - {t['entry_reason']}")
    else:
        print("无交易!")
    
    print("\n完成!")

if __name__ == '__main__':
    main()
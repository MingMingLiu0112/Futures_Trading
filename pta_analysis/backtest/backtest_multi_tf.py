#!/usr/bin/env python3
"""
PTA多周期联动策略回测
基于futures-trading skill框架

三级别：30分钟确认趋势 → 5分钟找买卖点 → 1分钟精确入场
操作级别：5分钟
"""
import pandas as pd
import numpy as np

INIT_CAPITAL = 100000
MAX_LOSS_RATIO = 0.02
STOP_LOSS_RATIO = 0.02
TAKE_PROFIT_RATIO = 0.05

def load_data():
    """加载所有周期数据"""
    periods = {
        '30min': pd.read_csv('/home/admin/.openclaw/workspace/codeman/pta_analysis/pta_30min.csv'),
        '5min': pd.read_csv('/home/admin/.openclaw/workspace/codeman/pta_analysis/pta_5min.csv'),
        '1min': pd.read_csv('/home/admin/.openclaw/workspace/codeman/pta_analysis/pta_1min.csv'),
    }
    
    for name, df in periods.items():
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.sort_values('datetime').reset_index(drop=True)
        df = df[df['close'] > 0]
        periods[name] = df
    
    return periods

def calculate_ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def calculate_macd(df, fast=12, slow=26, signal=9):
    """计算MACD"""
    close = df['close']
    ema_fast = calculate_ema(close, fast)
    ema_slow = calculate_ema(close, slow)
    df['diff'] = ema_fast - ema_slow
    df['dea'] = calculate_ema(df['diff'], signal)
    df['macd'] = (df['diff'] - df['dea']) * 2
    return df

def calculate_ma(df, periods=[5, 10, 20]):
    """计算均线"""
    close = df['close']
    for p in periods:
        df[f'ma{p}'] = close.rolling(p).mean()
    return df

def generate_signals_30min(df_30):
    """30分钟趋势判断"""
    df = df_30.copy()
    df = calculate_macd(df)
    df = calculate_ma(df)
    
    # 趋势判断：MACD在0轴上方 + MA多头排列
    df['trend_up'] = (df['diff'] > 0) & (df['ma5'] > df['ma10']) & (df['ma10'] > df['ma20'])
    df['trend_down'] = (df['diff'] < 0) & (df['ma5'] < df['ma10']) & (df['ma10'] < df['ma20'])
    
    return df

def generate_signals_5min(df_5, df_30):
    """5分钟买卖点（需要30分钟趋势确认）"""
    df = df_5.copy()
    df = calculate_macd(df)
    df = calculate_ma(df)
    
    # 金叉死叉
    df['macd_golden'] = (df['diff'] > df['dea']) & (df['diff'].shift(1) <= df['dea'].shift(1))
    df['macd_dead'] = (df['diff'] < df['dea']) & (df['diff'].shift(1) >= df['dea'].shift(1))
    
    # RSI
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-10)
    df['rsi'] = 100 - (100 / (1 + rs))
    df['rsi_overbought'] = df['rsi'] > 70
    df['rsi_oversold'] = df['rsi'] < 30
    
    # 获取对应时间的30分钟趋势
    # 通过时间对齐获取30分钟趋势
    df['trend_up'] = False
    df['trend_down'] = False
    
    # 为每根5分钟K线找到对应的30分钟趋势
    for i in range(len(df)):
        dt = df.iloc[i]['datetime']
        # 找到最近的30分钟K线
        mask = df_30['datetime'] <= dt
        if mask.any():
            idx = df_30[mask].index[-1]
            df.iloc[i, df.columns.get_loc('trend_up')] = df_30.loc[idx, 'trend_up']
            df.iloc[i, df.columns.get_loc('trend_down')] = df_30.loc[idx, 'trend_down']
    
    # 买入信号：5分钟金叉 + 30分钟趋势向上
    df['buy_signal'] = df['macd_golden'] & df['trend_up']
    
    # 卖出信号：5分钟死叉 + 30分钟趋势向下
    df['sell_signal'] = df['macd_dead'] & df['trend_down']
    
    return df

def calculate_position(entry_price, stop_loss_price, max_loss, contract_size=10):
    stop_loss_ratio = abs(entry_price - stop_loss_price) / entry_price
    if stop_loss_ratio == 0:
        return 1
    position = min(max_loss / (stop_loss_ratio * contract_size), 10)
    return int(position)

def backtest(df_5, df_30, initial_capital=INIT_CAPITAL):
    """执行多周期回测"""
    capital = initial_capital
    position = 0
    trades = []
    entry_price = 0
    entry_date = None
    position_size = 0
    
    # 生成5分钟信号（带30分钟趋势）
    print("生成信号...")
    df = generate_signals_5min(df_5, df_30)
    
    print(f"买入信号: {df['buy_signal'].sum()}")
    print(f"卖出信号: {df['sell_signal'].sum()}")
    
    for i in range(50, len(df)):
        row = df.iloc[i]
        
        # ==================== 空仓时 ====================
        if position == 0:
            if row['buy_signal']:
                position = 1
                entry_price = row['close']
                entry_date = row['datetime']
                
                # 开仓理由
                trend_30 = "30分钟向上" if row['trend_up'] else "30分钟震荡"
                entry_reason = f"5分钟金叉+{trend_30}"
                
                # 以损定量
                stop_loss_price = entry_price * (1 - STOP_LOSS_RATIO)
                max_loss = capital * MAX_LOSS_RATIO
                position_size = calculate_position(entry_price, stop_loss_price, max_loss)
        
        # ==================== 持有多头时 ====================
        elif position == 1:
            stop_loss = entry_price * (1 - STOP_LOSS_RATIO)
            take_profit = entry_price * (1 + TAKE_PROFIT_RATIO)
            
            exit_reason = None
            exit_price = row['close']
            
            # 止损
            if exit_price <= stop_loss:
                exit_reason = "止损(2%)"
            # 止盈
            elif exit_price >= take_profit:
                exit_reason = "止盈(5%)"
            # RSI超买
            elif row['rsi_overbought']:
                exit_reason = "RSI超买"
            # 死叉出场
            elif row['macd_dead'] and row['trend_down']:
                exit_reason = "死叉+30分钟转空"
            
            if exit_reason:
                profit = (exit_price - entry_price) * position_size * 10
                capital += profit
                trades.append({
                    'direction': 'Long',
                    'entry_date': str(entry_date)[:19],
                    'exit_date': str(row['datetime'])[:19],
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'position_size': position_size,
                    'profit': profit,
                    'capital_after': capital,
                    'exit_reason': exit_reason,
                    'entry_reason': entry_reason
                })
                position = 0
                
                # 检查是否反手做空
                if row['sell_signal']:
                    position = -1
                    entry_price = row['close']
                    entry_date = row['datetime']
                    trend_30 = "30分钟向下" if row['trend_down'] else "30分钟震荡"
                    entry_reason = f"5分钟死叉+{trend_30}"
                    stop_loss_price = entry_price * (1 + STOP_LOSS_RATIO)
                    max_loss = capital * MAX_LOSS_RATIO
                    position_size = calculate_position(entry_price, stop_loss_price, max_loss)
        
        # ==================== 持有空头时 ====================
        elif position == -1:
            stop_loss = entry_price * (1 + STOP_LOSS_RATIO)
            take_profit = entry_price * (1 - TAKE_PROFIT_RATIO)
            
            exit_reason = None
            exit_price = row['close']
            
            # 止损
            if exit_price >= stop_loss:
                exit_reason = "止损(2%)"
            # 止盈
            elif exit_price <= take_profit:
                exit_reason = "止盈(5%)"
            # RSI超卖
            elif row['rsi_oversold']:
                exit_reason = "RSI超卖"
            # 金叉出场
            elif row['macd_golden'] and row['trend_up']:
                exit_reason = "金叉+30分钟转多"
            
            if exit_reason:
                profit = (entry_price - exit_price) * position_size * 10
                capital += profit
                trades.append({
                    'direction': 'Short',
                    'entry_date': str(entry_date)[:19],
                    'exit_date': str(row['datetime'])[:19],
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'position_size': position_size,
                    'profit': profit,
                    'capital_after': capital,
                    'exit_reason': exit_reason,
                    'entry_reason': entry_reason
                })
                position = 0
                
                # 检查是否反手做多
                if row['buy_signal']:
                    position = 1
                    entry_price = row['close']
                    entry_date = row['datetime']
                    trend_30 = "30分钟向上" if row['trend_up'] else "30分钟震荡"
                    entry_reason = f"5分钟金叉+{trend_30}"
                    stop_loss_price = entry_price * (1 - STOP_LOSS_RATIO)
                    max_loss = capital * MAX_LOSS_RATIO
                    position_size = calculate_position(entry_price, stop_loss_price, max_loss)
    
    return capital, trades, df

def main():
    print("=" * 80)
    print("PTA多周期联动策略回测")
    print("框架：30分钟确认趋势 → 5分钟找买卖点")
    print("=" * 80)
    print(f"初始资金: {INIT_CAPITAL}元 | 止损: {STOP_LOSS_RATIO*100}% | 止盈: {TAKE_PROFIT_RATIO*100}%")
    print("=" * 80)
    
    # 加载数据
    print("\n[1] 加载数据...")
    periods = load_data()
    df_30 = periods['30min']
    df_5 = periods['5min']
    df_1 = periods['1min']
    
    print(f"    30分钟: {len(df_30)}根 ({str(df_30.iloc[0]['datetime'])[:19]} ~ {str(df_30.iloc[-1]['datetime'])[:19]})")
    print(f"    5分钟: {len(df_5)}根 ({str(df_5.iloc[0]['datetime'])[:19]} ~ {str(df_5.iloc[-1]['datetime'])[:19]})")
    print(f"    1分钟: {len(df_1)}根 ({str(df_1.iloc[0]['datetime'])[:19]} ~ {str(df_1.iloc[-1]['datetime'])[:19]})")
    
    # 生成30分钟趋势
    print("\n[2] 生成30分钟趋势...")
    df_30_trend = generate_signals_30min(df_30)
    trend_up_count = df_30_trend['trend_up'].sum()
    trend_down_count = df_30_trend['trend_down'].sum()
    print(f"    30分钟向上: {trend_up_count}根K线")
    print(f"    30分钟向下: {trend_down_count}根K线")
    
    # 回测
    print("\n[3] 执行回测...")
    final_capital, trades, df_5_signals = backtest(df_5, df_30_trend)
    
    # 结果
    print("\n" + "=" * 80)
    print("回测结果")
    print("=" * 80)
    
    if not trades:
        print("无交易!")
        return
    
    df_trades = pd.DataFrame(trades)
    total_profit = final_capital - INIT_CAPITAL
    profit_rate = total_profit / INIT_CAPITAL * 100
    wins = df_trades[df_trades['profit'] > 0]
    losses = df_trades[df_trades['profit'] <= 0]
    wr = len(wins) / len(trades) * 100
    
    print(f"回测周期: {str(df_5.iloc[0]['datetime'])[:10]} ~ {str(df_5.iloc[-1]['datetime'])[:10]}")
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
        print(f"{i:3}. {t['direction']:<6} {t['entry_date'][:16]} {t['entry_price']:.0f}->{t['exit_price']:.0f} 手数{t['position_size']} {p:>10}元 [{t['exit_reason']}]")
    
    print("\n" + "-" * 80)
    print("开仓逻辑记录")
    print("-" * 80)
    for i, t in enumerate(trades, 1):
        print(f"{i}. [{t['direction']}] {t['entry_date'][:16]} @ {t['entry_price']:.0f}")
        print(f"   开仓理由: {t['entry_reason']}")
    
    print("\n完成!")

if __name__ == '__main__':
    main()
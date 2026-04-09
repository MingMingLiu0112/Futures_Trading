#!/usr/bin/env python3
"""
PTA多周期联动策略回测 - 详细开平仓逻辑版
基于futures-trading skill框架

三级别：30分钟确认趋势 → 5分钟找买卖点
操作级别：5分钟

【开仓逻辑】
- 多头：5分钟MACD金叉 + 30分钟趋势向上（MACD在0轴上方 + MA多头排列）
- 空头：5分钟MACD死叉 + 30分钟趋势向下（MACD在0轴下方 + MA空头排列）

【平仓逻辑】
- 止损：价格反向波动2%
- 止盈：价格正向波动5%
- RSI超买（>70）：多头止盈
- RSI超卖（<30）：空头止盈
- 趋势反转：30分钟趋势改变时平仓

【仓位管理】
- 以损定量：单笔最大亏损不超过账户2%
- 仓位 = 最大允许亏损 / (2%止损幅度 × 合约乘数)
"""
import pandas as pd
import numpy as np

INIT_CAPITAL = 100000
MAX_LOSS_RATIO = 0.02  # 单笔最大亏损2%
STOP_LOSS_RATIO = 0.02  # 止损2%
TAKE_PROFIT_RATIO = 0.05  # 止盈5%
CONTRACT_SIZE = 10  # PTA合约乘数

def load_data():
    """加载所有周期数据"""
    periods = {
        '30min': pd.read_csv('/home/admin/.openclaw/workspace/codeman/pta_analysis/pta_30min.csv'),
        '5min': pd.read_csv('/home/admin/.openclaw/workspace/codeman/pta_analysis/pta_5min.csv'),
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

def calculate_rsi(df, window=14):
    """计算RSI"""
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window).mean()
    rs = gain / (loss + 1e-10)
    df['rsi'] = 100 - (100 / (1 + rs))
    return df

def generate_30min_trend(df_30):
    """生成30分钟趋势信号"""
    df = df_30.copy()
    df = calculate_macd(df)
    df = calculate_ma(df)
    
    # 趋势定义
    df['trend_up'] = (df['diff'] > 0) & (df['ma5'] > df['ma10']) & (df['ma10'] > df['ma20'])
    df['trend_down'] = (df['diff'] < 0) & (df['ma5'] < df['ma10']) & (df['ma10'] < df['ma20'])
    
    return df

def generate_5min_signals(df_5, df_30):
    """生成5分钟买卖信号（带30分钟趋势确认）"""
    df = df_5.copy()
    df = calculate_macd(df)
    df = calculate_ma(df)
    df = calculate_rsi(df)
    
    # MACD信号
    df['macd_golden'] = (df['diff'] > df['dea']) & (df['diff'].shift(1) <= df['dea'].shift(1))
    df['macd_dead'] = (df['diff'] < df['dea']) & (df['diff'].shift(1) >= df['dea'].shift(1))
    
    # RSI信号
    df['rsi_overbought'] = df['rsi'] > 70
    df['rsi_oversold'] = df['rsi'] < 30
    
    # 对齐30分钟趋势
    df['trend_up'] = False
    df['trend_down'] = False
    
    for i in range(len(df)):
        dt = df.iloc[i]['datetime']
        mask = df_30['datetime'] <= dt
        if mask.any():
            idx = df_30[mask].index[-1]
            df.iloc[i, df.columns.get_loc('trend_up')] = df_30.loc[idx, 'trend_up']
            df.iloc[i, df.columns.get_loc('trend_down')] = df_30.loc[idx, 'trend_down']
    
    # 开仓信号
    df['buy_signal'] = df['macd_golden'] & df['trend_up']
    df['sell_signal'] = df['macd_dead'] & df['trend_down']
    
    return df

def calculate_position(entry_price, stop_loss_price, max_loss, contract_size=CONTRACT_SIZE):
    """以损定量计算仓位"""
    stop_loss_ratio = abs(entry_price - stop_loss_price) / entry_price
    if stop_loss_ratio == 0:
        return 1
    position = min(max_loss / (stop_loss_ratio * contract_size), 10)
    return int(position)

def backtest(df_5, df_30, initial_capital=INIT_CAPITAL):
    """执行回测"""
    capital = initial_capital
    position = 0
    trades = []
    entry_price = 0
    entry_date = None
    position_size = 0
    
    df = generate_5min_signals(df_5, df_30)
    
    for i in range(50, len(df)):
        row = df.iloc[i]
        
        # ==================== 空仓时 ====================
        if position == 0:
            if row['buy_signal']:
                position = 1
                entry_price = row['close']
                entry_date = row['datetime']
                
                # 开仓理由
                entry_reason = f"5分钟MACD金叉 + 30分钟趋势向上(DIFF={'+' if row['diff']>0 else ''}{row['diff']:.0f})"
                
                stop_loss_price = entry_price * (1 - STOP_LOSS_RATIO)
                max_loss = capital * MAX_LOSS_RATIO
                position_size = calculate_position(entry_price, stop_loss_price, max_loss)
        
        # ==================== 持有多头时 ====================
        elif position == 1:
            stop_loss = entry_price * (1 - STOP_LOSS_RATIO)
            take_profit = entry_price * (1 + TAKE_PROFIT_RATIO)
            
            exit_reason = None
            exit_price = row['close']
            
            # 平仓条件判断（优先级从高到低）
            if exit_price <= stop_loss:
                exit_reason = f"止损({(exit_price/entry_price-1)*100:.1f}%)"
            elif exit_price >= take_profit:
                exit_reason = f"止盈({(exit_price/entry_price-1)*100:.1f}%)"
            elif row['rsi_overbought']:
                exit_reason = f"RSI超买({row['rsi']:.0f})"
            elif row['macd_dead'] and row['trend_down']:
                exit_reason = "MACD死叉 + 30分钟趋势转空"
            
            if exit_reason:
                profit = (exit_price - entry_price) * position_size * CONTRACT_SIZE
                capital += profit
                trades.append({
                    'direction': 'Long',
                    'entry_date': str(entry_date),
                    'exit_date': str(row['datetime']),
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
                    entry_reason = f"5分钟MACD死叉 + 30分钟趋势向下(DIFF={'+' if row['diff']<0 else ''}{row['diff']:.0f})"
                    stop_loss_price = entry_price * (1 + STOP_LOSS_RATIO)
                    max_loss = capital * MAX_LOSS_RATIO
                    position_size = calculate_position(entry_price, stop_loss_price, max_loss)
        
        # ==================== 持有空头时 ====================
        elif position == -1:
            stop_loss = entry_price * (1 + STOP_LOSS_RATIO)
            take_profit = entry_price * (1 - TAKE_PROFIT_RATIO)
            
            exit_reason = None
            exit_price = row['close']
            
            if exit_price >= stop_loss:
                exit_reason = f"止损({(exit_price/entry_price-1)*100:.1f}%)"
            elif exit_price <= take_profit:
                exit_reason = f"止盈({(exit_price/entry_price-1)*100:.1f}%)"
            elif row['rsi_oversold']:
                exit_reason = f"RSI超卖({row['rsi']:.0f})"
            elif row['macd_golden'] and row['trend_up']:
                exit_reason = "MACD金叉 + 30分钟趋势转多"
            
            if exit_reason:
                profit = (entry_price - exit_price) * position_size * CONTRACT_SIZE
                capital += profit
                trades.append({
                    'direction': 'Short',
                    'entry_date': str(entry_date),
                    'exit_date': str(row['datetime']),
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
                    entry_reason = f"5分钟MACD金叉 + 30分钟趋势向上(DIFF={'+' if row['diff']>0 else ''}{row['diff']:.0f})"
                    stop_loss_price = entry_price * (1 - STOP_LOSS_RATIO)
                    max_loss = capital * MAX_LOSS_RATIO
                    position_size = calculate_position(entry_price, stop_loss_price, max_loss)
    
    return capital, trades, df

def main():
    print("=" * 80)
    print("PTA多周期联动策略回测 - 详细开平仓逻辑版")
    print("=" * 80)
    print()
    print("【开仓逻辑】")
    print("  多头：5分钟MACD金叉 + 30分钟趋势向上（DIFF>0 + MA多头排列）")
    print("  空头：5分钟MACD死叉 + 30分钟趋势向下（DIFF<0 + MA空头排列）")
    print()
    print("【平仓逻辑】")
    print("  止损：价格反向波动2%")
    print("  止盈：价格正向波动5%")
    print("  RSI超买(>70)：多头止盈")
    print("  RSI超卖(<30)：空头止盈")
    print("  趋势反转：30分钟趋势改变时平仓")
    print()
    print("【仓位管理】")
    print("  以损定量：单笔最大亏损不超过账户2%")
    print("=" * 80)
    
    # 加载数据
    print("\n[1] 加载数据...")
    periods = load_data()
    df_30 = periods['30min']
    df_5 = periods['5min']
    
    print(f"    30分钟: {len(df_30)}根")
    print(f"    5分钟: {len(df_5)}根")
    
    # 生成信号
    print("\n[2] 生成信号...")
    df_30_trend = generate_30min_trend(df_30)
    print(f"    30分钟向上趋势: {df_30_trend['trend_up'].sum()}根K线")
    print(f"    30分钟向下趋势: {df_30_trend['trend_down'].sum()}根K线")
    
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
    print(f"盈利次数: {len(wins)}")
    print(f"亏损次数: {len(losses)}")
    print(f"胜率: {wr:.1f}%")
    
    if len(trades) > 0:
        print(f"平均收益: {df_trades['profit'].mean():.0f}元")
        print(f"最大盈利: {df_trades['profit'].max():.0f}元")
        print(f"最大亏损: {df_trades['profit'].min():.0f}元")
    
    print("\n" + "=" * 80)
    print("交易明细（开仓+平仓逻辑）")
    print("=" * 80)
    print(f"{'#':<3} {'方向':<6} {'开仓时间':<20} {'开仓价':<8} {'开仓理由':<35} {'平仓时间':<20} {'平仓价':<8} {'手数':<4} {'盈亏':<10}")
    print("-" * 140)
    
    for i, t in enumerate(trades, 1):
        p = f"+{t['profit']:.0f}" if t['profit'] >= 0 else f"{t['profit']:.0f}"
        print(f"{i:<3} {t['direction']:<6} {t['entry_date']:<20} {t['entry_price']:<8.0f} {t['entry_reason']:<35} {t['exit_date']:<20} {t['exit_price']:<8.0f} {t['position_size']:<4} {p:<10}")
    
    print("\n" + "=" * 80)
    print("开仓逻辑汇总")
    print("=" * 80)
    long_trades = [t for t in trades if t['direction'] == 'Long']
    short_trades = [t for t in trades if t['direction'] == 'Short']
    
    print(f"\n【多头开仓】共{len(long_trades)}笔")
    print("  条件：5分钟MACD金叉 + 30分钟趋势向上")
    print(f"  盈利：{len([t for t in long_trades if t['profit']>0])}笔，亏损：{len([t for t in long_trades if t['profit']<=0])}笔")
    
    print(f"\n【空头开仓】共{len(short_trades)}笔")
    print("  条件：5分钟MACD死叉 + 30分钟趋势向下")
    print(f"  盈利：{len([t for t in short_trades if t['profit']>0])}笔，亏损：{len([t for t in short_trades if t['profit']<=0])}笔")
    
    print("\n" + "=" * 80)
    print("平仓逻辑汇总")
    print("=" * 80)
    
    # 统计平仓原因
    exit_reasons = {}
    for t in trades:
        reason = t['exit_reason']
        if reason not in exit_reasons:
            exit_reasons[reason] = 0
        exit_reasons[reason] += 1
    
    print("\n平仓原因统计：")
    for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count}次")
    
    print("\n完成!")

if __name__ == '__main__':
    main()
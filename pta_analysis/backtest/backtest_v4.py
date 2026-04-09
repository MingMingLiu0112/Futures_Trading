#!/usr/bin/env python3
"""
PTA三维度策略回测 - 仓位管理版
- 以损定量：单笔最大亏损2%
- 开仓逻辑记录
"""
from tqsdk import TqApi, TqAuth, TqKq
import pandas as pd
import numpy as np
import time

# ========== 策略参数 ==========
INIT_CAPITAL = 100000  # 初始资金10万
MAX_LOSS_RATIO = 0.02  # 单笔最大亏损2%
STOP_LOSS_RATIO = 0.02  # 止损2%
TAKE_PROFIT_RATIO = 0.05  # 止盈5%

def calculate_indicators(df):
    """计算技术指标"""
    close = df['close']
    volume = df['volume']
    
    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df['diff'] = ema12 - ema26
    df['dea'] = df['diff'].ewm(span=9, adjust=False).mean()
    
    # MA
    df['ma10'] = close.rolling(10).mean()
    df['ma20'] = close.rolling(20).mean()
    
    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-10)
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # 成交量均线
    df['vol_ma5'] = volume.rolling(5).mean()
    
    return df

def generate_signals(df):
    """生成交易信号"""
    df = df.copy()
    
    # MACD
    df['macd_golden'] = (df['diff'] > df['dea']) & (df['diff'].shift(1) <= df['dea'].shift(1))
    df['macd_dead'] = (df['diff'] < df['dea']) & (df['diff'].shift(1) >= df['dea'].shift(1))
    
    # 趋势
    df['price_above_ma'] = df['close'] > df['ma10']
    
    # RSI
    df['rsi_overbought'] = df['rsi'] > 70
    df['rsi_oversold'] = df['rsi'] < 30
    
    # 信号
    df['buy_signal'] = df['macd_golden'] & df['price_above_ma']
    df['sell_signal'] = df['macd_dead'] & (~df['price_above_ma'])
    
    return df

def calculate_position(entry_price, stop_loss_price, max_loss, contract_size=10):
    """以损定量计算仓位"""
    # 止损金额 = 止损幅度 × 合约乘数 × 仓位
    # 仓位 = 最大亏损 / (止损幅度 × 合约乘数)
    stop_loss_ratio = abs(entry_price - stop_loss_price) / entry_price
    if stop_loss_ratio == 0:
        return 1
    position = min(max_loss / (stop_loss_ratio * contract_size), 10)  # 最多10手
    return int(position)

def backtest_with_position(df, initial_capital=INIT_CAPITAL):
    """带仓位管理的回测"""
    capital = initial_capital
    position = 0
    trades = []
    entry_price = 0
    entry_date = None
    entry_reason = ""
    position_size = 0
    
    for i in range(30, len(df)):
        row = df.iloc[i]
        
        if position == 0:
            if row['buy_signal']:
                position = 1
                entry_price = row['close']
                entry_date = row['datetime']
                entry_reason = f"MACD金叉+价格>{row['ma10']:.0f}均线"
                
                # 以损定量计算仓位
                stop_loss_price = entry_price * (1 - STOP_LOSS_RATIO)
                max_loss = capital * MAX_LOSS_RATIO
                position_size = calculate_position(entry_price, stop_loss_price, max_loss)
        
        elif position == 1:
            stop_loss = entry_price * (1 - STOP_LOSS_RATIO)
            take_profit = entry_price * (1 + TAKE_PROFIT_RATIO)
            
            # 出场判断
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
                
                # 反手
                if row['sell_signal']:
                    position = -1
                    entry_price = row['close']
                    entry_date = row['datetime']
                    entry_reason = f"MACD死叉+价格<{row['ma10']:.0f}均线"
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
                    entry_reason = f"MACD金叉+价格>{row['ma10']:.0f}均线"
                    stop_loss_price = entry_price * (1 - STOP_LOSS_RATIO)
                    max_loss = capital * MAX_LOSS_RATIO
                    position_size = calculate_position(entry_price, stop_loss_price, max_loss)
    
    return capital, trades

def main():
    print("=" * 80)
    print("PTA三维度策略回测 - 仓位管理版")
    print("=" * 80)
    print(f"初始资金: {INIT_CAPITAL}元 | 单笔最大亏损: {MAX_LOSS_RATIO*100}% | 止损: {STOP_LOSS_RATIO*100}% | 止盈: {TAKE_PROFIT_RATIO*100}%")
    print("=" * 80)
    
    api = TqApi(TqKq(), auth=TqAuth('test', 'test'))
    
    print("\n[1] 获取数据...")
    klines = api.get_kline_serial('CZCE.TA509', 86400, data_length=400)
    
    for i in range(25):
        time.sleep(1)
        if len(klines) >= 200 and klines.iloc[-1]['close'] > 0:
            break
    
    df = pd.DataFrame(klines)
    df['datetime'] = pd.to_datetime(df['datetime'], unit='ns')
    df = df.sort_values('datetime').reset_index(drop=True)
    df = df[df['close'] > 0]
    
    start_date = str(df.iloc[0]['datetime'])[:10]
    end_date = str(df.iloc[-1]['datetime'])[:10]
    print(f"    {start_date} ~ {end_date}, {len(df)}根K线")
    
    print("\n[2] 计算指标...")
    df = calculate_indicators(df)
    df = generate_signals(df)
    print(f"    买入信号: {df['buy_signal'].sum()}, 卖出信号: {df['sell_signal'].sum()}")
    
    print("\n[3] 回测...")
    final_capital, trades = backtest_with_position(df)
    
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
        
        print(f"回测周期: {start_date} ~ {end_date}")
        print(f"初始资金: {INIT_CAPITAL}元")
        print(f"最终资金: {final_capital:.0f}元")
        print(f"总收益: {total_profit:.0f}元 ({profit_rate:+.1f}%)")
        print(f"交易次数: {len(trades)}")
        print(f"盈利次数: {len(wins)}")
        print(f"亏损次数: {len(losses)}")
        print(f"胜率: {wr:.1f}%")
        
        if len(trades) > 0:
            avg_profit = df_trades['profit'].mean()
            max_win = df_trades['profit'].max()
            max_loss = df_trades['profit'].min()
            print(f"平均收益: {avg_profit:.0f}元")
            print(f"最大单笔盈利: {max_win:.0f}元")
            print(f"最大单笔亏损: {max_loss:.0f}元")
        
        print("\n" + "-" * 80)
        print("交易明细")
        print("-" * 80)
        print(f"{'#':<3} {'方向':<6} {'入场日期':<12} {'出场日期':<12} {'入场价':<8} {'出场价':<8} {'手数':<4} {'盈亏':<10} {'资金':<10} {'出场原因'}")
        print("-" * 80)
        
        for i, t in enumerate(trades, 1):
            p = f"+{t['profit']:.0f}" if t['profit'] >= 0 else f"{t['profit']:.0f}"
            print(f"{i:<3} {t['direction']:<6} {t['entry_date']:<12} {t['exit_date']:<12} {t['entry_price']:<8.0f} {t['exit_price']:<8.0f} {t['position_size']:<4} {p:<10} {t['capital_after']:<10.0f} {t['exit_reason']}")
        
        print("\n" + "-" * 80)
        print("开仓逻辑记录")
        print("-" * 80)
        for i, t in enumerate(trades, 1):
            print(f"{i}. [{t['direction']}] {t['entry_date']} 入场价{t['entry_price']:.0f}")
            print(f"   开仓理由: {t['entry_reason']}")
            print()
    else:
        print("无交易!")
    
    api.close()
    print("\n完成!")

if __name__ == '__main__':
    main()
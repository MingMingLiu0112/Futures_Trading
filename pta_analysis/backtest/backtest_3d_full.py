#!/usr/bin/env python3
"""
PTA三维度策略回测 - 基于futures-trading skill完整逻辑
维度一：宏观+基本面（市场状态判断）
维度二：技术面（MACD + RSI + 布林带）
维度三：期权印证（简化版 - 由于数据限制，用成交量验证代替）
"""
import pandas as pd
import numpy as np

INIT_CAPITAL = 100000
MAX_LOSS_RATIO = 0.02
STOP_LOSS_RATIO = 0.02
TAKE_PROFIT_RATIO = 0.05

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
    df['ma10'] = close.rolling(10).mean()
    df['ma20'] = close.rolling(20).mean()
    df['ma60'] = close.rolling(60).mean()
    
    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-10)
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # 布林带
    df['bb_mid'] = close.rolling(20).mean()
    df['bb_std'] = close.rolling(20).std()
    df['bb_upper'] = df['bb_mid'] + 2 * df['bb_std']
    df['bb_lower'] = df['bb_mid'] - 2 * df['bb_std']
    
    # 成交量均线
    df['vol_ma5'] = volume.rolling(5).mean()
    
    return df

def generate_signals(df):
    """生成交易信号 - 基于skills逻辑"""
    df = df.copy()
    
    # ===== 维度一：宏观状态（简化版：使用RSI和趋势） =====
    # 默认平静期，RSI极端值时考虑宏观驱动
    df['macro_drive'] = (df['rsi'] < 25) | (df['rsi'] > 75)
    
    # ===== 维度二：技术面信号 =====
    
    # 1. MACD金叉死叉
    df['macd_golden'] = (df['diff'] > df['dea']) & (df['diff'].shift(1) <= df['dea'].shift(1))
    df['macd_dead'] = (df['diff'] < df['dea']) & (df['diff'].shift(1) >= df['dea'].shift(1))
    
    # 2. 趋势判断（均线多头/空头排列）
    df['trend_up'] = (df['ma5'] > df['ma10']) & (df['ma10'] > df['ma20'])
    df['trend_down'] = (df['ma5'] < df['ma10']) & (df['ma10'] < df['ma20'])
    
    # 3. 价格位置（相对均线）
    df['price_above_ma20'] = df['close'] > df['ma20']
    df['price_above_ma10'] = df['close'] > df['ma10']
    
    # 4. RSI超买超卖
    df['rsi_overbought'] = df['rsi'] > 70
    df['rsi_oversold'] = df['rsi'] < 30
    df['rsi_extreme'] = (df['rsi'] > 80) | (df['rsi'] < 20)
    
    # 5. 布林带位置
    df['bb_at_upper'] = df['close'] >= df['bb_upper']
    df['bb_at_lower'] = df['close'] <= df['bb_lower']
    
    # 6. 量价配合
    df['volume_up'] = df['volume'] > df['vol_ma5'] * 1.2
    df['volume_down'] = df['volume'] < df['vol_ma5'] * 0.8
    
    # ===== 综合信号（基于skills三维度共振） =====
    
    # 做多信号：MACD金叉 + 趋势向上 + RSI未超买 + 量价配合
    df['buy_signal'] = (
        df['macd_golden'] & 
        df['price_above_ma10'] &
        ~df['rsi_overbought'] &
        (df['volume_up'] | df['volume'].shift(1) > df['vol_ma5'])
    )
    
    # 做空信号：MACD死叉 + 趋势向下 + RSI未超卖 + 量价配合
    df['sell_signal'] = (
        df['macd_dead'] & 
        ~df['price_above_ma10'] &
        ~df['rsi_oversold'] &
        (df['volume_down'] | df['volume'].shift(1) < df['vol_ma5'])
    )
    
    # 特殊出场信号
    # 杀期权阶段特征：RSI极端 + 布林带极端
    df['exit_long_urgent'] = df['rsi_extreme'] | df['bb_at_upper']
    df['exit_short_urgent'] = df['rsi_extreme'] | df['bb_at_lower']
    
    return df

def calculate_position(entry_price, stop_loss_price, max_loss, contract_size=10):
    """以损定量计算仓位"""
    stop_loss_ratio = abs(entry_price - stop_loss_price) / entry_price
    if stop_loss_ratio == 0:
        return 1
    position = min(max_loss / (stop_loss_ratio * contract_size), 10)
    return int(position)

def backtest_strategy(df, initial_capital=INIT_CAPITAL):
    """执行回测"""
    capital = initial_capital
    position = 0  # 0=空仓, 1=多头, -1=空头
    trades = []
    entry_price = 0
    entry_date = None
    position_size = 0
    
    for i in range(70, len(df)):
        row = df.iloc[i]
        
        # ==================== 空仓时 ====================
        if position == 0:
            if row['buy_signal']:
                position = 1
                entry_price = row['close']
                entry_date = row['datetime']
                
                # 记录开仓理由
                reasons = []
                if row['macd_golden']:
                    reasons.append('MACD金叉')
                if row['price_above_ma10']:
                    reasons.append('价格>MA10')
                if not row['rsi_overbought']:
                    reasons.append('RSI未超买')
                if row['volume_up']:
                    reasons.append('放量')
                entry_reason = '+'.join(reasons)
                
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
                exit_reason = '止损(2%)'
            # 止盈
            elif exit_price >= take_profit:
                exit_reason = '止盈(5%)'
            # RSI超买
            elif row['rsi_overbought'] and row['bb_at_upper']:
                exit_reason = 'RSI超买+布林上轨'
            # 紧急出场（杀期权特征）
            elif row['exit_long_urgent']:
                exit_reason = '杀期权特征出场'
            # 死叉反手
            elif row['sell_signal'] and row['trend_down']:
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
                
                # 检查是否反手做空
                if row['sell_signal'] and row['trend_down']:
                    position = -1
                    entry_price = row['close']
                    entry_date = row['datetime']
                    reasons = ['MACD死叉', '价格<MA10', 'RSI未超卖', '缩量' if row['volume_down'] else '量缩']
                    entry_reason = '+'.join(reasons)
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
                exit_reason = '止损(2%)'
            # 止盈
            elif exit_price <= take_profit:
                exit_reason = '止盈(5%)'
            # RSI超卖
            elif row['rsi_oversold'] and row['bb_at_lower']:
                exit_reason = 'RSI超卖+布林下轨'
            # 紧急出场
            elif row['exit_short_urgent']:
                exit_reason = '杀期权特征出场'
            # 金叉反手
            elif row['buy_signal'] and row['trend_up']:
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
                
                # 检查是否反手做多
                if row['buy_signal'] and row['trend_up']:
                    position = 1
                    entry_price = row['close']
                    entry_date = row['datetime']
                    reasons = ['MACD金叉', '价格>MA10', 'RSI未超买', '放量' if row['volume_up'] else '量稳']
                    entry_reason = '+'.join(reasons)
                    stop_loss_price = entry_price * (1 - STOP_LOSS_RATIO)
                    max_loss = capital * MAX_LOSS_RATIO
                    position_size = calculate_position(entry_price, stop_loss_price, max_loss)
    
    return capital, trades

def main():
    print("=" * 80)
    print("PTA三维度策略回测 - 基于futures-trading skill")
    print("策略：三维度共振（MACD + 趋势 + RSI + 布林带 + 量价配合）")
    print("=" * 80)
    print(f"初始资金: {INIT_CAPITAL}元 | 单笔最大亏损: {MAX_LOSS_RATIO*100}%")
    print(f"止损: {STOP_LOSS_RATIO*100}% | 止盈: {TAKE_PROFIT_RATIO*100}%")
    print("=" * 80)
    
    # 加载数据
    print("\n[1] 加载PTA主连数据...")
    df = pd.read_csv('/home/admin/.openclaw/workspace/codeman/pta_analysis/pta_real_history.csv')
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.sort_values('datetime').reset_index(drop=True)
    
    start_date = str(df.iloc[0]['datetime'])[:10]
    end_date = str(df.iloc[-1]['datetime'])[:10]
    print(f"    数据范围: {start_date} ~ {end_date}")
    print(f"    K线数量: {len(df)}根")
    
    # 计算指标
    print("\n[2] 计算技术指标...")
    df = calculate_indicators(df)
    df = generate_signals(df)
    
    buy_signals = df['buy_signal'].sum()
    sell_signals = df['sell_signal'].sum()
    print(f"    买入信号: {buy_signals}次")
    print(f"    卖出信号: {sell_signals}次")
    
    # 执行回测
    print("\n[3] 执行回测...")
    final_capital, trades = backtest_strategy(df)
    
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
    
    print(f"合约: PTA主连 (KQ.m@CZCE.TA)")
    print(f"回测周期: {start_date} ~ {end_date}")
    print(f"初始资金: {INIT_CAPITAL}元")
    print(f"最终资金: {final_capital:.0f}元")
    print(f"总收益: {total_profit:.0f}元 ({profit_rate:+.1f}%)")
    print(f"交易次数: {len(trades)}")
    print(f"盈利次数: {len(wins)}")
    print(f"亏损次数: {len(losses)}")
    print(f"胜率: {wr:.1f}%")
    
    if len(trades) > 0:
        print(f"平均收益: {df_trades['profit'].mean():.0f}元")
        print(f"最大单笔盈利: {df_trades['profit'].max():.0f}元")
        print(f"最大单笔亏损: {df_trades['profit'].min():.0f}元")
    
    print("\n" + "-" * 80)
    print("交易明细")
    print("-" * 80)
    print(f"{'#':<3} {'方向':<6} {'入场日期':<12} {'出场日期':<12} {'入场价':<8} {'出场价':<8} {'手数':<4} {'盈亏':<10} {'资金':<10} 出场原因")
    print("-" * 80)
    
    for i, t in enumerate(trades, 1):
        p = f"+{t['profit']:.0f}" if t['profit'] >= 0 else f"{t['profit']:.0f}"
        print(f"{i:<3} {t['direction']:<6} {t['entry_date']:<12} {t['exit_date']:<12} {t['entry_price']:<8.0f} {t['exit_price']:<8.0f} {t['position_size']:<4} {p:<10} {t['capital_after']:<10.0f} {t['exit_reason']}")
    
    print("\n" + "-" * 80)
    print("开仓逻辑记录（前15笔）")
    print("-" * 80)
    for i, t in enumerate(trades[:15], 1):
        print(f"{i}. [{t['direction']}] {t['entry_date']} @ {t['entry_price']:.0f}")
        print(f"   理由: {t['entry_reason']}")
        print()

if __name__ == '__main__':
    main()
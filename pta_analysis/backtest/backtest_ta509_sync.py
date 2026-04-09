#!/usr/bin/env python3
"""
PTA期货MACD策略回测 - 同步版本
"""
from tqsdk import TqApi, TqAuth, TqKq
import pandas as pd
import json
import time

def calculate_macd(close, fast=12, slow=26, signal=9):
    """计算MACD指标"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    diff = ema_fast - ema_slow
    dea = diff.ewm(span=signal, adjust=False).mean()
    macd = (diff - dea) * 2
    return diff, dea, macd

def backtest_macd(df):
    """MACD金叉死叉策略"""
    df = df.copy()
    df['diff'], df['dea'], df['macd'] = calculate_macd(df['close'])
    
    position = 0
    trades = []
    entry_price = 0
    entry_date = None
    
    for i in range(1, len(df)):
        diff_prev = df['diff'].iloc[i-1]
        diff_curr = df['diff'].iloc[i]
        dea_prev = df['dea'].iloc[i-1]
        dea_curr = df['dea'].iloc[i]
        
        # 金叉：diff上穿dea
        if diff_prev < dea_prev and diff_curr > dea_curr and position == 0:
            position = 1
            entry_price = df['close'].iloc[i]
            entry_date = df['datetime'].iloc[i]
        # 死叉：diff下穿dea
        elif diff_prev > dea_prev and diff_curr < dea_curr and position == 1:
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
    
    return trades, df

def main():
    print("=" * 50)
    print("PTA MACD策略回测")
    print("=" * 50)
    
    api = TqApi(TqKq(), auth=TqAuth('test', 'test'))
    
    # 获取日K线
    print("\n获取TA509日K线...")
    klines = api.get_kline_serial('CZCE.TA509', 86400, data_length=300)
    time.sleep(5)
    
    df = klines.to_pandas()
    df['datetime'] = pd.to_datetime(df['datetime'], unit='ns')
    df = df.sort_values('datetime').reset_index(drop=True)
    
    start_date = str(df.iloc[0]['datetime'])[:10]
    end_date = str(df.iloc[-1]['datetime'])[:10]
    
    print(f"K线: {len(df)}根, {start_date} ~ {end_date}")
    
    # 回测
    trades, df_macd = backtest_macd(df)
    
    # 统计
    if trades:
        df_trades = pd.DataFrame(trades)
        total_profit = df_trades['profit'].sum()
        win_count = len(df_trades[df_trades['profit'] > 0])
        loss_count = len(df_trades[df_trades['profit'] <= 0])
        win_rate = win_count / len(df_trades) * 100
    else:
        df_trades = pd.DataFrame()
        total_profit = 0
        win_count = 0
        loss_count = 0
        win_rate = 0
    
    print("\n" + "=" * 50)
    print("回测结果")
    print("=" * 50)
    print(f"合约: CZCE.TA509 (PTA 2025年5月)")
    print(f"周期: {start_date} ~ {end_date}")
    print(f"K线数量: {len(df)}")
    print(f"总交易次数: {len(trades)}")
    print(f"盈利次数: {win_count}")
    print(f"亏损次数: {loss_count}")
    print(f"胜率: {win_rate:.1f}%")
    print(f"总收益: {total_profit:.0f}元")
    
    if len(trades) > 0:
        print(f"平均收益: {df_trades['profit'].mean():.0f}元")
        print(f"最大盈利: {df_trades['profit'].max():.0f}元")
        print(f"最大亏损: {df_trades['profit'].min():.0f}元")
    
    api.close()
    
    # 打印交易明细
    if trades:
        print("\n交易明细:")
        for i, t in enumerate(trades, 1):
            print(f"  {i}. {t['entry_date']} -> {t['exit_date']}: {t['entry_price']} -> {t['exit_price']}, 盈亏: {t['profit']:.0f}元")
    
    # 保存结果
    result = {
        '回测合约': 'CZCE.TA509',
        '回测周期': f'{start_date} ~ {end_date}',
        'K线数量': len(df),
        '总交易次数': len(trades),
        '盈利次数': win_count,
        '亏损次数': loss_count,
        '胜率': f'{win_rate:.1f}%',
        '总收益': f'{total_profit:.0f}元',
        '交易明细': trades
    }
    
    with open('/home/admin/.openclaw/workspace/codeman/pta_analysis/backtest_result.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print("\n结果已保存到 backtest_result.json")
    return result

if __name__ == '__main__':
    main()
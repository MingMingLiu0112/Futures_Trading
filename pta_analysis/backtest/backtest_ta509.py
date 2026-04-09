#!/usr/bin/env python3
"""
PTA期货MACD策略回测
使用TqSdk天勤量化数据
"""
from tqsdk import TqApi, TqAuth, TqKq
import pandas as pd
import numpy as np
import json
from datetime import datetime

def calculate_macd(close, fast=12, slow=26, signal=9):
    """计算MACD指标"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    diff = ema_fast - ema_slow
    dea = diff.ewm(span=signal, adjust=False).mean()
    macd = (diff - dea) * 2
    return diff, dea, macd

def backtest_macd_strategy(df):
    """
    MACD金叉死叉策略回测
    - 金叉：DIFF上穿DEA -> 买入
    - 死叉：DIFF下穿DEA -> 卖出
    """
    df = df.copy()
    df['diff'], df['dea'], df['macd'] = calculate_macd(df['close'])
    
    # 生成交易信号
    df['signal'] = 0
    df.loc[df['diff'] > df['dea'], 'signal'] = 1   # 金叉买入
    df.loc[df['diff'] < df['dea'], 'signal'] = -1  # 死叉卖出
    
    # 持仓状态
    position = 0
    trades = []
    entry_price = 0
    entry_date = None
    
    for i in range(1, len(df)):
        if df['signal'].iloc[i] == 1 and position == 0:
            # 金叉，开多仓
            position = 1
            entry_price = df['close'].iloc[i]
            entry_date = df['datetime'].iloc[i]
        elif df['signal'].iloc[i] == -1 and position == 1:
            # 死叉，平多仓
            exit_price = df['close'].iloc[i]
            profit = (exit_price - entry_price) * position * 10  # PTA每手10吨
            trades.append({
                'entry_date': entry_date,
                'exit_date': df['datetime'].iloc[i],
                'entry_price': entry_price,
                'exit_price': exit_price,
                'profit': profit,
                'holding_days': (df['datetime'].iloc[i] - entry_date).days
            })
            position = 0
    
    return trades, df

def generate_report(df, trades):
    """生成回测报告"""
    if not trades:
        return {
            'contract': 'CZCE.TA509',
            'period': f"{pd.to_datetime(df.iloc[0]['datetime'], unit='ns').strftime('%Y-%m-%d')} ~ {pd.to_datetime(df.iloc[-1]['datetime'], unit='ns').strftime('%Y-%m-%d')}",
            'total_trades': 0,
            'message': '无交易信号'
        }
    
    df_trades = pd.DataFrame(trades)
    
    total_profit = df_trades['profit'].sum()
    win_trades = df_trades[df_trades['profit'] > 0]
    lose_trades = df_trades[df_trades['profit'] <= 0]
    
    win_rate = len(win_trades) / len(df_trades) * 100 if len(df_trades) > 0 else 0
    avg_profit = df_trades['profit'].mean()
    max_profit = df_trades['profit'].max()
    max_loss = df_trades['profit'].min()
    
    # 收益曲线
    df_trades['cumsum'] = df_trades['profit'].cumsum()
    
    report = {
        '回测合约': 'CZCE.TA509（PTA 2025年5月合约）',
        '回测周期': f"{pd.to_datetime(df.iloc[0]['datetime'], unit='ns').strftime('%Y-%m-%d')} ~ {pd.to_datetime(df.iloc[-1]['datetime'], unit='ns').strftime('%Y-%m-%d')}",
        'K线数量': str(len(df)),
        '总交易次数': str(len(df_trades)),
        '盈利次数': str(len(win_trades)),
        '亏损次数': str(len(lose_trades)),
        '胜率': f'{win_rate:.1f}%',
        '总收益': f'{total_profit:.0f}元',
        '平均收益': f'{avg_profit:.0f}元',
        '最大单笔盈利': f'{max_profit:.0f}元',
        '最大单笔亏损': f'{max_loss:.0f}元',
        '平均持仓天数': f"{df_trades['holding_days'].mean():.1f}天",
        '交易明细': df_trades[['entry_date', 'exit_date', 'entry_price', 'exit_price', 'profit']].to_dict('records')
    }
    
    return report

def format_feishu_table(report):
    """格式化飞书表格内容"""
    rows = []
    rows.append(['指标', '数值'])
    rows.append(['回测合约', report['回测合约']])
    rows.append(['回测周期', report['回测周期']])
    rows.append(['K线数量', report['K线数量']])
    rows.append(['总交易次数', report['总交易次数']])
    rows.append(['盈利次数', report['盈利次数']])
    rows.append(['亏损次数', report['亏损次数']])
    rows.append(['胜率', report['胜率']])
    rows.append(['总收益', report['总收益']])
    rows.append(['平均收益', report['平均收益']])
    rows.append(['最大单笔盈利', report['最大单笔盈利']])
    rows.append(['最大单笔亏损', report['最大单笔亏损']])
    rows.append(['平均持仓天数', report['平均持仓天数']])
    
    # 添加交易明细表头
    rows.append([])
    rows.append(['入场日期', '出场日期', '入场价', '出场价', '盈亏(元)'])
    
    for t in report.get('交易明细', []):
        entry_dt = pd.to_datetime(t['entry_date'], unit='ns').strftime('%Y-%m-%d') if hasattr(t['entry_date'], 'numpy') else str(t['entry_date'])[:10]
        exit_dt = pd.to_datetime(t['exit_date'], unit='ns').strftime('%Y-%m-%d') if hasattr(t['exit_date'], 'numpy') else str(t['exit_date'])[:10]
        rows.append([entry_dt, exit_dt, f"{t['entry_price']}", f"{t['exit_price']}", f"{t['profit']:.0f}"])
    
    return rows

async def main():
    print("=" * 50)
    print("PTA MACD策略回测")
    print("=" * 50)
    
    api = TqApi(TqKq(), auth=TqAuth('test', 'test'))
    
    # 获取日K线数据
    print("\n获取TA509日K线数据...")
    klines = api.get_kline_serial('CZCE.TA509', 86400, data_length=300)
    await api._wait_update()
    
    # 转换数据
    df = klines.to_pandas()
    df['datetime'] = pd.to_datetime(df['datetime'], unit='ns')
    df = df.sort_values('datetime').reset_index(drop=True)
    
    print(f"K线数量: {len(df)}")
    print(f"时间范围: {df.iloc[0]['datetime'].strftime('%Y-%m-%d')} ~ {df.iloc[-1]['datetime'].strftime('%Y-%m-%d')}")
    
    # 运行回测
    print("\n运行MACD金叉死叉策略回测...")
    trades, df_with_macd = backtest_macd_strategy(df)
    
    # 生成报告
    report = generate_report(df, trades)
    
    print("\n" + "=" * 50)
    print("回测结果")
    print("=" * 50)
    for k, v in report.items():
        if k != '交易明细':
            print(f"{k}: {v}")
    
    # 格式化飞书表格
    table_rows = format_feishu_table(report)
    
    await api.close()
    
    # 输出飞书表格格式
    print("\n" + "=" * 50)
    print("飞书表格内容")
    print("=" * 50)
    for row in table_rows:
        print(" | ".join(str(x) for x in row))
    
    # 保存结果到文件
    with open('/home/admin/.openclaw/workspace/codeman/pta_analysis/backtest_result.json', 'w', encoding='utf-8') as f:
        json.dump({'report': report, 'table_rows': table_rows}, f, ensure_ascii=False, default=str)
    
    print("\n回测结果已保存到 backtest_result.json")
    return report, table_rows

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
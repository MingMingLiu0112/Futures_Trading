#!/usr/bin/env python3
"""
PTA期货日K线图生成脚本
生成包含MA5/MA10/MA20均线、成交量、当前价格标注的日K线图
"""

import os
import sys
import warnings
warnings.filterwarnings('ignore')

# 设置代理
os.environ['http_proxy'] = 'http://127.0.0.1:7890'
os.environ['https_proxy'] = 'http://127.0.0.1:7890'

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Rectangle
import akshare as ak

# 设置字体
plt.rcParams['axes.unicode_minus'] = False

# 尝试找到可用的中文字体
import matplotlib.font_manager as fm
available_fonts = [f.name for f in fm.fontManager.ttflist]
chinese_fonts = ['SimHei', 'WenQuanYi Micro Hei', 'Noto Sans CJK SC', 'Noto Sans CJK', 'Source Han Sans SC', 'Droid Sans Fallback']
font_found = None
for font in chinese_fonts:
    if font in available_fonts:
        font_found = font
        break

if font_found:
    plt.rcParams['font.family'] = font_found
    print(f"使用中文字体: {font_found}")
else:
    print("警告: 未找到中文字体，使用默认字体")

def get_pta_data():
    """获取PTA期货历史日K线数据"""
    print("正在获取PTA期货数据...")
    try:
        # 使用akshare获取PTA期货历史数据 (sina接口)
        df = ak.futures_zh_daily_sina(symbol='TA0')
        print(f"成功获取数据，共 {len(df)} 条记录")
        print(f"最新数据日期: {df['date'].iloc[-1]}")
        return df
    except Exception as e:
        print(f"获取数据失败: {e}")
        import traceback
        traceback.print_exc()
        return None

def plot_kline_chart(df, output_path):
    """绘制PTA日K线图"""
    
    # 处理数据
    df['date'] = pd.to_datetime(df['date'])
    
    # 取最近100个交易日数据
    df = df.tail(100).reset_index(drop=True)
    print(f"绘制最近 {len(df)} 个交易日数据")
    
    # 计算均线
    df['MA5'] = df['close'].rolling(window=5).mean()
    df['MA10'] = df['close'].rolling(window=10).mean()
    df['MA20'] = df['close'].rolling(window=20).mean()
    
    # 创建图表
    fig = plt.figure(figsize=(16, 10), facecolor='white')
    
    # 设置网格
    gs = fig.add_gridspec(4, 1, height_ratios=[3, 1, 0.5, 0.1], hspace=0.1)
    ax1 = fig.add_subplot(gs[0])  # K线图
    ax2 = fig.add_subplot(gs[1], sharex=ax1)  # 成交量
    
    # ========== K线图 ==========
    width = 0.6
    up = df[df['close'] >= df['open']]
    down = df[df['close'] < df['open']]
    
    # 绘制涨跌
    for idx in up.index:
        color = '#DC143C'  # 红色涨
        height = up.loc[idx, 'close'] - up.loc[idx, 'open']
        rect = Rectangle((idx - width/2, up.loc[idx, 'open']), width, max(height, 0.001),
                         facecolor=color, edgecolor=color, linewidth=0.5)
        ax1.add_patch(rect)
        ax1.plot([idx, idx], [up.loc[idx, 'low'], up.loc[idx, 'high']], 
                color=color, linewidth=0.8)
    
    for idx in down.index:
        color = '#00C853'  # 绿色跌
        height = down.loc[idx, 'close'] - down.loc[idx, 'open']
        rect = Rectangle((idx - width/2, down.loc[idx, 'close']), width, max(abs(height), 0.001),
                         facecolor=color, edgecolor=color, linewidth=0.5)
        ax1.add_patch(rect)
        ax1.plot([idx, idx], [down.loc[idx, 'low'], down.loc[idx, 'high']], 
                color=color, linewidth=0.8)
    
    # 绘制均线
    ax1.plot(df.index, df['MA5'], color='#FF6B6B', linewidth=1.5, label='MA5', alpha=0.9)
    ax1.plot(df.index, df['MA10'], color='#4ECDC4', linewidth=1.5, label='MA10', alpha=0.9)
    ax1.plot(df.index, df['MA20'], color='#FFE66D', linewidth=1.5, label='MA20', alpha=0.9)
    
    # 获取当前价格
    current_price = df['close'].iloc[-1]
    current_date = df['date'].iloc[-1]
    
    # 标注当前价格
    ax1.axhline(y=current_price, color='purple', linestyle='--', linewidth=1, alpha=0.7)
    ax1.annotate(f'{current_price:.0f}', 
                xy=(len(df)-1, current_price),
                xytext=(len(df)-1 + 3, current_price),
                fontsize=12, fontweight='bold', color='purple',
                bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', alpha=0.7),
                arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0'))
    
    # 设置K线图属性
    ax1.set_ylabel('Price', fontsize=12)
    ax1.set_title(f'PTA Futures Daily K-Line (MA5/MA10/MA20) - {current_date.strftime("%Y-%m-%d")}', 
                  fontsize=16, fontweight='bold', pad=10)
    ax1.legend(loc='upper left', fontsize=10)
    ax1.grid(True, alpha=0.3, linestyle='--')
    ax1.set_xlim(-1, len(df) + 8)
    ax1.set_ylim(df['low'].min() * 0.995, df['high'].max() * 1.005)
    
    # 隐藏x轴标签
    plt.setp(ax1.get_xticklabels(), visible=False)
    
    # ========== 成交量图 ==========
    colors = ['#DC143C' if df.loc[i, 'close'] >= df.loc[i, 'open'] else '#00C853' for i in df.index]
    ax2.bar(df.index, df['volume'], color=colors, width=0.8, alpha=0.8)
    ax2.set_ylabel('Volume', fontsize=10)
    ax2.grid(True, alpha=0.3, linestyle='--')
    ax2.set_ylim(0, df['volume'].max() * 1.1)
    plt.setp(ax2.get_xticklabels(), visible=False)
    
    # ========== 信息面板 ==========
    # 计算涨跌幅
    if len(df) > 1:
        prev_close = df['close'].iloc[-2]
        change = current_price - prev_close
        change_pct = (change / prev_close) * 100
        change_color = '#DC143C' if change >= 0 else '#00C853'
        change_sign = '+' if change >= 0 else ''
        
        info_text = f"Latest: {current_price:.0f}  {change_sign}{change:.0f} ({change_sign}{change_pct:.2f}%)"
        fig.text(0.02, 0.02, info_text, fontsize=12, fontweight='bold', color=change_color)
        
        ma_text = f"MA5: {df['MA5'].iloc[-1]:.0f}  MA10: {df['MA10'].iloc[-1]:.0f}  MA20: {df['MA20'].iloc[-1]:.0f}"
        fig.text(0.4, 0.02, ma_text, fontsize=11, color='#333333')
        
        vol_text = f"Volume: {df['volume'].iloc[-1]:,.0f}"
        fig.text(0.8, 0.02, vol_text, fontsize=10, color='#666666')
    
    # 调整布局
    plt.tight_layout()
    plt.subplots_adjust(bottom=0.08)
    
    # 保存图表
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches='tight', 
                facecolor='white', edgecolor='none')
    plt.close()
    
    print(f"Chart saved to: {output_path}")

def main():
    output_path = '/home/admin/.openclaw/workspace/codeman/pta_analysis/charts/pta_daily.png'
    
    # 获取数据
    df = get_pta_data()
    
    if df is not None:
        # 绘制图表
        plot_kline_chart(df, output_path)
        print("Done!")
    else:
        print("Data acquisition failed, cannot generate chart")
        sys.exit(1)

if __name__ == '__main__':
    main()

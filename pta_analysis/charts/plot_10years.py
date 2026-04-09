#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PTA十年K线图"""
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

# 设置中文字体
try:
    plt.rcParams['font.sans-serif'] = ['Noto Sans CJK SC', 'WenQuanYi Micro Hei', 'SimHei', 'DejaVu Sans']
except:
    pass
plt.rcParams['axes.unicode_minus'] = False

# 读取数据
df = pd.read_csv('/home/admin/.openclaw/workspace/codeman/pta_analysis/data/pta_1day.csv')
df['datetime'] = pd.to_datetime(df['datetime'])
df = df.sort_values('datetime').reset_index(drop=True)

print(f"数据: {df['datetime'].iloc[0].strftime('%Y-%m-%d')} ~ {df['datetime'].iloc[-1].strftime('%Y-%m-%d')}, 共{len(df)}条")

# 计算均线
df['ma20'] = df['close'].rolling(20).mean()
df['ma60'] = df['close'].rolling(60).mean()
df['ma120'] = df['close'].rolling(120).mean()
df['ma250'] = df['close'].rolling(250).mean()

# 涨跌幅
df['pct_change'] = df['close'].pct_change() * 100

# 创建图表
fig, axes = plt.subplots(3, 1, figsize=(20, 14), 
                         gridspec_kw={'height_ratios': [3, 0.5, 1]},
                         facecolor='#0d1117')
for ax in axes:
    ax.set_facecolor('#0d1117')

# === 主图：K线 ===
ax = axes[0]
dates = df['datetime']

# K线用颜色区分涨跌
for i in range(len(df)):
    row = df.iloc[i]
    color = '#26a641' if row['close'] >= row['open'] else '#f85149'
    lw = 1
    ax.plot([i, i], [row['low'], row['high']], color=color, linewidth=lw)
    body_top = max(row['open'], row['close'])
    body_bot = min(row['open'], row['close'])
    ax.add_patch(plt.Rectangle((i-0.4, body_bot), 0.8, body_top-body_bot,
                                color=color, linewidth=0))

# 均线
ax.plot(df.index, df['ma20'], color='#58a6ff', linewidth=1.2, label='MA20', alpha=0.8)
ax.plot(df.index, df['ma60'], color='#ffc107', linewidth=1.2, label='MA60', alpha=0.8)
ax.plot(df.index, df['ma120'], color='#f78166', linewidth=1.2, label='MA120', alpha=0.8)
ax.plot(df.index, df['ma250'], color='#a371f7', linewidth=1.2, label='MA250', alpha=0.8)

# 最新价标注
latest = df.iloc[-1]
ax.axhline(y=latest['close'], color='#58a6ff', linestyle='--', alpha=0.5, linewidth=0.8)
ax.text(len(df)-1, latest['close']*1.01, f"{latest['close']:.0f}", 
        color='#58a6ff', fontsize=10, ha='right', va='bottom')

# 成本线（当前成本区间）
px = 9700
cost_low = px * 0.655 + 600
cost_high = px * 0.655 + 1000
ax.axhline(y=cost_low, color='#ffc107', linestyle=':', alpha=0.4, linewidth=1)
ax.axhline(y=cost_high, color='#ffc107', linestyle=':', alpha=0.4, linewidth=1)
ax.text(20, cost_low, f'Cost Low {cost_low:.0f}', color='#ffc107', fontsize=8, alpha=0.7)
ax.text(20, cost_high, f'Cost High {cost_high:.0f}', color='#ffc107', fontsize=8, alpha=0.7)

ax.set_xlim(-50, len(df)+50)
price_min = df['low'].min() * 0.95
price_max = df['high'].max() * 1.05
ax.set_ylim(price_min, price_max)
ax.legend(loc='upper left', fontsize=9, framealpha=0.3)
ax.set_ylabel('PTA Price (CNY)', fontsize=10, color='white')
ax.tick_params(axis='y', labelcolor='white')
ax.tick_params(axis='x', length=0)
ax.set_xticks([])

# Cost zone
ax.axhspan(cost_low, cost_high, alpha=0.08, color='#ffc107', label='Cost Zone')

# 年份标注
for year in range(2016, 2027):
    idx = df[df['datetime'].dt.year == year].index[0] if year <= 2026 else len(df)-1
    ax.text(idx, price_min + 100, str(year), color='#8b949e', fontsize=9, alpha=0.6)

# === 成交量 ===
ax_vol = axes[1]
colors = ['#26a641' if df.iloc[i]['close'] >= df.iloc[i]['open'] else '#f85149' for i in range(len(df))]
ax_vol.bar(df.index, df['volume']/1e4, color=colors, width=1.0, alpha=0.7)
ax_vol.set_xlim(-50, len(df)+50)
ax_vol.set_ylim(0, df['volume'].max()/1e4 * 1.1)
ax_vol.set_ylabel('Vol (万手)', fontsize=8, color='white')
ax_vol.tick_params(axis='both', labelsize=7, colors='white')
ax_vol.set_xticks([])
ax_vol.spines['top'].set_visible(False)
ax_vol.spines['right'].set_visible(False)

# === 持仓 ===
ax_oi = axes[2]
ax_oi.fill_between(df.index, df['close_oi']/1e4, alpha=0.3, color='#58a6ff')
ax_oi.plot(df.index, df['close_oi']/1e4, color='#58a6ff', linewidth=0.8)
ax_oi.set_xlim(-50, len(df)+50)
ax_oi.set_ylim(0, df['close_oi'].max()/1e4 * 1.1)
ax_oi.set_ylabel('OI (万手)', fontsize=8, color='white')
ax_oi.tick_params(axis='both', labelsize=7, colors='white')
ax_oi.set_xticks([])
ax_oi.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
ax_oi.spines['top'].set_visible(False)
ax_oi.spines['right'].set_visible(False)

# 统计信息
latest_date = df['datetime'].iloc[-1].strftime('%Y-%m-%d')
stats_text = (f"Period: 2016-01-04 ~ {latest_date}  ({len(df)} trading days)\n"
              f"Latest: {latest['close']:.0f}  High: {df['high'].max():.0f}  Low: {df['low'].min():.0f}\n"
              f"Ann.Vol: {df['pct_change'].std()*np.sqrt(252):.1f}%  MA20:{latest['ma20']:.0f}  MA60:{latest['ma60']:.0f}  MA250:{latest['ma250']:.0f}")

fig.text(0.02, 0.01, stats_text, color='#8b949e', fontsize=9, 
         family='monospace', transform=fig.transFigure)

# 标题
fig.suptitle('PTA Futures Daily K-Line (10 Years: 2016-2026)', fontsize=16, color='white', y=0.98)

plt.tight_layout(rect=[0, 0.06, 1, 0.97])
output = '/home/admin/.openclaw/workspace/codeman/pta_analysis/charts/pta_10years.png'
plt.savefig(output, dpi=100, facecolor='#0d1117', edgecolor='none', bbox_inches='tight')
plt.close()
print(f"保存: {output}")

# 额外统计
print(f"\n=== 十年统计 ===")
print(f"最高价: ¥{df['high'].max():.0f} ({df.loc[df['high'].idxmax(), 'datetime'].strftime('%Y-%m-%d')})")
print(f"最低价: ¥{df['low'].min():.0f} ({df.loc[df['low'].idxmin(), 'datetime'].strftime('%Y-%m-%d')})")
print(f"MA20: ¥{latest['ma20']:.0f}")
print(f"MA60: ¥{latest['ma60']:.0f}")
print(f"MA250: ¥{latest['ma250']:.0f}")
print(f"当前价位置: {(latest['close'] - df['low'].min())/(df['high'].max() - df['low'].min())*100:.1f}% (十年区间内)")

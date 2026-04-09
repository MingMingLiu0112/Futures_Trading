#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PTA 1min 缠论 | 2026-04-03 夜盘"""
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from czsc.py.objects import RawBar
from czsc.py.analyze import CZSC
from czsc.py.enum import Freq
import warnings
warnings.filterwarnings('ignore')

WORKSPACE = '/home/admin/.openclaw/workspace/codeman/pta_analysis'
DATA_DIR = f'{WORKSPACE}/data'

# 加载1min数据
df = pd.read_csv(f'{DATA_DIR}/pta_1min.csv')
df['datetime'] = pd.to_datetime(df['datetime'])
april3 = df[df['datetime'].dt.date == pd.Timestamp('2026-04-03').date()]
april3 = april3[april3['close'].notna() & (april3['close'] > 0)]
april3 = april3.sort_values('datetime').reset_index(drop=True)
print(f'数据: {len(april3)}条, {april3["datetime"].min()} ~ {april3["datetime"].max()}')

# 构建RawBar映射
bars = []
bar_dt_to_idx = {}
for i, (_, r) in enumerate(april3.iterrows()):
    bar = RawBar(symbol='TA', id=i, dt=r['datetime'],
                 open=float(r['open']), high=float(r['high']),
                 low=float(r['low']), close=float(r['close']),
                 vol=float(r['volume']), amount=0, freq=Freq.F1)
    bars.append(bar)
    bar_dt_to_idx[r['datetime']] = i

# 缠论
c = CZSC(bars)
print(f'笔数: {len(c.bi_list)}')
for bi in c.bi_list:
    x0 = bar_dt_to_idx.get(bi.raw_bars[0].dt, 0)
    x1 = bar_dt_to_idx.get(bi.raw_bars[-1].dt, 0)
    print(f"  {bi.direction} | {bi.high:.0f}~{bi.low:.0f} | 幅度={bi.length} | 动能={bi.power:.0f} | bars[{x0}:{x1+1}]")

# 画图
fig, axes = plt.subplots(2, 1, figsize=(24, 10), gridspec_kw={'height_ratios': [3, 1]}, facecolor='#0d1117')
for ax in axes:
    ax.set_facecolor('#0d1117')

# K线
ax = axes[0]
for i, (_, r) in enumerate(april3.iterrows()):
    color = '#26a641' if r['close'] >= r['open'] else '#f85149'
    ax.plot([i, i], [r['low'], r['high']], color=color, linewidth=0.8)
    body_top = max(r['open'], r['close'])
    body_bot = min(r['open'], r['close'])
    ax.add_patch(plt.Rectangle((i-0.4, body_bot), 0.8, body_top-body_bot, color=color, linewidth=0))

# 笔
colors = {'Up': '#26a641', 'Down': '#f85149'}
for bi in c.bi_list:
    x0 = bar_dt_to_idx.get(bi.raw_bars[0].dt, 0)
    x1 = bar_dt_to_idx.get(bi.raw_bars[-1].dt, x0)
    color = colors.get(bi.direction, '#58a6ff')
    ax.plot([x0, x1], [bi.high, bi.low], color=color, linewidth=2.5, alpha=0.9)
    mid_x = (x0 + x1) / 2
    mid_y = (bi.high + bi.low) / 2
    ax.text(mid_x, mid_y, f'{str(bi.direction)[0]}{bi.length}',
            color=color, fontsize=8, ha='center', va='center',
            bbox=dict(boxstyle='round,pad=0.2', facecolor='#0d1117', alpha=0.7))

# 最新价标注
ax.axhline(y=april3.iloc[-1]['close'], color='#58a6ff', linestyle='--', alpha=0.5)
ax.text(len(april3)-1, april3.iloc[-1]['close']*1.003,
        f"{april3.iloc[-1]['close']:.0f}", color='#58a6ff', fontsize=9, ha='right')

ax.set_xlim(-3, len(april3)+3)
ax.set_ylim(april3['low'].min()-20, april3['high'].max()+20)
ax.set_ylabel('PTA Price (CNY)', color='white', fontsize=10)
ax.tick_params(axis='y', labelcolor='white')
ax.set_xticks([])
ax.legend(loc='upper left', fontsize=9)

# 信息面板
info = (f"TA 1min | 2026-04-03 Night 01:00-06:59\n"
         f"K={len(april3)} 笔={len(c.bi_list)}  "
         f"O={april3.iloc[0]['open']:.0f} H={april3['high'].max():.0f} "
         f"L={april3['low'].min():.0f} C={april3.iloc[-1]['close']:.0f}")
ax.text(0.01, 0.99, info, transform=ax.transAxes, color='#8b949e',
        fontsize=9, va='top', ha='left', family='monospace',
        bbox=dict(boxstyle='round', facecolor='#161b22', alpha=0.8))

# 成交量
ax2 = axes[1]
for i, (_, r) in enumerate(april3.iterrows()):
    color = '#26a641' if r['close'] >= r['open'] else '#f85149'
    ax2.bar(i, r['volume']/1e4, color=color, width=1.0, alpha=0.7)
ax2.set_xlim(-3, len(april3)+3)
ax2.set_ylabel('Vol (万手)', color='white', fontsize=8)
ax2.tick_params(axis='both', labelsize=7, colors='white')
ax2.set_xticks([])
ax2.spines['top'].set_visible(False)

fig.suptitle('PTA 1min Chan Theory | 2026-04-03 Night Session (01:00-06:59)', fontsize=13, color='white', y=0.99)
plt.tight_layout(rect=[0, 0, 1, 0.97])
out = f'{WORKSPACE}/charts/chan_april3.png'
plt.savefig(out, dpi=120, facecolor='#0d1117', edgecolor='none', bbox_inches='tight')
plt.close()
print(f'\n保存: {out}')

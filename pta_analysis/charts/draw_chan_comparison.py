#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA 缠论笔对比图 - 同时显示 CZSC笔 + 用户指出漏掉的笔
"""
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

# 加载数据
df = pd.read_csv(f'{DATA_DIR}/pta_1min.csv')
df['datetime'] = pd.to_datetime(df['datetime'])
april3 = df[df['datetime'].dt.date == pd.Timestamp('2026-04-03').date()]
april3 = april3[april3['close'].notna() & (april3['close']>0)].sort_values('datetime').reset_index(drop=True)
april3['real_time'] = april3['datetime'] + pd.Timedelta(hours=8)

# 过滤 10:00-15:00 关键区间
t_start, t_end = '10:00', '15:00'
mask = (april3['real_time'].dt.strftime('%H:%M') >= t_start) & (april3['real_time'].dt.strftime('%H:%M') <= t_end)
sub = april3[mask].reset_index(drop=True)

bars = []
bar_dt_to_idx = {}
for i, (_, r) in enumerate(sub.iterrows()):
    b = RawBar(symbol='TA', id=i, dt=r['real_time'],
        open=float(r['open']), high=float(r['high']),
        low=float(r['low']), close=float(r['close']),
        vol=float(r['volume']), amount=0, freq=Freq.F1)
    bars.append(b)
    bar_dt_to_idx[r['real_time']] = i

# CZSC 笔
c = CZSC(bars)
dt_to_idx = {b.dt: i for i, b in enumerate(bars)}

# 用户指出的漏掉笔（手动标注，基于K线分析）
# 规则：3根以上同向K线创出新高/新低
user_bis = [
    # (start_idx, end_idx, direction, label)
    (21, 28, 'Up',   '1'),   # 10:36~10:43 6810→6874 (用户笔1)
    (29, 33, 'Down', '2'),   # 10:44~10:49 6874→6830 (用户笔2)
    (75, 96, 'Up',   '3'),   # 13:30~13:44 6894→6952 (用户笔3)
    (92, 98, 'Down', '4'),    # 13:47~13:53 6952→6948 (用户笔4)
    (116, 129, 'Down', '5'),  # 14:09~14:23 6996→6944 (用户笔5)
    (129, 148, 'Up', '6'),   # 14:23~14:43 6944→7000 (用户笔6)
]

# 验证这几根笔的K线
print("=== 用户指出的漏掉笔验证 ===")
for start_i, end_i, direction, label in user_bis:
    start_dt = bars[start_i].dt
    end_dt = bars[end_i].dt
    seg_bars = bars[start_i:end_i+1]
    high = max(b.high for b in seg_bars)
    low = min(b.low for b in seg_bars)
    print(f"笔{label}: bars[{start_i}:{end_i}] {start_dt.strftime('%H:%M')}~{end_dt.strftime('%H:%M')} "
          f"{direction} 高={high:.0f} 低={low:.0f} ({end_i-start_i+1}根K线)")

# 画图
fig, axes = plt.subplots(2, 1, figsize=(28, 12), gridspec_kw={'height_ratios': [3, 1]}, facecolor='#0d1117')
for ax in axes:
    ax.set_facecolor('#0d1117')

ax = axes[0]
ax2 = axes[1]

# 画K线
for i, b in enumerate(bars):
    color = '#26a641' if b.close >= b.open else '#f85149'
    ax.plot([i, i], [b.low, b.high], color=color, linewidth=0.8)
    body_top = max(b.open, b.close)
    body_bot = min(b.open, b.close)
    ax.add_patch(plt.Rectangle((i-0.4, body_bot), 0.8, body_top-body_bot, color=color, linewidth=0))

# CZSC 笔 (灰色虚线)
for bi in c.bi_list:
    x0 = dt_to_idx.get(bi.raw_bars[0].dt, 0)
    x1 = dt_to_idx.get(bi.raw_bars[-1].dt, x0)
    color = '#8b949e'
    ax.plot([x0, x1], [bi.high, bi.low], color=color, linewidth=2, alpha=0.6, linestyle='--')

# 用户漏掉的笔 (加粗彩色)
COLOR_MAP = {'Up': '#26a641', 'Down': '#f85149'}
for start_i, end_i, direction, label in user_bis:
    seg_bars = bars[start_i:end_i+1]
    high = max(b.high for b in seg_bars)
    low = min(b.low for b in seg_bars)
    color = COLOR_MAP.get(direction, '#58a6ff')
    ax.plot([start_i, end_i], [high, low], color=color, linewidth=3.5, alpha=0.9, zorder=10)
    mid_x = (start_i + end_i) / 2
    mid_y = (high + low) / 2
    ax.text(mid_x, mid_y, f'{label}', color='white', fontsize=10, ha='center', va='center',
            fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.3', facecolor=color, alpha=0.9, edgecolor='none'))

ax.set_xlim(-3, len(bars)+3)
ax.set_ylim(sub['low'].min()-15, sub['high'].max()+15)
ax.set_ylabel('PTA Price', color='white', fontsize=10)
ax.tick_params(axis='y', labelcolor='white')
ax.set_xticks([])

# 标注关键时间点
key_times = ['10:35', '10:44', '10:49', '13:30', '13:47', '14:09', '14:23']
for kt in key_times:
    try:
        idx = sub[sub['real_time'].dt.strftime('%H:%M') == kt].index[0]
        ax.axvline(x=idx, color='#30363d', linestyle=':', alpha=0.5, linewidth=0.8)
        ax.text(idx, ax.get_ylim()[0]+3, kt, color='#8b949e', fontsize=7, ha='center', rotation=0)
    except:
        pass

# 图例和标题
legend_elements = [
    plt.Line2D([0], [0], color='#8b949e', linewidth=2, linestyle='--', label='CZSC严格笔'),
    plt.Line2D([0], [0], color='#26a641', linewidth=3, label='用户指出漏掉笔(Up)'),
    plt.Line2D([0], [0], color='#f85149', linewidth=3, label='用户指出漏掉笔(Down)'),
]
ax.legend(handles=legend_elements, loc='upper left', fontsize=9, framealpha=0.8,
          facecolor='#161b22', edgecolor='#30363d', labelcolor='white')

ax.text(0.01, 0.99,
    f"CZSC严格笔: {len(c.bi_list)}笔  |  用户指出漏掉笔: {len(user_bis)}笔\n"
    f"区间: 10:00-15:00  ({len(bars)}根K线)",
    transform=ax.transAxes, color='#8b949e', fontsize=9, va='top', ha='left',
    family='monospace', bbox=dict(boxstyle='round', facecolor='#161b22', alpha=0.8))

# 成交量
for i, b in enumerate(bars):
    color = '#26a641' if b.close >= b.open else '#f85149'
    ax2.bar(i, b.vol/1e4, color=color, width=1.0, alpha=0.7)
ax2.set_xlim(-3, len(bars)+3)
ax2.set_ylabel('Vol (万手)', color='white', fontsize=8)
ax2.tick_params(axis='both', labelsize=7, colors='white')
ax2.set_xticks([])
ax2.spines['top'].set_visible(False)

fig.suptitle('PTA 1min 缠论笔对比 | CZSC严格笔 vs 用户指出漏掉笔', fontsize=13, color='white', y=0.99)
plt.tight_layout(rect=[0, 0, 1, 0.97])
plt.savefig(f'{WORKSPACE}/charts/chan_comparison.png', dpi=120,
            facecolor='#0d1117', edgecolor='none', bbox_inches='tight')
plt.close()
print(f"\n保存: {WORKSPACE}/charts/chan_comparison.png")

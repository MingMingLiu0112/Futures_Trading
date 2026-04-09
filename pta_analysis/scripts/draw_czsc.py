#!/usr/bin/env python3
import pandas as pd
from czsc.py.objects import RawBar
from czsc.py.analyze import CZSC
from czsc.py.enum import Freq
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

df = pd.read_csv('/home/admin/.openclaw/workspace/codeman/pta_analysis/data/pta_1min.csv')
df['datetime'] = pd.to_datetime(df['datetime'])
ap3 = df[df['datetime'].dt.date == pd.Timestamp('2026-04-03').date()]
ap3 = ap3[ap3['close'].notna() & (ap3['close'] > 0)]
ap3 = ap3.sort_values('datetime').reset_index(drop=True)
ap3['real_time'] = ap3['datetime'] + pd.Timedelta(hours=8)

bars = []
for i, (_, r) in enumerate(ap3.iterrows()):
    bars.append(RawBar(symbol='TA', id=i, dt=r['real_time'],
        open=float(r['open']), high=float(r['high']), low=float(r['low']),
        close=float(r['close']), vol=float(r['volume']), amount=0, freq=Freq.F1))

d2i = {b.dt: i for i, b in enumerate(bars)}
c = CZSC(bars)
print('CZSC:', len(c.bi_list), 'bi')

fig, axes = plt.subplots(2, 1, figsize=(40, 14), facecolor='#0d1117')
for ax in axes:
    ax.set_facecolor('#0d1117')
ax, ax2 = axes

for i, b in enumerate(bars):
    col = '#26a641' if b.close >= b.open else '#f85149'
    ax.plot([i, i], [b.low, b.high], color=col, linewidth=0.8)
    bot = b.open if b.open < b.close else b.close
    h = abs(b.close - b.open)
    ax.add_patch(plt.Rectangle((i-0.4, bot), 0.8, h, color=col))

COL = {'Up': '#26a641', 'Down': '#f85149'}
for bi in c.bi_list:
    x0 = d2i[bi.raw_bars[0].dt]
    x1 = d2i[bi.raw_bars[-1].dt]
    col = COL.get(str(bi.direction), '#8b949e')
    ax.plot([x0, x1], [bi.high, bi.low], color=col, linewidth=2.5, alpha=0.9)

pmin = min(b.low for b in bars)
pmax = max(b.high for b in bars)
ax.set_xlim(-2, len(bars)+2)
ax.set_ylim(pmin-30, pmax+30)
ax.tick_params(axis='y', labelcolor='white')
ax.set_xticks([])

for kh in ['09:00', '10:00', '11:00', '13:00', '14:00', '15:00']:
    mask = ap3['real_time'].dt.strftime('%H:%M') == kh
    if mask.any():
        idx = int(ap3[mask].index[0])
        ax.axvline(x=idx, color='#30363d', linestyle=':', alpha=0.6)
        ax.text(idx, pmin-20, kh, color='#8b949e', fontsize=8, ha='center')

info = 'CZSC: {}bi  4月3日'.format(len(c.bi_list))
ax.text(0.01, 0.99, info, transform=ax.transAxes, color='#8b949e',
        fontsize=10, va='top', ha='left', family='monospace',
        bbox=dict(boxstyle='round', facecolor='#161b22', alpha=0.8))

for i, b in enumerate(bars):
    col = '#26a641' if b.close >= b.open else '#f85149'
    ax2.bar(i, b.vol/1e4, color=col, width=1.0, alpha=0.7)
ax2.set_xlim(-2, len(bars)+2)
ax2.set_ylabel('Vol', color='white', fontsize=8)
ax2.tick_params(axis='both', labelsize=7, colors='white')
ax2.set_xticks([])
ax2.spines['top'].set_visible(False)

fig.suptitle('PTA 1min Chan | CZSC | 4月3日', fontsize=14, color='white')
plt.tight_layout(rect=[0, 0, 1, 0.97])
plt.savefig('/home/admin/.openclaw/workspace/codeman/pta_analysis/charts/chan_czsc_full.png', dpi=100, facecolor='#0d1117', bbox_inches='tight')
plt.close()
print('saved')

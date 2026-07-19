#!/usr/bin/env python3
import pandas as pd
from czsc.py.objects import RawBar
from czsc.py.analyze import CZSC
from czsc.py.enum import Freq
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')

DATA = '/home/admin/.openclaw/workspace/codeman/pta_analysis/data'
WORK = '/home/admin/.openclaw/workspace/codeman/pta_analysis'

df = pd.read_csv(DATA + '/pta_1min.csv')
df['datetime'] = pd.to_datetime(df['datetime'])
ap3 = df[df['datetime'].dt.date == pd.Timestamp('2026-04-03').date()]
ap3 = ap3[ap3['close'].notna() & (ap3['close'] > 0)]
ap3 = ap3.sort_values('datetime').reset_index(drop=True)
ap3['real_time'] = ap3['datetime'] + pd.Timedelta(hours=8)

m = (ap3['real_time'].dt.strftime('%H:%M') >= '10:00') & (ap3['real_time'].dt.strftime('%H:%M') <= '15:00')
sub = ap3[m].reset_index(drop=True)

bars = []
for i, (_, r) in enumerate(sub.iterrows()):
    bars.append(RawBar(symbol='TA', id=i, dt=r['real_time'],
        open=float(r['open']), high=float(r['high']), low=float(r['low']),
        close=float(r['close']), vol=float(r['volume']), amount=0, freq=Freq.F1))

d2i = {b.dt: i for i, b in enumerate(bars)}
c = CZSC(bars)

def find_rev(bi_bars, direction):
    if len(bi_bars) < 4:
        return []
    revs = []
    if direction == 'Up':
        sc = bi_bars[0].close
        for i in range(2, len(bi_bars) - 2):
            if bi_bars[i].high > sc + 5:
                revs.append((i, 'Up', bi_bars[i].high - sc))
    else:
        sc = bi_bars[0].close
        for i in range(2, len(bi_bars) - 2):
            if bi_bars[i].low < sc - 5:
                revs.append((i, 'Down', sc - bi_bars[i].low))
    return revs

fixed = []
for bi in c.bi_list:
    revs = find_rev(bi.raw_bars, bi.direction.value)
    if not revs:
        fixed.append({'d': bi.direction.value, 'sd': bi.raw_bars[0].dt,
                     'ed': bi.raw_bars[-1].dt, 'h': bi.high, 'l': bi.low, 'a': bi.length})
    else:
        raw = bi.raw_bars
        prev = 0
        for si, sd, sa in revs:
            seg = raw[prev:si+1]
            if len(seg) >= 2:
                d2 = 'Up' if seg[-1].high > seg[0].high else 'Down'
                fixed.append({'d': d2, 'sd': seg[0].dt, 'ed': seg[-1].dt,
                             'h': max(b.high for b in seg), 'l': min(b.low for b in seg), 'a': bi.length})
            prev = si
        seg = raw[prev:]
        if len(seg) >= 2:
            d2 = 'Up' if seg[-1].high > seg[0].high else 'Down'
            fixed.append({'d': d2, 'sd': seg[0].dt, 'ed': seg[-1].dt,
                         'h': max(b.high for b in seg), 'l': min(b.low for b in seg), 'a': bi.length})

merged = []
for seg in fixed:
    if not merged:
        merged.append(seg)
    elif seg['d'] == merged[-1]['d']:
        if seg['a'] < merged[-1]['a'] * 0.4:
            merged[-1]['ed'] = seg['ed']
            merged[-1]['h'] = max(merged[-1]['h'], seg['h'])
            merged[-1]['l'] = min(merged[-1]['l'], seg['l'])
            merged[-1]['a'] = max(merged[-1]['a'], seg['a'])
        else:
            merged.append(seg)
    else:
        merged.append(seg)

print("CZSC: {}笔 -> 修复: {}笔".format(len(c.bi_list), len(merged)))
for i, seg in enumerate(merged):
    print("  [{:2d}] {} {}-{} | {:.0f}~{:.0f}".format(
        i, seg['d'][0], seg['sd'].strftime('%H:%M'), seg['ed'].strftime('%H:%M'),
        seg['h'], seg['l']))

fig, ax = plt.subplots(figsize=(28, 8), facecolor='#0d1117')
ax.set_facecolor('#0d1117')
for i, b in enumerate(bars):
    col = '#26a641' if b.close >= b.open else '#f85149'
    ax.plot([i, i], [b.low, b.high], color=col, linewidth=0.8)
    ax.add_patch(plt.Rectangle((i-0.4, min(b.open, b.close)), 0.8, abs(b.close-b.open), color=col))
for bi in c.bi_list:
    x0 = d2i.get(bi.raw_bars[0].dt, 0)
    x1 = d2i.get(bi.raw_bars[-1].dt, x0)
    ax.plot([x0, x1], [bi.high, bi.low], color='#8b949e', linewidth=1.5, alpha=0.4, ls='--')
COL = {'Up': '#26a641', 'Down': '#f85149'}
for seg in merged:
    x0 = d2i.get(seg['sd'], 0)
    x1 = d2i.get(seg['ed'], x0)
    col = COL[seg['d']]
    ax.plot([x0, x1], [seg['h'], seg['l']], color=col, linewidth=3, alpha=0.9, zorder=10)
    mid = (x0 + x1) / 2
    my = (seg['h'] + seg['l']) / 2
    ax.text(mid, my, seg['d'][0], color='white', fontsize=8, ha='center', va='center',
            fontweight='bold', bbox=dict(boxstyle='round,pad=0.2', facecolor=col, alpha=0.8))
ax.set_xlim(-2, len(bars)+2)
ax.set_ylim(sub['low'].min()-15, sub['high'].max()+15)
ax.tick_params(axis='y', labelcolor='white')
ax.set_xticks([])
ax.text(0.01, 0.99, "CZSC {}笔 -> 修复 {}笔".format(len(c.bi_list), len(merged)),
        transform=ax.transAxes, color='#8b949e', fontsize=9, va='top', ha='left',
        family='monospace', bbox=dict(boxstyle='round', facecolor='#161b22', alpha=0.8))
plt.tight_layout()
plt.savefig(WORK + '/charts/chan_v4_test.png', dpi=100, facecolor='#0d1117', bbox_inches='tight')
plt.close()
print("Saved: chan_v4_test.png")

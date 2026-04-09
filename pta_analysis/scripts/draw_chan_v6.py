#!/usr/bin/env python3
"""绘制PTA缠论K线图"""
import sys
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

sys.path.insert(0, '/home/admin/.openclaw/workspace/codeman/pta_analysis/scripts')

# === 加载数据 ===
DATA = '/home/admin/.openclaw/workspace/codeman/pta_analysis/data'

from czsc.py.analyze import CZSC
from czsc.py.objects import RawBar
from czsc.py.enum import Freq

df = pd.read_csv(f'{DATA}/pta_1min.csv')
df['datetime'] = pd.to_datetime(df['datetime'])
ap = df[df['datetime'].dt.date == pd.Timestamp('2026-04-03').date()]
good = ap['close'].notna() & (ap['close'] > 0)
ap = ap[good].sort_values('datetime').reset_index(drop=True)
ap['real_time'] = ap['datetime'] + pd.Timedelta(hours=8)
bars = []
for i, (_, r) in enumerate(ap.iterrows()):
    bars.append(RawBar(symbol='TA', id=i, dt=r['real_time'],
        open=float(r['open']), high=float(r['high']), low=float(r['low']),
        close=float(r['close']), vol=float(r['volume']), amount=0, freq=Freq.F1))

c = CZSC(bars)

# === 转换笔数据 ===
bi_bars = []
for i, bi in enumerate(c.bi_list):
    d = 'up' if str(bi.direction) == '向上' else 'down'
    bi_bars.append({
        'idx': i, 'dir': d,
        'start_val': bi.raw_bars[0].low if d == 'up' else bi.raw_bars[0].high,
        'end_val': bi.raw_bars[-1].high if d == 'up' else bi.raw_bars[-1].low,
        'high': bi.high, 'low': bi.low,
        'raw_bars': [(b.dt, b.open, b.high, b.low, b.close) for b in bi.raw_bars]
    })

# === 线段检测（复制v6核心算法）===
def find_feat(start, end, seg_dir, bi_bars):
    feat = []
    for j in range(start, end + 1):
        if bi_bars[j]['dir'] != seg_dir:
            feat.append({'bi_idx': bi_bars[j]['idx'], 'high': bi_bars[j]['high'], 'low': bi_bars[j]['low']})
    return feat

def find_top(feat):
    for k in range(1, len(feat) - 1):
        l, m, r = feat[k-1], feat[k], feat[k+1]
        if m['high'] > l['high'] and m['high'] > r['high'] and \
           m['low'] > l['low'] and m['low'] > r['low']:
            return k
    return -1

def find_bottom(feat):
    for k in range(1, len(feat) - 1):
        l, m, r = feat[k-1], feat[k], feat[k+1]
        if m['high'] < l['high'] and m['high'] < r['high'] and \
           m['low'] < l['low'] and m['low'] < r['low']:
            return k
    return -1

def detect_xd(bi_bars):
    n = len(bi_bars)
    results = []
    seg_dir = 'up'
    seg_start = 0
    i = 0
    while i < n:
        cur_dir = bi_bars[i]['dir']
        if cur_dir == seg_dir:
            i += 1
            continue
        seg_len = i - seg_start
        if seg_len == 3:
            same_dir = all(bi_bars[j]['dir'] == seg_dir for j in range(seg_start, i))
            if same_dir:
                seg_end_bi = i - 1
                seg_max = max(bi_bars[j]['high'] for j in range(seg_start, seg_end_bi + 1))
                seg_min = min(bi_bars[j]['low'] for j in range(seg_start, seg_end_bi + 1))
                end_price = seg_max if seg_dir == 'up' else seg_min
                results.append((seg_start, seg_end_bi, seg_dir, end_price))
                seg_dir = 'down' if seg_dir == 'up' else 'up'
                seg_start = seg_end_bi
                i = seg_end_bi
                continue
        # 特征序列法
        feat = find_feat(seg_start, i, seg_dir, bi_bars)
        if len(feat) >= 3:
            if seg_dir == 'up':
                top_pos = find_top(feat)
                if top_pos >= 0:
                    if top_pos + 1 < len(feat) and feat[top_pos + 1]['low'] < feat[top_pos]['low']:
                        seg_end_bi = feat[top_pos]['bi_idx']
                        seg_max = max(bi_bars[j]['high'] for j in range(seg_start, seg_end_bi + 1))
                        seg_min = min(bi_bars[j]['low'] for j in range(seg_start, seg_end_bi + 1))
                        end_price = seg_max
                        results.append((seg_start, seg_end_bi, seg_dir, end_price))
                        seg_dir = 'down'
                        seg_start = seg_end_bi
                        i = seg_end_bi + 1
                        continue
                    else:
                        feat = feat[1:]
                        while len(feat) >= 3:
                            pos2 = find_top(feat)
                            if pos2 >= 0 and pos2 + 1 < len(feat) and feat[pos2 + 1]['low'] < feat[pos2]['low']:
                                seg_end_bi2 = feat[pos2]['bi_idx']
                                seg_max = max(bi_bars[j]['high'] for j in range(seg_start, seg_end_bi2 + 1))
                                results.append((seg_start, seg_end_bi2, seg_dir, seg_max))
                                seg_dir = 'down'
                                seg_start = seg_end_bi2
                                i = seg_end_bi2 + 1
                                break
                            feat = feat[1:]
                        else:
                            i += 1
                            continue
            else:
                bottom_pos = find_bottom(feat)
                if bottom_pos >= 0:
                    if bottom_pos + 1 < len(feat) and feat[bottom_pos + 1]['high'] > feat[bottom_pos]['high']:
                        seg_end_bi = feat[bottom_pos]['bi_idx']
                        seg_min = min(bi_bars[j]['low'] for j in range(seg_start, seg_end_bi + 1))
                        results.append((seg_start, seg_end_bi, seg_dir, seg_min))
                        seg_dir = 'up'
                        seg_start = seg_end_bi
                        i = seg_end_bi + 1
                        continue
                    else:
                        feat = feat[1:]
                        while len(feat) >= 3:
                            pos2 = find_bottom(feat)
                            if pos2 >= 0 and pos2 + 1 < len(feat) and feat[pos2 + 1]['high'] > feat[pos2]['high']:
                                seg_end_bi2 = feat[pos2]['bi_idx']
                                seg_min = min(bi_bars[j]['low'] for j in range(seg_start, seg_end_bi2 + 1))
                                results.append((seg_start, seg_end_bi2, seg_dir, seg_min))
                                seg_dir = 'up'
                                seg_start = seg_end_bi2
                                i = seg_end_bi2 + 1
                                break
                            feat = feat[1:]
                        else:
                            i += 1
                            continue
        i += 1
    if seg_start < n - 1:
        seg_end_bi = n - 1
        seg_max = max(bi_bars[j]['high'] for j in range(seg_start, seg_end_bi + 1))
        seg_min = min(bi_bars[j]['low'] for j in range(seg_start, seg_end_bi + 1))
        end_price = seg_max if seg_dir == 'up' else seg_min
        results.append((seg_start, seg_end_bi, seg_dir, end_price))
    return results

xd_results = detect_xd(bi_bars)
print("XD results:")
for r in xd_results:
    print(f"  b{r[0]+1}~b{r[1]+1} {r[2]} [{r[3]:.0f}]")

# === 绘图 ===
fig, ax = plt.subplots(figsize=(20, 8))

# 获取所有K线
all_klines = []
for bi in c.bi_list:
    for kb in bi.raw_bars:
        all_klines.append({'dt': kb.dt, 'open': kb.open, 'high': kb.high, 'low': kb.low, 'close': kb.close})

# 绘制K线
for k in all_klines:
    color = 'red' if k['close'] >= k['open'] else 'green'
    ax.plot([k['dt'], k['dt']], [k['low'], k['high']], color=color, linewidth=0.5)
    ax.plot([k['dt'], k['dt']], [k['open'], k['close']], color=color, linewidth=1.5)

# 绘制笔
colors = {'up': 'red', 'down': 'green'}
for b in bi_bars:
    color = colors[b['dir']]
    x_start = b['raw_bars'][0][0]
    x_end = b['raw_bars'][-1][0]
    ax.plot([x_start, x_end], [b['end_val'], b['end_val']], color=color, linewidth=2, alpha=0.8)

# 绘制线段
xd_colors = {'up': '#8B0000', 'down': '#006400'}
for xd in xd_results:
    s, e, d, p = xd
    x_mid = bi_bars[s]['raw_bars'][0][0]
    color = xd_colors[d]
    ax.axhline(y=p, color=color, linewidth=1.5, alpha=0.7, linestyle='--')
    ax.text(x_mid, p + 5, f'XD{len([x for x in xd_results if x <= xd])}', fontsize=9, color=color)

ax.set_title('PTA Apr 3 - Chan Bi & XD (3 Segments Confirmed)', fontsize=14, fontweight='bold')
ax.set_xlabel('Time')
ax.set_ylabel('Price')
plt.tight_layout()
plt.savefig('/home/admin/.openclaw/workspace/codeman/pta_analysis/charts/chan_bi_xd_v6.png', dpi=150)
print('Saved: chan_bi_xd_v6.png')

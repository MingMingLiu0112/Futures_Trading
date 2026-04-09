#!/usr/bin/env python3
"""画笔和线段图"""
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from czsc.py.objects import RawBar
from czsc.py.analyze import CZSC
from czsc.py.enum import Freq

DATA = '/home/admin/.openclaw/workspace/codeman/pta_analysis/data'


def load_bars(date='2026-04-03'):
    df = pd.read_csv(f'{DATA}/pta_1min.csv')
    df['datetime'] = pd.to_datetime(df['datetime'])
    ap = df[df['datetime'].dt.date == pd.Timestamp(date).date()]
    good = ap['close'].notna() & (ap['close'] > 0)
    ap = ap[good].sort_values('datetime').reset_index(drop=True)
    ap['real_time'] = ap['datetime'] + pd.Timedelta(hours=8)
    bars = []
    for i, (_, r) in enumerate(ap.iterrows()):
        bars.append(RawBar(symbol='TA', id=i, dt=r['real_time'],
            open=float(r['open']), high=float(r['high']), low=float(r['low']),
            close=float(r['close']), vol=float(r['volume']), amount=0, freq=Freq.F1))
    return bars


class BiBar:
    def __init__(self, bi_idx, dt, direction, start_p, end_p, high, low):
        self.bi_idx = bi_idx
        self.dt = dt
        self.direction = direction
        self.start = start_p
        self.end = end_p
        self.high = high
        self.low = low


def get_bi_bars(c):
    result = []
    for i, bi in enumerate(c.bi_list):
        fb, lb = bi.raw_bars[0], bi.raw_bars[-1]
        d = str(bi.direction)
        sp = fb.low if d == '向上' else fb.high
        ep = lb.high if d == '向上' else lb.low
        all_high = max(b.high for b in bi.raw_bars)
        all_low = min(b.low for b in bi.raw_bars)
        result.append(BiBar(i, fb.dt, 'up' if d == '向上' else 'down', sp, ep, all_high, all_low))
    return result


def detect_xd(bi_bars):
    n = len(bi_bars)
    results = []
    seg_start = 0
    seg_dir = bi_bars[0].direction
    last_opposite_idx = 1 if n >= 2 else None
    i = 2
    while i < n:
        cur = bi_bars[i]
        if cur.direction == seg_dir:
            i += 1
        else:
            prev_opposite = bi_bars[last_opposite_idx]
            destroyed = False
            if seg_dir == 'up' and cur.direction == 'down':
                if cur.low < prev_opposite.low:
                    destroyed = True
            elif seg_dir == 'down' and cur.direction == 'up':
                if cur.high > prev_opposite.high:
                    destroyed = True
            if destroyed:
                seg_end = i - 1
                seg_len = seg_end - seg_start + 1
                if seg_len >= 3:
                    results.append((seg_start, seg_end, seg_dir))
                seg_start = last_opposite_idx
                seg_dir = cur.direction
                last_opposite_idx = i
            else:
                last_opposite_idx = i
            i += 1
    if seg_start < n:
        seg_end = n - 1
        seg_len = seg_end - seg_start + 1
        if seg_len >= 3:
            results.append((seg_start, seg_end, seg_dir))
    return results


def main():
    bars = load_bars('2026-04-03')
    c = CZSC(bars)
    bi_bars = get_bi_bars(c)
    xd_results = detect_xd(bi_bars)

    fig, ax = plt.subplots(figsize=(20, 8))
    for i, b in enumerate(bars):
        color = '#ef5350' if b.close >= b.open else '#26a69a'
        ax.plot([i, i], [b.low, b.high], color=color, linewidth=0.5)
        ax.plot([i-0.3, i+0.3], [b.open, b.open], color=color, linewidth=0.5)
        ax.plot([i-0.3, i+0.3], [b.close, b.close], color=color, linewidth=0.5)

    for bi in bi_bars:
        color = '#ef5350' if bi.direction == 'up' else '#26a69a'
        x = bi.bi_idx
        ax.plot([x, x], [bi.start, bi.end], color=color, linewidth=2)
        ax.annotate(f'b{bi.bi_idx+1}', (x, bi.end), fontsize=7, ha='center', va='bottom', color=color)

    colors = {'up': '#ff6d00', 'down': '#2979ff'}
    for idx, (s, e, d) in enumerate(xd_results):
        color = colors[d]
        sb, eb = bi_bars[s], bi_bars[e]
        mid_x = (s + e) / 2
        mid_y = (sb.start + eb.end) / 2
        ax.plot([s, e], [sb.start, eb.end], color=color, linewidth=4, alpha=0.7)
        ax.annotate(f"XD{idx+1}", (mid_x, mid_y), fontsize=12, ha='center', va='center',
                   color='white', fontweight='bold',
                   bbox=dict(boxstyle='round,pad=0.3', facecolor=color, alpha=0.9))

    ax.set_xlim(-1, len(bars))
    ax.set_ylim(6650, 7100)
    ax.set_xlabel('Bar Index', fontsize=12)
    ax.set_ylabel('Price', fontsize=12)
    ax.set_title(f'PTA Apr 3 - Chan Bi & XD (Total {len(bi_bars)} Bi, {len(xd_results)} XD)', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig('/home/admin/.openclaw/workspace/codeman/pta_analysis/charts/chan_bi_xd.png', dpi=150)
    print(f'图片已保存: {len(xd_results)}条线段')
    for idx, (s, e, d) in enumerate(xd_results):
        sb, eb = bi_bars[s], bi_bars[e]
        print(f"  XD{idx+1}: b{s+1}~b{e+1} ({d}) [{sb.dt.strftime('%H:%M')}~{eb.dt.strftime('%H:%M')}] {sb.start:.0f}->{eb.end:.0f}")


if __name__ == '__main__':
    main()

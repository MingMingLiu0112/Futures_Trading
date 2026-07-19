#!/usr/bin/env python3
"""
PTA 缠论笔图画图脚本
用法: python3 draw_chan_bi.py [date]
默认日期: 2026-04-03
"""
import pandas as pd
from czsc.py.objects import RawBar
from czsc.py.analyze import CZSC
from czsc.py.enum import Freq
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import sys

DATA = '/home/admin/.openclaw/workspace/codeman/pta_analysis/data'
OUT = '/home/admin/.openclaw/workspace/codeman/pta_analysis/charts'
DATE = sys.argv[1] if len(sys.argv) > 1 else '2026-04-03'

def load_data(date):
    df = pd.read_csv(f'{DATA}/pta_1min.csv')
    df['datetime'] = pd.to_datetime(df['datetime'])
    ap = df[df['datetime'].dt.date == pd.Timestamp(date).date()]
    ap = ap[ap['close'].notna() & (ap['close'] > 0)]
    ap = ap.sort_values('datetime').reset_index(drop=True)
    ap['real_time'] = ap['datetime'] + pd.Timedelta(hours=8)

    bars = []
    for i, (_, r) in enumerate(ap.iterrows()):
        bars.append(RawBar(symbol='TA', id=i, dt=r['real_time'],
            open=float(r['open']), high=float(r['high']), low=float(r['low']),
            close=float(r['close']), vol=float(r['volume']), amount=0, freq=Freq.F1))
    return bars, ap

def draw_chan_bi(bars, ap, out_path):
    d2i = {b.dt: i for i, b in enumerate(bars)}
    c = CZSC(bars)

    # 缠论标准端点: Up=首bar.low->末bar.high, Down=首bar.high->末bar.low
    bi_pts = []
    for bi in c.bi_list:
        fb, lb = bi.raw_bars[0], bi.raw_bars[-1]
        if str(bi.direction) == '向上':
            sp, ep = fb.low, lb.high
        else:
            sp, ep = fb.high, lb.low
        bi_pts.append((d2i[fb.dt], sp, d2i[lb.dt], ep))

    # 画图
    fig, axes = plt.subplots(2, 1, figsize=(40, 14), facecolor='#0d1117')
    ax, ax2 = axes[0], axes[1]
    ax.set_facecolor('#0d1117')
    ax2.set_facecolor('#0d1117')

    # K线
    for i, b in enumerate(bars):
        col = '#26a641' if b.close >= b.open else '#f85149'
        ax.plot([i, i], [b.low, b.high], color=col, linewidth=0.8)
        bot = b.open if b.open < b.close else b.close
        ax.add_patch(plt.Rectangle((i-0.4, bot), 0.8, abs(b.close-b.open), color=col))

    # 笔=斜线, 连接=水平线
    LINE_COL = '#e6e6e6'
    for i, (x0, sp, x1, ep) in enumerate(bi_pts):
        ax.plot([x0, x1], [sp, ep], color=LINE_COL, linewidth=2.5)
        if i < len(bi_pts) - 1:
            nx0, nsp = bi_pts[i+1][0], bi_pts[i+1][1]
            ax.plot([x1, nx0], [ep, ep], color=LINE_COL, linewidth=1.5, alpha=0.7)

    pmin = min(b.low for b in bars)
    pmax = max(b.high for b in bars)
    ax.set_xlim(-2, len(bars)+2)
    ax.set_ylim(pmin-30, pmax+30)
    ax.tick_params(axis='y', labelcolor='white')
    ax.set_xticks([])

    for kh in ['09:00', '10:00', '11:00', '13:00', '14:00', '15:00']:
        mask = ap['real_time'].dt.strftime('%H:%M') == kh
        if mask.any():
            idx = int(ap[mask].index[0])
            ax.axvline(x=idx, color='#30363d', linestyle=':', alpha=0.6)
            ax.text(idx, pmin-20, kh, color='#8b949e', fontsize=8, ha='center')

    ax.text(0.01, 0.99, f'CZSC: {len(c.bi_list)}bi  {DATE}',
            transform=ax.transAxes, color='#8b949e', fontsize=10, va='top', ha='left',
            family='monospace', bbox=dict(boxstyle='round', facecolor='#161b22', alpha=0.8))

    for i, b in enumerate(bars):
        col = '#26a641' if b.close >= b.open else '#f85149'
        ax2.bar(i, b.vol/1e4, color=col, width=1.0, alpha=0.7)
    ax2.set_xlim(-2, len(bars)+2)
    ax2.set_ylabel('Vol', color='white', fontsize=8)
    ax2.tick_params(axis='both', labelsize=7, colors='white')
    ax2.set_xticks([])

    fig.suptitle(f'PTA 1min Chan | CZSC | {DATE}', fontsize=14, color='white')
    plt.tight_layout(rect=[0, 0, 1, 0.97])
    plt.savefig(out_path, dpi=100, facecolor='#0d1117', bbox_inches='tight')
    plt.close()

    # 打印笔序列
    print(f"CZSC笔序列 ({len(c.bi_list)}笔):")
    for i, (x0, sp, x1, ep) in enumerate(bi_pts):
        bi = c.bi_list[i]
        print(f"  {i+1:2d} [{bi.raw_bars[0].dt.strftime('%H:%M')}~{bi.raw_bars[-1].dt.strftime('%H:%M')}] {sp:.0f} -> {ep:.0f}")

if __name__ == '__main__':
    bars, ap = load_data(DATE)
    out = f'{OUT}/chan_bi_{DATE}.png'
    draw_chan_bi(bars, ap, out)
    print(f'\nsaved: {out}')

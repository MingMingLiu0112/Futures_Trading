#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA 缠论笔自动补漏算法 v4

核心发现：CZSC相邻笔之间没有bar间隙，而是在笔内部吞了反向走势。
原因：包含关系处理把多根K线合并后，抹掉了中间的反转信号。

修复原理：
- 对于每个"向上"笔：如果中间出现更低的低点 → 应在这里分割成两笔
- 对于每个"向下"笔：如果中间出现更高的高点 → 应在这里分割成两笔
- 具体：当内部bar的high超过笔开始bar的high（向上笔），或内部bar的low超过笔开始bar的low（向下笔），则分割

另外：连续小幅笔也要合并（幅度 < 前笔40%）
"""
import pandas as pd
import numpy as np
from czsc.py.objects import RawBar
from czsc.py.analyze import CZSC
from czsc.py.enum import Freq
import warnings
warnings.filterwarnings('ignore')

WORKSPACE = '/home/admin/.openclaw/workspace/codeman/pta_analysis'
DATA_DIR = f'{WORKSPACE}/data'


def find_split_points(bi_bars):
    """
    在一个笔的内部找反转点（被CZSC吞掉的笔）
    返回：[(split_idx, direction, amplitude), ...]
    split_idx: 在哪个bar之后分割（0-indexed in bi_bars）
    direction: 分割后的第二段笔的方向
    """
    if len(bi_bars) < 5:
        return []

    splits = []
    bars = bi_bars  # list of RawBar

    if bars[0].high > bars[-1].high:
        # 向上笔（从低点涨到高点）
        init_low = bars[0].low
        for i in range(1, len(bars) - 2):
            # 如果中间出现了明显更低的低点 → 分割成向下笔
            if bars[i].low < init_low - 10:
                # 找到了向下的转折，从i处分割
                amp = init_low - bars[i].low
                if amp >= 10:
                    splits.append((i, 'Down', amp))
                    init_low = bars[i].low  # 更新低点，继续找
    else:
        # 向下笔（从高点跌到低点）
        init_high = bars[0].high
        for i in range(1, len(bars) - 2):
            # 如果中间出现了更高的高点 → 分割成向上笔
            if bars[i].high > init_high + 10:
                amp = bars[i].high - init_high
                if amp >= 10:
                    splits.append((i, 'Up', amp))
                    init_high = bars[i].high

    return splits


def split_bis_with_splits(czsc_bis, min_amp_ratio=0.4):
    """
    将CZSC笔列表按split points分割
    同时合并相邻小幅笔
    """
    all_segs = []

    for bi in czsc_bis:
        splits = find_split_points(bi.raw_bars)

        if not splits:
            # 无分割，整个笔作为一段
            all_segs.append({
                'direction': bi.direction.value,
                'start_dt': bi.raw_bars[0].dt,
                'end_dt': bi.raw_bars[-1].dt,
                'start_idx_in_raw': bi.raw_bars[0].id,
                'end_idx_in_raw': bi.raw_bars[-1].id,
                'high': bi.high,
                'low': bi.low,
                'amplitude': bi.length,
            })
        else:
            # 按分割点切分
            raw_bars = bi.raw_bars
            prev = 0
            for split_idx, split_dir, amp in splits:
                # 第一段（从prev到split_idx）
                seg1 = raw_bars[prev:split_idx+1]
                if len(seg1) >= 2:
                    d = 'Up' if seg1[-1].high > seg1[0].high else 'Down'
                    amp1 = abs(seg1[-1].high - seg1[0].low) if d == 'Up' else abs(seg1[0].high - seg1[-1].low)
                    all_segs.append({
                        'direction': d,
                        'start_dt': seg1[0].dt,
                        'end_dt': seg1[-1].dt,
                        'start_idx_in_raw': seg1[0].id,
                        'end_idx_in_raw': seg1[-1].id,
                        'high': max(b.high for b in seg1),
                        'low': min(b.low for b in seg1),
                        'amplitude': amp1,
                    })

                # 第二段（从split_idx+1到结尾）→ 反向
                seg2 = raw_bars[split_idx:]
                if len(seg2) >= 2:
                    d2 = 'Down' if seg2[-1].high < seg2[0].high else 'Up'
                    amp2 = abs(seg2[0].high - seg2[-1].low) if d2 == 'Down' else abs(seg2[-1].high - seg2[0].low)
                    all_segs.append({
                        'direction': d2,
                        'start_dt': seg2[0].dt,
                        'end_dt': seg2[-1].dt,
                        'start_idx_in_raw': seg2[0].id,
                        'end_idx_in_raw': seg2[-1].id,
                        'high': max(b.high for b in seg2),
                        'low': min(b.low for b in seg2),
                        'amplitude': amp2,
                    })
                prev = split_idx

    # 合并相邻小幅笔（幅度 < 前一笔40%则合并）
    merged = []
    for seg in all_segs:
        if not merged:
            merged.append(seg)
        elif seg['direction'] == merged[-1]['direction']:
            # 同向，幅度小则合并
            if seg['amplitude'] < merged[-1]['amplitude'] * 0.4:
                merged[-1]['end_dt'] = seg['end_dt']
                merged[-1]['end_idx_in_raw'] = seg['end_idx_in_raw']
                merged[-1]['high'] = max(merged[-1]['high'], seg['high'])
                merged[-1]['low'] = min(merged[-1]['low'], seg['low'])
                merged[-1]['amplitude'] = abs(merged[-1]['high'] - merged[-1]['low'])
            else:
                merged.append(seg)
        else:
            # 反向，直接加
            merged.append(seg)

    return merged


def analyze_fixed(bars):
    """带补漏的完整分析"""
    dt_to_idx = {b.dt: i for i, b in enumerate(bars)}
    c = CZSC(bars)
    czsc_bis = list(c.bi_list)

    # 补漏+合并
    fixed = split_bis_with_splits(czsc_bis)

    return czsc_bis, fixed, dt_to_idx


def plot_comparison(bars, czsc_bis, fixed, dt_to_idx, title, filename):
    """画图"""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(20, 6), facecolor='#0d1117')
    ax.set_facecolor('#0d1117')

    # K线
    for i, b in enumerate(bars):
        col = '#26a641' if b.close >= b.open else '#f85149'
        ax.plot([i, i], [b.low, b.high], color=col, linewidth=0.8)
        ax.add_patch(plt.Rectangle((i-0.4, min(b.open, b.close)), 0.8, abs(b.close-b.open), color=col))

    # CZSC笔（灰虚线）
    for bi in czsc_bis:
        x0 = dt_to_idx.get(bi.raw_bars[0].dt, 0)
        x1 = dt_to_idx.get(bi.raw_bars[-1].dt, x0)
        ax.plot([x0, x1], [bi.high, bi.low], color='#8b949e', linewidth=1.5, alpha=0.4, linestyle='--')

    # 修复笔（彩色实线）
    COL = {'Up': '#26a641', 'Down': '#f85149'}
    for seg in fixed:
        # 用时间找bar索引（修复版中seg没有全局索引，改用datetime）
        try:
            x0 = dt_to_idx.get(seg['start_dt'], 0)
            x1 = dt_to_idx.get(seg['end_dt'], x0)
        except:
            continue
        col = COL.get(seg['direction'], '#58a6ff')
        ax.plot([x0, x1], [seg['high'], [seg['low']],
                color=col, linewidth=3, alpha=0.9, zorder=10)

    price_min = min(b.low for b in bars)
    price_max = max(b.high for b in bars)
    ax.set_xlim(-2, len(bars) + 2)
    ax.set_ylim(price_min - 15, price_max + 15)
    ax.set_ylabel('PTA', color='white', fontsize=10)
    ax.tick_params(axis='y', labelcolor='white')
    ax.set_xticks([])

    ax.text(0.01, 0.99, title, transform=ax.transAxes, color='#8b949e',
            fontsize=9, va='top', ha='left', family='monospace',
            bbox=dict(boxstyle='round', facecolor='#161b22', alpha=0.8))
    plt.tight_layout()
    plt.savefig(f'{WORKSPACE}/charts/{filename}', dpi=100,
                facecolor='#0d1117', bbox_inches='tight')
    plt.close()
    print(f'  -> {filename}')


def main():
    print("=== 缠论笔自动补漏算法 v4 ===\n")

    # 加载4月3日数据
    df = pd.read_csv(f'{DATA_DIR}/pta_1min.csv')
    df['datetime'] = pd.to_datetime(df['datetime'])
    april3 = df[df['datetime'].dt.date == pd.Timestamp('2026-04-03').date()]
    april3 = april3[april3['close'].notna() & (april3['close'] > 0)]
    april3 = april3.sort_values('datetime').reset_index(drop=True)
    april3['real_time'] = april3['datetime'] + pd.Timedelta(hours=8)

    bars = []
    for i, (_, r) in enumerate(april3.iterrows()):
        bars.append(RawBar(symbol='TA', id=i, dt=r['real_time'],
            open=float(r['open']), high=float(r['high']), low=float(r['low']),
            close=float(r['close']), vol=float(r['volume']), amount=0, freq=Freq.F1))

    # 测试 09:00-15:00
    mask = (april3['real_time'].dt.strftime('%H:%M') >= '09:00') & \
           (april3['real_time'].dt.strftime('%H:%M') <= '15:00')
    sub = april3[mask]
    sub_bars = [bars[i] for i in range(len(bars)) if mask.iloc[i]]

    czsc_bis, fixed, dt_to_idx = analyze_fixed(sub_bars)

    print(f"CZSC笔: {len(czsc_bis)}笔")
    print(f"修复后: {len(fixed)}笔")
    print()
    for i, seg in enumerate(fixed):
        print(f"  [{i:2d}] {str(seg['direction'])[0]} {seg['start_dt'].strftime('%H:%M')}-{seg['end_dt'].strftime('%H:%M')} "
              f"| {seg['high']:.0f}~{seg['low']:.0f} | 幅度={seg['amplitude']:.0f}")

    plot_comparison(sub_bars, czsc_bis, fixed, dt_to_idx,
                   f"CZSC {len(czsc_bis)}笔 -> 修复 {len(fixed)}笔",
                   'chan_v4_full.png')

    print()
    print("=== 完成 ===")


if __name__ == '__main__':
    main()

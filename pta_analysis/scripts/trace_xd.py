#!/usr/bin/env python3
"""
Trace XD algorithm for PTA 4月3日 - 正确版本

Seg_ref 逻辑（任务描述）：
1. 对于 UP 段，seg_ref = 段内遇到的最低点（segment's lowest low）
   对于 DOWN 段，seg_ref = 段内遇到的最高点（segment's highest high）
2. 段破坏判断：
   UP 段被 DOWN 笔破坏：cur.low < seg_ref
   DOWN 段被 UP 笔破坏：cur.high > seg_ref
3. 当 seg_dir 从 UP 变为 DOWN（或反之），新的 seg_ref = cur.start（起点价格）

手工期望结果：
  XD1 ↑ b1~b3 [6726->6922]
  XD2 ↓ b4~b6 [6922->6810]
  XD3 ↑ b7~b16 [6810->6948]
"""

import sys
sys.path.insert(0, '/home/admin/.openclaw/workspace/codeman/pta_analysis')

import pandas as pd
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
        self.start = start_p   # 笔起点价格
        self.end = end_p       # 笔终点价格
        self.high = high       # 笔内最高价
        self.low = low         # 笔内最低价


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


def detect_xd(bi_bars, debug=False):
    """
    正确的线段检测算法，使用 seg_ref 跟踪段内极值。

    seg_ref 规则：
    - UP segment: seg_ref = min low of all bars in segment (段内最低)
    - DOWN segment: seg_ref = max high of all bars in segment (段内最高)
    - When seg_dir changes: new seg_ref = cur.start (新段起点价格)

    破坏规则：
    - UP 段被 DOWN 笔破坏：cur.low < seg_ref
    - DOWN 段被 UP 笔破坏：cur.high > seg_ref

    段结束规则：
    - 至少 3 笔才能形成有效段
    - 破坏成功后，前段结束，新段从反向笔开始
    """
    n = len(bi_bars)
    results = []

    # 初始化：第一个笔
    seg_start = 0
    seg_dir = bi_bars[0].direction

    # 正确初始化 seg_ref：
    # UP 段：seg_ref = 段内最低点（第一个笔的 low）
    # DOWN 段：seg_ref = 段内最高点（第一个笔的 high）
    if seg_dir == 'up':
        seg_ref = bi_bars[0].low   # 段内最低
    else:
        seg_ref = bi_bars[0].high  # 段内最高

    if debug:
        print(f"初始化: seg_start=b{seg_start+1}, seg_dir={seg_dir}, seg_ref={seg_ref:.0f}")

    i = 0
    while i < n:
        cur = bi_bars[i]

        if cur.direction == seg_dir:
            # 同向笔：更新 seg_ref
            if seg_dir == 'up':
                seg_ref = min(seg_ref, cur.low)  # UP: 跟踪段内最低
            else:
                seg_ref = max(seg_ref, cur.high)  # DOWN: 跟踪段内最高
            if debug:
                print(f"  i={i} b{i+1} {cur.direction}: 同向, seg_ref更新={seg_ref:.0f}")
            i += 1
        else:
            # 方向反转！检查破坏
            destroyed = False
            if seg_dir == 'up' and cur.direction == 'down':
                # UP 段被 DOWN 笔破坏：cur.low < seg_ref（段内最低）
                destroyed = cur.low < seg_ref
                if debug:
                    print(f"  i={i} b{i+1} DOWN vs UP(seg_ref={seg_ref:.0f}): cur.low={cur.low:.0f}, {'破坏!' if destroyed else '未破坏'}")
            elif seg_dir == 'down' and cur.direction == 'up':
                # DOWN 段被 UP 笔破坏：cur.high > seg_ref（段内最高）
                destroyed = cur.high > seg_ref
                if debug:
                    print(f"  i={i} b{i+1} UP vs DOWN(seg_ref={seg_ref:.0f}): cur.high={cur.high:.0f}, {'破坏!' if destroyed else '未破坏'}")

            if destroyed:
                seg_end = i - 1
                seg_len = seg_end - seg_start + 1
                if debug:
                    print(f"  → 段结束: b{seg_start+1}~b{seg_end+1} ({seg_dir}) len={seg_len}")
                if seg_len >= 3:
                    results.append((seg_start, seg_end, seg_dir))
                    if debug:
                        print(f"  → 记录: XD{len(results)} {seg_dir} b{seg_start+1}~b{seg_end+1}")
                else:
                    if debug:
                        print(f"  → 跳过（<3笔）")

                # 新段开始
                seg_start = i
                seg_dir = cur.direction
                # 关键修复：新段的 seg_ref = cur.start（新段起点价格）
                if seg_dir == 'up':
                    seg_ref = cur.low   # 新 UP 段: seg_ref = 起点 low
                else:
                    seg_ref = cur.high  # 新 DOWN 段: seg_ref = 起点 high
                if debug:
                    print(f"  → 新段开始: b{seg_start+1}, dir={seg_dir}, seg_ref={seg_ref:.0f}")
            i += 1

    # 处理最后一段
    seg_end = n - 1
    seg_len = seg_end - seg_start + 1
    if debug:
        print(f"最后段: b{seg_start+1}~b{seg_end+1} ({seg_dir}) len={seg_len}")
    if seg_len >= 3:
        results.append((seg_start, seg_end, seg_dir))
        if debug:
            print(f"  → 记录: XD{len(results)} {seg_dir} b{seg_start+1}~b{seg_end+1}")

    return results


def main():
    bars = load_bars('2026-04-03')
    c = CZSC(bars)
    bi_bars = get_bi_bars(c)

    print("=" * 60)
    print("PTA 4月3日 缠论线段检测 - seg_ref 修复版")
    print("=" * 60)
    print(f"\n笔序列 ({len(bi_bars)}笔):")
    for b in bi_bars:
        print(f"  b{b.bi_idx+1:2d} {b.direction:4s} [{b.dt.strftime('%H:%M')}] "
              f"start={b.start:.0f} end={b.end:.0f} high={b.high:.0f} low={b.low:.0f}")

    print("\n" + "=" * 60)
    print("Seg_ref 修复版算法:")
    print("=" * 60)
    results = detect_xd(bi_bars, debug=True)

    print(f"\n检测结果: {len(results)}条线段")
    print("-" * 60)
    for idx, r in enumerate(results):
        s = bi_bars[r[0]]
        e = bi_bars[r[1]]
        n_bi = r[1] - r[0] + 1
        print(f"  XD{idx+1} {r[2]:4s} b{r[0]+1}~b{r[1]+1} ({n_bi}笔) "
              f"[{s.dt.strftime('%H:%M')}~{e.dt.strftime('%H:%M')}] "
              f"{s.start:.0f} → {e.end:.0f}")

    print("\n期望结果:")
    print("  XD1 ↑ b1~b3 [6726->6922] (3笔)")
    print("  XD2 ↓ b4~b6 [6922->6810] (3笔)")
    print("  XD3 ↑ b7~b16 [6810->6948] (10笔)")

    # 验证
    expected = [
        (0, 2, 'up'),
        (3, 5, 'down'),
        (6, 15, 'up'),
    ]
    print("\n验证:")
    if len(results) == len(expected):
        all_ok = True
        for i, (got, exp) in enumerate(zip(results, expected)):
            ok = (got[0] == exp[0] and got[1] == exp[1] and got[2] == exp[2])
            status = "✓" if ok else "✗"
            print(f"  XD{i+1}: {status} got b{got[0]+1}~b{got[1]+1} ({got[2]}) vs expected b{exp[0]+1}~b{exp[1]+1} ({exp[2]})")
            if not ok:
                all_ok = False
        if all_ok:
            print("\n  ✅ 结果完全匹配！")
        else:
            print("\n  ❌ 结果不匹配")
    else:
        print(f"  ❌ 数量不匹配: got {len(results)} vs expected {len(expected)}")


if __name__ == '__main__':
    main()

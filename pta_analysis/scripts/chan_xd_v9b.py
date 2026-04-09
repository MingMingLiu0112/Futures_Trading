#!/usr/bin/env python3
"""
PTA 缠论线段检测 v9b - 修正版
核心：
1. 上行段被下行笔破坏：下行笔.low < 前一上行笔.high → 线段在反向笔起点结束
2. 下行段被上行笔破坏：上行笔.high > 前一下行笔.low → 线段在反向笔起点结束
3. i++ 改为 i = next_idx + 1（正确推进）
"""

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
    def __init__(self, bi_idx, dt, direction, start_p, end_p):
        self.bi_idx = bi_idx
        self.dt = dt
        self.direction = direction
        self.start = start_p
        self.end = end_p
        self.high = max(start_p, end_p)
        self.low = min(start_p, end_p)


def get_bi_bars(c):
    result = []
    for i, bi in enumerate(c.bi_list):
        fb, lb = bi.raw_bars[0], bi.raw_bars[-1]
        d = str(bi.direction)
        sp = fb.low if d == '向上' else fb.high
        ep = lb.high if d == '向上' else lb.low
        result.append(BiBar(i, fb.dt, 'up' if d == '向上' else 'down', sp, ep))
    return result


def detect_xd(bi_bars):
    """线段检测：gap封闭=下行笔.low < 前一上行笔.high"""
    n = len(bi_bars)
    results = []

    i = 0
    while i < n:
        cur = bi_bars[i]

        # 找下一个反向笔
        next_idx = None
        for j in range(i + 1, n):
            if bi_bars[j].direction != cur.direction:
                next_idx = j
                break
        if next_idx is None:
            results.append((i, n - 1, cur.direction))
            break

        next_bi = bi_bars[next_idx]

        if cur.direction == 'up' and next_bi.direction == 'down':
            # 找前一上行笔（用于gap判断）
            prev_up_idx = None
            for k in range(next_idx - 1, -1, -1):
                if bi_bars[k].direction == 'up':
                    prev_up_idx = k
                    break

            if prev_up_idx is not None:
                prev_up_high = bi_bars[prev_up_idx].high
                broken = next_bi.low < prev_up_high
                print(f"bi{i+1}(up)~bi{next_idx+1}(dn): "
                      f"dn低={next_bi.low:.0f} < up高={prev_up_high:.0f} "
                      f"{'✓' if broken else '✗'}")

                if broken:
                    results.append((i, next_idx, 'up'))
                    i = next_idx + 1
                    continue

        elif cur.direction == 'down' and next_bi.direction == 'up':
            prev_dn_idx = None
            for k in range(next_idx - 1, -1, -1):
                if bi_bars[k].direction == 'down':
                    prev_dn_idx = k
                    break

            if prev_dn_idx is not None:
                prev_dn_low = bi_bars[prev_dn_idx].low
                broken = next_bi.high > prev_dn_low

                if broken:
                    results.append((i, next_idx, 'down'))
                    i = next_idx + 1
                    continue

        i = next_idx + 1

    return results


def main():
    bars = load_bars('2026-04-03')
    c = CZSC(bars)
    bi_bars = get_bi_bars(c)

    print("=" * 60)
    print("PTA 4月3日 缠论线段检测 v9b")
    print("=" * 60)
    print(f"\n笔序列 ({len(bi_bars)}笔):")
    for b in bi_bars:
        print(f"  bi{b.bi_idx+1:2d} {b.direction:4s} [{b.dt.strftime('%H:%M')}] "
              f"start={b.start:.0f} end={b.end:.0f} high={b.high:.0f} low={b.low:.0f}")

    print("\n" + "=" * 60)
    results = detect_xd(bi_bars)
    print(f"\n检测结果: {len(results)}条线段")
    print("-" * 60)
    for r in results:
        s = bi_bars[r[0]]
        e = bi_bars[r[1]]
        n_bi = r[1] - r[0] + 1
        print(f"  {r[2]:4s} bi{r[0]+1}~bi{r[1]+1} ({n_bi}笔) "
              f"[{s.dt.strftime('%H:%M')}~{e.dt.strftime('%H:%M')}] "
              f"{s.start:.0f} → {e.start:.0f}")

    print("\n用户确认:")
    print("  XD1↑ bi1~3 [09:01~09:58] 6726→6922")
    print("  XD2↓ bi4~6 [09:58~10:35] 6922→6810")
    print("  XD3↑ bi7~16 [10:35~14:54] 6810→6948")


if __name__ == '__main__':
    main()

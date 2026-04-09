#!/usr/bin/env python3
"""
PTA 缠论线段检测 v3 - 修正版
规则：
1. 所有反转候选都需要检测（不只是"笔破坏"）
2. 常规（缺口封闭）：回调低点 < 前一上行笔高点 → 反弹不新高再回落成顶分型 → 立即确认
3. 非常规（缺口未封闭）：回调低点 > 前一上行笔高点 → 等后续底分型两步确认
无未来函数
"""

import pandas as pd
from czsc.py.objects import RawBar
from czsc.py.analyze import CZSC
from czsc.py.enum import Freq


def load_bars(date='2026-04-03'):
    DATA = '/home/admin/.openclaw/workspace/codeman/pta_analysis/data'
    df = pd.read_csv(DATA + '/pta_1min.csv')
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
    def __init__(self, bi_idx, dt, direction, open, close):
        self.bi_idx = bi_idx
        self.dt = dt
        self.direction = direction
        self.open = open
        self.close = close
        self.high = max(open, close)
        self.low = min(open, close)


def get_bi_bars(c):
    result = []
    for i, bi in enumerate(c.bi_list):
        fb, lb = bi.raw_bars[0], bi.raw_bars[-1]
        d = str(bi.direction)
        sp = fb.low if d == '向上' else fb.high
        ep = lb.high if d == '向上' else lb.low
        result.append(BiBar(i, fb.dt, 'up' if d == '向上' else 'down', sp, ep))
    return result


def find_top_fx(bi_bars, start_idx, end_idx_excl):
    """在 start_idx~end_idx_excl 的上行笔中找顶分型：三根连续上行笔，中间close最高"""
    up = [b for b in bi_bars[start_idx:end_idx_excl] if b.direction == 'up']
    if len(up) < 3:
        return None
    for i in range(1, len(up) - 1):
        p, c, n = up[i-1], up[i], up[i+1]
        if c.close > p.close and c.close > n.close:
            return bi_bars.index(c)
    return None


def find_bottom_fx(bi_bars, start_idx, end_idx_excl):
    """在 start_idx~end_idx_excl 的下行笔中找底分型：三根连续下行笔，中间close最低"""
    dn = [b for b in bi_bars[start_idx:end_idx_excl] if b.direction == 'down']
    if len(dn) < 3:
        return None
    for i in range(1, len(dn) - 1):
        p, c, n = dn[i-1], dn[i], dn[i+1]
        if c.close < p.close and c.close < n.close:
            return bi_bars.index(c)
    return None


def detect_xd(bi_bars):
    """线段检测，无未来函数"""
    n = len(bi_bars)
    results = []
    confirmed = set()

    i = 0
    while i < n - 2:
        cur = bi_bars[i]
        next_idx = None
        for j in range(i + 1, n):
            if bi_bars[j].direction != cur.direction:
                next_idx = j
                break

        if next_idx is None:
            break

        next_bi = bi_bars[next_idx]

        if cur.direction == 'up' and next_bi.direction == 'down':
            # 反转候选：上行段末尾出现下行笔
            # 找前一上行笔的高点（用于缺口判断）
            prev_up_idx = None
            for k in range(next_idx - 1, -1, -1):
                if bi_bars[k].direction == 'up':
                    prev_up_idx = k
                    break

            if prev_up_idx is not None:
                prev_up_high = bi_bars[prev_up_idx].close  # 前上行笔终点
                gap_closed = next_bi.low < prev_up_high

                print(f"\n反转候选 bi{next_idx+1}(down): "
                      f"低点={next_bi.low:.0f} vs 前上行笔 bi{prev_up_idx+1}终点={prev_up_high:.0f} | "
                      f"{'封闭(常规)' if gap_closed else '未封闭(非常规)'}")

                if gap_closed:
                    # 常规：等反弹不新高
                    rebound_idx = None
                    for j in range(next_idx + 1, n):
                        if bi_bars[j].direction == 'up':
                            rebound_idx = j
                            break

                    if rebound_idx is not None:
                        rebound = bi_bars[rebound_idx]
                        if rebound.close < prev_up_high:
                            fx = find_top_fx(bi_bars, next_idx, rebound_idx + 1)
                            if fx is not None and fx not in confirmed:
                                print(f"  -> 常规确认! 上行 bi{i+1}~bi{fx+1}")
                                results.append((i, fx, 'up'))
                                confirmed.add(fx)
                                i = fx
                                continue
                else:
                    # 非常规：等反弹后不新高再回落
                    rebound_idx = None
                    for j in range(next_idx + 1, n):
                        if bi_bars[j].direction == 'up':
                            rebound_idx = j
                            break

                    if rebound_idx is not None:
                        rebound = bi_bars[rebound_idx]
                        if rebound.close < prev_up_high:
                            # 找顶分型
                            top_fx = find_top_fx(bi_bars, rebound_idx, n)
                            if top_fx is not None and top_fx not in confirmed:
                                bottom_fx = find_bottom_fx(bi_bars, top_fx, n)
                                if bottom_fx is not None and bottom_fx not in confirmed:
                                    print(f"  -> 非常规两步确认! 上行 bi{i+1}~bi{top_fx+1} | 下行 bi{top_fx+1}~bi{bottom_fx+1}")
                                    results.append((i, top_fx, 'up'))
                                    results.append((top_fx + 1, bottom_fx, 'down'))
                                    confirmed.add(top_fx)
                                    confirmed.add(bottom_fx)
                                    i = bottom_fx
                                    continue

        i = next_idx

    return results


def main():
    bars = load_bars('2026-04-03')
    c = CZSC(bars)
    bi_bars = get_bi_bars(c)

    print("笔序列:")
    for b in bi_bars:
        print(f"  bi{b.bi_idx+1:2d} {b.direction:4s} [{b.dt.strftime('%H:%M')}] "
              f"O={b.open:.0f} C={b.close:.0f} H={b.high:.0f} L={b.low:.0f}")

    print("\n" + "=" * 50)
    results = detect_xd(bi_bars)
    print(f"\n最终线段: {len(results)}条")
    for r in results:
        s_bi = bi_bars[r[0]]
        e_bi = bi_bars[r[1]]
        print(f"  {r[2]:3s} bi{r[0]+1}~bi{r[1]+1} "
              f"[{s_bi.dt.strftime('%H:%M')}~{e_bi.dt.strftime('%H:%M')}] "
              f"{s_bi.open:.0f} -> {e_bi.close:.0f}")


if __name__ == '__main__':
    main()

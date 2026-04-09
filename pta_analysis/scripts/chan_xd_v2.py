#!/usr/bin/env python3
"""
PTA 缠论线段检测 v2 - 修正版
规则：
1. 笔破坏：下行笔终点跌破上行段起点 → 触发反转检测
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
    def __init__(self, bi_idx, dt, direction, open, close, start_bar_idx, end_bar_idx):
        self.bi_idx = bi_idx
        self.dt = dt
        self.direction = direction
        self.open = open
        self.close = close
        self.high = max(open, close)
        self.low = min(open, close)


def get_bi_bars(c, d2i):
    result = []
    for i, bi in enumerate(c.bi_list):
        fb, lb = bi.raw_bars[0], bi.raw_bars[-1]
        d = str(bi.direction)
        sp = fb.low if d == '向上' else fb.high
        ep = lb.high if d == '向上' else lb.low
        result.append(BiBar(i, fb.dt, 'up' if d == '向上' else 'down',
                            sp, ep, d2i[fb.dt], d2i[lb.dt]))
    return result


def find_top_fx(bi_bars, start_idx, end_idx_excl):
    """
    在 start_idx 到 end_idx_excl 的上行笔中找顶分型
    顶分型：三根上行笔的端点，中间那根的close最高
    返回 (fx_stroke_idx, fx_bar_idx)
    """
    up = [b for b in bi_bars[start_idx:end_idx_excl] if b.direction == 'up']
    if len(up) < 3:
        return None
    for i in range(1, len(up) - 1):
        prev, curr, nxt = up[i-1], up[i], up[i+1]
        if curr.close > prev.close and curr.close > nxt.close:
            return (bi_bars.index(curr), bi_bars.index(prev))
    return None


def find_bottom_fx(bi_bars, start_idx, end_idx_excl):
    """
    在 start_idx 到 end_idx_excl 的下行笔中找底分型
    底分型：三根下行笔的端点，中间那根的close最低
    返回 (fx_stroke_idx, fx_bar_idx)
    """
    dn = [b for b in bi_bars[start_idx:end_idx_excl] if b.direction == 'down']
    if len(dn) < 3:
        return None
    for i in range(1, len(dn) - 1):
        prev, curr, nxt = dn[i-1], dn[i], dn[i+1]
        if curr.close < prev.close and curr.close < nxt.close:
            return (bi_bars.index(curr), bi_bars.index(prev))
    return None


def detect_xd(bi_bars):
    """
    线段检测
    返回: [(start_bi, end_bi, direction), ...]
    """
    n = len(bi_bars)
    results = []

    i = 0
    while i < n - 2:
        cur = bi_bars[i]

        # 找下一个反向笔
        next_idx = None
        for j in range(i + 1, n):
            if bi_bars[j].direction != cur.direction:
                next_idx = j
                break
            cur = bi_bars[j]

        if next_idx is None:
            break

        next_bi = bi_bars[next_idx]

        if cur.direction == 'up' and next_bi.direction == 'down':
            # ===== 上行段末尾出现下行笔 =====
            # 笔破坏：下行笔终点跌破上行段起点
            if next_bi.close < bi_bars[i].open:
                # 找前一个上行笔（用于缺口判断）
                prev_up_idx = None
                for k in range(next_idx - 1, -1, -1):
                    if bi_bars[k].direction == 'up':
                        prev_up_idx = k
                        break

                if prev_up_idx is not None:
                    prev_up_high = bi_bars[prev_up_idx].close  # 前上行笔终点
                    gap_closed = next_bi.low < prev_up_high

                    print(f"\n笔破坏 bi{next_idx+1}(down): "
                          f"close={next_bi.close:.0f} < 段起点={bi_bars[i].open:.0f}")
                    print(f"  缺口: bi{prev_up_idx+1}高点={prev_up_high:.0f} | "
                          f"bi{next_idx+1}低点={next_bi.low:.0f} | "
                          f"{'封闭(常规)' if gap_closed else '未封闭(非常规)'}")

                    if gap_closed:
                        # ===== 常规情形 =====
                        # 等反弹：找下一个上行笔
                        rebound_idx = None
                        for j in range(next_idx + 1, n):
                            if bi_bars[j].direction == 'up':
                                rebound_idx = j
                                break

                        if rebound_idx is not None:
                            rebound = bi_bars[rebound_idx]
                            # 反弹不新高：rebound.close < 前上行笔终点
                            if rebound.close < prev_up_high:
                                # 找顶分型确认
                                fx = find_top_fx(bi_bars, next_idx, rebound_idx + 1)
                                if fx is not None:
                                    print(f"  -> 常规确认! 上行段 bi{i+1}~bi{fx[0]+1} 终点={bi_bars[fx[0]].close:.0f}")
                                    results.append((i, fx[0], 'up'))
                                    i = fx[0]
                                    continue
                    else:
                        # ===== 非常规情形 =====
                        # 等反弹后不新高再回落，形成顶分型后再找底分型
                        rebound_idx = None
                        for j in range(next_idx + 1, n):
                            if bi_bars[j].direction == 'up':
                                rebound_idx = j
                                break

                        if rebound_idx is not None:
                            rebound = bi_bars[rebound_idx]
                            if rebound.close < prev_up_high:
                                # 反弹不新高！在rebound后的下行段中找顶分型
                                top_fx = find_top_fx(bi_bars, rebound_idx, n)
                                if top_fx is not None:
                                    # 确认顶分型后，在top_fx后的上行段中找底分型
                                    bottom_fx = find_bottom_fx(bi_bars, top_fx[0], n)
                                    if bottom_fx is not None:
                                        print(f"  -> 非常规两步确认! "
                                              f"上行 bi{i+1}~bi{top_fx[0]+1} | 下行 bi{top_fx[0]+1}~bi{bottom_fx[0]+1}")
                                        results.append((i, top_fx[0], 'up'))
                                        results.append((top_fx[0] + 1, bottom_fx[0], 'down'))
                                        i = bottom_fx[0]
                                        continue

        i = next_idx

    return results


def main():
    bars = load_bars('2026-04-03')
    d2i = {b.dt: i for i, b in enumerate(bars)}
    c = CZSC(bars)
    bi_bars = get_bi_bars(c, d2i)

    print("笔序列:")
    for b in bi_bars:
        print(f"  bi{b.bi_idx+1:2d} {b.direction:4s} [{b.dt.strftime('%H:%M')}] "
              f"O={b.open:.0f} C={b.close:.0f} H={b.high:.0f} L={b.low:.0f}")

    print("\n" + "=" * 50)
    print("线段检测:")
    print("=" * 50)
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

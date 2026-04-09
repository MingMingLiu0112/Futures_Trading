#!/usr/bin/env python3
"""
PTA 缠论线段检测 v1
规则：
- 上行段被下行笔破坏：下行笔终点跌破上行段最低点
- 常规（缺口封闭）：回调低点 < 前一上行笔高点 → 反弹不新高再回落成顶分型 → 立即确认
- 非常规（缺口未封闭）：回调低点 > 前一上行笔高点 → 等后续底分型两步确认
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
    good = (ap['close'].notna()) & (ap['close'] > 0)
    ap = ap[good]
    ap = ap.sort_values('datetime').reset_index(drop=True)
    ap['real_time'] = ap['datetime'] + pd.Timedelta(hours=8)
    bars = []
    for i, (_, r) in enumerate(ap.iterrows()):
        bars.append(RawBar(symbol='TA', id=i, dt=r['real_time'],
            open=float(r['open']), high=float(r['high']), low=float(r['low']),
            close=float(r['close']), vol=float(r['volume']), amount=0, freq=Freq.F1))
    return bars


class BiBar:
    def __init__(self, bi_idx, dt, direction, start_p, end_p, start_bar_idx, end_bar_idx):
        self.bi_idx = bi_idx
        self.dt = dt
        self.direction = direction
        self.open = start_p
        self.close = end_p
        self.high = max(start_p, end_p)
        self.low = min(start_p, end_p)


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


def find_top_fx_in_down_feature(bi_bars, start_idx, end_idx):
    """在下行段特征序列（上行笔）中找顶分型
    返回顶分型位置（上行笔索引），没有返回None"""
    # 收集从start_idx到end_idx的上行笔
    up_bars = [b for b in bi_bars[start_idx:end_idx+1] if b.direction == 'up']
    if len(up_bars) < 3:
        return None
    for i in range(1, len(up_bars) - 1):
        prev = up_bars[i-1]
        curr = up_bars[i]
        nxt = up_bars[i+1]
        cond = (curr.high > prev.high) & (curr.high > nxt.high)
        if cond:
            return bi_bars.index(curr)
    return None


def find_bottom_fx_in_up_feature(bi_bars, start_idx, end_idx):
    """在上行段特征序列（下行笔）中找底分型
    返回底分型位置（下行笔索引），没有返回None"""
    down_bars = [b for b in bi_bars[start_idx:end_idx+1] if b.direction == 'down']
    if len(down_bars) < 3:
        return None
    for i in range(1, len(down_bars) - 1):
        prev = down_bars[i-1]
        curr = down_bars[i]
        nxt = down_bars[i+1]
        cond = (curr.low < prev.low) & (curr.low < nxt.low)
        if cond:
            return bi_bars.index(curr)
    return None


def detect_xd(bi_bars):
    """
    线段检测 - 两步确认
    返回: [(start_bi_idx, end_bi_idx, direction), ...]
    """
    n = len(bi_bars)
    results = []

    # 从头开始扫描
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
            # 上行段末尾出现下行笔 - 检查是否笔破坏（终点跌破段起点）
            if next_bi.close < bi_bars[i].open:
                # 笔破坏！检查缺口
                # 找前一个上行笔的高点（用于缺口判断）
                prev_up_idx = None
                for k in range(next_idx - 1, -1, -1):
                    if bi_bars[k].direction == 'up':
                        prev_up_idx = k
                        break

                if prev_up_idx is not None:
                    prev_up_high = bi_bars[prev_up_idx].high
                    gap_closed = next_bi.low < prev_up_high

                    print(f"\n笔破坏 bi{next_idx+1}(down): low={next_bi.low:.0f} < "
                          f"段起点={bi_bars[i].open:.0f}")
                    print(f"  前上行笔 bi{prev_up_idx+1} high={prev_up_high:.0f} | "
                          f"缺口: {'封闭(常规)' if gap_closed else '未封闭(非常规)'}")

                    if gap_closed:
                        # ===== 常规情形 =====
                        # 找反弹上行笔（下一个）
                        rebound_idx = None
                        for j in range(next_idx + 1, n):
                            if bi_bars[j].direction == 'up':
                                rebound_idx = j
                                break

                        if rebound_idx is not None:
                            rebound = bi_bars[rebound_idx]
                            prev_up_close = bi_bars[prev_up_idx].close
                            if rebound.close < prev_up_close:
                                # 反弹不新高！在回调段内找顶分型
                                fx = find_top_fx_in_down_feature(bi_bars, next_idx, rebound_idx)
                                if fx is not None:
                                    print(f"  -> 常规确认！上行段 bi{i+1}~bi{fx+1}")
                                    results.append((i, fx, 'up'))
                                    i = fx
                                    continue
                    else:
                        # ===== 非常规情形 =====
                        # 等反弹
                        rebound_idx = None
                        for j in range(next_idx + 1, n):
                            if bi_bars[j].direction == 'up':
                                rebound_idx = j
                                break

                        if rebound_idx is not None:
                            rebound = bi_bars[rebound_idx]
                            prev_up_close = bi_bars[prev_up_idx].close
                            if rebound.close < prev_up_close:
                                # 反弹不新高！在rebound后的下行段中找顶分型
                                top_fx = find_top_fx_in_down_feature(bi_bars, rebound_idx, n - 1)
                                if top_fx is not None:
                                    # 确认顶分型后再找底分型
                                    bottom_fx = find_bottom_fx_in_up_feature(bi_bars, top_fx, n - 1)
                                    if bottom_fx is not None:
                                        print(f"  -> 非常规两步确认！上行段 bi{i+1}~bi{top_fx+1}, 下行段 bi{top_fx+1}~bi{bottom_fx+1}")
                                        results.append((i, top_fx, 'up'))
                                        results.append((top_fx + 1, bottom_fx, 'down'))
                                        i = bottom_fx
                                        continue

        i = next_idx

    return results


def main():
    bars = load_bars('2026-04-03')
    d2i = {b.dt: i for i, b in enumerate(bars)}
    c = CZSC(bars)
    bi_bars = get_bi_bars(c, d2i)

    print(f"笔数量: {len(bi_bars)}")
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

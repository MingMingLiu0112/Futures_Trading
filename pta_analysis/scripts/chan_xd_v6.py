#!/usr/bin/env python3
"""
PTA 缠论线段检测 v6 - 修正版
修正：笔破坏条件 = 下行笔.low < 前一上行笔.high（常规情形）

参考：缠论第67课、第71课
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
        self.start = start_p  # 向上笔=首bar.low, 向下笔=首bar.high
        self.end = end_p      # 向上笔=末bar.high, 向下笔=末bar.low
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


def find_top_fx(up_bi_list):
    """上行笔列表中找顶分型：三根相邻，上行的端点中间最高"""
    if len(up_bi_list) < 3:
        return None
    for i in range(1, len(up_bi_list) - 1):
        p = up_bi_list[i-1].end
        c = up_bi_list[i].end
        n = up_bi_list[i+1].end
        if c > p and c > n:
            return up_bi_list[i]
    return None


def find_bottom_fx(dn_bi_list):
    """下行笔列表中找底分型：三根相邻，下行的端点中间最低"""
    if len(dn_bi_list) < 3:
        return None
    for i in range(1, len(dn_bi_list) - 1):
        p = dn_bi_list[i-1].end
        c = dn_bi_list[i].end
        n = dn_bi_list[i+1].end
        if c < p and c < n:
            return dn_bi_list[i]
    return None


def detect_xd(bi_bars):
    """线段检测：笔破坏(常规) → 分型确认"""
    n = len(bi_bars)
    results = []

    i = 0
    while i < n - 1:
        cur = bi_bars[i]

        # 找下一个反向笔
        next_idx = None
        for j in range(i + 1, n):
            if bi_bars[j].direction != cur.direction:
                next_idx = j
                break
        if next_idx is None:
            break

        next_bi = bi_bars[next_idx]

        if cur.direction == 'up' and next_bi.direction == 'down':
            # ===== 上行段末尾出现下行笔 → 检查笔破坏 =====
            prev_up_idx = None
            for k in range(next_idx - 1, -1, -1):
                if bi_bars[k].direction == 'up':
                    prev_up_idx = k
                    break

            if prev_up_idx is not None:
                prev_up_high = bi_bars[prev_up_idx].high   # 前一上行笔的高点
                gap_closed = next_bi.low < prev_up_high      # 常规情形条件！

                print(f"\n下行笔 bi{next_idx+1}: low={next_bi.low:.0f} vs "
                      f"前一上行笔 bi{prev_up_idx+1} high={prev_up_high:.0f} | "
                      f"{'✓常规(笔破坏)' if gap_closed else '✗非常规'}")

                if gap_closed:
                    # 常规情形：立即检查分型确认
                    # 收集 next_idx 到下一个上行笔+1 的上行笔
                    rebound_up_idx = None
                    for j in range(next_idx + 1, n):
                        if bi_bars[j].direction == 'up':
                            rebound_up_idx = j
                            break

                    if rebound_up_idx is not None:
                        # 在 [next_idx, rebound_up_idx] 内找顶分型
                        up_in_range = [b for b in bi_bars[next_idx:rebound_up_idx+1]
                                      if b.direction == 'up']
                        fx = find_top_fx(up_in_range)
                        if fx is not None:
                            fx_idx = bi_bars.index(fx)
                            results.append((i, fx_idx, 'up'))
                            print(f"  → 确认上行段 bi{i+1}~bi{fx_idx+1} | "
                                  f"终点={fx.end:.0f} | 分型={fx.bi_idx+1}")
                            i = fx_idx
                            continue

        i = next_idx

    return results


def main():
    bars = load_bars('2026-04-03')
    c = CZSC(bars)
    bi_bars = get_bi_bars(c)

    print("=" * 55)
    print("PTA 4月3日 缠论线段检测 v6")
    print("=" * 55)
    print(f"\n笔序列 ({len(bi_bars)}笔):")
    for b in bi_bars:
        print(f"  bi{b.bi_idx+1:2d} {b.direction:4s} [{b.dt.strftime('%H:%M')}] "
              f"start={b.start:.0f} end={b.end:.0f} "
              f"high={b.high:.0f} low={b.low:.0f}")

    print("\n" + "=" * 55)
    results = detect_xd(bi_bars)
    print(f"\n检测结果: {len(results)}条线段")
    print("-" * 55)
    for r in results:
        s = bi_bars[r[0]]
        e = bi_bars[r[1]]
        print(f"  {r[2]:3s} bi{r[0]+1}~bi{r[1]+1} "
              f"[{s.dt.strftime('%H:%M')}~{e.dt.strftime('%H:%M')}] "
              f"{s.start:.0f} → {e.end:.0f}")

    print("\n用户确认:")
    print("  XD1↑ bi1~3 [09:01~09:58] 6726→6922")
    print("  XD2↓ bi4~6 [09:58~10:35] 6922→6810")
    print("  XD3↑ bi7~16 [10:35~14:54] 6810→6948")


if __name__ == '__main__':
    main()

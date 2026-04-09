#!/usr/bin/env python3
"""
PTA 缠论线段检测 - 最终正确版
规则：gap封闭后，需下一走势确认；无确认走势则反转自动确认
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


def find_prev_same(bi_bars, idx):
    """找前一个同向笔"""
    for k in range(idx - 1, -1, -1):
        if bi_bars[k].direction == bi_bars[idx].direction:
            return k
    return None


def find_next_same(bi_bars, idx):
    """找下一个同向笔"""
    for j in range(idx + 1, len(bi_bars)):
        if bi_bars[j].direction == bi_bars[idx].direction:
            return j
    return None


def detect_xd(bi_bars):
    n = len(bi_bars)
    results = []
    i = 0
    while i < n:
        cur = bi_bars[i]
        xd_start = i

        # 找下一个反向笔
        next_idx = None
        for j in range(i + 1, n):
            if bi_bars[j].direction != cur.direction:
                next_idx = j
                break
        if next_idx is None:
            results.append((xd_start, n - 1, cur.direction))
            break

        next_bi = bi_bars[next_idx]

        if cur.direction == 'up' and next_bi.direction == 'down':
            # ===== 上行段末尾出现下行笔 =====
            # gap封闭 = 下行笔终点 < 被破坏笔的终点
            broken_end = cur.end
            gap_closed = next_bi.end < broken_end

            print(f"\n候选 bi{next_idx+1}(dn): gap={gap_closed} "
                  f"(dn_end={next_bi.end:.0f} < broken_end={broken_end:.0f})")

            if gap_closed:
                # 找下一UP笔（确认走势）
                confirm_idx = None
                for j in range(next_idx + 1, n):
                    if bi_bars[j].direction == 'up':
                        confirm_idx = j
                        break

                if confirm_idx is not None:
                    confirm = bi_bars[confirm_idx]
                    # 确认：下一UP笔是否 > 被破坏笔起点（创新高相对于起点）？
                    if confirm.end <= cur.start:
                        results.append((xd_start, next_idx, 'up'))
                        print(f"  ✓ 反转确认! bi{xd_start+1}~bi{next_idx+1}")
                        i = next_idx + 1
                        continue
                    else:
                        print(f"  ✗ 反转被拒(bi{confirm_idx+1}={confirm.end:.0f}>{cur.start:.0f}), 延续")
                        i = next_idx  # 继续从当前段的下一候选笔
                        continue
                else:
                    results.append((xd_start, next_idx, 'up'))
                    print(f"  ✓ 反转确认(无确认走势)")
                    i = next_idx + 1
                    continue

        elif cur.direction == 'down' and next_bi.direction == 'up':
            # ===== 下行段末尾出现上行笔 =====
            broken_end = cur.end
            gap_closed = next_bi.end > broken_end

            print(f"\n候选 bi{next_idx+1}(up): gap={gap_closed}")

            if gap_closed:
                confirm_idx = None
                for j in range(next_idx + 1, n):
                    if bi_bars[j].direction == 'down':
                        confirm_idx = j
                        break

                if confirm_idx is not None:
                    confirm = bi_bars[confirm_idx]
                    if confirm.end >= cur.start:
                        results.append((xd_start, next_idx, 'down'))
                        print(f"  ✓ 反转确认! bi{xd_start+1}~bi{next_idx+1}")
                        i = next_idx + 1
                        continue
                    else:
                        print(f"  ✗ 反转被拒")
                        i = next_idx + 1
                        continue
                else:
                    results.append((xd_start, next_idx, 'down'))
                    print(f"  ✓ 反转确认(无确认走势)")
                    i = next_idx + 1
                    continue

        i = next_idx

    return results


def main():
    bars = load_bars('2026-04-03')
    c = CZSC(bars)
    bi_bars = get_bi_bars(c)

    print("=" * 60)
    print("PTA 4月3日 缠论线段检测")
    print("=" * 60)
    print(f"\n笔序列 ({len(bi_bars)}笔):")
    for b in bi_bars:
        print(f"  bi{b.bi_idx+1:2d} {b.direction:4s} [{b.dt.strftime('%H:%M')}] "
              f"start={b.start:.0f} end={b.end:.0f}")

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
              f"{s.start:.0f} -> {e.start:.0f}")

    print("\n用户确认:")
    print("  XD1↑ bi1~3 [09:01~09:58] 6726→6922")
    print("  XD2↓ bi4~6 [09:58~10:35] 6922→6810")
    print("  XD3↑ bi7~16 [10:35~14:54] 6810→6948")


if __name__ == '__main__':
    main()

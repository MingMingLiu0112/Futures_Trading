#!/usr/bin/env python3
"""
PTA 缠论线段检测 v5 - 基于正确的笔数据
规则：
- 反转条件（待验证）：下行笔的起点 < 前一上行笔的起点 → 反转成立
- 缺口：反转笔的起点 > 前一上行笔的终点 → 缺口未封闭（非常规）
- 常规：缺口封闭，立即确认
- 非常规：缺口未封闭，等后续底分型两步确认
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
    def __init__(self, bi_idx, dt, direction, start_p, end_p):
        self.bi_idx = bi_idx
        self.dt = dt
        self.direction = direction
        self.start = start_p  # 笔起点（向上笔=首bar.low，向下笔=首bar.high）
        self.end = end_p      # 笔终点（向上笔=末bar.high，向下笔=末bar.low）
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


def find_top_fx_in_feature(up_bi_list):
    """在一组上行笔（作为特征序列K线）中找顶分型：三根相邻K线，中间close最高"""
    if len(up_bi_list) < 3:
        return None
    for i in range(1, len(up_bi_list) - 1):
        p = up_bi_list[i-1].end
        c = up_bi_list[i].end
        n = up_bi_list[i+1].end
        if c > p and c > n:
            return up_bi_list[i]
    return None


def find_bottom_fx_in_feature(down_bi_list):
    """在一组下行笔（作为特征序列K线）中找底分型：三根相邻K线，中间close最低"""
    if len(down_bi_list) < 3:
        return None
    for i in range(1, len(down_bi_list) - 1):
        p = down_bi_list[i-1].end
        c = down_bi_list[i].end
        n = down_bi_list[i+1].end
        if c < p and c < n:
            return down_bi_list[i]
    return None


def detect_xd(bi_bars):
    """
    线段检测
    
    反转条件（试验）：下行笔的起点 < 前一上行笔的起点 → 反转候选
    缺口：反转笔的起点 > 前一上行笔的终点 → 缺口未封闭（非常规）
    """
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
            # ===== 上行段末尾出现下行笔 =====
            # 反转条件：下行笔的起点 < 前一上行笔的起点
            prev_up_idx = None
            for k in range(next_idx - 1, -1, -1):
                if bi_bars[k].direction == 'up':
                    prev_up_idx = k
                    break

            if prev_up_idx is not None:
                prev_up_start = bi_bars[prev_up_idx].start
                prev_up_end = bi_bars[prev_up_idx].end
                reversal = next_bi.start < prev_up_start
                gap_closed = next_bi.start < prev_up_end

                print(f"\n候选: bi{next_idx+1}(down) start={next_bi.start:.0f} vs "
                      f"前up笔 bi{prev_up_idx+1} start={prev_up_start:.0f} end={prev_up_end:.0f} | "
                      f"反转={reversal} 缺口{'封闭' if gap_closed else '未封闭'}")

                if reversal:
                    if gap_closed:
                        # 常规：立即确认
                        results.append((i, next_idx, 'up'))
                        print(f"  -> 常规确认! bi{i+1}~bi{next_idx+1}")
                        i = next_idx
                        continue
                    else:
                        # 非常规：等后续底分型
                        rebound_idx = None
                        for j in range(next_idx + 1, n):
                            if bi_bars[j].direction == 'up':
                                rebound_idx = j
                                break

                        if rebound_idx is not None:
                            rebound = bi_bars[rebound_idx]
                            if rebound.end < prev_up_end:
                                # 反弹不新高 → 找顶分型再找底分型
                                top_fx = find_top_fx_in_feature(
                                    [b for b in bi_bars[rebound_idx:] if b.direction == 'up'])
                                if top_fx is not None:
                                    top_idx = bi_bars.index(top_fx)
                                    bottom_fx = find_bottom_fx_in_feature(
                                        [b for b in bi_bars[top_idx:] if b.direction == 'down'])
                                    if bottom_fx is not None:
                                        bot_idx = bi_bars.index(bottom_fx)
                                        print(f"  -> 非常规确认! 上行 bi{i+1}~bi{top_idx+1} | 下行 bi{top_idx+1}~bi{bot_idx+1}")
                                        results.append((i, top_idx, 'up'))
                                        results.append((top_idx + 1, bot_idx, 'down'))
                                        i = bot_idx
                                        continue

        i = next_idx

    return results


def main():
    bars = load_bars('2026-04-03')
    c = CZSC(bars)
    bi_bars = get_bi_bars(c)

    print("=" * 60)
    print("PTA 4月3日 缠论线段检测 v5")
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
        print(f"  {r[2]:3s} bi{r[0]+1}~bi{r[1]+1} "
              f"[{s.dt.strftime('%H:%M')}~{e.dt.strftime('%H:%M')}] "
              f"{s.start:.0f} -> {e.end:.0f}")

    print("\n用户确认的线段:")
    print("  XD1↑ bi1~3 [09:01~09:58] 6726->6922")
    print("  XD2↓ bi4~6 [09:58~10:35] 6922->6810")
    print("  XD3↑ bi7~16 [10:35~14:54] 6810->6948")


if __name__ == '__main__':
    main()

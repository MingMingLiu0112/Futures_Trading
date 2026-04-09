#!/usr/bin/env python3
"""
PTA 缠论线段检测 - 修正比高低版

规则（用户最终指正）：
  - 同方向 = 延续（比高低点抬升/下降）
  - 反方向出现 = 检查能否破坏
    DOWN破坏UP：DOWN笔的LOW < 前一个UP笔的LOW → 破坏
    UP破坏DOWN：UP笔的HIGH > 前一个DOWN笔的HIGH → 破坏
  - 破坏成功 → 前段结束，新段开始
  - 破坏失败 → 前段延续

验证：
  bi10.down low=6876 > bi9.up low=6766 → 不破坏，延续
  bi11.up high=6948 > bi10.down high=6934 → 不破坏，延续
  bi12.down low=6894 < bi11.up low=6894 → 破坏！XD1结束
  bi13.up high=6996 > bi12.down high=6916 → 不破坏，延续
  bi14.down low=6944 > bi13.up low=6916 → 不破坏，延续
  bi15.up high=7010 > bi14.down high=6944 → 不破坏，延续
  bi16.down low=6948 > bi15.up low=6944 → 不破坏，延续
  → XD1=bi1~3, XD2=bi4~6, XD3=bi7~16 ✓
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
    def __init__(self, bi_idx, dt, direction, start_p, end_p, high, low):
        self.bi_idx = bi_idx
        self.dt = dt
        self.direction = direction
        self.start = start_p
        self.end = end_p
        self.high = high
        self.low = low


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


def detect_xd(bi_bars):
    n = len(bi_bars)
    results = []
    
    seg_start = 0
    seg_dir = bi_bars[0].direction
    last_opposite_idx = 1 if n >= 2 else None
    i = 2
    
    while i < n:
        cur = bi_bars[i]
        
        if cur.direction == seg_dir:
            i += 1
        else:
            prev_opposite = bi_bars[last_opposite_idx]
            destroyed = False
            
            if seg_dir == 'up' and cur.direction == 'down':
                # DOWN破坏UP：DOWN笔的LOW < 前一个UP笔的LOW
                if cur.low < prev_opposite.low:
                    destroyed = True
                    print(f"  bi{cur.bi_idx+1}.low={cur.low:.0f} < bi{prev_opposite.bi_idx+1}.low={prev_opposite.low:.0f} → 破坏✓")
            elif seg_dir == 'down' and cur.direction == 'up':
                # UP破坏DOWN：UP笔的HIGH > 前一个DOWN笔的HIGH
                if cur.high > prev_opposite.high:
                    destroyed = True
                    print(f"  bi{cur.bi_idx+1}.high={cur.high:.0f} > bi{prev_opposite.bi_idx+1}.high={prev_opposite.high:.0f} → 破坏✓")
            
            if destroyed:
                seg_end = i - 1
                seg_len = seg_end - seg_start + 1
                results.append((seg_start, seg_end, seg_dir))
                print(f"  ✓ {seg_dir}段: bi{seg_start+1}~bi{seg_end+1} "
                      f"[{bi_bars[seg_start].dt.strftime('%H:%M')}~{bi_bars[seg_end].dt.strftime('%H:%M')}] "
                      f"({seg_len}笔)")
                seg_start = last_opposite_idx
                seg_dir = cur.direction
                last_opposite_idx = i
            else:
                last_opposite_idx = i
            
            i += 1
    
    if seg_start < n:
        seg_end = n - 1
        seg_len = seg_end - seg_start + 1
        if seg_len >= 3:
            results.append((seg_start, seg_end, seg_dir))
            print(f"  ✓ {seg_dir}段(末尾): bi{seg_start+1}~bi{seg_end+1} "
                  f"[{bi_bars[seg_start].dt.strftime('%H:%M')}~{bi_bars[seg_end].dt.strftime('%H:%M')}] "
                  f"({seg_len}笔)")
    
    return results


def main():
    bars = load_bars('2026-04-03')
    c = CZSC(bars)
    bi_bars = get_bi_bars(c)

    print("=" * 60)
    print("PTA 4月3日 缠论线段检测")
    print("=" * 60)
    for b in bi_bars:
        print(f"  bi{b.bi_idx+1:2d} {b.direction:4s} [{b.dt.strftime('%H:%M')}] "
              f"start={b.start:.0f} end={b.end:.0f} high={b.high:.0f} low={b.low:.0f}")

    print()
    results = detect_xd(bi_bars)

    print(f"\n检测结果: {len(results)}条线段")
    for r in results:
        s = bi_bars[r[0]]
        e = bi_bars[r[1]]
        n_bi = r[1] - r[0] + 1
        print(f"  {r[2]:4s}  bi{r[0]+1}~bi{r[1]+1}  ({n_bi}笔)  "
              f"[{s.dt.strftime('%H:%M')}~{e.dt.strftime('%H:%M')}]  "
              f"{s.start:.0f} → {e.end:.0f}")

    print("\n用户确认:")
    print("  XD1↑ bi1~3 [09:01~09:58] 6726→6922")
    print("  XD2↓ bi4~6 [09:58~10:35] 6922→6810")
    print("  XD3↑ bi7~16 [10:35~14:54] 6810→6948")


if __name__ == '__main__':
    main()

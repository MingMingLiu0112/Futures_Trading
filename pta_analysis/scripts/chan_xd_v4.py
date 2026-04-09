#!/usr/bin/env python3
"""
PTA 缠论线段检测 v4 - 基于"假设-验证"框架
参考：缠论第67课(线段划分标准) + 第71课(再分辨)

核心算法：
1. 扫描笔序列，每当出现反向笔，就假设该点为线段分界点
2. 用特征序列分型判断验证假设
3. 满足条件则确认，不满足则延续原线段

线段破坏判断：
- 上升段：下行笔终点跌破段内最低点 → 触发破坏检测
- 常规情形（缺口封闭）：下行笔低点 < 前一上行笔高点 → 立即确认
- 非常规情形（缺口未封闭）：需等特征序列底分型确认
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
        self.open = open   # 起点价格
        self.close = close  # 终点价格
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


def find_top_fx_in_feature(up_bi_list):
    """
    在一组上行笔（作为特征序列K线）中找顶分型
    顶分型：三根相邻K线，中间那根的收盘价最高
    返回顶分型所在的上行笔索引，没有返回None
    """
    if len(up_bi_list) < 3:
        return None
    for i in range(1, len(up_bi_list) - 1):
        prev_close = up_bi_list[i-1].close
        curr_close = up_bi_list[i].close
        nxt_close = up_bi_list[i+1].close
        if curr_close > prev_close and curr_close > nxt_close:
            return up_bi_list[i]
    return None


def find_bottom_fx_in_feature(down_bi_list):
    """
    在一组下行笔（作为特征序列K线）中找底分型
    底分型：三根相邻K线，中间那根的收盘价最低
    返回底分型所在的下行笔索引，没有返回None
    """
    if len(down_bi_list) < 3:
        return None
    for i in range(1, len(down_bi_list) - 1):
        prev_close = down_bi_list[i-1].close
        curr_close = down_bi_list[i].close
        nxt_close = down_bi_list[i+1].close
        if curr_close < prev_close and curr_close < nxt_close:
            return down_bi_list[i]
    return None


def detect_xd(bi_bars):
    """
    线段检测 - "假设-验证"框架
    
    步骤：
    1. 从左到右扫描笔序列
    2. 当上行笔出现新低（跌破段内最低点）→ 可能的新分段
    3. 检查是否笔破坏：下行笔终点 < 上行段内最低点
    4. 笔破坏 → 找前一同向笔（用于判断缺口）
    5. 缺口封闭 → 常规确认（顶分型即确认）
    6. 缺口未封闭 → 非常规（等底分型两步确认）
    """
    n = len(bi_bars)
    results = []  # [(start_bi_idx, end_bi_idx, direction)]
    confirmed_ends = set()  # 已确认的线段终点索引

    # 初始化第一个线段候选（从第一笔开始向上）
    if bi_bars[0].direction != 'up':
        return results
    
    xd_start = 0
    xd_dir = 'up'
    
    i = 0
    while i < n:
        cur = bi_bars[i]
        
        if xd_dir == 'up':
            # ===== 扫描上行段 =====
            # 找下一个下行笔
            next_idx = None
            for j in range(i + 1, n):
                if bi_bars[j].direction == 'down':
                    next_idx = j
                    break
            
            if next_idx is None:
                # 没有下行笔，上行段延续到结尾
                results.append((xd_start, n - 1, xd_dir))
                break
            
            next_bi = bi_bars[next_idx]
            
            # 检查是否笔破坏：下行笔终点跌破上行段起点
            # （注意：不是跌破段内最低点，因为段内最低点就是起点）
            if next_bi.close < bi_bars[xd_start].open:
                # 笔破坏！找前一上行笔（用于判断缺口）
                prev_up_idx = None
                for k in range(next_idx - 1, -1, -1):
                    if bi_bars[k].direction == 'up':
                        prev_up_idx = k
                        break
                
                if prev_up_idx is not None:
                    prev_up_end = bi_bars[prev_up_idx].close  # 前上行笔终点
                    prev_up_start = bi_bars[prev_up_idx].open  # 前上行笔起点
                    
                    # 缺口判断：下行笔起点 vs 前上行笔终点
                    # 缺口封闭：next_bi.open < prev_up_end
                    # 缺口未封闭：next_bi.open > prev_up_end
                    gap_closed = next_bi.open < prev_up_end
                    
                    print(f"\n候选分界点 bi{next_idx+1}(down): "
                          f"终点={next_bi.close:.0f} < 段起点={bi_bars[xd_start].open:.0f}")
                    print(f"  前上行笔 bi{prev_up_idx+1}: 起点={prev_up_start:.0f} 终点={prev_up_end:.0f}")
                    print(f"  bi{next_idx+1}起点={next_bi.open:.0f} | "
                          f"缺口: {'封闭(常规)' if gap_closed else '未封闭(非常规)'}")
                    
                    if gap_closed:
                        # ===== 常规情形 =====
                        # 在[next_idx, next_up]范围内找顶分型
                        # 特征序列：上行笔序列
                        rebound_up_idx = None
                        for j in range(next_idx + 1, n):
                            if bi_bars[j].direction == 'up':
                                rebound_up_idx = j
                                break
                        
                        if rebound_up_idx is not None:
                            # 收集从next_idx到rebound_up_idx的上行笔
                            up_in_range = [b for b in bi_bars[next_idx:rebound_up_idx+1] 
                                          if b.direction == 'up']
                            fx = find_top_fx_in_feature(up_in_range)
                            if fx is not None:
                                fx_idx = bi_bars.index(fx)
                                print(f"  -> 常规确认! 上行段 bi{xd_start+1}~bi{fx_idx+1} 终点={fx.close:.0f}")
                                results.append((xd_start, fx_idx, xd_dir))
                                confirmed_ends.add(fx_idx)
                                # 从分界点开始新的下行段
                                xd_start = next_idx
                                xd_dir = 'down'
                                i = next_idx
                                continue
                    else:
                        # ===== 非常规情形 =====
                        # 等反弹上行笔
                        rebound_up_idx = None
                        for j in range(next_idx + 1, n):
                            if bi_bars[j].direction == 'up':
                                rebound_up_idx = j
                                break
                        
                        if rebound_up_idx is not None:
                            rebound = bi_bars[rebound_up_idx]
                            print(f"  反弹上行笔 bi{rebound_up_idx+1}: 终点={rebound.close:.0f}")
                            
                            # 在rebound后的下行段中找顶分型
                            top_fx = None
                            for j in range(rebound_up_idx + 1, n - 2):
                                # 收集从rebound_up_idx+1到j+1的下行笔
                                dn_in_range = [b for b in bi_bars[rebound_up_idx:j+2] 
                                              if b.direction == 'down']
                                fx = find_bottom_fx_in_feature(dn_in_range)
                                if fx is not None:
                                    top_fx = bi_bars.index(fx)
                                    break
                            
                            if top_fx is not None:
                                # 确认顶分型后，在top_fx后的上行段中找底分型
                                bottom_fx = None
                                for j in range(top_fx + 1, n - 2):
                                    up_in_range = [b for b in bi_bars[top_fx:j+2] 
                                                  if b.direction == 'up']
                                    fx = find_top_fx_in_feature(up_in_range)
                                    if fx is not None:
                                        bottom_fx = bi_bars.index(fx)
                                        break
                                
                                if bottom_fx is not None:
                                    print(f"  -> 非常规两步确认! "
                                          f"上行 bi{xd_start+1}~bi{top_fx+1} | 下行 bi{top_fx+1}~bi{bottom_fx+1}")
                                    results.append((xd_start, top_fx, xd_dir))
                                    results.append((top_fx + 1, bottom_fx, 'down'))
                                    confirmed_ends.add(top_fx)
                                    confirmed_ends.add(bottom_fx)
                                    xd_start = bottom_fx + 1
                                    xd_dir = 'up'
                                    i = bottom_fx + 1
                                    continue
            
            # 没有笔破坏或未确认，继续扫描
            i = next_idx if next_idx is not None else i + 1
            
        else:
            # ===== 扫描下行段 =====
            # 找下一个上行笔
            next_idx = None
            for j in range(i + 1, n):
                if bi_bars[j].direction == 'up':
                    next_idx = j
                    break
            
            if next_idx is None:
                results.append((xd_start, n - 1, xd_dir))
                break
            
            next_bi = bi_bars[next_idx]
            
            # 检查是否笔破坏：上行笔终点升破下行段起点
            if next_bi.close > bi_bars[xd_start].open:
                # 笔破坏！
                prev_down_idx = None
                for k in range(next_idx - 1, -1, -1):
                    if bi_bars[k].direction == 'down':
                        prev_down_idx = k
                        break
                
                if prev_down_idx is not None:
                    prev_down_end = bi_bars[prev_down_idx].close
                    gap_closed = next_bi.open > prev_down_end  # 下行段中缺口封闭判断相反
                    
                    print(f"\n候选分界点 bi{next_idx+1}(up): "
                          f"终点={next_bi.close:.0f} > 段起点={bi_bars[xd_start].open:.0f}")
                    print(f"  前下行笔 bi{prev_down_idx+1}终点={prev_down_end:.0f} | "
                          f"缺口: {'封闭(常规)' if gap_closed else '未封闭(非常规)'}")
                    
                    if gap_closed:
                        # 常规：找底分型确认
                        rebound_down_idx = None
                        for j in range(next_idx + 1, n):
                            if bi_bars[j].direction == 'down':
                                rebound_down_idx = j
                                break
                        
                        if rebound_down_idx is not None:
                            dn_in_range = [b for b in bi_bars[next_idx:rebound_down_idx+1]
                                          if b.direction == 'down']
                            fx = find_bottom_fx_in_feature(dn_in_range)
                            if fx is not None:
                                fx_idx = bi_bars.index(fx)
                                results.append((xd_start, fx_idx, xd_dir))
                                confirmed_ends.add(fx_idx)
                                xd_start = next_idx
                                xd_dir = 'up'
                                i = next_idx
                                continue
                    else:
                        # 非常规：等反弹后再回落找底分型
                        rebound_down_idx = None
                        for j in range(next_idx + 1, n):
                            if bi_bars[j].direction == 'down':
                                rebound_down_idx = j
                                break
                        
                        if rebound_down_idx is not None:
                            bottom_fx = None
                            for j in range(rebound_down_idx + 1, n - 2):
                                dn_in_range = [b for b in bi_bars[rebound_down_idx:j+2]
                                              if b.direction == 'down']
                                fx = find_bottom_fx_in_feature(dn_in_range)
                                if fx is not None:
                                    bottom_fx = bi_bars.index(fx)
                                    break
                            
                            if bottom_fx is not None:
                                top_fx = None
                                for j in range(bottom_fx + 1, n - 2):
                                    up_in_range = [b for b in bi_bars[bottom_fx:j+2]
                                                  if b.direction == 'up']
                                    fx = find_top_fx_in_feature(up_in_range)
                                    if fx is not None:
                                        top_fx = bi_bars.index(fx)
                                        break
                                
                                if top_fx is not None:
                                    results.append((xd_start, bottom_fx, xd_dir))
                                    results.append((bottom_fx + 1, top_fx, 'up'))
                                    confirmed_ends.add(bottom_fx)
                                    confirmed_ends.add(top_fx)
                                    xd_start = top_fx + 1
                                    xd_dir = 'down'
                                    i = top_fx + 1
                                    continue
            
            i = next_idx if next_idx is not None else i + 1
    
    return results


def main():
    bars = load_bars('2026-04-03')
    c = CZSC(bars)
    bi_bars = get_bi_bars(c)

    print("=" * 60)
    print("PTA 4月3日 缠论线段检测 v4")
    print("=" * 60)
    print(f"\n笔序列 ({len(bi_bars)}笔):")
    for b in bi_bars:
        print(f"  bi{b.bi_idx+1:2d} {b.direction:4s} [{b.dt.strftime('%H:%M')}] "
              f"O={b.open:.0f} C={b.close:.0f}")

    print("\n" + "=" * 60)
    results = detect_xd(bi_bars)
    print(f"\n线段检测结果: {len(results)}条")
    print("-" * 60)
    for r in results:
        s_bi = bi_bars[r[0]]
        e_bi = bi_bars[r[1]]
        n_bi = r[1] - r[0] + 1
        print(f"  {r[2]:3s} bi{r[0]+1}~bi{r[1]+1} ({n_bi}笔) "
              f"[{s_bi.dt.strftime('%H:%M')}~{e_bi.dt.strftime('%H:%M')}] "
              f"{s_bi.open:.0f} -> {e_bi.close:.0f}")


if __name__ == '__main__':
    main()

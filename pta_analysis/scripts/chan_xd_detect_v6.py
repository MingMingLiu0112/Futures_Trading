#!/usr/bin/env python3
"""
PTA 缠论线段检测 - v6
严格按缠论原文定义实现

原文关键定义：
1. 线段：至少3笔，连续同方向
2. 线段结束条件：
   a) 反向笔出现（分型形成）
   b) 后续笔必须"实际破坏"该分型
     - 顶分型破坏：后续笔的低点 < 分型中间笔的低点
     - 底分型破坏：后续笔的高点 > 分型中间笔的高点
3. 破坏成功 → 线段结束；破坏失败 → 线段延续
4. 线段笔数一定为奇数
"""

import pandas as pd
from typing import List, Optional, Tuple

DATA = '/home/admin/.openclaw/workspace/codeman/pta_analysis/data'


def load_bars(date='2026-04-03'):
    from czsc.py.analyze import CZSC
    from czsc.py.objects import RawBar
    from czsc.py.enum import Freq

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


def find_feat(start, end, seg_dir, bi_bars):
    """找seg_start到scan_end范围内的反向笔（特征序列）"""
    feat = []
    for j in range(start, end + 1):
        bi = bi_bars[j]
        if bi['dir'] != seg_dir:  # 反向笔
            feat.append({'bi_idx': bi['idx'], 'high': bi['high'], 'low': bi['low']})
    return feat


def find_top(feat):
    """找顶分型（高高低低），返回feat中的位置"""
    for k in range(1, len(feat) - 1):
        l, m, r = feat[k-1], feat[k], feat[k+1]
        if m['high'] > l['high'] and m['high'] > r['high'] and \
           m['low'] > l['low'] and m['low'] > r['low']:
            return k
    return -1


def find_bottom(feat):
    """找底分型（低低高高）"""
    for k in range(1, len(feat) - 1):
        l, m, r = feat[k-1], feat[k], feat[k+1]
        if m['high'] < l['high'] and m['high'] < r['high'] and \
           m['low'] < l['low'] and m['low'] < r['low']:
            return k
    return -1


def detect_xd_v6(bi_bars, debug=False):
    """
    严格按缠论原文的线段检测算法
    """
    n = len(bi_bars)
    results = []
    seg_dir = 'up'  # 初始方向
    seg_start = 0
    i = 0

    while i < n:
        cur_bi = bi_bars[i]

        # 方向未变，继续扫描
        if cur_bi['dir'] == seg_dir:
            i += 1
            continue

        # 方向反转！
        seg_len = i - seg_start  # 当前段包含的笔数（到i-1为止）

        # 缠论原文核心规则：若连续3笔同向，段在第3笔结束
        if seg_len == 3:
            same_dir = all(bi_bars[j]['dir'] == seg_dir for j in range(seg_start, i))
            if same_dir:
                seg_end_bi = i - 1
                eb = bi_bars[seg_end_bi]
                # 段终点价格 = 段的峰值（UP取段内最高，DOWN取段内最低）
                # 找段内最高/最低
                seg_max = max(bi_bars[j]['high'] for j in range(seg_start, seg_end_bi + 1))
                seg_min = min(bi_bars[j]['low'] for j in range(seg_start, seg_end_bi + 1))
                end_price = seg_max if seg_dir == 'up' else seg_min
                results.append((seg_start, seg_end_bi, seg_dir, end_price))
                if debug:
                    print(f"  XD{len(results)}: b{seg_start+1}~b{seg_end_bi+1} ({seg_dir}) [3笔同向]")
                seg_dir = 'down' if seg_dir == 'up' else 'up'
                seg_start = seg_end_bi  # 下一段从i-1开始（i-1是反向bi的起点）
                i = seg_end_bi  # 下一段从i-1开始，i不变
                continue

        # 方向反转 → 可能形成分型
        # 收集从seg_start到i的所有反向笔
        feat = find_feat(seg_start, i, seg_dir, bi_bars)

        if len(feat) >= 3:
            if seg_dir == 'up':
                top_pos = find_top(feat)
                if top_pos >= 0:
                    # 顶分型形成
                    pattern = feat[top_pos]
                    # 破坏检查：后续笔必须创新低（实际破坏顶分型）
                    if top_pos + 1 < len(feat):
                        breaker = feat[top_pos + 1]
                        # UP线段被破坏 = 新笔内部低点 < 顶分型中间笔的低点
                        if breaker['low'] < pattern['low']:
                            # 破坏成功 → 线段结束
                            seg_end_bi = pattern['bi_idx']
                            # 段终点 = 段内最高/最低
                            seg_max = max(bi_bars[j]['high'] for j in range(seg_start, seg_end_bi + 1))
                            seg_min = min(bi_bars[j]['low'] for j in range(seg_start, seg_end_bi + 1))
                            end_price = seg_max  # UP段取最高
                            results.append((seg_start, seg_end_bi, seg_dir, end_price))
                            if debug:
                                print(f"  XD{len(results)}: b{seg_start+1}~b{seg_end_bi+1} ({seg_dir}) feat={[f['bi_idx']+1 for f in feat[:3]]}破坏成功")
                            seg_dir = 'down'
                            seg_start = seg_end_bi
                            i = seg_end_bi + 1
                            continue
                        else:
                            # 破坏失败 → 线段延续，丢弃feat[0]
                            feat = feat[1:]
                            # 继续扫描（i不增加）
                            while len(feat) >= 3:
                                top_pos2 = find_top(feat)
                                if top_pos2 >= 0:
                                    pattern2 = feat[top_pos2]
                                    if top_pos2 + 1 < len(feat) and feat[top_pos2 + 1]['low'] < pattern2['low']:
                                        seg_end_bi2 = pattern2['bi_idx']
                                        end_price2 = pattern2['high']
                                        results.append((seg_start, seg_end_bi2, seg_dir, end_price2))
                                        if debug:
                                            print(f"  XD{len(results)}: b{seg_start+1}~b{seg_end_bi2+1} ({seg_dir}) feat_dropped")
                                        seg_dir = 'down'
                                        seg_start = seg_end_bi2
                                        i = seg_end_bi2 + 1
                                        break
                                    feat = feat[1:]
                                else:
                                    break
                            i += 1
                            continue
                    else:
                        # 没有破坏笔，分型不成立
                        feat = feat[1:]
                        i += 1
                        continue
            else:  # seg_dir == 'down'
                bottom_pos = find_bottom(feat)
                if bottom_pos >= 0:
                    pattern = feat[bottom_pos]
                    if bottom_pos + 1 < len(feat):
                        breaker = feat[bottom_pos + 1]
                        # DOWN线段被破坏 = 新笔内部高点 > 底分型中间笔的高点
                        if breaker['high'] > pattern['high']:
                            seg_end_bi = pattern['bi_idx']
                            end_price = pattern['low']
                            results.append((seg_start, seg_end_bi, seg_dir, end_price))
                            if debug:
                                print(f"  XD{len(results)}: b{seg_start+1}~b{seg_end_bi+1} ({seg_dir})")
                            seg_dir = 'up'
                            seg_start = seg_end_bi
                            i = seg_end_bi + 1
                            continue
                        else:
                            feat = feat[1:]
                            while len(feat) >= 3:
                                bottom_pos2 = find_bottom(feat)
                                if bottom_pos2 >= 0:
                                    pattern2 = feat[bottom_pos2]
                                    if bottom_pos2 + 1 < len(feat) and feat[bottom_pos2 + 1]['high'] > pattern2['high']:
                                        seg_end_bi2 = pattern2['bi_idx']
                                        end_price2 = pattern2['low']
                                        results.append((seg_start, seg_end_bi2, seg_dir, end_price2))
                                        seg_dir = 'up'
                                        seg_start = seg_end_bi2
                                        i = seg_end_bi2 + 1
                                        break
                                    feat = feat[1:]
                                else:
                                    break
                            i += 1
                            continue
                        i += 1
                        continue
        i += 1

    # 最后一段
    if seg_start < n - 1:
        seg_end_bi = n - 1
        results.append((seg_start, seg_end_bi, seg_dir, bi_bars[seg_end_bi]['end_val']))

    return results


def main():
    bars = load_bars('2026-04-03')
    from czsc.py.analyze import CZSC
    c = CZSC(bars)

    bi_bars = []
    for i, bi in enumerate(c.bi_list):
        d = 'up' if str(bi.direction) == '向上' else 'down'
        bi_bars.append({
            'idx': i,
            'dir': d,
            'start_val': bi.raw_bars[0].low if d == 'up' else bi.raw_bars[0].high,
            'end_val': bi.raw_bars[-1].high if d == 'up' else bi.raw_bars[-1].low,
            'high': bi.high,
            'low': bi.low,
        })

    print(f"笔数量: {len(bi_bars)}")
    for b in bi_bars:
        print(f"  b{b['idx']+1:2d} {b['dir']:4s} end={b['end_val']:.0f}")

    print("\n=== 线段检测(v6) ===")
    xd = detect_xd_v6(bi_bars, debug=True)
    print(f"\n检测到{len(xd)}条线段:")
    for idx, (s, e, d, p) in enumerate(xd):
        bi_count = e - s + 1
        sb = bi_bars[s]
        print(f"  XD{idx+1} {d:4s} b{s+1}~b{e+1} [{sb['start_val']:.0f}->{p:.0f}] ({bi_count}笔)")

    print("\n期望结果:")
    print("  XD1 up  b1~b3  [6726 -> 6922] (3笔)")
    print("  XD2 down b4~b6  [6922 -> 6810] (3笔)")
    print("  XD3 up  b7~b16 [6810 -> 6948] (10笔)")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""PTA缠论线段检测 v8 - 正确实现"""
import pandas as pd
from datetime import datetime

def parse_bi(date_str):
    """从CSV读取K线，用ZigZag检测笔"""
    df = pd.read_csv('/tmp/pta_1min.csv')
    df['datetime'] = pd.to_datetime(df['datetime'])
    day_df = df[df['datetime'].dt.date == pd.Timestamp(date_str).date()].sort_values('datetime')
    day_df = day_df[day_df['close'].notna() & (day_df['close'] > 0)].reset_index(drop=True)
    bars = list(day_df.itertuples())

    # 简单ZigZag：找极值点
    # 笔定义：一端是极点，另一端是后续不再创新高/新低的点
    bi_list = []
    i = 0
    while i < len(bars) - 1:
        high = float(bars[i].high)
        low = float(bars[i].low)
        
        # 找下一个极值
        j = i + 1
        if high >= float(bars[j].high):
            # 向下找极点
            while j < len(bars) - 1 and float(bars[j].high) <= float(bars[j-1].high):
                j += 1
            # 此时bars[j-1]是局部最低
            end_j = j - 1
            end_price = float(bars[end_j].low)
            seg_high = max(float(bars[k].high) for k in range(i, end_j+1))
            seg_low = float(bars[end_j].low)
            bi_list.append({'idx': i, 'dir': 'up', 'start': i, 'end': end_j,
                           'start_price': float(bars[i].low), 'end_price': end_price,
                           'high': seg_high, 'low': seg_low})
            i = end_j
        else:
            # 向上找极点
            while j < len(bars) - 1 and float(bars[j].high) >= float(bars[j-1].high):
                j += 1
            end_j = j - 1
            end_price = float(bars[end_j].high)
            seg_high = float(bars[end_j].high)
            seg_low = min(float(bars[k].low) for k in range(i, end_j+1))
            bi_list.append({'idx': i, 'dir': 'down', 'start': i, 'end': end_j,
                           'start_price': float(bars[i].high), 'end_price': end_price,
                           'high': seg_high, 'low': seg_low})
            i = end_j

    # 过滤小于5根K线的笔
    valid = [b for b in bi_list if b['end'] - b['start'] + 1 >= 5]
    return valid, bars

def detect_xd(bi_list, debug=False):
    """线段检测：三元素分型法"""
    if len(bi_list) < 3:
        return []

    results = []
    seg_start = 0
    seg_dir = bi_list[0]['dir']  # 第一笔决定第一段方向

    max_iter = len(bi_list) * 2
    it = 0

    while seg_start < len(bi_list) - 1 and it < max_iter:
        it += 1

        # 收集特征序列（反向笔）
        feat_dir = 'down' if seg_dir == 'up' else 'up'
        feat = [b for b in bi_list[seg_start:] if b['dir'] == feat_dir]

        if len(feat) < 3:
            # 特征序列不足3条，等待
            if debug:
                print(f"  b{seg_start+1}~: 特征{len(feat)}条<3，等待更多笔")
            break

        # 找分型（顶分型或底分型）
        pattern_pos = -1
        for k in range(1, len(feat) - 1):
            e1, e2, e3 = feat[k-1], feat[k], feat[k+1]
            if seg_dir == 'up':
                # UP段：找顶分型 = e2.high > e1.high and e2.high > e3.high
                if e2['high'] > e1['high'] and e2['high'] > e3['high']:
                    pattern_pos = k
                    break
            else:
                # DOWN段：找底分型 = e2.low < e1.low and e2.low < e3.low
                if e2['low'] < e1['low'] and e2['low'] < e3['low']:
                    pattern_pos = k
                    break

        if pattern_pos < 0:
            if debug:
                print(f"  b{seg_start+1}~: 特征{len(feat)}条无分型，等待...")
            break

        e1, e2, e3 = feat[pattern_pos-1], feat[pattern_pos], feat[pattern_pos+1]

        if debug:
            print(f"  b{seg_start+1}~: feat[{len(feat)}] pos={pattern_pos} e1=b{e1['idx']+1}(h={e1['high']:.0f}) e2=b{e2['idx']+1}(h={e2['high']:.0f}) e3=b{e3['idx']+1}(h={e3['high']:.0f})")

        # 破坏检查
        if seg_dir == 'up':
            # UP段被破坏：e3的终点创新低（跌破e2低点）
            broken = e3['end_price'] < e2['end_price']
            if debug:
                print(f"    UP破坏: e3.end({e3['end_price']:.0f}) < e2.end({e2['end_price']:.0f}) = {broken}")
        else:
            # DOWN段被破坏：e3的终点创新高（突破e2高点）
            broken = e3['end_price'] > e2['end_price']
            if debug:
                print(f"    DOWN破坏: e3.end({e3['end_price']:.0f}) > e2.end({e2['end_price']:.0f}) = {broken}")

        if broken:
            # 破坏成功 → 线段结束于e2的idx
            seg_end = e2['idx']
            seg_count = seg_end - seg_start + 1
            is_sure = seg_count >= 3

            # 计算段内peak/trough
            seg_bars = bi_list[seg_start:seg_end+1]
            if seg_dir == 'up':
                peak_trough = min(b['low'] for b in seg_bars)
            else:
                peak_trough = max(b['high'] for b in seg_bars)

            results.append((len(results), seg_start, seg_end, seg_dir, is_sure, peak_trough))
            if debug:
                print(f"    → XD{len(results)} {seg_dir} b{seg_start+1}~b{seg_end+1} {'✅' if is_sure else '❌'}(e2={e2['end_price']:.0f})")

            seg_dir = 'down' if seg_dir == 'up' else 'up'
            seg_start = seg_end + 1
            if debug:
                print(f"    → 新段: {seg_dir} 从b{seg_start+1}开始")
        else:
            # 破坏失败：移除e1，从e2位置继续（chan.py的reset逻辑）
            if pattern_pos >= 1:
                new_start = feat[pattern_pos]['idx']
                if new_start > seg_start:
                    seg_start = new_start
                    if debug:
                        print(f"    破坏失败，跳到b{seg_start+1}继续")
            else:
                break

    # 最后一段
    if seg_start < len(bi_list):
        seg_count = len(bi_list) - seg_start
        is_sure = seg_count >= 3
        seg_bars = bi_list[seg_start:]
        if seg_dir == 'up':
            peak_trough = min(b['low'] for b in seg_bars)
        else:
            peak_trough = max(b['high'] for b in seg_bars)
        results.append((len(results), seg_start, len(bi_list)-1, seg_dir, is_sure, peak_trough))

    return results

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('date', nargs='?', default='2026-04-03')
    parser.add_argument('--debug', '-d', action='store_true')
    args = parser.parse_args()

    print(f"\n{'='*50}")
    print(f"PTA缠论线段检测 v8 | {args.date}")
    print(f"{'='*50}\n")

    bi_list, bars = parse_bi(args.date)
    if not bi_list:
        print("无法读取数据"); exit(1)

    print(f"[K线] {len(bars)}根 | [笔] {len(bi_list)}条")
    for i, b in enumerate(bi_list):
        print(f"  b{i+1} {b['dir']:4s} [{b['start']+1}~{b['end']+1}] start={b['start_price']:.0f} end={b['end_price']:.0f} high={b['high']:.0f} low={b['low']:.0f}")

    print()
    xd = detect_xd(bi_list, debug=args.debug)

    print(f"\n[线段] {len(xd)}条")
    for seg_idx, start, end, seg_dir, is_sure, pt in xd:
        sure_str = "✅" if is_sure else "❌"
        if seg_dir == 'up':
            print(f"  XD{seg_idx+1} {seg_dir} b{start+1}~b{end+1} [{sure_str}] trough={pt:.0f}")
        else:
            print(f"  XD{seg_idx+1} {seg_dir} b{start+1}~b{end+1} [{sure_str}] peak={pt:.0f}")
    confirmed = sum(1 for r in xd if r[4])
    print(f"\n确认线段: {confirmed}条 | 虚段: {len(xd)-confirmed}条")

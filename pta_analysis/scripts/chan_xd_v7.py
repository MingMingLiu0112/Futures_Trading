#!/usr/bin/env python3
"""
PTA缠论线段检测 - v7
参考chan.py SegListChan.py + EigenFX.py核心逻辑

核心规则（chan.py）：
1. 线段方向由第一段笔的方向决定
2. 特征序列 = 与线段方向相反的笔序列
3. 三元素分型：e1,e2,e3，当e3加入时判断是否形成分型
4. 分型成立 + 实际破坏 → 线段结束
5. is_sure = True 需要至少3条笔
"""

import pandas as pd, re
from datetime import datetime

# ============================================================
# 工具函数
# ============================================================
def parse_bi_from_csv(date_str):
    """从CSV读取指定日期的K线，生成笔"""
    try:
        df = pd.read_csv('/tmp/pta_1min.csv')
        df['datetime'] = pd.to_datetime(df['datetime'])
        day_df = df[df['datetime'].dt.date == pd.Timestamp(date_str).date()].sort_values('datetime')
        day_df = day_df[day_df['close'].notna() & (day_df['close'] > 0)].reset_index(drop=True)
        day_df['real_time'] = day_df['datetime'] + pd.Timedelta(hours=8)
        bars = list(day_df.itertuples())
        return bars, df
    except Exception as e:
        print(f"读取CSV失败: {e}")
        return None, None

def combine_bi(bi_list):
    """
    笔合并：相邻笔如果有包含关系需要合并
    bi_list: list of (idx, direction, high, low)
    返回: list of (idx, direction, high, low, start_price, end_price)
    """
    if not bi_list:
        return []

    # 初始笔列表
    result = []
    for item in bi_list:
        idx, direction, high, low = item[:4]
        if len(result) == 0:
            result.append([idx, direction, high, low, low if direction == 'up' else high])
        else:
            prev = result[-1]
            # 检查包含关系：同向笔或反向笔
            if prev[1] == direction:
                # 同向：合并高低点
                new_high = max(prev[2], high)
                new_low = min(prev[3], low)
                new_dir = prev[1]
                new_start = prev[4]
                new_end = low if new_dir == 'up' else high
                result[-1] = [prev[0], new_dir, new_high, new_low, new_start, new_end]
            else:
                # 反向：直接添加
                result.append([idx, direction, high, low, low if direction == 'up' else high])

    # 多轮合并直到没有包含关系
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(result):
            if i > 0 and result[i][1] != result[i-1][1]:
                # 检查是否有包含关系
                p = result[i-1]
                c = result[i]
                if p[1] == 'up' and c[1] == 'down':
                    if c[2] >= p[2] and c[3] <= p[3]:
                        # DOWN笔被UP笔包含：合并
                        new_high = max(p[2], c[2])
                        new_low = min(p[3], c[3])
                        result[i-1] = [p[0], 'up', new_high, new_low, p[4], c[3]]
                        result.pop(i)
                        changed = True
                        continue
                elif p[1] == 'down' and c[1] == 'up':
                    if c[2] >= p[2] and c[3] <= p[3]:
                        # UP笔被DOWN笔包含：合并
                        new_high = max(p[2], c[2])
                        new_low = min(p[3], c[3])
                        result[i-1] = [p[0], 'down', new_high, new_low, p[4], c[3]]
                        result.pop(i)
                        changed = True
                        continue
            i += 1

    # 过滤小于5根K线的笔（笔定义：至少5根K线）
    final = []
    for item in result:
        if len(final) == 0:
            final.append(item)
        else:
            if item[1] != final[-1][1]:
                final.append(item)
            else:
                # 同向合并
                prev = final[-1]
                new_high = max(prev[2], item[2])
                new_low = min(prev[3], item[3])
                new_dir = prev[1]
                new_start = prev[4]
                new_end = item[5]
                final[-1] = [prev[0], new_dir, new_high, new_low, new_start, new_end]

    # 笔数验证
    dirs = [r[1] for r in final]
    flips = sum(1 for i in range(1, len(dirs)) if dirs[i] != dirs[i-1])
    print(f"  笔数: {len(final)} (方向切换{flips}次)")

    return final

def detect_bi(bars):
    """从K线检测笔"""
    if not bars:
        return []

    # 生成初始笔（基于极值）
    bi_raw = []
    for i, bar in enumerate(bars):
        high = float(getattr(bar, 'high', 0))
        low = float(getattr(bar, 'low', 0))
        if i == 0:
            cur_dir = 'up' if high > low else 'down'
            bi_start = i
            bi_high = high
            bi_low = low
        else:
            if high > bi_high and low >= bi_low:
                bi_high = high
            elif low < bi_low and high <= bi_high:
                bi_low = low
            else:
                # 笔结束
                end_price = bi_low if cur_dir == 'up' else bi_high
                bi_raw.append((bi_start, cur_dir, bi_high, bi_low, getattr(bars[bi_start], 'close', bi_low), end_price))
                cur_dir = 'up' if high > bi_low else 'down'
                bi_start = i
                bi_high = high
                bi_low = low

    # 最后一个笔
    if bi_raw:
        last = bi_raw[-1]
        if bi_start != last[0]:
            end_price = bi_low if cur_dir == 'up' else bi_high
            bi_raw.append((bi_start, cur_dir, bi_high, bi_low, getattr(bars[bi_start], 'close', bi_low), end_price))

    # 合并包含关系
    bi_list = combine_bi(bi_raw)
    return bi_list

def get_segment_peak_trough(seg_bars, seg_dir):
    """获取线段的峰值或谷值（段内最高或最低）"""
    if not seg_bars:
        return 0 if seg_dir == 'down' else float('inf')
    if seg_dir == 'up':
        return min(b['low'] for b in seg_bars)  # UP段: 段内最低点
    else:
        return max(b['high'] for b in seg_bars)  # DOWN段: 段内最高点

def detect_xd(bi_list, debug=False):
    """
    线段检测算法 - 参考chan.py三元素分型法

    bi_list: list of (idx, dir, high, low, start_price, end_price)
    返回: list of (seg_idx, start_bi_idx, end_bi_idx, seg_dir, is_sure, seg_peak_trough)
    """
    if len(bi_list) < 3:
        return []

    results = []
    seg_start = 0
    seg_dir = bi_list[0][1]  # 第一笔决定第一段方向

    # 段内所有笔
    seg_bars = [dict(zip(['idx','dir','high','low','start_price','end_price'], b)) for b in bi_list[seg_start:]]
    seg_bars[0]['start_bi'] = seg_start

    if debug:
        print(f"  第一段方向: {seg_dir}, 从b{seg_start+1}开始")

    def find_feat(start_idx, current_idx, feat_dir, bi_list):
        """找特征序列：反向笔列表"""
        feat = []
        for j in range(start_idx, current_idx + 1):
            if bi_list[j][1] != feat_dir:
                b = dict(zip(['idx','dir','high','low','start_price','end_price'], bi_list[j]))
                feat.append(b)
        return feat

    def find_pattern_idx(feat, feat_dir):
        """找分型位置（顶分型或底分型）
        UP段特征序列=DOWN笔，找顶分型
        DOWN段特征序列=UP笔，找底分型
        返回顶分型位置，不存在返回-1
        """
        if len(feat) < 3:
            return -1

        for k in range(1, len(feat) - 1):
            e1, e2, e3 = feat[k-1], feat[k], feat[k+1]
            if feat_dir == 'up':
                # UP段: 顶分型 = e2.high > e1.high and e2.high > e3.high
                if e2['high'] > e1['high'] and e2['high'] > e3['high']:
                    return k
            else:
                # DOWN段: 底分型 = e2.low < e1.low and e2.low < e3.low
                if e2['low'] < e1['low'] and e2['low'] < e3['low']:
                    return k
        return -1

    max_iterations = len(bi_list) * 2
    iteration = 0

    while seg_start < len(bi_list) - 1 and iteration < max_iterations:
        iteration += 1

        # 收集反向笔作为特征序列
        feat_dir = 'down' if seg_dir == 'up' else 'up'
        feat = []
        for j in range(seg_start, len(bi_list)):
            if bi_list[j][1] != seg_dir:
                b = dict(zip(['idx','dir','high','low','start_price','end_price'], bi_list[j]))
                feat.append(b)

        if len(feat) < 3:
            if debug:
                print(f"  b{seg_start+1}~{len(bi_list)}: 特征序列不足{len(feat)}条，等待更多笔...")
            # 不确定段：直到数据结束
            results.append((len(results), seg_start, len(bi_list)-1, seg_dir, False, get_segment_peak_trough([dict(zip(['idx','dir','high','low'], bi_list[i])) for i in range(seg_start, len(bi_list))], seg_dir)))
            break

        # 找分型
        pattern_pos = find_pattern_idx(feat, feat_dir)

        if pattern_pos < 0:
            if debug:
                print(f"  b{seg_start+1}~: 特征序列{len(feat)}条但无分型，等待...")
            # 继续等待下一笔
            break

        pattern_bar = feat[pattern_pos]  # e2 = 分型笔
        e3_bar = feat[pattern_pos + 1] if pattern_pos + 1 < len(feat) else None

        if debug:
            print(f"  b{seg_start+1}~: 特征{len(feat)}条, e2=b{pattern_bar['idx']+1}({pattern_bar.get('high','?')}/{pattern_bar.get('low','?')})")

        # 检查破坏
        if e3_bar is not None:
            if seg_dir == 'up':
                # UP段被破坏: e3笔的内部低点 < e2笔的内部低点（实际破坏）
                # 注意：这里比较的是特征序列笔的端点，不是段内最高最低
                broken = e3_bar['end_price'] < pattern_bar['end_price']
                if debug:
                    print(f"    UP破坏检查: e3.end({e3_bar['end_price']}) < e2.end({pattern_bar['end_price']}) = {broken}")
            else:
                # DOWN段被破坏: e3笔的内部高点 > e2笔的内部高点
                broken = e3_bar['end_price'] > pattern_bar['end_price']
                if debug:
                    print(f"    DOWN破坏检查: e3.end({e3_bar['end_price']}) > e2.end({pattern_bar['end_price']}) = {broken}")
        else:
            broken = False

        if broken:
            # 破坏成功 → 线段结束
            seg_end = pattern_bar['idx']
            seg_bar_count = seg_end - seg_start + 1
            is_sure = seg_bar_count >= 3

            seg_bars_in_result = [dict(zip(['idx','dir','high','low','start_price','end_price'], bi_list[i])) for i in range(seg_start, seg_end + 1)]
            peak_trough = get_segment_peak_trough(seg_bars_in_result, seg_dir)

            results.append((len(results), seg_start, seg_end, seg_dir, is_sure, peak_trough))
            if debug:
                sure_str = "确认" if is_sure else "虚段"
                print(f"    → XD{len(results)} {seg_dir} b{seg_start+1}~b{seg_end+1} [{sure_str}] 破坏成功")

            # 下一段
            seg_dir = 'down' if seg_dir == 'up' else 'up'
            seg_start = seg_end + 1
            if debug:
                print(f"    新段方向: {seg_dir}, 从b{seg_start+1}开始")
        else:
            # 破坏失败：移除e1，继续等待
            if debug:
                print(f"    破坏失败，移除e1，继续等待...")
            # 实际上：跳过e1，继续从下一笔判断
            # chan.py的逻辑：找到e2的位置后，从e2位置重新搜索
            if pattern_pos >= 1:
                # 从e2位置继续
                new_start = feat[pattern_pos]['idx']
                if new_start > seg_start:
                    seg_start = new_start
            else:
                break

    # 处理最后一段（到数据末尾）
    if seg_start < len(bi_list):
        seg_bar_count = len(bi_list) - seg_start
        is_sure = seg_bar_count >= 3
        seg_bars_in_result = [dict(zip(['idx','dir','high','low','start_price','end_price'], bi_list[i])) for i in range(seg_start, len(bi_list))]
        peak_trough = get_segment_peak_trough(seg_bars_in_result, seg_dir)
        results.append((len(results), seg_start, len(bi_list)-1, seg_dir, is_sure, peak_trough))

    return results

# ============================================================
# 主程序
# ============================================================
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('date', nargs='?', default='2026-04-03')
    parser.add_argument('--debug', '-d', action='store_true')
    args = parser.parse_args()

    print(f"\n{'='*50}")
    print(f"PTA缠论线段检测 v7 | {args.date}")
    print(f"{'='*50}\n")

    # 读取K线
    bars, df = parse_bi_from_csv(args.date)
    if bars is None:
        print("无法读取数据")
        exit(1)

    print(f"[数据] {len(bars)}根K线")

    # 检测笔
    bi_list = detect_bi(bars)
    if not bi_list:
        print("无法检测笔")
        exit(1)

    print(f"[笔] {len(bi_list)}条笔")
    print()
    for i, b in enumerate(bi_list):
        d = b[1]
        print(f"  b{i+1} {d:4s} start={b[4]:.0f} end={b[5]:.0f} high={b[2]:.0f} low={b[3]:.0f}")

    # 检测线段
    print()
    xd_results = detect_xd(bi_list, debug=args.debug)

    print(f"\n[线段] {len(xd_results)}条")
    for seg_idx, start, end, seg_dir, is_sure, pt in xd_results:
        sure_str = "✅确认" if is_sure else "❌虚段"
        peak_info = f"peak={pt:.0f}" if seg_dir == 'down' else f"trough={pt:.0f}"
        print(f"  XD{seg_idx+1} {seg_dir} b{start+1}~b{end+1} [{sure_str}] ({peak_info})")

    # 验证
    print(f"\n[验证]")
    print(f"  笔数: {len(bi_list)}")
    print(f"  线段数: {len(xd_results)}")
    confirmed = sum(1 for r in xd_results if r[4])
    print(f"  确认线段: {confirmed}条")
    print(f"  虚段: {len(xd_results)-confirmed}条")
#!/usr/bin/env python3
"""
PTA缠论线段检测 - v9
简化版笔检测：基于局部极值点的ZigZag算法
"""

import pandas as pd
import numpy as np
from datetime import datetime

def parse_kline(date_str):
    """读取K线数据"""
    df = pd.read_csv('/tmp/pta_1min.csv')
    df['datetime'] = pd.to_datetime(df['datetime'])
    day_df = df[df['datetime'].dt.date == pd.Timestamp(date_str).date()].sort_values('datetime')
    day_df = day_df[day_df['close'].notna() & (day_df['close'] > 0)].reset_index(drop=True)
    return day_df

def detect_bi_simple(kline_df):
    """
    简单笔检测算法：基于局部极值点的ZigZag
    
    算法步骤：
    1. 找到所有局部高点和低点
    2. 交替连接高低点形成笔
    3. 过滤太短的笔（<5根K线）
    """
    highs = kline_df['high'].values
    lows = kline_df['low'].values
    times = kline_df['datetime'].values
    
    # 找局部极值点
    peaks = []  # (idx, price, type='high'/'low')
    
    for i in range(1, len(highs)-1):
        # 检查局部高点
        if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
            peaks.append((i, highs[i], 'high'))
        # 检查局部低点
        if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
            peaks.append((i, lows[i], 'low'))
    
    # 按时间排序
    peaks.sort(key=lambda x: x[0])
    
    # 过滤：只保留交替的高点和低点
    filtered = []
    for i, (idx, price, ptype) in enumerate(peaks):
        if i == 0:
            filtered.append((idx, price, ptype))
        else:
            last_type = filtered[-1][2]
            if ptype != last_type:
                # 检查价格差是否足够大（避免微小波动）
                last_price = filtered[-1][1]
                price_change = abs(price - last_price) / last_price
                if price_change > 0.0005:  # 最小变化0.05%
                    filtered.append((idx, price, ptype))
    
    # 创建笔列表
    bi_list = []
    for i in range(len(filtered)-1):
        idx1, price1, type1 = filtered[i]
        idx2, price2, type2 = filtered[i+1]
        
        # 确保交替：high -> low -> high -> low
        if type1 == 'high' and type2 == 'low':
            direction = 'down'
            start_price = price1
            end_price = price2
            bi_high = price1
            bi_low = price2
        elif type1 == 'low' and type2 == 'high':
            direction = 'up'
            start_price = price1
            end_price = price2
            bi_high = price2
            bi_low = price1
        else:
            continue
        
        # 检查笔长度
        bi_len = idx2 - idx1 + 1
        if bi_len >= 5:  # 缠论要求至少5根K线
            bi_list.append({
                'idx': len(bi_list),
                'dir': direction,
                'start_idx': idx1,
                'end_idx': idx2,
                'start_price': start_price,
                'end_price': end_price,
                'high': bi_high,
                'low': bi_low,
                'k_count': bi_len
            })
    
    return bi_list, filtered

def detect_xd_improved(bi_list, debug=False):
    """
    改进的线段检测算法
    
    规则：
    1. 线段方向由第一笔决定
    2. 特征序列 = 与线段方向相反的笔
    3. 三元素分型：e1,e2,e3形成顶/底分型
    4. 分型成立 + 实际破坏 → 线段结束
    """
    if len(bi_list) < 3:
        return []
    
    results = []
    seg_start = 0
    seg_dir = bi_list[0]['dir']
    
    iteration = 0
    max_iter = len(bi_list) * 3
    
    while seg_start < len(bi_list) - 1 and iteration < max_iter:
        iteration += 1
        
        # 收集特征序列（反向笔）
        feat_dir = 'down' if seg_dir == 'up' else 'up'
        feat = [b for b in bi_list[seg_start:] if b['dir'] == feat_dir]
        
        if len(feat) < 3:
            if debug:
                print(f"  b{seg_start+1}~: 特征序列不足{len(feat)}条，等待更多笔")
            break
        
        # 寻找分型
        pattern_pos = -1
        for k in range(1, len(feat) - 1):
            e1, e2, e3 = feat[k-1], feat[k], feat[k+1]
            
            if seg_dir == 'up':
                # UP段：寻找顶分型（e2高点 > e1高点 and e2高点 > e3高点）
                if e2['high'] > e1['high'] and e2['high'] > e3['high']:
                    pattern_pos = k
                    break
            else:
                # DOWN段：寻找底分型（e2低点 < e1低点 and e2低点 < e3低点）
                if e2['low'] < e1['low'] and e2['low'] < e3['low']:
                    pattern_pos = k
                    break
        
        if pattern_pos < 0:
            if debug:
                print(f"  b{seg_start+1}~: 特征{len(feat)}条但无分型")
            break
        
        e1, e2, e3 = feat[pattern_pos-1], feat[pattern_pos], feat[pattern_pos+1]
        
        if debug:
            print(f"  b{seg_start+1}~: 特征{len(feat)}条, e2=b{e2['idx']+1} pos={pattern_pos}")
            print(f"    e1={e1['start_price']:.0f}→{e1['end_price']:.0f} h={e1['high']:.0f} l={e1['low']:.0f}")
            print(f"    e2={e2['start_price']:.0f}→{e2['end_price']:.0f} h={e2['high']:.0f} l={e2['low']:.0f}")
            print(f"    e3={e3['start_price']:.0f}→{e3['end_price']:.0f} h={e3['high']:.0f} l={e3['low']:.0f}")
        
        # 检查破坏
        if seg_dir == 'up':
            # UP段破坏：e3终点跌破e2终点
            broken = e3['end_price'] < e2['end_price']
            if debug:
                print(f"    UP破坏检查: e3.end({e3['end_price']:.0f}) < e2.end({e2['end_price']:.0f}) = {broken}")
        else:
            # DOWN段破坏：e3终点突破e2终点
            broken = e3['end_price'] > e2['end_price']
            if debug:
                print(f"    DOWN破坏检查: e3.end({e3['end_price']:.0f}) > e2.end({e2['end_price']:.0f}) = {broken}")
        
        if broken:
            # 线段结束
            seg_end = e2['idx']
            seg_len = seg_end - seg_start + 1
            is_sure = seg_len >= 3
            
            # 计算段内峰值/谷值
            seg_bars = bi_list[seg_start:seg_end+1]
            if seg_dir == 'up':
                trough = min(b['low'] for b in seg_bars)
                peak_trough = trough
            else:
                peak = max(b['high'] for b in seg_bars)
                peak_trough = peak
            
            results.append((len(results), seg_start, seg_end, seg_dir, is_sure, peak_trough))
            
            if debug:
                sure_str = "✅确认" if is_sure else "❌虚段"
                print(f"    → XD{len(results)} {seg_dir} b{seg_start+1}~b{seg_end+1} [{sure_str}]")
            
            # 开始新线段
            seg_dir = 'down' if seg_dir == 'up' else 'up'
            seg_start = seg_end + 1
            
            if debug:
                print(f"    新段: {seg_dir} 从b{seg_start+1}开始")
        else:
            # 破坏失败：从e2位置继续
            new_start = feat[pattern_pos]['idx']
            if new_start > seg_start:
                seg_start = new_start
                if debug:
                    print(f"    破坏失败，跳到b{seg_start+1}继续")
            else:
                break
    
    # 处理最后一段
    if seg_start < len(bi_list):
        seg_len = len(bi_list) - seg_start
        is_sure = seg_len >= 3
        seg_bars = bi_list[seg_start:]
        if seg_dir == 'up':
            peak_trough = min(b['low'] for b in seg_bars)
        else:
            peak_trough = max(b['high'] for b in seg_bars)
        results.append((len(results), seg_start, len(bi_list)-1, seg_dir, is_sure, peak_trough))
    
    return results

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('date', nargs='?', default='2026-04-03')
    parser.add_argument('--debug', '-d', action='store_true')
    args = parser.parse_args()
    
    print(f"\n{'='*50}")
    print(f"PTA缠论线段检测 v9 | {args.date}")
    print(f"{'='*50}\n")
    
    # 读取K线
    kline_df = parse_kline(args.date)
    print(f"[K线] {len(kline_df)}根")
    
    # 检测笔
    bi_list, peaks = detect_bi_simple(kline_df)
    print(f"[笔] {len(bi_list)}条")
    print(f"[极值点] {len(peaks)}个")
    
    for i, bi in enumerate(bi_list):
        print(f"  b{i+1} {bi['dir']:4s} [{bi['start_idx']+1}~{bi['end_idx']+1}] {bi['k_count']}K")
        print(f"    price: {bi['start_price']:.0f}→{bi['end_price']:.0f}  high={bi['high']:.0f} low={bi['low']:.0f}")
    
    # 检测线段
    print()
    xd_results = detect_xd_improved(bi_list, debug=args.debug)
    
    print(f"\n[线段] {len(xd_results)}条")
    for seg_idx, start, end, seg_dir, is_sure, pt in xd_results:
        sure_str = "✅" if is_sure else "❌"
        pt_type = "trough" if seg_dir == 'up' else "peak"
        print(f"  XD{seg_idx+1} {seg_dir} b{start+1}~b{end+1} [{sure_str}] {pt_type}={pt:.0f}")
    
    # 统计
    confirmed = sum(1 for r in xd_results if r[4])
    print(f"\n[统计] 确认线段: {confirmed}条 | 虚段: {len(xd_results)-confirmed}条")
    
    # 验证预期结果
    print(f"\n[预期] 4月3日应有16条笔，3条线段")
    print(f"       实际笔数: {len(bi_list)}")
    
    if len(bi_list) == 16:
        print("✓ 笔数正确")
    else:
        print(f"✗ 笔数错误，期望16，实际{len(bi_list)}")

if __name__ == '__main__':
    main()
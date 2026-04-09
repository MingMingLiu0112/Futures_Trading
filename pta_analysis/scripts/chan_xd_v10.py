#!/usr/bin/env python3
"""
PTA缠论线段检测 - v10
改进笔检测：添加幅度过滤和分型确认
"""

import pandas as pd
import numpy as np

def parse_kline(date_str):
    """读取K线数据"""
    df = pd.read_csv('/tmp/pta_1min.csv')
    df['datetime'] = pd.to_datetime(df['datetime'])
    day_df = df[df['datetime'].dt.date == pd.Timestamp(date_str).date()].sort_values('datetime')
    day_df = day_df[day_df['close'].notna() & (day_df['close'] > 0)].reset_index(drop=True)
    return day_df

def find_fractal_points(kline_df):
    """
    寻找分型点（顶分型和底分型）
    顶分型：中间K线高点最高，低点也最高（或至少不是最低）
    底分型：中间K线低点最低，高点也最低（或至少不是最高）
    """
    highs = kline_df['high'].values
    lows = kline_df['low'].values
    idxs = kline_df.index.values
    
    top_points = []  # 顶分型
    bottom_points = []  # 底分型
    
    for i in range(1, len(kline_df)-1):
        # 检查顶分型
        if (highs[i] > highs[i-1] and highs[i] > highs[i+1] and
            lows[i] >= min(lows[i-1], lows[i+1])):
            top_points.append((idxs[i], highs[i], 'top'))
        
        # 检查底分型
        if (lows[i] < lows[i-1] and lows[i] < lows[i+1] and
            highs[i] <= max(highs[i-1], highs[i+1])):
            bottom_points.append((idxs[i], lows[i], 'bottom'))
    
    # 合并并排序
    all_points = top_points + bottom_points
    all_points.sort(key=lambda x: x[0])
    
    return all_points

def detect_bi_with_fractal(kline_df):
    """
    基于分型点检测笔
    规则：顶分型 -> 底分型 -> 顶分型 -> ...
    """
    fractal_points = find_fractal_points(kline_df)
    
    if len(fractal_points) < 2:
        return []
    
    bi_list = []
    i = 0
    while i < len(fractal_points) - 1:
        idx1, price1, type1 = fractal_points[i]
        idx2, price2, type2 = fractal_points[i+1]
        
        # 确保交替：顶分型 -> 底分型 或 底分型 -> 顶分型
        if type1 == 'top' and type2 == 'bottom':
            direction = 'down'
            start_price = price1
            end_price = price2
            bi_high = price1
            bi_low = price2
            
            # 计算笔内最高最低
            segment = kline_df.loc[idx1:idx2]
            bi_high = max(segment['high'].max(), bi_high)
            bi_low = min(segment['low'].min(), bi_low)
            
        elif type1 == 'bottom' and type2 == 'top':
            direction = 'up'
            start_price = price1
            end_price = price2
            bi_high = price2
            bi_low = price1
            
            segment = kline_df.loc[idx1:idx2]
            bi_high = max(segment['high'].max(), bi_high)
            bi_low = min(segment['low'].min(), bi_low)
        else:
            i += 1
            continue
        
        # 检查笔长度（至少5根K线）
        bi_len = idx2 - idx1 + 1
        if bi_len < 5:
            i += 1
            continue
        
        # 检查价格变化幅度（至少10点）
        price_change = abs(end_price - start_price)
        if price_change < 10:
            i += 1
            continue
        
        bi_list.append({
            'idx': len(bi_list),
            'dir': direction,
            'start_idx': idx1,
            'end_idx': idx2,
            'start_price': start_price,
            'end_price': end_price,
            'high': bi_high,
            'low': bi_low,
            'k_count': bi_len,
            'change': price_change
        })
        
        i += 1
    
    return bi_list

def detect_xd_simple(bi_list):
    """
    简化线段检测：基于笔的方向变化
    当出现3笔同向时，检查是否形成线段
    """
    if len(bi_list) < 3:
        return []
    
    results = []
    seg_start = 0
    seg_dir = bi_list[0]['dir']
    
    i = 0
    while i < len(bi_list):
        # 统计连续同向笔的数量
        same_dir_count = 0
        while i + same_dir_count < len(bi_list) and bi_list[i + same_dir_count]['dir'] == seg_dir:
            same_dir_count += 1
        
        # 如果至少有3笔同向，可能形成线段
        if same_dir_count >= 3:
            # 找这组笔的结束点（当反向笔出现时）
            seg_end = i + same_dir_count - 1
            
            # 简单检查：线段应该包含至少3笔
            seg_bars = bi_list[i:seg_end+1]
            is_sure = len(seg_bars) >= 3
            
            # 计算段内极值
            if seg_dir == 'up':
                trough = min(b['low'] for b in seg_bars)
                peak_trough = trough
            else:
                peak = max(b['high'] for b in seg_bars)
                peak_trough = peak
            
            results.append((len(results), i, seg_end, seg_dir, is_sure, peak_trough))
            
            # 下一段方向相反
            seg_dir = 'down' if seg_dir == 'up' else 'up'
            i = seg_end + 1
        else:
            # 不足3笔，跳过
            i += 1
    
    return results

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('date', nargs='?', default='2026-04-03')
    parser.add_argument('--debug', '-d', action='store_true')
    args = parser.parse_args()
    
    print(f"\n{'='*50}")
    print(f"PTA缠论线段检测 v10 | {args.date}")
    print(f"{'='*50}\n")
    
    # 读取K线
    kline_df = parse_kline(args.date)
    print(f"[K线] {len(kline_df)}根")
    
    # 检测笔
    bi_list = detect_bi_with_fractal(kline_df)
    print(f"[笔] {len(bi_list)}条")
    
    for i, bi in enumerate(bi_list):
        print(f"  b{i+1} {bi['dir']:4s} [{bi['start_idx']+1}~{bi['end_idx']+1}] {bi['k_count']}K Δ{bi['change']:.0f}")
        print(f"    price: {bi['start_price']:.0f}→{bi['end_price']:.0f}  high={bi['high']:.0f} low={bi['low']:.0f}")
    
    # 检测线段
    print()
    xd_results = detect_xd_simple(bi_list)
    
    print(f"\n[线段] {len(xd_results)}条")
    for seg_idx, start, end, seg_dir, is_sure, pt in xd_results:
        sure_str = "✅" if is_sure else "❌"
        pt_type = "trough" if seg_dir == 'up' else "peak"
        seg_len = end - start + 1
        print(f"  XD{seg_idx+1} {seg_dir} b{start+1}~b{end+1} ({seg_len}笔) [{sure_str}] {pt_type}={pt:.0f}")
    
    # 统计
    confirmed = sum(1 for r in xd_results if r[4])
    print(f"\n[统计] 确认线段: {confirmed}条 | 虚段: {len(xd_results)-confirmed}条")
    print(f"[预期] 4月3日应有16条笔，3条线段")
    print(f"       实际笔数: {len(bi_list)}")
    
    # 尝试匹配已知的16笔
    if len(bi_list) > 0:
        print("\n[关键笔验证]")
        for i, bi in enumerate(bi_list):
            if i < 8:
                print(f"  b{i+1}: {bi['dir']} {bi['start_price']:.0f}→{bi['end_price']:.0f} (期望: b1↑6726→6922, b4↓6922→6810)")

if __name__ == '__main__':
    main()
#!/usr/bin/env python3
"""
PTA缠论线段检测 - v22
基于v20结果，合并相邻同向笔（如果中间逆向笔未创新低/新高）
"""

import pandas as pd
import numpy as np

def parse_kline(date_str):
    """读取K线数据"""
    df = pd.read_csv('/tmp/pta_1min.csv')
    df['datetime'] = pd.to_datetime(df['datetime'])
    day_df = df[df['datetime'].dt.date == pd.Timestamp(date_str).date()].sort_values('datetime')
    day_df = day_df[df['close'].notna() & (df['close'] > 0)].reset_index(drop=True)
    return day_df

def find_fractals_simple(kline_df):
    """在原始K线上简单找分型"""
    highs = kline_df['high'].values
    lows = kline_df['low'].values
    
    fractals = []
    
    for i in range(1, len(kline_df)-1):
        h1, l1 = highs[i-1], lows[i-1]
        h2, l2 = highs[i], lows[i]
        h3, l3 = highs[i+1], lows[i+1]
        
        # 顶分型
        if h2 > h1 and h2 > h3 and l2 > min(l1, l3):
            fractals.append({
                'idx': i,
                'price': h2,
                'type': 'top',
                'datetime': kline_df.iloc[i]['datetime']
            })
        
        # 底分型
        if l2 < l1 and l2 < l3 and h2 < max(h1, h3):
            fractals.append({
                'idx': i,
                'price': l2,
                'type': 'bottom',
                'datetime': kline_df.iloc[i]['datetime']
            })
    
    return fractals

def detect_bi_v20(kline_df, fractals):
    """v20笔检测（复制过来）"""
    if len(fractals) < 2:
        return []
    
    fractals.sort(key=lambda x: x['idx'])
    
    bi_list = []
    i = 0
    
    current_fractal = fractals[i]
    current_dir = 'up' if current_fractal['type'] == 'bottom' else 'down'
    
    while i < len(fractals):
        if current_dir == 'up':
            if current_fractal['type'] != 'bottom':
                for j in range(i, len(fractals)):
                    if fractals[j]['type'] == 'bottom':
                        current_fractal = fractals[j]
                        i = j
                        break
                else:
                    break
            
            start_fractal = current_fractal
            end_fractal = None
            j = i + 1
            
            while j < len(fractals):
                f = fractals[j]
                
                if f['type'] == 'top':
                    k_count = f['idx'] - start_fractal['idx'] + 1
                    if k_count >= 4:
                        if end_fractal is None or f['price'] > end_fractal['price']:
                            end_fractal = f
                
                elif f['type'] == 'bottom':
                    if end_fractal is not None:
                        k_count = f['idx'] - end_fractal['idx'] + 1
                        if k_count >= 4:
                            break
                
                j += 1
            
            if end_fractal:
                bi_list.append({
                    'idx': len(bi_list),
                    'dir': 'up',
                    'start_idx': start_fractal['idx'],
                    'end_idx': end_fractal['idx'],
                    'start_price': start_fractal['price'],
                    'end_price': end_fractal['price'],
                    'k_count': end_fractal['idx'] - start_fractal['idx'] + 1,
                    'change': end_fractal['price'] - start_fractal['price']
                })
                
                current_fractal = end_fractal
                current_dir = 'down'
                i = fractals.index(end_fractal)
            else:
                i += 1
        
        else:
            if current_fractal['type'] != 'top':
                for j in range(i, len(fractals)):
                    if fractals[j]['type'] == 'top':
                        current_fractal = fractals[j]
                        i = j
                        break
                else:
                    break
            
            start_fractal = current_fractal
            end_fractal = None
            j = i + 1
            
            while j < len(fractals):
                f = fractals[j]
                
                if f['type'] == 'bottom':
                    k_count = f['idx'] - start_fractal['idx'] + 1
                    if k_count >= 4:
                        if end_fractal is None or f['price'] < end_fractal['price']:
                            end_fractal = f
                
                elif f['type'] == 'top':
                    if end_fractal is not None:
                        k_count = f['idx'] - end_fractal['idx'] + 1
                        if k_count >= 4:
                            break
                
                j += 1
            
            if end_fractal:
                bi_list.append({
                    'idx': len(bi_list),
                    'dir': 'down',
                    'start_idx': start_fractal['idx'],
                    'end_idx': end_fractal['idx'],
                    'start_price': start_fractal['price'],
                    'end_price': end_fractal['price'],
                    'k_count': end_fractal['idx'] - start_fractal['idx'] + 1,
                    'change': start_fractal['price'] - end_fractal['price']
                })
                
                current_fractal = end_fractal
                current_dir = 'up'
                i = fractals.index(end_fractal)
            else:
                i += 1
    
    return bi_list

def merge_adjacent_bi(bi_list, kline_df):
    """
    合并相邻同向笔（如果中间逆向笔未创新低/新高）
    """
    if len(bi_list) < 2:
        return bi_list
    
    merged = []
    i = 0
    
    while i < len(bi_list):
        current = bi_list[i]
        
        # 检查是否可以与后面的同向笔合并
        j = i + 1
        while j < len(bi_list) and bi_list[j]['dir'] == current['dir']:
            # 检查i和j之间的逆向笔
            can_merge = True
            
            for k in range(i, j):
                if bi_list[k]['dir'] != current['dir']:
                    # 逆向笔
                    if current['dir'] == 'up':
                        # 向上笔合并：检查逆向笔是否创新低
                        if bi_list[k]['end_price'] < current['start_price']:
                            can_merge = False
                            break
                    else:
                        # 向下笔合并：检查逆向笔是否创新高
                        if bi_list[k]['end_price'] > current['start_price']:
                            can_merge = False
                            break
            
            if not can_merge:
                break
            
            # 可以合并，更新current的端点
            current['end_idx'] = bi_list[j]['end_idx']
            current['end_price'] = bi_list[j]['end_price']
            current['k_count'] = bi_list[j]['end_idx'] - current['start_idx'] + 1
            current['change'] = abs(current['end_price'] - current['start_price'])
            
            j += 1
        
        merged.append(current)
        i = j
    
    return merged

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('date', nargs='?', default='2026-04-03')
    args = parser.parse_args()
    
    print(f"\n{'='*50}")
    print(f"PTA缠论线段检测 v22 | {args.date}")
    print(f"{'='*50}\n")
    
    # 读取K线
    kline_df = parse_kline(args.date)
    print(f"[K线] {len(kline_df)}根")
    
    # 找分型
    fractals = find_fractals_simple(kline_df)
    print(f"[分型] {len(fractals)}个")
    
    # v20检测笔
    bi_list_v20 = detect_bi_v20(kline_df, fractals)
    print(f"[v20笔] {len(bi_list_v20)}条")
    
    # 合并相邻笔
    bi_list = merge_adjacent_bi(bi_list_v20, kline_df)
    print(f"[合并后笔] {len(bi_list)}条")
    
    # 显示所有笔
    for i, bi in enumerate(bi_list):
        print(f"  b{i+1} {bi['dir']:4s} [{bi['start_idx']+1}~{bi['end_idx']+1}] {bi['k_count']}K Δ{bi['change']:.0f}")
        print(f"    price: {bi['start_price']:.0f}→{bi['end_price']:.0f}")
    
    # 匹配预期笔
    print("\n[与预期笔匹配]")
    expected = [
        (1, 'up', 6726, 6922),
        (4, 'down', 6922, 6810),
        (7, 'up', 6810, 6948)
    ]
    
    matches = 0
    for exp_idx, exp_dir, exp_start, exp_end in expected:
        found = False
        for bi in bi_list:
            if bi['dir'] == exp_dir:
                start_diff = abs(bi['start_price'] - exp_start)
                end_diff = abs(bi['end_price'] - exp_end)
                if start_diff < 30 and end_diff < 30:
                    print(f"  b{exp_idx} {exp_dir} {exp_start}→{exp_end}")
                    print(f"    匹配: b{bi['idx']+1} {bi['dir']} {bi['start_price']:.0f}→{bi['end_price']:.0f}")
                    matches += 1
                    found = True
                    break
        
        if not found:
            print(f"  b{exp_idx} {exp_dir} {exp_start}→{exp_end} - 未匹配")
    
    print(f"\n[统计] 笔数: {len(bi_list)} (期望: 16)")
    print(f"       关键笔匹配: {matches}/3")
    
    # 线段检测
    if len(bi_list) >= 3:
        print(f"\n[线段检测]")
        xd_count = 0
        i = 0
        while i < len(bi_list):
            seg_dir = bi_list[i]['dir']
            seg_start = i
            while i < len(bi_list) and bi_list[i]['dir'] == seg_dir:
                i += 1
            seg_end = i - 1
            seg_len = seg_end - seg_start + 1
            
            if seg_len >= 3:
                xd_count += 1
                seg_bars = bi_list[seg_start:seg_end+1]
                if seg_dir == 'up':
                    trough = min(b['low'] for b in seg_bars)
                    print(f"  XD{xd_count} {seg_dir} b{seg_start+1}~b{seg_end+1} ({seg_len}笔) trough={trough:.0f}")
                else:
                    peak = max(b['high'] for b in seg_bars)
                    print(f"  XD{xd_count} {seg_dir} b{seg_start+1}~b{seg_end+1} ({seg_len}笔) peak={peak:.0f}")
        
        print(f"\n[线段] {xd_count}条 (期望: 3)")

if __name__ == '__main__':
    main()
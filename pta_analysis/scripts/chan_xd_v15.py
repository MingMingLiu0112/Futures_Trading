#!/usr/bin/env python3
"""
PTA缠论线段检测 - v15
改进端点检测：跟踪最高/最低分型直到破坏
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

def find_fractals_raw(kline_df):
    """在原始K线上找分型"""
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

def detect_bi_v15(kline_df, fractals):
    """
    v15笔检测：跟踪最高/最低分型直到破坏
    """
    if len(fractals) < 2:
        return []
    
    bi_list = []
    i = 0
    
    while i < len(fractals):
        current = fractals[i]
        
        if current['type'] == 'bottom':
            # 向上笔
            best_top = None
            best_top_idx = -1
            j = i + 1
            broken = False
            
            while j < len(fractals) and not broken:
                f = fractals[j]
                
                if f['type'] == 'top':
                    # 更高的顶分型
                    if f['price'] > current['price']:
                        if best_top is None or f['price'] > best_top['price']:
                            best_top = f
                            best_top_idx = j
                elif f['type'] == 'bottom':
                    # 检查是否破坏
                    if f['price'] < current['price']:
                        # 更低的底分型，破坏向上笔
                        broken = True
                        break
                
                j += 1
            
            if best_top and not broken:
                # 检查笔长度
                start_idx = current['idx']
                end_idx = best_top['idx']
                k_count = end_idx - start_idx + 1
                
                if k_count >= 5:
                    # 计算笔内高低点
                    segment = kline_df.iloc[start_idx:end_idx+1]
                    bi_high = segment['high'].max()
                    bi_low = segment['low'].min()
                    
                    bi_list.append({
                        'idx': len(bi_list),
                        'dir': 'up',
                        'start_idx': start_idx,
                        'end_idx': end_idx,
                        'start_price': current['price'],
                        'end_price': best_top['price'],
                        'high': bi_high,
                        'low': bi_low,
                        'k_count': k_count,
                        'change': best_top['price'] - current['price']
                    })
                    
                    i = best_top_idx
                    continue
        
        elif current['type'] == 'top':
            # 向下笔
            best_bottom = None
            best_bottom_idx = -1
            j = i + 1
            broken = False
            
            while j < len(fractals) and not broken:
                f = fractals[j]
                
                if f['type'] == 'bottom':
                    # 更低的底分型
                    if f['price'] < current['price']:
                        if best_bottom is None or f['price'] < best_bottom['price']:
                            best_bottom = f
                            best_bottom_idx = j
                elif f['type'] == 'top':
                    # 检查是否破坏
                    if f['price'] > current['price']:
                        # 更高的顶分型，破坏向下笔
                        broken = True
                        break
                
                j += 1
            
            if best_bottom and not broken:
                # 检查笔长度
                start_idx = current['idx']
                end_idx = best_bottom['idx']
                k_count = end_idx - start_idx + 1
                
                if k_count >= 5:
                    # 计算笔内高低点
                    segment = kline_df.iloc[start_idx:end_idx+1]
                    bi_high = segment['high'].max()
                    bi_low = segment['low'].min()
                    
                    bi_list.append({
                        'idx': len(bi_list),
                        'dir': 'down',
                        'start_idx': start_idx,
                        'end_idx': end_idx,
                        'start_price': current['price'],
                        'end_price': best_bottom['price'],
                        'high': bi_high,
                        'low': bi_low,
                        'k_count': k_count,
                        'change': current['price'] - best_bottom['price']
                    })
                    
                    i = best_bottom_idx
                    continue
        
        # 如果没有找到有效的笔，移动到下一个分型
        i += 1
    
    return bi_list

def match_expected_bi(bi_list):
    """匹配预期的16条笔"""
    expected_key_points = [
        (1, 'up', 6726, 6922),
        (4, 'down', 6922, 6810),
        (7, 'up', 6810, 6948)
    ]
    
    print("\n[与预期笔匹配]")
    matches = []
    for exp_idx, exp_dir, exp_start, exp_end in expected_key_points:
        best_match = None
        best_score = float('inf')
        
        for bi in bi_list:
            if bi['dir'] == exp_dir:
                start_diff = abs(bi['start_price'] - exp_start)
                end_diff = abs(bi['end_price'] - exp_end)
                score = start_diff + end_diff
                
                if score < best_score and score < 50:
                    best_score = score
                    best_match = bi
        
        if best_match:
            matches.append((exp_idx, best_match))
            print(f"  b{exp_idx} {exp_dir} {exp_start}→{exp_end}")
            print(f"    匹配: b{best_match['idx']+1} {best_match['dir']} {best_match['start_price']:.0f}→{best_match['end_price']:.0f} (误差={best_score:.0f})")
        else:
            print(f"  b{exp_idx} {exp_dir} {exp_start}→{exp_end} - 未找到匹配")
    
    return matches

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('date', nargs='?', default='2026-04-03')
    args = parser.parse_args()
    
    print(f"\n{'='*50}")
    print(f"PTA缠论线段检测 v15 | {args.date}")
    print(f"{'='*50}\n")
    
    # 读取K线
    kline_df = parse_kline(args.date)
    print(f"[K线] {len(kline_df)}根")
    
    # 找分型
    fractals = find_fractals_raw(kline_df)
    print(f"[分型] {len(fractals)}个")
    
    # 检测笔
    bi_list = detect_bi_v15(kline_df, fractals)
    print(f"\n[笔] {len(bi_list)}条")
    
    # 显示所有笔
    for i, bi in enumerate(bi_list):
        print(f"  b{i+1} {bi['dir']:4s} [{bi['start_idx']+1}~{bi['end_idx']+1}] {bi['k_count']}K Δ{bi['change']:.0f}")
        print(f"    price: {bi['start_price']:.0f}→{bi['end_price']:.0f}")
    
    # 匹配预期笔
    matches = match_expected_bi(bi_list)
    
    print(f"\n[统计] 笔数: {len(bi_list)} (期望: 16)")
    
    # 如果笔数接近16，尝试线段检测
    if 14 <= len(bi_list) <= 18:
        print("\n✅ 笔数接近预期 (16±2)")
        
        # 简单线段检测
        if len(bi_list) >= 3:
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
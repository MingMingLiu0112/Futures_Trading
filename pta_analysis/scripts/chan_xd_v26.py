#!/usr/bin/env python3
"""
PTA缠论线段检测 - v26
基于v25结果，尝试合并向上笔以获得线段
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

def detect_bi_v24(kline_df, fractals, threshold_ratio=0.2):
    """v24笔检测（复制过来）"""
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
            main_bi_amplitude = 0
            
            while j < len(fractals):
                f = fractals[j]
                
                if f['type'] == 'top':
                    k_count = f['idx'] - start_fractal['idx'] + 1
                    if k_count >= 4:
                        candidate_amplitude = f['price'] - start_fractal['price']
                        if end_fractal is None or f['price'] > end_fractal['price']:
                            end_fractal = f
                            main_bi_amplitude = candidate_amplitude
                
                elif f['type'] == 'bottom':
                    if end_fractal is not None:
                        k_count = f['idx'] - end_fractal['idx'] + 1
                        if k_count >= 4:
                            pullback_amplitude = end_fractal['price'] - f['price']
                            if main_bi_amplitude > 0 and pullback_amplitude < main_bi_amplitude * threshold_ratio:
                                pass
                            else:
                                break
                
                j += 1
            
            if end_fractal:
                start_idx = start_fractal['idx']
                end_idx = end_fractal['idx']
                segment = kline_df.iloc[start_idx:end_idx+1]
                
                start_price = segment.iloc[0]['low']
                end_price = segment.iloc[-1]['high']
                
                bi_high = segment['high'].max()
                bi_low = segment['low'].min()
                
                bi_list.append({
                    'idx': len(bi_list),
                    'dir': 'up',
                    'start_idx': start_idx,
                    'end_idx': end_idx,
                    'start_price': start_price,
                    'end_price': end_price,
                    'high': bi_high,
                    'low': bi_low,
                    'k_count': end_idx - start_idx + 1,
                    'change': end_price - start_price,
                    'amplitude': main_bi_amplitude
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
            main_bi_amplitude = 0
            
            while j < len(fractals):
                f = fractals[j]
                
                if f['type'] == 'bottom':
                    k_count = f['idx'] - start_fractal['idx'] + 1
                    if k_count >= 4:
                        candidate_amplitude = start_fractal['price'] - f['price']
                        if end_fractal is None or f['price'] < end_fractal['price']:
                            end_fractal = f
                            main_bi_amplitude = candidate_amplitude
                
                elif f['type'] == 'top':
                    if end_fractal is not None:
                        k_count = f['idx'] - end_fractal['idx'] + 1
                        if k_count >= 4:
                            rebound_amplitude = f['price'] - end_fractal['price']
                            if main_bi_amplitude > 0 and rebound_amplitude < main_bi_amplitude * threshold_ratio:
                                pass
                            else:
                                break
                
                j += 1
            
            if end_fractal:
                start_idx = start_fractal['idx']
                end_idx = end_fractal['idx']
                segment = kline_df.iloc[start_idx:end_idx+1]
                
                start_price = segment.iloc[0]['high']
                end_price = segment.iloc[-1]['low']
                
                bi_high = segment['high'].max()
                bi_low = segment['low'].min()
                
                bi_list.append({
                    'idx': len(bi_list),
                    'dir': 'down',
                    'start_idx': start_idx,
                    'end_idx': end_idx,
                    'start_price': start_price,
                    'end_price': end_price,
                    'high': bi_high,
                    'low': bi_low,
                    'k_count': end_idx - start_idx + 1,
                    'change': start_price - end_price,
                    'amplitude': main_bi_amplitude
                })
                
                current_fractal = end_fractal
                current_dir = 'up'
                i = fractals.index(end_fractal)
            else:
                i += 1
    
    return bi_list

def merge_first_bi(bi_list, kline_df):
    """合并第一笔（从v25复制）"""
    if len(bi_list) < 5:
        return bi_list
    
    if (bi_list[0]['dir'] == 'up' and 
        bi_list[1]['dir'] == 'down' and 
        bi_list[2]['dir'] == 'up' and 
        bi_list[3]['dir'] == 'down' and 
        bi_list[4]['dir'] == 'up'):
        
        b1 = bi_list[0]
        b2 = bi_list[1]
        b3 = bi_list[2]
        b4 = bi_list[3]
        b5 = bi_list[4]
        
        b1_start = b1['start_price']
        b2_end = b2['end_price']
        b4_end = b4['end_price']
        
        if b2_end > b1_start and b4_end > b1_start:
            start_idx = b1['start_idx']
            end_idx = b5['end_idx']
            segment = kline_df.iloc[start_idx:end_idx+1]
            
            start_price = segment.iloc[0]['low']
            end_price = segment.iloc[-1]['high']
            
            bi_high = segment['high'].max()
            bi_low = segment['low'].min()
            
            merged_bi = {
                'idx': 0,
                'dir': 'up',
                'start_idx': start_idx,
                'end_idx': end_idx,
                'start_price': start_price,
                'end_price': end_price,
                'high': bi_high,
                'low': bi_low,
                'k_count': end_idx - start_idx + 1,
                'change': end_price - start_price,
                'amplitude': end_price - start_price,
                'merged': True
            }
            
            new_bi_list = [merged_bi]
            for i in range(5, len(bi_list)):
                bi = bi_list[i].copy()
                bi['idx'] = len(new_bi_list)
                new_bi_list.append(bi)
            
            return new_bi_list
    
    return bi_list

def merge_up_bi_for_xd(bi_list, kline_df, min_segment_len=3):
    """
    合并向上笔以获得线段
    尝试将多个向上笔合并为一条大向上笔（如果中间向下笔幅度小）
    """
    if len(bi_list) < 3:
        return bi_list
    
    new_bi_list = []
    i = 0
    
    while i < len(bi_list):
        current = bi_list[i]
        
        # 如果是向上笔，尝试合并后续向上笔
        if current['dir'] == 'up':
            merge_candidates = [current]
            j = i + 1
            
            while j < len(bi_list):
                # 检查下一个笔
                next_bi = bi_list[j]
                
                if next_bi['dir'] == 'down':
                    # 向下笔，检查幅度
                    down_amplitude = next_bi['change']
                    # 与当前向上笔幅度比较
                    up_amplitude = current['end_price'] - current['start_price']
                    
                    if down_amplitude < up_amplitude * 0.3:  # 向下笔幅度小于向上笔的30%
                        # 小幅度回调，可能不破坏线段
                        # 检查再下一个笔
                        if j + 1 < len(bi_list) and bi_list[j+1]['dir'] == 'up':
                            # 后面还有向上笔，可以合并
                            merge_candidates.append(next_bi)
                            merge_candidates.append(bi_list[j+1])
                            j += 2
                            continue
                
                # 不能合并，结束
                break
            
            if len(merge_candidates) >= 3:  # 至少1上1下1上
                # 合并
                start_idx = merge_candidates[0]['start_idx']
                end_idx = merge_candidates[-1]['end_idx']
                segment = kline_df.iloc[start_idx:end_idx+1]
                
                start_price = segment.iloc[0]['low']
                end_price = segment.iloc[-1]['high']
                
                bi_high = segment['high'].max()
                bi_low = segment['low'].min()
                
                merged_bi = {
                    'idx': len(new_bi_list),
                    'dir': 'up',
                    'start_idx': start_idx,
                    'end_idx': end_idx,
                    'start_price': start_price,
                    'end_price': end_price,
                    'high': bi_high,
                    'low': bi_low,
                    'k_count': end_idx - start_idx + 1,
                    'change': end_price - start_price,
                    'amplitude': end_price - start_price,
                    'merged_xd': True
                }
                
                new_bi_list.append(merged_bi)
                i = j
            else:
                new_bi_list.append(current)
                i += 1
        else:
            new_bi_list.append(current)
            i += 1
    
    return new_bi_list

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('date', nargs='?', default='2026-04-03')
    args = parser.parse_args()
    
    print(f"\n{'='*50}")
    print(f"PTA缠论线段检测 v26 | {args.date}")
    print(f"{'='*50}\n")
    
    # 读取K线
    kline_df = parse_kline(args.date)
    print(f"[K线] {len(kline_df)}根")
    
    # 找分型
    fractals = find_fractals_simple(kline_df)
    print(f"[分型] {len(fractals)}个")
    
    # v24检测笔（阈值0.2）
    bi_list = detect_bi_v24(kline_df, fractals, threshold_ratio=0.2)
    print(f"[v24笔] {len(bi_list)}条")
    
    # 合并第一笔
    bi_list = merge_first_bi(bi_list, kline_df)
    print(f"[合并第一笔后] {len(bi_list)}条")
    
    # 合并向上笔以获得线段
    bi_list = merge_up_bi_for_xd(bi_list, kline_df)
    print(f"[合并向上笔后] {len(bi_list)}条")
    
    # 显示所有笔
    for i, bi in enumerate(bi_list):
        merged_flag = ""
        if bi.get('merged', False):
            merged_flag = " (合并第一笔)"
        elif bi.get('merged_xd', False):
            merged_flag = " (合并线段)"
        
        print(f"  b{i+1} {bi['dir']:4s} [{bi['start_idx']+1}~{bi['end_idx']+1}] {bi['k_count']}K Δ{bi['change']:.0f}{merged_flag}")
        print(f"    price: {bi['start_price']:.0f}→{bi['end_price']:.0f}")
        print(f"    range: {bi['low']:.0f}~{bi['high']:.0f}")
    
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
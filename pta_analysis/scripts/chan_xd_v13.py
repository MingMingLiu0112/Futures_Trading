#!/usr/bin/env python3
"""
PTA缠论线段检测 - v13
改进笔检测：寻找有效的顶底分型对
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
    """
    在原始K线上找分型（不合并）
    """
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

def detect_bi_from_fractals(kline_df, fractals):
    """
    从分型点检测笔，寻找有效的顶底分型对
    """
    if len(fractals) < 2:
        return []
    
    bi_list = []
    i = 0
    
    while i < len(fractals):
        current = fractals[i]
        
        if current['type'] == 'bottom':
            # 从底分型开始找向上的笔
            # 找下一个更高的顶分型
            found_top = None
            for j in range(i+1, len(fractals)):
                if fractals[j]['type'] == 'top' and fractals[j]['price'] > current['price']:
                    # 检查中间是否有更低的底分型破坏
                    has_lower_bottom = False
                    for k in range(i+1, j):
                        if fractals[k]['type'] == 'bottom' and fractals[k]['price'] < current['price']:
                            has_lower_bottom = True
                            break
                    
                    if not has_lower_bottom:
                        found_top = fractals[j]
                        break
            
            if found_top:
                # 检查笔长度
                start_idx = current['idx']
                end_idx = found_top['idx']
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
                        'end_price': found_top['price'],
                        'high': bi_high,
                        'low': bi_low,
                        'k_count': k_count,
                        'change': found_top['price'] - current['price']
                    })
                    
                    # 移动到顶分型位置
                    i = j
                    continue
        
        elif current['type'] == 'top':
            # 从顶分型开始找向下的笔
            # 找下一个更低的底分型
            found_bottom = None
            for j in range(i+1, len(fractals)):
                if fractals[j]['type'] == 'bottom' and fractals[j]['price'] < current['price']:
                    # 检查中间是否有更高的顶分型破坏
                    has_higher_top = False
                    for k in range(i+1, j):
                        if fractals[k]['type'] == 'top' and fractals[k]['price'] > current['price']:
                            has_higher_top = True
                            break
                    
                    if not has_higher_top:
                        found_bottom = fractals[j]
                        break
            
            if found_bottom:
                # 检查笔长度
                start_idx = current['idx']
                end_idx = found_bottom['idx']
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
                        'end_price': found_bottom['price'],
                        'high': bi_high,
                        'low': bi_low,
                        'k_count': k_count,
                        'change': current['price'] - found_bottom['price']
                    })
                    
                    # 移动到底分型位置
                    i = j
                    continue
        
        # 如果没有找到有效的笔，移动到下一个分型
        i += 1
    
    return bi_list

def match_expected_bi(bi_list):
    """尝试匹配预期的16条笔"""
    expected_key_points = [
        (1, 'up', 6726, 6922),
        (4, 'down', 6922, 6810),
        (7, 'up', 6810, 6948)
    ]
    
    print("\n[与预期笔匹配]")
    for exp_idx, exp_dir, exp_start, exp_end in expected_key_points:
        found = False
        for bi in bi_list:
            if bi['dir'] == exp_dir:
                start_diff = abs(bi['start_price'] - exp_start)
                end_diff = abs(bi['end_price'] - exp_end)
                if start_diff < 20 and end_diff < 20:
                    print(f"  b{exp_idx} {exp_dir} {exp_start}→{exp_end}")
                    print(f"    匹配: b{bi['idx']+1} {bi['dir']} {bi['start_price']:.0f}→{bi['end_price']:.0f}")
                    found = True
                    break
        
        if not found:
            print(f"  b{exp_idx} {exp_dir} {exp_start}→{exp_end} - 未找到匹配")

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('date', nargs='?', default='2026-04-03')
    args = parser.parse_args()
    
    print(f"\n{'='*50}")
    print(f"PTA缠论线段检测 v13 | {args.date}")
    print(f"{'='*50}\n")
    
    # 读取K线
    kline_df = parse_kline(args.date)
    print(f"[K线] {len(kline_df)}根")
    
    # 找分型
    fractals = find_fractals_raw(kline_df)
    print(f"[分型] {len(fractals)}个")
    
    # 显示前10个分型
    print("\n前10个分型:")
    for i, f in enumerate(fractals[:10]):
        print(f"  {i+1}: {f['type']} at idx={f['idx']+1} price={f['price']:.0f}")
    
    # 检测笔
    bi_list = detect_bi_from_fractals(kline_df, fractals)
    print(f"\n[笔] {len(bi_list)}条")
    
    # 显示所有笔
    for i, bi in enumerate(bi_list):
        print(f"  b{i+1} {bi['dir']:4s} [{bi['start_idx']+1}~{bi['end_idx']+1}] {bi['k_count']}K Δ{bi['change']:.0f}")
        print(f"    price: {bi['start_price']:.0f}→{bi['end_price']:.0f}")
    
    # 匹配预期笔
    match_expected_bi(bi_list)
    
    # 简单线段检测
    if len(bi_list) >= 3:
        print(f"\n[简单线段检测]")
        seg_idx = 0
        i = 0
        while i < len(bi_list):
            seg_dir = bi_list[i]['dir']
            seg_start = i
            while i < len(bi_list) and bi_list[i]['dir'] == seg_dir:
                i += 1
            seg_end = i - 1
            
            seg_len = seg_end - seg_start + 1
            if seg_len >= 3:
                seg_idx += 1
                seg_bars = bi_list[seg_start:seg_end+1]
                if seg_dir == 'up':
                    trough = min(b['low'] for b in seg_bars)
                    print(f"  XD{seg_idx} {seg_dir} b{seg_start+1}~b{seg_end+1} ({seg_len}笔) trough={trough:.0f}")
                else:
                    peak = max(b['high'] for b in seg_bars)
                    print(f"  XD{seg_idx} {seg_dir} b{seg_start+1}~b{seg_end+1} ({seg_len}笔) peak={peak:.0f}")

if __name__ == '__main__':
    main()
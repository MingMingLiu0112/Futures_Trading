#!/usr/bin/env python3
"""
PTA缠论线段检测 - v18
提高反向笔幅度阈值（60点）
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

def detect_bi_v18(kline_df, fractals, reverse_threshold=60):
    """
    v18笔检测：提高反向笔幅度阈值
    """
    if len(fractals) < 2:
        return []
    
    bi_list = []
    i = 0
    
    while i < len(fractals):
        current = fractals[i]
        
        if current['type'] == 'bottom':
            # 向上笔
            candidate_tops = []
            j = i + 1
            
            while j < len(fractals):
                f = fractals[j]
                
                if f['type'] == 'top' and f['price'] > current['price']:
                    # 候选顶分型
                    candidate_tops.append((j, f))
                    
                    # 检查这个顶分型后是否有有效的向下笔（幅度>阈值）
                    has_down_bi = False
                    for k in range(j+1, min(j+15, len(fractals))):  # 检查后面15个分型
                        if fractals[k]['type'] == 'bottom' and fractals[k]['price'] < f['price']:
                            down_change = f['price'] - fractals[k]['price']
                            if down_change > reverse_threshold:  # 提高阈值
                                has_down_bi = True
                                break
                    
                    if has_down_bi:
                        # 这个顶分型后跟有效向下笔，可能结束向上笔
                        break
                
                j += 1
            
            if candidate_tops:
                # 取最后一个候选顶分型
                last_idx, last_top = candidate_tops[-1]
                
                # 检查笔长度
                start_idx = current['idx']
                end_idx = last_top['idx']
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
                        'end_price': last_top['price'],
                        'high': bi_high,
                        'low': bi_low,
                        'k_count': k_count,
                        'change': last_top['price'] - current['price']
                    })
                    
                    i = last_idx
                    continue
        
        elif current['type'] == 'top':
            # 向下笔
            candidate_bottoms = []
            j = i + 1
            
            while j < len(fractals):
                f = fractals[j]
                
                if f['type'] == 'bottom' and f['price'] < current['price']:
                    # 候选底分型
                    candidate_bottoms.append((j, f))
                    
                    # 检查这个底分型后是否有有效的向上笔
                    has_up_bi = False
                    for k in range(j+1, min(j+15, len(fractals))):
                        if fractals[k]['type'] == 'top' and fractals[k]['price'] > f['price']:
                            up_change = fractals[k]['price'] - f['price']
                            if up_change > reverse_threshold:
                                has_up_bi = True
                                break
                    
                    if has_up_bi:
                        break
                
                j += 1
            
            if candidate_bottoms:
                # 取最后一个候选底分型
                last_idx, last_bottom = candidate_bottoms[-1]
                
                # 检查笔长度
                start_idx = current['idx']
                end_idx = last_bottom['idx']
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
                        'end_price': last_bottom['price'],
                        'high': bi_high,
                        'low': bi_low,
                        'k_count': k_count,
                        'change': current['price'] - last_bottom['price']
                    })
                    
                    i = last_idx
                    continue
        
        i += 1
    
    return bi_list

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('date', nargs='?', default='2026-04-03')
    parser.add_argument('--threshold', '-t', type=int, default=60)
    args = parser.parse_args()
    
    print(f"\n{'='*50}")
    print(f"PTA缠论线段检测 v18 | {args.date} | 阈值={args.threshold}")
    print(f"{'='*50}\n")
    
    # 读取K线
    kline_df = parse_kline(args.date)
    print(f"[K线] {len(kline_df)}根")
    
    # 找分型
    fractals = find_fractals_raw(kline_df)
    print(f"[分型] {len(fractals)}个")
    
    # 检测笔
    bi_list = detect_bi_v18(kline_df, fractals, args.threshold)
    print(f"\n[笔] {len(bi_list)}条")
    
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
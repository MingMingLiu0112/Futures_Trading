#!/usr/bin/env python3
"""
PTA缠论线段检测 - v16
新方法：枚举所有可能的分型对，选择有效笔
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

def find_valid_bi_pairs(fractals, kline_df):
    """
    寻找有效的笔对：底分型->顶分型 或 顶分型->底分型
    """
    if len(fractals) < 2:
        return []
    
    # 按索引排序
    fractals.sort(key=lambda x: x['idx'])
    
    potential_pairs = []
    
    # 枚举所有可能的分型对
    for i in range(len(fractals)):
        for j in range(i+1, len(fractals)):
            f1 = fractals[i]
            f2 = fractals[j]
            
            # 必须交替：底->顶 或 顶->底
            if not ((f1['type'] == 'bottom' and f2['type'] == 'top') or
                    (f1['type'] == 'top' and f2['type'] == 'bottom')):
                continue
            
            # 检查价格关系
            if f1['type'] == 'bottom' and f2['type'] == 'top':
                if f2['price'] <= f1['price']:
                    continue  # 顶分型必须高于底分型
                direction = 'up'
                price_change = f2['price'] - f1['price']
            else:
                if f2['price'] >= f1['price']:
                    continue  # 底分型必须低于顶分型
                direction = 'down'
                price_change = f1['price'] - f2['price']
            
            # 检查笔长度
            k_count = f2['idx'] - f1['idx'] + 1
            if k_count < 5:
                continue
            
            # 价格变化幅度检查
            if price_change < 10:
                continue
            
            # 检查中间是否有破坏性分型
            has_break = False
            for k in range(i+1, j):
                f_mid = fractals[k]
                if direction == 'up':
                    # 向上笔：中间有更低的底分型破坏
                    if f_mid['type'] == 'bottom' and f_mid['price'] < f1['price']:
                        has_break = True
                        break
                else:
                    # 向下笔：中间有更高的顶分型破坏
                    if f_mid['type'] == 'top' and f_mid['price'] > f1['price']:
                        has_break = True
                        break
            
            if has_break:
                continue
            
            # 计算笔内高低点
            segment = kline_df.iloc[f1['idx']:f2['idx']+1]
            bi_high = segment['high'].max()
            bi_low = segment['low'].min()
            
            potential_pairs.append({
                'start_idx': f1['idx'],
                'end_idx': f2['idx'],
                'start_fractal': f1,
                'end_fractal': f2,
                'direction': direction,
                'price_change': price_change,
                'k_count': k_count,
                'bi_high': bi_high,
                'bi_low': bi_low,
                'score': price_change * k_count  # 简单评分
            })
    
    return potential_pairs

def select_best_bi_sequence(pairs):
    """
    从所有可能的笔对中选择最佳序列（不重叠）
    """
    if not pairs:
        return []
    
    # 按结束索引排序
    pairs.sort(key=lambda x: x['end_idx'])
    
    # 动态规划选择最佳序列
    n = len(pairs)
    dp = [0] * n
    prev = [-1] * n
    
    for i in range(n):
        # 当前笔的分数
        dp[i] = pairs[i]['score']
        
        # 找不重叠的前一个笔
        for j in range(i):
            if pairs[j]['end_idx'] < pairs[i]['start_idx']:
                if dp[j] + pairs[i]['score'] > dp[i]:
                    dp[i] = dp[j] + pairs[i]['score']
                    prev[i] = j
    
    # 重建序列
    if not dp:
        return []
    
    # 找最高分
    best_idx = max(range(n), key=lambda i: dp[i])
    
    sequence = []
    while best_idx != -1:
        sequence.append(pairs[best_idx])
        best_idx = prev[best_idx]
    
    sequence.reverse()  # 按时间顺序
    
    # 转换为笔列表
    bi_list = []
    for i, pair in enumerate(sequence):
        bi_list.append({
            'idx': i,
            'dir': pair['direction'],
            'start_idx': pair['start_idx'],
            'end_idx': pair['end_idx'],
            'start_price': pair['start_fractal']['price'],
            'end_price': pair['end_fractal']['price'],
            'high': pair['bi_high'],
            'low': pair['bi_low'],
            'k_count': pair['k_count'],
            'change': pair['price_change']
        })
    
    return bi_list

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('date', nargs='?', default='2026-04-03')
    args = parser.parse_args()
    
    print(f"\n{'='*50}")
    print(f"PTA缠论线段检测 v16 | {args.date}")
    print(f"{'='*50}\n")
    
    # 读取K线
    kline_df = parse_kline(args.date)
    print(f"[K线] {len(kline_df)}根")
    
    # 找分型
    fractals = find_fractals_raw(kline_df)
    print(f"[分型] {len(fractals)}个")
    
    # 显示关键分型
    print("\n关键分型（价格接近预期点）:")
    for f in fractals:
        if (f['type'] == 'bottom' and abs(f['price'] - 6726) < 20) or \
           (f['type'] == 'top' and abs(f['price'] - 6922) < 20) or \
           (f['type'] == 'bottom' and abs(f['price'] - 6810) < 20) or \
           (f['type'] == 'top' and abs(f['price'] - 6948) < 20):
            print(f"  {f['type']} at idx={f['idx']+1} price={f['price']:.0f}")
    
    # 寻找有效笔对
    pairs = find_valid_bi_pairs(fractals, kline_df)
    print(f"\n[潜在笔对] {len(pairs)}个")
    
    # 选择最佳笔序列
    bi_list = select_best_bi_sequence(pairs)
    print(f"[选择笔] {len(bi_list)}条")
    
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
        
        print(f"\n[统计] 笔: {len(bi_list)} (期望: 16) | 线段: {xd_count} (期望: 3)")
        print(f"       关键笔匹配: {matches}/3")

if __name__ == '__main__':
    main()
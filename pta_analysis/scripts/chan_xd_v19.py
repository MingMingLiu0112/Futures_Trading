#!/usr/bin/env python3
"""
PTA缠论线段检测 - v19
基于用户提供的正确笔检测逻辑
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

def handle_include_relationship_simple(kline_df):
    """
    简单包含关系处理：合并连续包含的K线
    实际缠论包含关系更复杂，这里简化
    """
    if len(kline_df) < 2:
        return kline_df
    
    bars = []
    for _, row in kline_df.iterrows():
        bars.append({
            'high': float(row['high']),
            'low': float(row['low']),
            'open': float(row['open']),
            'close': float(row['close']),
            'datetime': row['datetime']
        })
    
    # 简单合并：如果后一根K线完全包含在前一根内，合并
    merged = []
    i = 0
    
    while i < len(bars):
        current = bars[i]
        j = i + 1
        
        while j < len(bars):
            next_bar = bars[j]
            # 检查包含关系
            if (next_bar['high'] <= current['high'] and next_bar['low'] >= current['low']) or \
               (next_bar['high'] >= current['high'] and next_bar['low'] <= current['low']):
                # 合并：取最高high和最低low
                current['high'] = max(current['high'], next_bar['high'])
                current['low'] = min(current['low'], next_bar['low'])
                current['close'] = next_bar['close']  # 更新收盘价
                j += 1
            else:
                break
        
        merged.append(current)
        i = j
    
    return merged

def find_fractals_in_merged(bars):
    """
    在合并后的K线上找分型
    """
    if len(bars) < 3:
        return []
    
    fractals = []
    
    for i in range(1, len(bars)-1):
        h1, l1 = bars[i-1]['high'], bars[i-1]['low']
        h2, l2 = bars[i]['high'], bars[i]['low']
        h3, l3 = bars[i+1]['high'], bars[i+1]['low']
        
        # 顶分型：中间K线高点最高，低点也相对高
        if h2 > h1 and h2 > h3 and l2 > min(l1, l3):
            fractals.append({
                'idx': i,
                'price': h2,
                'type': 'top',
                'datetime': bars[i]['datetime']
            })
        
        # 底分型：中间K线低点最低，高点也相对低
        if l2 < l1 and l2 < l3 and h2 < max(h1, h3):
            fractals.append({
                'idx': i,
                'price': l2,
                'type': 'bottom',
                'datetime': bars[i]['datetime']
            })
    
    return fractals

def detect_bi_v19(bars, fractals):
    """
    v19笔检测：基于用户提供的正确逻辑
    笔动态延续，直到被反向分型确认结束
    """
    if len(fractals) < 2:
        return []
    
    # 按索引排序
    fractals.sort(key=lambda x: x['idx'])
    
    bi_list = []
    i = 0
    
    # 找到第一个分型作为起点
    while i < len(fractals):
        current = fractals[i]
        
        if current['type'] == 'bottom':
            # 开始一个上行笔
            bi_start = current
            bi_dir = 'up'
            bi_end = None
            
            # 寻找笔的结束点
            j = i + 1
            while j < len(fractals):
                f = fractals[j]
                
                if bi_dir == 'up':
                    # 上行笔：寻找顶分型
                    if f['type'] == 'top':
                        # 检查K线数量（简化：用分型索引差）
                        k_count = f['idx'] - bi_start['idx'] + 1
                        if k_count >= 4:  # 至少4根K线
                            # 这是一个可能的结束点
                            bi_end = f
                            
                            # 检查后面是否有更高的顶分型（笔延续）
                            has_higher_top = False
                            for k in range(j+1, len(fractals)):
                                if fractals[k]['type'] == 'top' and fractals[k]['price'] > f['price']:
                                    has_higher_top = True
                                    # 笔延续到更高的顶分型
                                    bi_end = fractals[k]
                                    j = k  # 跳到这个更高的顶分型
                                    break
                            
                            if not has_higher_top:
                                # 笔结束，开始下行笔
                                break
                
                elif bi_dir == 'down':
                    # 下行笔：寻找底分型
                    if f['type'] == 'bottom':
                        k_count = f['idx'] - bi_start['idx'] + 1
                        if k_count >= 4:
                            bi_end = f
                            
                            # 检查后面是否有更低的底分型
                            has_lower_bottom = False
                            for k in range(j+1, len(fractals)):
                                if fractals[k]['type'] == 'bottom' and fractals[k]['price'] < f['price']:
                                    has_lower_bottom = True
                                    bi_end = fractals[k]
                                    j = k
                                    break
                            
                            if not has_lower_bottom:
                                break
                
                j += 1
            
            if bi_end:
                # 计算笔内高低点
                start_idx = bi_start['idx']
                end_idx = bi_end['idx']
                
                # 获取原始K线片段（简化：用合并后的bars）
                segment = bars[start_idx:end_idx+1]
                bi_high = max(b['high'] for b in segment)
                bi_low = min(b['low'] for b in segment)
                
                bi_list.append({
                    'idx': len(bi_list),
                    'dir': bi_dir,
                    'start_idx': start_idx,
                    'end_idx': end_idx,
                    'start_price': bi_start['price'],
                    'end_price': bi_end['price'],
                    'high': bi_high,
                    'low': bi_low,
                    'k_count': end_idx - start_idx + 1,
                    'change': abs(bi_end['price'] - bi_start['price'])
                })
                
                # 下一笔方向相反
                bi_dir = 'down' if bi_dir == 'up' else 'up'
                bi_start = bi_end
                i = fractals.index(bi_end)
            else:
                i += 1
        else:
            # 第一个分型是顶分型，开始下行笔
            bi_start = current
            bi_dir = 'down'
            bi_end = None
            
            j = i + 1
            while j < len(fractals):
                f = fractals[j]
                
                if bi_dir == 'down':
                    if f['type'] == 'bottom':
                        k_count = f['idx'] - bi_start['idx'] + 1
                        if k_count >= 4:
                            bi_end = f
                            
                            # 检查后面是否有更低的底分型
                            has_lower_bottom = False
                            for k in range(j+1, len(fractals)):
                                if fractals[k]['type'] == 'bottom' and fractals[k]['price'] < f['price']:
                                    has_lower_bottom = True
                                    bi_end = fractals[k]
                                    j = k
                                    break
                            
                            if not has_lower_bottom:
                                break
                
                j += 1
            
            if bi_end:
                start_idx = bi_start['idx']
                end_idx = bi_end['idx']
                segment = bars[start_idx:end_idx+1]
                bi_high = max(b['high'] for b in segment)
                bi_low = min(b['low'] for b in segment)
                
                bi_list.append({
                    'idx': len(bi_list),
                    'dir': bi_dir,
                    'start_idx': start_idx,
                    'end_idx': end_idx,
                    'start_price': bi_start['price'],
                    'end_price': bi_end['price'],
                    'high': bi_high,
                    'low': bi_low,
                    'k_count': end_idx - start_idx + 1,
                    'change': abs(bi_end['price'] - bi_start['price'])
                })
                
                bi_dir = 'up'
                bi_start = bi_end
                i = fractals.index(bi_end)
            else:
                i += 1
    
    return bi_list

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('date', nargs='?', default='2026-04-03')
    args = parser.parse_args()
    
    print(f"\n{'='*50}")
    print(f"PTA缠论线段检测 v19 | {args.date}")
    print(f"{'='*50}\n")
    
    # 读取K线
    kline_df = parse_kline(args.date)
    print(f"[原始K线] {len(kline_df)}根")
    
    # 处理包含关系（简化）
    merged_bars = handle_include_relationship_simple(kline_df)
    print(f"[合并后K线] {len(merged_bars)}根")
    
    # 找分型
    fractals = find_fractals_in_merged(merged_bars)
    print(f"[分型] {len(fractals)}个")
    
    # 显示关键分型
    print("\n关键分型:")
    for f in fractals:
        if (f['type'] == 'bottom' and abs(f['price'] - 6726) < 30) or \
           (f['type'] == 'top' and abs(f['price'] - 6922) < 30) or \
           (f['type'] == 'bottom' and abs(f['price'] - 6810) < 30) or \
           (f['type'] == 'top' and abs(f['price'] - 6948) < 30):
            print(f"  {f['type']} at idx={f['idx']+1} price={f['price']:.0f}")
    
    # 检测笔
    bi_list = detect_bi_v19(merged_bars, fractals)
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
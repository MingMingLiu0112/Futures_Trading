#!/usr/bin/env python3
"""
PTA缠论线段检测 - v12
简化版：直接在原始K线找分型，然后验证笔长度
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

def simple_include_merge(kline_df):
    """
    简单包含关系处理：合并连续的包含K线
    取最高high和最低low作为合并后的K线
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
            'datetime': row['datetime'],
            'orig_idx': len(bars)  # 记录原始索引
        })
    
    merged = []
    i = 0
    
    while i < len(bars):
        current = bars[i]
        start_idx = i
        end_idx = i
        
        # 向前查找包含关系
        j = i + 1
        while j < len(bars):
            # 检查是否包含
            if (bars[j]['high'] <= current['high'] and bars[j]['low'] >= current['low']) or \
               (bars[j]['high'] >= current['high'] and bars[j]['low'] <= current['low']):
                # 合并：取最宽范围
                current['high'] = max(current['high'], bars[j]['high'])
                current['low'] = min(current['low'], bars[j]['low'])
                current['close'] = bars[j]['close']  # 更新收盘价为最后一个
                end_idx = j
                j += 1
            else:
                break
        
        merged.append(current)
        i = end_idx + 1
    
    return merged

def find_fractals_simple(bars):
    """
    简单分型检测
    """
    if len(bars) < 3:
        return []
    
    fractals = []
    
    for i in range(1, len(bars)-1):
        h1, l1 = bars[i-1]['high'], bars[i-1]['low']
        h2, l2 = bars[i]['high'], bars[i]['low']
        h3, l3 = bars[i+1]['high'], bars[i+1]['low']
        
        # 顶分型
        if h2 > h1 and h2 > h3 and l2 > min(l1, l3):
            fractals.append({
                'idx': i,
                'price': h2,
                'type': 'top',
                'orig_idx': bars[i].get('orig_idx', i)
            })
        
        # 底分型
        if l2 < l1 and l2 < l3 and h2 < max(h1, h3):
            fractals.append({
                'idx': i,
                'price': l2,
                'type': 'bottom',
                'orig_idx': bars[i].get('orig_idx', i)
            })
    
    return fractals

def detect_bi_from_fractals_simple(bars, fractals, orig_kline_count):
    """
    从分型检测笔，检查原始K线数量
    """
    if len(fractals) < 2:
        return []
    
    # 按索引排序
    fractals.sort(key=lambda x: x['idx'])
    
    bi_list = []
    i = 0
    
    while i < len(fractals) - 1:
        f1 = fractals[i]
        f2 = fractals[i+1]
        
        # 必须交替
        if f1['type'] == f2['type']:
            i += 1
            continue
        
        # 确定方向
        if f1['type'] == 'bottom' and f2['type'] == 'top':
            direction = 'up'
            start_price = f1['price']
            end_price = f2['price']
            
            # 找到笔内的实际高低点
            seg_start = f1['orig_idx']
            seg_end = f2['orig_idx']
            bi_high = max(b['high'] for b in bars[seg_start:seg_end+1])
            bi_low = min(b['low'] for b in bars[seg_start:seg_end+1])
            
        elif f1['type'] == 'top' and f2['type'] == 'bottom':
            direction = 'down'
            start_price = f1['price']
            end_price = f2['price']
            
            seg_start = f1['orig_idx']
            seg_end = f2['orig_idx']
            bi_high = max(b['high'] for b in bars[seg_start:seg_end+1])
            bi_low = min(b['low'] for b in bars[seg_start:seg_end+1])
        else:
            i += 1
            continue
        
        # 检查笔长度（原始K线数量）
        orig_k_count = seg_end - seg_start + 1
        if orig_k_count < 5:
            i += 1
            continue
        
        # 价格变化检查
        price_change = abs(end_price - start_price)
        if price_change < 10:
            i += 1
            continue
        
        bi_list.append({
            'idx': len(bi_list),
            'dir': direction,
            'start_idx': seg_start,
            'end_idx': seg_end,
            'start_price': start_price,
            'end_price': end_price,
            'high': bi_high,
            'low': bi_low,
            'orig_k_count': orig_k_count,
            'change': price_change
        })
        
        i += 1
    
    return bi_list

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('date', nargs='?', default='2026-04-03')
    args = parser.parse_args()
    
    print(f"\n{'='*50}")
    print(f"PTA缠论线段检测 v12 | {args.date}")
    print(f"{'='*50}\n")
    
    # 读取原始K线
    raw_df = parse_kline(args.date)
    print(f"[原始K线] {len(raw_df)}根")
    
    # 转换bars格式
    bars = []
    for idx, row in raw_df.iterrows():
        bars.append({
            'high': float(row['high']),
            'low': float(row['low']),
            'open': float(row['open']),
            'close': float(row['close']),
            'datetime': row['datetime'],
            'orig_idx': idx
        })
    
    # 简单包含处理
    merged_bars = simple_include_merge(raw_df)
    print(f"[合并后K线] {len(merged_bars)}根")
    
    # 在合并后的K线上找分型
    fractals = find_fractals_simple(merged_bars)
    print(f"[分型点] {len(fractals)}个")
    
    # 显示前10个分型
    print("\n前10个分型:")
    for i, f in enumerate(fractals[:10]):
        bar = merged_bars[f['idx']]
        print(f"  {f['type']} at idx={f['idx']} price={f['price']:.0f} (orig_idx={f.get('orig_idx', 'N/A')})")
    
    # 检测笔
    bi_list = detect_bi_from_fractals_simple(bars, fractals, len(raw_df))
    print(f"\n[笔] {len(bi_list)}条")
    
    # 显示所有笔
    for i, bi in enumerate(bi_list):
        print(f"  b{i+1} {bi['dir']:4s} [{bi['start_idx']+1}~{bi['end_idx']+1}] {bi['orig_k_count']}K Δ{bi['change']:.0f}")
        print(f"    price: {bi['start_price']:.0f}→{bi['end_price']:.0f}")
    
    # 检查第一笔
    if bi_list:
        first_bi = bi_list[0]
        print(f"\n[第一笔检查]")
        print(f"  方向: {first_bi['dir']}")
        print(f"  价格: {first_bi['start_price']:.0f}→{first_bi['end_price']:.0f}")
        print(f"  期望: up 6726→6922")
        
        if first_bi['dir'] == 'up' and abs(first_bi['start_price'] - 6726) < 10:
            print("  ✓ 第一笔方向正确，起点接近6726")
        else:
            print("  ✗ 第一笔不正确")
    
    print(f"\n[预期] 16条笔")
    print(f"[实际] {len(bi_list)}条笔")

if __name__ == '__main__':
    main()
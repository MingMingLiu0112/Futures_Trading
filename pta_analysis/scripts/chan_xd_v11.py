#!/usr/bin/env python3
"""
PTA缠论线段检测 - v11
包含缠论标准的包含关系处理
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

def handle_include_relationship(kline_df):
    """
    处理K线包含关系
    规则：
    1. 向上笔中：包含关系取高高（高点取最高，低点取最高的K线的低点）
    2. 向下笔中：包含关系取低低（低点取最低，高点取最低的K线的高点）
    """
    if len(kline_df) < 2:
        return kline_df
    
    # 转换为列表方便处理
    bars = []
    for _, row in kline_df.iterrows():
        bars.append({
            'high': float(row['high']),
            'low': float(row['low']),
            'open': float(row['open']),
            'close': float(row['close']),
            'datetime': row['datetime']
        })
    
    # 处理包含关系
    i = 0
    merged_bars = []
    
    # 确定初始方向
    if len(bars) >= 2:
        dir_up = bars[1]['high'] > bars[0]['high'] and bars[1]['low'] > bars[0]['low']
        direction = 'up' if dir_up else 'down'
        merged_bars.append(bars[0])
        i = 1
    else:
        return kline_df
    
    while i < len(bars):
        cur_bar = bars[i]
        last_bar = merged_bars[-1]
        
        # 检查是否有包含关系
        if (cur_bar['high'] <= last_bar['high'] and cur_bar['low'] >= last_bar['low']) or \
           (cur_bar['high'] >= last_bar['high'] and cur_bar['low'] <= last_bar['low']):
            # 有包含关系，合并
            if direction == 'up':
                # 向上笔：取高高
                new_high = max(last_bar['high'], cur_bar['high'])
                new_low = max(last_bar['low'], cur_bar['low']) if last_bar['high'] >= cur_bar['high'] else cur_bar['low']
                merged_bars[-1] = {
                    'high': new_high,
                    'low': new_low,
                    'open': last_bar['open'],  # 保留第一个K线的开盘
                    'close': cur_bar['close'],  # 保留最后一个K线的收盘
                    'datetime': last_bar['datetime']  # 保留第一个K线的时间
                }
            else:
                # 向下笔：取低低
                new_low = min(last_bar['low'], cur_bar['low'])
                new_high = min(last_bar['high'], cur_bar['high']) if last_bar['low'] <= cur_bar['low'] else cur_bar['high']
                merged_bars[-1] = {
                    'high': new_high,
                    'low': new_low,
                    'open': last_bar['open'],
                    'close': cur_bar['close'],
                    'datetime': last_bar['datetime']
                }
        else:
            # 无包含关系，添加新K线
            merged_bars.append(cur_bar)
            # 更新方向
            if i < len(bars) - 1:
                next_bar = bars[i+1]
                dir_up = next_bar['high'] > cur_bar['high'] and next_bar['low'] > cur_bar['low']
                direction = 'up' if dir_up else 'down'
        
        i += 1
    
    # 转换回DataFrame
    result_df = pd.DataFrame(merged_bars)
    return result_df

def find_fractals(kline_df):
    """
    在已处理包含关系的K线中寻找分型
    顶分型：中间K线高点最高，低点也相对高
    底分型：中间K线低点最低，高点也相对低
    """
    highs = kline_df['high'].values
    lows = kline_df['low'].values
    
    top_points = []  # 顶分型
    bottom_points = []  # 底分型
    
    for i in range(1, len(kline_df)-1):
        # 检查顶分型
        if (highs[i] > highs[i-1] and highs[i] > highs[i+1] and
            lows[i] > min(lows[i-1], lows[i+1])):
            top_points.append((i, highs[i], 'top'))
        
        # 检查底分型
        if (lows[i] < lows[i-1] and lows[i] < lows[i+1] and
            highs[i] < max(highs[i-1], highs[i+1])):
            bottom_points.append((i, lows[i], 'bottom'))
    
    # 合并并排序
    all_points = top_points + bottom_points
    all_points.sort(key=lambda x: x[0])
    
    return all_points

def detect_bi_from_fractals(kline_df, fractals):
    """
    从分型点检测笔
    """
    if len(fractals) < 2:
        return []
    
    bi_list = []
    i = 0
    
    # 找到第一个有效的分型对
    while i < len(fractals) - 1:
        idx1, price1, type1 = fractals[i]
        idx2, price2, type2 = fractals[i+1]
        
        # 确保交替：顶->底 或 底->顶
        if not ((type1 == 'top' and type2 == 'bottom') or 
                (type1 == 'bottom' and type2 == 'top')):
            i += 1
            continue
        
        # 检查笔的长度（至少5根原始K线，这里用处理后的K线索引近似）
        # 实际上需要检查原始K线数量，这里简化处理
        k_count = idx2 - idx1 + 1
        if k_count < 3:  # 处理后的K线较少，对应更多原始K线
            i += 1
            continue
        
        # 确定笔的方向和价格
        if type1 == 'bottom' and type2 == 'top':
            direction = 'up'
            start_price = price1
            end_price = price2
            
            # 获取笔内的实际最高最低
            segment = kline_df.iloc[idx1:idx2+1]
            bi_high = segment['high'].max()
            bi_low = segment['low'].min()
        else:
            direction = 'down'
            start_price = price1
            end_price = price2
            
            segment = kline_df.iloc[idx1:idx2+1]
            bi_high = segment['high'].max()
            bi_low = segment['low'].min()
        
        # 价格变化幅度检查（至少10点）
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
            'k_count': k_count,
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
    print(f"PTA缠论线段检测 v11 | {args.date}")
    print(f"{'='*50}\n")
    
    # 读取K线
    raw_df = parse_kline(args.date)
    print(f"[原始K线] {len(raw_df)}根")
    
    # 处理包含关系
    merged_df = handle_include_relationship(raw_df)
    print(f"[合并后K线] {len(merged_df)}根")
    
    # 寻找分型
    fractals = find_fractals(merged_df)
    print(f"[分型点] {len(fractals)}个")
    
    # 显示分型点
    for i, (idx, price, ftype) in enumerate(fractals[:10]):
        time = merged_df.iloc[idx]['datetime']
        print(f"  {ftype} at {time} price={price:.0f}")
    
    # 检测笔
    bi_list = detect_bi_from_fractals(merged_df, fractals)
    print(f"\n[笔] {len(bi_list)}条")
    
    for i, bi in enumerate(bi_list):
        print(f"  b{i+1} {bi['dir']:4s} [{bi['start_idx']+1}~{bi['end_idx']+1}] {bi['k_count']}K Δ{bi['change']:.0f}")
        print(f"    price: {bi['start_price']:.0f}→{bi['end_price']:.0f}  high={bi['high']:.0f} low={bi['low']:.0f}")
    
    # 简单线段检测（基于连续同向笔）
    if len(bi_list) >= 3:
        print(f"\n[简单线段检测]")
        seg_idx = 0
        i = 0
        while i < len(bi_list):
            # 找连续同向笔
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
    
    print(f"\n[预期] 4月3日应有16条笔，3条线段")
    print(f"       实际笔数: {len(bi_list)}")

if __name__ == '__main__':
    main()
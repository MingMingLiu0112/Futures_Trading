#!/usr/bin/env python3
"""
PTA缠论线段检测 - v29
基于chan_step1.py的算法，但去掉ATR阈值，严格按照缠论原始定义
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

def process_baohan_v2(kline_df):
    """
    处理K线包含关系（只用最高价最低价）
    上升趋势（最低价抬升）：当前low > 前一low → 高高原则 max(high) + max(low)
    下降趋势（最高价下降）：当前high < 前一high → 低低原则 min(high) + min(low)
    """
    rows = kline_df[['high', 'low']].values.tolist()
    result = []
    
    i = 0
    while i < len(rows):
        if len(result) == 0:
            result.append(rows[i])
            i += 1
            continue
        
        h1, l1 = result[-1]
        h2, l2 = rows[i]
        
        # 判断包含关系：h2在[h1,l1]内部 或 l2在[h1,l1]内部
        hasContain = (h2 <= h1 and l2 >= l1) or (h2 >= h1 and l2 <= l1)
        
        if not hasContain:
            result.append(rows[i])
            i += 1
            continue
        
        # 判断趋势：最低价抬升=上升，最高价下降=下降
        if l2 > l1:
            # 上升趋势 → 高高原则
            new_h = max(h1, h2)
            new_l = max(l1, l2)
        else:
            # 下降趋势 → 低低原则
            new_h = min(h1, h2)
            new_l = min(l1, l2)
        
        result[-1] = (new_h, new_l)
        i += 1
    
    return result

def find_fenxing(klist):
    """
    识别顶分型和底分型
    顶分型：连续三根K线，中间K线的最高价和最低价都分别高于左右两根
    底分型：连续三根K线，中间K线的最高价和最低价都分别低于左右两根
    返回分型列表 [(type, index, price), ...]
    """
    n = len(klist)
    fen = []
    
    for i in range(1, n - 1):
        h_prev, l_prev = klist[i - 1]
        h_curr, l_curr = klist[i]
        h_next, l_next = klist[i + 1]
        
        # 顶分型
        if h_curr > h_prev and h_curr > h_next and l_curr > l_prev and l_curr > l_next:
            fen.append(('top', i, h_curr))
        # 底分型
        elif h_curr < h_prev and h_curr < h_next and l_curr < l_prev and l_curr < l_next:
            fen.append(('bottom', i, l_curr))
    
    return fen

def build_bi_strict(fen_list, klist):
    """
    严格缠论笔构建（去掉ATR阈值）
    规则：
    - 底分型 + 顶分型 = 上行笔（up）
    - 顶分型 + 底分型 = 下行笔（down）
    - 标准笔：分型间至少4根K线
    返回笔列表 [(direction, start_idx, end_idx, start_price, end_price), ...]
    """
    if len(fen_list) < 2:
        return []
    
    result = []
    i = 0
    
    while i < len(fen_list) - 1:
        t_start, idx_start, price_start = fen_list[i]
        
        # 确定笔方向
        if t_start == 'bottom':
            direction = 'up'
            target_type = 'top'
        else:
            direction = 'down'
            target_type = 'bottom'
        
        # 寻找下一个目标分型
        j = i + 1
        while j < len(fen_list):
            t_check, idx_check, price_check = fen_list[j]
            
            if t_check == target_type:
                # 检查K线数量
                k_count = idx_check - idx_start + 1
                if k_count >= 4:
                    # 有效笔
                    result.append((direction, idx_start, idx_check, price_start, price_check))
                    i = j
                    break
                else:
                    # K线数量不足，继续寻找
                    j += 1
            else:
                j += 1
        else:
            # 没有找到合适的目标分型
            i += 1
    
    return result

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('date', nargs='?', default='2026-04-03')
    args = parser.parse_args()
    
    print(f"\n{'='*50}")
    print(f"PTA缠论线段检测 v29 | {args.date} | 严格缠论定义")
    print(f"{'='*50}\n")
    
    # 读取K线
    kline_df = parse_kline(args.date)
    print(f"[原始K线] {len(kline_df)}根")
    
    # 处理包含关系
    processed_klist = process_baohan_v2(kline_df)
    print(f"[处理后K线] {len(processed_klist)}根")
    
    # 识别分型
    fen_list = find_fenxing(processed_klist)
    print(f"[分型] {len(fen_list)}个")
    
    # 显示关键分型
    print(f"\n[关键分型] (价格接近预期点):")
    for f in fen_list:
        f_type, f_idx, f_price = f
        if f_type == 'bottom' and abs(f_price - 6726) < 30:
            print(f"  bottom at idx={f_idx} price={f_price}")
        elif f_type == 'top' and abs(f_price - 6922) < 30:
            print(f"  top at idx={f_idx} price={f_price}")
        elif f_type == 'bottom' and abs(f_price - 6810) < 30:
            print(f"  bottom at idx={f_idx} price={f_price}")
        elif f_type == 'top' and abs(f_price - 6948) < 30:
            print(f"  top at idx={f_idx} price={f_price}")
    
    # 构建笔
    bi_list = build_bi_strict(fen_list, processed_klist)
    print(f"\n[笔] {len(bi_list)}条")
    
    # 显示所有笔
    for i, bi in enumerate(bi_list):
        direction, start_idx, end_idx, start_price, end_price = bi
        k_count = end_idx - start_idx + 1
        change = end_price - start_price if direction == 'up' else start_price - end_price
        print(f"  b{i+1} {direction:4s} [{start_idx+1}~{end_idx+1}] {k_count}K Δ{change:.0f}")
        print(f"    price: {start_price:.0f}→{end_price:.0f}")
    
    # 匹配预期笔
    print(f"\n[与预期笔匹配]")
    expected = [
        (1, 'up', 6726, 6922),
        (4, 'down', 6922, 6810),
        (7, 'up', 6810, 6948)
    ]
    
    matches = 0
    for exp_idx, exp_dir, exp_start, exp_end in expected:
        found = False
        for bi in bi_list:
            direction, start_idx, end_idx, start_price, end_price = bi
            if direction == exp_dir:
                start_diff = abs(start_price - exp_start)
                end_diff = abs(end_price - exp_end)
                if start_diff < 30 and end_diff < 30:
                    print(f"  b{exp_idx} {exp_dir} {exp_start}→{exp_end}")
                    print(f"    匹配: b{bi_list.index(bi)+1} {direction} {start_price:.0f}→{end_price:.0f}")
                    matches += 1
                    found = True
                    break
        
        if not found:
            print(f"  b{exp_idx} {exp_dir} {exp_start}→{exp_end} - 未匹配")
    
    print(f"\n[统计] 笔数: {len(bi_list)} (期望: 16)")
    print(f"       关键笔匹配: {matches}/3")
    
    # 线段检测（简化）
    if len(bi_list) >= 3:
        print(f"\n[线段检测（简化）]")
        xd_count = 0
        i = 0
        while i < len(bi_list):
            seg_dir = bi_list[i][0]
            seg_start = i
            while i < len(bi_list) and bi_list[i][0] == seg_dir:
                i += 1
            seg_end = i - 1
            seg_len = seg_end - seg_start + 1
            
            if seg_len >= 3:
                xd_count += 1
                print(f"  XD{xd_count} {seg_dir} b{seg_start+1}~b{seg_end+1} ({seg_len}笔)")
        
        print(f"\n[线段] {xd_count}条 (期望: 3)")

if __name__ == '__main__':
    main()
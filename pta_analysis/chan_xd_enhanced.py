#!/usr/bin/env python3
"""
缠论算法增强版：改进的线段检测算法
基于缠论108课标准定义，实现更准确的线段检测
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from typing import List, Tuple, Dict, Any
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# 1. 数据获取（复用之前的代码）
# ============================================================================

def get_sample_data() -> pd.DataFrame:
    np.random.seed(42)
    n = 200
    base = 6000
    trend = np.cumsum(np.random.randn(n) * 2)
    noise = np.random.randn(n) * 10
    
    prices = base + trend + noise
    prices = np.maximum(prices, 5800)
    prices = np.minimum(prices, 6200)
    
    opens = prices[:-1]
    closes = prices[1:]
    highs = np.maximum(opens, closes) + np.random.rand(n-1) * 5
    lows = np.minimum(opens, closes) - np.random.rand(n-1) * 5
    
    highs = np.maximum(highs, lows + 1)
    
    df = pd.DataFrame({
        'datetime': pd.date_range('2026-04-08 09:00', periods=n-1, freq='1min'),
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes
    })
    
    return df

def process_containment(klines: pd.DataFrame) -> List[Tuple[float, float]]:
    rows = klines[['high', 'low']].values.tolist()
    if not rows:
        return []
    
    result = []
    
    for i in range(len(rows)):
        if not result:
            result.append(rows[i])
            continue
            
        h1, l1 = result[-1]
        h2, l2 = rows[i]
        
        is_contained = (h2 <= h1 and l2 >= l1) or (h2 >= h1 and l2 <= l1)
        
        if not is_contained:
            result.append(rows[i])
            continue
            
        if l2 > l1:
            new_h = max(h1, h2)
            new_l = max(l1, l2)
        else:
            new_h = min(h1, h2)
            new_l = min(l1, l2)
            
        result[-1] = (new_h, new_l)
    
    return result

def find_fractals(klist: List[Tuple[float, float]]) -> List[Tuple[str, int, float]]:
    n = len(klist)
    if n < 3:
        return []
    
    fractals = []
    
    for i in range(1, n - 1):
        h_prev, l_prev = klist[i - 1]
        h_curr, l_curr = klist[i]
        h_next, l_next = klist[i + 1]
        
        if (h_curr > h_prev and h_curr > h_next and 
            l_curr > l_prev and l_curr > l_next):
            fractals.append(('top', i, h_curr))
        
        elif (h_curr < h_prev and h_curr < h_next and 
              l_curr < l_prev and l_curr < l_next):
            fractals.append(('bottom', i, l_curr))
    
    filtered = []
    for i in range(len(fractals)):
        if i == 0:
            filtered.append(fractals[i])
        else:
            prev_idx = fractals[i-1][1]
            curr_idx = fractals[i][1]
            if curr_idx - prev_idx >= 2:
                filtered.append(fractals[i])
    
    return filtered

def build_strokes(fractals: List[Tuple[str, int, float]], 
                  klist: List[Tuple[float, float]],
                  min_k_bars: int = 4,
                  min_price_range: float = 30.0) -> List[Tuple[str, int, int, float, float, bool]]:
    if len(fractals) < 2:
        return []
    
    strokes = []
    i = 0
    
    while i < len(fractals) - 1:
        ftype1, idx1, price1 = fractals[i]
        
        if ftype1 == 'bottom':
            direction = 'up'
            target_type = 'top'
        else:
            direction = 'down'
            target_type = 'bottom'
        
        found = False
        for j in range(i + 1, len(fractals)):
            ftype2, idx2, price2 = fractals[j]
            
            if ftype2 != target_type:
                continue
            
            k_gap = idx2 - idx1
            price_range = abs(price2 - price1)
            
            if k_gap >= min_k_bars:
                strokes.append((direction, idx1, idx2, price1, price2, False))
                i = j
                found = True
                break
            elif price_range >= min_price_range:
                strokes.append((direction, idx1, idx2, price1, price2, True))
                i = j
                found = True
                break
        
        if not found:
            i += 1
    
    return strokes

# ============================================================================
# 2. 增强版线段检测算法
# ============================================================================

def build_segments_enhanced(strokes: List[Tuple[str, int, int, float, float, bool]]) -> List[Tuple[str, int, int, float, float, List[int]]]:
    """
    增强版线段检测算法
    基于缠论线段定义：
    1. 线段至少由3笔构成
    2. 线段破坏：特征序列分型
    3. 线段延伸：同方向笔不断创新高/新低
    4. 线段结束：出现特征序列顶底分型
    """
    if len(strokes) < 3:
        return []
    
    segments = []
    i = 0
    
    while i <= len(strokes) - 3:
        # 尝试构建线段
        segment = _try_build_segment(strokes, i)
        
        if segment:
            segments.append(segment)
            # 跳到线段结束后的位置
            stroke_indices = segment[5]
            i = stroke_indices[-1] + 1
        else:
            i += 1
    
    return segments

def _try_build_segment(strokes: List[Tuple[str, int, int, float, float, bool]], start_idx: int) -> Tuple[str, int, int, float, float, List[int]]:
    """
    尝试从指定位置开始构建线段
    """
    if start_idx > len(strokes) - 3:
        return None
    
    # 获取前三笔
    s1 = strokes[start_idx]
    s2 = strokes[start_idx + 1]
    s3 = strokes[start_idx + 2]
    
    dir1, idx1_s, idx1_e, price1_s, price1_e, _ = s1
    dir2, idx2_s, idx2_e, price2_s, price2_e, _ = s2
    dir3, idx3_s, idx3_e, price3_s, price3_e, _ = s3
    
    # 检查是否满足线段起始条件
    if dir1 == 'up' and dir2 == 'down' and dir3 == 'up':
        # 潜在上行线段
        if price2_e > price1_e and price3_e > price2_e:
            return _extend_up_segment(strokes, start_idx)
    
    elif dir1 == 'down' and dir2 == 'up' and dir3 == 'down':
        # 潜在下行线段
        if price2_e < price1_e and price3_e < price2_e:
            return _extend_down_segment(strokes, start_idx)
    
    return None

def _extend_up_segment(strokes: List[Tuple[str, int, int, float, float, bool]], start_idx: int) -> Tuple[str, int, int, float, float, List[int]]:
    """
    延伸上行线段
    """
    segment_dir = 'up'
    stroke_indices = [start_idx, start_idx + 1, start_idx + 2]
    
    # 获取初始线段信息
    s1 = strokes[start_idx]
    s3 = strokes[start_idx + 2]
    segment_start_idx = s1[1]
    segment_start_price = s1[3]
    segment_end_idx = s3[2]
    segment_end_price = s3[4]
    
    # 特征序列（对于上行线段，特征序列是向下笔的终点）
    feature_sequence = []
    
    # 添加前两个特征点
    s2 = strokes[start_idx + 1]
    feature_sequence.append(s2[4])  # 第一个向下笔的终点（低点）
    
    # 延伸线段
    i = start_idx + 3
    while i < len(strokes):
        current_stroke = strokes[i]
        dir_current, _, idx_current_e, _, price_current_e, _ = current_stroke
        
        if dir_current == 'up':
            # 同方向笔，检查是否创新高
            if price_current_e > segment_end_price:
                # 更新线段终点
                segment_end_idx = idx_current_e
                segment_end_price = price_current_e
                stroke_indices.append(i)
                i += 1
            else:
                # 不再创新高，检查特征序列
                if i + 1 < len(strokes):
                    next_stroke = strokes[i + 1]
                    if next_stroke[0] == 'down':
                        feature_sequence.append(next_stroke[4])
                        
                        # 检查特征序列是否形成顶分型
                        if len(feature_sequence) >= 3:
                            last_three = feature_sequence[-3:]
                            if (last_three[1] > last_three[0] and 
                                last_three[1] > last_three[2]):
                                # 特征序列顶分型，线段结束
                                break
                
                i += 1
        else:
            # 向下笔，添加到特征序列
            feature_sequence.append(price_current_e)
            stroke_indices.append(i)
            i += 1
    
    return (segment_dir, segment_start_idx, segment_end_idx,
            segment_start_price, segment_end_price, stroke_indices)

def _extend_down_segment(strokes: List[Tuple[str, int, int, float, float, bool]], start_idx: int) -> Tuple[str, int, int, float, float, List[int]]:
    """
    延伸下行线段
    """
    segment_dir = 'down'
    stroke_indices = [start_idx, start_idx + 1, start_idx + 2]
    
    # 获取初始线段信息
    s1 = strokes[start_idx]
    s3 = strokes[start_idx + 2]
    segment_start_idx = s1[1]
    segment_start_price = s1[3]
    segment_end_idx = s3[2]
    segment_end_price = s3[4]
    
    # 特征序列（对于下行线段，特征序列是向上笔的终点）
    feature_sequence = []
    
    # 添加前两个特征点
    s2 = strokes[start_idx + 1]
    feature_sequence.append(s2[4])  # 第一个向上笔的终点（高点）
    
    # 延伸线段
    i = start_idx + 3
    while i < len(strokes):
        current_stroke = strokes[i]
        dir_current, _, idx_current_e, _, price_current_e, _ = current_stroke
        
        if dir_current == 'down':
            # 同方向笔，检查是否创新低
            if price_current_e < segment_end_price:
                # 更新线段终点
                segment_end_idx = idx_current_e
                segment_end_price = price_current_e
                stroke_indices.append(i)
                i += 1
            else:
                # 不再创新低，检查特征序列
                if i + 1 < len(strokes):
                    next_stroke = strokes[i + 1]
                    if next_stroke[0] == 'up':
                        feature_sequence.append(next_stroke[4])
                        
                        # 检查特征序列是否形成底分型
                        if len(feature_sequence) >= 3:
                            last_three = feature_sequence[-3:]
                            if (last_three[1] < last_three[0] and 
                                last_three[1] < last_three[2]):
                                # 特征序列底分型，线段结束
                                break
                
                i += 1
        else:
            # 向上笔，添加到特征序列
            feature_sequence.append(price_current_e)
            stroke_indices.append(i)
            i += 1
    
    return (segment_dir, segment_start_idx, segment_end_idx,
            segment_start_price, segment_end_price, stroke_indices)

# ============================================================================
# 3. 可视化
# ============================================================================

def visualize_enhanced(klines: pd.DataFrame,
                      processed_k: List[Tuple[float, float]],
                      fractals: List[Tuple[str, int, float]],
                      strokes: List[Tuple[str, int, int, float, float, bool]],
                      segments: List[Tuple[str, int, int, float, float, List[int]]],
                      output_path: str = 'chan_enhanced.png'):
    """
    可视化增强版分析结果
    """
    plt.style.use('dark_background')
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10), height_ratios=[2, 1])
    
    # 子图1：K线 + 分型 + 笔 + 线段
    for idx, row in klines.iterrows():
        color = '#e54d4d' if row['close'] >= row['open'] else '#4da64d'
        ax1.plot([idx, idx], [row['low'], row['high']], color=color, linewidth=0.8)
        body_bottom = min(row['open'], row['close'])
        body_top = max(row['open'], row['close'])
        ax1.add_patch(mpatches.Rectangle((idx-0.4, body_bottom), 0.8, body_top-body_bottom,
                                        facecolor=color, edgecolor=color, linewidth=0.5))
    
    # 绘制分型
    for ftype, idx, price in fractals:
        color = '#ffff00' if ftype == 'top' else '#00ffcc'
        marker = 'v' if ftype == 'top' else '^'
        ax1.scatter(idx, price, color=color, s=60, marker=marker, zorder=5)
    
    # 绘制笔
    for stroke in strokes:
        direction, start_idx, end_idx, start_price, end_price, is_small = stroke
        color = '#ff6b35' if direction == 'up' else '#35a7ff'
        linewidth = 1.5 if is_small else 3.0
        linestyle = '--' if is_small else '-'
        ax1.plot([start_idx, end_idx], [start_price, end_price], 
                color=color, linewidth=linewidth, linestyle=linestyle, alpha=0.9)
    
    # 绘制线段（用更粗的线）
    for segment in segments:
        direction, start_idx, end_idx, start_price, end_price, stroke_indices = segment
        color = '#ff1493' if direction == 'up' else '#00ced1'
        ax1.plot([start_idx, end_idx], [start_price, end_price], 
                color=color, linewidth=5, alpha=0.7, linestyle='-')
        
        # 标记线段包含的笔
        for stroke_idx in stroke_indices:
            if stroke_idx < len(strokes):
                stroke = strokes[stroke_idx]
                _, s_idx, e_idx, s_price, e_price, _ = stroke
                ax1.scatter([s_idx, e_idx], [s_price, e_price], 
                          color=color, s=30, zorder=10)
    
    ax1.set_title('缠论增强版分析：K线 + 分型 + 笔 + 线段', color='white', fontsize=14, pad=12)
    ax1.set_xlabel('K线序号', color='white')
    ax1.set_ylabel('价格', color='white')
    ax1.grid(True, alpha=0.2)
    
    # 创建图例
    legend_elements = [
        mpatches.Patch(color='#ff6b35', label='上行笔'),
        mpatches.Patch(color='#35a7ff', label='下行笔'),
        mpatches.Patch(color='#ff1493', label='上行线段'),
        mpatches.Patch(color='#00ced1', label='下行线段'),
        plt.Line2D([0], [0], marker='v', color='w', markerfacecolor='#ffff00', markersize=8, label='顶分型'),
        plt.Line2D([0], [0], marker='^', color='w', markerfacecolor='#00ffcc', markersize=8, label='底分型')
    ]
    ax1.legend(handles=legend_elements, loc='upper left', fontsize=9)
    
    # 子图2：价格走势
    ax2.plot(klines.index, klines['close'], color='white', linewidth=1.5, alpha=0.7, label='收盘价')
    
    # 标记线段转折点
    for segment in segments:
        direction, start_idx, end_idx, start_price, end_price, _ = segment
        color = '#ff1493' if direction == 'up' else '#00ced1'
        ax2.scatter([start_idx, end_idx], [start_price, end_price], 
                   color=color, s=50, zorder=10)
    
    ax2.set_title('收盘价走势与线段转折点', color='white', fontsize=12, pad=10)
    ax2.set_xlabel('K线序号', color='white')
    ax2.set_ylabel('价格', color='white')
    ax2.grid(True, alpha=0.2)
    ax2.legend(loc='upper left')
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=120, bbox_inches='tight')
    print(f"增强版可视化结果已保存到: {output_path}")

# ============================================================================
# 4. 测试和主程序
# ============================================================================

def run_enhanced_test():
    """
    运行增强版测试
    """
    print("=" * 60)
    print("缠论增强版算法测试")
    print("=" * 60)
    
    # 获取数据
    print("\n1. 获取数据...")
    data = get_sample_data()
    print(f"   数据量: {len(data)} 根K线")
    
    # 处理包含关系
    print("\n2. 处理包含关系...")
    processed_k = process_containment(data)
    print(f"   原始K线: {len(data)} 根")
    print(f"   处理后K线: {len(processed_k)} 根")
    
    # 识别分型
    print("\n3. 识别分型...")
    fractals = find_fractals(processed_k)
    print(f"   找到 {len(fractals)} 个分型")
    
    # 构建笔
    print("\n4. 构建笔...")
    strokes = build_strokes(fractals, processed_k, min_k_bars=4, min_price_range=30.0)
    print(f"   找到 {len(strokes)} 笔")
    print(f"   上行笔: {sum(1 for s in strokes if s[0] == 'up')}")
    print(f"   下行笔: {sum(1 for s in strokes if s[0] == 'down')}")
    
    # 构建线段（增强版）
    print("\n5. 构建线段（增强版）...")
    segments = build_segments_enhanced(strokes)
    print(f"   找到 {len(segments)} 个线段")
    
    if segments:
        print("\n   线段详情:")
        for i, segment in enumerate(segments):
            direction, start_idx, end_idx, start_price, end_price, stroke_indices = segment
            arrow = "↗" if direction == 'up' else "↘"
            price_range = abs(end_price - start_price)
            k_gap = end_idx - start_idx
            stroke_count = len(stroke_indices)
            print(f"     线段{i+1}: {arrow} {start_price:.1f}→{end_price:.1f} "
                  f"(幅度:{price_range:.1f}, K线:{k_gap}根, 包含{stroke_count}笔)")
    
    # 可视化
    print("\n6. 生成可视化图表...")
    visualize_enhanced(data, processed_k, fractals, strokes, segments, 'chan_enhanced_analysis.png')
    
    print("\n" + "=" * 60)
    print("增强版测试完成！")
    print("=" * 60)
    
    return {
        'data': data,
        'processed_k': processed_k,
        'fractals': fractals,
        'strokes': strokes,
        'segments': segments
    }

def main():
    """
    主函数
    """
    print("缠论算法增强版实现")
    print("=" * 50)
    
    results = run_enhanced_test()
    
    # 分析报告
    print("\n分析报告:")
    print("-" * 40)
    
    strokes = results['strokes']
    segments = results['segments']
    
    print(f"笔统计:")
    print(f"  总数: {len(strokes)}")
    print(f"  上行笔: {sum(1 for s in strokes if s[0] == 'up')}")
    print(f"  下行笔: {sum(1 for s in strokes if s[0] == 'down')}")
    print(f"  小笔: {sum(1 for s in strokes if s[5])}")
    
    print(f"\n线段统计:")
    print(f"  总数: {len(segments)}")
    
    if segments:
        # 计算线段特征
        segment_directions = [s[0] for s in segments]
        segment_lengths = [abs(s[4] - s[3]) for s in segments]
        segment_stroke_counts = [len(s[5]) for s in segments]
        
        print(f"  上行线段: {segment_directions.count('up')}")
        print(f"  下行线段: {segment_directions.count('down')}")
        print(f"  平均幅度: {np.mean(segment_lengths):.1f}")
        print(f"  平均包含笔数: {np.mean(segment_stroke_counts):.1f}")
        
        # 趋势分析
        if len(segments) >= 2:
            last_segment = segments[-1]
            prev_segment = segments[-2]
            
            print(f"\n趋势分析:")
            print(f"  最新线段方向: {'上行' if last_segment[0] == 'up' else '下行'}")
            print(f"  前一线段方向: {'上行' if prev_segment[0] == 'up' else '下行'}")
            
            if last_segment[0] == prev_segment[0]:
                print(f"  趋势状态: 延续")
            else:
                print(f"  趋势状态: 反转")
    
    print("\n" + "=" * 50)
    print("分析完成！图表已保存为 'chan_enhanced_analysis.png'")

if __name__ == "__main__":
    main()
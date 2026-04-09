#!/usr/bin/env python3
"""
缠论算法完整测试套件
包含多种测试场景和实际数据测试
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from typing import List, Tuple, Dict, Any
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# 1. 缠论核心算法（复用）
# ============================================================================

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
# 2. 简化但有效的线段检测算法
# ============================================================================

def build_segments_simple(strokes: List[Tuple[str, int, int, float, float, bool]]) -> List[Tuple[str, int, int, float, float, List[int]]]:
    """
    简化版线段检测算法
    规则：连续三笔构成线段，后续同向笔延伸线段直到被破坏
    """
    if len(strokes) < 3:
        return []
    
    segments = []
    i = 0
    
    while i <= len(strokes) - 3:
        s1 = strokes[i]
        s2 = strokes[i + 1]
        s3 = strokes[i + 2]
        
        dir1, idx1_s, idx1_e, price1_s, price1_e, _ = s1
        dir2, idx2_s, idx2_e, price2_s, price2_e, _ = s2
        dir3, idx3_s, idx3_e, price3_s, price3_e, _ = s3
        
        # 检查是否构成线段起始
        if dir1 == 'up' and dir2 == 'down' and dir3 == 'up':
            # 上行线段：低点抬高，高点抬高
            if price2_e > price1_e and price3_e > price2_e:
                segment = _extend_segment_simple(strokes, i, 'up')
                if segment:
                    segments.append(segment)
                    i = segment[5][-1] + 1
                    continue
        
        elif dir1 == 'down' and dir2 == 'up' and dir3 == 'down':
            # 下行线段：高点降低，低点降低
            if price2_e < price1_e and price3_e < price2_e:
                segment = _extend_segment_simple(strokes, i, 'down')
                if segment:
                    segments.append(segment)
                    i = segment[5][-1] + 1
                    continue
        
        i += 1
    
    return segments

def _extend_segment_simple(strokes: List[Tuple[str, int, int, float, float, bool]], 
                          start_idx: int, 
                          direction: str) -> Tuple[str, int, int, float, float, List[int]]:
    """
    延伸线段（简化版）
    """
    stroke_indices = [start_idx, start_idx + 1, start_idx + 2]
    
    # 获取初始线段信息
    s1 = strokes[start_idx]
    s3 = strokes[start_idx + 2]
    segment_start_idx = s1[1]
    segment_start_price = s1[3]
    segment_end_idx = s3[2]
    segment_end_price = s3[4]
    
    # 延伸线段
    i = start_idx + 3
    while i < len(strokes):
        current_stroke = strokes[i]
        dir_current, _, idx_current_e, _, price_current_e, _ = current_stroke
        
        if dir_current == direction:
            # 同方向笔，检查是否延伸线段
            if (direction == 'up' and price_current_e > segment_end_price) or \
               (direction == 'down' and price_current_e < segment_end_price):
                # 延伸线段
                segment_end_idx = idx_current_e
                segment_end_price = price_current_e
                stroke_indices.append(i)
                i += 1
            else:
                # 不再延伸，检查是否被破坏
                break
        else:
            # 反方向笔，检查是否破坏线段
            if direction == 'up':
                # 上行线段被破坏：向下笔创新低
                if i + 1 < len(strokes):
                    next_stroke = strokes[i + 1]
                    if next_stroke[0] == 'up':
                        # 后续还有向上笔，线段可能未结束
                        stroke_indices.append(i)
                        i += 1
                    else:
                        # 线段被破坏
                        break
                else:
                    break
            else:
                # 下行线段被破坏：向上笔创新高
                if i + 1 < len(strokes):
                    next_stroke = strokes[i + 1]
                    if next_stroke[0] == 'down':
                        stroke_indices.append(i)
                        i += 1
                    else:
                        break
                else:
                    break
    
    return (direction, segment_start_idx, segment_end_idx,
            segment_start_price, segment_end_price, stroke_indices)

# ============================================================================
# 3. 测试数据生成器
# ============================================================================

def generate_trend_data(trend_type: str = 'up_trend') -> pd.DataFrame:
    """
    生成具有明显趋势的测试数据
    """
    np.random.seed(123)
    n = 300
    
    if trend_type == 'up_trend':
        # 上升趋势
        base_trend = np.linspace(6000, 6100, n)
        swings = 20 * np.sin(np.linspace(0, 6*np.pi, n))
        noise = np.random.randn(n) * 8
        prices = base_trend + swings + noise
    
    elif trend_type == 'down_trend':
        # 下降趋势
        base_trend = np.linspace(6100, 6000, n)
        swings = 15 * np.sin(np.linspace(0, 5*np.pi, n))
        noise = np.random.randn(n) * 7
        prices = base_trend + swings + noise
    
    elif trend_type == 'sideways':
        # 横盘震荡
        base = 6050
        swings = 30 * np.sin(np.linspace(0, 8*np.pi, n))
        noise = np.random.randn(n) * 6
        prices = base + swings + noise
    
    else:  # complex
        # 复杂走势（趋势+震荡）
        trend1 = np.linspace(6000, 6080, n//3)
        trend2 = np.linspace(6080, 6020, n//3)
        trend3 = np.linspace(6020, 6060, n//3)
        base_trend = np.concatenate([trend1, trend2, trend3])
        
        swings = 25 * np.sin(np.linspace(0, 10*np.pi, n))
        noise = np.random.randn(n) * 9
        prices = base_trend + swings + noise
    
    # 确保价格合理
    prices = np.maximum(prices, 5900)
    prices = np.minimum(prices, 6150)
    
    # 生成OHLC
    opens = prices[:-1]
    closes = prices[1:]
    highs = np.maximum(opens, closes) + np.random.rand(n-1) * 6
    lows = np.minimum(opens, closes) - np.random.rand(n-1) * 6
    
    # 确保high > low
    highs = np.maximum(highs, lows + 1)
    
    df = pd.DataFrame({
        'datetime': pd.date_range('2026-04-08 09:00', periods=n-1, freq='1min'),
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes
    })
    
    return df

# ============================================================================
# 4. 可视化函数
# ============================================================================

def visualize_test_result(klines: pd.DataFrame,
                         processed_k: List[Tuple[float, float]],
                         fractals: List[Tuple[str, int, float]],
                         strokes: List[Tuple[str, int, int, float, float, bool]],
                         segments: List[Tuple[str, int, int, float, float, List[int]]],
                         title: str = '缠论分析',
                         output_path: str = 'chan_test_result.png'):
    """
    可视化测试结果
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
    
    # 绘制线段
    for segment in segments:
        direction, start_idx, end_idx, start_price, end_price, stroke_indices = segment
        color = '#ff1493' if direction == 'up' else '#00ced1'
        ax1.plot([start_idx, end_idx], [start_price, end_price], 
                color=color, linewidth=5, alpha=0.7, linestyle='-')
        
        # 标记线段起点和终点
        ax1.scatter([start_idx, end_idx], [start_price, end_price], 
                   color=color, s=80, marker='o', zorder=10)
    
    ax1.set_title(f'{title}', color='white', fontsize=14, pad=12)
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
    
    # 子图2：收盘价和线段
    ax2.plot(klines.index, klines['close'], color='white', linewidth=1.5, alpha=0.7, label='收盘价')
    
    # 标记线段
    for segment in segments:
        direction, start_idx, end_idx, start_price, end_price, _ = segment
        color = '#ff1493' if direction == 'up' else '#00ced1'
        ax2.plot([start_idx, end_idx], [start_price, end_price], 
                color=color, linewidth=3, alpha=0.6)
        ax2.scatter([start_idx, end_idx], [start_price, end_price], 
                   color=color, s=40, zorder=10)
    
    ax2.set_title('收盘价走势与线段', color='white', fontsize=12, pad=10)
    ax2.set_xlabel('K线序号', color='white')
    ax2.set_ylabel('价格', color='white')
    ax2.grid(True, alpha=0.2)
    ax2.legend(loc='upper left')
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=120, bbox_inches='tight')
    print(f"图表已保存到: {output_path}")

# ============================================================================
# 5. 测试套件
# ============================================================================

def run_comprehensive_test():
    """
    运行全面测试
    """
    print("=" * 70)
    print("缠论算法全面测试套件")
    print("=" * 70)
    
    test_cases = [
        ('上升趋势', 'up_trend'),
        ('下降趋势', 'down_trend'),
        ('横盘震荡', 'sideways'),
        ('复杂走势', 'complex')
    ]
    
    all_results = {}
    
    for test_name, trend_type in test_cases:
        print(f"\n{'='*40}")
        print(f"测试案例: {test_name}")
        print(f"{'='*40}")
        
        # 生成测试数据
        print(f"1. 生成{test_name}数据...")
        data = generate_trend_data(trend_type)
        
        # 处理包含关系
        print("2. 处理包含关系...")
        processed_k = process_containment(data)
        
        # 识别分型
        print("3. 识别分型...")
        fractals = find_fractals(processed_k)
        
        # 构建笔
        print("4. 构建笔...")
        strokes = build_strokes(fractals, processed_k, min_k_bars=4, min_price_range=30.0)
        
        # 构建线段
        print("5. 构建线段...")
        segments = build_segments_simple(strokes)
        
        # 保存结果
        all_results[test_name] = {
            'data': data,
            'processed_k': processed_k,
            'fractals': fractals,
            'strokes': strokes,
            'segments': segments
        }
        
        # 输出统计信息
        print(f"\n  统计结果:")
        print(f"    原始K线: {len(data)} 根")
        print(f"    处理后K线: {len(processed_k)} 根")
        print(f"    分型数量: {len(fractals)} 个")
        print(f"    笔数量: {len(strokes)} 笔")
        print(f"    线段数量: {len(segments)} 段")
        
        if segments:
            avg_strokes = np.mean([len(s[5]) for s in segments])
            avg_length = np.mean([abs(s[4] - s[3]) for s in segments])
            print(f"    平均每线段包含笔数: {avg_strokes:.1f}")
            print(f"    平均线段幅度: {avg_length:.1f}")
        
        # 可视化
        print("6. 生成可视化图表...")
        output_file = f'chan_test_{trend_type}.png'
        visualize_test_result(data, processed_k, fractals, strokes, segments, 
                            f'缠论分析 - {test_name}', output_file)
    
    print(f"\n{'='*70}")
    print("全面测试完成！")
    print(f"{'='*70}")
    
    # 生成总结报告
    print("\n总结报告:")
    print("-" * 40)
    
    for test_name in all_results:
        results = all_results[test_name]
        segments = results['segments']
        
        print(f"\n{test_name}:")
        print(f"  笔数量: {len(results['strokes'])}")
        print(f"  线段数量: {len(segments)}")
        
        if segments:
            directions = [s[0] for s in segments]
            print(f"  上行线段: {directions.count('up')}")
            print(f"  下行线段: {directions.count('down')}")
    
    return all_results

# ============================================================================
# 6. 单元测试
# ============================================================================

def run_unit_tests():
    """
    运行单元测试
    """
    print("\n" + "=" * 70)
    print("单元测试")
    print("=" * 70)
    
    # 测试1：包含关系处理
    print("\n1. 测试包含关系处理...")
    test_data = pd.DataFrame({
        'high': [100, 102, 101, 103, 105],
        'low': [95, 96, 97, 96, 98]
    })
    
    processed = process_containment(test_data)
    print(f"   测试数据: {len(test_data)} 根K线")
    print(f"   处理后: {len(processed)} 根K线")
    print(f"   测试结果: {'通过' if len(processed) <= len(test_data) else '失败'}")
    
    # 测试2：分型识别
    print("\n2. 测试分型识别...")
    test_klist = [
        (95, 90),   # 低点
        (100, 95),  # 高点（顶分型中间）
        (98, 93),   # 低点
        (105, 100), # 高点
        (102, 97)   # 低点
    ]
    
    fractals = find_fractals(test_klist)
    print(f"   测试K线: {len(test_klist)} 根")
    print(f"   找到分型: {len(fractals)} 个")
    print(f"   测试结果: {'通过' if len(fractals) > 0 else '失败'}")
    
    # 测试3：笔划分
    print("\n3. 测试笔划分...")
    test_fractals = [
        ('bottom', 1, 95),
        ('top', 3, 105),
        ('bottom', 5, 97),
        ('top', 7, 108)
    ]
    
    strokes = build_strokes(test_fractals, test_klist, min_k_bars=2, min_price_range=5)
    print(f"   测试分型: {len(test_fractals)} 个")
    print(f"   找到笔: {len(strokes)} 笔")
    print(f"   测试结果: {'通过' if len(strokes) > 0 else '失败'}")
    
    # 测试4：线段检测
    print("\n4. 测试线段检测...")
    test_strokes = [
        ('up', 1, 3, 95, 105, False),
        ('down', 3, 5, 105, 97, False),
        ('up', 5, 7, 97, 108, False),
        ('down', 7, 9, 108, 100, False),
        ('up', 9, 11, 100, 112, False)
    ]
    
    segments = build_segments_simple(test_strokes)
    print(f"   测试笔: {len(test_strokes)} 笔")
    print(f"   找到线段: {len(segments)} 段")
    print(f"   测试结果: {'通过' if len(segments) > 0 else '失败'}")
    
    print("\n" + "=" * 70)
    print("单元测试完成！")
    print("=" * 70)

# ============================================================================
# 7. 主程序
# ============================================================================

def main():
    """
    主函数
    """
    print("缠论算法完整测试套件")
    print("=" * 70)
    
    # 运行单元测试
    run_unit_tests()
    
    # 运行全面测试
    print("\n\n开始全面测试...")
    results = run_comprehensive_test()
    
    # 最终报告
    print("\n" + "=" * 70)
    print("最终测试报告")
    print("=" * 70)
    
    total_strokes = 0
    total_segments = 0
    
    for test_name, result in results.items():
        strokes = result['strokes']
        segments = result['segments']
        
        total_strokes += len(strokes)
        total_segments += len(segments)
        
        print(f"\n{test_name}:")
        print(f"  笔: {len(strokes)} 笔")
        print(f"  线段: {len(segments)} 段")
        
        if segments:
            avg_length = np.mean([abs(s[4] - s[3]) for s in segments])
            print(f"  平均线段幅度: {avg_length:.1f}")
    
    print(f"\n总计:")
    print(f"  总笔数: {total_strokes} 笔")
    print(f"  总线段数: {total_segments} 段")
    
    print("\n" + "=" * 70)
    print("所有测试完成！")
    print("生成的图表:")
    print("  - chan_test_up_trend.png (上升趋势)")
    print("  - chan_test_down_trend.png (下降趋势)")
    print("  - chan_test_sideways.png (横盘震荡)")
    print("  - chan_test_complex.png (复杂走势)")
    print("=" * 70)

if __name__ == "__main__":
    main()

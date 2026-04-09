#!/usr/bin/env python3
"""
缠论算法完整实现：笔划分和线段检测
基于缠论108课标准定义：
1. 包含关系处理
2. 顶底分型识别
3. 笔划分（标准笔、小笔）
4. 线段检测（线段破坏规则）
5. 可视化输出
6. 测试用例
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from typing import List, Tuple, Dict, Any
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# 1. 数据获取模块
# ============================================================================

def get_sample_data() -> pd.DataFrame:
    """
    获取示例数据（模拟PTA期货1分钟K线）
    返回包含datetime, open, high, low, close的DataFrame
    """
    # 创建模拟数据
    np.random.seed(42)
    n = 200
    base = 6000
    trend = np.cumsum(np.random.randn(n) * 2)
    noise = np.random.randn(n) * 10
    
    prices = base + trend + noise
    prices = np.maximum(prices, 5800)
    prices = np.minimum(prices, 6200)
    
    # 生成OHLC
    opens = prices[:-1]
    closes = prices[1:]
    highs = np.maximum(opens, closes) + np.random.rand(n-1) * 5
    lows = np.minimum(opens, closes) - np.random.rand(n-1) * 5
    
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
# 2. 包含关系处理
# ============================================================================

def process_containment(klines: pd.DataFrame) -> List[Tuple[float, float]]:
    """
    处理K线包含关系
    规则：
    1. 上升趋势中的包含：取高高原则（max(high), max(low)）
    2. 下降趋势中的包含：取低低原则（min(high), min(low)）
    3. 趋势判断：当前K线low > 前一根low为上升，否则为下降
    
    返回：处理后的K线列表[(high, low), ...]
    """
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
        
        # 判断包含关系
        is_contained = (h2 <= h1 and l2 >= l1) or (h2 >= h1 and l2 <= l1)
        
        if not is_contained:
            result.append(rows[i])
            continue
            
        # 判断趋势
        if l2 > l1:
            # 上升趋势 - 高高原则
            new_h = max(h1, h2)
            new_l = max(l1, l2)
        else:
            # 下降趋势 - 低低原则
            new_h = min(h1, h2)
            new_l = min(l1, l2)
            
        result[-1] = (new_h, new_l)
    
    return result

# ============================================================================
# 3. 分型识别
# ============================================================================

def find_fractals(klist: List[Tuple[float, float]]) -> List[Tuple[str, int, float]]:
    """
    识别顶分型和底分型
    规则：
    1. 顶分型：中间K线的high和low都高于左右两根K线
    2. 底分型：中间K线的high和low都低于左右两根K线
    3. 排除包含关系处理后的相邻分型
    
    返回：分型列表[('top', index, high), ('bottom', index, low), ...]
    """
    n = len(klist)
    if n < 3:
        return []
    
    fractals = []
    
    for i in range(1, n - 1):
        h_prev, l_prev = klist[i - 1]
        h_curr, l_curr = klist[i]
        h_next, l_next = klist[i + 1]
        
        # 顶分型
        if (h_curr > h_prev and h_curr > h_next and 
            l_curr > l_prev and l_curr > l_next):
            fractals.append(('top', i, h_curr))
        
        # 底分型
        elif (h_curr < h_prev and h_curr < h_next and 
              l_curr < l_prev and l_curr < l_next):
            fractals.append(('bottom', i, l_curr))
    
    # 过滤相邻分型（缠论要求分型之间至少有一根独立K线）
    filtered = []
    for i in range(len(fractals)):
        if i == 0:
            filtered.append(fractals[i])
        else:
            prev_idx = fractals[i-1][1]
            curr_idx = fractals[i][1]
            if curr_idx - prev_idx >= 2:  # 至少间隔一根K线
                filtered.append(fractals[i])
    
    return filtered

# ============================================================================
# 4. 笔划分算法
# ============================================================================

def build_strokes(fractals: List[Tuple[str, int, float]], 
                  klist: List[Tuple[float, float]],
                  min_k_bars: int = 4,
                  min_price_range: float = 30.0) -> List[Tuple[str, int, int, float, float, bool]]:
    """
    构建笔（Stroke）
    规则：
    1. 标准笔：相邻顶底分型，间隔至少4根K线
    2. 小笔：间隔不足4根但价格幅度超过阈值
    3. 笔的方向：底分型->顶分型=上升笔，顶分型->底分型=下降笔
    
    返回：笔列表[(direction, start_idx, end_idx, start_price, end_price, is_small), ...]
    """
    if len(fractals) < 2:
        return []
    
    strokes = []
    i = 0
    
    while i < len(fractals) - 1:
        ftype1, idx1, price1 = fractals[i]
        
        # 确定笔的起点类型和方向
        if ftype1 == 'bottom':
            direction = 'up'
            target_type = 'top'
        else:
            direction = 'down'
            target_type = 'bottom'
        
        # 寻找符合条件的终点分型
        found = False
        for j in range(i + 1, len(fractals)):
            ftype2, idx2, price2 = fractals[j]
            
            if ftype2 != target_type:
                continue
            
            # 计算K线间隔和价格幅度
            k_gap = idx2 - idx1
            price_range = abs(price2 - price1)
            
            # 检查是否满足笔的条件
            if k_gap >= min_k_bars:
                # 标准笔
                strokes.append((direction, idx1, idx2, price1, price2, False))
                i = j
                found = True
                break
            elif price_range >= min_price_range:
                # 小笔（幅度达标但K线不足）
                strokes.append((direction, idx1, idx2, price1, price2, True))
                i = j
                found = True
                break
        
        if not found:
            i += 1
    
    return strokes

# ============================================================================
# 5. 线段检测算法
# ============================================================================

def build_segments(strokes: List[Tuple[str, int, int, float, float, bool]]) -> List[Tuple[str, int, int, float, float, List[int]]]:
    """
    构建线段（Segment）
    规则：
    1. 线段由至少3笔构成
    2. 上行线段：底-顶-底（低点抬高，高点抬高）
    3. 下行线段：顶-底-顶（高点降低，低点降低）
    4. 线段延伸：同方向笔不断创新高/新低
    5. 线段破坏：反方向笔突破前一线段极值
    
    返回：线段列表[(direction, start_idx, end_idx, start_price, end_price, stroke_indices), ...]
    """
    if len(strokes) < 3:
        return []
    
    segments = []
    i = 0
    
    while i <= len(strokes) - 3:
        # 检查三笔组合
        s1 = strokes[i]
        s2 = strokes[i + 1]
        s3 = strokes[i + 2]
        
        dir1, idx1_s, idx1_e, price1_s, price1_e, small1 = s1
        dir2, idx2_s, idx2_e, price2_s, price2_e, small2 = s2
        dir3, idx3_s, idx3_e, price3_s, price3_e, small3 = s3
        
        # 检查笔的方向模式
        if dir1 == 'up' and dir2 == 'down' and dir3 == 'up':
            # 潜在上行线段：底-顶-底
            if (price2_e > price1_e and  # 第二笔低点 > 第一笔低点
                price3_e > price2_e):    # 第三笔高点 > 第二笔高点
                
                # 线段延伸检查
                segment_dir = 'up'
                segment_start_idx = idx1_s
                segment_end_idx = idx3_e
                segment_start_price = price1_s
                segment_end_price = price3_e
                stroke_indices = [i, i+1, i+2]
                
                # 检查后续笔是否延伸线段
                j = i + 3
                while j < len(strokes):
                    s_next = strokes[j]
                    dir_next, _, idx_next_e, _, price_next_e, _ = s_next
                    
                    if dir_next == 'up':
                        # 同方向笔，检查是否创新高
                        if price_next_e > segment_end_price:
                            segment_end_idx = idx_next_e
                            segment_end_price = price_next_e
                            stroke_indices.append(j)
                            j += 1
                        else:
                            # 不再创新高，线段结束
                            break
                    else:
                        # 反方向笔，检查是否破坏线段
                        if price_next_e < price2_e:  # 跌破前一个低点
                            # 线段被破坏
                            break
                        else:
                            # 未破坏，继续延伸
                            stroke_indices.append(j)
                            j += 1
                
                segments.append((segment_dir, segment_start_idx, segment_end_idx,
                               segment_start_price, segment_end_price, stroke_indices))
                i = j  # 跳到线段结束后的位置
                continue
                
        elif dir1 == 'down' and dir2 == 'up' and dir3 == 'down':
            # 潜在下行线段：顶-底-顶
            if (price2_e < price1_e and  # 第二笔高点 < 第一笔高点
                price3_e < price2_e):    # 第三笔低点 < 第二笔低点
                
                # 线段延伸检查
                segment_dir = 'down'
                segment_start_idx = idx1_s
                segment_end_idx = idx3_e
                segment_start_price = price1_s
                segment_end_price = price3_e
                stroke_indices = [i, i+1, i+2]
                
                # 检查后续笔是否延伸线段
                j = i + 3
                while j < len(strokes):
                    s_next = strokes[j]
                    dir_next, _, idx_next_e, _, price_next_e, _ = s_next
                    
                    if dir_next == 'down':
                        # 同方向笔，检查是否创新低
                        if price_next_e < segment_end_price:
                            segment_end_idx = idx_next_e
                            segment_end_price = price_next_e
                            stroke_indices.append(j)
                            j += 1
                        else:
                            # 不再创新低，线段结束
                            break
                    else:
                        # 反方向笔，检查是否破坏线段
                        if price_next_e > price2_e:  # 突破前一个高点
                            # 线段被破坏
                            break
                        else:
                            # 未破坏，继续延伸
                            stroke_indices.append(j)
                            j += 1
                
                segments.append((segment_dir, segment_start_idx, segment_end_idx,
                               segment_start_price, segment_end_price, stroke_indices))
                i = j  # 跳到线段结束后的位置
                continue
        
        i += 1
    
    return segments

# ============================================================================
# 6. 可视化模块
# ============================================================================

def visualize_analysis(klines: pd.DataFrame,
                      processed_k: List[Tuple[float, float]],
                      fractals: List[Tuple[str, int, float]],
                      strokes: List[Tuple[str, int, int, float, float, bool]],
                      segments: List[Tuple[str, int, int, float, float, List[int]]],
                      output_path: str = 'chan_analysis.png'):
    """
    可视化缠论分析结果
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
        ax1.scatter(idx, price, color=color, s=60, marker=marker, zorder=5, label=ftype)
    
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
                color=color, linewidth=4, alpha=0.6, linestyle='-')
    
    ax1.set_title('缠论分析：K线 + 分型 + 笔 + 线段', color='white', fontsize=14, pad=12)
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
    
    # 子图2：价格和指标
    ax2.plot(klines.index, klines['close'], color='white', linewidth=1.5, alpha=0.7, label='收盘价')
    
    # 标记分型位置
    for ftype, idx, price in fractals:
        color = '#ffff00' if ftype == 'top' else '#00ffcc'
        ax2.scatter(idx, price, color=color, s=40, zorder=5)
    
    ax2.set_title('收盘价走势', color='white', fontsize=12, pad=10)
    ax2.set_xlabel('K线序号', color='white')
    ax2.set_ylabel('价格', color='white')
    ax2.grid(True, alpha=0.2)
    ax2.legend(loc='upper left')
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=120, bbox_inches='tight')
    print(f"可视化结果已保存到: {output_path}")

# ============================================================================
# 7. 测试用例
# ============================================================================

def run_test_cases():
    """
    运行完整的测试用例
    """
    print("=" * 60)
    print("缠论算法测试用例")
    print("=" * 60)
    
    # 测试1：数据获取
    print("\n1. 测试数据获取...")
    data = get_sample_data()
    print(f"   获取到 {len(data)} 根K线")
    print(f"   时间范围: {data['datetime'].iloc[0]} ~ {data['datetime'].iloc[-1]}")
    print(f"   价格范围: {data['low'].min():.1f} ~ {data['high'].max():.1f}")
    
    # 测试2：包含关系处理
    print("\n2. 测试包含关系处理...")
    processed_k = process_containment(data)
    print(f"   原始K线: {len(data)} 根")
    print(f"   处理后K线: {len(processed_k)} 根")
    print(f"   压缩率: {(1 - len(processed_k)/len(data))*100:.1f}%")
    
    # 测试3：分型识别
    print("\n3. 测试分型识别...")
    fractals = find_fractals(processed_k)
    top_count = sum(1 for f in fractals if f[0] == 'top')
    bottom_count = sum(1 for f in fractals if f[0] == 'bottom')
    print(f"   找到 {len(fractals)} 个分型")
    print(f"   顶分型: {top_count} 个")
    print(f"   底分型: {bottom_count} 个")
    
    # 测试4：笔划分
    print("\n4. 测试笔划分...")
    strokes = build_strokes(fractals, processed_k, min_k_bars=4, min_price_range=30.0)
    up_strokes = sum(1 for s in strokes if s[0] == 'up')
    down_strokes = sum(1 for s in strokes if s[0] == 'down')
    small_strokes = sum(1 for s in strokes if s[5])
    print(f"   找到 {len(strokes)} 笔")
    print(f"   上行笔: {up_strokes} 笔")
    print(f"   下行笔: {down_strokes} 笔")
    print(f"   小笔: {small_strokes} 笔")
    
    # 显示前5笔
    print("\n   前5笔详情:")
    for i, stroke in enumerate(strokes[:5]):
        direction, start_idx, end_idx, start_price, end_price, is_small = stroke
        arrow = "↑" if direction == 'up' else "↓"
        small_tag = "[小笔]" if is_small else ""
        price_range = abs(end_price - start_price)
        k_gap = end_idx - start_idx
        print(f"     笔{i+1}: {arrow} {start_price:.1f}→{end_price:.1f} "
              f"(幅度:{price_range:.1f}, K线:{k_gap}根) {small_tag}")
    
    # 测试5：线段检测
    print("\n5. 测试线段检测...")
    segments = build_segments(strokes)
    up_segments = sum(1 for s in segments if s[0] == 'up')
    down_segments = sum(1 for s in segments if s[0] == 'down')
    print(f"   找到 {len(segments)} 个线段")
    print(f"   上行线段: {up_segments} 个")
    print(f"   下行线段: {down_segments} 个")
    
    # 显示线段详情
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
    
    # 测试6：可视化
    print("\n6. 生成可视化图表...")
    visualize_analysis(data, processed_k, fractals, strokes, segments, 'test_chan_analysis.png')
    
    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)
    
    return {
        'data': data,
        'processed_k': processed_k,
        'fractals': fractals,
        'strokes': strokes,
        'segments': segments
    }

# ============================================================================
# 8. 主程序
# ============================================================================

def main():
    """
    主函数：运行完整缠论分析
    """
    print("缠论算法完整实现")
    print("=" * 50)
    
    # 运行测试用例
    results = run_test_cases()
    
    # 生成详细报告
    print("\n详细分析报告:")
    print("-" * 40)
    
    data = results['data']
    fractals = results['fractals']
    strokes = results['strokes']
    segments = results['segments']
    
    # 分型统计
    print(f"分型统计:")
    print(f"  总数: {len(fractals)}")
    print(f"  顶分型: {sum(1 for f in fractals if f[0] == 'top')}")
    print(f"  底分型: {sum(1 for f in fractals if f[0] == 'bottom')}")
    
    # 笔统计
    print(f"\n笔统计:")
    print(f"  总数: {len(strokes)}")
    print(f"  上行笔: {sum(1 for s in strokes if s[0] == 'up')}")
    print(f"  下行笔: {sum(1 for s in strokes if s[0] == 'down')}")
    print(f"  标准笔: {sum(1 for s in strokes if not s[5])}")
    print(f"  小笔: {sum(1 for s in strokes if s[5])}")
    
    # 线段统计
    print(f"\n线段统计:")
    print(f"  总数: {len(segments)}")
    if segments:
        avg_strokes = np.mean([len(s[5]) for s in segments])
        avg_length = np.mean([abs(s[4] - s[3]) for s in segments])
        print(f"  平均包含笔数: {avg_strokes:.1f}")
        print(f"  平均幅度: {avg_length:.1f}")
    
    # 市场状态分析
    print(f"\n市场状态分析:")
    if strokes:
        last_stroke = strokes[-1]
        direction = "上行" if last_stroke[0] == 'up' else "下行"
        print(f"  最新笔方向: {direction}")
        
        if segments:
            last_segment = segments[-1]
            seg_direction = "上行" if last_segment[0] == 'up' else "下行"
            print(f"  最新线段方向: {seg_direction}")
            
            # 判断趋势强度
            if len(segments) >= 2:
                prev_segment = segments[-2]
                if last_segment[0] == prev_segment[0]:
                    print(f"  趋势状态: 延续")
                else:
                    print(f"  趋势状态: 反转")
    
    print("\n" + "=" * 50)
    print("分析完成！图表已保存为 'test_chan_analysis.png'")

if __name__ == "__main__":
    main()
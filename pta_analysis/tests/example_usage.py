#!/usr/bin/env python3
"""
缠论算法使用示例
展示如何使用缠论分析器进行实际分析
"""

import pandas as pd
import numpy as np
from chan_final_implementation import ChanTheoryAnalyzer, ChanVisualizer, DataGenerator

def example_basic():
    """
    示例1：基本使用
    """
    print("=" * 60)
    print("示例1：基本使用")
    print("=" * 60)
    
    # 生成测试数据
    data = DataGenerator.generate_trend_data('up_trend', n_bars=100)
    
    # 创建分析器
    analyzer = ChanTheoryAnalyzer(min_k_bars=4, min_price_range=30.0)
    
    # 执行分析
    results = analyzer.analyze(data)
    
    # 显示基本信息
    print(f"数据信息:")
    print(f"  时间范围: {data['datetime'].iloc[0]} 到 {data['datetime'].iloc[-1]}")
    print(f"  价格范围: {data['low'].min():.1f} - {data['high'].max():.1f}")
    
    # 获取统计信息
    stats = analyzer.get_statistics()
    print(f"\n分析结果:")
    print(f"  原始K线: {stats['kline_count']} 根")
    print(f"  处理后K线: {stats['processed_kline_count']} 根")
    print(f"  分型数量: {stats['fractal_count']} 个")
    print(f"  笔数量: {stats['stroke_count']} 笔")
    print(f"    上行笔: {stats['up_stroke_count']}")
    print(f"    下行笔: {stats['down_stroke_count']}")
    print(f"    小笔: {stats['small_stroke_count']}")
    print(f"  线段数量: {stats['segment_count']} 段")
    
    if stats['segment_count'] > 0:
        print(f"    上行线段: {stats['up_segment_count']}")
        print(f"    下行线段: {stats['down_segment_count']}")
        print(f"    平均线段幅度: {stats['avg_segment_length']:.1f}")
    
    # 趋势分析
    trend = analyzer.get_trend_analysis()
    print(f"\n趋势分析:")
    print(f"  当前笔方向: {trend['current_stroke_direction']}")
    print(f"  当前线段方向: {trend['current_segment_direction']}")
    print(f"  趋势状态: {trend['trend_status']}")
    print(f"  趋势强度: {trend['strength']}")
    
    # 可视化
    ChanVisualizer.visualize(analyzer, 'example_basic.png', '基本使用示例')
    
    print(f"\n图表已保存到: example_basic.png")

def example_detailed_analysis():
    """
    示例2：详细分析
    """
    print("\n" + "=" * 60)
    print("示例2：详细分析")
    print("=" * 60)
    
    # 生成复杂走势数据
    data = DataGenerator.generate_trend_data('complex', n_bars=150)
    
    # 创建分析器
    analyzer = ChanTheoryAnalyzer()
    
    # 执行分析
    analyzer.analyze(data)
    
    # 显示分型详情
    print(f"分型详情（前10个）:")
    fractals = analyzer.fractals[:10] if analyzer.fractals else []
    for i, (ftype, idx, price) in enumerate(fractals):
        type_name = "顶分型" if ftype == 'top' else "底分型"
        print(f"  {i+1:2d}. {type_name:4s} - 位置:{idx:4d}, 价格:{price:7.1f}")
    
    # 显示笔详情
    print(f"\n笔详情（前5笔）:")
    strokes = analyzer.strokes[:5] if analyzer.strokes else []
    for i, (direction, start_idx, end_idx, start_price, end_price, is_small) in enumerate(strokes):
        dir_name = "上行" if direction == 'up' else "下行"
        small_tag = "[小笔]" if is_small else ""
        price_range = abs(end_price - start_price)
        k_gap = end_idx - start_idx
        print(f"  笔{i+1}: {dir_name} {start_price:.1f}→{end_price:.1f} "
              f"(幅度:{price_range:.1f}, K线:{k_gap}根) {small_tag}")
    
    # 显示线段详情
    print(f"\n线段详情:")
    segments = analyzer.segments if analyzer.segments else []
    for i, (direction, start_idx, end_idx, start_price, end_price, stroke_indices) in enumerate(segments):
        dir_name = "上行" if direction == 'up' else "下行"
        price_range = abs(end_price - start_price)
        k_gap = end_idx - start_idx
        stroke_count = len(stroke_indices)
        print(f"  线段{i+1}: {dir_name} {start_price:.1f}→{end_price:.1f} "
              f"(幅度:{price_range:.1f}, K线:{k_gap}根, 包含{stroke_count}笔)")
    
    # 可视化
    ChanVisualizer.visualize(analyzer, 'example_detailed.png', '详细分析示例')
    
    print(f"\n图表已保存到: example_detailed.png")

def example_multiple_timeframes():
    """
    示例3：多时间周期分析
    """
    print("\n" + "=" * 60)
    print("示例3：多时间周期分析")
    print("=" * 60)
    
    # 生成不同时间周期的数据
    timeframes = {
        '1分钟': DataGenerator.generate_trend_data('up_trend', n_bars=200),
        '5分钟': DataGenerator.generate_trend_data('sideways', n_bars=100),
        '15分钟': DataGenerator.generate_trend_data('complex', n_bars=80)
    }
    
    results = {}
    
    for tf_name, data in timeframes.items():
        print(f"\n分析 {tf_name} 数据:")
        
        # 创建分析器（不同时间周期使用不同参数）
        if tf_name == '1分钟':
            analyzer = ChanTheoryAnalyzer(min_k_bars=4, min_price_range=20.0)
        elif tf_name == '5分钟':
            analyzer = ChanTheoryAnalyzer(min_k_bars=3, min_price_range=40.0)
        else:  # 15分钟
            analyzer = ChanTheoryAnalyzer(min_k_bars=2, min_price_range=60.0)
        
        # 执行分析
        analyzer.analyze(data)
        
        # 保存结果
        results[tf_name] = analyzer
        
        # 显示简要结果
        stats = analyzer.get_statistics()
        print(f"  笔数量: {stats['stroke_count']}")
        print(f"  线段数量: {stats['segment_count']}")
        
        if stats['segment_count'] > 0:
            print(f"  平均线段幅度: {stats['avg_segment_length']:.1f}")
    
    # 可视化其中一个
    if '1分钟' in results:
        ChanVisualizer.visualize(
            results['1分钟'], 
            'example_multitime_1min.png', 
            '1分钟K线缠论分析'
        )
        print(f"\n1分钟图表已保存到: example_multitime_1min.png")

def example_custom_data():
    """
    示例4：使用自定义数据
    """
    print("\n" + "=" * 60)
    print("示例4：使用自定义数据")
    print("=" * 60)
    
    # 创建自定义数据（模拟PTA期货）
    np.random.seed(123)
    n = 120
    base = 6000
    
    # 创建趋势 + 震荡
    trend = np.linspace(0, 100, n)
    cycles = 50 * np.sin(np.linspace(0, 4*np.pi, n))
    noise = np.random.randn(n) * 15
    
    prices = base + trend + cycles + noise
    
    # 生成OHLC
    opens = prices[:-1]
    closes = prices[1:]
    highs = np.maximum(opens, closes) + np.random.rand(n-1) * 8
    lows = np.minimum(opens, closes) - np.random.rand(n-1) * 8
    
    # 确保high > low
    highs = np.maximum(highs, lows + 1)
    
    # 创建DataFrame
    custom_data = pd.DataFrame({
        'datetime': pd.date_range('2026-04-08 09:00', periods=n-1, freq='1min'),
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes
    })
    
    # 分析
    analyzer = ChanTheoryAnalyzer()
    analyzer.analyze(custom_data)
    
    # 显示结果
    stats = analyzer.get_statistics()
    print(f"自定义数据分析结果:")
    print(f"  数据点数: {len(custom_data)}")
    print(f"  笔数量: {stats['stroke_count']}")
    print(f"  线段数量: {stats['segment_count']}")
    
    # 可视化
    ChanVisualizer.visualize(analyzer, 'example_custom.png', '自定义数据分析')
    
    print(f"\n图表已保存到: example_custom.png")

def main():
    """
    主函数：运行所有示例
    """
    print("缠论算法使用示例")
    print("=" * 60)
    
    # 运行所有示例
    example_basic()
    example_detailed_analysis()
    example_multiple_timeframes()
    example_custom_data()
    
    print("\n" + "=" * 60)
    print("所有示例运行完成！")
    print("生成的文件:")
    print("  - example_basic.png (基本使用示例)")
    print("  - example_detailed.png (详细分析示例)")
    print("  - example_multitime_1min.png (多时间周期示例)")
    print("  - example_custom.png (自定义数据示例)")
    print("=" * 60)

if __name__ == "__main__":
    main()
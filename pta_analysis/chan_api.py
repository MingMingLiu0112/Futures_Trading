"""
缠论算法API接口
提供简洁易用的函数接口
"""

import pandas as pd
from typing import List, Dict, Any, Optional
from chan_algorithm import ChanKLine, ChanProcessor, klines_from_dataframe


def process_chan_analysis(df: pd.DataFrame, 
                         min_kline_gap: int = 4,
                         min_price_range: Optional[float] = None) -> Dict[str, Any]:
    """
    缠论分析主函数
    
    参数:
        df: DataFrame，必须包含'high'和'low'列，可选'open'、'close'、'volume'、'datetime'
        min_kline_gap: 笔的最小K线间隔，默认4根
        min_price_range: 笔的最小价格幅度，None表示不限制
    
    返回:
        Dict包含:
            - processed_klines: 处理后的K线列表
            - fenxing_list: 分型列表
            - bi_list: 笔列表
            - statistics: 统计信息
    """
    # 转换DataFrame为K线对象
    klines = klines_from_dataframe(df)
    
    # 创建处理器
    processor = ChanProcessor()
    
    # 运行完整流水线
    result = processor.process_pipeline(klines, min_kline_gap, min_price_range)
    
    # 添加统计信息
    result['statistics'] = {
        'original_kline_count': len(klines),
        'processed_kline_count': len(result['processed_klines']),
        'fenxing_count': len(result['fenxing_list']),
        'bi_count': len(result['bi_list']),
        'up_bi_count': sum(1 for bi in result['bi_list'] if bi['direction'] == 'up'),
        'down_bi_count': sum(1 for bi in result['bi_list'] if bi['direction'] == 'down'),
        'small_bi_count': sum(1 for bi in result['bi_list'] if bi['is_small_bi']),
    }
    
    return result


def get_fenxing_summary(fenxing_list: List[Dict]) -> pd.DataFrame:
    """将分型列表转换为DataFrame摘要"""
    if not fenxing_list:
        return pd.DataFrame()
    
    data = []
    for fen in fenxing_list:
        data.append({
            'index': fen['index'],
            'type': fen['type'],
            'price': fen['price'],
            'timestamp': fen['kline'].timestamp if fen['kline'].timestamp else None,
        })
    
    return pd.DataFrame(data)


def get_bi_summary(bi_list: List[Dict]) -> pd.DataFrame:
    """将笔列表转换为DataFrame摘要"""
    if not bi_list:
        return pd.DataFrame()
    
    data = []
    for bi in bi_list:
        data.append({
            'direction': bi['direction'],
            'start_index': bi['start_index'],
            'end_index': bi['end_index'],
            'start_price': bi['start_price'],
            'end_price': bi['end_price'],
            'price_range': bi['price_range'],
            'kline_gap': bi['kline_gap'],
            'is_small_bi': bi['is_small_bi'],
            'start_timestamp': bi['start_fenxing']['kline'].timestamp if bi['start_fenxing']['kline'].timestamp else None,
            'end_timestamp': bi['end_fenxing']['kline'].timestamp if bi['end_fenxing']['kline'].timestamp else None,
        })
    
    return pd.DataFrame(data)


def visualize_analysis(result: Dict[str, Any], save_path: Optional[str] = None):
    """
    可视化缠论分析结果
    
    参数:
        result: process_chan_analysis的返回结果
        save_path: 保存图片的路径，None表示不保存
    """
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        
        klines = result['processed_klines']
        fenxing_list = result['fenxing_list']
        bi_list = result['bi_list']
        
        # 创建图形
        fig, ax = plt.subplots(figsize=(15, 8))
        
        # 提取时间和价格
        timestamps = []
        highs = []
        lows = []
        
        for kline in klines:
            if kline.timestamp:
                timestamps.append(kline.timestamp)
            else:
                timestamps.append(pd.Timestamp.now())  # 如果没有时间戳，使用当前时间
            highs.append(kline.high)
            lows.append(kline.low)
        
        # 绘制K线（简化版，用高低点连线）
        for i in range(len(klines) - 1):
            ax.plot([timestamps[i], timestamps[i + 1]], [highs[i], highs[i + 1]], 
                   'k-', alpha=0.3, linewidth=0.5)
            ax.plot([timestamps[i], timestamps[i + 1]], [lows[i], lows[i + 1]], 
                   'k-', alpha=0.3, linewidth=0.5)
        
        # 绘制分型
        top_prices = []
        top_times = []
        bottom_prices = []
        bottom_times = []
        
        for fen in fenxing_list:
            if fen['type'] == 'top':
                top_prices.append(fen['price'])
                top_times.append(timestamps[fen['index']] if fen['index'] < len(timestamps) else timestamps[-1])
            else:
                bottom_prices.append(fen['price'])
                bottom_times.append(timestamps[fen['index']] if fen['index'] < len(timestamps) else timestamps[-1])
        
        if top_prices:
            ax.scatter(top_times, top_prices, color='red', s=100, marker='v', 
                      label='顶分型', zorder=5)
        if bottom_prices:
            ax.scatter(bottom_times, bottom_prices, color='green', s=100, marker='^', 
                      label='底分型', zorder=5)
        
        # 绘制笔
        for bi in bi_list:
            start_time = timestamps[bi['start_index']] if bi['start_index'] < len(timestamps) else timestamps[-1]
            end_time = timestamps[bi['end_index']] if bi['end_index'] < len(timestamps) else timestamps[-1]
            
            color = 'blue' if bi['direction'] == 'up' else 'orange'
            linestyle = '-' if not bi['is_small_bi'] else '--'
            linewidth = 2 if not bi['is_small_bi'] else 1
            
            ax.plot([start_time, end_time], [bi['start_price'], bi['end_price']],
                   color=color, linestyle=linestyle, linewidth=linewidth, 
                   label=f"{bi['direction']}笔" if bi == bi_list[0] else "")
        
        # 设置图形属性
        ax.set_title('缠论分析结果', fontsize=16)
        ax.set_xlabel('时间', fontsize=12)
        ax.set_ylabel('价格', fontsize=12)
        ax.grid(True, alpha=0.3)
        ax.legend()
        
        # 格式化时间轴
        if len(timestamps) > 1:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
            plt.xticks(rotation=45)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"图表已保存到: {save_path}")
        
        plt.show()
        
    except ImportError:
        print("警告: matplotlib未安装，无法可视化。请运行: pip install matplotlib")
    except Exception as e:
        print(f"可视化失败: {e}")


def quick_analysis(df: pd.DataFrame, visualize: bool = True) -> Dict[str, Any]:
    """
    快速缠论分析
    
    参数:
        df: 包含K线数据的DataFrame
        visualize: 是否可视化结果
    
    返回:
        分析结果字典
    """
    print("开始缠论快速分析...")
    print(f"数据形状: {df.shape}")
    
    # 运行分析
    result = process_chan_analysis(df)
    stats = result['statistics']
    
    # 打印统计信息
    print(f"\n分析结果:")
    print(f"  原始K线: {stats['original_kline_count']}")
    print(f"  处理后K线: {stats['processed_kline_count']}")
    print(f"  分型数量: {stats['fenxing_count']}")
    print(f"  笔数量: {stats['bi_count']} (上行: {stats['up_bi_count']}, 下行: {stats['down_bi_count']})")
    print(f"  小笔数量: {stats['small_bi_count']}")
    
    # 打印分型详情
    if result['fenxing_list']:
        print(f"\n分型详情 (前10个):")
        fen_df = get_fenxing_summary(result['fenxing_list'][:10])
        print(fen_df.to_string())
    
    # 打印笔详情
    if result['bi_list']:
        print(f"\n笔详情 (前10支):")
        bi_df = get_bi_summary(result['bi_list'][:10])
        print(bi_df.to_string())
    
    # 可视化
    if visualize and result['bi_list']:
        print(f"\n生成可视化图表...")
        visualize_analysis(result)
    
    return result


# ============================================================================
# 示例使用
# ============================================================================

def example_usage():
    """示例使用"""
    print("缠论API使用示例")
    print("=" * 50)
    
    # 创建示例数据
    data = {
        'datetime': pd.date_range('2024-01-01 09:00', periods=50, freq='1min'),
        'open': [100 + i * 0.5 + np.random.randn() * 2 for i in range(50)],
        'high': [105 + i * 0.5 + np.random.randn() * 3 for i in range(50)],
        'low': [95 + i * 0.5 + np.random.randn() * 3 for i in range(50)],
        'close': [102 + i * 0.5 + np.random.randn() * 2 for i in range(50)],
        'volume': [1000 + np.random.randint(-200, 200) for _ in range(50)],
    }
    
    df = pd.DataFrame(data)
    
    # 方法1: 快速分析
    print("\n方法1: 快速分析")
    result = quick_analysis(df.head(30), visualize=False)
    
    # 方法2: 完整分析
    print("\n方法2: 完整分析")
    full_result = process_chan_analysis(df)
    
    # 获取DataFrame摘要
    fen_df = get_fenxing_summary(full_result['fenxing_list'])
    bi_df = get_bi_summary(full_result['bi_list'])
    
    print(f"\n分型DataFrame形状: {fen_df.shape}")
    print(f"笔DataFrame形状: {bi_df.shape}")
    
    # 方法3: 自定义参数
    print("\n方法3: 自定义参数分析")
    custom_result = process_chan_analysis(
        df, 
        min_kline_gap=3,  # 最小3根K线
        min_price_range=5.0  # 最小价格幅度5.0
    )
    
    print(f"自定义参数分析结果:")
    print(f"  笔数量: {len(custom_result['bi_list'])}")
    
    return {
        'quick_result': result,
        'full_result': full_result,
        'custom_result': custom_result,
        'fen_df': fen_df,
        'bi_df': bi_df
    }


if __name__ == "__main__":
    import numpy as np
    
    print("缠论算法API接口")
    print("-" * 40)
    
    # 运行示例
    results = example_usage()
    
    print("\n" + "=" * 50)
    print("示例完成")
    print("=" * 50)
    
    # 显示API函数说明
    print("\n可用函数:")
    print("  1. process_chan_analysis(df, min_kline_gap=4, min_price_range=None)")
    print("     - 主分析函数，返回完整分析结果")
    print("  2. quick_analysis(df, visualize=True)")
    print("     - 快速分析，包含统计信息和可视化")
    print("  3. get_fenxing_summary(fenxing_list)")
    print("     - 将分型列表转换为DataFrame")
    print("  4. get_bi_summary(bi_list)")
    print("     - 将笔列表转换为DataFrame")
    print("  5. visualize_analysis(result, save_path=None)")
    print("     - 可视化分析结果")
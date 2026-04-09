#!/usr/bin/env python3
"""
缠论算法最终实现：完整的笔划分和线段检测
基于缠论108课标准定义，包含：
1. 包含关系处理
2. 顶底分型识别
3. 笔划分算法（标准笔、小笔）
4. 线段检测算法（线段破坏规则）
5. 可视化输出
6. 完整的测试用例
7. 实际数据接口
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from typing import List, Tuple, Dict, Any, Optional
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# 1. 核心算法类
# ============================================================================

class ChanTheoryAnalyzer:
    """
    缠论分析器
    实现完整的缠论分析流程
    """
    
    def __init__(self, min_k_bars: int = 4, min_price_range: float = 30.0):
        """
        初始化缠论分析器
        
        Args:
            min_k_bars: 笔的最小K线数量（默认4根）
            min_price_range: 小笔的最小价格幅度（默认30点）
        """
        self.min_k_bars = min_k_bars
        self.min_price_range = min_price_range
        
        # 分析结果
        self.klines = None
        self.processed_k = None
        self.fractals = None
        self.strokes = None
        self.segments = None
        
    # ------------------------------------------------------------------------
    # 1.1 包含关系处理
    # ------------------------------------------------------------------------
    
    def process_containment(self, klines: pd.DataFrame) -> List[Tuple[float, float]]:
        """
        处理K线包含关系
        
        Args:
            klines: 包含high, low列的DataFrame
            
        Returns:
            处理后的K线列表[(high, low), ...]
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
    
    # ------------------------------------------------------------------------
    # 1.2 分型识别
    # ------------------------------------------------------------------------
    
    def find_fractals(self, klist: List[Tuple[float, float]]) -> List[Tuple[str, int, float]]:
        """
        识别顶分型和底分型
        
        Args:
            klist: 处理后的K线列表[(high, low), ...]
            
        Returns:
            分型列表[('top', index, high), ('bottom', index, low), ...]
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
        
        # 过滤相邻分型
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
    
    # ------------------------------------------------------------------------
    # 1.3 笔划分算法
    # ------------------------------------------------------------------------
    
    def build_strokes(self, fractals: List[Tuple[str, int, float]], 
                     klist: List[Tuple[float, float]]) -> List[Tuple[str, int, int, float, float, bool]]:
        """
        构建笔（Stroke）
        
        Args:
            fractals: 分型列表
            klist: 处理后的K线列表
            
        Returns:
            笔列表[(direction, start_idx, end_idx, start_price, end_price, is_small), ...]
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
                if k_gap >= self.min_k_bars:
                    # 标准笔
                    strokes.append((direction, idx1, idx2, price1, price2, False))
                    i = j
                    found = True
                    break
                elif price_range >= self.min_price_range:
                    # 小笔（幅度达标但K线不足）
                    strokes.append((direction, idx1, idx2, price1, price2, True))
                    i = j
                    found = True
                    break
            
            if not found:
                i += 1
        
        return strokes
    
    # ------------------------------------------------------------------------
    # 1.4 线段检测算法
    # ------------------------------------------------------------------------
    
    def build_segments(self, strokes: List[Tuple[str, int, int, float, float, bool]]) -> List[Tuple[str, int, int, float, float, List[int]]]:
        """
        构建线段（Segment）
        
        Args:
            strokes: 笔列表
            
        Returns:
            线段列表[(direction, start_idx, end_idx, start_price, end_price, stroke_indices), ...]
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
            
            dir1, idx1_s, idx1_e, price1_s, price1_e, _ = s1
            dir2, idx2_s, idx2_e, price2_s, price2_e, _ = s2
            dir3, idx3_s, idx3_e, price3_s, price3_e, _ = s3
            
            # 检查是否构成线段起始
            if dir1 == 'up' and dir2 == 'down' and dir3 == 'up':
                # 上行线段：低点抬高，高点抬高
                if price2_e > price1_e and price3_e > price2_e:
                    segment = self._extend_segment(strokes, i, 'up')
                    if segment:
                        segments.append(segment)
                        i = segment[5][-1] + 1
                        continue
            
            elif dir1 == 'down' and dir2 == 'up' and dir3 == 'down':
                # 下行线段：高点降低，低点降低
                if price2_e < price1_e and price3_e < price2_e:
                    segment = self._extend_segment(strokes, i, 'down')
                    if segment:
                        segments.append(segment)
                        i = segment[5][-1] + 1
                        continue
            
            i += 1
        
        return segments
    
    def _extend_segment(self, strokes: List[Tuple[str, int, int, float, float, bool]], 
                       start_idx: int, 
                       direction: str) -> Optional[Tuple[str, int, int, float, float, List[int]]]:
        """
        延伸线段
        
        Args:
            strokes: 笔列表
            start_idx: 起始笔索引
            direction: 线段方向
            
        Returns:
            线段元组或None
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
                    # 不再延伸，线段可能结束
                    break
            else:
                # 反方向笔
                stroke_indices.append(i)
                i += 1
        
        # 确保线段至少包含3笔
        if len(stroke_indices) >= 3:
            return (direction, segment_start_idx, segment_end_idx,
                    segment_start_price, segment_end_price, stroke_indices)
        
        return None
    
    # ------------------------------------------------------------------------
    # 1.5 完整分析流程
    # ------------------------------------------------------------------------
    
    def analyze(self, klines: pd.DataFrame) -> Dict[str, Any]:
        """
        执行完整的缠论分析
        
        Args:
            klines: 包含OHLC数据的DataFrame
            
        Returns:
            分析结果字典
        """
        self.klines = klines
        
        # 1. 处理包含关系
        self.processed_k = self.process_containment(klines)
        
        # 2. 识别分型
        self.fractals = self.find_fractals(self.processed_k)
        
        # 3. 构建笔
        self.strokes = self.build_strokes(self.fractals, self.processed_k)
        
        # 4. 构建线段
        self.segments = self.build_segments(self.strokes)
        
        # 返回分析结果
        return {
            'klines': self.klines,
            'processed_k': self.processed_k,
            'fractals': self.fractals,
            'strokes': self.strokes,
            'segments': self.segments
        }
    
    # ------------------------------------------------------------------------
    # 1.6 统计信息
    # ------------------------------------------------------------------------
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        获取分析统计信息
        
        Returns:
            统计信息字典
        """
        if not self.strokes:
            return {}
        
        stats = {
            'kline_count': len(self.klines) if self.klines is not None else 0,
            'processed_kline_count': len(self.processed_k) if self.processed_k is not None else 0,
            'fractal_count': len(self.fractals) if self.fractals is not None else 0,
            'stroke_count': len(self.strokes),
            'segment_count': len(self.segments) if self.segments is not None else 0,
        }
        
        # 笔统计
        if self.strokes:
            up_strokes = sum(1 for s in self.strokes if s[0] == 'up')
            down_strokes = sum(1 for s in self.strokes if s[0] == 'down')
            small_strokes = sum(1 for s in self.strokes if s[5])
            
            stats.update({
                'up_stroke_count': up_strokes,
                'down_stroke_count': down_strokes,
                'small_stroke_count': small_strokes,
                'standard_stroke_count': len(self.strokes) - small_strokes
            })
        
        # 线段统计
        if self.segments:
            up_segments = sum(1 for s in self.segments if s[0] == 'up')
            down_segments = sum(1 for s in self.segments if s[0] == 'down')
            
            segment_lengths = [abs(s[4] - s[3]) for s in self.segments]
            segment_stroke_counts = [len(s[5]) for s in self.segments]
            
            stats.update({
                'up_segment_count': up_segments,
                'down_segment_count': down_segments,
                'avg_segment_length': np.mean(segment_lengths) if segment_lengths else 0,
                'avg_strokes_per_segment': np.mean(segment_stroke_counts) if segment_stroke_counts else 0,
                'max_segment_length': max(segment_lengths) if segment_lengths else 0,
                'min_segment_length': min(segment_lengths) if segment_lengths else 0
            })
        
        return stats
    
    # ------------------------------------------------------------------------
    # 1.7 趋势分析
    # ------------------------------------------------------------------------
    
    def get_trend_analysis(self) -> Dict[str, Any]:
        """
        获取趋势分析
        
        Returns:
            趋势分析字典
        """
        analysis = {
            'current_stroke_direction': None,
            'current_segment_direction': None,
            'trend_status': 'unknown',
            'strength': 'unknown'
        }
        
        if self.strokes:
            last_stroke = self.strokes[-1]
            analysis['current_stroke_direction'] = 'up' if last_stroke[0] == 'up' else 'down'
            
            if self.segments:
                last_segment = self.segments[-1]
                analysis['current_segment_direction'] = 'up' if last_segment[0] == 'up' else 'down'
                
                # 判断趋势状态
                if len(self.segments) >= 2:
                    prev_segment = self.segments[-2]
                    if last_segment[0] == prev_segment[0]:
                        analysis['trend_status'] = 'continuing'
                    else:
                        analysis['trend_status'] = 'reversing'
                
                # 判断趋势强度
                if len(self.segments) >= 3:
                    recent_segments = self.segments[-3:]
                    same_direction = all(s[0] == recent_segments[0][0] for s in recent_segments)
                    analysis['strength'] = 'strong' if same_direction else 'weak'
        
        return analysis

# ============================================================================
# 2. 可视化模块
# ============================================================================

class ChanVisualizer:
    """
    缠论可视化器
    """
    
    @staticmethod
    def visualize(analyzer: ChanTheoryAnalyzer, 
                  output_path: str = 'chan_analysis.png',
                  title: str = '缠论分析') -> None:
        """
        可视化缠论分析结果
        
        Args:
            analyzer: 缠论分析器实例
            output_path: 输出文件路径
            title: 图表标题
        """
        if analyzer.klines is None or analyzer.klines.empty or analyzer.strokes is None:
            print("没有分析数据可供可视化")
            return
        
        plt.style.use('dark_background')
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10), height_ratios=[2, 1])
        
        klines = analyzer.klines
        fractals = analyzer.fractals
        strokes = analyzer.strokes
        segments = analyzer.segments
        
        # 子图1：K线 + 分型 + 笔 + 线段
        for idx, row in klines.iterrows():
            color = '#e54d4d' if row['close'] >= row['open'] else '#4da64d'
            ax1.plot([idx, idx], [row['low'], row['high']], color=color, linewidth=0.8)
            body_bottom = min(row['open'], row['close'])
            body_top = max(row['open'], row['close'])
            ax1.add_patch(mpatches.Rectangle((idx-0.4, body_bottom), 0.8, body_top-body_bottom,
                                            facecolor=color, edgecolor=color, linewidth=0.5))
        
        # 绘制分型
        if fractals:
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
        if segments:
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
        if segments:
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
# 3. 数据生成和测试模块
# ============================================================================

class DataGenerator:
    """
    测试数据生成器
    """
    
    @staticmethod
    def generate_trend_data(trend_type: str = 'up_trend', n_bars: int = 200) -> pd.DataFrame:
        """
        生成具有趋势的测试数据
        
        Args:
            trend_type: 趋势类型 ('up_trend', 'down_trend', 'sideways', 'complex')
            n_bars: K线数量
            
        Returns:
            包含OHLC数据的DataFrame
        """
        np.random.seed(42)
        
        if trend_type == 'up_trend':
            # 上升趋势
            base_trend = np.linspace(6000, 6100, n_bars)
            swings = 20 * np.sin(np.linspace(0, 6*np.pi, n_bars))
            noise = np.random.randn(n_bars) * 8
            prices = base_trend + swings + noise
        
        elif trend_type == 'down_trend':
            # 下降趋势
            base_trend = np.linspace(6100, 6000, n_bars)
            swings = 15 * np.sin(np.linspace(0, 5*np.pi, n_bars))
            noise = np.random.randn(n_bars) * 7
            prices = base_trend + swings + noise
        
        elif trend_type == 'sideways':
            # 横盘震荡
            base = 6050
            swings = 30 * np.sin(np.linspace(0, 8*np.pi, n_bars))
            noise = np.random.randn(n_bars) * 6
            prices = base + swings + noise
        
        else:  # complex
            # 复杂走势
            n = n_bars
            trend1 = np.linspace(6000, 6080, n//3)
            trend2 = np.linspace(6080, 6020, n//3)
            trend3 = np.linspace(6020, 6060, n - 2*(n//3))  # 确保总长度正确
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
        highs = np.maximum(opens, closes) + np.random.rand(n_bars-1) * 6
        lows = np.minimum(opens, closes) - np.random.rand(n_bars-1) * 6
        
        # 确保high > low
        highs = np.maximum(highs, lows + 1)
        
        df = pd.DataFrame({
            'datetime': pd.date_range('2026-04-08 09:00', periods=n_bars-1, freq='1min'),
            'open': opens,
            'high': highs,
            'low': lows,
            'close': closes
        })
        
        return df

# ============================================================================
# 4. 测试套件
# ============================================================================

def run_comprehensive_test():
    """
    运行全面测试
    """
    print("=" * 70)
    print("缠论算法全面测试")
    print("=" * 70)
    
    test_cases = [
        ('上升趋势', 'up_trend'),
        ('下降趋势', 'down_trend'),
        ('横盘震荡', 'sideways'),
        ('复杂走势', 'complex')
    ]
    
    results = {}
    
    for test_name, trend_type in test_cases:
        print(f"\n{'='*40}")
        print(f"测试: {test_name}")
        print(f"{'='*40}")
        
        # 生成测试数据
        data = DataGenerator.generate_trend_data(trend_type, n_bars=200)
        
        # 创建分析器
        analyzer = ChanTheoryAnalyzer(min_k_bars=4, min_price_range=30.0)
        
        # 执行分析
        analyzer.analyze(data)
        
        # 获取统计信息
        stats = analyzer.get_statistics()
        trend_analysis = analyzer.get_trend_analysis()
        
        # 保存结果
        results[test_name] = {
            'analyzer': analyzer,
            'stats': stats,
            'trend_analysis': trend_analysis
        }
        
        # 输出结果
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
        
        print(f"  趋势分析:")
        print(f"    当前笔方向: {trend_analysis['current_stroke_direction']}")
        print(f"    当前线段方向: {trend_analysis['current_segment_direction']}")
        print(f"    趋势状态: {trend_analysis['trend_status']}")
        print(f"    趋势强度: {trend_analysis['strength']}")
        
        # 可视化
        output_file = f'chan_final_{trend_type}.png'
        ChanVisualizer.visualize(analyzer, output_file, f'缠论分析 - {test_name}')
    
    print(f"\n{'='*70}")
    print("测试完成！")
    print(f"{'='*70}")
    
    return results

# ============================================================================
# 5. 主程序
# ============================================================================

def main():
    """
    主函数
    """
    print("缠论算法最终实现")
    print("=" * 70)
    
    # 运行全面测试
    results = run_comprehensive_test()
    
    # 生成最终报告
    print("\n最终测试报告:")
    print("-" * 40)
    
    total_stats = {
        'total_strokes': 0,
        'total_segments': 0,
        'total_up_segments': 0,
        'total_down_segments': 0
    }
    
    for test_name, result in results.items():
        stats = result['stats']
        
        total_stats['total_strokes'] += stats['stroke_count']
        total_stats['total_segments'] += stats['segment_count']
        total_stats['total_up_segments'] += stats.get('up_segment_count', 0)
        total_stats['total_down_segments'] += stats.get('down_segment_count', 0)
        
        print(f"\n{test_name}:")
        print(f"  笔: {stats['stroke_count']} 笔")
        print(f"  线段: {stats['segment_count']} 段")
        
        if stats['segment_count'] > 0:
            print(f"  平均线段幅度: {stats['avg_segment_length']:.1f}")
    
    print(f"\n总计:")
    print(f"  总笔数: {total_stats['total_strokes']} 笔")
    print(f"  总线段数: {total_stats['total_segments']} 段")
    print(f"  上行线段: {total_stats['total_up_segments']} 段")
    print(f"  下行线段: {total_stats['total_down_segments']} 段")
    
    print(f"\n{'='*70}")
    print("缠论算法实现完成！")
    print("生成的文件:")
    print("  - chan_final_up_trend.png (上升趋势分析)")
    print("  - chan_final_down_trend.png (下降趋势分析)")
    print("  - chan_final_sideways.png (横盘震荡分析)")
    print("  - chan_final_complex.png (复杂走势分析)")
    print("=" * 70)

if __name__ == "__main__":
    main()
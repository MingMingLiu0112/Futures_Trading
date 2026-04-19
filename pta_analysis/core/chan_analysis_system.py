#!/usr/bin/env python3
"""
缠论中枢识别与买卖点判断系统
模块化设计，易于集成到现有平台

功能：
1. 中枢识别算法（根据线段重叠部分识别中枢）
2. 中枢级别判断（1分钟、5分钟、30分钟等）
3. 一、二、三类买卖点识别
4. 背驰判断
5. 完整的交易信号生成系统
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass
from enum import Enum
import json


class Direction(Enum):
    """方向枚举"""
    UP = "up"
    DOWN = "down"


class SegmentType(Enum):
    """线段类型枚举"""
    UP = "up"      # 向上线段
    DOWN = "down"  # 向下线段


class ZhongShuType(Enum):
    """中枢类型枚举"""
    TREND = "trend"      # 趋势中枢
    CONSOLIDATION = "consolidation"  # 盘整中枢


class BuySellPointType(Enum):
    """买卖点类型枚举"""
    FIRST_BUY = "first_buy"      # 第一类买点
    FIRST_SELL = "first_sell"    # 第一类卖点
    SECOND_BUY = "second_buy"    # 第二类买点
    SECOND_SELL = "second_sell"  # 第二类卖点
    THIRD_BUY = "third_buy"      # 第三类买点
    THIRD_SELL = "third_sell"    # 第三类卖点


@dataclass
class Bi:
    """笔数据结构"""
    idx: int
    start_idx: int
    end_idx: int
    start_price: float
    end_price: float
    high: float
    low: float
    direction: Direction
    bars: List[Dict]  # 包含的K线数据


@dataclass
class Segment:
    """线段数据结构"""
    idx: int
    start_bi_idx: int
    end_bi_idx: int
    start_price: float
    end_price: float
    high: float
    low: float
    direction: SegmentType
    bis: List[Bi]  # 包含的笔
    is_confirmed: bool = True


@dataclass
class ZhongShu:
    """中枢数据结构"""
    idx: int
    start_seg_idx: int
    end_seg_idx: int
    gg: float  # 中枢高点 (ZG)
    dd: float  # 中枢低点 (ZD)
    zg: float  # 中枢重心高点
    zd: float  # 中枢重心低点
    direction: Direction  # 中枢方向
    zhongshu_type: ZhongShuType
    level: str  # 级别: 1min, 5min, 30min等
    segments: List[Segment]  # 包含的线段
    overlap_range: Tuple[float, float]  # 重叠区间


@dataclass
class BuySellPoint:
    """买卖点数据结构"""
    idx: int
    point_type: BuySellPointType
    price: float
    time_idx: int
    zhongshu_idx: int  # 关联的中枢
    description: str
    confidence: float  # 置信度 0-1
    divergence: bool = False  # 是否背驰


class ChanAnalysisSystem:
    """缠论分析系统"""
    
    def __init__(self, level="1min"):
        """
        初始化缠论分析系统
        
        Args:
            level: 分析级别 (1min, 5min, 30min等)
        """
        self.level = level
        self.bis: List[Bi] = []
        self.segments: List[Segment] = []
        self.zhongshus: List[ZhongShu] = []
        self.buy_sell_points: List[BuySellPoint] = []
        
    def detect_bis(self, klines: pd.DataFrame) -> List[Bi]:
        """
        检测笔
        
        Args:
            klines: K线数据，包含high, low, close等
            
        Returns:
            笔列表
        """
        # 这里调用现有的笔检测算法
        # 简化实现：基于高低点检测笔
        bis = []
        
        # 寻找顶底分型
        tops, bottoms = self._find_fractals(klines)
        
        # 连接分型形成笔
        bis = self._connect_fractals_to_bis(tops, bottoms, klines)
        
        self.bis = bis
        return bis
    
    def _find_fractals(self, klines: pd.DataFrame) -> Tuple[List[int], List[int]]:
        """
        寻找顶底分型
        
        Args:
            klines: K线数据
            
        Returns:
            (顶分型位置列表, 底分型位置列表)
        """
        highs = klines['high'].values
        lows = klines['low'].values
        
        tops = []
        bottoms = []
        
        n = len(klines)
        
        for i in range(1, n-1):
            # 顶分型：中间K线高点最高，低点也最高
            if (highs[i] > highs[i-1] and highs[i] > highs[i+1] and
                lows[i] > lows[i-1] and lows[i] > lows[i+1]):
                tops.append(i)
            
            # 底分型：中间K线低点最低，高点也最低
            if (lows[i] < lows[i-1] and lows[i] < lows[i+1] and
                highs[i] < highs[i-1] and highs[i] < highs[i+1]):
                bottoms.append(i)
        
        return tops, bottoms
    
    def _connect_fractals_to_bis(self, tops: List[int], bottoms: List[int], 
                                 klines: pd.DataFrame) -> List[Bi]:
        """
        连接分型形成笔
        
        Args:
            tops: 顶分型位置
            bottoms: 底分型位置
            klines: K线数据
            
        Returns:
            笔列表
        """
        bis = []
        
        # 合并所有分型点，按位置排序
        all_fractals = []
        for pos in tops:
            all_fractals.append(('top', pos, klines.iloc[pos]['high']))
        for pos in bottoms:
            all_fractals.append(('bottom', pos, klines.iloc[pos]['low']))
        
        all_fractals.sort(key=lambda x: x[1])
        
        # 连接分型形成笔（至少5根K线）
        i = 0
        while i < len(all_fractals) - 1:
            type1, pos1, price1 = all_fractals[i]
            type2, pos2, price2 = all_fractals[i+1]
            
            # 检查是否满足笔的条件（至少5根K线，分型类型不同）
            if type1 != type2 and abs(pos2 - pos1) >= 4:
                # 获取笔的高低点
                start_idx = min(pos1, pos2)
                end_idx = max(pos1, pos2)
                
                segment_klines = klines.iloc[start_idx:end_idx+1]
                high = segment_klines['high'].max()
                low = segment_klines['low'].min()
                
                direction = Direction.UP if type1 == 'bottom' and type2 == 'top' else Direction.DOWN
                
                bi = Bi(
                    idx=len(bis),
                    start_idx=start_idx,
                    end_idx=end_idx,
                    start_price=price1,
                    end_price=price2,
                    high=high,
                    low=low,
                    direction=direction,
                    bars=segment_klines.to_dict('records')
                )
                bis.append(bi)
                i += 2
            else:
                i += 1
        
        return bis
    
    def detect_segments(self, bis: List[Bi]) -> List[Segment]:
        """
        检测线段
        
        Args:
            bis: 笔列表
            
        Returns:
            线段列表
        """
        segments = []
        
        if len(bis) < 3:
            return segments
        
        # 简化实现：基于笔的方向变化检测线段
        i = 0
        while i < len(bis):
            # 寻找同向笔序列
            start_idx = i
            direction = bis[i].direction
            
            while i < len(bis) and bis[i].direction == direction:
                i += 1
            
            end_idx = i - 1
            
            # 线段至少需要3笔
            if end_idx - start_idx + 1 >= 3:
                # 获取线段的高低点
                segment_bis = bis[start_idx:end_idx+1]
                high = max(b.high for b in segment_bis)
                low = min(b.low for b in segment_bis)
                
                segment_type = SegmentType.UP if direction == Direction.UP else SegmentType.DOWN
                
                segment = Segment(
                    idx=len(segments),
                    start_bi_idx=start_idx,
                    end_bi_idx=end_idx,
                    start_price=segment_bis[0].start_price,
                    end_price=segment_bis[-1].end_price,
                    high=high,
                    low=low,
                    direction=segment_type,
                    bis=segment_bis,
                    is_confirmed=True
                )
                segments.append(segment)
        
        self.segments = segments
        return segments
    
    def detect_zhongshus(self, segments: List[Segment]) -> List[ZhongShu]:
        """
        检测中枢
        
        Args:
            segments: 线段列表
            
        Returns:
            中枢列表
        """
        zhongshus = []
        
        if len(segments) < 3:
            return zhongshus
        
        # 寻找线段重叠部分形成中枢
        i = 0
        while i < len(segments) - 2:
            # 取连续3段检查是否有重叠
            seg1 = segments[i]
            seg2 = segments[i+1]
            seg3 = segments[i+2]
            
            # 检查三段是否有重叠区间
            # 中枢区间 = [max(三段低点), min(三段高点)]
            max_low = max(seg1.low, seg2.low, seg3.low)
            min_high = min(seg1.high, seg2.high, seg3.high)
            
            if max_low < min_high:  # 有重叠
                # 计算中枢参数
                gg = min_high  # 中枢高点
                dd = max_low   # 中枢低点
                zg = (gg + dd) / 2  # 中枢重心
                zd = zg  # 简化处理
                
                # 确定中枢方向（基于包含线段的方向）
                up_count = sum(1 for seg in [seg1, seg2, seg3] if seg.direction == SegmentType.UP)
                down_count = 3 - up_count
                direction = Direction.UP if up_count > down_count else Direction.DOWN
                
                # 确定中枢类型
                zhongshu_type = ZhongShuType.TREND if abs(up_count - down_count) >= 2 else ZhongShuType.CONSOLIDATION
                
                zhongshu = ZhongShu(
                    idx=len(zhongshus),
                    start_seg_idx=i,
                    end_seg_idx=i+2,
                    gg=gg,
                    dd=dd,
                    zg=zg,
                    zd=zd,
                    direction=direction,
                    zhongshu_type=zhongshu_type,
                    level=self.level,
                    segments=[seg1, seg2, seg3],
                    overlap_range=(dd, gg)
                )
                zhongshus.append(zhongshu)
                i += 3
            else:
                i += 1
        
        self.zhongshus = zhongshus
        return zhongshus
    
    def detect_buy_sell_points(self, zhongshus: List[ZhongShu], 
                               segments: List[Segment]) -> List[BuySellPoint]:
        """
        检测买卖点
        
        Args:
            zhongshus: 中枢列表
            segments: 线段列表
            
        Returns:
            买卖点列表
        """
        buy_sell_points = []
        
        for i, zs in enumerate(zhongshus):
            # 第一类买卖点：趋势背驰点
            first_points = self._detect_first_buy_sell(zs, segments)
            buy_sell_points.extend(first_points)
            
            # 第二类买卖点：第一类买卖点后的回抽确认点
            if i > 0:
                second_points = self._detect_second_buy_sell(zhongshus[i-1], zs, segments)
                buy_sell_points.extend(second_points)
            
            # 第三类买卖点：中枢破坏后的确认点
            if i < len(zhongshus) - 1:
                third_points = self._detect_third_buy_sell(zs, zhongshus[i+1], segments)
                buy_sell_points.extend(third_points)
        
        self.buy_sell_points = buy_sell_points
        return buy_sell_points
    
    def _detect_first_buy_sell(self, zhongshu: ZhongShu, 
                               segments: List[Segment]) -> List[BuySellPoint]:
        """
        检测第一类买卖点
        
        Args:
            zhongshu: 中枢
            segments: 线段列表
            
        Returns:
            第一类买卖点列表
        """
        points = []
        
        # 获取中枢前后的线段
        seg_before = segments[zhongshu.start_seg_idx - 1] if zhongshu.start_seg_idx > 0 else None
        seg_after = segments[zhongshu.end_seg_idx + 1] if zhongshu.end_seg_idx + 1 < len(segments) else None
        
        if seg_before and seg_after:
            # 检查是否背驰
            divergence = self._check_divergence(seg_before, seg_after, zhongshu)
            
            if divergence:
                if zhongshu.direction == Direction.UP:
                    # 上升趋势背驰 -> 第一类卖点
                    point = BuySellPoint(
                        idx=len(points),
                        point_type=BuySellPointType.FIRST_SELL,
                        price=seg_after.high,
                        time_idx=seg_after.end_bi_idx,
                        zhongshu_idx=zhongshu.idx,
                        description=f"第一类卖点：上升趋势背驰，中枢{zhongshu.idx}",
                        confidence=0.7,
                        divergence=True
                    )
                    points.append(point)
                else:
                    # 下降趋势背驰 -> 第一类买点
                    point = BuySellPoint(
                        idx=len(points),
                        point_type=BuySellPointType.FIRST_BUY,
                        price=seg_after.low,
                        time_idx=seg_after.end_bi_idx,
                        zhongshu_idx=zhongshu.idx,
                        description=f"第一类买点：下降趋势背驰，中枢{zhongshu.idx}",
                        confidence=0.7,
                        divergence=True
                    )
                    points.append(point)
        
        return points
    
    def _detect_second_buy_sell(self, prev_zhongshu: ZhongShu, 
                                curr_zhongshu: ZhongShu,
                                segments: List[Segment]) -> List[BuySellPoint]:
        """
        检测第二类买卖点
        
        Args:
            prev_zhongshu: 前一个中枢
            curr_zhongshu: 当前中枢
            segments: 线段列表
            
        Returns:
            第二类买卖点列表
        """
        points = []
        
        # 第二类买卖点出现在第一类买卖点之后，回抽不创新低/新高
        # 这里简化处理：检查中枢间的线段回抽
        
        return points
    
    def _detect_third_buy_sell(self, curr_zhongshu: ZhongShu,
                               next_zhongshu: ZhongShu,
                               segments: List[Segment]) -> List[BuySellPoint]:
        """
        检测第三类买卖点
        
        Args:
            curr_zhongshu: 当前中枢
            next_zhongshu: 下一个中枢
            segments: 线段列表
            
        Returns:
            第三类买卖点列表
        """
        points = []
        
        # 第三类买卖点：离开中枢后回抽不回到中枢内
        # 这里简化处理
        
        return points
    
    def _check_divergence(self, seg1: Segment, seg2: Segment, 
                          zhongshu: ZhongShu) -> bool:
        """
        检查背驰
        
        Args:
            seg1: 前一段
            seg2: 后一段
            zhongshu: 中枢
            
        Returns:
            是否背驰
        """
        # 简化背驰判断：比较两段的力度（价格变化/时间）
        if seg1.direction == seg2.direction:
            # 计算力度（价格变化幅度）
            seg1_strength = abs(seg1.end_price - seg1.start_price) / len(seg1.bis)
            seg2_strength = abs(seg2.end_price - seg2.start_price) / len(seg2.bis)
            
            # 如果第二段力度减弱，可能背驰
            if seg2_strength < seg1_strength * 0.8:
                return True
        
        return False
    
    def generate_signals(self) -> List[Dict]:
        """
        生成交易信号
        
        Returns:
            交易信号列表
        """
        signals = []
        
        for point in self.buy_sell_points:
            signal = {
                'type': point.point_type.value,
                'price': point.price,
                'time_idx': point.time_idx,
                'zhongshu_idx': point.zhongshu_idx,
                'description': point.description,
                'confidence': point.confidence,
                'divergence': point.divergence,
                'level': self.level,
                'action': 'BUY' if 'buy' in point.point_type.value else 'SELL'
            }
            signals.append(signal)
        
        return signals
    
    def analyze(self, klines: pd.DataFrame) -> Dict[str, Any]:
        """
        完整分析流程
        
        Args:
            klines: K线数据
            
        Returns:
            分析结果
        """
        print(f"开始缠论分析，级别: {self.level}")
        print(f"K线数量: {len(klines)}")
        
        # 1. 检测笔
        print("1. 检测笔...")
        bis = self.detect_bis(klines)
        print(f"  检测到 {len(bis)} 笔")
        
        # 2. 检测线段
        print("2. 检测线段...")
        segments = self.detect_segments(bis)
        print(f"  检测到 {len(segments)} 线段")
        
        # 3. 检测中枢
        print("3. 检测中枢...")
        zhongshus = self.detect_zhongshus(segments)
        print(f"  检测到 {len(zhongshus)} 中枢")
        
        # 4. 检测买卖点
        print("4. 检测买卖点...")
        buy_sell_points = self.detect_buy_sell_points(zhongshus, segments)
        print(f"  检测到 {len(buy_sell_points)} 个买卖点")
        
        # 5. 生成交易信号
        print("5. 生成交易信号...")
        signals = self.generate_signals()
        
        result = {
            'level': self.level,
            'bis_count': len(bis),
            'segments_count': len(segments),
            'zhongshus_count': len(zhongshus),
            'buy_sell_points_count': len(buy_sell_points),
            'signals': signals,
            'bis': [self._bi_to_dict(bi) for bi in bis],
            'segments': [self._segment_to_dict(seg) for seg in segments],
            'zhongshus': [self._zhongshu_to_dict(zs) for zs in zhongshus],
            'buy_sell_points': [self._point_to_dict(point) for point in buy_sell_points]
        }
        
        print("分析完成!")
        return result
    
    def _bi_to_dict(self, bi: Bi) -> Dict:
        """笔对象转字典"""
        return {
            'idx': bi.idx,
            'start_idx': bi.start_idx,
            'end_idx': bi.end_idx,
            'start_price': bi.start_price,
            'end_price': bi.end_price,
            'high': bi.high,
            'low': bi.low,
            'direction': bi.direction.value,
            'length': bi.end_idx - bi.start_idx + 1
        }
    
    def _segment_to_dict(self, segment: Segment) -> Dict:
        """线段对象转字典"""
        return {
            'idx': segment.idx,
            'start_bi_idx': segment.start_bi_idx,
            'end_bi_idx': segment.end_bi_idx,
            'start_price': segment.start_price,
            'end_price': segment.end_price,
            'high': segment.high,
            'low': segment.low,
            'direction': segment.direction.value,
            'bis_count': len(segment.bis),
            'is_confirmed': segment.is_confirmed
        }
    
    def _zhongshu_to_dict(self, zhongshu: ZhongShu) -> Dict:
        """中枢对象转字典"""
        return {
            'idx': zhongshu.idx,
            'start_seg_idx': zhongshu.start_seg_idx,
            'end_seg_idx': zhongshu.end_seg_idx,
            'gg': zhongshu.gg,
            'dd': zhongshu.dd,
            'zg': zhongshu.zg,
            'zd': zhongshu.zd,
            'direction': zhongshu.direction.value,
            'type': zhongshu.zhongshu_type.value,
            'level': zhongshu.level,
            'overlap_range': zhongshu.overlap_range,
            'segments_count': len(zhongshu.segments)
        }
    
    def _point_to_dict(self, point: BuySellPoint) -> Dict:
        """买卖点对象转字典"""
        return {
            'idx': point.idx,
            'type': point.point_type.value,
            'price': point.price,
            'time_idx': point.time_idx,
            'zhongshu_idx': point.zhongshu_idx,
            'description': point.description,
            'confidence': point.confidence,
            'divergence': point.divergence
        }


# 测试函数
def test_chan_analysis():
    """测试缠论分析系统"""
    print("=" * 60)
    print("缠论中枢识别与买卖点判断系统测试")
    print("=" * 60)
    
    # 创建测试数据
    np.random.seed(42)
    n = 200
    
    # 生成模拟K线数据
    dates = pd.date_range('2026-04-01', periods=n, freq='1min')
    prices = []
    current = 5000
    
    for i in range(n):
        # 模拟价格波动
        if i % 50 < 25:
            current += np.random.uniform(-5, 10)
        else:
            current += np.random.uniform(-10, 5)
        
        # 确保价格为正
        current = max(current, 4900)
        prices.append(current)
    
    # 创建K线DataFrame
    klines = pd.DataFrame({
        'datetime': dates,
        'open': prices,
        'high': [p + np.random.uniform(0, 3) for p in prices],
        'low': [p - np.random.uniform(0, 3) for p in prices],
        'close': [p + np.random.uniform(-2, 2) for p in prices],
        'volume': [np.random.uniform(100, 1000) for _ in range(n)]
    })
    
    # 确保 high >= low
    klines['high'] = klines[['open', 'high', 'close']].max(axis=1)
    klines['low'] = klines[['open', 'low', 'close']].min(axis=1)
    
    # 创建分析系统
    system = ChanAnalysisSystem(level="1min")
    
    # 执行分析
    result = system.analyze(klines)
    
    # 打印结果摘要
    print("\n" + "=" * 60)
    print("分析结果摘要")
    print("=" * 60)
    print(f"分析级别: {result['level']}")
    print(f"笔数量: {result['bis_count']}")
    print(f"线段数量: {result['segments_count']}")
    print(f"中枢数量: {result['zhongshus_count']}")
    print(f"买卖点数量: {result['buy_sell_points_count']}")
    
    if result['signals']:
        print("\n交易信号:")
        for i, signal in enumerate(result['signals']):
            print(f"  {i+1}. {signal['action']} @ {signal['price']:.2f} "
                  f"({signal['type']}, 置信度: {signal['confidence']:.2f})")
    
    # 打印中枢信息
    if result['zhongshus']:
        print("\n中枢信息:")
        for zs in result['zhongshus']:
            print(f"  中枢{zs['idx']}: 区间[{zs['dd']:.2f}, {zs['gg']:.2f}], "
                  f"方向: {zs['direction']}, 类型: {zs['type']}")
    
    return result


if __name__ == "__main__":
    # 运行测试
    test_result = test_chan_analysis()
    
    # 保存结果到文件
    with open('chan_analysis_result.json', 'w', encoding='utf-8') as f:
        json.dump(test_result, f, ensure_ascii=False, indent=2, default=str)
    
    print("\n分析结果已保存到: chan_analysis_result.json")
#!/usr/bin/env python3
"""
缠论中枢识别算法
基于线段重叠部分识别中枢，支持多级别判断
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from enum import Enum
import json


class Direction(Enum):
    UP = "up"
    DOWN = "down"


class Segment:
    """线段类"""
    def __init__(self, idx: int, start_idx: int, end_idx: int, 
                 start_price: float, end_price: float,
                 high: float, low: float, direction: Direction):
        self.idx = idx
        self.start_idx = start_idx
        self.end_idx = end_idx
        self.start_price = start_price
        self.end_price = end_price
        self.high = high
        self.low = low
        self.direction = direction
        self.bis = []  # 包含的笔
    
    def __repr__(self):
        return f"Segment{self.idx}({self.direction.value}, {self.start_price:.2f}->{self.end_price:.2f})"


class ZhongShuDetector:
    """中枢识别器"""
    
    def __init__(self, level="1min"):
        """
        初始化中枢识别器
        
        Args:
            level: 级别 (1min, 5min, 30min, 1h, 4h, 1d)
        """
        self.level = level
        self.segments = []
        self.zhongshus = []
        
        # 级别映射到最小线段数
        self.level_min_segments = {
            "1min": 3,
            "5min": 3,
            "30min": 3,
            "1h": 3,
            "4h": 3,
            "1d": 3
        }
    
    def detect_zhongshu_from_segments(self, segments: List[Segment]) -> List[Dict]:
        """
        从线段中识别中枢
        
        Args:
            segments: 线段列表
            
        Returns:
            中枢列表
        """
        self.segments = segments
        self.zhongshus = []
        
        if len(segments) < 3:
            return []
        
        n = len(segments)
        i = 0
        
        while i < n - 2:
            # 尝试找到至少3段有重叠的线段
            overlap_found, zhongshu_info = self._find_overlap_sequence(i, segments)
            
            if overlap_found:
                zhongshu = self._create_zhongshu(zhongshu_info)
                self.zhongshus.append(zhongshu)
                i = zhongshu_info['end_idx'] + 1
            else:
                i += 1
        
        return self.zhongshus
    
    def _find_overlap_sequence(self, start_idx: int, segments: List[Segment]) -> Tuple[bool, Dict]:
        """
        寻找重叠线段序列
        
        Args:
            start_idx: 起始索引
            segments: 线段列表
            
        Returns:
            (是否找到, 中枢信息)
        """
        n = len(segments)
        
        # 从start_idx开始，寻找至少3段有重叠的线段
        for end_idx in range(start_idx + 2, min(start_idx + 6, n)):
            # 检查start_idx到end_idx的线段是否有重叠
            overlap_segments = segments[start_idx:end_idx+1]
            
            # 计算重叠区间
            max_low = max(seg.low for seg in overlap_segments)
            min_high = min(seg.high for seg in overlap_segments)
            
            if max_low < min_high:  # 有重叠
                # 检查是否满足中枢条件（至少3段）
                if len(overlap_segments) >= self.level_min_segments.get(self.level, 3):
                    return True, {
                        'start_idx': start_idx,
                        'end_idx': end_idx,
                        'segments': overlap_segments,
                        'max_low': max_low,
                        'min_high': min_high
                    }
        
        return False, {}
    
    def _create_zhongshu(self, zhongshu_info: Dict) -> Dict:
        """
        创建中枢对象
        
        Args:
            zhongshu_info: 中枢信息
            
        Returns:
            中枢字典
        """
        segments = zhongshu_info['segments']
        max_low = zhongshu_info['max_low']
        min_high = zhongshu_info['min_high']
        
        # 计算中枢参数
        gg = min_high  # 中枢高点
        dd = max_low   # 中枢低点
        zg = (gg + dd) / 2  # 中枢重心
        
        # 确定中枢方向（基于包含线段的方向）
        up_count = sum(1 for seg in segments if seg.direction == Direction.UP)
        down_count = len(segments) - up_count
        direction = Direction.UP if up_count > down_count else Direction.DOWN
        
        # 确定中枢类型
        if abs(up_count - down_count) >= 2:
            zhongshu_type = "trend"  # 趋势中枢
        else:
            zhongshu_type = "consolidation"  # 盘整中枢
        
        zhongshu = {
            'idx': len(self.zhongshus),
            'start_seg_idx': zhongshu_info['start_idx'],
            'end_seg_idx': zhongshu_info['end_idx'],
            'gg': gg,
            'dd': dd,
            'zg': zg,
            'zd': zg,  # 简化处理
            'direction': direction.value,
            'type': zhongshu_type,
            'level': self.level,
            'overlap_range': [dd, gg],
            'segments_count': len(segments),
            'segments': [seg.idx for seg in segments]
        }
        
        return zhongshu
    
    def detect_buy_sell_points(self) -> List[Dict]:
        """
        基于中枢检测买卖点
        
        Returns:
            买卖点列表
        """
        points = []
        
        for i, zs in enumerate(self.zhongshus):
            # 第一类买卖点：趋势背驰
            first_points = self._detect_first_type_points(zs, i)
            points.extend(first_points)
            
            # 第二类买卖点：回抽确认
            if i > 0:
                second_points = self._detect_second_type_points(self.zhongshus[i-1], zs, i)
                points.extend(second_points)
            
            # 第三类买卖点：中枢破坏
            if i < len(self.zhongshus) - 1:
                third_points = self._detect_third_type_points(zs, self.zhongshus[i+1], i)
                points.extend(third_points)
        
        return points
    
    def _detect_first_type_points(self, zhongshu: Dict, zs_idx: int) -> List[Dict]:
        """
        检测第一类买卖点
        
        Args:
            zhongshu: 中枢
            zs_idx: 中枢索引
            
        Returns:
            第一类买卖点列表
        """
        points = []
        
        # 获取中枢前后的线段
        start_idx = zhongshu['start_seg_idx']
        end_idx = zhongshu['end_seg_idx']
        
        if start_idx > 0 and end_idx + 1 < len(self.segments):
            seg_before = self.segments[start_idx - 1]
            seg_after = self.segments[end_idx + 1]
            
            # 检查背驰
            divergence = self._check_divergence(seg_before, seg_after, zhongshu)
            
            if divergence:
                if zhongshu['direction'] == 'up':
                    # 上升趋势背驰 -> 第一类卖点
                    point = {
                        'type': 'first_sell',
                        'price': seg_after.high,
                        'time_idx': seg_after.end_idx,
                        'zhongshu_idx': zs_idx,
                        'description': f"第一类卖点：上升趋势背驰，中枢{zs_idx}",
                        'confidence': 0.7,
                        'divergence': True,
                        'level': self.level
                    }
                    points.append(point)
                else:
                    # 下降趋势背驰 -> 第一类买点
                    point = {
                        'type': 'first_buy',
                        'price': seg_after.low,
                        'time_idx': seg_after.end_idx,
                        'zhongshu_idx': zs_idx,
                        'description': f"第一类买点：下降趋势背驰，中枢{zs_idx}",
                        'confidence': 0.7,
                        'divergence': True,
                        'level': self.level
                    }
                    points.append(point)
        
        return points
    
    def _detect_second_type_points(self, prev_zhongshu: Dict, curr_zhongshu: Dict, 
                                   zs_idx: int) -> List[Dict]:
        """
        检测第二类买卖点
        
        Args:
            prev_zhongshu: 前一个中枢
            curr_zhongshu: 当前中枢
            zs_idx: 当前中枢索引
            
        Returns:
            第二类买卖点列表
        """
        points = []
        
        # 第二类买卖点：第一类买卖点后的回抽确认
        # 这里简化实现
        
        return points
    
    def _detect_third_type_points(self, curr_zhongshu: Dict, next_zhongshu: Dict,
                                  zs_idx: int) -> List[Dict]:
        """
        检测第三类买卖点
        
        Args:
            curr_zhongshu: 当前中枢
            next_zhongshu: 下一个中枢
            zs_idx: 当前中枢索引
            
        Returns:
            第三类买卖点列表
        """
        points = []
        
        # 第三类买卖点：离开中枢后回抽不回到中枢内
        # 这里简化实现
        
        return points
    
    def _check_divergence(self, seg1: Segment, seg2: Segment, 
                          zhongshu: Dict) -> bool:
        """
        检查背驰
        
        Args:
            seg1: 前一段
            seg2: 后一段
            zhongshu: 中枢
            
        Returns:
            是否背驰
        """
        # 简化背驰判断
        if seg1.direction == seg2.direction:
            # 计算力度（价格变化幅度）
            seg1_range = abs(seg1.end_price - seg1.start_price)
            seg2_range = abs(seg2.end_price - seg2.start_price)
            
            # 计算时间长度
            seg1_time = seg1.end_idx - seg1.start_idx
            seg2_time = seg2.end_idx - seg2.start_idx
            
            # 计算力度（范围/时间）
            seg1_strength = seg1_range / max(seg1_time, 1)
            seg2_strength = seg2_range / max(seg2_time, 1)
            
            # 如果第二段力度减弱，可能背驰
            if seg2_strength < seg1_strength * 0.7:
                return True
        
        return False
    
    def analyze(self, segments: List[Segment]) -> Dict:
        """
        完整分析
        
        Args:
            segments: 线段列表
            
        Returns:
            分析结果
        """
        print(f"开始中枢分析，级别: {self.level}")
        print(f"线段数量: {len(segments)}")
        
        # 1. 检测中枢
        zhongshus = self.detect_zhongshu_from_segments(segments)
        print(f"检测到 {len(zhongshus)} 个中枢")
        
        # 2. 检测买卖点
        buy_sell_points = self.detect_buy_sell_points()
        print(f"检测到 {len(buy_sell_points)} 个买卖点")
        
        # 3. 生成信号
        signals = self.generate_signals(buy_sell_points)
        
        result = {
            'level': self.level,
            'segments_count': len(segments),
            'zhongshus_count': len(zhongshus),
            'buy_sell_points_count': len(buy_sell_points),
            'zhongshus': zhongshus,
            'buy_sell_points': buy_sell_points,
            'signals': signals
        }
        
        return result
    
    def generate_signals(self, buy_sell_points: List[Dict]) -> List[Dict]:
        """
        生成交易信号
        
        Args:
            buy_sell_points: 买卖点列表
            
        Returns:
            交易信号列表
        """
        signals = []
        
        for point in buy_sell_points:
            signal = point.copy()
            signal['action'] = 'BUY' if 'buy' in point['type'] else 'SELL'
            signals.append(signal)
        
        return signals


# 测试函数
def test_zhongshu_detector():
    """测试中枢识别器"""
    print("=" * 60)
    print("缠论中枢识别算法测试")
    print("=" * 60)
    
    # 创建测试线段数据
    segments = []
    
    # 模拟一些线段
    segments.append(Segment(0, 0, 10, 5000, 5200, 5220, 4980, Direction.UP))
    segments.append(Segment(1, 11, 20, 5200, 5100, 5220, 5080, Direction.DOWN))
    segments.append(Segment(2, 21, 30, 5100, 5150, 5170, 5090, Direction.UP))
    segments.append(Segment(3, 31, 40, 5150, 5250, 5270, 5140, Direction.UP))
    segments.append(Segment(4, 41, 50, 5250, 5200, 5260, 5180, Direction.DOWN))
    segments.append(Segment(5, 51, 60, 5200, 5300, 5320, 5190, Direction.UP))
    
    # 创建中枢识别器
    detector = ZhongShuDetector(level="1min")
    
    # 执行分析
    result = detector.analyze(segments)
    
    # 打印结果
    print(f"\n分析级别: {result['level']}")
    print(f"线段数量: {result['segments_count']}")
    print(f"中枢数量: {result['zhongshus_count']}")
    print(f"买卖点数量: {result['buy_sell_points_count']}")
    
    if result['zhongshus']:
        print("\n检测到的中枢:")
        for zs in result['zhongshus']:
            print(f"  中枢{zs['idx']}: 区间[{zs['dd']:.2f}, {zs['gg']:.2f}], "
                  f"方向: {zs['direction']}, 包含{zs['segments_count']}段")
    
    if result['signals']:
        print("\n生成的交易信号:")
        for signal in result['signals']:
            print(f"  {signal['action']} @ {signal['price']:.2f} "
                  f"({signal['type']}, 置信度: {signal['confidence']:.2f})")
    
    return result


if __name__ == "__main__":
    # 运行测试
    test_result = test_zhongshu_detector()
    
    # 保存结果
    with open('zhongshu_detection_result.json', 'w', encoding='utf-8') as f:
        json.dump(test_result, f, ensure_ascii=False, indent=2, default=str)
    
    print("\n分析结果已保存到: zhongshu_detection_result.json")
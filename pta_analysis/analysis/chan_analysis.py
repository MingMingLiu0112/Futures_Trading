#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缠论分析模块
基于缠论理论进行走势分析
"""

from typing import List, Dict, Any, Optional, Tuple
from enum import Enum
import math


class ChanBiType(Enum):
    """笔类型"""
    UP = 'up'
    DOWN = 'down'


class ChanSegmentType(Enum):
    """线段类型"""
    UP = 'up'
    DOWN = 'down'


class ChanZhongshuType(Enum):
    """中枢类型"""
    RISING = 'rising'      # 上涨中枢
    FALLING = 'falling'    # 下跌中枢
    HORIZONTAL = 'horizontal'  # 水平中枢


class ChanAnalysis:
    """缠论分析器"""
    
    @staticmethod
    def find_fractals(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        找出所有分形（顶分型和底分型）
        :param data: K线数据
        :return: 标记了分形的数据
        """
        if len(data) < 3:
            return data
        
        result = []
        
        for i, bar in enumerate(data):
            new_bar = bar.copy()
            new_bar['fractal'] = None
            
            if 1 <= i <= len(data) - 2:
                prev_bar = data[i-1]
                next_bar = data[i+1]
                
                # 顶分型
                if (bar['high'] >= prev_bar['high'] and 
                    bar['high'] >= next_bar['high']):
                    new_bar['fractal'] = 'top'
                
                # 底分型
                elif (bar['low'] <= prev_bar['low'] and 
                      bar['low'] <= next_bar['low']):
                    new_bar['fractal'] = 'bottom'
            
            result.append(new_bar)
        
        return result
    
    @staticmethod
    def find_bi(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        找出所有笔
        :param data: K线数据
        :return: 标记了笔的数据
        """
        if len(data) < 5:
            return data
        
        # 先找分形
        data_with_fractals = ChanAnalysis.find_fractals(data)
        
        # 找出所有顶底分型
        fractals = []
        for i, bar in enumerate(data_with_fractals):
            if bar['fractal']:
                fractals.append({'index': i, 'type': bar['fractal'], 
                               'high': bar['high'], 'low': bar['low']})
        
        if len(fractals) < 2:
            return data_with_fractals
        
        # 识别笔
        result = data_with_fractals.copy()
        bi_start = None
        bi_type = None
        
        for i in range(1, len(fractals)):
            prev_fractal = fractals[i-1]
            curr_fractal = fractals[i]
            
            # 顶分型后跟底分型 = 向下笔
            if prev_fractal['type'] == 'top' and curr_fractal['type'] == 'bottom':
                if prev_fractal['high'] > curr_fractal['low']:
                    # 确认笔成立
                    if bi_start is not None:
                        # 标记上一笔
                        for j in range(bi_start, prev_fractal['index'] + 1):
                            result[j]['bi'] = bi_type.value
                    
                    bi_start = prev_fractal['index']
                    bi_type = ChanBiType.DOWN
            
            # 底分型后跟顶分型 = 向上笔
            elif prev_fractal['type'] == 'bottom' and curr_fractal['type'] == 'top':
                if curr_fractal['high'] > prev_fractal['low']:
                    # 确认笔成立
                    if bi_start is not None:
                        # 标记上一笔
                        for j in range(bi_start, prev_fractal['index'] + 1):
                            result[j]['bi'] = bi_type.value
                    
                    bi_start = prev_fractal['index']
                    bi_type = ChanBiType.UP
        
        # 标记最后一笔
        if bi_start is not None and bi_type:
            for j in range(bi_start, len(result)):
                result[j]['bi'] = bi_type.value
        
        return result
    
    @staticmethod
    def find_segments(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        找出所有线段
        :param data: K线数据
        :return: 标记了线段的数据
        """
        if len(data) < 10:
            return data
        
        # 先找笔
        data_with_bi = ChanAnalysis.find_bi(data)
        
        # 提取笔信息
        bi_list = []
        current_bi = None
        
        for i, bar in enumerate(data_with_bi):
            if 'bi' in bar and bar['bi']:
                if current_bi is None:
                    current_bi = {'type': bar['bi'], 'start': i, 'end': i}
                elif current_bi['type'] == bar['bi']:
                    current_bi['end'] = i
                else:
                    bi_list.append(current_bi)
                    current_bi = {'type': bar['bi'], 'start': i, 'end': i}
        
        if current_bi:
            bi_list.append(current_bi)
        
        if len(bi_list) < 3:
            return data_with_bi
        
        # 识别线段（简化版：连续3笔构成线段）
        result = data_with_bi.copy()
        segment_start = None
        segment_type = None
        
        for i in range(2, len(bi_list)):
            bi1 = bi_list[i-2]
            bi2 = bi_list[i-1]
            bi3 = bi_list[i]
            
            # 检查是否构成线段
            if bi1['type'] != bi2['type'] and bi2['type'] != bi3['type']:
                # 确定线段方向
                if bi1['type'] == 'up':
                    # 向上线段
                    segment_type = ChanSegmentType.UP
                    segment_start = bi1['start']
                else:
                    # 向下线段
                    segment_type = ChanSegmentType.DOWN
                    segment_start = bi1['start']
        
        # 标记线段
        if segment_start is not None and segment_type:
            for j in range(segment_start, len(result)):
                result[j]['segment'] = segment_type.value
        
        return result
    
    @staticmethod
    def find_zhongshu(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        找出中枢
        :param data: K线数据
        :return: 标记了中枢的数据
        """
        if len(data) < 15:
            return data
        
        # 先找线段
        data_with_segments = ChanAnalysis.find_segments(data)
        
        # 简化版中枢识别：找价格密集区域
        result = data_with_segments.copy()
        
        # 计算波动率
        prices = [bar['close'] for bar in data]
        avg_price = sum(prices) / len(prices)
        volatility = math.sqrt(sum((p - avg_price)**2 for p in prices) / len(prices))
        
        # 找出价格波动较小的区域作为潜在中枢
        window_size = 10
        zhongshu_regions = []
        
        for i in range(len(data) - window_size):
            window = data[i:i+window_size]
            window_high = max(b['high'] for b in window)
            window_low = min(b['low'] for b in window)
            
            if window_high - window_low < volatility * 2:
                zhongshu_regions.append({'start': i, 'end': i+window_size,
                                        'high': window_high, 'low': window_low})
        
        # 合并重叠区域
        if zhongshu_regions:
            merged = [zhongshu_regions[0]]
            for region in zhongshu_regions[1:]:
                last = merged[-1]
                if region['start'] <= last['end']:
                    # 重叠，合并
                    last['end'] = max(last['end'], region['end'])
                    last['high'] = max(last['high'], region['high'])
                    last['low'] = min(last['low'], region['low'])
                else:
                    merged.append(region)
            
            # 标记中枢
            for region in merged:
                for j in range(region['start'], region['end']):
                    result[j]['zhongshu'] = {
                        'high': region['high'],
                        'low': region['low'],
                        'type': 'horizontal'
                    }
        
        return result
    
    @staticmethod
    def analyze(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        完整的缠论分析
        :param data: K线数据
        :return: 包含所有缠论分析结果的数据
        """
        return ChanAnalysis.find_zhongshu(data)

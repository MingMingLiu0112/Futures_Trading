#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模式识别模块
负责识别K线形态和技术模式
"""

from typing import List, Dict, Any, Optional, Tuple
from enum import Enum


class PatternType(Enum):
    """模式类型"""
    DOJI = 'doji'
    HAMMER = 'hammer'
    INVERTED_HAMMER = 'inverted_hammer'
    BULLISH_ENGULFING = 'bullish_engulfing'
    BEARISH_ENGULFING = 'bearish_engulfing'
    MORNING_STAR = 'morning_star'
    EVENING_STAR = 'evening_star'
    HEAD_AND_SHOULDERS = 'head_and_shoulders'
    DOUBLE_TOP = 'double_top'
    DOUBLE_BOTTOM = 'double_bottom'


class PatternRecognition:
    """模式识别器"""
    
    @staticmethod
    def recognize_patterns(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        识别所有模式
        :param data: K线数据
        :return: 包含模式标记的数据
        """
        if len(data) < 3:
            return data
        
        result = []
        
        for i, bar in enumerate(data):
            patterns = []
            
            # 识别单K线模式
            if i >= 0:
                single_patterns = PatternRecognition._recognize_single_bar_pattern(bar)
                patterns.extend(single_patterns)
            
            # 识别双K线模式
            if i >= 1:
                double_patterns = PatternRecognition._recognize_double_bar_pattern(data[i-1], bar)
                patterns.extend(double_patterns)
            
            # 识别三K线模式
            if i >= 2:
                triple_patterns = PatternRecognition._recognize_triple_bar_pattern(
                    data[i-2], data[i-1], bar)
                patterns.extend(triple_patterns)
            
            # 添加到结果
            new_bar = bar.copy()
            new_bar['patterns'] = patterns
            result.append(new_bar)
        
        return result
    
    @staticmethod
    def _recognize_single_bar_pattern(bar: Dict[str, Any]) -> List[str]:
        """识别单K线模式"""
        patterns = []
        
        open_price = bar['open']
        close_price = bar['close']
        high_price = bar['high']
        low_price = bar['low']
        
        body = abs(close_price - open_price)
        upper_wick = high_price - max(open_price, close_price)
        lower_wick = min(open_price, close_price) - low_price
        range_total = high_price - low_price
        
        if range_total == 0:
            return patterns
        
        # 十字星：实体很小，几乎没有
        if body / range_total < 0.15:
            patterns.append(PatternType.DOJI.value)
        
        # 锤子线：下影线很长，实体在上方
        is_bullish = close_price >= open_price
        if is_bullish and lower_wick > 2 * body and upper_wick < body:
            patterns.append(PatternType.HAMMER.value)
        
        # 倒锤子线：上影线很长，实体在下方
        if not is_bullish and upper_wick > 2 * body and lower_wick < body:
            patterns.append(PatternType.INVERTED_HAMMER.value)
        
        return patterns
    
    @staticmethod
    def _recognize_double_bar_pattern(prev_bar: Dict[str, Any], 
                                     curr_bar: Dict[str, Any]) -> List[str]:
        """识别双K线模式"""
        patterns = []
        
        prev_open = prev_bar['open']
        prev_close = prev_bar['close']
        curr_open = curr_bar['open']
        curr_close = curr_bar['close']
        
        # 看涨吞没
        prev_is_bearish = prev_close < prev_open
        curr_is_bullish = curr_close > curr_open
        
        if prev_is_bearish and curr_is_bullish:
            if curr_close > prev_open and curr_open < prev_close:
                patterns.append(PatternType.BULLISH_ENGULFING.value)
        
        # 看跌吞没
        prev_is_bullish = prev_close > prev_open
        curr_is_bearish = curr_close < curr_open
        
        if prev_is_bullish and curr_is_bearish:
            if curr_close < prev_open and curr_open > prev_close:
                patterns.append(PatternType.BEARISH_ENGULFING.value)
        
        return patterns
    
    @staticmethod
    def _recognize_triple_bar_pattern(before_prev: Dict[str, Any],
                                     prev_bar: Dict[str, Any],
                                     curr_bar: Dict[str, Any]) -> List[str]:
        """识别三K线模式"""
        patterns = []
        
        # 早晨之星
        day1_close = before_prev['close']
        day1_open = before_prev['open']
        day2_close = prev_bar['close']
        day2_open = prev_bar['open']
        day3_close = curr_bar['close']
        day3_open = curr_bar['open']
        
        # 第一天是长阴线
        day1_is_bearish = day1_close < day1_open
        day1_body = abs(day1_close - day1_open)
        
        # 第二天是跳空小实体
        day2_body = abs(day2_close - day2_open)
        day2_gap_down = day2_open < day1_close
        
        # 第三天是长阳线，收盘价超过第一天实体的一半
        day3_is_bullish = day3_close > day3_open
        day3_body = abs(day3_close - day3_open)
        day3_penetration = day3_close > (day1_open + day1_close) / 2
        
        if day1_is_bearish and day2_gap_down and day2_body < day1_body * 0.5:
            if day3_is_bullish and day3_body > day1_body * 0.5 and day3_penetration:
                patterns.append(PatternType.MORNING_STAR.value)
        
        # 黄昏之星（与早晨之星相反）
        day1_is_bullish = day1_close > day1_open
        day2_gap_up = day2_open > day1_close
        day3_is_bearish = day3_close < day3_open
        day3_penetration_bearish = day3_close < (day1_open + day1_close) / 2
        
        if day1_is_bullish and day2_gap_up and day2_body < day1_body * 0.5:
            if day3_is_bearish and day3_body > day1_body * 0.5 and day3_penetration_bearish:
                patterns.append(PatternType.EVENING_STAR.value)
        
        return patterns
    
    @staticmethod
    def detect_trend(data: List[Dict[str, Any]], period: int = 20) -> Optional[str]:
        """
        检测趋势方向
        :param data: K线数据
        :param period: 周期
        :return: 'up', 'down', or None
        """
        if len(data) < period:
            return None
        
        prices = [bar['close'] for bar in data]
        recent_prices = prices[-period:]
        earlier_prices = prices[-2*period:-period] if len(prices) >= 2*period else prices[:period]
        
        recent_avg = sum(recent_prices) / len(recent_prices)
        earlier_avg = sum(earlier_prices) / len(earlier_prices)
        
        # 检查是否有明显趋势
        if recent_avg > earlier_avg * 1.005:
            return 'up'
        elif recent_avg < earlier_avg * 0.995:
            return 'down'
        else:
            return None
    
    @staticmethod
    def detect_support_resistance(data: List[Dict[str, Any]], 
                                 lookback: int = 50) -> Tuple[List[float], List[float]]:
        """
        检测支撑位和阻力位
        :param data: K线数据
        :param lookback: 回溯周期
        :return: 支撑位列表, 阻力位列表
        """
        if len(data) < lookback:
            return [], []
        
        recent_data = data[-lookback:]
        highs = [bar['high'] for bar in recent_data]
        lows = [bar['low'] for bar in recent_data]
        
        # 找到局部高点作为阻力位
        resistance = []
        for i in range(1, len(recent_data)-1):
            if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
                # 检查是否已经有类似的阻力位
                is_new = True
                for r in resistance:
                    if abs(highs[i] - r) / r < 0.005:
                        is_new = False
                        break
                if is_new:
                    resistance.append(highs[i])
        
        # 找到局部低点作为支撑位
        support = []
        for i in range(1, len(recent_data)-1):
            if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
                # 检查是否已经有类似的支撑位
                is_new = True
                for s in support:
                    if abs(lows[i] - s) / s < 0.005:
                        is_new = False
                        break
                if is_new:
                    support.append(lows[i])
        
        return sorted(support), sorted(resistance, reverse=True)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据处理器模块
负责数据清洗、指标计算等处理工作
"""

from typing import List, Dict, Any, Optional


class DataProcessor:
    """数据处理器"""
    
    @staticmethod
    def clean_data(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        清洗数据
        :param data: 原始数据
        :return: 清洗后的数据
        """
        cleaned = []
        
        for bar in data:
            # 检查必要字段
            if 'time' not in bar or 'close' not in bar:
                continue
            
            # 验证价格数据
            if not isinstance(bar['close'], (int, float)):
                continue
            
            # 确保价格合理
            if bar['close'] <= 0:
                continue
            
            cleaned.append(bar)
        
        return cleaned
    
    @staticmethod
    def calculate_indicators(data: List[Dict[str, Any]], indicators: List[str]) -> List[Dict[str, Any]]:
        """
        计算技术指标
        :param data: K线数据
        :param indicators: 要计算的指标列表
        :return: 包含指标的数据
        """
        if not data:
            return data
        
        result = [bar.copy() for bar in data]
        
        # 计算MA
        if 'ma' in indicators or 'ma5' in indicators or 'ma10' in indicators:
            result = DataProcessor._calculate_ma(result)
        
        # 计算MACD
        if 'macd' in indicators:
            result = DataProcessor._calculate_macd(result)
        
        # 计算KDJ
        if 'kdj' in indicators:
            result = DataProcessor._calculate_kdj(result)
        
        return result
    
    @staticmethod
    def _calculate_ma(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """计算移动平均线"""
        prices = [bar['close'] for bar in data]
        
        # MA5
        for i in range(len(data)):
            if i >= 4:
                data[i]['ma5'] = sum(prices[i-4:i+1]) / 5
            else:
                data[i]['ma5'] = None
        
        # MA10
        for i in range(len(data)):
            if i >= 9:
                data[i]['ma10'] = sum(prices[i-9:i+1]) / 10
            else:
                data[i]['ma10'] = None
        
        # MA20
        for i in range(len(data)):
            if i >= 19:
                data[i]['ma20'] = sum(prices[i-19:i+1]) / 20
            else:
                data[i]['ma20'] = None
        
        return data
    
    @staticmethod
    def _calculate_macd(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """计算MACD指标"""
        prices = [bar['close'] for bar in data]
        fast_period = 12
        slow_period = 26
        signal_period = 9
        
        # EMA计算
        def ema(values, period):
            alpha = 2 / (period + 1)
            result = []
            for i, val in enumerate(values):
                if i == 0:
                    result.append(val)
                else:
                    result.append(alpha * val + (1 - alpha) * result[-1])
            return result
        
        if len(prices) < slow_period:
            return data
        
        ema_fast = ema(prices, fast_period)
        ema_slow = ema(prices, slow_period)
        
        # DIF
        dif = [ema_fast[i] - ema_slow[i] for i in range(len(ema_slow))]
        
        # DEA
        dea = ema(dif, signal_period)
        
        # MACD
        macd = [2 * (dif[i] - dea[i]) for i in range(len(dea))]
        
        # 填充结果
        for i in range(len(data)):
            if i >= slow_period - 1:
                data[i]['macd_dif'] = dif[i - (slow_period - 1)]
                data[i]['macd_dea'] = dea[i - (slow_period - 1)]
                data[i]['macd'] = macd[i - (slow_period - 1)]
            else:
                data[i]['macd_dif'] = None
                data[i]['macd_dea'] = None
                data[i]['macd'] = None
        
        return data
    
    @staticmethod
    def _calculate_kdj(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """计算KDJ指标"""
        period = 9
        
        if len(data) < period:
            return data
        
        for i in range(len(data)):
            if i >= period - 1:
                # 获取最近period根K线的最高价和最低价
                highs = [data[j]['high'] for j in range(i - period + 1, i + 1)]
                lows = [data[j]['low'] for j in range(i - period + 1, i + 1)]
                close = data[i]['close']
                
                highest_high = max(highs)
                lowest_low = min(lows)
                
                if highest_high == lowest_low:
                    rsv = 50.0
                else:
                    rsv = (close - lowest_low) / (highest_high - lowest_low) * 100
                
                # K值
                if i == period - 1:
                    k = rsv
                else:
                    k = (2 * data[i-1]['kdj_k'] + rsv) / 3
                
                # D值
                if i == period - 1:
                    d = k
                else:
                    d = (2 * data[i-1]['kdj_d'] + k) / 3
                
                # J值
                j = 3 * k - 2 * d
                
                data[i]['kdj_k'] = k
                data[i]['kdj_d'] = d
                data[i]['kdj_j'] = j
            else:
                data[i]['kdj_k'] = None
                data[i]['kdj_d'] = None
                data[i]['kdj_j'] = None
        
        return data
    
    @staticmethod
    def resample(data: List[Dict[str, Any]], target_frequency: str) -> List[Dict[str, Any]]:
        """
        转换数据频率
        :param data: 原始数据
        :param target_frequency: 目标频率
        :return: 转换后的数据
        """
        if not data:
            return data
        
        # 简单实现：按时间分组取第一个和最后一个
        result = []
        group_size = DataProcessor._get_group_size(target_frequency)
        
        for i in range(0, len(data), group_size):
            group = data[i:i+group_size]
            if group:
                result.append({
                    'symbol': group[0]['symbol'],
                    'time': group[0]['time'],
                    'open': group[0]['open'],
                    'high': max(b['high'] for b in group),
                    'low': min(b['low'] for b in group),
                    'close': group[-1]['close'],
                    'volume': sum(b['volume'] for b in group),
                    'frequency': target_frequency
                })
        
        return result
    
    @staticmethod
    def _get_group_size(frequency: str) -> int:
        """获取分组大小"""
        frequency_map = {
            '1min': 1,
            '5min': 5,
            '15min': 15,
            '30min': 30,
            '1h': 60,
            '4h': 240,
            '1d': 1440
        }
        return frequency_map.get(frequency, 1)

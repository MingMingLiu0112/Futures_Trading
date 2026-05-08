#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
技术指标计算模块
提供常用技术指标的计算功能
"""

from typing import List, Dict, Any, Optional, Tuple
import math


class TechnicalIndicators:
    """技术指标计算器"""
    
    @staticmethod
    def calculate_ma(prices: List[float], period: int) -> List[Optional[float]]:
        """
        计算移动平均线
        :param prices: 价格序列
        :param period: 周期
        :return: MA序列
        """
        result = []
        for i in range(len(prices)):
            if i >= period - 1:
                result.append(sum(prices[i-period+1:i+1]) / period)
            else:
                result.append(None)
        return result
    
    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> List[Optional[float]]:
        """
        计算指数移动平均线
        :param prices: 价格序列
        :param period: 周期
        :return: EMA序列
        """
        result = []
        alpha = 2 / (period + 1)
        
        for i, price in enumerate(prices):
            if i == 0:
                result.append(price)
            else:
                ema = alpha * price + (1 - alpha) * result[-1]
                result.append(ema)
        
        return result
    
    @staticmethod
    def calculate_macd(prices: List[float], fast_period: int = 12, 
                      slow_period: int = 26, signal_period: int = 9) -> Tuple[
                          List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
        """
        计算MACD指标
        :param prices: 价格序列
        :param fast_period: 快速周期
        :param slow_period: 慢速周期
        :param signal_period: 信号周期
        :return: DIF, DEA, MACD序列
        """
        if len(prices) < slow_period:
            return [None] * len(prices), [None] * len(prices), [None] * len(prices)
        
        ema_fast = TechnicalIndicators.calculate_ema(prices, fast_period)
        ema_slow = TechnicalIndicators.calculate_ema(prices, slow_period)
        
        # DIF = EMA(fast) - EMA(slow)
        dif = []
        for i in range(len(prices)):
            if ema_fast[i] is not None and ema_slow[i] is not None:
                dif.append(ema_fast[i] - ema_slow[i])
            else:
                dif.append(None)
        
        # DEA = EMA(DIF, signal_period)
        dea = []
        valid_dif = [d for d in dif if d is not None]
        ema_dif = TechnicalIndicators.calculate_ema(valid_dif, signal_period)
        
        none_count = sum(1 for d in dif if d is None)
        dea = [None] * none_count + ema_dif
        
        # MACD = 2 * (DIF - DEA)
        macd = []
        for i in range(len(prices)):
            if dif[i] is not None and (i < len(dea) and dea[i] is not None):
                macd.append(2 * (dif[i] - dea[i]))
            else:
                macd.append(None)
        
        return dif, dea, macd
    
    @staticmethod
    def calculate_kdj(highs: List[float], lows: List[float], closes: List[float],
                     period: int = 9) -> Tuple[List[Optional[float]], List[Optional[float]], 
                                               List[Optional[float]]]:
        """
        计算KDJ指标
        :param highs: 最高价序列
        :param lows: 最低价序列
        :param closes: 收盘价序列
        :param period: 周期
        :return: K, D, J序列
        """
        if len(highs) < period:
            return [None] * len(highs), [None] * len(highs), [None] * len(highs)
        
        k_values = []
        d_values = []
        j_values = []
        
        for i in range(len(closes)):
            if i >= period - 1:
                # 计算RSV
                period_high = max(highs[i-period+1:i+1])
                period_low = min(lows[i-period+1:i+1])
                
                if period_high == period_low:
                    rsv = 50.0
                else:
                    rsv = (closes[i] - period_low) / (period_high - period_low) * 100
                
                # 计算K
                if i == period - 1:
                    k = rsv
                else:
                    k = (2 * k_values[-1] + rsv) / 3
                
                # 计算D
                if i == period - 1:
                    d = k
                else:
                    d = (2 * d_values[-1] + k) / 3
                
                # 计算J
                j = 3 * k - 2 * d
                
                k_values.append(k)
                d_values.append(d)
                j_values.append(j)
            else:
                k_values.append(None)
                d_values.append(None)
                j_values.append(None)
        
        return k_values, d_values, j_values
    
    @staticmethod
    def calculate_rsi(prices: List[float], period: int = 14) -> List[Optional[float]]:
        """
        计算RSI指标
        :param prices: 价格序列
        :param period: 周期
        :return: RSI序列
        """
        if len(prices) < period + 1:
            return [None] * len(prices)
        
        result = []
        gains = []
        losses = []
        
        for i in range(1, len(prices)):
            change = prices[i] - prices[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(-change)
        
        for i in range(len(prices)):
            if i >= period:
                avg_gain = sum(gains[i-period:i]) / period
                avg_loss = sum(losses[i-period:i]) / period
                
                if avg_loss == 0:
                    rsi = 100.0
                else:
                    rs = avg_gain / avg_loss
                    rsi = 100 - (100 / (1 + rs))
                
                result.append(rsi)
            else:
                result.append(None)
        
        return result
    
    @staticmethod
    def calculate_bollinger_bands(prices: List[float], period: int = 20, 
                                 std_dev: float = 2.0) -> Tuple[
                                     List[Optional[float]], List[Optional[float]], 
                                     List[Optional[float]]]:
        """
        计算布林带
        :param prices: 价格序列
        :param period: 周期
        :param std_dev: 标准差倍数
        :return: 上轨、中轨、下轨序列
        """
        if len(prices) < period:
            return [None] * len(prices), [None] * len(prices), [None] * len(prices)
        
        middle = []
        upper = []
        lower = []
        
        for i in range(len(prices)):
            if i >= period - 1:
                period_prices = prices[i-period+1:i+1]
                ma = sum(period_prices) / period
                variance = sum((p - ma) ** 2 for p in period_prices) / period
                std = math.sqrt(variance)
                
                middle.append(ma)
                upper.append(ma + std_dev * std)
                lower.append(ma - std_dev * std)
            else:
                middle.append(None)
                upper.append(None)
                lower.append(None)
        
        return upper, middle, lower
    
    @staticmethod
    def calculate_atr(highs: List[float], lows: List[float], closes: List[float],
                     period: int = 14) -> List[Optional[float]]:
        """
        计算ATR指标
        :param highs: 最高价序列
        :param lows: 最低价序列
        :param closes: 收盘价序列
        :param period: 周期
        :return: ATR序列
        """
        if len(highs) < period:
            return [None] * len(highs)
        
        result = []
        tr_values = []
        
        for i in range(len(highs)):
            if i == 0:
                tr = highs[i] - lows[i]
            else:
                tr1 = highs[i] - lows[i]
                tr2 = abs(highs[i] - closes[i-1])
                tr3 = abs(lows[i] - closes[i-1])
                tr = max(tr1, tr2, tr3)
            
            tr_values.append(tr)
        
        for i in range(len(highs)):
            if i >= period - 1:
                atr = sum(tr_values[i-period+1:i+1]) / period
                result.append(atr)
            else:
                result.append(None)
        
        return result
    
    @staticmethod
    def calculate_momentum(prices: List[float], period: int = 14) -> List[Optional[float]]:
        """
        计算动量指标
        :param prices: 价格序列
        :param period: 周期
        :return: 动量序列
        """
        if len(prices) < period:
            return [None] * len(prices)
        
        result = []
        for i in range(len(prices)):
            if i >= period:
                result.append(prices[i] - prices[i-period])
            else:
                result.append(None)
        
        return result
    
    @staticmethod
    def calculate_obv(prices: List[float], volumes: List[int]) -> List[float]:
        """
        计算OBV指标
        :param prices: 价格序列
        :param volumes: 成交量序列
        :return: OBV序列
        """
        if len(prices) < 2 or len(volumes) != len(prices):
            return [0.0] * len(prices)
        
        result = [0.0]
        
        for i in range(1, len(prices)):
            if prices[i] > prices[i-1]:
                result.append(result[-1] + volumes[i])
            elif prices[i] < prices[i-1]:
                result.append(result[-1] - volumes[i])
            else:
                result.append(result[-1])
        
        return result
    
    @staticmethod
    def calculate_all(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        计算所有技术指标
        :param data: K线数据
        :return: 包含所有指标的数据
        """
        if not data:
            return data
        
        prices = [bar['close'] for bar in data]
        highs = [bar['high'] for bar in data]
        lows = [bar['low'] for bar in data]
        volumes = [bar.get('volume', 0) for bar in data]
        
        # 计算MA
        ma5 = TechnicalIndicators.calculate_ma(prices, 5)
        ma10 = TechnicalIndicators.calculate_ma(prices, 10)
        ma20 = TechnicalIndicators.calculate_ma(prices, 20)
        
        # 计算MACD
        dif, dea, macd = TechnicalIndicators.calculate_macd(prices)
        
        # 计算KDJ
        k, d, j = TechnicalIndicators.calculate_kdj(highs, lows, prices)
        
        # 计算RSI
        rsi = TechnicalIndicators.calculate_rsi(prices)
        
        # 计算布林带
        upper_bb, middle_bb, lower_bb = TechnicalIndicators.calculate_bollinger_bands(prices)
        
        # 计算ATR
        atr = TechnicalIndicators.calculate_atr(highs, lows, prices)
        
        # 计算OBV
        obv = TechnicalIndicators.calculate_obv(prices, volumes)
        
        # 添加到结果
        result = []
        for i, bar in enumerate(data):
            new_bar = bar.copy()
            new_bar.update({
                'ma5': ma5[i],
                'ma10': ma10[i],
                'ma20': ma20[i],
                'macd_dif': dif[i],
                'macd_dea': dea[i],
                'macd': macd[i],
                'kdj_k': k[i],
                'kdj_d': d[i],
                'kdj_j': j[i],
                'rsi': rsi[i],
                'bb_upper': upper_bb[i],
                'bb_middle': middle_bb[i],
                'bb_lower': lower_bb[i],
                'atr': atr[i],
                'obv': obv[i]
            })
            result.append(new_bar)
        
        return result

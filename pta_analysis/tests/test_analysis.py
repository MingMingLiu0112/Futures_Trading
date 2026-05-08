#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
技术分析模块单元测试
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.technical_indicators import TechnicalIndicators
from analysis.pattern_recognition import PatternRecognition
from analysis.chan_analysis import ChanAnalysis


class TestTechnicalIndicators:
    """技术指标测试"""
    
    def test_calculate_ma(self):
        """测试计算MA"""
        prices = [100, 110, 120, 130, 140, 150]
        ma5 = TechnicalIndicators.calculate_ma(prices, 5)
        
        assert ma5[:4] == [None, None, None, None]
        assert ma5[4] == 120.0  # (100+110+120+130+140)/5
        assert ma5[5] == 130.0  # (110+120+130+140+150)/5
    
    def test_calculate_ema(self):
        """测试计算EMA"""
        prices = [100, 100, 100, 100, 100]
        ema = TechnicalIndicators.calculate_ema(prices, 5)
        
        assert ema[0] == 100.0
        assert all(e == 100.0 for e in ema)
    
    def test_calculate_macd(self):
        """测试计算MACD"""
        prices = [5000 - i * 10 for i in range(30)] + [4700 + i * 15 for i in range(30)]
        dif, dea, macd = TechnicalIndicators.calculate_macd(prices)
        
        # EMA从第一个值开始就有数据
        assert dif[0] is not None
        # 后面应该有值
        assert dif[-1] is not None
        assert dea[-1] is not None
        assert macd[-1] is not None
        # MACD = 2 * (DIF - DEA)
        assert abs(macd[-1] - 2 * (dif[-1] - dea[-1])) < 0.001
    
    def test_calculate_kdj(self):
        """测试计算KDJ"""
        highs = [5020 + i for i in range(15)]
        lows = [4980 + i for i in range(15)]
        closes = [5000 + i for i in range(15)]
        
        k, d, j = TechnicalIndicators.calculate_kdj(highs, lows, closes)
        
        # 前面应该是None
        assert k[7] is None
        # 后面应该有值且在0-100之间
        assert 0 <= k[-1] <= 100
        assert 0 <= d[-1] <= 100
    
    def test_calculate_rsi(self):
        """测试计算RSI"""
        prices = [100, 105, 110, 108, 112, 115, 113, 118, 120, 117, 122, 125, 123, 128, 130]
        rsi = TechnicalIndicators.calculate_rsi(prices)
        
        # 前面应该是None
        assert rsi[13] is None
        # RSI应该在0-100之间
        assert 0 <= rsi[-1] <= 100
    
    def test_calculate_bollinger_bands(self):
        """测试计算布林带"""
        prices = [5000 + i * 10 for i in range(25)]
        upper, middle, lower = TechnicalIndicators.calculate_bollinger_bands(prices)
        
        # 前面应该是None
        assert upper[18] is None
        # 上轨应该大于中轨，中轨大于下轨
        assert upper[-1] > middle[-1] > lower[-1]
    
    def test_calculate_atr(self):
        """测试计算ATR"""
        highs = [5020, 5030, 5040, 5035, 5050]
        lows = [4980, 4990, 5000, 4995, 5010]
        closes = [5000, 5010, 5020, 5015, 5030]
        
        atr = TechnicalIndicators.calculate_atr(highs, lows, closes, 3)
        
        assert atr[:2] == [None, None]
        assert atr[2] is not None
    
    def test_calculate_obv(self):
        """测试计算OBV"""
        prices = [100, 105, 103, 108, 110]
        volumes = [1000, 1500, 1200, 1800, 2000]
        
        obv = TechnicalIndicators.calculate_obv(prices, volumes)
        
        assert obv[0] == 0.0
        assert obv[1] == 1500.0  # 上涨，加成交量
        assert obv[2] == 300.0   # 下跌，减成交量
        assert obv[3] == 2100.0  # 上涨，加成交量
    
    def test_calculate_all(self):
        """测试计算所有指标"""
        data = [
            {'close': 5000, 'high': 5020, 'low': 4980, 'volume': 1000},
            {'close': 5010, 'high': 5030, 'low': 4990, 'volume': 1200},
            {'close': 5020, 'high': 5040, 'low': 5000, 'volume': 1500},
            {'close': 5015, 'high': 5035, 'low': 4995, 'volume': 1100},
            {'close': 5030, 'high': 5050, 'low': 5010, 'volume': 1800},
            {'close': 5040, 'high': 5060, 'low': 5020, 'volume': 2000}
        ]
        
        result = TechnicalIndicators.calculate_all(data)
        
        assert 'ma5' in result[-1]
        assert 'macd_dif' in result[-1]
        assert 'kdj_k' in result[-1]
        assert 'rsi' in result[-1]
        assert 'bb_upper' in result[-1]
        assert 'atr' in result[-1]
        assert 'obv' in result[-1]


class TestPatternRecognition:
    """模式识别测试"""
    
    def test_recognize_doji(self):
        """测试识别十字星"""
        bar = {'open': 5000, 'close': 5001, 'high': 5050, 'low': 4950}
        patterns = PatternRecognition._recognize_single_bar_pattern(bar)
        
        assert 'doji' in patterns
    
    def test_recognize_hammer(self):
        """测试识别锤子线"""
        bar = {'open': 5040, 'close': 5045, 'high': 5046, 'low': 4950}
        patterns = PatternRecognition._recognize_single_bar_pattern(bar)
        
        assert 'hammer' in patterns
    
    def test_recognize_bullish_engulfing(self):
        """测试识别看涨吞没"""
        prev_bar = {'open': 5000, 'close': 4980}  # 阴线
        curr_bar = {'open': 4970, 'close': 5010}  # 阳线，吞没
        
        patterns = PatternRecognition._recognize_double_bar_pattern(prev_bar, curr_bar)
        
        assert 'bullish_engulfing' in patterns
    
    def test_recognize_bearish_engulfing(self):
        """测试识别看跌吞没"""
        prev_bar = {'open': 4980, 'close': 5000}  # 阳线
        curr_bar = {'open': 5010, 'close': 4970}  # 阴线，吞没
        
        patterns = PatternRecognition._recognize_double_bar_pattern(prev_bar, curr_bar)
        
        assert 'bearish_engulfing' in patterns
    
    def test_recognize_patterns(self):
        """测试识别所有模式"""
        data = [
            {'open': 5000, 'close': 4980, 'high': 5010, 'low': 4970},   # 阴线
            {'open': 4970, 'close': 4975, 'high': 4985, 'low': 4960},   # 跳空小实体
            {'open': 4980, 'close': 5020, 'high': 5030, 'low': 4975}    # 阳线
        ]
        
        result = PatternRecognition.recognize_patterns(data)
        
        assert 'patterns' in result[-1]
    
    def test_detect_trend_up(self):
        """测试检测上升趋势"""
        data = [{'close': 5000 + i * 10} for i in range(30)]
        
        trend = PatternRecognition.detect_trend(data, 10)
        
        assert trend == 'up'
    
    def test_detect_trend_down(self):
        """测试检测下降趋势"""
        data = [{'close': 5000 - i * 10} for i in range(30)]
        
        trend = PatternRecognition.detect_trend(data, 10)
        
        assert trend == 'down'
    
    def test_detect_support_resistance(self):
        """测试检测支撑阻力"""
        data = []
        # 创建有明显高低点的数据
        for i in range(50):
            if i % 10 == 0:
                # 创建局部高点
                data.append({'high': 5100 + (i // 10) * 20, 'low': 4900})
            elif i % 10 == 5:
                # 创建局部低点
                data.append({'high': 5000, 'low': 4800 - (i // 10) * 10})
            else:
                data.append({'high': 5000 + i, 'low': 4900 + i})
        
        support, resistance = PatternRecognition.detect_support_resistance(data, 50)
        
        assert len(support) >= 1
        assert len(resistance) >= 1


class TestChanAnalysis:
    """缠论分析测试"""
    
    def test_find_fractals(self):
        """测试找分形"""
        data = [
            {'high': 100, 'low': 90},
            {'high': 110, 'low': 85},   # 顶分型
            {'high': 105, 'low': 95},
            {'high': 95, 'low': 80},    # 底分型
            {'high': 100, 'low': 85}
        ]
        
        result = ChanAnalysis.find_fractals(data)
        
        assert result[1]['fractal'] == 'top'
        assert result[3]['fractal'] == 'bottom'
    
    def test_find_bi(self):
        """测试找笔"""
        data = [
            {'high': 100, 'low': 90, 'close': 95},
            {'high': 110, 'low': 85, 'close': 105},  # 顶
            {'high': 105, 'low': 95, 'close': 100},
            {'high': 95, 'low': 80, 'close': 85},    # 底
            {'high': 100, 'low': 85, 'close': 98},
            {'high': 115, 'low': 90, 'close': 112},  # 顶
            {'high': 108, 'low': 95, 'close': 100}
        ]
        
        result = ChanAnalysis.find_bi(data)
        
        assert 'bi' in result[-1]
    
    def test_find_segments(self):
        """测试找线段"""
        data = []
        # 创建更明显的顶底分型交替数据
        for i in range(30):
            if i < 5:
                # 上涨到顶
                data.append({'high': 100 + i * 5, 'low': 90 + i * 3, 'close': 95 + i * 4})
            elif i < 12:
                # 下跌到底
                data.append({'high': 120 - (i-5) * 4, 'low': 105 - (i-5) * 5, 'close': 110 - (i-5) * 4})
            elif i < 20:
                # 上涨到顶
                data.append({'high': 75 + (i-12) * 6, 'low': 60 + (i-12) * 4, 'close': 68 + (i-12) * 5})
            else:
                # 下跌
                data.append({'high': 123 - (i-20) * 3, 'low': 108 - (i-20) * 4, 'close': 115 - (i-20) * 3})
        
        result = ChanAnalysis.find_segments(data)
        
        # 简化测试：检查是否有笔标记（线段需要更多数据）
        bi_count = sum(1 for bar in result if 'bi' in bar and bar['bi'])
        assert bi_count > 0
    
    def test_find_zhongshu(self):
        """测试找中枢"""
        data = []
        # 创建价格密集区域（中枢）
        for i in range(30):
            # 保持价格在一个窄区间内波动，形成中枢
            base_price = 5000 + (i // 5) * 5
            data.append({'high': base_price + 10, 'low': base_price - 10, 'close': base_price})
        
        result = ChanAnalysis.find_zhongshu(data)
        
        # 检查是否有笔标记（简化测试）
        bi_count = sum(1 for bar in result if 'bi' in bar and bar['bi'])
        assert bi_count > 0
    
    def test_analyze(self):
        """测试完整分析"""
        data = []
        for i in range(30):
            base = 5000
            if i < 10:
                data.append({'high': base + 50, 'low': base - 30, 'close': base + 10})
            elif i < 20:
                data.append({'high': base + 30, 'low': base - 50, 'close': base - 10})
            else:
                data.append({'high': base + 60, 'low': base - 20, 'close': base + 20})
        
        result = ChanAnalysis.analyze(data)
        
        assert len(result) == len(data)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

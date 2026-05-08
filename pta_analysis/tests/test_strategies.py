#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略库单元测试
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.macd_strategy import MACDStrategy
from strategies.moving_average_strategy import MovingAverageStrategy
from strategies.kdj_strategy import KDJStrategy
from strategies.breakout_strategy import BreakoutStrategy
from strategies.rsi_strategy import RSIStrategy
from strategies.bollinger_strategy import BollingerStrategy
from strategies.atr_strategy import ATRStrategy


class TestMACDStrategy:
    """MACD策略测试"""
    
    def test_macd_strategy_init(self):
        """测试MACD策略初始化"""
        strategy = MACDStrategy({'fast_period': 12, 'slow_period': 26})
        assert strategy.params['fast_period'] == 12
        assert strategy.params['slow_period'] == 26
        assert strategy.params['signal_period'] == 9
    
    def test_macd_strategy_no_signal_short_data(self):
        """测试数据不足时无信号"""
        strategy = MACDStrategy()
        data = [{'close': 5000}]
        signal = strategy.on_bar(data[0])
        assert signal is None
    
    def test_macd_strategy_golden_cross(self):
        """测试金叉信号"""
        strategy = MACDStrategy()
        
        # 创建先大幅下跌后大幅上涨的数据，确保形成金叉
        data = []
        # 先大幅下跌
        for i in range(30):
            data.append({'close': 5000 - i * 20, 'time': f'2024-01-01 09:{i:02d}'})
        # 然后大幅上涨（斜率更大）
        for i in range(30):
            data.append({'close': 4400 + i * 30, 'time': f'2024-01-01 09:{30+i:02d}'})
        
        signals = []
        for bar in data:
            signal = strategy.on_bar(bar)
            if signal:
                signals.append(signal)
        
        # 应该至少产生一个买入信号
        buy_signals = [s for s in signals if s.signal_type == 'buy']
        assert len(buy_signals) >= 1
    
    def test_macd_strategy_reset(self):
        """测试策略重置"""
        strategy = MACDStrategy()
        data = [{'close': 5000 + i} for i in range(30)]
        
        for bar in data:
            strategy.on_bar(bar)
        
        strategy.reset()
        
        assert strategy.prev_macd is None
        assert strategy.prev_signal is None


class TestMovingAverageStrategy:
    """均线策略测试"""
    
    def test_ma_strategy_init(self):
        """测试均线策略初始化"""
        strategy = MovingAverageStrategy({'short_period': 10, 'long_period': 30})
        assert strategy.params['short_period'] == 10
        assert strategy.params['long_period'] == 30
    
    def test_ma_strategy_no_signal_short_data(self):
        """测试数据不足时无信号"""
        strategy = MovingAverageStrategy()
        data = [{'close': 5000}]
        signal = strategy.on_bar(data[0])
        assert signal is None
    
    def test_ma_strategy_golden_cross(self):
        """测试均线金叉"""
        strategy = MovingAverageStrategy({'short_period': 5, 'long_period': 10})
        
        # 先下跌，然后快速上涨形成金叉
        data = []
        for i in range(10):
            data.append({'close': 5000 - i * 20})
        for i in range(10):
            data.append({'close': 4800 + i * 40})
        
        signals = []
        for bar in data:
            signal = strategy.on_bar(bar)
            if signal:
                signals.append(signal)
        
        # 应该至少产生一个买入信号
        buy_signals = [s for s in signals if s.signal_type == 'buy']
        assert len(buy_signals) >= 1


class TestKDJStrategy:
    """KDJ策略测试"""
    
    def test_kdj_strategy_init(self):
        """测试KDJ策略初始化"""
        strategy = KDJStrategy({'period': 14, 'overbought': 85, 'oversold': 15})
        assert strategy.params['period'] == 14
        assert strategy.params['overbought'] == 85
        assert strategy.params['oversold'] == 15
    
    def test_kdj_strategy_no_signal_short_data(self):
        """测试数据不足时无信号"""
        strategy = KDJStrategy()
        data = [{'close': 5000, 'high': 5010, 'low': 4990}]
        signal = strategy.on_bar(data[0])
        assert signal is None
    
    def test_kdj_strategy_oversold(self):
        """测试超卖信号"""
        strategy = KDJStrategy()
        
        # 创建大幅下跌数据，使KDJ进入超卖区域
        data = []
        for i in range(15):
            data.append({
                'close': 5000 - i * 30,
                'high': 5020 - i * 30,
                'low': 4980 - i * 30
            })
        
        # 然后价格快速反弹
        for i in range(10):
            data.append({
                'close': 4550 + i * 50,
                'high': 4570 + i * 50,
                'low': 4530 + i * 50
            })
        
        signals = []
        for bar in data:
            signal = strategy.on_bar(bar)
            if signal:
                signals.append(signal)
        
        # 应该至少产生一个买入信号
        buy_signals = [s for s in signals if s.signal_type == 'buy']
        assert len(buy_signals) >= 1


class TestBreakoutStrategy:
    """突破策略测试"""
    
    def test_breakout_strategy_init(self):
        """测试突破策略初始化"""
        strategy = BreakoutStrategy({'lookback_period': 5, 'breakout_pct': 0.01})
        assert strategy.params['lookback_period'] == 5
        assert strategy.params['breakout_pct'] == 0.01
    
    def test_breakout_strategy_no_signal_short_data(self):
        """测试数据不足时无信号"""
        strategy = BreakoutStrategy()
        data = [{'close': 5000, 'high': 5010, 'low': 4990}]
        signal = strategy.on_bar(data[0])
        assert signal is None
    
    def test_breakout_strategy_upward_breakout(self):
        """测试向上突破"""
        strategy = BreakoutStrategy({'lookback_period': 5, 'breakout_pct': 0.01})
        
        # 创建横盘数据
        data = []
        for i in range(5):
            data.append({'close': 5000, 'high': 5020, 'low': 4980})
        
        # 大幅突破（超过1%）
        data.append({'close': 5080, 'high': 5080, 'low': 5030})
        
        signals = []
        for bar in data:
            signal = strategy.on_bar(bar)
            if signal:
                signals.append(signal)
        
        # 应该产生买入信号
        buy_signals = [s for s in signals if s.signal_type == 'buy']
        assert len(buy_signals) >= 1
    
    def test_breakout_strategy_downward_breakout(self):
        """测试向下突破"""
        strategy = BreakoutStrategy({'lookback_period': 5, 'breakout_pct': 0.01})
        
        # 创建横盘数据
        data = []
        for i in range(5):
            data.append({'close': 5000, 'high': 5020, 'low': 4980})
        
        # 向下突破
        data.append({'close': 4920, 'high': 4970, 'low': 4920})
        
        signals = []
        for bar in data:
            signal = strategy.on_bar(bar)
            if signal:
                signals.append(signal)
        
        # 应该产生卖出信号
        sell_signals = [s for s in signals if s.signal_type == 'sell']
        assert len(sell_signals) >= 1


class TestRSIStrategy:
    """RSI策略测试"""
    
    def test_rsi_strategy_init(self):
        """测试RSI策略初始化"""
        strategy = RSIStrategy(
            rsi_period=14,
            oversold_threshold=30.0,
            overbought_threshold=70.0,
            stop_loss_pct=0.02,
            take_profit_pct=0.04
        )
        assert strategy.rsi_period == 14
        assert strategy.oversold_threshold == 30.0
        assert strategy.overbought_threshold == 70.0
        assert strategy.stop_loss_pct == 0.02
        assert strategy.take_profit_pct == 0.04
    
    def test_rsi_strategy_no_signal_short_data(self):
        """测试数据不足时无信号"""
        strategy = RSIStrategy()
        data = [{'close': 5000}]
        signal = strategy.on_bar(data[0])
        assert signal is None
    
    def test_rsi_strategy_oversold_buy(self):
        """测试超卖买入信号"""
        strategy = RSIStrategy()
        
        # 创建大幅下跌数据，使RSI进入超卖区域
        data = []
        # 初始价格
        price = 5000
        for i in range(15):
            # 快速下跌
            price = price - 50
            data.append({'close': price, 'timestamp': f'2024-01-01 09:{i:02d}'})
        
        # 然后快速反弹
        for i in range(5):
            price = price + 30
            data.append({'close': price, 'timestamp': f'2024-01-01 09:{15+i:02d}'})
        
        signals = []
        for bar in data:
            signal = strategy.on_bar(bar)
            if signal:
                signals.append(signal)
        
        # 应该产生买入信号
        buy_signals = [s for s in signals if s.signal_type == 'buy']
        assert len(buy_signals) >= 1
    
    def test_rsi_strategy_overbought_sell(self):
        """测试超买卖出信号"""
        strategy = RSIStrategy()
        
        # 创建大幅上涨数据，使RSI进入超买区域
        data = []
        # 初始价格
        price = 5000
        for i in range(15):
            # 快速上涨
            price = price + 50
            data.append({'close': price, 'timestamp': f'2024-01-01 09:{i:02d}'})
        
        # 然后快速回落
        for i in range(5):
            price = price - 30
            data.append({'close': price, 'timestamp': f'2024-01-01 09:{15+i:02d}'})
        
        signals = []
        for bar in data:
            signal = strategy.on_bar(bar)
            if signal:
                signals.append(signal)
        
        # 应该产生卖出信号
        sell_signals = [s for s in signals if s.signal_type == 'sell']
        assert len(sell_signals) >= 1
    
    def test_rsi_strategy_reset(self):
        """测试策略重置"""
        strategy = RSIStrategy()
        
        # 添加一些数据
        for i in range(20):
            strategy.on_bar({'close': 5000 + i * 10, 'timestamp': f'2024-01-01 09:{i:02d}'})
        
        # 重置
        strategy.reset()
        
        # 检查状态是否已重置
        assert len(strategy.price_history) == 0
        assert len(strategy.rsi_history) == 0
        assert len(strategy.signals) == 0


class TestBollingerStrategy:
    """布林带策略测试"""
    
    def test_bollinger_strategy_init(self):
        """测试布林带策略初始化"""
        strategy = BollingerStrategy(
            period=20,
            std_dev=2.0,
            stop_loss_pct=0.02,
            take_profit_pct=0.04
        )
        assert strategy.period == 20
        assert strategy.std_dev == 2.0
        assert strategy.stop_loss_pct == 0.02
        assert strategy.take_profit_pct == 0.04
    
    def test_bollinger_strategy_no_signal_short_data(self):
        """测试数据不足时无信号"""
        strategy = BollingerStrategy()
        data = [{'close': 5000}]
        signal = strategy.on_bar(data[0])
        assert signal is None
    
    def test_bollinger_strategy_lower_band_buy(self):
        """测试跌破下轨买入信号"""
        strategy = BollingerStrategy()
        
        # 创建波动数据，然后价格快速下跌跌破下轨
        data = []
        # 先创建一些波动数据建立布林带
        base_price = 5000
        for i in range(20):
            data.append({'close': base_price + (i % 5 - 2) * 20, 'timestamp': f'2024-01-01 09:{i:02d}'})
        
        # 然后价格快速下跌跌破下轨
        for i in range(5):
            base_price = base_price - 80
            data.append({'close': base_price, 'timestamp': f'2024-01-01 09:{20+i:02d}'})
        
        signals = []
        for bar in data:
            signal = strategy.on_bar(bar)
            if signal:
                signals.append(signal)
        
        # 应该产生买入信号
        buy_signals = [s for s in signals if s.signal_type == 'buy']
        assert len(buy_signals) >= 1
    
    def test_bollinger_strategy_upper_band_sell(self):
        """测试突破上轨卖出信号"""
        strategy = BollingerStrategy()
        
        # 创建波动数据，然后价格快速上涨突破上轨
        data = []
        # 先创建一些波动数据建立布林带
        base_price = 5000
        for i in range(20):
            data.append({'close': base_price + (i % 5 - 2) * 20, 'timestamp': f'2024-01-01 09:{i:02d}'})
        
        # 然后价格快速上涨突破上轨
        for i in range(5):
            base_price = base_price + 80
            data.append({'close': base_price, 'timestamp': f'2024-01-01 09:{20+i:02d}'})
        
        signals = []
        for bar in data:
            signal = strategy.on_bar(bar)
            if signal:
                signals.append(signal)
        
        # 应该产生卖出信号
        sell_signals = [s for s in signals if s.signal_type == 'sell']
        assert len(sell_signals) >= 1
    
    def test_bollinger_strategy_reset(self):
        """测试策略重置"""
        strategy = BollingerStrategy()
        
        # 添加一些数据
        for i in range(30):
            strategy.on_bar({'close': 5000 + i * 10, 'timestamp': f'2024-01-01 09:{i:02d}'})
        
        # 重置
        strategy.reset()
        
        # 检查状态是否已重置
        assert len(strategy.price_history) == 0
        assert len(strategy.middle_band_history) == 0
        assert len(strategy.upper_band_history) == 0
        assert len(strategy.lower_band_history) == 0
        assert len(strategy.signals) == 0


class TestATRStrategy:
    """ATR策略测试"""
    
    def test_atr_strategy_init(self):
        """测试ATR策略初始化"""
        strategy = ATRStrategy(
            atr_period=14,
            breakout_factor=1.5,
            stop_loss_multiplier=1.0,
            take_profit_multiplier=2.0
        )
        assert strategy.atr_period == 14
        assert strategy.breakout_factor == 1.5
        assert strategy.stop_loss_multiplier == 1.0
        assert strategy.take_profit_multiplier == 2.0
    
    def test_atr_strategy_no_signal_short_data(self):
        """测试数据不足时无信号"""
        strategy = ATRStrategy()
        data = [{'close': 5000, 'high': 5010, 'low': 4990}]
        signal = strategy.on_bar(data[0])
        assert signal is None
    
    def test_atr_strategy_upward_breakout(self):
        """测试向上突破信号"""
        # 使用较低的突破系数使信号更容易触发
        strategy = ATRStrategy(breakout_factor=0.1)
        
        # 创建固定波动范围的数据，然后大幅跳空突破
        data = []
        # 先创建一些固定波动数据建立ATR
        for i in range(20):
            data.append({
                'close': 5000,
                'high': 5010,
                'low': 4990,
                'timestamp': f'2024-01-01 09:{i:02d}'
            })
        
        # 然后价格大幅跳空上涨突破
        data.append({
            'close': 5050,
            'high': 5055,
            'low': 5045,
            'timestamp': '2024-01-01 09:20'
        })
        
        signals = []
        for bar in data:
            signal = strategy.on_bar(bar)
            if signal:
                signals.append(signal)
        
        # 应该产生买入信号
        buy_signals = [s for s in signals if s.signal_type == 'buy']
        assert len(buy_signals) >= 1
    
    def test_atr_strategy_downward_breakout(self):
        """测试向下突破信号"""
        # 使用较低的突破系数使信号更容易触发
        strategy = ATRStrategy(breakout_factor=0.1)
        
        # 创建固定波动范围的数据，然后大幅跳空下跌突破
        data = []
        # 先创建一些固定波动数据建立ATR
        for i in range(20):
            data.append({
                'close': 5000,
                'high': 5010,
                'low': 4990,
                'timestamp': f'2024-01-01 09:{i:02d}'
            })
        
        # 然后价格大幅跳空下跌突破
        data.append({
            'close': 4950,
            'high': 4955,
            'low': 4945,
            'timestamp': '2024-01-01 09:20'
        })
        
        signals = []
        for bar in data:
            signal = strategy.on_bar(bar)
            if signal:
                signals.append(signal)
        
        # 应该产生卖出信号
        sell_signals = [s for s in signals if s.signal_type == 'sell']
        assert len(sell_signals) >= 1
    
    def test_atr_strategy_reset(self):
        """测试策略重置"""
        strategy = ATRStrategy()
        
        # 添加一些数据
        for i in range(30):
            strategy.on_bar({
                'close': 5000 + i * 10,
                'high': 5005 + i * 10,
                'low': 4995 + i * 10,
                'timestamp': f'2024-01-01 09:{i:02d}'
            })
        
        # 重置
        strategy.reset()
        
        # 检查状态是否已重置
        assert len(strategy.high_history) == 0
        assert len(strategy.low_history) == 0
        assert len(strategy.close_history) == 0
        assert len(strategy.atr_history) == 0
        assert len(strategy.signals) == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

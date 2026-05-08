#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KDJ策略模块
基于KDJ指标的交易策略
"""

from typing import Optional, Dict, Any
from backtest.strategy_base import StrategyBase, StrategySignal


class KDJStrategy(StrategyBase):
    """KDJ策略"""
    
    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        self.default_params = {
            'period': 9,
            'k_period': 3,
            'd_period': 3,
            'overbought': 80,
            'oversold': 20,
            'risk_pct': 0.01,
            'take_profit_pct': 0.02
        }
        self.params = {**self.default_params, **(params or {})}
        self.prev_k = None
        self.prev_d = None
    
    def _calculate_kdj(self, prices: list, highs: list, lows: list) -> tuple:
        """计算KDJ指标"""
        period = self.params['period']
        
        if len(prices) < period:
            return None, None, None
        
        # 计算RSV
        lowest_low = min(lows[-period:])
        highest_high = max(highs[-period:])
        
        if highest_high == lowest_low:
            rsv = 50.0
        else:
            rsv = (prices[-1] - lowest_low) / (highest_high - lowest_low) * 100
        
        # 计算K和D
        if self.prev_k is None:
            k = rsv
        else:
            k = (self.params['k_period'] - 1) / self.params['k_period'] * self.prev_k + \
                1 / self.params['k_period'] * rsv
        
        if self.prev_d is None:
            d = k
        else:
            d = (self.params['d_period'] - 1) / self.params['d_period'] * self.prev_d + \
                1 / self.params['d_period'] * k
        
        # J = 3K - 2D
        j = 3 * k - 2 * d
        
        return k, d, j
    
    def on_bar(self, bar: Dict[str, Any]) -> Optional[StrategySignal]:
        """
        处理一根K线
        :param bar: K线数据字典，需要包含 'close', 'high', 'low' 字段
        :return: 信号（如果有）
        """
        if not hasattr(self, 'price_history'):
            self.price_history = []
            self.high_history = []
            self.low_history = []
        
        self.price_history.append(bar['close'])
        self.high_history.append(bar.get('high', bar['close']))
        self.low_history.append(bar.get('low', bar['close']))
        
        k, d, j = self._calculate_kdj(self.price_history, self.high_history, self.low_history)
        
        if k is None:
            return None
        
        current_price = bar['close']
        timestamp = bar.get('time', '')
        
        # 买入信号：K上穿D，且低于超卖线
        if self.prev_k is not None and self.prev_d is not None:
            if self.prev_k <= self.prev_d and k > d and k < self.params['oversold']:
                stop_loss = current_price * (1 - self.params['risk_pct'])
                take_profit = current_price * (1 + self.params['take_profit_pct'])
                return self.generate_signal('buy', current_price, timestamp,
                                          stop_loss=stop_loss, take_profit=take_profit)
            
            # 卖出信号：K下穿D，且高于超买线
            elif self.prev_k >= self.prev_d and k < d and k > self.params['overbought']:
                stop_loss = current_price * (1 + self.params['risk_pct'])
                take_profit = current_price * (1 - self.params['take_profit_pct'])
                return self.generate_signal('sell', current_price, timestamp,
                                          stop_loss=stop_loss, take_profit=take_profit)
        
        self.prev_k = k
        self.prev_d = d
        
        return None
    
    def reset(self):
        """重置策略状态"""
        super().reset()
        self.prev_k = None
        self.prev_d = None
        if hasattr(self, 'price_history'):
            self.price_history = []
            self.high_history = []
            self.low_history = []

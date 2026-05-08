#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
均线策略模块
基于均线交叉的交易策略
"""

from typing import Optional, Dict, Any
from backtest.strategy_base import StrategyBase, StrategySignal


class MovingAverageStrategy(StrategyBase):
    """均线交叉策略"""
    
    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        self.default_params = {
            'short_period': 5,
            'long_period': 20,
            'risk_pct': 0.01,
            'take_profit_pct': 0.02
        }
        self.params = {**self.default_params, **(params or {})}
        self.prev_short_ma = None
        self.prev_long_ma = None
    
    def _calculate_ma(self, prices: list, period: int) -> float:
        """计算简单移动平均线"""
        if len(prices) < period:
            return None
        return sum(prices[-period:]) / period
    
    def on_bar(self, bar: Dict[str, Any]) -> Optional[StrategySignal]:
        """
        处理一根K线
        :param bar: K线数据字典，需要包含 'close' 字段
        :return: 信号（如果有）
        """
        if not hasattr(self, 'price_history'):
            self.price_history = []
        
        self.price_history.append(bar['close'])
        
        short_ma = self._calculate_ma(self.price_history, self.params['short_period'])
        long_ma = self._calculate_ma(self.price_history, self.params['long_period'])
        
        if short_ma is None or long_ma is None:
            return None
        
        current_price = bar['close']
        timestamp = bar.get('time', '')
        
        # 金叉信号：短期均线上穿长期均线
        if self.prev_short_ma is not None and self.prev_long_ma is not None:
            if self.prev_short_ma <= self.prev_long_ma and short_ma > long_ma:
                stop_loss = current_price * (1 - self.params['risk_pct'])
                take_profit = current_price * (1 + self.params['take_profit_pct'])
                return self.generate_signal('buy', current_price, timestamp,
                                          stop_loss=stop_loss, take_profit=take_profit)
            
            # 死叉信号：短期均线下穿长期均线
            elif self.prev_short_ma >= self.prev_long_ma and short_ma < long_ma:
                stop_loss = current_price * (1 + self.params['risk_pct'])
                take_profit = current_price * (1 - self.params['take_profit_pct'])
                return self.generate_signal('sell', current_price, timestamp,
                                          stop_loss=stop_loss, take_profit=take_profit)
        
        self.prev_short_ma = short_ma
        self.prev_long_ma = long_ma
        
        return None
    
    def reset(self):
        """重置策略状态"""
        super().reset()
        self.prev_short_ma = None
        self.prev_long_ma = None
        if hasattr(self, 'price_history'):
            self.price_history = []

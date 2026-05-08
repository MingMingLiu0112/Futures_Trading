#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
突破策略模块
基于价格突破的交易策略
"""

from typing import Optional, Dict, Any
from backtest.strategy_base import StrategyBase, StrategySignal


class BreakoutStrategy(StrategyBase):
    """突破策略"""
    
    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        self.default_params = {
            'lookback_period': 20,
            'breakout_pct': 0.005,
            'risk_pct': 0.01,
            'take_profit_pct': 0.02
        }
        self.params = {**self.default_params, **(params or {})}
    
    def _get_high_low_range(self, highs: list, lows: list) -> tuple:
        """获取历史高低价区间"""
        lookback = self.params['lookback_period']
        recent_highs = highs[-lookback:]
        recent_lows = lows[-lookback:]
        return max(recent_highs), min(recent_lows)
    
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
        
        lookback = self.params['lookback_period']
        
        if len(self.price_history) < lookback:
            return None
        
        current_high = bar.get('high', bar['close'])
        current_low = bar.get('low', bar['close'])
        current_price = bar['close']
        timestamp = bar.get('time', '')
        
        # 获取历史区间
        historical_high, historical_low = self._get_high_low_range(
            self.high_history[:-1],  # 不包含当前K线
            self.low_history[:-1]
        )
        
        breakout_pct = self.params['breakout_pct']
        
        # 上突破信号
        if current_high >= historical_high * (1 + breakout_pct):
            stop_loss = historical_high * (1 - self.params['risk_pct'])
            take_profit = current_price * (1 + self.params['take_profit_pct'])
            return self.generate_signal('buy', current_price, timestamp,
                                      stop_loss=stop_loss, take_profit=take_profit)
        
        # 下突破信号
        if current_low <= historical_low * (1 - breakout_pct):
            stop_loss = historical_low * (1 + self.params['risk_pct'])
            take_profit = current_price * (1 - self.params['take_profit_pct'])
            return self.generate_signal('sell', current_price, timestamp,
                                      stop_loss=stop_loss, take_profit=take_profit)
        
        return None
    
    def reset(self):
        """重置策略状态"""
        super().reset()
        if hasattr(self, 'price_history'):
            self.price_history = []
            self.high_history = []
            self.low_history = []

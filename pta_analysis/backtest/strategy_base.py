#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略基类模块
定义策略接口和基本功能
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any


class StrategySignal:
    """策略信号"""
    
    def __init__(self, signal_type: str, price: float, timestamp: str, 
                 stop_loss: Optional[float] = None, take_profit: Optional[float] = None):
        self.signal_type = signal_type  # 'buy' or 'sell'
        self.price = price
        self.timestamp = timestamp
        self.stop_loss = stop_loss
        self.take_profit = take_profit


class StrategyBase(ABC):
    """策略基类"""
    
    def __init__(self, params: Optional[Dict[str, Any]] = None):
        self.params = params or {}
        self.signals = []
        self.position = None  # 当前持仓: 'long', 'short', or None
        self.entry_price = None
    
    @abstractmethod
    def on_bar(self, bar: Dict[str, Any]) -> Optional[StrategySignal]:
        """
        处理一根K线
        :param bar: K线数据字典
        :return: 信号（如果有）
        """
        pass
    
    def reset(self):
        """重置策略状态"""
        self.signals = []
        self.position = None
        self.entry_price = None
    
    def generate_signal(self, signal_type: str, price: float, timestamp: str,
                       stop_loss: Optional[float] = None, take_profit: Optional[float] = None) -> StrategySignal:
        """生成信号"""
        signal = StrategySignal(signal_type, price, timestamp, stop_loss, take_profit)
        self.signals.append(signal)
        return signal

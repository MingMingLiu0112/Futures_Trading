#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
止损策略模块
支持固定止损和移动止损两种策略
"""

from abc import ABC, abstractmethod
from typing import Optional


class StopLossStrategy(ABC):
    """止损策略基类"""
    
    def __init__(self, symbol: str, initial_price: float):
        self.symbol = symbol
        self.initial_price = initial_price
        self.stop_price = None
        self.is_triggered = False
        self.trailing_count = 0
    
    @abstractmethod
    def calculate_stop_price(self, current_price: float) -> float:
        """计算止损价格"""
        pass
    
    @abstractmethod
    def check_trigger(self, current_price: float) -> bool:
        """检查是否触发止损"""
        pass
    
    def reset(self, new_price: float):
        """重置止损状态"""
        self.initial_price = new_price
        self.is_triggered = False
        self.trailing_count = 0


class FixedStopLoss(StopLossStrategy):
    """固定止损策略"""
    
    def __init__(self, symbol: str, initial_price: float, stop_pct: float = 0.02):
        super().__init__(symbol, initial_price)
        self.stop_pct = stop_pct
        self.stop_price = self._calculate_initial_stop()
    
    def _calculate_initial_stop(self) -> float:
        """计算初始止损价格"""
        return self.initial_price * (1 - self.stop_pct)
    
    def calculate_stop_price(self, current_price: float) -> float:
        """计算止损价格（固定止损不变）"""
        return self.stop_price
    
    def check_trigger(self, current_price: float) -> bool:
        """检查是否触发止损"""
        if self.is_triggered:
            return True
        
        if current_price <= self.stop_price:
            self.is_triggered = True
            return True
        
        return False
    
    def reset(self, new_price: float):
        """重置止损状态"""
        super().reset(new_price)
        self.stop_price = self._calculate_initial_stop()


class TrailingStopLoss(StopLossStrategy):
    """移动止损策略"""
    
    def __init__(self, symbol: str, initial_price: float, trail_pct: float = 0.02):
        super().__init__(symbol, initial_price)
        self.trail_pct = trail_pct
        self.highest_price = initial_price
        self.stop_price = self._calculate_initial_stop()
    
    def _calculate_initial_stop(self) -> float:
        """计算初始止损价格"""
        return self.initial_price * (1 - self.trail_pct)
    
    def calculate_stop_price(self, current_price: float) -> float:
        """计算止损价格（移动止损会跟随价格调整）"""
        # 更新最高价
        if current_price > self.highest_price:
            self.highest_price = current_price
            # 调整止损价格
            new_stop_price = self.highest_price * (1 - self.trail_pct)
            if new_stop_price > self.stop_price:
                self.stop_price = new_stop_price
                self.trailing_count += 1
        
        return self.stop_price
    
    def check_trigger(self, current_price: float) -> bool:
        """检查是否触发止损"""
        if self.is_triggered:
            return True
        
        if current_price <= self.stop_price:
            self.is_triggered = True
            return True
        
        return False

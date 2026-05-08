#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
止盈策略模块
支持固定止盈和追踪止盈两种策略
"""

from abc import ABC, abstractmethod


class TakeProfitStrategy(ABC):
    """止盈策略基类"""
    
    def __init__(self, symbol: str, initial_price: float):
        self.symbol = symbol
        self.initial_price = initial_price
        self.target_price = None
        self.is_triggered = False
        self.trailing_count = 0
    
    @abstractmethod
    def calculate_target_price(self, current_price: float) -> float:
        """计算止盈价格"""
        pass
    
    @abstractmethod
    def check_trigger(self, current_price: float) -> bool:
        """检查是否触发止盈"""
        pass
    
    def reset(self, new_price: float):
        """重置止盈状态"""
        self.initial_price = new_price
        self.target_price = None
        self.is_triggered = False
        self.trailing_count = 0


class FixedTakeProfit(TakeProfitStrategy):
    """固定止盈策略"""
    
    def __init__(self, symbol: str, initial_price: float, target_pct: float = 0.03):
        super().__init__(symbol, initial_price)
        self.target_pct = target_pct
        self.target_price = self._calculate_initial_target()
    
    def _calculate_initial_target(self) -> float:
        """计算初始止盈价格"""
        return self.initial_price * (1 + self.target_pct)
    
    def calculate_target_price(self, current_price: float) -> float:
        """计算止盈价格（固定止盈不变）"""
        return self.target_price
    
    def check_trigger(self, current_price: float) -> bool:
        """检查是否触发止盈"""
        if self.is_triggered:
            return True
        
        if current_price >= self.target_price:
            self.is_triggered = True
            return True
        
        return False


class TrailingTakeProfit(TakeProfitStrategy):
    """追踪止盈策略"""
    
    def __init__(self, symbol: str, initial_price: float, trail_pct: float = 0.02):
        super().__init__(symbol, initial_price)
        self.trail_pct = trail_pct
        self.highest_price = initial_price
        self.target_price = self._calculate_initial_target()
    
    def _calculate_initial_target(self) -> float:
        """计算初始止盈价格"""
        return self.initial_price * (1 - self.trail_pct)
    
    def calculate_target_price(self, current_price: float) -> float:
        """计算止盈价格（追踪止盈会跟随价格调整）"""
        # 更新最高价
        if current_price > self.highest_price:
            self.highest_price = current_price
            # 调整止盈价格（始终更新）
            new_target_price = self.highest_price * (1 - self.trail_pct)
            self.target_price = new_target_price
            self.trailing_count += 1
        
        return self.target_price
    
    def check_trigger(self, current_price: float) -> bool:
        """检查是否触发止盈"""
        if self.is_triggered:
            return True
        
        if current_price <= self.target_price:
            self.is_triggered = True
            return True
        
        return False

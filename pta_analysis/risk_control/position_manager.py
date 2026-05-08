#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仓位管理模块
支持固定仓位和风险百分比仓位两种管理方式
"""

from typing import Dict, Optional, Tuple


class Position:
    """仓位对象"""
    
    def __init__(self, symbol: str, direction: str, quantity: int, entry_price: float):
        self.symbol = symbol
        self.direction = direction  # 'long' or 'short'
        self.quantity = quantity
        self.entry_price = entry_price
        self.current_price = entry_price
        self.stop_loss_price = None
        self.take_profit_price = None
    
    @property
    def pnl(self) -> float:
        """计算当前盈亏"""
        if self.direction == 'long':
            return (self.current_price - self.entry_price) * self.quantity
        else:
            return (self.entry_price - self.current_price) * self.quantity
    
    @property
    def pnl_pct(self) -> float:
        """计算盈亏百分比"""
        if self.entry_price == 0:
            return 0.0
        return self.pnl / (self.entry_price * self.quantity) * 100
    
    def update_current_price(self, price: float):
        """更新当前价格"""
        self.current_price = price


class PositionManager:
    """仓位管理器"""
    
    def __init__(self, account_balance: float, risk_per_trade: float = 0.01):
        self.account_balance = account_balance
        self.risk_per_trade = risk_per_trade  # 每笔交易风险占账户比例
        self.positions: Dict[str, Position] = {}
    
    def calculate_position_size_fixed(self, entry_price: float, position_value: float) -> int:
        """
        固定金额仓位计算
        :param entry_price: 入场价格
        :param position_value: 仓位价值（金额）
        :return: 仓位数量
        """
        return int(position_value / entry_price)
    
    def calculate_position_size_risk(self, entry_price: float, stop_price: float) -> int:
        """
        风险百分比仓位计算
        :param entry_price: 入场价格
        :param stop_price: 止损价格
        :return: 仓位数量
        """
        if entry_price == stop_price:
            return 0
        
        risk_amount = self.account_balance * self.risk_per_trade
        risk_per_unit = abs(entry_price - stop_price)
        
        if risk_per_unit <= 0:
            return 0
        
        position_size = int(risk_amount / risk_per_unit)
        return max(1, position_size)  # 至少1手
    
    def calculate_position_size_quantity(self, quantity: int) -> int:
        """
        固定数量仓位计算
        :param quantity: 固定数量
        :return: 仓位数量
        """
        return quantity
    
    def open_position(self, symbol: str, direction: str, quantity: int, entry_price: float,
                     stop_loss_price: Optional[float] = None, take_profit_price: Optional[float] = None):
        """
        开仓
        :param symbol: 合约代码
        :param direction: 方向 ('long' or 'short')
        :param quantity: 数量
        :param entry_price: 入场价格
        :param stop_loss_price: 止损价格
        :param take_profit_price: 止盈价格
        """
        position = Position(symbol, direction, quantity, entry_price)
        position.stop_loss_price = stop_loss_price
        position.take_profit_price = take_profit_price
        self.positions[symbol] = position
    
    def close_position(self, symbol: str, exit_price: float) -> Tuple[float, float]:
        """
        平仓
        :param symbol: 合约代码
        :param exit_price: 出场价格
        :return: (盈亏金额, 盈亏百分比)
        """
        if symbol not in self.positions:
            return 0.0, 0.0
        
        position = self.positions[symbol]
        position.update_current_price(exit_price)
        pnl = position.pnl
        pnl_pct = position.pnl_pct
        
        del self.positions[symbol]
        return pnl, pnl_pct
    
    def update_price(self, symbol: str, price: float):
        """更新仓位当前价格"""
        if symbol in self.positions:
            self.positions[symbol].update_current_price(price)
    
    @property
    def total_pnl(self) -> float:
        """计算总盈亏"""
        return sum(pos.pnl for pos in self.positions.values())
    
    @property
    def total_position_value(self) -> float:
        """计算总持仓价值"""
        return sum(pos.current_price * pos.quantity for pos in self.positions.values())
    
    @property
    def position_count(self) -> int:
        """获取持仓数量"""
        return len(self.positions)

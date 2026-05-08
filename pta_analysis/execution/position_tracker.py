#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仓位追踪器模块
负责追踪和管理持仓
"""

from typing import Dict, Any, Optional
from enum import Enum


class PositionDirection(Enum):
    """持仓方向"""
    LONG = 'long'    # 多头
    SHORT = 'short'  # 空头
    FLAT = 'flat'    # 平仓


class PositionTracker:
    """仓位追踪器"""
    
    def __init__(self):
        self.positions: Dict[str, Dict[str, Any]] = {}  # symbol -> position info
    
    def update_position(self, symbol: str, direction: PositionDirection, 
                       quantity: int, price: float):
        """
        更新仓位
        :param symbol: 合约代码
        :param direction: 方向
        :param quantity: 数量
        :param price: 价格
        """
        if symbol not in self.positions:
            self.positions[symbol] = {
                'direction': PositionDirection.FLAT,
                'quantity': 0,
                'avg_price': 0.0,
                'unrealized_pnl': 0.0
            }
        
        pos = self.positions[symbol]
        
        if direction == PositionDirection.FLAT:
            pos['direction'] = PositionDirection.FLAT
            pos['quantity'] = 0
            pos['avg_price'] = 0.0
            pos['unrealized_pnl'] = 0.0
        else:
            if pos['direction'] == PositionDirection.FLAT:
                # 开仓
                pos['direction'] = direction
                pos['quantity'] = quantity
                pos['avg_price'] = price
            elif pos['direction'] == direction:
                # 加仓
                total_value = pos['avg_price'] * pos['quantity'] + price * quantity
                pos['quantity'] += quantity
                pos['avg_price'] = total_value / pos['quantity']
            else:
                # 减仓或平仓
                if quantity >= pos['quantity']:
                    # 完全平仓
                    pos['direction'] = PositionDirection.FLAT
                    pos['quantity'] = 0
                    pos['avg_price'] = 0.0
                else:
                    # 部分平仓
                    pos['quantity'] -= quantity
        
        # 更新未实现盈亏（需要最新价格）
    
    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        获取持仓
        :param symbol: 合约代码
        :return: 持仓信息
        """
        return self.positions.get(symbol)
    
    def get_all_positions(self) -> Dict[str, Dict[str, Any]]:
        """获取所有持仓"""
        return self.positions
    
    def get_net_position(self) -> float:
        """获取净持仓价值"""
        total = 0.0
        for symbol, pos in self.positions.items():
            if pos['direction'] == PositionDirection.LONG:
                total += pos['quantity'] * pos['avg_price']
            elif pos['direction'] == PositionDirection.SHORT:
                total -= pos['quantity'] * pos['avg_price']
        return total
    
    def update_unrealized_pnl(self, symbol: str, current_price: float):
        """
        更新未实现盈亏
        :param symbol: 合约代码
        :param current_price: 当前价格
        """
        pos = self.positions.get(symbol)
        if pos and pos['quantity'] > 0:
            if pos['direction'] == PositionDirection.LONG:
                pos['unrealized_pnl'] = (current_price - pos['avg_price']) * pos['quantity']
            else:
                pos['unrealized_pnl'] = (pos['avg_price'] - current_price) * pos['quantity']
    
    def get_total_unrealized_pnl(self) -> float:
        """获取总未实现盈亏"""
        total = 0.0
        for pos in self.positions.values():
            total += pos.get('unrealized_pnl', 0.0)
        return total
    
    def is_flat(self, symbol: str) -> bool:
        """
        是否空仓
        :param symbol: 合约代码
        :return: 是否空仓
        """
        pos = self.positions.get(symbol)
        return pos is None or pos['direction'] == PositionDirection.FLAT
    
    def get_position_summary(self) -> Dict[str, Any]:
        """获取持仓汇总"""
        summary = {
            'total_positions': len([p for p in self.positions.values() if p['quantity'] > 0]),
            'long_count': 0,
            'short_count': 0,
            'total_quantity': 0,
            'total_unrealized_pnl': 0.0,
            'net_exposure': 0.0
        }
        
        for symbol, pos in self.positions.items():
            if pos['quantity'] > 0:
                summary['total_quantity'] += pos['quantity']
                summary['total_unrealized_pnl'] += pos.get('unrealized_pnl', 0.0)
                
                if pos['direction'] == PositionDirection.LONG:
                    summary['long_count'] += 1
                    summary['net_exposure'] += pos['quantity'] * pos['avg_price']
                else:
                    summary['short_count'] += 1
                    summary['net_exposure'] -= pos['quantity'] * pos['avg_price']
        
        return summary

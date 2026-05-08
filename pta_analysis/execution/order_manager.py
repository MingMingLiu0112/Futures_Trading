#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
订单管理模块
负责订单的创建、追踪和管理
"""

from typing import List, Dict, Any, Optional
from enum import Enum
import uuid


class OrderStatus(Enum):
    """订单状态"""
    PENDING = 'pending'       # 待提交
    SUBMITTED = 'submitted'   # 已提交
    FILLED = 'filled'         # 已成交
    PARTIALLY_FILLED = 'partially_filled'  # 部分成交
    CANCELLED = 'cancelled'   # 已取消
    FAILED = 'failed'         # 失败


class OrderType(Enum):
    """订单类型"""
    MARKET = 'market'         # 市价单
    LIMIT = 'limit'           # 限价单
    STOP = 'stop'             # 止损单
    STOP_LIMIT = 'stop_limit' # 止损限价单


class OrderSide(Enum):
    """订单方向"""
    BUY = 'buy'               # 买入
    SELL = 'sell'             # 卖出


class Order:
    """订单类"""
    
    def __init__(self, symbol: str, side: OrderSide, quantity: int, 
                 order_type: OrderType = OrderType.MARKET, 
                 price: Optional[float] = None, stop_price: Optional[float] = None):
        self.order_id = str(uuid.uuid4())
        self.symbol = symbol
        self.side = side
        self.quantity = quantity
        self.order_type = order_type
        self.price = price
        self.stop_price = stop_price
        self.status = OrderStatus.PENDING
        self.filled_quantity = 0
        self.filled_price = None
        self.create_time = None
        self.update_time = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'order_id': self.order_id,
            'symbol': self.symbol,
            'side': self.side.value,
            'quantity': self.quantity,
            'order_type': self.order_type.value,
            'price': self.price,
            'stop_price': self.stop_price,
            'status': self.status.value,
            'filled_quantity': self.filled_quantity,
            'filled_price': self.filled_price,
            'create_time': self.create_time,
            'update_time': self.update_time
        }
    
    def update_filled(self, quantity: int, price: float):
        """更新成交数量和价格"""
        self.filled_quantity += quantity
        
        if self.filled_price is None:
            self.filled_price = price
        else:
            # 加权平均价格
            total_value = self.filled_price * (self.filled_quantity - quantity) + price * quantity
            self.filled_price = total_value / self.filled_quantity
        
        if self.filled_quantity >= self.quantity:
            self.status = OrderStatus.FILLED
        else:
            self.status = OrderStatus.PARTIALLY_FILLED
        
        self.update_time = self._get_current_time()
    
    def cancel(self):
        """取消订单"""
        if self.status in [OrderStatus.PENDING, OrderStatus.SUBMITTED]:
            self.status = OrderStatus.CANCELLED
            self.update_time = self._get_current_time()
    
    def _get_current_time(self) -> str:
        """获取当前时间"""
        from datetime import datetime
        return datetime.now().isoformat()


class OrderManager:
    """订单管理器"""
    
    def __init__(self):
        self.orders: Dict[str, Order] = {}
    
    def create_order(self, symbol: str, side: OrderSide, quantity: int,
                     order_type: OrderType = OrderType.MARKET,
                     price: Optional[float] = None,
                     stop_price: Optional[float] = None) -> Order:
        """
        创建订单
        :param symbol: 合约代码
        :param side: 订单方向
        :param quantity: 数量
        :param order_type: 订单类型
        :param price: 价格（限价单）
        :param stop_price: 止损价格（止损单）
        :return: 订单对象
        """
        order = Order(symbol, side, quantity, order_type, price, stop_price)
        order.create_time = order._get_current_time()
        order.update_time = order.create_time
        self.orders[order.order_id] = order
        
        return order
    
    def get_order(self, order_id: str) -> Optional[Order]:
        """获取订单"""
        return self.orders.get(order_id)
    
    def get_orders_by_status(self, status: OrderStatus) -> List[Order]:
        """按状态获取订单"""
        return [order for order in self.orders.values() if order.status == status]
    
    def get_active_orders(self) -> List[Order]:
        """获取活跃订单（待提交、已提交、部分成交）"""
        active_statuses = [OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED]
        return [order for order in self.orders.values() if order.status in active_statuses]
    
    def update_order(self, order_id: str, **kwargs):
        """更新订单"""
        order = self.orders.get(order_id)
        if order:
            for key, value in kwargs.items():
                if hasattr(order, key):
                    setattr(order, key, value)
            order.update_time = order._get_current_time()
    
    def cancel_order(self, order_id: str):
        """取消订单"""
        order = self.orders.get(order_id)
        if order:
            order.cancel()
    
    def cancel_all_orders(self):
        """取消所有订单"""
        for order in self.get_active_orders():
            order.cancel()
    
    def get_all_orders(self) -> List[Order]:
        """获取所有订单"""
        return list(self.orders.values())
    
    def get_order_history(self, symbol: Optional[str] = None) -> List[Order]:
        """获取历史订单（已成交、已取消、失败）"""
        history_statuses = [OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.FAILED]
        orders = [order for order in self.orders.values() if order.status in history_statuses]
        
        if symbol:
            orders = [order for order in orders if order.symbol == symbol]
        
        return orders

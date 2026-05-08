#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易执行器模块
负责订单的执行和成交管理
"""

from typing import Optional, Dict, Any
from .order_manager import OrderManager, Order, OrderStatus, OrderType, OrderSide


class TradeExecutor:
    """交易执行器"""
    
    def __init__(self, order_manager: OrderManager):
        self.order_manager = order_manager
        self.broker = None
    
    def connect_broker(self, broker):
        """连接交易接口"""
        self.broker = broker
    
    def submit_order(self, order: Order) -> bool:
        """
        提交订单
        :param order: 订单对象
        :return: 是否提交成功
        """
        if order.status != OrderStatus.PENDING:
            return False
        
        try:
            if self.broker:
                # 通过真实接口提交
                result = self.broker.submit_order(order)
                if result:
                    order.status = OrderStatus.SUBMITTED
                    order.update_time = order._get_current_time()
                    return True
            else:
                # 模拟成交
                self._simulate_order(order)
                return True
        except Exception as e:
            order.status = OrderStatus.FAILED
            order.update_time = order._get_current_time()
            return False
    
    def _simulate_order(self, order: Order):
        """模拟订单成交"""
        if order.order_type == OrderType.MARKET:
            # 市价单立即成交
            order.filled_quantity = order.quantity
            order.filled_price = order.price or 5000  # 默认价格
            order.status = OrderStatus.FILLED
        elif order.order_type == OrderType.LIMIT:
            # 限价单模拟成交（简单处理）
            if order.price:
                order.filled_quantity = order.quantity
                order.filled_price = order.price
                order.status = OrderStatus.FILLED
            else:
                order.status = OrderStatus.FAILED
        elif order.order_type == OrderType.STOP:
            # 止损单需要价格触发
            order.status = OrderStatus.SUBMITTED
    
    def check_order_status(self, order_id: str) -> Optional[OrderStatus]:
        """
        检查订单状态
        :param order_id: 订单ID
        :return: 订单状态
        """
        order = self.order_manager.get_order(order_id)
        if order and self.broker:
            # 从接口更新状态
            status = self.broker.get_order_status(order_id)
            if status:
                order.status = status
                return status
        return order.status if order else None
    
    def cancel_order(self, order_id: str) -> bool:
        """
        取消订单
        :param order_id: 订单ID
        :return: 是否取消成功
        """
        order = self.order_manager.get_order(order_id)
        if not order:
            return False
        
        try:
            if self.broker:
                result = self.broker.cancel_order(order_id)
                if result:
                    order.cancel()
                    return True
            else:
                order.cancel()
                return True
        except Exception as e:
            return False
    
    def execute_signal(self, signal: Dict[str, Any]) -> Optional[Order]:
        """
        执行交易信号
        :param signal: 交易信号字典
        :return: 创建的订单
        """
        symbol = signal.get('symbol', '')
        signal_type = signal.get('signal_type', '')
        price = signal.get('price')
        stop_loss = signal.get('stop_loss')
        take_profit = signal.get('take_profit')
        
        if not symbol or not signal_type:
            return None
        
        side = OrderSide.BUY if signal_type == 'buy' else OrderSide.SELL
        
        # 创建订单
        order = self.order_manager.create_order(
            symbol=symbol,
            side=side,
            quantity=1,  # 默认1手
            order_type=OrderType.MARKET,
            price=price
        )
        
        # 提交订单
        self.submit_order(order)
        
        # 如果有止损止盈，创建对应的订单
        if stop_loss:
            self._create_stop_order(symbol, side, stop_loss)
        
        if take_profit:
            self._create_take_profit_order(symbol, side, take_profit)
        
        return order
    
    def _create_stop_order(self, symbol: str, side: OrderSide, stop_price: float):
        """创建止损订单"""
        stop_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY
        
        order = self.order_manager.create_order(
            symbol=symbol,
            side=stop_side,
            quantity=1,
            order_type=OrderType.STOP,
            stop_price=stop_price
        )
        self.submit_order(order)
    
    def _create_take_profit_order(self, symbol: str, side: OrderSide, take_profit_price: float):
        """创建止盈订单"""
        tp_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY
        
        order = self.order_manager.create_order(
            symbol=symbol,
            side=tp_side,
            quantity=1,
            order_type=OrderType.LIMIT,
            price=take_profit_price
        )
        self.submit_order(order)


class MockBroker:
    """模拟交易接口"""
    
    def __init__(self):
        self.orders = {}
    
    def submit_order(self, order: Order) -> bool:
        """提交订单"""
        self.orders[order.order_id] = order.to_dict()
        return True
    
    def get_order_status(self, order_id: str) -> Optional[OrderStatus]:
        """获取订单状态"""
        order_data = self.orders.get(order_id)
        if order_data:
            return OrderStatus(order_data['status'])
        return None
    
    def cancel_order(self, order_id: str) -> bool:
        """取消订单"""
        if order_id in self.orders:
            self.orders[order_id]['status'] = OrderStatus.CANCELLED.value
            return True
        return False
    
    def get_account_balance(self) -> float:
        """获取账户余额"""
        return 1000000.0  # 默认100万
    
    def get_positions(self) -> Dict[str, Any]:
        """获取持仓"""
        return {}

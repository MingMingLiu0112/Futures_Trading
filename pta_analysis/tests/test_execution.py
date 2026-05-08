#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易执行模块单元测试
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execution.order_manager import OrderManager, Order, OrderStatus, OrderType, OrderSide
from execution.trade_executor import TradeExecutor, MockBroker
from execution.position_tracker import PositionTracker, PositionDirection


class TestOrder:
    """订单类测试"""
    
    def test_order_init(self):
        """测试订单初始化"""
        order = Order('TEST', OrderSide.BUY, 100)
        
        assert order.symbol == 'TEST'
        assert order.side == OrderSide.BUY
        assert order.quantity == 100
        assert order.order_type == OrderType.MARKET
        assert order.status == OrderStatus.PENDING
    
    def test_order_to_dict(self):
        """测试订单转字典"""
        order = Order('TEST', OrderSide.SELL, 50, OrderType.LIMIT, 5000.0)
        order.status = OrderStatus.FILLED
        order.filled_quantity = 50
        order.filled_price = 5000.0
        
        result = order.to_dict()
        
        assert result['symbol'] == 'TEST'
        assert result['side'] == 'sell'
        assert result['status'] == 'filled'
    
    def test_order_update_filled(self):
        """测试更新成交"""
        order = Order('TEST', OrderSide.BUY, 100)
        order.update_filled(50, 5000.0)
        
        assert order.filled_quantity == 50
        assert order.filled_price == 5000.0
        assert order.status == OrderStatus.PARTIALLY_FILLED
        
        order.update_filled(50, 5010.0)
        
        assert order.filled_quantity == 100
        assert order.status == OrderStatus.FILLED
        # 加权平均价格
        assert order.filled_price == 5005.0
    
    def test_order_cancel(self):
        """测试取消订单"""
        order = Order('TEST', OrderSide.BUY, 100)
        order.cancel()
        
        assert order.status == OrderStatus.CANCELLED


class TestOrderManager:
    """订单管理器测试"""
    
    def test_order_manager_init(self):
        """测试订单管理器初始化"""
        manager = OrderManager()
        assert manager.orders == {}
    
    def test_create_order(self):
        """测试创建订单"""
        manager = OrderManager()
        order = manager.create_order('TEST', OrderSide.BUY, 100)
        
        assert order.order_id in manager.orders
        assert manager.orders[order.order_id] == order
    
    def test_get_order(self):
        """测试获取订单"""
        manager = OrderManager()
        order = manager.create_order('TEST', OrderSide.BUY, 100)
        
        retrieved = manager.get_order(order.order_id)
        assert retrieved == order
        
        assert manager.get_order('invalid_id') is None
    
    def test_get_orders_by_status(self):
        """测试按状态获取订单"""
        manager = OrderManager()
        order1 = manager.create_order('TEST', OrderSide.BUY, 100)
        order2 = manager.create_order('TEST', OrderSide.SELL, 50)
        order2.status = OrderStatus.FILLED
        
        pending_orders = manager.get_orders_by_status(OrderStatus.PENDING)
        filled_orders = manager.get_orders_by_status(OrderStatus.FILLED)
        
        assert len(pending_orders) == 1
        assert len(filled_orders) == 1
    
    def test_get_active_orders(self):
        """测试获取活跃订单"""
        manager = OrderManager()
        manager.create_order('TEST', OrderSide.BUY, 100)  # PENDING
        order2 = manager.create_order('TEST', OrderSide.SELL, 50)
        order2.status = OrderStatus.SUBMITTED
        order3 = manager.create_order('TEST', OrderSide.BUY, 75)
        order3.status = OrderStatus.FILLED
        
        active = manager.get_active_orders()
        assert len(active) == 2
    
    def test_cancel_order(self):
        """测试取消订单"""
        manager = OrderManager()
        order = manager.create_order('TEST', OrderSide.BUY, 100)
        
        manager.cancel_order(order.order_id)
        
        assert order.status == OrderStatus.CANCELLED
    
    def test_cancel_all_orders(self):
        """测试取消所有订单"""
        manager = OrderManager()
        manager.create_order('TEST', OrderSide.BUY, 100)
        manager.create_order('TEST', OrderSide.SELL, 50)
        
        manager.cancel_all_orders()
        
        active = manager.get_active_orders()
        assert len(active) == 0


class TestTradeExecutor:
    """交易执行器测试"""
    
    def test_trade_executor_init(self):
        """测试交易执行器初始化"""
        manager = OrderManager()
        executor = TradeExecutor(manager)
        
        assert executor.order_manager == manager
        assert executor.broker is None
    
    def test_connect_broker(self):
        """测试连接交易接口"""
        manager = OrderManager()
        executor = TradeExecutor(manager)
        broker = MockBroker()
        
        executor.connect_broker(broker)
        
        assert executor.broker == broker
    
    def test_submit_order(self):
        """测试提交订单"""
        manager = OrderManager()
        executor = TradeExecutor(manager)
        
        order = manager.create_order('TEST', OrderSide.BUY, 100)
        result = executor.submit_order(order)
        
        assert result is True
        assert order.status == OrderStatus.FILLED
    
    def test_execute_signal(self):
        """测试执行交易信号"""
        manager = OrderManager()
        executor = TradeExecutor(manager)
        
        signal = {
            'symbol': 'TEST',
            'signal_type': 'buy',
            'price': 5000.0,
            'stop_loss': 4950.0,
            'take_profit': 5100.0
        }
        
        order = executor.execute_signal(signal)
        
        assert order is not None
        assert order.symbol == 'TEST'
        assert order.side == OrderSide.BUY
        assert order.status == OrderStatus.FILLED


class TestPositionTracker:
    """仓位追踪器测试"""
    
    def test_position_tracker_init(self):
        """测试仓位追踪器初始化"""
        tracker = PositionTracker()
        assert tracker.positions == {}
    
    def test_update_position_open(self):
        """测试开仓"""
        tracker = PositionTracker()
        tracker.update_position('TEST', PositionDirection.LONG, 10, 5000.0)
        
        pos = tracker.get_position('TEST')
        assert pos['direction'] == PositionDirection.LONG
        assert pos['quantity'] == 10
        assert pos['avg_price'] == 5000.0
    
    def test_update_position_add(self):
        """测试加仓"""
        tracker = PositionTracker()
        tracker.update_position('TEST', PositionDirection.LONG, 10, 5000.0)
        tracker.update_position('TEST', PositionDirection.LONG, 10, 5050.0)
        
        pos = tracker.get_position('TEST')
        assert pos['quantity'] == 20
        assert pos['avg_price'] == 5025.0  # 加权平均
    
    def test_update_position_close(self):
        """测试平仓"""
        tracker = PositionTracker()
        tracker.update_position('TEST', PositionDirection.LONG, 10, 5000.0)
        tracker.update_position('TEST', PositionDirection.SHORT, 10, 5100.0)
        
        pos = tracker.get_position('TEST')
        assert pos['direction'] == PositionDirection.FLAT
        assert pos['quantity'] == 0
    
    def test_update_unrealized_pnl(self):
        """测试更新未实现盈亏"""
        tracker = PositionTracker()
        tracker.update_position('TEST', PositionDirection.LONG, 10, 5000.0)
        tracker.update_unrealized_pnl('TEST', 5100.0)
        
        pos = tracker.get_position('TEST')
        assert pos['unrealized_pnl'] == 1000.0  # (5100-5000)*10
    
    def test_get_position_summary(self):
        """测试获取持仓汇总"""
        tracker = PositionTracker()
        tracker.update_position('TEST1', PositionDirection.LONG, 10, 5000.0)
        tracker.update_position('TEST2', PositionDirection.SHORT, 5, 6000.0)
        
        summary = tracker.get_position_summary()
        
        assert summary['total_positions'] == 2
        assert summary['long_count'] == 1
        assert summary['short_count'] == 1
        assert summary['total_quantity'] == 15
    
    def test_is_flat(self):
        """测试是否空仓"""
        tracker = PositionTracker()
        
        assert tracker.is_flat('TEST') is True
        
        tracker.update_position('TEST', PositionDirection.LONG, 10, 5000.0)
        assert tracker.is_flat('TEST') is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

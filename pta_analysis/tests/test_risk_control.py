#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
风险控制模块单元测试
"""

import pytest
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk_control.stop_loss import FixedStopLoss, TrailingStopLoss
from risk_control.take_profit import FixedTakeProfit, TrailingTakeProfit
from risk_control.position_manager import PositionManager, Position
from risk_control.money_manager import MoneyManager, TradeRecord


class TestStopLoss:
    """止损策略测试"""
    
    def test_fixed_stop_loss_initial(self):
        """测试固定止损初始计算"""
        sl = FixedStopLoss('TA', 5000, 0.02)
        assert sl.stop_price == 4900  # 5000 * (1 - 0.02)
    
    def test_fixed_stop_loss_calculate(self):
        """测试固定止损计算（价格不变）"""
        sl = FixedStopLoss('TA', 5000, 0.02)
        assert sl.calculate_stop_price(5050) == 4900
        assert sl.calculate_stop_price(4950) == 4900
    
    def test_fixed_stop_loss_trigger_below(self):
        """测试固定止损触发（价格低于止损价）"""
        sl = FixedStopLoss('TA', 5000, 0.02)
        assert sl.check_trigger(4899) == True
        assert sl.is_triggered == True
    
    def test_fixed_stop_loss_no_trigger(self):
        """测试固定止损未触发"""
        sl = FixedStopLoss('TA', 5000, 0.02)
        assert sl.check_trigger(4901) == False
        assert sl.is_triggered == False
    
    def test_fixed_stop_loss_reset(self):
        """测试固定止损重置"""
        sl = FixedStopLoss('TA', 5000, 0.02)
        sl.is_triggered = True
        sl.reset(5100)
        assert sl.initial_price == 5100
        assert sl.stop_price == 4998  # 5100 * (1 - 0.02)
        assert sl.is_triggered == False
    
    def test_trailing_stop_loss_initial(self):
        """测试移动止损初始计算"""
        sl = TrailingStopLoss('TA', 5000, 0.02)
        assert sl.stop_price == 4900
        assert sl.highest_price == 5000
    
    def test_trailing_stop_loss_trail_up(self):
        """测试移动止损跟随上涨"""
        sl = TrailingStopLoss('TA', 5000, 0.02)
        # 价格上涨到5100
        stop_price = sl.calculate_stop_price(5100)
        assert sl.highest_price == 5100
        assert stop_price == 4998  # 5100 * (1 - 0.02)
        assert sl.trailing_count == 1
        
        # 价格继续上涨到5200
        stop_price = sl.calculate_stop_price(5200)
        assert sl.highest_price == 5200
        assert stop_price == 5096  # 5200 * (1 - 0.02)
        assert sl.trailing_count == 2
    
    def test_trailing_stop_loss_no_trail_down(self):
        """测试移动止损不跟随下跌"""
        sl = TrailingStopLoss('TA', 5000, 0.02)
        # 价格下跌到4950
        stop_price = sl.calculate_stop_price(4950)
        assert sl.highest_price == 5000  # 最高价不变
        assert stop_price == 4900  # 止损价不变
        assert sl.trailing_count == 0
    
    def test_trailing_stop_loss_trigger(self):
        """测试移动止损触发"""
        sl = TrailingStopLoss('TA', 5000, 0.02)
        sl.calculate_stop_price(5100)  # 止损价变为4998
        assert sl.check_trigger(4997) == True
        assert sl.is_triggered == True


class TestTakeProfit:
    """止盈策略测试"""
    
    def test_fixed_take_profit_initial(self):
        """测试固定止盈初始计算"""
        tp = FixedTakeProfit('TA', 5000, 0.03)
        assert tp.target_price == 5150  # 5000 * (1 + 0.03)
    
    def test_fixed_take_profit_calculate(self):
        """测试固定止盈计算"""
        tp = FixedTakeProfit('TA', 5000, 0.03)
        assert tp.calculate_target_price(4950) == 5150
        assert tp.calculate_target_price(5100) == 5150
    
    def test_fixed_take_profit_trigger_above(self):
        """测试固定止盈触发（价格高于目标价）"""
        tp = FixedTakeProfit('TA', 5000, 0.03)
        assert tp.check_trigger(5151) == True
        assert tp.is_triggered == True
    
    def test_fixed_take_profit_no_trigger(self):
        """测试固定止盈未触发"""
        tp = FixedTakeProfit('TA', 5000, 0.03)
        assert tp.check_trigger(5149) == False
        assert tp.is_triggered == False
    
    def test_trailing_take_profit_initial(self):
        """测试追踪止盈初始计算"""
        tp = TrailingTakeProfit('TA', 5000, 0.02)
        assert tp.target_price == 4900  # 5000 * (1 - 0.02)
        assert tp.highest_price == 5000
    
    def test_trailing_take_profit_trail_up(self):
        """测试追踪止盈跟随上涨"""
        tp = TrailingTakeProfit('TA', 5000, 0.02)
        # 价格上涨到5100
        target_price = tp.calculate_target_price(5100)
        assert tp.highest_price == 5100
        assert target_price == 4998  # 5100 * (1 - 0.02)
        assert tp.trailing_count == 1
        
        # 价格继续上涨到5200
        target_price = tp.calculate_target_price(5200)
        assert tp.highest_price == 5200
        assert target_price == 5096  # 5200 * (1 - 0.02)
        assert tp.trailing_count == 2
    
    def test_trailing_take_profit_trigger(self):
        """测试追踪止盈触发（价格回落至目标价）"""
        tp = TrailingTakeProfit('TA', 5000, 0.02)
        tp.calculate_target_price(5100)  # 目标价变为4998
        assert tp.check_trigger(4997) == True
        assert tp.is_triggered == True


class TestPosition:
    """仓位对象测试"""
    
    def test_position_init(self):
        """测试仓位初始化"""
        pos = Position('TA', 'long', 10, 5000)
        assert pos.symbol == 'TA'
        assert pos.direction == 'long'
        assert pos.quantity == 10
        assert pos.entry_price == 5000
        assert pos.current_price == 5000
    
    def test_position_pnl_long(self):
        """测试多头仓位盈亏"""
        pos = Position('TA', 'long', 10, 5000)
        pos.update_current_price(5100)
        assert pos.pnl == 1000  # (5100 - 5000) * 10
        assert pos.pnl_pct == 2.0  # 2%
    
    def test_position_pnl_short(self):
        """测试空头仓位盈亏"""
        pos = Position('TA', 'short', 10, 5000)
        pos.update_current_price(4900)
        assert pos.pnl == 1000  # (5000 - 4900) * 10
        assert pos.pnl_pct == 2.0  # 2%
    
    def test_position_pnl_loss(self):
        """测试亏损情况"""
        pos = Position('TA', 'long', 10, 5000)
        pos.update_current_price(4900)
        assert pos.pnl == -1000
        assert pos.pnl_pct == -2.0


class TestPositionManager:
    """仓位管理器测试"""
    
    def test_position_manager_init(self):
        """测试仓位管理器初始化"""
        pm = PositionManager(100000.0, 0.01)
        assert pm.account_balance == 100000.0
        assert pm.risk_per_trade == 0.01
        assert pm.positions == {}
    
    def test_calculate_position_size_fixed(self):
        """测试固定金额仓位计算"""
        pm = PositionManager(100000.0)
        size = pm.calculate_position_size_fixed(5000, 10000)
        assert size == 2  # 10000 / 5000 = 2
    
    def test_calculate_position_size_risk(self):
        """测试风险百分比仓位计算"""
        pm = PositionManager(100000.0, 0.01)
        # 风险金额: 100000 * 0.01 = 1000
        # 每单位风险: 5000 - 4900 = 100
        # 仓位大小: 1000 / 100 = 10
        size = pm.calculate_position_size_risk(5000, 4900)
        assert size == 10
    
    def test_calculate_position_size_risk_zero_diff(self):
        """测试风险计算（入场价等于止损价）"""
        pm = PositionManager(100000.0)
        size = pm.calculate_position_size_risk(5000, 5000)
        assert size == 0
    
    def test_calculate_position_size_quantity(self):
        """测试固定数量仓位计算"""
        pm = PositionManager(100000.0)
        size = pm.calculate_position_size_quantity(5)
        assert size == 5
    
    def test_open_position(self):
        """测试开仓"""
        pm = PositionManager(100000.0)
        pm.open_position('TA', 'long', 10, 5000, 4900, 5100)
        
        assert 'TA' in pm.positions
        pos = pm.positions['TA']
        assert pos.symbol == 'TA'
        assert pos.direction == 'long'
        assert pos.quantity == 10
        assert pos.entry_price == 5000
        assert pos.stop_loss_price == 4900
        assert pos.take_profit_price == 5100
    
    def test_close_position(self):
        """测试平仓"""
        pm = PositionManager(100000.0)
        pm.open_position('TA', 'long', 10, 5000)
        pm.positions['TA'].update_current_price(5100)
        
        pnl, pnl_pct = pm.close_position('TA', 5100)
        
        assert pnl == 1000
        assert pnl_pct == 2.0
        assert 'TA' not in pm.positions
    
    def test_close_nonexistent_position(self):
        """测试平仓不存在的仓位"""
        pm = PositionManager(100000.0)
        pnl, pnl_pct = pm.close_position('TA', 5000)
        assert pnl == 0.0
        assert pnl_pct == 0.0
    
    def test_update_price(self):
        """测试更新价格"""
        pm = PositionManager(100000.0)
        pm.open_position('TA', 'long', 10, 5000)
        pm.update_price('TA', 5050)
        
        assert pm.positions['TA'].current_price == 5050
    
    def test_total_pnl(self):
        """测试总盈亏"""
        pm = PositionManager(100000.0)
        pm.open_position('TA', 'long', 10, 5000)
        pm.open_position('RU', 'long', 5, 6000)
        
        pm.positions['TA'].update_current_price(5100)  # PNL: 1000
        pm.positions['RU'].update_current_price(5900)  # PNL: -500
        
        assert pm.total_pnl == 500
    
    def test_total_position_value(self):
        """测试总持仓价值"""
        pm = PositionManager(100000.0)
        pm.open_position('TA', 'long', 10, 5000)
        pm.open_position('RU', 'long', 5, 6000)
        
        pm.positions['TA'].update_current_price(5050)
        pm.positions['RU'].update_current_price(6100)
        
        assert pm.total_position_value == 5050 * 10 + 6100 * 5  # 50500 + 30500 = 81000


class TestMoneyManager:
    """资金管理器测试"""
    
    def test_money_manager_init(self):
        """测试资金管理器初始化"""
        mm = MoneyManager(100000.0, 0.10, 0.20, 0.01)
        assert mm.initial_balance == 100000.0
        assert mm.current_balance == 100000.0
        assert mm.max_drawdown == 0.10
        assert mm.max_risk_exposure == 0.20
        assert mm.highest_balance == 100000.0
    
    def test_current_drawdown_no_drawdown(self):
        """测试当前回撤（无回撤）"""
        mm = MoneyManager(100000.0)
        assert mm.current_drawdown == 0.0
    
    def test_current_drawdown_with_loss(self):
        """测试当前回撤（有亏损）"""
        mm = MoneyManager(100000.0)
        mm.update_balance(90000.0)
        assert mm.current_drawdown == 0.10  # 10%
    
    def test_max_drawdown_exceeded(self):
        """测试超过最大回撤"""
        mm = MoneyManager(100000.0, 0.10)
        mm.update_balance(89000.0)  # 11%回撤
        assert mm.max_drawdown_exceeded == True
    
    def test_max_drawdown_not_exceeded(self):
        """测试未超过最大回撤"""
        mm = MoneyManager(100000.0, 0.10)
        mm.update_balance(91000.0)  # 9%回撤
        assert mm.max_drawdown_exceeded == False
    
    def test_update_balance_new_high(self):
        """测试更新余额（创新高）"""
        mm = MoneyManager(100000.0)
        mm.update_balance(105000.0)
        assert mm.current_balance == 105000.0
        assert mm.highest_balance == 105000.0
    
    def test_add_trade_profit(self):
        """测试添加盈利交易"""
        mm = MoneyManager(100000.0)
        trade = TradeRecord(
            trade_id='test1',
            symbol='TA',
            direction='long',
            entry_price=5000,
            exit_price=5100,
            quantity=10,
            pnl=1000,
            pnl_pct=2.0,
            timestamp='2024-01-01 10:00:00'
        )
        mm.add_trade(trade)
        
        assert len(mm.trade_records) == 1
        assert mm.current_balance == 101000.0
        assert mm.highest_balance == 101000.0
    
    def test_add_trade_loss(self):
        """测试添加亏损交易"""
        mm = MoneyManager(100000.0)
        trade = TradeRecord(
            trade_id='test2',
            symbol='TA',
            direction='long',
            entry_price=5000,
            exit_price=4900,
            quantity=10,
            pnl=-1000,
            pnl_pct=-2.0,
            timestamp='2024-01-01 11:00:00'
        )
        mm.add_trade(trade)
        
        assert len(mm.trade_records) == 1
        assert mm.current_balance == 99000.0
        assert mm.highest_balance == 100000.0  # 最高价不变
    
    def test_can_open_new_position_ok(self):
        """测试可以开新仓"""
        mm = MoneyManager(100000.0)
        assert mm.can_open_new_position(1000) == True
    
    def test_can_open_new_position_drawdown_exceeded(self):
        """测试超过最大回撤不能开仓"""
        mm = MoneyManager(100000.0, 0.10)
        mm.update_balance(89000.0)  # 11%回撤
        assert mm.can_open_new_position(1000) == False
    
    def test_get_trade_statistics_empty(self):
        """测试空交易记录统计"""
        mm = MoneyManager(100000.0)
        stats = mm.get_trade_statistics()
        
        assert stats['total_trades'] == 0
        assert stats['win_count'] == 0
        assert stats['loss_count'] == 0
        assert stats['win_rate'] == 0.0
    
    def test_get_trade_statistics_with_trades(self):
        """测试交易统计"""
        mm = MoneyManager(100000.0)
        
        # 添加盈利交易
        mm.add_trade(TradeRecord('t1', 'TA', 'long', 5000, 5100, 10, 1000, 2.0, '2024-01-01'))
        mm.add_trade(TradeRecord('t2', 'TA', 'long', 5000, 5200, 10, 2000, 4.0, '2024-01-02'))
        # 添加亏损交易
        mm.add_trade(TradeRecord('t3', 'TA', 'long', 5000, 4900, 10, -1000, -2.0, '2024-01-03'))
        
        stats = mm.get_trade_statistics()
        
        assert stats['total_trades'] == 3
        assert stats['win_count'] == 2
        assert stats['loss_count'] == 1
        assert stats['win_rate'] == 2/3 * 100  # ~66.67%
        assert stats['avg_win'] == (1000 + 2000) / 2  # 1500
        assert stats['avg_loss'] == 1000
        assert stats['profit_factor'] == 1.5
        assert stats['total_pnl'] == 2000


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

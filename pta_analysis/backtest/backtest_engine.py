#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测引擎模块
执行策略回测并生成结果
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
import pandas as pd

from .strategy_base import StrategyBase, StrategySignal
from .performance_metrics import calculate_performance_metrics


class TradeResult:
    """单笔交易结果"""

    def __init__(self, trade_id: str, entry_time: str, exit_time: str,
                 direction: str, entry_price: float, exit_price: float,
                 quantity: int = 1, stop_loss: Optional[float] = None,
                 take_profit: Optional[float] = None,
                 entry_bar_index: int = -1, exit_bar_index: int = -1,
                 exit_reason: str = 'signal'):
        self.trade_id = trade_id
        self.entry_time = entry_time
        self.exit_time = exit_time
        self.direction = direction
        self.entry_price = entry_price
        self.exit_price = exit_price
        self.quantity = quantity
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.entry_bar_index = entry_bar_index
        self.exit_bar_index = exit_bar_index
        self.exit_reason = exit_reason  # 'signal', 'stop_loss', 'take_profit'

    @property
    def pnl(self) -> float:
        """计算盈亏"""
        if self.direction == 'long':
            return (self.exit_price - self.entry_price) * self.quantity
        else:
            return (self.entry_price - self.exit_price) * self.quantity

    @property
    def pnl_pct(self) -> float:
        """计算盈亏百分比"""
        if self.entry_price == 0:
            return 0.0
        return self.pnl / (self.entry_price * self.quantity) * 100

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典，包含属性"""
        return {
            'trade_id': self.trade_id,
            'entry_time': self.entry_time,
            'exit_time': self.exit_time,
            'direction': self.direction,
            'entry_price': self.entry_price,
            'exit_price': self.exit_price,
            'quantity': self.quantity,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'pnl': self.pnl,
            'pnl_pct': self.pnl_pct,
            'entry_bar_index': self.entry_bar_index,
            'exit_bar_index': self.exit_bar_index,
            'exit_reason': self.exit_reason
        }


class BacktestEngine:
    """回测引擎"""
    
    def __init__(self, initial_balance: float = 100000.0, 
                 risk_per_trade: float = 0.01, commission_rate: float = 0.0001):
        self.initial_balance = initial_balance
        self.risk_per_trade = risk_per_trade
        self.commission_rate = commission_rate
        self.balance = initial_balance
        self.equity_curve = []
        self.trades: List[TradeResult] = []
        self.current_position = None  # 'long', 'short', or None
        self.current_entry_price = None
        self.current_stop_loss = None
        self.current_take_profit = None
        self.trade_counter = 0
        self.current_entry_bar_index = -1  # 新增：记录入场bar索引
        self.trade_entries: List[Dict[str, Any]] = []  # 新增：记录入场点信息（用于可视化）

    def _calculate_position_size(self, entry_price: float, stop_price: float) -> int:
        """计算仓位大小"""
        if entry_price == stop_price:
            return 1

        risk_amount = self.balance * self.risk_per_trade
        risk_per_unit = abs(entry_price - stop_price)

        if risk_per_unit <= 0:
            return 1

        position_size = int(risk_amount / risk_per_unit)
        return max(1, position_size)

    def _execute_trade(self, signal: StrategySignal, bar: Dict[str, Any], 
                       bar_index: int = -1, exit_reason: str = 'signal') -> Optional[TradeResult]:
        """执行交易"""
        if signal.signal_type == 'buy' and self.current_position is None:
            # 开多
            stop_price = signal.stop_loss if signal.stop_loss else signal.price * 0.98
            position_size = self._calculate_position_size(signal.price, stop_price)

            self.current_position = 'long'
            self.current_entry_price = signal.price
            self.current_stop_loss = signal.stop_loss
            self.current_take_profit = signal.take_profit
            self.current_entry_bar_index = bar_index

            # 记录入场点（用于可视化）
            self.trade_entries.append({
                'type': 'entry',
                'direction': 'long',
                'bar_index': bar_index,
                'time': bar.get('time', ''),
                'price': signal.price,
                'stop_loss': signal.stop_loss,
                'take_profit': signal.take_profit
            })

            return None  # 开仓不返回交易结果

        elif signal.signal_type == 'sell' and self.current_position is None:
            # 开空
            stop_price = signal.stop_loss if signal.stop_loss else signal.price * 1.02
            position_size = self._calculate_position_size(signal.price, stop_price)

            self.current_position = 'short'
            self.current_entry_price = signal.price
            self.current_stop_loss = signal.stop_loss
            self.current_take_profit = signal.take_profit
            self.current_entry_bar_index = bar_index

            # 记录入场点（用于可视化）
            self.trade_entries.append({
                'type': 'entry',
                'direction': 'short',
                'bar_index': bar_index,
                'time': bar.get('time', ''),
                'price': signal.price,
                'stop_loss': signal.stop_loss,
                'take_profit': signal.take_profit
            })

            return None  # 开仓不返回交易结果

        elif signal.signal_type == 'close' and self.current_position is not None:
            # 平仓
            exit_price = bar['close']
            trade = TradeResult(
                trade_id=f"trade_{self.trade_counter}",
                entry_time=bar.get('time', ''),
                exit_time=bar.get('time', ''),
                direction=self.current_position,
                entry_price=self.current_entry_price,
                exit_price=exit_price,
                stop_loss=self.current_stop_loss,
                take_profit=self.current_take_profit,
                entry_bar_index=self.current_entry_bar_index,
                exit_bar_index=bar_index,
                exit_reason=exit_reason
            )

            # 更新余额
            pnl = trade.pnl
            commission = exit_price * 1 * self.commission_rate * 2  # 开仓+平仓
            self.balance += pnl - commission

            self.trades.append(trade)

            # 记录出场点（用于可视化）
            self.trade_entries.append({
                'type': 'exit',
                'direction': self.current_position,
                'bar_index': bar_index,
                'time': bar.get('time', ''),
                'price': exit_price,
                'exit_reason': exit_reason,
                'pnl': pnl
            })

            self.trade_counter += 1

            # 重置状态
            self.current_position = None
            self.current_entry_price = None
            self.current_stop_loss = None
            self.current_take_profit = None
            self.current_entry_bar_index = -1

            return trade

        return None

    def _check_stop_loss_take_profit(self, bar: Dict[str, Any], 
                                      bar_index: int = -1) -> Optional[TradeResult]:
        """检查止损/止盈"""
        if self.current_position is None:
            return None

        current_price = bar['close']

        # 检查止损
        if self.current_stop_loss:
            if self.current_position == 'long' and current_price <= self.current_stop_loss:
                return self._execute_trade(
                    StrategySignal('close', self.current_stop_loss, bar.get('time', '')),
                    bar, bar_index, 'stop_loss'
                )
            elif self.current_position == 'short' and current_price >= self.current_stop_loss:
                return self._execute_trade(
                    StrategySignal('close', self.current_stop_loss, bar.get('time', '')),
                    bar, bar_index, 'stop_loss'
                )

        # 检查止盈
        if self.current_take_profit:
            if self.current_position == 'long' and current_price >= self.current_take_profit:
                return self._execute_trade(
                    StrategySignal('close', self.current_take_profit, bar.get('time', '')),
                    bar, bar_index, 'take_profit'
                )
            elif self.current_position == 'short' and current_price <= self.current_take_profit:
                return self._execute_trade(
                    StrategySignal('close', self.current_take_profit, bar.get('time', '')),
                    bar, bar_index, 'take_profit'
                )

        return None

    def run(self, strategy: StrategyBase, data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        运行回测
        :param strategy: 策略实例
        :param data: K线数据列表
        :return: 回测结果
        """
        # 重置状态
        self.balance = self.initial_balance
        self.equity_curve = []
        self.trades = []
        self.current_position = None
        self.current_entry_price = None
        self.current_entry_bar_index = -1
        self.trade_entries = []
        self.trade_counter = 0
        strategy.reset()

        for i, bar in enumerate(data):
            # 检查止损/止盈
            self._check_stop_loss_take_profit(bar, i)

            # 执行策略
            signal = strategy.on_bar(bar)

            # 执行信号
            if signal:
                self._execute_trade(signal, bar, i, 'signal')

            # 记录权益曲线
            self.equity_curve.append({
                'time': bar.get('time', ''),
                'balance': self.balance,
                'position': self.current_position or 'none',
                'price': bar.get('close', 0)
            })

        # 计算统计指标
        stats = self._calculate_stats()

        return {
            'success': True,
            'initial_balance': self.initial_balance,
            'final_balance': self.balance,
            'total_return': (self.balance - self.initial_balance) / self.initial_balance * 100,
            'trades': [t.to_dict() for t in self.trades],
            'equity_curve': self.equity_curve,
            'statistics': stats,
            'trade_entries': self.trade_entries  # 新增：用于K线图标注
        }
    
    def _calculate_stats(self) -> Dict[str, Any]:
        """计算统计指标（委托给 performance_metrics 模块）"""
        trades_dict = [t.to_dict() for t in self.trades]
        return calculate_performance_metrics(trades_dict, self.equity_curve, self.initial_balance)

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


class TradeResult:
    """单笔交易结果"""
    
    def __init__(self, trade_id: str, entry_time: str, exit_time: str,
                 direction: str, entry_price: float, exit_price: float,
                 quantity: int = 1, stop_loss: Optional[float] = None,
                 take_profit: Optional[float] = None):
        self.trade_id = trade_id
        self.entry_time = entry_time
        self.exit_time = exit_time
        self.direction = direction
        self.entry_price = entry_price
        self.exit_price = exit_price
        self.quantity = quantity
        self.stop_loss = stop_loss
        self.take_profit = take_profit
    
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
            'pnl_pct': self.pnl_pct
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
    
    def _execute_trade(self, signal: StrategySignal, bar: Dict[str, Any]) -> Optional[TradeResult]:
        """执行交易"""
        if signal.signal_type == 'buy' and self.current_position is None:
            # 开多
            stop_price = signal.stop_loss if signal.stop_loss else signal.price * 0.98
            position_size = self._calculate_position_size(signal.price, stop_price)
            
            self.current_position = 'long'
            self.current_entry_price = signal.price
            self.current_stop_loss = signal.stop_loss
            self.current_take_profit = signal.take_profit
            
            return None  # 开仓不返回交易结果
        
        elif signal.signal_type == 'sell' and self.current_position is None:
            # 开空
            stop_price = signal.stop_loss if signal.stop_loss else signal.price * 1.02
            position_size = self._calculate_position_size(signal.price, stop_price)
            
            self.current_position = 'short'
            self.current_entry_price = signal.price
            self.current_stop_loss = signal.stop_loss
            self.current_take_profit = signal.take_profit
            
            return None  # 开仓不返回交易结果
        
        elif signal.signal_type == 'close' and self.current_position is not None:
            # 平仓
            exit_price = bar['close']
            trade = TradeResult(
                trade_id=f"trade_{self.trade_counter}",
                entry_time=self.current_entry_price,
                exit_time=bar.get('time', ''),
                direction=self.current_position,
                entry_price=self.current_entry_price,
                exit_price=exit_price,
                stop_loss=self.current_stop_loss,
                take_profit=self.current_take_profit
            )
            
            # 更新余额
            pnl = trade.pnl
            commission = exit_price * 1 * self.commission_rate * 2  # 开仓+平仓
            self.balance += pnl - commission
            
            self.trades.append(trade)
            self.trade_counter += 1
            
            # 重置状态
            self.current_position = None
            self.current_entry_price = None
            self.current_stop_loss = None
            self.current_take_profit = None
            
            return trade
        
        return None
    
    def _check_stop_loss_take_profit(self, bar: Dict[str, Any]) -> Optional[TradeResult]:
        """检查止损/止盈"""
        if self.current_position is None:
            return None
        
        current_price = bar['close']
        
        # 检查止损
        if self.current_stop_loss:
            if self.current_position == 'long' and current_price <= self.current_stop_loss:
                return self._execute_trade(
                    StrategySignal('close', self.current_stop_loss, bar.get('time', '')),
                    bar
                )
            elif self.current_position == 'short' and current_price >= self.current_stop_loss:
                return self._execute_trade(
                    StrategySignal('close', self.current_stop_loss, bar.get('time', '')),
                    bar
                )
        
        # 检查止盈
        if self.current_take_profit:
            if self.current_position == 'long' and current_price >= self.current_take_profit:
                return self._execute_trade(
                    StrategySignal('close', self.current_take_profit, bar.get('time', '')),
                    bar
                )
            elif self.current_position == 'short' and current_price <= self.current_take_profit:
                return self._execute_trade(
                    StrategySignal('close', self.current_take_profit, bar.get('time', '')),
                    bar
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
        self.trade_counter = 0
        strategy.reset()
        
        for bar in data:
            # 检查止损/止盈
            self._check_stop_loss_take_profit(bar)
            
            # 执行策略
            signal = strategy.on_bar(bar)
            
            # 执行信号
            if signal:
                self._execute_trade(signal, bar)
            
            # 记录权益曲线
            self.equity_curve.append({
                'time': bar.get('time', ''),
                'balance': self.balance,
                'position': self.current_position or 'none'
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
            'statistics': stats
        }
    
    def _calculate_stats(self) -> Dict[str, Any]:
        """计算统计指标"""
        if not self.trades:
            return {
                'total_trades': 0,
                'win_count': 0,
                'loss_count': 0,
                'win_rate': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'profit_factor': 0.0,
                'max_drawdown': 0.0,
                'sharpe_ratio': 0.0
            }
        
        total_trades = len(self.trades)
        win_trades = [t for t in self.trades if t.pnl > 0]
        loss_trades = [t for t in self.trades if t.pnl <= 0]
        
        win_count = len(win_trades)
        loss_count = len(loss_trades)
        win_rate = win_count / total_trades * 100
        
        avg_win = sum(t.pnl for t in win_trades) / win_count if win_count > 0 else 0.0
        avg_loss = abs(sum(t.pnl for t in loss_trades) / loss_count) if loss_count > 0 else 0.0
        
        profit_factor = avg_win / avg_loss if avg_loss > 0 else float('inf')
        
        # 计算最大回撤
        max_drawdown = 0.0
        peak = self.initial_balance
        for point in self.equity_curve:
            peak = max(peak, point['balance'])
            drawdown = (peak - point['balance']) / peak * 100
            max_drawdown = max(max_drawdown, drawdown)
        
        # 计算夏普比率（简化版，假设无风险利率为0）
        returns = []
        for i in range(1, len(self.equity_curve)):
            prev_balance = self.equity_curve[i-1]['balance']
            curr_balance = self.equity_curve[i]['balance']
            returns.append((curr_balance - prev_balance) / prev_balance)
        
        if returns:
            mean_return = sum(returns) / len(returns)
            std_return = (sum((r - mean_return) ** 2 for r in returns) / len(returns)) ** 0.5
            sharpe_ratio = mean_return / std_return * (252 ** 0.5) if std_return > 0 else 0.0
        else:
            sharpe_ratio = 0.0
        
        # 计算总盈亏
        total_pnl = sum(t.pnl for t in self.trades)
        final_balance = self.initial_balance + total_pnl
        total_return = (final_balance - self.initial_balance) / self.initial_balance * 100
        
        return {
            'total_trades': total_trades,
            'win_count': win_count,
            'loss_count': loss_count,
            'win_rate': round(win_rate, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'profit_factor': round(profit_factor, 2),
            'max_drawdown': round(max_drawdown, 2),
            'sharpe_ratio': round(sharpe_ratio, 2),
            'total_pnl': round(total_pnl, 2),
            'final_balance': round(final_balance, 2),
            'total_return': round(total_return, 2)
        }

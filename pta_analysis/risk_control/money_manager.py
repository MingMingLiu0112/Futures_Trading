#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资金管理模块
支持最大回撤控制、风险敞口限制等功能
"""

from typing import List, Dict, Optional


class TradeRecord:
    """交易记录"""
    
    def __init__(self, trade_id: str, symbol: str, direction: str, 
                 entry_price: float, exit_price: float, quantity: int, 
                 pnl: float, pnl_pct: float, timestamp: str):
        self.trade_id = trade_id
        self.symbol = symbol
        self.direction = direction
        self.entry_price = entry_price
        self.exit_price = exit_price
        self.quantity = quantity
        self.pnl = pnl
        self.pnl_pct = pnl_pct
        self.timestamp = timestamp


class MoneyManager:
    """资金管理器"""
    
    def __init__(self, initial_balance: float, max_drawdown: float = 0.10, 
                 max_risk_exposure: float = 0.20, risk_per_trade: float = 0.01):
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.max_drawdown = max_drawdown  # 最大回撤限制
        self.max_risk_exposure = max_risk_exposure  # 最大风险敞口
        self.risk_per_trade = risk_per_trade  # 每笔交易风险
        self.highest_balance = initial_balance
        self.trade_records: List[TradeRecord] = []
    
    @property
    def current_drawdown(self) -> float:
        """计算当前回撤"""
        if self.highest_balance == 0:
            return 0.0
        drawdown = (self.highest_balance - self.current_balance) / self.highest_balance
        return max(0.0, drawdown)
    
    @property
    def max_drawdown_exceeded(self) -> bool:
        """检查是否超过最大回撤"""
        return self.current_drawdown >= self.max_drawdown
    
    def update_balance(self, new_balance: float):
        """更新账户余额"""
        self.current_balance = new_balance
        if new_balance > self.highest_balance:
            self.highest_balance = new_balance
    
    def add_trade(self, trade_record: TradeRecord):
        """添加交易记录"""
        self.trade_records.append(trade_record)
        # 更新余额
        self.update_balance(self.current_balance + trade_record.pnl)
    
    def can_open_new_position(self, position_risk: float) -> bool:
        """
        检查是否可以开新仓
        :param position_risk: 新仓位风险金额
        :return: 是否允许开仓
        """
        # 检查最大回撤
        if self.max_drawdown_exceeded:
            return False
        
        # 检查风险敞口
        total_risk = sum(self._get_position_risk(pos) for pos in self._get_open_positions())
        total_risk += position_risk
        
        if total_risk / self.current_balance > self.max_risk_exposure:
            return False
        
        return True
    
    def _get_open_positions(self) -> List[dict]:
        """获取当前持仓（需与PositionManager集成）"""
        return []
    
    def _get_position_risk(self, position: dict) -> float:
        """计算仓位风险"""
        return 0.0
    
    def get_trade_statistics(self) -> Dict[str, float]:
        """获取交易统计"""
        if not self.trade_records:
            return {
                'total_trades': 0,
                'win_count': 0,
                'loss_count': 0,
                'win_rate': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'profit_factor': 0.0,
                'total_pnl': 0.0
            }
        
        total_trades = len(self.trade_records)
        win_trades = [t for t in self.trade_records if t.pnl > 0]
        loss_trades = [t for t in self.trade_records if t.pnl <= 0]
        
        win_count = len(win_trades)
        loss_count = len(loss_trades)
        win_rate = win_count / total_trades * 100
        
        avg_win = sum(t.pnl for t in win_trades) / win_count if win_count > 0 else 0.0
        avg_loss = abs(sum(t.pnl for t in loss_trades) / loss_count) if loss_count > 0 else 0.0
        
        profit_factor = avg_win / avg_loss if avg_loss > 0 else float('inf')
        total_pnl = sum(t.pnl for t in self.trade_records)
        
        return {
            'total_trades': total_trades,
            'win_count': win_count,
            'loss_count': loss_count,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'total_pnl': total_pnl
        }

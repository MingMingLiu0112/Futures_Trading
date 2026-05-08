#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
绩效指标计算模块
提供多种绩效评估指标
"""

from typing import List, Dict, Any


def calculate_performance_metrics(trades: List[Dict[str, Any]], 
                                  equity_curve: List[Dict[str, Any]],
                                  initial_balance: float) -> Dict[str, Any]:
    """
    计算绩效指标
    :param trades: 交易列表
    :param equity_curve: 权益曲线
    :param initial_balance: 初始资金
    :return: 绩效指标字典
    """
    if not trades:
        return _empty_stats()
    
    total_trades = len(trades)
    win_trades = [t for t in trades if t['pnl'] > 0]
    loss_trades = [t for t in trades if t['pnl'] <= 0]
    
    win_count = len(win_trades)
    loss_count = len(loss_trades)
    win_rate = win_count / total_trades * 100
    
    avg_win = sum(t['pnl'] for t in win_trades) / win_count if win_count > 0 else 0.0
    avg_loss = abs(sum(t['pnl'] for t in loss_trades) / loss_count) if loss_count > 0 else 0.0
    
    profit_factor = avg_win / avg_loss if avg_loss > 0 else float('inf')
    
    # 计算最大回撤
    max_drawdown = 0.0
    peak = initial_balance
    for point in equity_curve:
        peak = max(peak, point['balance'])
        drawdown = (peak - point['balance']) / peak * 100
        max_drawdown = max(max_drawdown, drawdown)
    
    # 计算夏普比率
    returns = []
    for i in range(1, len(equity_curve)):
        prev_balance = equity_curve[i-1]['balance']
        curr_balance = equity_curve[i]['balance']
        returns.append((curr_balance - prev_balance) / prev_balance)
    
    if returns:
        mean_return = sum(returns) / len(returns)
        std_return = (sum((r - mean_return) ** 2 for r in returns) / len(returns)) ** 0.5
        sharpe_ratio = mean_return / std_return * (252 ** 0.5) if std_return > 0 else 0.0
    else:
        sharpe_ratio = 0.0
    
    # 计算收益风险比
    profit_risk_ratio = avg_win / avg_loss if avg_loss > 0 else float('inf')
    
    # 计算总盈亏
    total_pnl = sum(t['pnl'] for t in trades)
    
    # 计算最终余额
    final_balance = initial_balance + total_pnl
    total_return = (final_balance - initial_balance) / initial_balance * 100
    
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
        'profit_risk_ratio': round(profit_risk_ratio, 2),
        'total_pnl': round(total_pnl, 2),
        'final_balance': round(final_balance, 2),
        'total_return': round(total_return, 2)
    }


def _empty_stats() -> Dict[str, Any]:
    """返回空统计结果"""
    return {
        'total_trades': 0,
        'win_count': 0,
        'loss_count': 0,
        'win_rate': 0.0,
        'avg_win': 0.0,
        'avg_loss': 0.0,
        'profit_factor': 0.0,
        'max_drawdown': 0.0,
        'sharpe_ratio': 0.0,
        'profit_risk_ratio': 0.0,
        'total_pnl': 0.0,
        'final_balance': 0.0,
        'total_return': 0.0
    }

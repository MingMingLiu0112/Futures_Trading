#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
绩效指标计算模块

计算完整的回测绩效指标，包括：
- 基础指标：胜率、盈亏比、总交易次数
- 风险指标：最大回撤、夏普比率、索提诺比率、卡尔玛比率
- 连续性指标：最大连续亏损次数、最大连续盈利次数
- 每日指标：日均盈亏

用法:
```python
from backtest.performance_metrics import calculate_performance_metrics

metrics = calculate_performance_metrics(trades, equity_curve, initial_balance)
```
"""

from typing import Any, Dict, List, Optional
import math


def calculate_performance_metrics(
    trades: List[Dict[str, Any]],
    equity_curve: List[Dict[str, Any]],
    initial_balance: float,
    annual_days: int = 240,
    risk_free_rate: float = 0.0
) -> Dict[str, Any]:
    """
    计算完整的绩效指标

    Args:
        trades: 交易记录列表，每笔包含 trade_id, direction, entry_price, exit_price,
                quantity, pnl, pnl_pct, exit_reason, entry_time, exit_time
        equity_curve: 权益曲线，列表包含 {'time': str, 'balance': float}
        initial_balance: 初始资金
        annual_days: 年化交易日数，默认240
        risk_free_rate: 无风险利率，默认0

    Returns:
        包含所有绩效指标的字典
    """
    if not trades or not equity_curve:
        return _empty_metrics()

    # ========== 基础统计 ==========
    total_trades = len(trades)
    winning_trades = [t for t in trades if t.get('pnl', 0) > 0]
    losing_trades = [t for t in trades if t.get('pnl', 0) < 0]
    win_count = len(winning_trades)
    loss_count = len(losing_trades)

    win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0

    # 总盈亏
    total_pnl = sum(t.get('pnl', 0) for t in trades)
    total_win = sum(t.get('pnl', 0) for t in winning_trades)
    total_loss = abs(sum(t.get('pnl', 0) for t in losing_trades))

    # 盈亏比
    avg_win = total_win / win_count if win_count > 0 else 0
    avg_loss = total_loss / loss_count if loss_count > 0 else 0
    profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0

    # ========== 权益曲线分析 ==========
    balances = [eq['balance'] for eq in equity_curve]
    final_balance = balances[-1] if balances else initial_balance

    # 计算每日收益率
    returns = []
    for i in range(1, len(balances)):
        if balances[i-1] > 0:
            ret = (balances[i] - balances[i-1]) / balances[i-1]
            returns.append(ret)

    # ========== 最大回撤 ==========
    peak = initial_balance
    max_drawdown = 0
    max_drawdown_pct = 0
    peak_balance = initial_balance

    for balance in balances:
        if balance > peak_balance:
            peak_balance = balance
        dd = peak_balance - balance
        dd_pct = (dd / peak_balance * 100) if peak_balance > 0 else 0
        if dd > max_drawdown:
            max_drawdown = dd
            max_drawdown_pct = dd_pct

    # ========== 年化收益率 ==========
    total_return_pct = (final_balance - initial_balance) / initial_balance * 100

    if equity_curve and len(equity_curve) > 1:
        first_time = equity_curve[0].get('time', '')
        last_time = equity_curve[-1].get('time', '')
        # 简单估算：假设每日一条数据
        days = len(equity_curve)
        annual_return = total_return_pct / days * annual_days if days > 0 else 0
    else:
        days = 1
        annual_return = total_return_pct

    # ========== 夏普比率 ==========
    if len(returns) > 1:
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_return = math.sqrt(variance)

        if std_return > 0:
            daily_rf = risk_free_rate / annual_days
            sharpe_ratio = (mean_return - daily_rf) / std_return * math.sqrt(annual_days)
        else:
            sharpe_ratio = 0
    else:
        sharpe_ratio = 0
        std_return = 0

    # ========== 索提诺比率 (Sortino Ratio) ==========
    # 只考虑下行风险（负收益）
    if len(returns) > 1:
        mean_return = sum(returns) / len(returns)
        downside_returns = [r for r in returns if r < 0]
        if downside_returns:
            downside_var = sum(r ** 2 for r in downside_returns) / len(downside_returns)
            downside_std = math.sqrt(downside_var)
            if downside_std > 0:
                daily_rf = risk_free_rate / annual_days
                sortino_ratio = (mean_return - daily_rf) / downside_std * math.sqrt(annual_days)
            else:
                sortino_ratio = 0
        else:
            sortino_ratio = 0
    else:
        sortino_ratio = 0

    # ========== 卡尔玛比率 (Calmar Ratio) ==========
    # 年化收益率 / 最大回撤百分比
    if max_drawdown_pct > 0:
        calmar_ratio = annual_return / max_drawdown_pct
    else:
        calmar_ratio = 0

    # ========== 最大连续亏损/盈利 ==========
    max_consecutive_losses = 0
    max_consecutive_wins = 0
    current_loss_streak = 0
    current_win_streak = 0

    for trade in trades:
        pnl = trade.get('pnl', 0)
        if pnl > 0:
            current_win_streak += 1
            current_loss_streak = 0
            max_consecutive_wins = max(max_consecutive_wins, current_win_streak)
        elif pnl < 0:
            current_loss_streak += 1
            current_win_streak = 0
            max_consecutive_losses = max(max_consecutive_losses, current_loss_streak)
        else:
            current_win_streak = 0
            current_loss_streak = 0

    # ========== 日均盈亏 ==========
    daily_pnl = total_pnl / max(days, 1)

    # ========== 收益回撤比 ==========
    return_drawdown_ratio = -total_pnl / max_drawdown if max_drawdown > 0 else 0

    # ========== 构建结果 ==========
    metrics = {
        # 基础统计
        'total_trades': total_trades,
        'win_count': win_count,
        'loss_count': loss_count,
        'win_rate': round(win_rate, 2),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'profit_loss_ratio': round(profit_loss_ratio, 2),
        'total_pnl': round(total_pnl, 2),
        'total_return': round(total_return_pct, 2),

        # 资金
        'initial_balance': initial_balance,
        'final_balance': round(final_balance, 2),
        'max_drawdown': round(max_drawdown, 2),
        'max_drawdown_pct': round(max_drawdown_pct, 2),

        # 风险指标
        'sharpe_ratio': round(sharpe_ratio, 4),
        'sortino_ratio': round(sortino_ratio, 4),
        'calmar_ratio': round(calmar_ratio, 4),
        'return_drawdown_ratio': round(return_drawdown_ratio, 2),

        # 连续性
        'max_consecutive_losses': max_consecutive_losses,
        'max_consecutive_wins': max_consecutive_wins,

        # 收益指标
        'annual_return': round(annual_return, 2),
        'daily_pnl': round(daily_pnl, 2),
        'return_std': round(std_return * 100, 4) if std_return else 0,
    }

    return metrics


def _empty_metrics() -> Dict[str, Any]:
    """返回空指标"""
    return {
        'total_trades': 0, 'win_count': 0, 'loss_count': 0,
        'win_rate': 0, 'avg_win': 0, 'avg_loss': 0,
        'profit_loss_ratio': 0, 'total_pnl': 0, 'total_return': 0,
        'initial_balance': 0, 'final_balance': 0,
        'max_drawdown': 0, 'max_drawdown_pct': 0,
        'sharpe_ratio': 0, 'sortino_ratio': 0, 'calmar_ratio': 0,
        'return_drawdown_ratio': 0,
        'max_consecutive_losses': 0, 'max_consecutive_wins': 0,
        'annual_return': 0, 'daily_pnl': 0, 'return_std': 0,
    }

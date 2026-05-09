
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
绩效指标计算模块
提供多种绩效评估指标
"""

from typing import List, Dict, Any, Tuple
import math


def calculate_performance_metrics(trades: List[Dict[str, Any]], 
                                  equity_curve: List[Dict[str, Any]],
                                  initial_balance: float,
                                  annual_days: int = 252) -> Dict[str, Any]:
    """
    计算绩效指标
    :param trades: 交易列表
    :param equity_curve: 权益曲线
    :param initial_balance: 初始资金
    :param annual_days: 年化交易日天数（默认252）
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
    
    # 盈亏比
    profit_factor = avg_win / avg_loss if avg_loss > 0 else float('inf')
    
    # ========== 最大回撤 ==========
    max_drawdown, max_drawdown_pct, dd_start_time, dd_end_time = _calculate_max_drawdown(
        equity_curve, initial_balance
    )
    
    # ========== 夏普比率 ==========
    sharpe_ratio = _calculate_sharpe_ratio(equity_curve, annual_days)
    
    # ========== 索提诺比率（只考虑下行风险）==========
    sortino_ratio = _calculate_sortino_ratio(equity_curve, annual_days)
    
    # ========== 卡尔玛比率 ==========
    calmar_ratio = _calculate_calmar_ratio(max_drawdown_pct, equity_curve, annual_days)
    
    # ========== 最大连续亏损 ==========
    max_consecutive_losses, max_consecutive_wins = _calculate_consecutive_trades(trades)
    
    # ========== 日均盈亏 ==========
    daily_pnl, trading_days = _calculate_daily_pnl(equity_curve, initial_balance)
    
    # ========== 收益风险比 ==========
    profit_risk_ratio = avg_win / avg_loss if avg_loss > 0 else float('inf')
    
    # ========== 总盈亏 ==========
    total_pnl = sum(t['pnl'] for t in trades)
    final_balance = initial_balance + total_pnl
    total_return = (final_balance - initial_balance) / initial_balance * 100
    
    # ========== 年化收益率 ==========
    annual_return = _calculate_annual_return(total_return, trading_days, annual_days)
    
    # ========== 持仓时间统计 ==========
    avg_holding_bars, total_holding_bars = _calculate_holding_stats(trades)
    
    # ========== 止损止盈统计 ==========
    sl_count, tp_count, close_count = _calculate_exit_stats(trades)
    
    return {
        # 基础统计
        'total_trades': total_trades,
        'win_count': win_count,
        'loss_count': loss_count,
        'win_rate': round(win_rate, 2),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'profit_factor': round(profit_factor, 2) if profit_factor != float('inf') else 999.99,
        
        # 收益指标
        'total_pnl': round(total_pnl, 2),
        'final_balance': round(final_balance, 2),
        'total_return': round(total_return, 2),
        'annual_return': round(annual_return, 2),
        'daily_pnl': round(daily_pnl, 2),
        
        # 风险指标
        'max_drawdown': round(max_drawdown, 2),
        'max_drawdown_pct': round(max_drawdown_pct, 2),
        'max_consecutive_losses': max_consecutive_losses,
        'max_consecutive_wins': max_consecutive_wins,
        
        # 比率指标
        'sharpe_ratio': round(sharpe_ratio, 3),
        'sortino_ratio': round(sortino_ratio, 3),
        'calmar_ratio': round(calmar_ratio, 3) if not math.isinf(calmar_ratio) else 999.99,
        'profit_risk_ratio': round(profit_risk_ratio, 2) if profit_risk_ratio != float('inf') else 999.99,
        
        # 持仓统计
        'avg_holding_bars': round(avg_holding_bars, 1),
        'total_holding_bars': total_holding_bars,
        
        # 退出统计
        'stop_loss_count': sl_count,
        'take_profit_count': tp_count,
        'close_count': close_count,
    }


def _calculate_max_drawdown(equity_curve: List[Dict[str, Any]], initial_balance: float) -> Tuple[float, float, str, str]:
    """计算最大回撤及相关信息"""
    max_drawdown = 0.0
    max_drawdown_pct = 0.0
    peak = initial_balance
    dd_start_time = ''
    dd_end_time = ''
    
    for point in equity_curve:
        current_balance = point.get('balance', initial_balance)
        if current_balance >= peak:
            peak = current_balance
        else:
            drawdown = peak - current_balance
            drawdown_pct = (drawdown / peak * 100) if peak > 0 else 0
            
            if drawdown > max_drawdown:
                max_drawdown = drawdown
                max_drawdown_pct = drawdown_pct
                dd_end_time = point.get('time', '')
    
    return max_drawdown, max_drawdown_pct, dd_start_time, dd_end_time


def _calculate_sharpe_ratio(equity_curve: List[Dict[str, Any]], annual_days: int = 252) -> float:
    """计算夏普比率"""
    if len(equity_curve) < 2:
        return 0.0
    
    returns = []
    for i in range(1, len(equity_curve)):
        prev_balance = equity_curve[i-1].get('balance', 0)
        curr_balance = equity_curve[i].get('balance', 0)
        if prev_balance > 0:
            returns.append((curr_balance - prev_balance) / prev_balance)
    
    if not returns:
        return 0.0
    
    mean_return = sum(returns) / len(returns)
    std_return = math.sqrt(sum((r - mean_return) ** 2 for r in returns) / len(returns))
    
    if std_return == 0:
        return 0.0
    
    # 年化夏普比率
    sharpe = (mean_return / std_return) * math.sqrt(annual_days)
    return sharpe


def _calculate_sortino_ratio(equity_curve: List[Dict[str, Any]], annual_days: int = 252, target_return: float = 0.0) -> float:
    """计算索提诺比率（只考虑下行风险）"""
    if len(equity_curve) < 2:
        return 0.0
    
    returns = []
    for i in range(1, len(equity_curve)):
        prev_balance = equity_curve[i-1].get('balance', 0)
        curr_balance = equity_curve[i].get('balance', 0)
        if prev_balance > 0:
            returns.append((curr_balance - prev_balance) / prev_balance)
    
    if not returns:
        return 0.0
    
    mean_return = sum(returns) / len(returns)
    
    # 只计算下行偏差
    downside_returns = [r for r in returns if r < target_return]
    if not downside_returns:
        return 0.0  # 没有下行波动
    
    downside_std = math.sqrt(sum((r - target_return) ** 2 for r in downside_returns) / len(downside_returns))
    
    if downside_std == 0:
        return 0.0
    
    sortino = (mean_return / downside_std) * math.sqrt(annual_days)
    return sortino


def _calculate_calmar_ratio(max_drawdown_pct: float, equity_curve: List[Dict[str, Any]], annual_days: int = 252) -> float:
    """计算卡尔玛比率（年化收益/最大回撤）"""
    if max_drawdown_pct == 0:
        return float('inf')
    
    if len(equity_curve) < 2:
        return 0.0
    
    # 计算年化收益率
    initial = equity_curve[0].get('balance', 0)
    final = equity_curve[-1].get('balance', initial)
    
    if initial <= 0:
        return 0.0
    
    total_return = (final - initial) / initial
    trading_days = len(equity_curve)
    
    if trading_days < 2:
        return 0.0
    
    # 年化
    years = trading_days / annual_days
    annual_return = ((1 + total_return) ** (1 / years) - 1) if years > 0 else 0
    
    calmar = annual_return / (max_drawdown_pct / 100)
    return calmar


def _calculate_consecutive_trades(trades: List[Dict[str, Any]]) -> Tuple[int, int]:
    """计算最大连续亏损/盈利次数"""
    if not trades:
        return 0, 0
    
    max_consecutive_losses = 0
    max_consecutive_wins = 0
    current_losses = 0
    current_wins = 0
    
    for trade in trades:
        if trade['pnl'] <= 0:
            current_losses += 1
            current_wins = 0
            max_consecutive_losses = max(max_consecutive_losses, current_losses)
        else:
            current_wins += 1
            current_losses = 0
            max_consecutive_wins = max(max_consecutive_wins, current_wins)
    
    return max_consecutive_losses, max_consecutive_wins


def _calculate_daily_pnl(equity_curve: List[Dict[str, Any]], initial_balance: float) -> Tuple[float, int]:
    """计算日均盈亏"""
    if len(equity_curve) < 2:
        return 0.0, 0
    
    total_pnl = equity_curve[-1].get('balance', initial_balance) - initial_balance
    trading_days = len(equity_curve)
    
    daily_pnl = total_pnl / trading_days if trading_days > 0 else 0.0
    return daily_pnl, trading_days


def _calculate_annual_return(total_return: float, trading_days: int, annual_days: int = 252) -> float:
    """计算年化收益率"""
    if trading_days <= 0 or total_return <= -1:
        return 0.0
    
    years = trading_days / annual_days
    if years <= 0:
        return 0.0
    
    annual_return = ((1 + total_return / 100) ** (1 / years) - 1) * 100
    return annual_return


def _calculate_holding_stats(trades: List[Dict[str, Any]]) -> Tuple[float, int]:
    """计算持仓时间统计"""
    if not trades:
        return 0.0, 0
    
    total_bars = 0
    for trade in trades:
        # 估算持仓bar数（如果有exit_time的话需要解析）
        entry_price = trade.get('entry_price', 0)
        exit_price = trade.get('exit_price', 0)
        if entry_price > 0 and exit_price > 0:
            # 使用价格变动估算（简化处理）
            price_change_pct = abs(exit_price - entry_price) / entry_price
            # 假设每1%价格变动代表约1个bar（非常粗略的估算）
            estimated_bars = max(1, int(price_change_pct * 100))
            total_bars += estimated_bars
    
    avg_bars = total_bars / len(trades) if trades else 0
    return avg_bars, total_bars


def _calculate_exit_stats(trades: List[Dict[str, Any]]) -> Tuple[int, int, int]:
    """统计止损/止盈/主动平仓次数"""
    sl_count = 0
    tp_count = 0
    close_count = 0
    
    for trade in trades:
        sl = trade.get('stop_loss')
        tp = trade.get('take_profit')
        exit_price = trade.get('exit_price', 0)
        entry_price = trade.get('entry_price', 0)
        direction = trade.get('direction', 'long')
        
        if not sl or not tp or not entry_price or not exit_price:
            close_count += 1
            continue
        
        # 判断退出原因
        if direction == 'long':
            if exit_price <= sl:
                sl_count += 1
            elif exit_price >= tp:
                tp_count += 1
            else:
                close_count += 1
        else:  # short
            if exit_price >= sl:
                sl_count += 1
            elif exit_price <= tp:
                tp_count += 1
            else:
                close_count += 1
    
    return sl_count, tp_count, close_count


def _empty_stats() -> Dict[str, Any]:
    """返回空统计结果"""
    return {
        # 基础统计
        'total_trades': 0,
        'win_count': 0,
        'loss_count': 0,
        'win_rate': 0.0,
        'avg_win': 0.0,
        'avg_loss': 0.0,
        'profit_factor': 0.0,
        
        # 收益指标
        'total_pnl': 0.0,
        'final_balance': 0.0,
        'total_return': 0.0,
        'annual_return': 0.0,
        'daily_pnl': 0.0,
        
        # 风险指标
        'max_drawdown': 0.0,
        'max_drawdown_pct': 0.0,
        'max_consecutive_losses': 0,
        'max_consecutive_wins': 0,
        
        # 比率指标
        'sharpe_ratio': 0.0,
        'sortino_ratio': 0.0,
        'calmar_ratio': 0.0,
        'profit_risk_ratio': 0.0,
        
        # 持仓统计
        'avg_holding_bars': 0.0,
        'total_holding_bars': 0,
        
        # 退出统计
        'stop_loss_count': 0,
        'take_profit_count': 0,
        'close_count': 0,
    }

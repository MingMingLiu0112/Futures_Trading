#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
风险控制API模块
提供风险控制相关的REST API接口
"""

from flask import Blueprint, request, jsonify
from datetime import datetime
import uuid

from .stop_loss import FixedStopLoss, TrailingStopLoss
from .take_profit import FixedTakeProfit, TrailingTakeProfit
from .position_manager import PositionManager
from .money_manager import MoneyManager, TradeRecord

# 创建蓝图
risk_bp = Blueprint('risk', __name__)

# 全局状态管理（生产环境应使用Redis等持久化存储）
position_managers = {}
money_managers = {}


def get_position_manager(account_id: str) -> PositionManager:
    """获取或创建仓位管理器"""
    if account_id not in position_managers:
        position_managers[account_id] = PositionManager(100000.0)  # 默认10万资金
    return position_managers[account_id]


def get_money_manager(account_id: str) -> MoneyManager:
    """获取或创建资金管理器"""
    if account_id not in money_managers:
        money_managers[account_id] = MoneyManager(100000.0)
    return money_managers[account_id]


@risk_bp.route('/api/risk/stop-loss/calculate', methods=['POST'])
def calculate_stop_loss():
    """计算止损价格"""
    try:
        data = request.get_json()
        
        symbol = data.get('symbol', 'TA')
        initial_price = float(data.get('initial_price', 0))
        strategy_type = data.get('strategy_type', 'fixed')
        stop_pct = float(data.get('stop_pct', 0.02))
        current_price = float(data.get('current_price', initial_price))
        
        if strategy_type == 'trailing':
            strategy = TrailingStopLoss(symbol, initial_price, stop_pct)
        else:
            strategy = FixedStopLoss(symbol, initial_price, stop_pct)
        
        stop_price = strategy.calculate_stop_price(current_price)
        is_triggered = strategy.check_trigger(current_price)
        
        return jsonify({
            'success': True,
            'symbol': symbol,
            'strategy_type': strategy_type,
            'initial_price': initial_price,
            'current_price': current_price,
            'stop_price': stop_price,
            'is_triggered': is_triggered,
            'trailing_count': strategy.trailing_count,
            'timestamp': datetime.now().isoformat()
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400


@risk_bp.route('/api/risk/take-profit/calculate', methods=['POST'])
def calculate_take_profit():
    """计算止盈价格"""
    try:
        data = request.get_json()
        
        symbol = data.get('symbol', 'TA')
        initial_price = float(data.get('initial_price', 0))
        strategy_type = data.get('strategy_type', 'fixed')
        target_pct = float(data.get('target_pct', 0.03))
        current_price = float(data.get('current_price', initial_price))
        
        if strategy_type == 'trailing':
            strategy = TrailingTakeProfit(symbol, initial_price, target_pct)
        else:
            strategy = FixedTakeProfit(symbol, initial_price, target_pct)
        
        target_price = strategy.calculate_target_price(current_price)
        is_triggered = strategy.check_trigger(current_price)
        
        return jsonify({
            'success': True,
            'symbol': symbol,
            'strategy_type': strategy_type,
            'initial_price': initial_price,
            'current_price': current_price,
            'target_price': target_price,
            'is_triggered': is_triggered,
            'trailing_count': strategy.trailing_count,
            'timestamp': datetime.now().isoformat()
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400


@risk_bp.route('/api/risk/position/calculate', methods=['POST'])
def calculate_position():
    """计算仓位大小"""
    try:
        data = request.get_json()
        
        account_id = data.get('account_id', 'default')
        calculation_type = data.get('calculation_type', 'risk')  # 'risk', 'fixed', 'quantity'
        entry_price = float(data.get('entry_price', 0))
        stop_price = float(data.get('stop_price', 0))
        position_value = float(data.get('position_value', 10000))
        quantity = int(data.get('quantity', 1))
        
        pm = get_position_manager(account_id)
        
        if calculation_type == 'risk':
            size = pm.calculate_position_size_risk(entry_price, stop_price)
        elif calculation_type == 'fixed':
            size = pm.calculate_position_size_fixed(entry_price, position_value)
        else:
            size = pm.calculate_position_size_quantity(quantity)
        
        return jsonify({
            'success': True,
            'account_id': account_id,
            'calculation_type': calculation_type,
            'entry_price': entry_price,
            'stop_price': stop_price,
            'position_value': position_value,
            'quantity': quantity,
            'position_size': size,
            'estimated_value': size * entry_price,
            'timestamp': datetime.now().isoformat()
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400


@risk_bp.route('/api/risk/position/open', methods=['POST'])
def open_position():
    """开仓"""
    try:
        data = request.get_json()
        
        account_id = data.get('account_id', 'default')
        symbol = data.get('symbol', 'TA')
        direction = data.get('direction', 'long')
        quantity = int(data.get('quantity', 1))
        entry_price = float(data.get('entry_price', 0))
        stop_loss_price = data.get('stop_loss_price')
        take_profit_price = data.get('take_profit_price')
        
        if stop_loss_price is not None:
            stop_loss_price = float(stop_loss_price)
        if take_profit_price is not None:
            take_profit_price = float(take_profit_price)
        
        pm = get_position_manager(account_id)
        pm.open_position(symbol, direction, quantity, entry_price,
                        stop_loss_price, take_profit_price)
        
        return jsonify({
            'success': True,
            'account_id': account_id,
            'symbol': symbol,
            'direction': direction,
            'quantity': quantity,
            'entry_price': entry_price,
            'stop_loss_price': stop_loss_price,
            'take_profit_price': take_profit_price,
            'timestamp': datetime.now().isoformat()
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400


@risk_bp.route('/api/risk/position/close', methods=['POST'])
def close_position():
    """平仓"""
    try:
        data = request.get_json()
        
        account_id = data.get('account_id', 'default')
        symbol = data.get('symbol', 'TA')
        exit_price = float(data.get('exit_price', 0))
        
        pm = get_position_manager(account_id)
        pnl, pnl_pct = pm.close_position(symbol, exit_price)
        
        # 添加交易记录
        mm = get_money_manager(account_id)
        trade_record = TradeRecord(
            trade_id=str(uuid.uuid4()),
            symbol=symbol,
            direction='long',
            entry_price=0,
            exit_price=exit_price,
            quantity=0,
            pnl=pnl,
            pnl_pct=pnl_pct,
            timestamp=datetime.now().isoformat()
        )
        mm.add_trade(trade_record)
        
        return jsonify({
            'success': True,
            'account_id': account_id,
            'symbol': symbol,
            'exit_price': exit_price,
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'timestamp': datetime.now().isoformat()
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400


# ==================== 风控规则配置 ====================

_risk_rules = {
    'max_drawdown': 0.10,      # 最大回撤限制（%）
    'max_daily_trades': 10,    # 每日最大交易次数
    'max_daily_loss': 0.03,    # 每日最大亏损（%）
    'max_position_hands': 5,    # 单合约最大手数
    'max_position_value': 0.3, # 最大持仓市值（占账户比例）
}

# 告警历史（内存存储，生产环境建议用Redis）
_alert_history = []

# 每日统计（按自然日重置）
_daily_stats = {}


def _check_risk_alerts(account_id: str, balance: float, today_pnl: float,
                       today_trades: int, positions: list, rules: dict) -> list:
    """检查风控规则，生成告警"""
    alerts = []
    initial = 1_000_000.0
    today_loss_pct = abs(today_pnl) / initial if today_pnl < 0 else 0

    # 权益告警
    if balance < initial * 0.9:
        alerts.append({'level': 'danger', 'msg': f'⚠️ 账户权益 ({balance:,.0f}) 低于初始90%，请注意风险'})

    # 每日亏损告警
    if today_loss_pct > rules['max_daily_loss']:
        alerts.append({'level': 'danger', 'msg': f'🚨 今日亏损 ({today_loss_pct*100:.1f}%) 超过上限 ({rules["max_daily_loss"]*100:.1f}%)'})

    # 每日交易次数告警
    if today_trades >= rules['max_daily_trades']:
        alerts.append({'level': 'warning', 'msg': f'⚠️ 今日交易次数 ({today_trades}) 已达上限 ({rules["max_daily_trades"]})'})

    # 持仓过重告警
    if positions:
        total_value = sum(p.get('quantity', 0) * p.get('current_price', 0) for p in positions)
        if total_value / balance > rules['max_position_value']:
            alerts.append({'level': 'warning', 'msg': f'⚠️ 持仓市值占比 ({total_value/balance*100:.0f}%) 超过上限 ({rules["max_position_value"]*100:.0f}%)'})

    # 超过最大回撤
    if (initial - balance) / initial > rules['max_drawdown']:
        alerts.append({'level': 'danger', 'msg': f'🚨 已超过最大回撤限制 ({rules["max_drawdown"]*100:.0f}%)，禁止开仓'})

    # 保存告警
    for a in alerts:
        _alert_history.append({**a, 'time': datetime.now().isoformat()})

    return alerts[-10:]  # 保留最近10条


def _get_daily_key() -> str:
    return datetime.now().strftime('%Y-%m-%d')


@risk_bp.route('/api/risk/rules', methods=['GET', 'POST'])
def api_risk_rules():
    """获取或更新风控规则"""
    global _risk_rules
    if request.method == 'POST':
        data = request.get_json() or {}
        _risk_rules.update({k: float(v) for k, v in data.items()})
        return jsonify({'success': True, 'rules': _risk_rules})
    return jsonify({'success': True, 'rules': _risk_rules})


@risk_bp.route('/api/risk/account/status', methods=['GET'])
def get_account_status():
    """获取账户状态（含每日统计+告警）"""
    try:
        account_id = request.args.get('account_id', 'default')

        pm = get_position_manager(account_id)
        mm = get_money_manager(account_id)

        positions = []
        for symbol, pos in pm.positions.items():
            positions.append({
                'symbol': symbol,
                'direction': pos.direction,
                'quantity': pos.quantity,
                'entry_price': pos.entry_price,
                'current_price': pos.current_price,
                'stop_loss_price': pos.stop_loss_price,
                'take_profit_price': pos.take_profit_price,
                'pnl': pos.pnl,
                'pnl_pct': pos.pnl_pct
            })

        statistics = mm.get_trade_statistics()

        # 每日统计
        today_key = _get_daily_key()
        today_stats = _daily_stats.get(today_key, {'pnl': 0.0, 'trades': 0, 'wins': 0, 'losses': 0})
        today_records = [r for r in mm.trade_records if r.timestamp.startswith(today_key)]

        # 夏普比率（简化版：用总交易估算）
        returns = [r.pnl_pct / 100 for r in mm.trade_records if hasattr(r, 'pnl_pct')]
        if len(returns) >= 2:
            mean_ret = sum(returns) / len(returns)
            std_ret = (sum((r - mean_ret) ** 2 for r in returns) / len(returns)) ** 0.5
            sharpe = round(mean_ret / std_ret * (252 ** 0.5), 2) if std_ret > 0 else 0.0
        else:
            sharpe = 0.0

        # 风险度：持仓占用 / 账户权益
        risk_degree = round(pm.total_position_value / mm.current_balance, 4) if mm.current_balance > 0 else 0

        # 生成告警
        alerts = _check_risk_alerts(account_id, mm.current_balance,
                                    today_stats['pnl'], today_stats['trades'],
                                    positions, _risk_rules)

        return jsonify({
            'success': True,
            'account_id': account_id,
            'balance': mm.current_balance,
            'highest_balance': mm.highest_balance,
            'current_drawdown': mm.current_drawdown,
            'max_drawdown': mm.max_drawdown,
            'max_drawdown_exceeded': mm.max_drawdown_exceeded,
            'risk_degree': risk_degree,
            'positions': positions,
            'position_count': pm.position_count,
            'total_pnl': pm.total_pnl,
            'total_position_value': pm.total_position_value,
            'trade_statistics': statistics,
            'today': {
                'pnl': today_stats['pnl'],
                'trades': today_stats['trades'],
                'wins': today_stats['wins'],
                'losses': today_stats['losses'],
            },
            'sharpe_ratio': sharpe,
            'alerts': alerts,
            'rules': _risk_rules,
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400


@risk_bp.route('/api/risk/daily-stats', methods=['GET'])
def api_risk_daily_stats():
    """获取每日统计"""
    today_key = _get_daily_key()
    stats = _daily_stats.get(today_key, {'pnl': 0.0, 'trades': 0, 'wins': 0, 'losses': 0})
    return jsonify({'success': True, 'date': today_key, **stats})


def register_risk_routes(app):
    """注册风险控制路由到Flask应用"""
    app.register_blueprint(risk_bp)

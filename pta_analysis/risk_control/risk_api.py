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


@risk_bp.route('/api/risk/account/status', methods=['GET'])
def get_account_status():
    """获取账户状态"""
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
        
        return jsonify({
            'success': True,
            'account_id': account_id,
            'balance': mm.current_balance,
            'highest_balance': mm.highest_balance,
            'current_drawdown': mm.current_drawdown,
            'max_drawdown': mm.max_drawdown,
            'max_drawdown_exceeded': mm.max_drawdown_exceeded,
            'positions': positions,
            'position_count': pm.position_count,
            'total_pnl': pm.total_pnl,
            'total_position_value': pm.total_position_value,
            'trade_statistics': statistics,
            'timestamp': datetime.now().isoformat()
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400


def register_risk_routes(app):
    """注册风险控制路由到Flask应用"""
    app.register_blueprint(risk_bp)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
期货交易辅助系统 API 服务
提供 RESTful API 接口供前端调用
"""

import json
from flask import Flask, request, jsonify
from flask_cors import CORS
import sys
import os

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from risk_control import PositionManager, MoneyManager
from backtest import BacktestEngine
from strategies import MACDStrategy, MovingAverageStrategy, KDJStrategy, BreakoutStrategy, RSIStrategy, BollingerStrategy, ATRStrategy
from data import DataCollector, DataProcessor, DataStore
from data.data_collector import SimulatedDataSource
from execution import OrderManager, TradeExecutor, PositionTracker
from execution.trade_executor import MockBroker
from execution.position_tracker import PositionDirection

app = Flask(__name__)
CORS(app)

# 全局交易系统实例
class TradingSystem:
    """交易系统主类"""
    
    def __init__(self):
        self.data_collector = DataCollector()
        self.data_processor = DataProcessor()
        self.data_store = DataStore()
        self.money_manager = MoneyManager(initial_balance=1000000.0, max_drawdown=0.1)
        self.position_manager = PositionManager(account_balance=1000000.0)
        self.order_manager = OrderManager()
        self.position_tracker = PositionTracker()
        self.backtest_engine = BacktestEngine(
            initial_balance=1000000.0,
            risk_per_trade=0.01,
            commission_rate=0.0001
        )
        self.trade_executor = TradeExecutor(self.order_manager)
        self.mock_broker = MockBroker()
        self.trade_executor.connect_broker(self.mock_broker)
        self.data_collector.add_source(SimulatedDataSource())
        
        # 风险限制配置
        self.risk_limits = {
            'max_drawdown': 0.1,
            'risk_per_trade': 0.01,
            'max_position_size': 0.1,
            'stop_loss_pct': 0.02,
            'take_profit_pct': 0.04
        }
    
    def load_data(self, symbol, frequency='1min'):
        """加载数据"""
        data = self.data_store.get_klines(symbol, frequency=frequency)
        return data

trading_system = TradingSystem()

# ========== 数据相关接口 ==========

@app.route('/api/data/klines', methods=['GET'])
def get_klines():
    """获取K线数据"""
    symbol = request.args.get('symbol', 'TEST')
    frequency = request.args.get('frequency', '1min')
    
    try:
        # 使用数据收集器获取数据
        data = trading_system.data_collector.collect(symbol, frequency)
        if not data:
            # 生成模拟数据
            data = generate_mock_klines(100)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/data/collect', methods=['POST'])
def collect_data():
    """采集数据"""
    symbol = request.json.get('symbol', 'TEST')
    
    try:
        data = trading_system.data_collector.collect(symbol)
        if data:
            processed = trading_system.data_processor.process(data)
            trading_system.data_store.store(processed)
            return jsonify({'status': 'success', 'count': len(data)})
        return jsonify({'status': 'success', 'count': 0})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ========== 信号相关接口 ==========

@app.route('/api/signals', methods=['GET'])
def get_signals():
    """获取交易信号"""
    symbol = request.args.get('symbol', 'TEST')
    
    try:
        # 获取最新数据
        data = trading_system.data_collector.collect(symbol)
        if not data:
            data = generate_mock_klines(50)
        
        # 使用多个策略生成信号
        signals = []
        strategies = {
            'MACD': MACDStrategy(),
            'MA': MovingAverageStrategy(),
            'KDJ': KDJStrategy(),
            'RSI': RSIStrategy(),
            'Bollinger': BollingerStrategy(),
            'ATR': ATRStrategy()
        }
        
        for name, strategy in strategies.items():
            signal = None
            for bar in data[-20:]:  # 检查最近20根K线
                signal = strategy.on_bar(bar)
                if signal:
                    break
            
            if signal:
                signals.append({
                    'id': f"{name.lower()}-{len(signals)}",
                    'symbol': symbol,
                    'signal_type': signal.signal_type,
                    'strategy': name,
                    'price': signal.price,
                    'timestamp': signal.timestamp or data[-1].get('timestamp', ''),
                    'stop_loss': signal.stop_loss,
                    'take_profit': signal.take_profit,
                    'confidence': round(0.6 + (strategy.__class__.__name__.count('Strategy') * 0.05), 2),
                    'indicator_value': round(10 + len(signals) * 15, 1)
                })
        
        return jsonify(signals)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/signals/history', methods=['GET'])
def get_signal_history():
    """获取信号历史"""
    symbol = request.args.get('symbol', 'TEST')
    strategy = request.args.get('strategy', 'all')
    
    # 返回模拟历史数据
    history = []
    for i in range(10):
        history.append({
            'id': f'history-{i}',
            'symbol': symbol,
            'signal_type': 'buy' if i % 2 == 0 else 'sell',
            'strategy': strategy if strategy != 'all' else ['MACD', 'MA', 'KDJ'][i % 3],
            'price': 5000 + i * 10 + (1 if i % 2 == 0 else -1) * 5,
            'timestamp': f'2024-01-{10 + i} 09:{30 + i * 5}:00',
            'stop_loss': None,
            'take_profit': None,
            'confidence': round(0.65 + i * 0.03, 2)
        })
    
    return jsonify(history)

# ========== 回测相关接口 ==========

@app.route('/api/backtest/run', methods=['POST'])
def run_backtest():
    """运行回测"""
    strategy_name = request.json.get('strategy', 'macd')
    symbol = request.json.get('symbol', 'TEST')
    params = request.json.get('params', {})
    
    try:
        # 获取数据
        data = trading_system.data_collector.collect(symbol)
        if not data:
            data = generate_mock_klines(200)
        
        # 创建策略
        strategies = {
            'macd': MACDStrategy(),
            'ma': MovingAverageStrategy(),
            'kdj': KDJStrategy(),
            'rsi': RSIStrategy(),
            'bollinger': BollingerStrategy(),
            'atr': ATRStrategy()
        }
        
        strategy = strategies.get(strategy_name.lower())
        if not strategy:
            return jsonify({'error': '未知策略'}), 400
        
        # 应用参数
        if params:
            for key, value in params.items():
                if hasattr(strategy, key):
                    setattr(strategy, key, value)
        
        # 运行回测
        result = trading_system.backtest_engine.run(strategy, data)
        
        # 生成权益曲线
        equity_curve = []
        if 'trade_history' in result:
            equity = 1000000.0
            equity_curve.append(equity)
            for trade in result['trade_history']:
                pnl = trade.get('pnl', 0)
                equity += pnl
                equity_curve.append(equity)
        
        result['equity_curve'] = equity_curve
        result['strategy'] = strategy_name
        
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/backtest/results', methods=['GET'])
def get_backtest_results():
    """获取回测结果"""
    return jsonify([])

@app.route('/api/backtest/compare', methods=['POST'])
def compare_strategies():
    """比较策略"""
    strategies = request.json.get('strategies', [])
    symbol = request.json.get('symbol', 'TEST')
    
    results = []
    for strategy_name in strategies:
        result = {
            'strategy': strategy_name,
            'total_trades': 100 + len(results) * 20,
            'win_rate': 0.55 + len(results) * 0.02,
            'total_pnl': 30000 + len(results) * 10000,
            'max_drawdown': 0.08 - len(results) * 0.01,
            'sharpe_ratio': 1.5 + len(results) * 0.15,
            'profit_factor': 1.4 + len(results) * 0.1
        }
        results.append(result)
    
    return jsonify(results)

# ========== 风险控制相关接口 ==========

@app.route('/api/risk/limits', methods=['GET'])
def get_risk_limits():
    """获取风险限制"""
    return jsonify(trading_system.risk_limits)

@app.route('/api/risk/limits', methods=['PUT'])
def update_risk_limits():
    """更新风险限制"""
    limits = request.json
    
    # 验证并更新
    valid_keys = ['max_drawdown', 'risk_per_trade', 'max_position_size', 'stop_loss_pct', 'take_profit_pct']
    for key in valid_keys:
        if key in limits:
            trading_system.risk_limits[key] = limits[key]
    
    return jsonify(trading_system.risk_limits)

@app.route('/api/risk/positions', methods=['GET'])
def get_position_status():
    """获取持仓状态"""
    positions = trading_system.position_tracker.get_position_summary()
    return jsonify(positions)

# ========== 账户相关接口 ==========

@app.route('/api/account/info', methods=['GET'])
def get_account_info():
    """获取账户信息"""
    info = {
        'balance': trading_system.money_manager.current_balance,
        'equity': trading_system.money_manager.current_balance + 5230,  # 模拟权益
        'margin': 25000,  # 模拟保证金
        'available': trading_system.money_manager.current_balance - 25000,
        'frozen': 0,
        'unrealized_pnl': 5230,  # 模拟未实现盈亏
        'realized_pnl': 12580  # 模拟已实现盈亏
    }
    return jsonify(info)

@app.route('/api/account/trades', methods=['GET'])
def get_trade_history():
    """获取交易历史"""
    history = [
        {
            'id': '1',
            'symbol': 'TEST',
            'direction': 'long',
            'entry_price': 4980,
            'exit_price': 5020,
            'pnl': 40,
            'pnl_pct': 0.008,
            'entry_time': '2024-01-15 09:30:00',
            'exit_time': '2024-01-15 10:15:00',
            'status': 'closed'
        },
        {
            'id': '2',
            'symbol': 'TEST',
            'direction': 'short',
            'entry_price': 5050,
            'exit_price': 5010,
            'pnl': 40,
            'pnl_pct': 0.0079,
            'entry_time': '2024-01-14 14:20:00',
            'exit_time': '2024-01-14 15:00:00',
            'status': 'closed'
        },
        {
            'id': '3',
            'symbol': 'RB2401',
            'direction': 'long',
            'entry_price': 3820,
            'exit_price': 3865,
            'pnl': 45,
            'pnl_pct': 0.0118,
            'entry_time': '2024-01-14 10:00:00',
            'exit_time': '2024-01-14 11:30:00',
            'status': 'closed'
        },
        {
            'id': '4',
            'symbol': 'HC2401',
            'direction': 'short',
            'entry_price': 4250,
            'exit_price': 4280,
            'pnl': -30,
            'pnl_pct': -0.0071,
            'entry_time': '2024-01-13 14:00:00',
            'exit_time': '2024-01-13 14:45:00',
            'status': 'closed'
        },
        {
            'id': '5',
            'symbol': 'TEST',
            'direction': 'long',
            'entry_price': 5020,
            'exit_price': 0,
            'pnl': 0,
            'pnl_pct': 0,
            'entry_time': '2024-01-15 10:30:00',
            'exit_time': '',
            'status': 'open'
        }
    ]
    return jsonify(history)

@app.route('/api/account/balance', methods=['GET'])
def get_balance_history():
    """获取余额历史"""
    history = [
        {'date': '2024-01-09', 'balance': 1000000},
        {'date': '2024-01-10', 'balance': 1002500},
        {'date': '2024-01-11', 'balance': 998000},
        {'date': '2024-01-12', 'balance': 1005000},
        {'date': '2024-01-13', 'balance': 1001500},
        {'date': '2024-01-14', 'balance': 1008000},
        {'date': '2024-01-15', 'balance': 1003500},
        {'date': '2024-01-16', 'balance': 1005230}
    ]
    return jsonify(history)

# ========== 辅助函数 ==========

def generate_mock_klines(count: int) -> list:
    """生成模拟K线数据"""
    data = []
    base_price = 5000
    from datetime import datetime, timedelta
    
    now = datetime.now()
    for i in range(count):
        timestamp = (now - timedelta(minutes=count - i)).strftime('%Y-%m-%d %H:%M:%S')
        change = (hash(str(i)) % 100 - 50) * 0.8
        open_price = base_price
        close_price = base_price + change
        high_price = max(open_price, close_price) + abs(change) * 0.3
        low_price = min(open_price, close_price) - abs(change) * 0.3
        volume = (hash(str(i * 7)) % 1000) + 100
        
        data.append({
            'timestamp': timestamp,
            'open': round(open_price, 2),
            'high': round(high_price, 2),
            'low': round(low_price, 2),
            'close': round(close_price, 2),
            'volume': volume
        })
        
        base_price = close_price
    
    return data

@app.route('/')
def index():
    """返回前端主页面"""
    frontend_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend')
    index_path = os.path.join(frontend_path, 'index.html')
    
    if os.path.exists(index_path):
        with open(index_path, 'r', encoding='utf-8') as f:
            return f.read()
    else:
        return "<h1>Futures Trading System</h1><p>Frontend not found</p>", 500

@app.route('/<path:path>')
def static_files(path):
    """提供前端静态文件"""
    frontend_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend')
    file_path = os.path.join(frontend_path, path)
    
    if os.path.exists(file_path) and os.path.isfile(file_path):
        # 根据文件扩展名设置正确的Content-Type
        if path.endswith('.js'):
            return open(file_path, 'r', encoding='utf-8').read(), 200, {'Content-Type': 'application/javascript'}
        elif path.endswith('.css'):
            return open(file_path, 'r', encoding='utf-8').read(), 200, {'Content-Type': 'text/css'}
        elif path.endswith('.svg'):
            return open(file_path, 'rb').read(), 200, {'Content-Type': 'image/svg+xml'}
        elif path.endswith('.ico'):
            return open(file_path, 'rb').read(), 200, {'Content-Type': 'image/x-icon'}
        else:
            return open(file_path, 'rb').read(), 200
    else:
        return "File not found", 404

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5001, help='Port to run the server on')
    args = parser.parse_args()
    app.run(host='0.0.0.0', port=args.port, debug=True)

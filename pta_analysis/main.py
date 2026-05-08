#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
期货交易辅助系统主入口
整合所有模块，提供统一的交易分析框架
"""

import argparse
import sys
import os

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from risk_control import PositionManager, MoneyManager
from backtest import BacktestEngine
from strategies import MACDStrategy, MovingAverageStrategy, KDJStrategy, BreakoutStrategy, RSIStrategy, BollingerStrategy
from data import DataCollector, DataProcessor, DataStore
from data.data_collector import SimulatedDataSource
from execution import OrderManager, TradeExecutor, PositionTracker
from execution.trade_executor import MockBroker
from execution.position_tracker import PositionDirection
from analysis import TechnicalIndicators, PatternRecognition, ChanAnalysis


class TradingSystem:
    """交易系统主类"""
    
    def __init__(self):
        # 初始化各个模块
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
        
        # 连接模拟交易接口
        self.trade_executor = TradeExecutor(self.order_manager)
        self.mock_broker = MockBroker()
        self.trade_executor.connect_broker(self.mock_broker)
        
        # 添加模拟数据源
        self.data_collector.add_source(SimulatedDataSource())
    
    def collect_data(self, symbol: str, start_time=None, end_time=None, frequency='1min'):
        """采集数据"""
        print(f"正在采集 {symbol} 的数据...")
        data = self.data_collector.collect(symbol, start_time, end_time, frequency)
        print(f"采集到 {len(data)} 条数据")
        return data
    
    def process_data(self, data):
        """处理数据"""
        print("正在处理数据...")
        # 清洗数据
        cleaned = self.data_processor.clean_data(data)
        # 计算指标
        processed = self.data_processor.calculate_indicators(cleaned, ['ma', 'macd', 'kdj'])
        return processed
    
    def store_data(self, data):
        """存储数据"""
        print("正在存储数据...")
        self.data_store.save_klines(data)
        print(f"已存储 {len(data)} 条数据")
    
    def load_data(self, symbol, frequency='1min'):
        """加载数据"""
        print(f"正在加载 {symbol} 的数据...")
        data = self.data_store.get_klines(symbol, frequency=frequency)
        print(f"加载到 {len(data)} 条数据")
        return data
    
    def run_backtest(self, strategy_name, data):
        """运行回测"""
        print(f"正在运行 {strategy_name} 回测...")
        
        # 创建策略
        strategies = {
            'macd': MACDStrategy(),
            'ma': MovingAverageStrategy(),
            'kdj': KDJStrategy(),
            'breakout': BreakoutStrategy(),
            'rsi': RSIStrategy(),
            'bollinger': BollingerStrategy()
        }
        
        strategy = strategies.get(strategy_name.lower())
        if not strategy:
            print(f"未知策略: {strategy_name}")
            return None
        
        # 运行回测
        result = self.backtest_engine.run(strategy, data)
        
        # 打印统计结果
        print("\n回测结果:")
        print(f"总交易次数: {result.get('total_trades', 0)}")
        print(f"胜率: {result.get('win_rate', 0):.2%}")
        print(f"总盈亏: {result.get('total_pnl', 0):.2f}")
        print(f"最大回撤: {result.get('max_drawdown', 0):.2%}")
        print(f"夏普比率: {result.get('sharpe_ratio', 0):.2f}")
        print(f"盈利因子: {result.get('profit_factor', 0):.2f}")
        
        return result
    
    def analyze_patterns(self, data):
        """分析模式"""
        print("正在分析K线模式...")
        result = PatternRecognition.recognize_patterns(data)
        
        # 统计模式
        pattern_count = {}
        for bar in result:
            if 'patterns' in bar and bar['patterns']:
                for pattern in bar['patterns']:
                    pattern_count[pattern] = pattern_count.get(pattern, 0) + 1
        
        print("\n模式统计:")
        for pattern, count in pattern_count.items():
            print(f"  {pattern}: {count}次")
        
        return result
    
    def analyze_chan(self, data):
        """缠论分析"""
        print("正在进行缠论分析...")
        result = ChanAnalysis.analyze(data)
        
        # 统计分型和笔
        fractal_count = {'top': 0, 'bottom': 0}
        bi_count = {'up': 0, 'down': 0}
        
        for bar in result:
            if 'fractal' in bar and bar['fractal']:
                if bar['fractal'] in fractal_count:
                    fractal_count[bar['fractal']] += 1
            if 'bi' in bar and bar['bi']:
                if bar['bi'] in bi_count:
                    bi_count[bar['bi']] += 1
        
        print("\n缠论分析结果:")
        print(f"顶分型: {fractal_count['top']}个")
        print(f"底分型: {fractal_count['bottom']}个")
        print(f"向上笔: {bi_count['up']}个")
        print(f"向下笔: {bi_count['down']}个")
        
        return result
    
    def execute_signal(self, signal):
        """执行交易信号"""
        print(f"执行交易信号: {signal}")
        order = self.trade_executor.execute_signal(signal)
        
        if order:
            print(f"订单已创建: {order.order_id}, 状态: {order.status.value}")
            # 更新仓位追踪
            direction = PositionDirection.LONG if signal.get('signal_type') == 'buy' else PositionDirection.SHORT
            self.position_tracker.update_position(
                symbol=signal['symbol'],
                direction=direction,
                quantity=1,
                price=signal.get('price', 0)
            )
        
        return order
    
    def get_account_status(self):
        """获取账户状态"""
        status = {
            'balance': self.money_manager.current_balance,
            'max_drawdown': self.money_manager.max_drawdown,
            'current_drawdown': self.money_manager.current_drawdown,
            'trades': self.money_manager.get_trade_statistics(),
            'positions': self.position_tracker.get_position_summary()
        }
        
        return status
    
    def print_account_status(self):
        """打印账户状态"""
        status = self.get_account_status()
        
        print("\n账户状态:")
        print(f"账户余额: {status['balance']:.2f}")
        print(f"最大回撤: {status['max_drawdown']:.2%}")
        print(f"当前回撤: {status['current_drawdown']:.2%}")
        print("\n交易统计:")
        trades = status['trades']
        print(f"  总交易: {trades.get('total_trades', 0)}")
        print(f"  盈利交易: {trades.get('winning_trades', 0)}")
        print(f"  亏损交易: {trades.get('losing_trades', 0)}")
        print("\n持仓汇总:")
        positions = status['positions']
        print(f"  持仓数量: {positions.get('total_positions', 0)}")
        print(f"  多头数量: {positions.get('long_count', 0)}")
        print(f"  空头数量: {positions.get('short_count', 0)}")
        print(f"  未实现盈亏: {positions.get('total_unrealized_pnl', 0):.2f}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='期货交易辅助系统')
    parser.add_argument('--collect', action='store_true', help='采集数据')
    parser.add_argument('--backtest', type=str, help='运行回测策略 (macd/ma/kdj/breakout)')
    parser.add_argument('--analyze', action='store_true', help='分析数据')
    parser.add_argument('--status', action='store_true', help='查看账户状态')
    parser.add_argument('--symbol', type=str, default='TEST', help='合约代码')
    
    args = parser.parse_args()
    
    # 创建交易系统
    system = TradingSystem()
    
    if args.collect:
        # 采集、处理、存储数据
        data = system.collect_data(args.symbol)
        if data:
            processed = system.process_data(data)
            system.store_data(processed)
    
    if args.backtest:
        # 加载数据并运行回测
        data = system.load_data(args.symbol)
        if data:
            system.run_backtest(args.backtest, data)
    
    if args.analyze:
        # 加载数据并分析
        data = system.load_data(args.symbol)
        if data:
            system.analyze_patterns(data)
            system.analyze_chan(data)
    
    if args.status:
        # 查看账户状态
        system.print_account_status()
    
    # 如果没有指定参数，显示帮助
    if not any([args.collect, args.backtest, args.analyze, args.status]):
        parser.print_help()


if __name__ == '__main__':
    main()

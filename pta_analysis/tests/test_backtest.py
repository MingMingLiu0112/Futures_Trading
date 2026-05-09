#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测框架单元测试
"""

import pytest
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.backtest_engine import BacktestEngine, TradeResult
from backtest.strategy_base import StrategyBase, StrategySignal


class DummyStrategy(StrategyBase):
    """测试策略实现"""
    
    def on_bar(self, bar):
        if bar['close'] > bar['open']:
            return self.generate_signal('buy', bar['close'], bar.get('time', ''))
        return None


class TestStrategyBase:
    """策略基类测试"""
    
    def test_strategy_init(self):
        """测试策略初始化"""
        params = {'param1': 1, 'param2': 2}
        strategy = DummyStrategy(params)
        assert strategy.params == params
        assert strategy.signals == []
        assert strategy.position is None
    
    def test_strategy_generate_signal(self):
        """测试生成信号"""
        strategy = DummyStrategy()
        signal = strategy.generate_signal('buy', 5000, '2024-01-01 10:00:00')
        
        assert len(strategy.signals) == 1
        assert signal.signal_type == 'buy'
        assert signal.price == 5000
        assert signal.timestamp == '2024-01-01 10:00:00'
    
    def test_strategy_reset(self):
        """测试策略重置"""
        strategy = DummyStrategy()
        strategy.position = 'long'
        strategy.entry_price = 5000
        strategy.generate_signal('buy', 5000, '2024-01-01')
        
        strategy.reset()
        
        assert strategy.position is None
        assert strategy.entry_price is None
        assert strategy.signals == []


class TestTradeResult:
    """交易结果测试"""
    
    def test_trade_result_init(self):
        """测试交易结果初始化"""
        trade = TradeResult(
            trade_id='t1',
            entry_time='2024-01-01 10:00:00',
            exit_time='2024-01-01 11:00:00',
            direction='long',
            entry_price=5000,
            exit_price=5100,
            quantity=10
        )
        
        assert trade.trade_id == 't1'
        assert trade.direction == 'long'
        assert trade.entry_price == 5000
        assert trade.exit_price == 5100
    
    def test_trade_result_pnl_long(self):
        """测试多头交易盈亏"""
        trade = TradeResult(
            trade_id='t1',
            entry_time='2024-01-01',
            exit_time='2024-01-02',
            direction='long',
            entry_price=5000,
            exit_price=5100,
            quantity=10
        )
        
        assert trade.pnl == 1000  # (5100 - 5000) * 10
        assert trade.pnl_pct == 2.0  # 2%
    
    def test_trade_result_pnl_short(self):
        """测试空头交易盈亏"""
        trade = TradeResult(
            trade_id='t1',
            entry_time='2024-01-01',
            exit_time='2024-01-02',
            direction='short',
            entry_price=5000,
            exit_price=4900,
            quantity=10
        )
        
        assert trade.pnl == 1000  # (5000 - 4900) * 10
        assert trade.pnl_pct == 2.0  # 2%
    
    def test_trade_result_loss(self):
        """测试亏损交易"""
        trade = TradeResult(
            trade_id='t1',
            entry_time='2024-01-01',
            exit_time='2024-01-02',
            direction='long',
            entry_price=5000,
            exit_price=4900,
            quantity=10
        )
        
        assert trade.pnl == -1000
        assert trade.pnl_pct == -2.0


class TestBacktestEngine:
    """回测引擎测试"""
    
    def test_backtest_engine_init(self):
        """测试回测引擎初始化"""
        engine = BacktestEngine(initial_balance=100000, risk_per_trade=0.01)
        
        assert engine.initial_balance == 100000
        assert engine.risk_per_trade == 0.01
        assert engine.balance == 100000
        assert engine.trades == []
    
    def test_calculate_position_size(self):
        """测试仓位大小计算"""
        engine = BacktestEngine(initial_balance=100000, risk_per_trade=0.01)
        
        # 风险金额: 100000 * 0.01 = 1000
        # 每单位风险: 5000 - 4900 = 100
        # 仓位大小: 1000 / 100 = 10
        size = engine._calculate_position_size(5000, 4900)
        assert size == 10
    
    def test_calculate_position_size_zero_diff(self):
        """测试仓位大小计算（入场价等于止损价）"""
        engine = BacktestEngine()
        size = engine._calculate_position_size(5000, 5000)
        assert size == 1
    
    def test_run_with_simple_strategy(self):
        """测试运行简单策略"""
        # 创建简单策略
        class SimpleStrategy(StrategyBase):
            def __init__(self):
                super().__init__()
                self.counter = 0
            
            def on_bar(self, bar):
                self.counter += 1
                if self.counter == 2:
                    # 第二根K线开多
                    return self.generate_signal('buy', bar['close'], bar.get('time', ''))
                elif self.counter == 5:
                    # 第五根K线平仓
                    return self.generate_signal('close', bar['close'], bar.get('time', ''))
                return None
        
        # 创建测试数据
        data = [
            {'time': '2024-01-01 09:01', 'open': 5000, 'high': 5010, 'low': 4990, 'close': 5005},
            {'time': '2024-01-01 09:02', 'open': 5005, 'high': 5020, 'low': 5000, 'close': 5015},
            {'time': '2024-01-01 09:03', 'open': 5015, 'high': 5030, 'low': 5010, 'close': 5025},
            {'time': '2024-01-01 09:04', 'open': 5025, 'high': 5040, 'low': 5020, 'close': 5035},
            {'time': '2024-01-01 09:05', 'open': 5035, 'high': 5050, 'low': 5030, 'close': 5045},
        ]
        
        # 运行回测
        strategy = SimpleStrategy()
        engine = BacktestEngine(initial_balance=100000, commission_rate=0)
        result = engine.run(strategy, data)
        
        assert result['success'] == True
        assert len(result['trades']) == 1
        assert result['trades'][0]['direction'] == 'long'
        assert result['trades'][0]['entry_price'] == 5015
        assert result['trades'][0]['exit_price'] == 5045
        assert result['trades'][0]['pnl'] == 30  # (5045 - 5015) * 1
    
    def test_run_stop_loss(self):
        """测试止损功能"""
        class StopLossStrategy(StrategyBase):
            def __init__(self):
                super().__init__()
                self.counter = 0
            
            def on_bar(self, bar):
                self.counter += 1
                if self.counter == 1:
                    return self.generate_signal('buy', bar['close'], bar.get('time', ''),
                                              stop_loss=bar['close'] * 0.98)
                return None
        
        # 创建测试数据（价格下跌触发止损）
        data = [
            {'time': '2024-01-01 09:01', 'open': 5000, 'high': 5010, 'low': 4990, 'close': 5000},
            {'time': '2024-01-01 09:02', 'open': 5000, 'high': 5005, 'low': 4980, 'close': 4990},
            {'time': '2024-01-01 09:03', 'open': 4990, 'high': 4995, 'low': 4900, 'close': 4900},  # 触发止损
        ]
        
        strategy = StopLossStrategy()
        engine = BacktestEngine(initial_balance=100000, commission_rate=0)
        result = engine.run(strategy, data)
        
        assert result['success'] == True
        assert len(result['trades']) == 1
        assert result['trades'][0]['direction'] == 'long'
        assert result['trades'][0]['exit_price'] == 4900
        assert result['trades'][0]['pnl'] == -100  # (4900 - 5000) * 1
    
    def test_run_take_profit(self):
        """测试止盈功能"""
        class TakeProfitStrategy(StrategyBase):
            def __init__(self):
                super().__init__()
                self.counter = 0
            
            def on_bar(self, bar):
                self.counter += 1
                if self.counter == 1:
                    return self.generate_signal('buy', bar['close'], bar.get('time', ''),
                                              take_profit=bar['close'] * 1.02)
                return None
        
        # 创建测试数据（价格上涨触发止盈）
        data = [
            {'time': '2024-01-01 09:01', 'open': 5000, 'high': 5010, 'low': 4990, 'close': 5000},
            {'time': '2024-01-01 09:02', 'open': 5000, 'high': 5050, 'low': 5000, 'close': 5050},
            {'time': '2024-01-01 09:03', 'open': 5050, 'high': 5100, 'low': 5040, 'close': 5100},  # 触发止盈
        ]
        
        strategy = TakeProfitStrategy()
        engine = BacktestEngine(initial_balance=100000, commission_rate=0)
        result = engine.run(strategy, data)
        
        assert result['success'] == True
        assert len(result['trades']) == 1
        assert result['trades'][0]['direction'] == 'long'
        assert result['trades'][0]['exit_price'] == 5100
        assert result['trades'][0]['pnl'] == 100  # (5100 - 5000) * 1
    
    def test_run_empty_data(self):
        """测试空数据"""
        strategy = DummyStrategy()
        engine = BacktestEngine()
        result = engine.run(strategy, [])
        
        assert result['success'] == True
        assert len(result['trades']) == 0
        assert result['final_balance'] == 100000
    
    def test_statistics_calculation(self):
        """测试统计指标计算"""
        class TestStrategy2(StrategyBase):
            def __init__(self):
                super().__init__()
                self.counter = 0
            
            def on_bar(self, bar):
                self.counter += 1
                if self.counter == 1:
                    return self.generate_signal('buy', 5000, bar.get('time', ''))
                elif self.counter == 2:
                    return self.generate_signal('close', 5100, bar.get('time', ''))
                elif self.counter == 3:
                    return self.generate_signal('buy', 5100, bar.get('time', ''))
                elif self.counter == 4:
                    return self.generate_signal('close', 5050, bar.get('time', ''))
                return None
        
        data = [
            {'time': '2024-01-01 09:01', 'close': 5000},
            {'time': '2024-01-01 09:02', 'close': 5100},
            {'time': '2024-01-01 09:03', 'close': 5100},
            {'time': '2024-01-01 09:04', 'close': 5050},
        ]
        
        strategy = TestStrategy2()
        engine = BacktestEngine(initial_balance=100000, commission_rate=0)
        result = engine.run(strategy, data)
        
        stats = result['statistics']
        assert stats['total_trades'] == 2
        assert stats['win_count'] == 1
        assert stats['loss_count'] == 1
        assert stats['win_rate'] == 50.0
        assert stats['total_pnl'] == 50  # 100 - 50


class TestPerformanceMetrics:
    """绩效指标测试"""

    def test_all_metrics_present(self):
        """测试所有绩效指标都存在"""
        from backtest.performance_metrics import calculate_performance_metrics

        trades = [
            {'trade_id': 't1', 'direction': 'long', 'entry_price': 5000, 'exit_price': 5100,
             'quantity': 1, 'pnl': 100, 'pnl_pct': 2.0, 'exit_reason': 'signal'},
            {'trade_id': 't2', 'direction': 'long', 'entry_price': 5100, 'exit_price': 5050,
             'quantity': 1, 'pnl': -50, 'pnl_pct': -1.0, 'exit_reason': 'signal'},
        ]

        equity_curve = [
            {'time': '2024-01-01', 'balance': 100000},
            {'time': '2024-01-02', 'balance': 100100},
            {'time': '2024-01-03', 'balance': 100050},
        ]

        metrics = calculate_performance_metrics(trades, equity_curve, 100000)

        # 检查所有新增指标
        assert 'sharpe_ratio' in metrics
        assert 'sortino_ratio' in metrics
        assert 'calmar_ratio' in metrics
        assert 'max_consecutive_losses' in metrics
        assert 'max_consecutive_wins' in metrics
        assert 'daily_pnl' in metrics
        assert 'annual_return' in metrics


class TestGridOptimizer:
    """参数优化测试"""

    def test_parameter_grid_generation(self):
        """测试参数网格生成"""
        from backtest.optimizer import ParameterGrid

        param_grid = {
            'fast_period': [12, 26],
            'signal_period': [9]
        }

        grid = ParameterGrid(param_grid)
        assert len(grid) == 2  # 2 * 1 = 2 组合

        params_list = list(grid)
        assert params_list[0] == {'fast_period': 12, 'signal_period': 9}
        assert params_list[1] == {'fast_period': 26, 'signal_period': 9}

    def test_grid_optimizer_integration(self):
        """测试优化器集成"""
        from backtest.optimizer import GridOptimizer, ParameterGrid, run_backtest_for_optimization
        from backtest.strategy_base import StrategyBase

        class SimpleTestStrategy(StrategyBase):
            def on_bar(self, bar):
                if bar.get('close', 5000) > bar.get('open', 4900):
                    return self.generate_signal('buy', bar['close'], bar.get('time', ''))
                elif self.position:
                    return self.generate_signal('close', bar['close'], bar.get('time', ''))
                return None

        param_grid = {
            'fast_period': [12]  # 简化测试
        }

        data = [
            {'time': '2024-01-01', 'open': 5000, 'close': 5050},
            {'time': '2024-01-02', 'open': 5050, 'close': 5100},
        ]

        grid = ParameterGrid(param_grid)
        optimizer = GridOptimizer(objective='total_return', mode='max', top_n=1)

        result = optimizer.optimize(
            backtest_func=run_backtest_for_optimization,
            param_grid=grid,
            strategy_class=SimpleTestStrategy,
            data=data,
            fixed_params={},
            initial_balance=100000.0
        )

        assert result['success'] == True
        assert len(result['top_params']) >= 1


class TestStrategyComparator:
    """策略对比测试"""

    def test_comparator_basic(self):
        """测试策略对比器基本功能"""
        from backtest.strategy_comparison import StrategyComparator
        from backtest.strategy_base import StrategyBase

        class StrategyA(StrategyBase):
            def on_bar(self, bar):
                if bar['close'] > bar['open']:
                    return self.generate_signal('buy', bar['close'], bar.get('time', ''))
                elif self.position:
                    return self.generate_signal('close', bar['close'], bar.get('time', ''))
                return None

        class StrategyB(StrategyBase):
            def on_bar(self, bar):
                if bar['close'] < bar['open']:
                    return self.generate_signal('sell', bar['close'], bar.get('time', ''))
                elif self.position:
                    return self.generate_signal('close', bar['close'], bar.get('time', ''))
                return None

        data = [
            {'time': '2024-01-01', 'open': 5000, 'close': 5050},
            {'time': '2024-01-02', 'open': 5050, 'close': 5100},
            {'time': '2024-01-03', 'open': 5100, 'close': 5050},
        ]

        comparator = StrategyComparator(initial_balance=100000.0)
        strategies = {
            'StrategyA': StrategyA(),
            'StrategyB': StrategyB()
        }

        result = comparator.run_multiple_strategies(strategies, data)

        assert result['success'] == True
        assert result['total_strategies'] == 2
        assert 'comparison' in result
        assert len(result['comparison']) == 2


class TestBacktestExporter:
    """回测导出测试"""

    def test_exporter_to_dict(self):
        """测试导出为字典"""
        from backtest.backtest_exporter import BacktestExporter

        result_data = {
            'strategy_name': 'TestStrategy',
            'initial_balance': 100000,
            'final_balance': 105000,
            'statistics': {
                'total_return': 5.0,
                'total_trades': 10,
                'win_rate': 60.0,
                'sharpe_ratio': 1.5,
                'sortino_ratio': 2.0,
                'calmar_ratio': 3.0,
                'max_drawdown': 5000,
            },
            'trades': [],
            'equity_curve': []
        }

        exporter = BacktestExporter(result_data)
        output = exporter.to_dict()

        assert 'summary' in output
        assert output['summary']['strategy_name'] == 'TestStrategy'
        assert output['summary']['final_balance'] == 105000


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

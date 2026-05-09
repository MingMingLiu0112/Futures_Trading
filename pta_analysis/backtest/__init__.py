#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测框架模块
提供策略回测、绩效分析等功能
"""

from .backtest_engine import BacktestEngine, TradeResult
from .strategy_base import StrategyBase
from .performance_metrics import calculate_performance_metrics
from .optimizer import GridOptimizer, ParameterGrid, WalkForwardOptimizer, run_backtest_for_optimization
from .strategy_comparison import StrategyComparator, StrategyMultiPeriod
from .backtest_exporter import BacktestExporter

__all__ = [
    'BacktestEngine',
    'TradeResult',
    'StrategyBase',
    'calculate_performance_metrics',
    'GridOptimizer',
    'ParameterGrid',
    'WalkForwardOptimizer',
    'run_backtest_for_optimization',
    'StrategyComparator',
    'StrategyMultiPeriod',
    'BacktestExporter',
]

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测框架模块
提供策略回测、绩效分析等功能
"""

from .backtest_engine import BacktestEngine, TradeResult
from .strategy_base import StrategyBase
from .performance_metrics import calculate_performance_metrics

__all__ = [
    'BacktestEngine',
    'TradeResult',
    'StrategyBase',
    'calculate_performance_metrics'
]

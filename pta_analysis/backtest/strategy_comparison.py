#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多策略对比模块

同时运行多个策略并对比它们的绩效表现。

用法:
```python
from backtest.strategy_comparison import StrategyComparator
from backtest.strategy_base import StrategyBase

class StrategyA(StrategyBase):
    def on_bar(self, bar):
        ...

class StrategyB(StrategyBase):
    def on_bar(self, bar):
        ...

comparator = StrategyComparator(initial_balance=100000.0)
strategies = {
    'StrategyA': StrategyA(),
    'StrategyB': StrategyB()
}
result = comparator.run_multiple_strategies(strategies, kline_data)
```
"""

from typing import Any, Dict, List, Type

from .backtest_engine import BacktestEngine
from .strategy_base import StrategyBase


class StrategyComparator:
    """
    多策略对比器

    在相同的K线数据上运行多个策略，并对比它们的绩效指标。
    """

    def __init__(self, initial_balance: float = 100000.0, commission_rate: float = 0.0001):
        """
        Args:
            initial_balance: 初始资金
            commission_rate: 手续费率
        """
        self.initial_balance = initial_balance
        self.commission_rate = commission_rate
        self.results: Dict[str, Dict[str, Any]] = {}

    def run_multiple_strategies(
        self,
        strategies: Dict[str, StrategyBase],
        data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        运行多个策略并对比

        Args:
            strategies: 策略字典，key为策略名，value为策略实例
            data: K线数据

        Returns:
            对比结果字典
        """
        self.results = {}
        engine = BacktestEngine(
            initial_balance=self.initial_balance,
            commission_rate=self.commission_rate
        )

        comparison = []
        for name, strategy in strategies.items():
            result = engine.run(strategy, data)
            stats = result.get('statistics', {})

            entry = {
                'strategy_name': name,
                'total_trades': stats.get('total_trades', 0),
                'win_rate': stats.get('win_rate', 0),
                'total_return': stats.get('total_return', 0),
                'annual_return': stats.get('annual_return', 0),
                'max_drawdown': stats.get('max_drawdown', 0),
                'sharpe_ratio': stats.get('sharpe_ratio', 0),
                'sortino_ratio': stats.get('sortino_ratio', 0),
                'calmar_ratio': stats.get('calmar_ratio', 0),
                'profit_loss_ratio': stats.get('profit_loss_ratio', 0),
                'max_consecutive_losses': stats.get('max_consecutive_losses', 0),
            }
            comparison.append(entry)
            self.results[name] = result

        # 按总收益率排序
        comparison.sort(key=lambda x: x['total_return'], reverse=True)

        # 排名
        for i, entry in enumerate(comparison):
            entry['rank'] = i + 1

        return {
            'success': True,
            'total_strategies': len(strategies),
            'comparison': comparison,
            'initial_balance': self.initial_balance,
            'data_count': len(data),
        }

    def get_best_strategy(self) -> str:
        """获取最优策略名"""
        if not self.results:
            return ''
        comparison = sorted(
            self.results.items(),
            key=lambda x: x[1].get('statistics', {}).get('total_return', 0),
            reverse=True
        )
        return comparison[0][0] if comparison else ''

    def get_comparison_table(self) -> str:
        """获取对比表格（文本格式）"""
        if not self.results:
            return '无结果'

        comparison = []
        for name, result in self.results.items():
            stats = result.get('statistics', {})
            comparison.append({
                'name': name,
                'trades': stats.get('total_trades', 0),
                'win_rate': f"{stats.get('win_rate', 0):.1f}%",
                'return': f"{stats.get('total_return', 0):.2f}%",
                'sharpe': f"{stats.get('sharpe_ratio', 0):.2f}",
                'max_dd': f"{stats.get('max_drawdown', 0):.2f}",
            })

        comparison.sort(key=lambda x: float(x['return'][:-1]), reverse=True)

        header = f"{'策略':<15} {'交易数':<8} {'胜率':<8} {'收益率':<10} {'夏普':<8} {'最大回撤':<10}"
        lines = [header, '-' * 60]
        for entry in comparison:
            lines.append(
                f"{entry['name']:<15} {entry['trades']:<8} {entry['win_rate']:<8} "
                f"{entry['return']:<10} {entry['sharpe']:<8} {entry['max_dd']:<10}"
            )
        return '\n'.join(lines)

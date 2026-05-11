#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
参数优化器扩展 - GridOptimizer 和 ParameterGrid

GridOptimizer 提供网格搜索参数优化功能，支持：
- 多参数同时优化
- 多种优化目标（总收益、夏普比率、最大回撤等）
- 热力图可视化
- 多进程并行

用法:
```python
from backtest.optimizer import GridOptimizer, ParameterGrid, run_backtest_for_optimization

grid = ParameterGrid({
    'fast_period': [12, 26],
    'signal_period': [9]
})

optimizer = GridOptimizer(objective='total_return', mode='max', top_n=5)
result = optimizer.optimize(
    backtest_func=run_backtest_for_optimization,
    param_grid=grid,
    strategy_class=MyStrategy,
    data=kline_data,
    fixed_params={},
    initial_balance=100000.0
)
```
"""

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type
import itertools
import multiprocessing
import os

from .strategy_base import StrategyBase


class ParameterGrid:
    """
    参数网格生成器

    将参数配置转换为所有可能的参数组合。
    """

    def __init__(self, param_config: Dict[str, List[Any]]):
        """
        Args:
            param_config: 参数配置，如 {'fast_period': [12, 26], 'signal_period': [9]}
        """
        self.param_config = param_config
        self._combinations: Optional[List[Dict[str, Any]]] = None

    def __len__(self) -> int:
        if self._combinations is None:
            self._generate()
        return len(self._combinations)

    def __iter__(self):
        if self._combinations is None:
            self._generate()
        return iter(self._combinations)

    def _generate(self):
        """生成所有参数组合"""
        keys = list(self.param_config.keys())
        values = list(self.param_config.values())

        self._combinations = []
        for combination in itertools.product(*values):
            self._combinations.append(dict(zip(keys, combination)))

    def get_combinations(self) -> List[Dict[str, Any]]:
        """获取所有参数组合"""
        if self._combinations is None:
            self._generate()
        return self._combinations


class GridOptimizer:
    """
    网格搜索参数优化器

    使用多进程并行搜索最优参数组合。
    """

    def __init__(
        self,
        objective: str = 'total_return',
        mode: str = 'max',
        top_n: int = 5
    ):
        """
        Args:
            objective: 优化目标 ('total_return', 'sharpe_ratio', 'max_drawdown', 'win_rate')
            mode: 优化模式 ('max' 或 'min')
            top_n: 返回前N组最优参数
        """
        self.objective = objective
        self.mode = mode  # 'max' or 'min'
        self.top_n = top_n
        self.results: List[Dict[str, Any]] = []
        self._max_workers = max(1, multiprocessing.cpu_count() - 1)

    def optimize(
        self,
        backtest_func: Callable,
        param_grid: ParameterGrid,
        strategy_class: Type[StrategyBase],
        data: List[Dict[str, Any]],
        fixed_params: Dict[str, Any] = None,
        initial_balance: float = 100000.0,
        **kwargs
    ) -> Dict[str, Any]:
        """
        运行参数优化

        Args:
            backtest_func: 回测函数，签名为 (strategy_class, params, data, initial_balance) -> dict
            param_grid: 参数网格
            strategy_class: 策略类
            data: K线数据
            fixed_params: 固定参数（不参与优化）
            initial_balance: 初始资金

        Returns:
            优化结果字典
        """
        fixed_params = fixed_params or {}
        combinations = param_grid.get_combinations()
        total = len(combinations)

        self.results = []

        if total == 0:
            return {'success': False, 'error': '没有参数组合'}

        print(f"开始参数优化: {total} 种参数组合, 目标={self.objective}")

        # 小规模串行执行，大规模并行
        if total <= 10:
            for i, params in enumerate(combinations):
                merged_params = {**fixed_params, **params}
                result = backtest_func(
                    strategy_class=strategy_class,
                    params=merged_params,
                    data=data,
                    initial_balance=initial_balance
                )
                result['_params'] = params
                self.results.append(result)
                print(f"  [{i+1}/{total}] {params}")
        else:
            with ProcessPoolExecutor(max_workers=self._max_workers) as executor:
                futures = {}
                for params in combinations:
                    merged_params = {**fixed_params, **params}
                    future = executor.submit(
                        backtest_func,
                        strategy_class=strategy_class,
                        params=merged_params,
                        data=data,
                        initial_balance=initial_balance
                    )
                    futures[future] = params

                completed = 0
                for future in as_completed(futures):
                    completed += 1
                    params = futures[future]
                    try:
                        result = future.result()
                        result['_params'] = params
                        self.results.append(result)
                        print(f"  [{completed}/{total}] {params}")
                    except Exception as e:
                        print(f"  [{completed}/{total}] 失败: {params} - {e}")

        # 排序
        self._sort_results()

        # 取前N个
        top = self.results[:self.top_n]

        return {
            'success': True,
            'total_combinations': total,
            'objective': self.objective,
            'mode': self.mode,
            'top_params': [r.get('_params') for r in top],
            'top_results': top,
            'all_results': self.results,
        }

    def _sort_results(self):
        """根据优化目标排序"""
        if self.mode == 'max':
            reverse = True
        else:
            reverse = False

        if self.objective == 'max_drawdown':
            # 最大回撤越小越好
            reverse = not reverse

        self.results.sort(
            key=lambda r: r.get('statistics', {}).get(self.objective, 0) if isinstance(r.get('statistics'), dict) else 0,
            reverse=reverse
        )

    def plot_heatmap(
        self,
        param_x: str,
        param_y: str,
        metric: str = 'total_return'
    ) -> Any:
        """
        绘制双参数热力图

        注意: 只支持2个参数的优化
        """
        try:
            import numpy as np
            import plotly.graph_objects as go

            # 提取参数值
            x_values = sorted(set(r.get('_params', {}).get(param_x, None) for r in self.results))
            y_values = sorted(set(r.get('_params', {}).get(param_y, None) for r in self.results))

            if None in x_values or None in y_values:
                print(f"热力图: 参数 {param_x} 或 {param_y} 不在结果中")
                return None

            # 构建热力图矩阵
            z = np.full((len(y_values), len(x_values)), None, dtype=float)
            for r in self.results:
                params = r.get('_params', {})
                try:
                    ix = x_values.index(params.get(param_x))
                    iy = y_values.index(params.get(param_y))
                    val = r.get('statistics', {}).get(metric, 0)
                    z[iy, ix] = val if val is not None else 0
                except (ValueError, KeyError):
                    continue

            fig = go.Figure(data=go.Heatmap(
                z=z,
                x=x_values,
                y=y_values,
                colorscale='Viridis',
                colorbar=dict(title=metric)
            ))
            fig.update_layout(
                title=f"参数优化热力图: {param_x} vs {param_y}",
                xaxis_title=param_x,
                yaxis_title=param_y
            )
            return fig
        except ImportError:
            print("热力图需要 plotly: pip install plotly")
            return None


def run_backtest_for_optimization(
    strategy_class: Type[StrategyBase],
    params: Dict[str, Any],
    data: List[Dict[str, Any]],
    initial_balance: float = 100000.0
) -> Dict[str, Any]:
    """
    用于参数优化的回测函数

    这个函数签名与 GridOptimizer.optimize 的 backtest_func 参数兼容。

    Args:
        strategy_class: 策略类
        params: 策略参数
        data: K线数据
        initial_balance: 初始资金

    Returns:
        回测结果字典
    """
    from .backtest_engine import BacktestEngine

    strategy = strategy_class(params=params)
    engine = BacktestEngine(
        initial_balance=initial_balance,
        commission_rate=0.0001
    )
    result = engine.run(strategy, data)

    # 确保 statistics 有基本字段
    if 'statistics' not in result:
        result['statistics'] = {}

    return result

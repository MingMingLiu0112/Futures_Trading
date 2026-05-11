#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
参数优化器 - 网格搜索优化策略参数

用法:
```python
from backtest.optimizer import ParameterOptimizer, OptimizationTarget
from backtest import BacktestingEngine, pandas_to_bars

# 1. 创建优化器
optimizer = ParameterOptimizer()

# 2. 设置引擎和数据
optimizer.set_engine(engine)
optimizer.set_data(bars)

# 3. 设置参数网格
optimizer.add_parameter("fast_period", 5, 20, 3)   # start, end, step
optimizer.add_parameter("slow_period", 15, 40, 5)

# 4. 设置优化目标
optimizer.set_target(OptimizationTarget.SHARPE_RATIO)

# 5. 运行优化
results = optimizer.run(max_workers=4)

# 6. 获取最优参数
best = optimizer.get_best_params()
print(f"最优参数: {best}")
```
"""

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple, Type
import itertools
import multiprocessing

from .native_engine import BacktestingEngine, AlphaStrategy
from vnpy.trader.object import BarData
from vnpy.trader.constant import Interval

# Re-export for convenience
from .optimizer_extension import GridOptimizer, ParameterGrid, run_backtest_for_optimization


class OptimizationTarget:
    """优化目标"""
    
    TOTAL_RETURN = "total_return"           # 总收益率
    ANNUAL_RETURN = "annual_return"          # 年化收益率
    SHARPE_RATIO = "sharpe_ratio"            # 夏普比率
    MAX_DRAWDOWN = "max_drawdown"            # 最大回撤(越小越好)
    RETURN_DRAWDOWN_RATIO = "return_drawdown_ratio"  # 收益回撤比
    DAILY_NET_PNL = "daily_net_pnl"          # 日均盈亏


@dataclass
class OptimizationResult:
    """单次优化结果"""
    params: Dict[str, Any]
    stats: Dict[str, Any]
    
    @property
    def total_return(self) -> float:
        return self.stats.get("total_return", 0)
    
    @property
    def annual_return(self) -> float:
        return self.stats.get("annual_return", 0)
    
    @property
    def sharpe_ratio(self) -> float:
        return self.stats.get("sharpe_ratio", 0)
    
    @property
    def max_drawdown(self) -> float:
        return self.stats.get("max_drawdown", float("inf"))
    
    @property
    def return_drawdown_ratio(self) -> float:
        return self.stats.get("return_drawdown_ratio", 0)
    
    @property
    def daily_net_pnl(self) -> float:
        return self.stats.get("daily_net_pnl", 0)
    
    @property
    def total_trade_count(self) -> int:
        return self.stats.get("total_trade_count", 0)


@dataclass
class ParameterGrid:
    """参数网格"""
    name: str
    start: float
    end: float
    step: float
    
    def values(self) -> List[Any]:
        """生成参数值列表"""
        result = []
        value = self.start
        while value <= self.end:
            result.append(int(value) if self.step >= 1 else value)
            value += self.step
        return result


class ParameterOptimizer:
    """
    策略参数优化器
    
    使用网格搜索找到最优参数组合
    """
    
    def __init__(
        self,
        strategy_class: Optional[Type[AlphaStrategy]] = None,
        target: str = OptimizationTarget.SHARPE_RATIO
    ):
        self.strategy_class = strategy_class
        self.target = target
        
        # 引擎和数据
        self.engine: Optional[BacktestingEngine] = None
        self.bars: List[BarData] = []
        self.vt_symbols: List[str] = []
        self.interval: Interval = Interval.MINUTE
        self.start: Optional[datetime] = None
        self.end: Optional[datetime] = None
        
        # 参数网格
        self.param_grids: List[ParameterGrid] = []
        
        # 结果
        self.results: List[OptimizationResult] = []
        
        # 并行数
        self.max_workers = max(1, multiprocessing.cpu_count() - 1)
        
        # 约束条件
        self.min_trade_count = 0
        self.min_total_return = None
    
    def set_engine_config(
        self,
        vt_symbols: List[str],
        interval: Interval,
        start: datetime,
        end: datetime,
        capital: float = 1_000_000,
        **kwargs
    ) -> "ParameterOptimizer":
        """设置引擎配置"""
        self.vt_symbols = vt_symbols
        self.interval = interval
        self.start = start
        self.end = end
        self.engine_config = {
            "capital": capital,
            "risk_free": kwargs.get("risk_free", 0),
            "annual_days": kwargs.get("annual_days", 240),
            "size": kwargs.get("size", 10),
            "pricetick": kwargs.get("pricetick", 1),
            "long_rate": kwargs.get("long_rate", 0.00005),
            "short_rate": kwargs.get("short_rate", 0.00005),
        }
        return self
    
    def set_data(self, bars: List[BarData]) -> "ParameterOptimizer":
        """设置K线数据"""
        self.bars = bars
        return self
    
    def add_parameter(
        self,
        name: str,
        start: float,
        end: float,
        step: float = 1
    ) -> "ParameterOptimizer":
        """添加要优化的参数"""
        self.param_grids.append(ParameterGrid(name, start, end, step))
        return self
    
    def set_target(self, target: str) -> "ParameterOptimizer":
        """设置优化目标"""
        self.target = target
        return self
    
    def set_constraints(
        self,
        min_trade_count: int = 0,
        min_total_return: Optional[float] = None
    ) -> "ParameterOptimizer":
        """设置约束条件"""
        self.min_trade_count = min_trade_count
        self.min_total_return = min_total_return
        return self
    
    def set_max_workers(self, max_workers: int) -> "ParameterOptimizer":
        """设置并行任务数"""
        self.max_workers = max_workers
        return self
    
    def _generate_param_combinations(self) -> List[Dict[str, Any]]:
        """生成所有参数组合"""
        if not self.param_grids:
            return [{}]
        
        param_names = [pg.name for pg in self.param_grids]
        param_values_list = [pg.values() for pg in self.param_grids]
        
        combinations = []
        for values in itertools.product(*param_values_list):
            combinations.append(dict(zip(param_names, values)))
        
        return combinations
    
    def _run_single_backtest(self, params: Dict[str, Any]) -> OptimizationResult:
        """运行单次回测"""
        engine = BacktestingEngine()
        engine.set_parameters(
            vt_symbols=self.vt_symbols,
            interval=self.interval,
            start=self.start,
            end=self.end,
            capital=self.engine_config["capital"],
            risk_free=self.engine_config["risk_free"],
            annual_days=self.engine_config["annual_days"],
        )
        
        # 添加合约配置
        for symbol in self.vt_symbols:
            engine.add_contract_setting(
                symbol,
                size=self.engine_config["size"],
                pricetick=self.engine_config["pricetick"],
                long_rate=self.engine_config["long_rate"],
                short_rate=self.engine_config["short_rate"],
            )
        
        engine.load_data(self.bars)
        
        # 深拷贝参数
        from copy import deepcopy
        strategy_params = deepcopy(params)
        engine.add_strategy(self.strategy_class, strategy_params)
        
        # 运行回测
        engine.run_backtesting()
        
        # 计算结果
        engine.calculate_result()
        stats = engine.calculate_statistics()
        
        return OptimizationResult(params=params, stats=stats)
    
    def run(self, progress: bool = True) -> List[OptimizationResult]:
        """
        运行参数优化
        
        Returns:
            List[OptimizationResult]: 所有参数组合的优化结果
        """
        if self.strategy_class is None:
            raise ValueError("strategy_class must be set")
        
        param_combinations = self._generate_param_combinations()
        total = len(param_combinations)
        
        print(f"开始参数优化: {total} 种参数组合")
        print(f"优化目标: {self.target}")
        print("-" * 50)
        
        self.results = []
        
        if total == 1:
            # 单参数组合直接运行
            result = self._run_single_backtest(param_combinations[0])
            self.results.append(result)
        elif total <= 10:
            # 小规模串行执行
            for i, params in enumerate(param_combinations):
                result = self._run_single_backtest(params)
                self.results.append(result)
                if progress:
                    print(f"  [{i+1}/{total}] {params}")
        else:
            # 大规模并行执行
            with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(self._run_single_backtest, params): params
                    for params in param_combinations
                }
                
                completed = 0
                for future in as_completed(futures):
                    completed += 1
                    try:
                        result = future.result()
                        self.results.append(result)
                        if progress:
                            params = futures[future]
                            print(f"  [{completed}/{total}] {params}")
                    except Exception as e:
                        if progress:
                            print(f"  [{completed}/{total}] 失败: {e}")
        
        # 过滤约束条件
        self._filter_results()
        
        # 排序
        self._sort_results()
        
        print("-" * 50)
        print(f"优化完成! 有效结果: {len(self.results)}")
        
        return self.results
    
    def _filter_results(self) -> None:
        """过滤不满足约束条件的结果"""
        filtered = []
        for result in self.results:
            # 检查交易次数
            if result.total_trade_count < self.min_trade_count:
                continue
            
            # 检查收益率
            if self.min_total_return is not None:
                if result.total_return < self.min_total_return:
                    continue
            
            filtered.append(result)
        
        self.results = filtered
    
    def _sort_results(self) -> None:
        """根据优化目标排序结果"""
        if self.target == OptimizationTarget.MAX_DRAWDOWN:
            # 最大回撤越小越好
            self.results.sort(key=lambda x: x.max_drawdown)
        elif self.target == OptimizationTarget.TOTAL_RETURN:
            self.results.sort(key=lambda x: x.total_return, reverse=True)
        elif self.target == OptimizationTarget.ANNUAL_RETURN:
            self.results.sort(key=lambda x: x.annual_return, reverse=True)
        elif self.target == OptimizationTarget.SHARPE_RATIO:
            self.results.sort(key=lambda x: x.sharpe_ratio, reverse=True)
        elif self.target == OptimizationTarget.RETURN_DRAWDOWN_RATIO:
            self.results.sort(key=lambda x: x.return_drawdown_ratio, reverse=True)
        elif self.target == OptimizationTarget.DAILY_NET_PNL:
            self.results.sort(key=lambda x: x.daily_net_pnl, reverse=True)
    
    def get_best_params(self, n: int = 1) -> List[Dict[str, Any]]:
        """
        获取最优参数
        
        Args:
            n: 返回前N组最优参数
            
        Returns:
            List[Dict]: 参数列表
        """
        if not self.results:
            return []
        return [r.params for r in self.results[:n]]
    
    def get_top_results(self, n: int = 1) -> List[OptimizationResult]:
        """
        获取前N个最优结果
        
        Args:
            n: 返回前N个结果
            
        Returns:
            List[OptimizationResult]: 结果列表
        """
        if not self.results:
            return []
        return self.results[:n]
    
    def get_best_result(self) -> Optional[OptimizationResult]:
        """获取最优结果"""
        if not self.results:
            return None
        return self.results[0]
    
    def get_results_by_rank(self, rank: int) -> Optional[OptimizationResult]:
        """获取指定排名的结果(1-indexed)"""
        if not self.results or rank > len(self.results):
            return None
        return self.results[rank - 1]
    
    def print_top_results(self, n: int = 10) -> None:
        """打印前N个最优结果"""
        if not self.results:
            print("没有优化结果")
            return
        
        print(f"\n{'排名':<6}{'参数':<40}{'总收益':<12}{'年化收益':<12}{'夏普比率':<10}{'最大回撤':<12}{'交易次数':<10}")
        print("-" * 100)
        
        for i, result in enumerate(self.results[:n]):
            params_str = str(result.params)[:38]
            print(
                f"{i+1:<6}"
                f"{params_str:<40}"
                f"{result.total_return:>10.2f}%  "
                f"{result.annual_return:>10.2f}%  "
                f"{result.sharpe_ratio:>8.2f}  "
                f"{result.max_drawdown:>10.2f}  "
                f"{result.total_trade_count:>8}"
            )
    
    def export_results(self, path: str) -> None:
        """导出优化结果到CSV"""
        import csv
        
        if not self.results:
            print("没有结果可导出")
            return
        
        with open(path, 'w', newline='', encoding='utf-8') as f:
            # 写入参数列
            param_names = list(self.results[0].params.keys())
            
            fieldnames = param_names + [
                "total_return", "annual_return", "sharpe_ratio",
                "max_drawdown", "max_ddpercent", "return_drawdown_ratio",
                "total_trade_count", "daily_net_pnl"
            ]
            
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for result in self.results:
                row = dict(result.params)
                row.update({
                    "total_return": result.stats.get("total_return", 0),
                    "annual_return": result.stats.get("annual_return", 0),
                    "sharpe_ratio": result.stats.get("sharpe_ratio", 0),
                    "max_drawdown": result.stats.get("max_drawdown", 0),
                    "max_ddpercent": result.stats.get("max_ddpercent", 0),
                    "return_drawdown_ratio": result.stats.get("return_drawdown_ratio", 0),
                    "total_trade_count": result.stats.get("total_trade_count", 0),
                    "daily_net_pnl": result.stats.get("daily_net_pnl", 0),
                })
                writer.writerow(row)
        
        print(f"结果已导出到: {path}")
    
    def plot_optimization_heatmap(
        self,
        param_x: str,
        param_y: str,
        metric: str = "sharpe_ratio"
    ) -> None:
        """
        绘制双参数热力图
        
        注意: 只支持2个参数的优化
        """
        if len(self.param_grids) != 2:
            print("热力图只支持2个参数的优化")
            return
        
        import numpy as np
        import plotly.graph_objects as go
        
        # 获取参数值
        values_x = self.param_grids[0].values()
        values_y = self.param_grids[1].values()
        
        # 构建热力图数据
        z = np.zeros((len(values_y), len(values_x)))
        
        for result in self.results:
            try:
                ix = values_x.index(result.params[param_x])
                iy = values_y.index(result.params[param_y])
                
                if metric == "sharpe_ratio":
                    z[iy, ix] = result.sharpe_ratio
                elif metric == "total_return":
                    z[iy, ix] = result.total_return
                elif metric == "annual_return":
                    z[iy, ix] = result.annual_return
                elif metric == "max_drawdown":
                    z[iy, ix] = -result.max_drawdown  # 取负因为越小越好
            except (ValueError, KeyError):
                continue
        
        fig = go.Figure(data=go.Heatmap(
            z=z,
            x=values_x,
            y=values_y,
            colorscale='Viridis',
            colorbar=dict(title=metric)
        ))
        
        fig.update_layout(
            title=f"参数优化热力图: {param_x} vs {param_y}",
            xaxis_title=param_x,
            yaxis_title=param_y
        )
        
        fig.show()


if __name__ == "__main__":
    # 快速测试
    from backtest import BacktestingEngine, pandas_to_bars
    from backtest.examples.macd_strategy import MacdStrategy
    from vnpy.trader.constant import Interval
    import numpy as np
    import pandas as pd
    
    print("参数优化器测试")
    print("=" * 50)
    
    # 生成测试数据
    np.random.seed(42)
    n = 5000
    dates = pd.date_range('2024-03-01', periods=n, freq='min')
    close = 6000 + np.cumsum(np.random.randn(n) * 5)
    df = pd.DataFrame({
        'datetime': dates,
        'open': close - 5, 'high': close + 10, 'low': close - 10,
        'close': close, 'volume': 500
    })
    
    bars = pandas_to_bars(df, "TA.CZCE")
    
    # 创建优化器
    optimizer = ParameterOptimizer(strategy_class=MacdStrategy)
    optimizer.set_engine_config(
        vt_symbols=["TA.CZCE"],
        interval=Interval.MINUTE,
        start=datetime(2024, 3, 1),
        end=datetime(2024, 6, 30),
        capital=100_000,
    )
    optimizer.set_data(bars)
    
    # 设置参数网格
    optimizer.add_parameter("fast_period", 5, 15, 5)
    optimizer.add_parameter("slow_period", 20, 40, 10)
    
    # 设置优化目标
    optimizer.set_target(OptimizationTarget.SHARPE_RATIO)
    
    # 设置约束
    optimizer.set_constraints(min_trade_count=1)
    
    # 运行优化
    results = optimizer.run(progress=True)
    
    # 打印结果
    optimizer.print_top_results(5)
    
    print()
    print("最优参数:", optimizer.get_best_params()[0])

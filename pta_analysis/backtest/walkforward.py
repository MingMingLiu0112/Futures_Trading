#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Walk-Forward Analysis（滚动窗口验证）
=====================================

防止过拟合的标准方法：
1. 用历史数据「训练窗口」优化参数
2. 在「测试窗口」验证参数效果
3. 滚动向前移动，重复以上步骤

对比结果解读：
- 训练集得分 >> 测试集得分 → 过拟合
- 训练集得分 ≈ 测试集得分 → 参数稳健

用法:
```python
from backtest.walkforward import WalkForwardAnalyzer, WalkForwardConfig

config = WalkForwardConfig(
    train_window=240,    # 训练窗口（天数或K线根数）
    test_window=60,     # 测试窗口
    step=60,            # 滚动步长
    top_n=5,            # 每轮取前N组参数
)
analyzer = WalkForwardAnalyzer(config)
result = analyzer.run(strategy_class=MyStrategy, data=kline_data)
```
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type
import random

from .strategy_base import StrategyBase


@dataclass
class WalkForwardConfig:
    """Walk-Forward 配置"""
    train_window: int = 240          # 训练窗口大小（根K线数）
    test_window: int = 60           # 测试窗口大小
    step: int = 60                  # 滚动步长
    top_n: int = 5                  # 每轮取前N组参数
    objective: str = "total_return" # 优化目标
    mode: str = "max"               # max 或 min
    min_train_trades: int = 5       # 训练集最小交易次数过滤
    parallel: bool = False          # 是否并行（串行更稳定）

    def __post_init__(self):
        assert self.train_window > 0
        assert self.test_window > 0
        assert self.step > 0


@dataclass
class WalkForwardRound:
    """单轮 Walk-Forward 结果"""
    round_index: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    best_params: Dict[str, Any]
    train_stats: Dict[str, float]
    test_stats: Dict[str, float]
    train_score: float   # 训练集上的目标指标
    test_score: float    # 测试集上的目标指标
    degradation: float   # 衰退率 (train - test) / train
    degradation_pct: float  # 衰退百分比


@dataclass
class WalkForwardResult:
    """完整 Walk-Forward 分析结果"""
    rounds: List[WalkForwardRound]
    train_degradation_avg: float      # 平均衰退率
    test_score_avg: float             # 测试集平均得分
    train_score_avg: float            # 训练集平均得分
    is_robust: bool                  # 是否稳健（平均衰退 < 20%）
    consistency: float               # 一致性（测试集得分 > 0 的比例）
    conclusion: str                  # 综合结论


class WalkForwardAnalyzer:
    """
    Walk-Forward 滚动验证分析器

    将数据划分为多个「训练→测试」窗口，
    在每个训练窗口优化参数，在对应测试窗口验证。
    """

    def __init__(self, config: WalkForwardConfig = None):
        self.config = config or WalkForwardConfig()

    def run(
        self,
        strategy_class: Type[StrategyBase],
        data: List[Dict[str, Any]],
        param_grid: Dict[str, List[Any]],
        backtest_func: Callable = None,
        initial_balance: float = 100000.0,
        fixed_params: Dict[str, Any] = None,
    ) -> WalkForwardResult:
        """
        运行 Walk-Forward 分析

        Args:
            strategy_class: 策略类
            data: K线数据（有序列表）
            param_grid: 参数网格，如 {'fast': [5,10,15], 'slow': [20,30]}
            backtest_func: 回测函数，签名为 (strategy_class, params, data, initial_balance) -> dict
            initial_balance: 初始资金
            fixed_params: 固定参数

        Returns:
            WalkForwardResult
        """
        from .optimizer_extension import ParameterGrid
        from .optimizer_extension import run_backtest_for_optimization

        if backtest_func is None:
            backtest_func = run_backtest_for_optimization

        fixed_params = fixed_params or {}
        grid = ParameterGrid(param_grid)
        combinations = grid.get_combinations()
        total = len(combinations)

        cfg = self.config
        rounds: List[WalkForwardRound] = []

        # 滑动窗口
        pos = 0
        round_idx = 0

        while pos + cfg.train_window + cfg.test_window <= len(data):
            train_data = data[pos: pos + cfg.train_window]
            test_data = data[pos + cfg.train_window: pos + cfg.train_window + cfg.test_window]

            train_end_idx = pos + cfg.train_window - 1
            test_end_idx = pos + cfg.train_window + cfg.test_window - 1

            print(f"\n[WF Round {round_idx+1}] train=[{pos}:{train_end_idx}] test=[{train_end_idx+1}:{test_end_idx}] "
                  f"train_bars={len(train_data)} test_bars={len(test_data)}")

            # ---- 训练阶段：在 train_data 上找最优参数 ----
            best_params, best_score = None, float('-inf') if cfg.mode == 'max' else float('inf')
            train_stats_best = {}

            # 串行遍历所有参数组合
            for params in combinations:
                merged = {**fixed_params, **params}
                result = backtest_func(
                    strategy_class=strategy_class,
                    params=merged,
                    data=train_data,
                    initial_balance=initial_balance
                )
                stats = result.get('statistics', {})
                score = stats.get(cfg.objective, 0) if cfg.mode == 'max' else stats.get(cfg.objective, float('inf'))
                trades = stats.get('total_trades', 0)

                if cfg.mode == 'max' and score > best_score and trades >= cfg.min_train_trades:
                    best_score = score
                    best_params = merged.copy()
                    train_stats_best = stats.copy()
                elif cfg.mode == 'min' and score < best_score and trades >= cfg.min_train_trades:
                    best_score = score
                    best_params = merged.copy()
                    train_stats_best = stats.copy()

            if best_params is None:
                print(f"  [WF] 训练窗口无有效参数（交易次数不足 {cfg.min_train_trades}），跳过")
                pos += cfg.step
                round_idx += 1
                continue

            print(f"  [WF] 训练最优: {best_params}, score={best_score:.4f}, trades={train_stats_best.get('total_trades',0)}")

            # ---- 测试阶段：用最优参数在 test_data 上验证 ----
            test_result = backtest_func(
                strategy_class=strategy_class,
                params=best_params,
                data=test_data,
                initial_balance=initial_balance
            )
            test_stats = test_result.get('statistics', {})
            test_score = test_stats.get(cfg.objective, 0)

            degradation = best_score - test_score
            degradation_pct = (degradation / abs(best_score) * 100) if best_score != 0 else 0

            print(f"  [WF] 测试得分: score={test_score:.4f}, 衰退={degradation_pct:.1f}%, trades={test_stats.get('total_trades',0)}")

            wf_round = WalkForwardRound(
                round_index=round_idx,
                train_start=pos,
                train_end=train_end_idx,
                test_start=train_end_idx + 1,
                test_end=test_end_idx,
                best_params=best_params,
                train_stats=train_stats_best,
                test_stats=test_stats,
                train_score=best_score,
                test_score=test_score,
                degradation=degradation,
                degradation_pct=degradation_pct,
            )
            rounds.append(wf_round)

            pos += cfg.step
            round_idx += 1

        if not rounds:
            return WalkForwardResult(
                rounds=[],
                train_degradation_avg=0,
                test_score_avg=0,
                train_score_avg=0,
                is_robust=False,
                consistency=0,
                conclusion="数据不足，无法完成 Walk-Forward 分析",
            )

        # ---- 汇总统计 ----
        train_scores = [r.train_score for r in rounds]
        test_scores = [r.test_score for r in rounds]
        degradations = [r.degradation_pct for r in rounds]

        train_avg = sum(train_scores) / len(train_scores)
        test_avg = sum(test_scores) / len(test_scores)
        deg_avg = sum(degradations) / len(degradations)
        consistency = sum(1 for s in test_scores if s > 0) / len(test_scores)

        is_robust = deg_avg < 20.0  # 衰退 < 20% 认为稳健

        # 生成结论
        if is_robust and consistency >= 0.7:
            conclusion = f"策略稳健（平均衰退 {deg_avg:.1f}%，测试得分一致率 {consistency*100:.0f}%）"
        elif is_robust and consistency < 0.7:
            conclusion = f"参数稳健但测试得分波动大（衰退 {deg_avg:.1f}%，一致率 {consistency*100:.0f}%）"
        elif deg_avg >= 20 and deg_avg < 50:
            conclusion = f"轻度过拟合（平均衰退 {deg_avg:.1f}%）"
        else:
            conclusion = f"严重过拟合（平均衰退 {deg_avg:.1f}%），参数不可靠"

        result = WalkForwardResult(
            rounds=rounds,
            train_degradation_avg=round(deg_avg, 2),
            test_score_avg=round(test_avg, 4),
            train_score_avg=round(train_avg, 4),
            is_robust=is_robust,
            consistency=round(consistency, 2),
            conclusion=conclusion,
        )

        print(f"\n[WF] 汇总: 轮次={len(rounds)}, 平均衰退={deg_avg:.1f}%, 测试均分={test_avg:.4f}, 稳健={is_robust}")
        print(f"[WF] 结论: {conclusion}")

        return result

    def print_summary(self, result: WalkForwardResult) -> None:
        """打印汇总报告"""
        print("\n" + "=" * 70)
        print("Walk-Forward 分析报告")
        print("=" * 70)
        print(f"滚动轮次: {len(result.rounds)}")
        print(f"训练集平均得分: {result.train_score_avg:.4f}")
        print(f"测试集平均得分: {result.test_score_avg:.4f}")
        print(f"平均参数衰退: {result.train_degradation_avg:.1f}%")
        print(f"测试得分一致率: {result.consistency*100:.0f}%")
        print(f"稳健判定: {'✅ 稳健' if result.is_robust else '❌ 过拟合'}")
        print(f"结论: {result.conclusion}")
        print("-" * 70)
        print(f"{'轮次':<6} {'训练区间':<20} {'测试区间':<20} {'训练得分':<12} {'测试得分':<12} {'衰退%':<8} {'最优参数'}")
        print("-" * 70)
        for r in result.rounds:
            print(f"{r.round_index+1:<6} "
                  f"({r.train_start:>4}-{r.train_end:>4}) "
                  f"({r.test_start:>4}-{r.test_end:>4}) "
                  f"{r.train_score:>10.4f}  {r.test_score:>10.4f}  {r.degradation_pct:>6.1f}%  {r.best_params}")
        print("=" * 70)


# ---- Monte Carlo 模拟 ----

@dataclass
class MonteCarloConfig:
    """Monte Carlo 配置"""
    n_simulations: int = 1000       # 模拟次数
    randomize_trades: bool = True   # 打乱交易顺序
    bootstrap: bool = False          # 带放回抽样（bootstrap）
    confidence_levels: List[float] = field(default_factory=lambda: [0.05, 0.25, 0.50, 0.75, 0.95])


@dataclass
class MonteCarloResult:
    """Monte Carlo 模拟结果"""
    equity_curves: List[List[float]]  # 所有模拟的权益曲线
    final_balances: List[float]       # 所有模拟的最终权益
    max_drawdowns: List[float]        # 所有模拟的最大回撤
    sharpe_ratios: List[float]        # 所有模拟的夏普比率
    final_balance_pcts: List[float]   # 最终权益百分比变化
    confidence: Dict[str, Dict[str, float]]  # 各置信水平统计
    # 分位数
    p5_final_balance: float
    p25_final_balance: float
    p50_final_balance: float
    p75_final_balance: float
    p95_final_balance: float
    p5_max_drawdown: float
    p95_max_drawdown: float
    probability_of_ruin: float        # 破产概率（权益 <= 0）


def _calc_equity_curve(trades: List[Dict], initial_balance: float) -> List[float]:
    """从交易列表重建权益曲线"""
    if not trades:
        return [initial_balance]
    curve = [initial_balance]
    bal = initial_balance
    for t in trades:
        bal += t.get('pnl', 0)
        curve.append(bal)
    return curve


def _max_drawdown_from_curve(curve: List[float]) -> float:
    peak = curve[0]
    max_dd = 0
    for bal in curve:
        if bal > peak:
            peak = bal
        dd = peak - bal
        if dd > max_dd:
            max_dd = dd
    return max_dd


def run_monte_carlo(
    trades: List[Dict[str, Any]],
    initial_balance: float = 100000.0,
    config: MonteCarloConfig = None,
) -> MonteCarloResult:
    """
    Monte Carlo 模拟

    通过打乱交易顺序，评估策略的稳健性和收益分布。

    用法:
    ```python
    from backtest.walkforward import run_monte_carlo, MonteCarloConfig

    mc_result = run_monte_carlo(trades, initial_balance=100000)
    print(f"50%分位数最终权益: {mc_result.p50_final_balance:,.0f}")
    print(f"破产概率: {mc_result.probability_of_ruin:.1%}")
    ```
    """
    if config is None:
        config = MonteCarloConfig()

    if not trades:
        return MonteCarloResult(
            equity_curves=[], final_balances=[], max_drawdowns=[],
            sharpe_ratios=[], final_balance_pcts=[],
            confidence={}, p5_final_balance=0, p25_final_balance=0,
            p50_final_balance=0, p75_final_balance=0, p95_final_balance=0,
            p5_max_drawdown=0, p95_max_drawdown=0, probability_of_ruin=0
        )

    n = config.n_simulations
    equity_curves: List[List[float]] = []
    final_balances: List[float] = []
    max_drawdowns: List[float] = []
    sharpe_ratios: List[float] = []
    final_balance_pcts: List[float] = []

    for i in range(n):
        # 复制交易列表
        sim_trades = trades.copy()

        # 打乱顺序（核心：验证收益是否来自交易顺序）
        if config.randomize_trades:
            random.shuffle(sim_trades)

        # 计算权益曲线
        curve = _calc_equity_curve(sim_trades, initial_balance)
        equity_curves.append(curve)

        final_bal = curve[-1]
        final_balances.append(final_bal)
        final_balance_pcts.append((final_bal - initial_balance) / initial_balance * 100)

        # 最大回撤
        max_dd = _max_drawdown_from_curve(curve)
        max_drawdowns.append(max_dd)

        # 简化夏普（用收益率标准差）
        if len(curve) > 1:
            returns = [(curve[j] - curve[j-1]) / curve[j-1] for j in range(1, len(curve)) if curve[j-1] > 0]
            if returns and len(returns) > 1:
                mean_ret = sum(returns) / len(returns)
                variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
                std = variance ** 0.5
                if std > 0:
                    sharpe = (mean_ret / std) * (240 ** 0.5)  # 年化
                else:
                    sharpe = 0
            else:
                sharpe = 0
        else:
            sharpe = 0
        sharpe_ratios.append(sharpe)

    # 计算分位数
    sorted_final = sorted(final_balances)
    n_total = len(sorted_final)
    pcts = [5, 25, 50, 75, 95]

    def percentile(data, p):
        idx = int(len(data) * p / 100)
        idx = min(idx, len(data) - 1)
        return sorted(data)[int(len(data) * p / 100)]

    p5 = percentile(sorted_final, 5)
    p25 = percentile(sorted_final, 25)
    p50 = percentile(sorted_final, 50)
    p75 = percentile(sorted_final, 75)
    p95 = percentile(sorted_final, 95)

    sorted_dd = sorted(max_drawdowns)
    p5_dd = percentile(sorted_dd, 5)
    p95_dd = percentile(sorted_dd, 95)

    # 破产概率
    ruin_count = sum(1 for fb in final_balances if fb <= 0)
    prob_ruin = ruin_count / n

    # 各置信区间统计
    confidence = {}
    for level in config.confidence_levels:
        idx_lo = max(0, int(n_total * level / 2))
        idx_hi = min(n_total - 1, n_total - 1 - idx_lo)
        sorted_fb = sorted(final_balances)
        confidence[f"{int(level*100)}"] = {
            'final_balance': sorted_fb[idx_hi] if idx_hi < len(sorted_fb) else sorted_fb[-1],
            'max_drawdown': sorted_dd[idx_hi] if idx_hi < len(sorted_dd) else sorted_dd[-1],
        }

    return MonteCarloResult(
        equity_curves=equity_curves,
        final_balances=final_balances,
        max_drawdowns=max_drawdowns,
        sharpe_ratios=sharpe_ratios,
        final_balance_pcts=final_balance_pcts,
        confidence=confidence,
        p5_final_balance=p5,
        p25_final_balance=p25,
        p50_final_balance=p50,
        p75_final_balance=p75,
        p95_final_balance=p95,
        p5_max_drawdown=p5_dd,
        p95_max_drawdown=p95_dd,
        probability_of_ruin=prob_ruin,
    )


def print_monte_carlo_summary(result: MonteCarloResult, initial_balance: float = 100000.0) -> None:
    """打印 Monte Carlo 汇总"""
    print("\n" + "=" * 60)
    print("Monte Carlo 模拟报告")
    print("=" * 60)
    print(f"模拟次数: {len(result.final_balances)}")
    print(f"最终权益分位数:")
    print(f"  5%   (最差情况):  {result.p5_final_balance:>12,.0f}  ({(result.p5_final_balance/initial_balance-1)*100:+.1f}%)")
    print(f"  25%:                  {result.p25_final_balance:>12,.0f}  ({(result.p25_final_balance/initial_balance-1)*100:+.1f}%)")
    print(f"  50%  (中位数):        {result.p50_final_balance:>12,.0f}  ({(result.p50_final_balance/initial_balance-1)*100:+.1f}%)")
    print(f"  75%:                  {result.p75_final_balance:>12,.0f}  ({(result.p75_final_balance/initial_balance-1)*100:+.1f}%)")
    print(f"  95%  (最好情况):      {result.p95_final_balance:>12,.0f}  ({(result.p95_final_balance/initial_balance-1)*100:+.1f}%)")
    print(f"最大回撤 5%~95%: {result.p5_max_drawdown:,.0f} ~ {result.p95_max_drawdown:,.0f}")
    print(f"破产概率: {result.probability_of_ruin:.1%}")
    if result.probability_of_ruin < 0.05:
        print("✅ 破产概率 < 5%，风险可控")
    elif result.probability_of_ruin < 0.20:
        print("⚠️ 破产概率 5%~20%，存在一定风险")
    else:
        print("❌ 破产概率 > 20%，风险较高")
    print("=" * 60)

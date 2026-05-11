"""
VNpy回测框架 - 完整版
=====================

基于官方vnpy框架结构实现的回测框架,包含:

- event: 事件引擎 (EventEngine)
- lab: 数据加载 (AlphaLab)
- gateway: 交易网关抽象层
- strategy: 策略模板 (CtaStrategy, AlphaStrategy)

用法:

```python
# 1. 使用AlphaLab加载数据
from backtest.lab import AlphaLab
lab = AlphaLab()
bars = lab.load_bar_data("TA.CZCE", Interval.MINUTE, start, end)

# 2. 使用回测引擎
from backtest import BacktestingEngine
engine = BacktestingEngine()
engine.load_data(bars)
engine.add_strategy(MacdStrategy, setting={...})
engine.run_backtesting()

# 3. 使用事件驱动
from backtest.event import EventEngine, Event, EventType
ee = EventEngine()
ee.register(EventType.BAR, on_bar_handler)
ee.start()
```

"""

# 核心引擎
from backtest.native_engine import (
    BacktestingEngine,
    AlphaStrategy,
    ContractDailyResult,
    PortfolioDailyResult,
    df_to_bars,
    pandas_to_bars,
)

# 事件引擎
from backtest.event import (
    EventEngine,
    Event,
    EventType,
    EventHandler,
    LogEvent,
)

# 数据实验室
from backtest.lab import (
    AlphaLab,
    bars_to_dataframe,
    dataframe_to_bars,
)

# Gateway
from backtest.gateway import (
    BaseGateway,
    TqGateway,
    SimNowGateway,
    GatewayManager,
    GatewaySetting,
    GatewayType,
)

# 策略模板
from backtest.strategy import (
    CtaStrategy,
    MultiTimeframeStrategy,
    StrategyManager,
)

# 工具
from backtest.strategy_base import (
    StrategyIndicator,
    PositionManager,
    IndicatorBar,
)

# 优化器
from backtest.optimizer import (
    ParameterOptimizer,
    OptimizationResult,
    OptimizationTarget,
)
from backtest.optimizer_extension import (
    GridOptimizer,
    ParameterGrid,
    run_backtest_for_optimization,
)

# 轻量级回测
from backtest.backtest_engine import BacktestEngine
from backtest.performance_metrics import calculate_performance_metrics
from backtest.strategy_base import StrategyBase, StrategySignal, TradeResult
from backtest.strategy_comparison import StrategyComparator
from backtest.backtest_exporter import BacktestExporter
from backtest.walkforward import (
    WalkForwardAnalyzer,
    WalkForwardConfig,
    WalkForwardResult,
    run_monte_carlo,
    MonteCarloConfig,
    MonteCarloResult,
)

__all__ = [
    # 核心
    "BacktestingEngine",
    "AlphaStrategy",
    "ContractDailyResult",
    "PortfolioDailyResult",
    "df_to_bars",
    "pandas_to_bars",
    # 事件
    "EventEngine",
    "Event",
    "EventType",
    "EventHandler",
    "LogEvent",
    # 数据
    "AlphaLab",
    "bars_to_dataframe",
    "dataframe_to_bars",
    # Gateway
    "BaseGateway",
    "TqGateway",
    "SimNowGateway",
    "GatewayManager",
    "GatewaySetting",
    "GatewayType",
    # 策略
    "CtaStrategy",
    "MultiTimeframeStrategy",
    "StrategyManager",
    # 工具
    "StrategyIndicator",
    "PositionManager",
    "IndicatorBar",
    # 优化
    "ParameterOptimizer",
    "OptimizationResult",
    "OptimizationTarget",
    "GridOptimizer",
    "ParameterGrid",
    "run_backtest_for_optimization",
    # 轻量级回测
    "BacktestEngine",
    "calculate_performance_metrics",
    "StrategyBase",
    "StrategySignal",
    "TradeResult",
    "StrategyComparator",
    "BacktestExporter",
    # Walk-Forward & Monte Carlo
    "WalkForwardAnalyzer",
    "WalkForwardConfig",
    "WalkForwardResult",
    "run_monte_carlo",
    "MonteCarloConfig",
    "MonteCarloResult",
]

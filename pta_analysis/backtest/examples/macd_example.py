#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MACD策略示例 - 展示如何在VNpy框架下编写策略

用法:
```python
from backtest.examples.macd_example import MacdStrategy, run_macd_backtest

# 简单运行
stats = run_macd_backtest("TA.CZCE", start, end, capital=100000)

# 或者自定义参数
from backtest import BacktestingEngine
engine = BacktestingEngine()
# ... 配置引擎和数据
engine.add_strategy(MacdStrategy, setting={
    "fast_period": 12,
    "slow_period": 26,
    "signal_period": 9,
    "bar_window": 20,         # K线窗口
    "size": 1,                # 每次交易手数
    "fixed_size": True,       # 固定手数交易
})
```

"""

from datetime import datetime
from typing import Dict
from collections import defaultdict

from ..vnpy_data import BarData, Direction, Offset, Interval
from ..vnpy_backtest_engine import BacktestingEngine, AlphaStrategy
from ..vnpy_data import TradeData


class MacdStrategy(AlphaStrategy):
    """
    MACD趋势策略
    
    策略逻辑:
    - MACD金叉(快线从下方穿过慢线) -> 做多
    - MACD死叉(快线从上方穿过慢线) -> 做空/平多
    - 或者基于MACD柱方向变化
    
    参数:
    - fast_period: 快线周期 (默认12)
    - slow_period: 慢线周期 (默认26)
    - signal_period: 信号线周期 (默认9)
    - bar_window: K线窗口用于过滤 (默认20)
    - size: 交易手数 (默认1)
    - fixed_size: 是否固定手数 (默认True)
    """
    
    author = "VNpy User"
    
    fast_period: int = 12
    slow_period: int = 26
    signal_period: int = 9
    bar_window: int = 20
    size: int = 1
    fixed_size: bool = True
    
    def __init__(self, strategy_engine, strategy_name, vt_symbols, setting):
        super().__init__(strategy_engine, strategy_name, vt_symbols, setting)
        
        # 指标缓存
        self.fast_ema: Dict[str, float] = defaultdict(lambda: None)
        self.slow_ema: Dict[str, float] = defaultdict(lambda: None)
        self.macd: Dict[str, float] = defaultdict(lambda: None)
        self.signal: Dict[str, float] = defaultdict(lambda: None)
        self.histogram: Dict[str, float] = defaultdict(lambda: None)
        self.pre_histogram: Dict[str, float] = defaultdict(lambda: None)
        
        # 持仓状态
        self.intra_trade_high: Dict[str, float] = defaultdict(lambda: 0)
        self.intra_trade_low: Dict[str, float] = defaultdict(lambda: float('inf'))
        
        self.write_log(f"MACD策略初始化完成, 参数: fast={self.fast_period}, slow={self.slow_period}, signal={self.signal_period}")
    
    def on_init(self) -> None:
        """策略初始化"""
        self.write_log("策略初始化...")
        
        # 可以在这里初始化指标数据
        for vt_symbol in self.vt_symbols:
            self.fast_ema[vt_symbol] = 0
            self.slow_ema[vt_symbol] = 0
            self.macd[vt_symbol] = 0
            self.signal[vt_symbol] = 0
            self.histogram[vt_symbol] = 0
            self.pre_histogram[vt_symbol] = 0
    
    def on_bars(self, bars: Dict[str, BarData]) -> None:
        """K线回调"""
        for vt_symbol, bar in bars.items():
            self.process_bar(vt_symbol, bar)
    
    def process_bar(self, vt_symbol: str, bar: BarData) -> None:
        """处理单根K线"""
        # 更新持仓状态
        pos = self.get_pos(vt_symbol)
        
        # 计算MACD
        self.calculate_macd(vt_symbol, bar.close_price)
        
        # 获取前一时刻的MACD柱
        pre_hist = self.pre_histogram[vt_symbol]
        curr_hist = self.histogram[vt_symbol]
        
        # 无持仓时
        if pos == 0:
            # MACD金叉买入条件:
            # 1. 快线 > 慢线 (histogram > 0)
            # 2. 前一时刻 histogram < 0 (从负转正)
            if pre_hist < 0 and curr_hist > 0:
                self.write_log(f"{bar.datetime} {vt_symbol} MACD金叉, 买入开仓")
                self.buy(vt_symbol, bar.close_price, self.size)
                self.intra_trade_high[vt_symbol] = bar.high_price
                self.intra_trade_low[vt_symbol] = bar.low_price
        
        # 有多头持仓时
        elif pos > 0:
            self.intra_trade_high[vt_symbol] = max(self.intra_trade_high[vt_symbol], bar.high_price)
            
            # 止损: 价格跌破买入后最低价的2%
            cost = self.get_avg_cost(vt_symbol)
            if cost and bar.low_price < cost * 0.98:
                self.write_log(f"{bar.datetime} {vt_symbol} 止损卖出")
                self.sell(vt_symbol, bar.close_price, abs(pos))
            
            # MACD死叉: 卖出平仓
            elif pre_hist > 0 and curr_hist < 0:
                self.write_log(f"{bar.datetime} {vt_symbol} MACD死叉, 卖出平仓")
                self.sell(vt_symbol, bar.close_price, abs(pos))
        
        # 有空头持仓时
        elif pos < 0:
            self.intra_trade_low[vt_symbol] = min(self.intra_trade_low[vt_symbol], bar.low_price)
            
            # 止损
            cost = self.get_avg_cost(vt_symbol)
            if cost and bar.high_price > cost * 1.02:
                self.write_log(f"{bar.datetime} {vt_symbol} 止损买入")
                self.cover(vt_symbol, bar.close_price, abs(pos))
            
            # MACD金叉: 买入平仓
            elif pre_hist < 0 and curr_hist > 0:
                self.write_log(f"{bar.datetime} {vt_symbol} MACD金叉, 买入平仓")
                self.cover(vt_symbol, bar.close_price, abs(pos))
        
        # 更新前一时刻的histogram
        self.pre_histogram[vt_symbol] = curr_hist
    
    def calculate_macd(self, vt_symbol: str, close_price: float) -> None:
        """
        计算MACD指标
        
        EMA公式: EMA_t = (Close_t * k) + (EMA_{t-1} * (1 - k))
        其中 k = 2 / (period + 1)
        
        DIF = EMA(fast) - EMA(slow)
        DEA = EMA(DIF, signal_period)
        MACD = (DIF - DEA) * 2  # 柱状图,乘以2是为了和传统MACD一致
        """
        fast_k = 2 / (self.fast_period + 1)
        slow_k = 2 / (self.slow_period + 1)
        signal_k = 2 / (self.signal_period + 1)
        
        # 初始化
        if self.fast_ema[vt_symbol] == 0:
            self.fast_ema[vt_symbol] = close_price
            self.slow_ema[vt_symbol] = close_price
        
        # 计算EMA
        self.fast_ema[vt_symbol] = close_price * fast_k + self.fast_ema[vt_symbol] * (1 - fast_k)
        self.slow_ema[vt_symbol] = close_price * slow_k + self.slow_ema[vt_symbol] * (1 - slow_k)
        
        # DIF
        dif = self.fast_ema[vt_symbol] - self.slow_ema[vt_symbol]
        self.macd[vt_symbol] = dif
        
        # DEA (Signal)
        if self.signal[vt_symbol] == 0:
            self.signal[vt_symbol] = dif
        else:
            self.signal[vt_symbol] = dif * signal_k + self.signal[vt_symbol] * (1 - signal_k)
        
        # MACD柱
        self.histogram[vt_symbol] = (dif - self.signal[vt_symbol]) * 2
    
    def get_avg_cost(self, vt_symbol: str) -> float:
        """获取持仓成本"""
        pos = self.get_pos(vt_symbol)
        if pos == 0:
            return 0
        
        # 从交易记录计算成本
        trades = self.strategy_engine.get_all_trades()
        total_cost = 0
        total_volume = 0
        
        for trade in trades:
            if trade.vt_symbol == vt_symbol and trade.direction == Direction.LONG:
                if trade.offset == Offset.OPEN:
                    total_cost += trade.price * trade.volume
                    total_volume += trade.volume
        
        if total_volume > 0:
            return total_cost / total_volume
        return 0
    
    def on_trade(self, trade: TradeData) -> None:
        """成交回调"""
        self.write_log(
            f"成交: {trade.datetime} {trade.vt_symbol} {trade.direction.value} "
            f"{trade.offset.value} {trade.price} x {trade.volume}"
        )


def run_macd_backtest(
    vt_symbol: str,
    start: datetime,
    end: datetime,
    capital: float = 100_000,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    size: int = 1,
) -> Dict:
    """
    运行MACD回测的便捷函数
    
    Args:
        vt_symbol: 合约代码, 如 "TA.CZCE"
        start: 回测开始时间
        end: 回测结束时间
        capital: 初始资金
        fast: MACD快线周期
        slow: MACD慢线周期
        signal: MACD信号线周期
        size: 每次交易手数
    
    Returns:
        包含回测结果的字典
    """
    from ..vnpy_data import DataConverter
    
    # 1. 创建引擎
    engine = BacktestingEngine()
    
    # 2. 设置参数
    engine.set_parameters(
        vt_symbols=[vt_symbol],
        interval=Interval.MINUTE,
        start=start,
        end=end,
        capital=capital,
    )
    
    # 3. 添加合约配置
    engine.add_contract_setting(
        vt_symbol,
        size=10,           # 合约乘数
        pricetick=2,       # 最小变动价位
        commission_rate=0.00005  # 手续费率
    )
    
    # 4. 加载数据 (需要自己提供)
    # from your_data_source import get_bars
    # bars = get_bars(vt_symbol, start, end)
    # engine.load_data(bars)
    
    # 5. 添加策略
    engine.add_strategy(MacdStrategy, setting={
        "fast_period": fast,
        "slow_period": slow,
        "signal_period": signal,
        "size": size,
    })
    
    # 6. 运行回测
    engine.run_backtesting()
    
    # 7. 计算结果
    stats = engine.calculate_statistics()
    
    return {
        "stats": stats,
        "engine": engine,
        "strategy": engine.strategy,
    }


# 演示如何从DataFrame加载数据并运行回测
def run_backtest_from_df(
    df: 'pd.DataFrame',
    vt_symbol: str,
    start: datetime,
    end: datetime,
    capital: float = 100_000,
    strategy_class=MacdStrategy,
    strategy_params: Dict = None,
) -> Dict:
    """
    从DataFrame加载数据并运行回测
    
    DataFrame必须包含列:
    - datetime: 时间戳
    - open: 开盘价
    - high: 最高价
    - low: 最低价
    - close: 收盘价
    - volume: 成交量
    """
    from ..vnpy_data import DataConverter
    
    # 1. 创建引擎
    engine = BacktestingEngine()
    
    # 2. 设置参数
    engine.set_parameters(
        vt_symbols=[vt_symbol],
        interval=Interval.MINUTE,
        start=start,
        end=end,
        capital=capital,
    )
    
    # 3. 添加合约配置
    engine.add_contract_setting(
        vt_symbol,
        size=10,
        pricetick=2,
        commission_rate=0.00005
    )
    
    # 4. 从DataFrame转换K线
    bars = DataConverter.dataframe_to_bars(df, vt_symbol)
    
    # 过滤日期范围
    bars = [bar for bar in bars if start <= bar.datetime <= end]
    
    # 5. 加载数据
    engine.load_data(bars)
    
    # 6. 添加策略
    params = strategy_params or {}
    engine.add_strategy(strategy_class, setting=params)
    
    # 7. 运行回测
    engine.run_backtesting()
    
    # 8. 计算结果
    stats = engine.calculate_statistics()
    
    return {
        "stats": stats,
        "engine": engine,
        "equity_curve": engine.get_equity_curve(),
        "trades": engine.get_all_trades(),
        "orders": engine.get_all_orders(),
    }


if __name__ == "__main__":
    print("=" * 50)
    print("MACD策略回测示例")
    print("=" * 50)
    print()
    print("用法:")
    print("```python")
    print("from backtest.examples.macd_example import MacdStrategy, run_backtest_from_df")
    print()
    print("# 准备数据")
    print("df = get_your_data()  # DataFrame with OHLCV")
    print()
    print("# 运行回测")
    print("result = run_backtest_from_df(")
    print("    df, vt_symbol='TA.CZCE',")
    print("    start=datetime(2024,1,1),")
    print("    end=datetime(2024,12,31),")
    print("    capital=100000")
    print(")")
    print()
    print("# 查看结果")
    print("stats = result['stats']")
    print("equity = result['equity_curve']")
    print("```")
    print()
    
    # 演示生成测试数据
    import numpy as np
    import pandas as pd
    
    print("生成测试数据演示...")
    
    # 生成随机K线数据
    np.random.seed(42)
    n = 5000
    dates = pd.date_range("2024-01-01", periods=n, freq="min")
    
    close = 6000 + np.cumsum(np.random.randn(n) * 10)
    high = close + np.random.rand(n) * 50
    low = close - np.random.rand(n) * 50
    open_price = low + np.random.rand(n) * (high - low)
    volume = np.random.randint(100, 1000, n)
    
    df = pd.DataFrame({
        "datetime": dates,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })
    
    print(f"生成了 {len(df)} 根测试K线")
    print(f"时间范围: {df['datetime'].iloc[0]} ~ {df['datetime'].iloc[-1]}")
    print()
    print("运行回测中...")
    
    result = run_backtest_from_df(
        df,
        vt_symbol="TA.CZCE",
        start=datetime(2024, 3, 1),
        end=datetime(2024, 6, 30),
        capital=100000,
        strategy_params={"fast_period": 12, "slow_period": 26, "signal_period": 9, "size": 1}
    )
    
    print()
    print("回测完成!")
    
    # 显示图表(如果可用)
    try:
        print("尝试显示图表...")
        result["engine"].show_chart()
    except Exception as e:
        print(f"图表显示跳过: {e}")

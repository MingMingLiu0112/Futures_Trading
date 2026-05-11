#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MACD策略示例 - 展示如何在VNpy框架下编写策略

用法:
```python
from backtest.examples.macd_strategy import MacdStrategy, run_macd_example

# 简单运行
stats = run_macd_example("TA.CZCE", start, end, capital=100000)

# 或者自定义参数
from backtest import BacktestingEngine, pandas_to_bars
engine = BacktestingEngine()
# ... 配置引擎和数据
engine.add_strategy(MacdStrategy, setting={
    "fast_period": 12,
    "slow_period": 26,
    "signal_period": 9,
    "size": 1,
})
```
"""

from datetime import datetime
from typing import Dict, List
from collections import defaultdict

from ..native_engine import BacktestingEngine, AlphaStrategy
from vnpy.trader.object import BarData
from vnpy.trader.constant import Direction, Offset


class MacdStrategy(AlphaStrategy):
    """
    MACD趋势策略
    
    策略逻辑:
    - DIF线上穿DEA线(金叉) -> 做多
    - DIF线下穿DEA线(死叉) -> 平多/做空
    - MACD柱由绿转红(负转正) -> 做多
    - MACD柱由红转绿(正转负) -> 平多/做空
    
    参数:
    - fast_period: 快线EMA周期 (默认12)
    - slow_period: 慢线EMA周期 (默认26)
    - signal_period: 信号线周期 (默认9)
    - size: 交易手数 (默认1)
    """
    
    author = "VNpy User"
    
    fast_period: int = 12
    slow_period: int = 26
    signal_period: int = 9
    size: int = 1
    
    def __init__(self, strategy_engine, strategy_name, vt_symbols, setting):
        super().__init__(strategy_engine, strategy_name, vt_symbols, setting)
        
        # EMA指标
        self.fast_ema: Dict[str, float] = defaultdict(float)
        self.slow_ema: Dict[str, float] = defaultdict(float)
        self.dif: Dict[str, float] = defaultdict(float)
        self.dea: Dict[str, float] = defaultdict(float)
        self.pre_hist: Dict[str, float] = defaultdict(float)
        
        # 缓存窗口
        self.bar_count: Dict[str, int] = defaultdict(int)
        
        self.write_log(f"MACD策略初始化: fast={self.fast_period}, slow={self.slow_period}, signal={self.signal_period}")
    
    def on_bars(self, bars: Dict[str, BarData]) -> None:
        """K线回调"""
        for vt_symbol, bar in bars.items():
            self.process_bar(vt_symbol, bar)
    
    def process_bar(self, vt_symbol: str, bar: BarData) -> None:
        """处理单根K线"""
        close = bar.close_price
        self.bar_count[vt_symbol] += 1
        
        # 计算MACD
        fk = 2 / (self.fast_period + 1)
        sk = 2 / (self.slow_period + 1)
        sig_k = 2 / (self.signal_period + 1)
        
        if self.fast_ema[vt_symbol] == 0:
            self.fast_ema[vt_symbol] = close
            self.slow_ema[vt_symbol] = close
            self.dif[vt_symbol] = 0
            self.dea[vt_symbol] = 0
            self.pre_hist[vt_symbol] = 0
            return
        
        # EMA更新
        self.fast_ema[vt_symbol] = close * fk + self.fast_ema[vt_symbol] * (1 - fk)
        self.slow_ema[vt_symbol] = close * sk + self.slow_ema[vt_symbol] * (1 - sk)
        
        # DIF = 快EMA - 慢EMA
        dif = self.fast_ema[vt_symbol] - self.slow_ema[vt_symbol]
        
        # DEA = DIF的EMA
        if self.dea[vt_symbol] == 0:
            self.dea[vt_symbol] = dif
        else:
            self.dea[vt_symbol] = dif * sig_k + self.dea[vt_symbol] * (1 - sig_k)
        
        # MACD柱 = (DIF - DEA) * 2
        hist = (dif - self.dea[vt_symbol]) * 2
        
        pos = self.get_pos(vt_symbol)
        
        # 交易信号
        if pos == 0:
            # 无持仓
            if self.pre_hist[vt_symbol] < 0 and hist >= 0:
                # MACD柱由绿转红 -> 买入开仓
                self.buy(vt_symbol, close, self.size)
        elif pos > 0:
            # 持有多仓
            if self.pre_hist[vt_symbol] > 0 and hist <= 0:
                # MACD柱由红转绿 -> 卖出平仓
                self.sell(vt_symbol, close, abs(pos))
        elif pos < 0:
            # 持有空仓
            if self.pre_hist[vt_symbol] > 0 and hist <= 0:
                # MACD柱由红转绿 -> 买入平仓
                self.cover(vt_symbol, close, abs(pos))
            elif self.pre_hist[vt_symbol] < 0 and hist >= 0:
                # MACD柱由绿转红 -> 做空开仓
                self.short(vt_symbol, close, self.size)
        
        self.pre_hist[vt_symbol] = hist


class RsiStrategy(AlphaStrategy):
    """
    RSI均值回归策略
    
    策略逻辑:
    - RSI低于超卖线(默认30) -> 买入
    - RSI高于超买线(默认70) -> 卖出
    
    参数:
    - rsi_period: RSI周期 (默认14)
    - rsi_long: 做多阈值 (默认30)
    - rsi_short: 做空阈值 (默认70)
    - size: 交易手数 (默认1)
    """
    
    author = "VNpy User"
    
    rsi_period: int = 14
    rsi_long: float = 30
    rsi_short: float = 70
    size: int = 1
    
    def __init__(self, strategy_engine, strategy_name, vt_symbols, setting):
        super().__init__(strategy_engine, strategy_name, vt_symbols, setting)
        
        self.rsi: Dict[str, float] = defaultdict(float)
        self.gains: Dict[str, float] = defaultdict(float)
        self.losses: Dict[str, float] = defaultdict(float)
        self.pre_close: Dict[str, float] = defaultdict(float)
        
        self.write_log(f"RSI策略初始化: period={self.rsi_period}, long={self.rsi_long}, short={self.rsi_short}")
    
    def on_bars(self, bars: Dict[str, BarData]) -> None:
        for vt_symbol, bar in bars.items():
            close = bar.close_price
            
            # 计算RSI
            if self.pre_close[vt_symbol] == 0:
                self.pre_close[vt_symbol] = close
                return
            
            change = close - self.pre_close[vt_symbol]
            self.gains[vt_symbol] = (self.gains[vt_symbol] * (self.rsi_period - 1) + max(change, 0)) / self.rsi_period
            self.losses[vt_symbol] = (self.losses[vt_symbol] * (self.rsi_period - 1) + max(-change, 0)) / self.rsi_period
            
            if self.losses[vt_symbol] == 0:
                self.rsi[vt_symbol] = 100
            else:
                rs = self.gains[vt_symbol] / self.losses[vt_symbol]
                self.rsi[vt_symbol] = 100 - (100 / (1 + rs))
            
            pos = self.get_pos(vt_symbol)
            
            # 交易信号
            if pos == 0:
                if self.rsi[vt_symbol] < self.rsi_long:
                    self.buy(vt_symbol, close, self.size)
            elif pos > 0:
                if self.rsi[vt_symbol] > self.rsi_short:
                    self.sell(vt_symbol, close, abs(pos))
            
            self.pre_close[vt_symbol] = close


class BollingerStrategy(AlphaStrategy):
    """
    布林带均值回归策略
    
    策略逻辑:
    - 价格下穿布林带下轨 -> 买入
    - 价格上穿布林带上轨 -> 卖出
    
    参数:
    - bb_period: 布林带周期 (默认20)
    - bb_std: 标准差倍数 (默认2)
    - size: 交易手数 (默认1)
    """
    
    author = "VNpy User"
    
    bb_period: int = 20
    bb_std: float = 2
    size: int = 1
    
    def __init__(self, strategy_engine, strategy_name, vt_symbols, setting):
        super().__init__(strategy_engine, strategy_name, vt_symbols, setting)
        
        self.close_prices: Dict[str, List[float]] = defaultdict(list)
        self.write_log(f"布林带策略初始化: period={self.bb_period}, std={self.bb_std}")
    
    def on_bars(self, bars: Dict[str, BarData]) -> None:
        for vt_symbol, bar in bars.items():
            close = bar.close_price
            
            self.close_prices[vt_symbol].append(close)
            if len(self.close_prices[vt_symbol]) > self.bb_period:
                self.close_prices[vt_symbol].pop(0)
            
            if len(self.close_prices[vt_symbol]) < self.bb_period:
                continue
            
            import numpy as np
            prices = np.array(self.close_prices[vt_symbol])
            mid = np.mean(prices)
            std = np.std(prices)
            upper = mid + self.bb_std * std
            lower = mid - self.bb_std * std
            
            pos = self.get_pos(vt_symbol)
            
            if pos == 0:
                if close <= lower:
                    self.buy(vt_symbol, close, self.size)
            elif pos > 0:
                if close >= upper:
                    self.sell(vt_symbol, close, abs(pos))


def run_macd_example(
    symbol: str = "TA.CZCE",
    start: datetime = datetime(2024, 3, 1),
    end: datetime = datetime(2024, 6, 30),
    capital: float = 100_000,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
    size: int = 1,
) -> dict:
    """
    运行MACD策略示例回测
    
    Returns:
        dict: 回测统计结果
    """
    from backtest import pandas_to_bars
    from vnpy.trader.constant import Interval
    import pandas as pd
    import numpy as np
    
    # 生成模拟数据
    np.random.seed(42)
    n = 10000
    base = 6000
    data = []
    for i in range(n):
        dt = start.toordinal() + i // 240
        close = base + np.random.randn() * 10
        data.append({
            'datetime': datetime.fromordinal(dt) if isinstance(dt, int) else dt,
            'open': close - 5,
            'high': close + 10,
            'low': close - 10,
            'close': close,
            'volume': 100
        })
    
    df = pd.DataFrame(data)
    
    # 创建引擎
    engine = BacktestingEngine()
    engine.set_parameters(
        vt_symbols=[symbol],
        interval=Interval.MINUTE,
        start=start,
        end=end,
        capital=capital,
        risk_free=0.0,
        annual_days=240
    )
    engine.add_contract_setting(
        symbol,
        size=10,
        pricetick=2,
        long_rate=0.00005,
        short_rate=0.00005
    )
    
    # 加载数据
    bars = pandas_to_bars(df, symbol)
    engine.load_data(bars)
    
    # 添加策略
    engine.add_strategy(MacdStrategy, setting={
        "fast_period": fast_period,
        "slow_period": slow_period,
        "signal_period": signal_period,
        "size": size
    })
    
    # 运行回测
    engine.run_backtesting()
    
    # 计算结果
    engine.calculate_result()
    stats = engine.calculate_statistics()
    
    return stats


if __name__ == "__main__":
    print("=" * 60)
    print("MACD策略示例回测")
    print("=" * 60)
    
    stats = run_macd_example(
        symbol="TA.CZCE",
        start=datetime(2024, 3, 1),
        end=datetime(2024, 6, 30),
        capital=100_000
    )
    
    print()
    print("回测完成!")

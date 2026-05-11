#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略模板模块 - 对标vnpy.trader的策略体系

包含:
- CtaStrategy: CTA策略模板
- AlphaStrategy: Alpha策略模板
- AlgoStrategy: 算法交易策略模板

用法:
```python
from backtest.strategy import CtaStrategy, AlphaStrategy

class MyCtaStrategy(CtaStrategy):
    def on_init(self):
        self.intra_trade_high = 0
        self.intra_trade_low = 0
    
    def on_calculate(self, bar):
        # 计算策略信号
        if self.pos == 0:
            if self.macd > 0:
                self.buy(bar.close_price, 1)
        elif self.pos > 0:
            if self.macd < 0:
                self.sell(bar.close_price, abs(self.pos))
```
"""

from abc import ABC, abstractmethod
from collections import defaultdict
from copy import copy
from datetime import datetime
from typing import Dict, List, Optional, Any, TYPE_CHECKING
import numpy as np

from vnpy.trader.constant import Direction, Offset, Interval, Status
from vnpy.trader.object import BarData, TickData, TradeData, OrderData

if TYPE_CHECKING:
    from backtest.native_engine import BacktestingEngine


# ==================== CtaStrategy ====================

class CtaStrategy:
    """
    CTA策略模板
    
    对标vnpy.trader.app.cta_strategy.template.CtaStrategy
    
    特点:
    - 基于K线回测
    - 支持固定手数交易
    - 内置持仓管理
    - 支持止损止盈
    
    用法:
    ```python
    class MyStrategy(CtaStrategy):
        author = "MyName"
        
        # 策略参数
        fast_period = 12
        slow_period = 26
        
        def on_init(self):
            '''策略初始化'''
            self.register()
        
        def on_calculate(self, bar):
            '''策略计算'''
            # 计算指标
            self.update_ema(bar)
            
            # 交易逻辑
            if self.pos == 0:
                if self.fast_ema > self.slow_ema:
                    self.buy(bar.close_price, 1)
            elif self.pos > 0:
                if self.fast_ema < self.slow_ema:
                    self.sell(bar.close_price, abs(self.pos))
        
        def on_stop(self):
            '''策略停止'''
            pass
    ```
    """
    
    author: str = ""
    class_name: str = ""
    
    # 策略参数 (子类可以覆盖)
    name: str = ""
    vt_symbols: List[str] = []
    
    # 运行时参数
    pos: float = 0                    # 当前持仓
    trading: bool = True              # 是否允许交易
    
    # 指标缓存
    bars: Dict[str, BarData] = {}
    tick: Optional[TickData] = None
    
    def __init__(
        self,
        strategy_engine: "BacktestingEngine",
        strategy_name: str,
        vt_symbols: List[str],
        setting: dict
    ):
        """
        初始化策略
        
        Args:
            strategy_engine: 策略引擎
            strategy_name: 策略名称
            vt_symbols: 合约列表
            setting: 参数配置
        """
        self.strategy_engine = strategy_engine
        self.strategy_name = strategy_name
        self.vt_symbols = vt_symbols
        
        # 运行时变量
        self.pos = 0
        self.inited = False
        self.trading = True
        
        # K线和Tick缓存
        self.bars = {}
        self.tick = None
        
        # 订单管理
        self.orders: Dict[str, OrderData] = {}
        self.active_orderids: set = set()
        
        # 持仓成本
        self.long_entry: float = 0
        self.short_entry: float = 0
        
        # 应用参数
        for key, value in setting.items():
            if hasattr(self, key):
                setattr(self, key, value)
        
        # 策略名称
        if not self.name:
            self.name = self.class_name or self.__class__.__name__
    
    def on_init(self) -> None:
        """
        策略初始化回调
        
        在回测/实盘开始前调用,用于:
        - 加载历史数据
        - 初始化指标
        - 预计算
        """
        pass
    
    def on_start(self) -> None:
        """策略启动回调"""
        pass
    
    def on_stop(self) -> None:
        """
        策略停止回调
        
        用于:
        - 平仓
        - 清理资源
        """
        # 默认: 平所有持仓
        if self.pos != 0:
            for vt_symbol in self.vt_symbols:
                bar = self.bars.get(vt_symbol)
                if bar:
                    if self.pos > 0:
                        self.sell(bar.close_price, abs(self.pos))
                    else:
                        self.cover(bar.close_price, abs(self.pos))
    
    def on_calculate(self, bar: BarData) -> None:
        """
        K线计算回调 (CTA策略主入口)
        
        Args:
            bar: K线数据
        """
        pass
    
    def on_tick(self, tick: TickData) -> None:
        """
        Tick行情回调
        
        Args:
            tick: Tick数据
        """
        self.tick = tick
        
        # 更新最新价
        if hasattr(self.strategy_engine, 'update_tick'):
            self.strategy_engine.update_tick(tick)
    
    def on_bar(self, bar: BarData) -> None:
        """
        K线回调 (用于多合约)
        
        Args:
            bar: K线数据
        """
        self.bars[bar.vt_symbol] = bar
        self.on_calculate(bar)
    
    def on_trade(self, trade: TradeData) -> None:
        """
        成交回调
        
        Args:
            trade: 成交数据
        """
        # 更新持仓
        if trade.direction == Direction.LONG:
            if trade.offset == Offset.OPEN:
                self.pos += trade.volume
                if self.pos == trade.volume:
                    self.long_entry = trade.price
            else:
                self.pos -= trade.volume
        else:
            if trade.offset == Offset.OPEN:
                self.pos -= trade.volume
                if self.pos == -trade.volume:
                    self.short_entry = trade.price
            else:
                self.pos += trade.volume
    
    def on_order(self, order: OrderData) -> None:
        """
        订单回调
        
        Args:
            order: 订单数据
        """
        self.orders[order.vt_orderid] = order
        
        if not order.is_active():
            self.active_orderids.discard(order.vt_orderid)
    
    def buy(
        self,
        price: float,
        volume: float,
        vt_symbol: Optional[str] = None
    ) -> List[str]:
        """
        买入开仓
        
        Args:
            price: 价格
            volume: 数量
            vt_symbol: 合约代码
            
        Returns:
            订单ID列表
        """
        if not self.trading:
            return []
        
        if vt_symbol is None:
            vt_symbol = self.vt_symbols[0] if self.vt_symbols else ""
        
        return self.send_order(
            vt_symbol, Direction.LONG, Offset.OPEN, price, volume
        )
    
    def sell(
        self,
        price: float,
        volume: float,
        vt_symbol: Optional[str] = None,
        stop: bool = False
    ) -> List[str]:
        """
        卖出平仓
        
        Args:
            price: 价格
            volume: 数量
            vt_symbol: 合约代码
            stop: 是否为止损单
        """
        if not self.trading:
            return []
        
        if vt_symbol is None:
            vt_symbol = self.vt_symbols[0] if self.vt_symbols else ""
        
        return self.send_order(
            vt_symbol, Direction.SHORT, Offset.CLOSE, price, volume
        )
    
    def short(
        self,
        price: float,
        volume: float,
        vt_symbol: Optional[str] = None
    ) -> List[str]:
        """
        卖出开仓
        
        Args:
            price: 价格
            volume: 数量
            vt_symbol: 合约代码
        """
        if not self.trading:
            return []
        
        if vt_symbol is None:
            vt_symbol = self.vt_symbols[0] if self.vt_symbols else ""
        
        return self.send_order(
            vt_symbol, Direction.SHORT, Offset.OPEN, price, volume
        )
    
    def cover(
        self,
        price: float,
        volume: float,
        vt_symbol: Optional[str] = None
    ) -> List[str]:
        """
        买入平仓
        
        Args:
            price: 价格
            volume: 数量
            vt_symbol: 合约代码
        """
        if not self.trading:
            return []
        
        if vt_symbol is None:
            vt_symbol = self.vt_symbols[0] if self.vt_symbols else ""
        
        return self.send_order(
            vt_symbol, Direction.LONG, Offset.CLOSE, price, volume
        )
    
    def send_order(
        self,
        vt_symbol: str,
        direction: Direction,
        offset: Offset,
        price: float,
        volume: float
    ) -> List[str]:
        """
        发送订单
        
        Args:
            vt_symbol: 合约代码
            direction: 方向
            offset: 开平
            price: 价格
            volume: 数量
        """
        if not self.strategy_engine:
            return []
        
        orderids = self.strategy_engine.send_order(
            self, vt_symbol, direction, offset, price, volume
        )
        
        for orderid in orderids:
            self.active_orderids.add(orderid)
        
        return orderids
    
    def cancel_order(self, orderid: str) -> None:
        """撤销订单"""
        if self.strategy_engine:
            self.strategy_engine.cancel_order(self, orderid)
    
    def cancel_all(self) -> None:
        """撤销所有活动订单"""
        for orderid in list(self.active_orderids):
            self.cancel_order(orderid)
    
    def get_pos(self, vt_symbol: Optional[str] = None) -> float:
        """
        获取持仓
        
        Args:
            vt_symbol: 合约代码
        """
        if vt_symbol is None:
            return self.pos
        return self.pos  # 简化版本只支持单一持仓
    
    def write_log(self, msg: str) -> None:
        """写日志"""
        if self.strategy_engine:
            self.strategy_engine.write_log(msg, self)
    
    def load_bar(
        self,
        vt_symbol: str,
        interval: Interval,
        start: datetime,
        end: datetime,
        rate: float = 0.0
    ) -> List[BarData]:
        """
        加载历史K线
        
        Args:
            vt_symbol: 合约代码
            interval: K线周期
            start: 开始时间
            end: 结束时间
            rate: 数据滚动窗口比例
        """
        if self.strategy_engine and hasattr(self.strategy_engine, 'load_bar'):
            return self.strategy_engine.load_bar(
                vt_symbol, interval, start, end, rate
            )
        return []


# ==================== 多周期策略 ====================

class MultiTimeframeStrategy(CtaStrategy):
    """
    多周期策略模板
    
    支持多个时间周期的策略,适用于跨周期分析。
    """
    
    def __init__(self, strategy_engine, strategy_name, vt_symbols, setting):
        super().__init__(strategy_engine, strategy_name, vt_symbols, setting)
        
        # 多周期K线缓存
        self.bar_minute: Dict[str, BarData] = {}
        self.bar_hour: Dict[str, BarData] = {}
        self.bar_daily: Dict[str, BarData] = {}
        
        # 周期切换标记
        self.last_minute: Dict[str, int] = {}
        self.last_hour: Dict[str, int] = {}
        self.last_day: Dict[str, int] = {}
    
    def on_bar(self, bar: BarData) -> None:
        """处理K线,自动聚合到不同周期"""
        vt_symbol = bar.vt_symbol
        
        # 存储分钟K线
        self.bar_minute[vt_symbol] = bar
        
        # 检查是否需要聚合小时K线
        minute = bar.datetime.minute
        if vt_symbol not in self.last_minute or self.last_minute[vt_symbol] != minute:
            if minute == 0 and vt_symbol in self.last_minute:
                # 新的小时开始,聚合小时K线
                self.bar_hour[vt_symbol] = bar
            self.last_minute[vt_symbol] = minute
        
        # 检查是否需要聚合日K线
        day = bar.datetime.day
        if vt_symbol not in self.last_day or self.last_day[vt_symbol] != day:
            if day == 1 and vt_symbol in self.last_day:
                # 新的月开始,聚合日K线
                self.bar_daily[vt_symbol] = bar
            self.last_day[vt_symbol] = day
        
        # 调用主计算逻辑
        self.on_calculate(bar)
    
    def get_bar(self, vt_symbol: str, interval: Interval) -> Optional[BarData]:
        """获取指定周期的最新K线"""
        if interval == Interval.MINUTE:
            return self.bar_minute.get(vt_symbol)
        elif interval == Interval.HOUR:
            return self.bar_hour.get(vt_symbol)
        elif interval == Interval.DAILY:
            return self.bar_daily.get(vt_symbol)
        return None


# ==================== 策略管理器 ====================

class StrategyManager:
    """
    策略管理器
    
    统一管理多个策略实例
    """
    
    def __init__(self, strategy_engine):
        self.strategy_engine = strategy_engine
        self.strategies: Dict[str, CtaStrategy] = {}
    
    def add_strategy(self, strategy_class: type, strategy_name: str, vt_symbols: List[str], setting: dict) -> CtaStrategy:
        """添加策略"""
        strategy = strategy_class(
            self.strategy_engine,
            strategy_name,
            vt_symbols,
            setting
        )
        self.strategies[strategy_name] = strategy
        return strategy
    
    def remove_strategy(self, strategy_name: str) -> None:
        """移除策略"""
        if strategy_name in self.strategies:
            self.strategies[strategy_name].on_stop()
            del self.strategies[strategy_name]
    
    def init_all(self) -> None:
        """初始化所有策略"""
        for strategy in self.strategies.values():
            strategy.on_init()
    
    def start_all(self) -> None:
        """启动所有策略"""
        for strategy in self.strategies.values():
            strategy.on_start()
    
    def stop_all(self) -> None:
        """停止所有策略"""
        for strategy in self.strategies.values():
            strategy.on_stop()
    
    def on_tick(self, tick: TickData) -> None:
        """分发Tick到各策略"""
        for strategy in self.strategies.values():
            strategy.on_tick(tick)
    
    def on_bar(self, bar: BarData) -> None:
        """分发K线到各策略"""
        for strategy in self.strategies.values():
            if bar.vt_symbol in strategy.vt_symbols:
                strategy.on_bar(bar)
    
    def on_trade(self, trade: TradeData) -> None:
        """分发成交到策略"""
        # 找到对应的策略
        for strategy in self.strategies.values():
            if trade.vt_symbol in strategy.vt_symbols:
                strategy.on_trade(trade)
    
    def get_strategy(self, strategy_name: str) -> Optional[CtaStrategy]:
        """获取策略"""
        return self.strategies.get(strategy_name)


if __name__ == "__main__":
    print("策略模板测试")
    print("=" * 50)
    
    class TestMACD(CtaStrategy):
        author = "Test"
        fast_period = 12
        slow_period = 26
        
        def on_init(self):
            self.fast_ema = 0
            self.slow_ema = 0
            print(f"{self.name} 初始化")
        
        def on_calculate(self, bar):
            # MACD计算
            k = 2 / (self.fast_period + 1)
            
            if self.fast_ema == 0:
                self.fast_ema = bar.close_price
                self.slow_ema = bar.close_price
            else:
                self.fast_ema = bar.close_price * k + self.fast_ema * (1 - k)
                self.slow_ema = bar.close_price * (2/(self.slow_period+1)) + self.slow_ema * (1 - 2/(self.slow_period+1))
            
            dif = self.fast_ema - self.slow_ema
            
            # 交易逻辑
            if self.pos == 0 and bar.close_price > self.fast_ema:
                self.buy(bar.close_price, 1)
            elif self.pos > 0 and bar.close_price < self.fast_ema:
                self.sell(bar.close_price, abs(self.pos))
    
    # 测试策略创建
    print("策略类创建成功")
    print(f"策略作者: {TestMACD.author}")
    print(f"快速周期: {TestMACD.fast_period}")

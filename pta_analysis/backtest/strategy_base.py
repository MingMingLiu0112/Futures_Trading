#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略基础模块 - 轻量级回测策略基类

与 native_engine.py 的 AlphaStrategy 不同，这里提供更简单的策略接口，
适用于 GridOptimizer 等轻量级回测场景。

用法:
```python
from backtest.strategy_base import StrategyBase, StrategySignal

class MyStrategy(StrategyBase):
    def on_bar(self, bar):
        if bar['close'] > bar['open']:
            return self.generate_signal('buy', bar['close'], bar.get('time', ''))
        return None
```
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import uuid


@dataclass
class IndicatorBar:
    """用于指标计算的K线数据结构（轻量级版本）"""
    datetime: Any
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class StrategySignal:
    """交易信号"""
    signal_type: str          # 'buy', 'sell', 'short', 'cover', 'close'
    price: float              # 信号价格
    timestamp: str            # 时间戳
    stop_loss: Optional[float] = None   # 止损价
    take_profit: Optional[float] = None  # 止盈价
    quantity: int = 1         # 数量（手）


@dataclass
class TradeResult:
    """交易结果（单笔）"""
    trade_id: str
    entry_time: str
    exit_time: str
    direction: str           # 'long' or 'short'
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float = 0
    pnl_pct: float = 0
    exit_reason: str = ''    # 'signal', 'stop_loss', 'take_profit'

    def __post_init__(self):
        if self.pnl == 0:
            if self.direction == 'long':
                self.pnl = (self.exit_price - self.entry_price) * self.quantity
            else:
                self.pnl = (self.entry_price - self.exit_price) * self.quantity
        if self.pnl_pct == 0 and self.entry_price > 0:
            price_diff = self.exit_price - self.entry_price
            sign = 1 if self.direction == 'long' else -1
            self.pnl_pct = sign * (abs(price_diff) / self.entry_price) * 100


class StrategyBase:
    """
    策略基类 - 轻量级策略接口

    与 AlphaStrategy 不同，这个基类操作简单的 dict 结构 (bar['open', 'high', 'low', 'close', 'time'])
    而非 BarData 对象，适合参数优化和多策略对比等轻量级场景。
    """

    def __init__(self, params: Dict[str, Any] = None):
        """
        Args:
            params: 策略参数字典，如 {'fast_period': 12, 'slow_period': 26}
        """
        self.params: Dict[str, Any] = params or {}
        self.signals: List[StrategySignal] = []
        self.position: Optional[str] = None   # 'long', 'short', or None
        self.entry_price: Optional[float] = None
        self.entry_time: Optional[str] = None
        self.quantity: int = 1
        self.stop_loss: Optional[float] = None
        self.take_profit: Optional[float] = None

    def generate_signal(
        self,
        signal_type: str,
        price: float,
        timestamp: str,
        stop_loss: float = None,
        take_profit: float = None,
        quantity: int = 1
    ) -> StrategySignal:
        """
        生成交易信号

        Args:
            signal_type: 信号类型 ('buy', 'sell', 'short', 'cover', 'close')
            price: 信号价格
            timestamp: 时间戳
            stop_loss: 止损价
            take_profit: 止盈价
            quantity: 数量

        Returns:
            StrategySignal 对象
        """
        signal = StrategySignal(
            signal_type=signal_type,
            price=price,
            timestamp=timestamp,
            stop_loss=stop_loss,
            take_profit=take_profit,
            quantity=quantity
        )
        self.signals.append(signal)
        return signal

    def on_bar(self, bar: Dict[str, Any]) -> Optional[StrategySignal]:
        """
        K线数据回调 - 子类实现具体策略逻辑

        Args:
            bar: K线数据 dict，包含 'time', 'open', 'high', 'low', 'close', 'volume'

        Returns:
            StrategySignal 或 None
        """
        raise NotImplementedError("子策略必须实现 on_bar 方法")

    def reset(self):
        """重置策略状态"""
        self.position = None
        self.entry_price = None
        self.entry_time = None
        self.stop_loss = None
        self.take_profit = None
        self.signals = []
        self.quantity = 1

    def get_params(self) -> Dict[str, Any]:
        """获取策略参数"""
        return self.params.copy()


# ==================== 指标计算器和持仓管理（从原文件保留） ====================
# 这些类在 native_engine 回测中仍然使用

class StrategyIndicator:
    """策略技术指标计算器（轻量级版本，用于dict数据）"""

    def __init__(self):
        self.bars: Dict[str, List] = {}
        self.ema_cache: Dict[str, Dict[int, float]] = {}
        self.macd_cache: Dict = {}

    def update(self, bar: Dict[str, Any], vt_symbol: str = "default") -> None:
        if vt_symbol not in self.bars:
            self.bars[vt_symbol] = []
        self.bars[vt_symbol].append(bar)

    def ema(self, vt_symbol: str = "default", period: int = 20) -> float:
        bars = self.bars.get(vt_symbol, [])
        if len(bars) < period:
            return bars[-1]['close'] if bars else 0
        prices = [b['close'] for b in bars[-period:]]
        k = 2 / (period + 1)
        if vt_symbol not in self.ema_cache:
            self.ema_cache[vt_symbol] = {}
        if period not in self.ema_cache[vt_symbol]:
            self.ema_cache[vt_symbol][period] = sum(prices[:period]) / period
            return self.ema_cache[vt_symbol][period]
        ema = self.ema_cache[vt_symbol][period]
        ema = prices[-1] * k + ema * (1 - k)
        self.ema_cache[vt_symbol][period] = ema
        return ema

    def macd(self, vt_symbol: str = "default", fast: int = 12, slow: int = 26, signal: int = 9):
        fast_ema = self.ema(vt_symbol, fast)
        slow_ema = self.ema(vt_symbol, slow)
        dif = fast_ema - slow_ema
        key = (fast, slow, signal)
        if vt_symbol not in self.macd_cache:
            self.macd_cache[vt_symbol] = {}
        if key not in self.macd_cache[vt_symbol]:
            self.macd_cache[vt_symbol][key] = dif
        dea = self.macd_cache[vt_symbol][key]
        dea = dif * (2 / (signal + 1)) + dea * (1 - 2 / (signal + 1))
        self.macd_cache[vt_symbol][key] = dea
        hist = (dif - dea) * 2
        return dif, dea, hist

    def rsi(self, vt_symbol: str = "default", period: int = 14) -> float:
        bars = self.bars.get(vt_symbol, [])
        if len(bars) < period + 1:
            return 50
        gains, losses = [], []
        for i in range(1, len(bars)):
            ch = bars[i]['close'] - bars[i-1]['close']
            gains.append(ch if ch > 0 else 0)
            losses.append(abs(ch) if ch < 0 else 0)
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def bollinger(self, vt_symbol: str = "default", period: int = 20, nbdev: int = 2) -> Tuple[float, float, float]:
        """布林带指标

        Returns:
            (upper_band, middle_band, lower_band)
        """
        bars = self.bars.get(vt_symbol, [])
        if len(bars) < period:
            last_close = bars[-1]['close'] if bars else 0
            return last_close, last_close, last_close
        closes = [b['close'] for b in bars[-period:]]
        middle = sum(closes) / period
        variance = sum((c - middle) ** 2 for c in closes) / period
        std = variance ** 0.5
        upper = middle + nbdev * std
        lower = middle - nbdev * std
        return upper, middle, lower

    def atr(self, vt_symbol: str = "default", period: int = 14) -> float:
        """平均真实波幅 (Average True Range)"""
        bars = self.bars.get(vt_symbol, [])
        if len(bars) < period + 1:
            return 0.0
        tr_list = []
        for i in range(1, len(bars)):
            high = bars[i].get('high', bars[i].get('close', 0))
            low = bars[i].get('low', bars[i].get('close', 0))
            prev_close = bars[i - 1].get('close', 0)
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            tr_list.append(tr)
        if len(tr_list) < period:
            return sum(tr_list) / len(tr_list) if tr_list else 0.0
        return sum(tr_list[-period:]) / period

    def kdj(self, vt_symbol: str = "default", n: int = 9, m1: int = 3, m2: int = 3):
        """KDJ随机指标

        Returns:
            (k_value, d_value, j_value)
        """
        bars = self.bars.get(vt_symbol, [])
        if len(bars) < n:
            return 50.0, 50.0, 50.0
        k_vals, d_vals = [], []
        for i in range(n - 1, len(bars)):
            high_list = [b.get('high', b.get('close', 0)) for b in bars[i - n + 1:i + 1]]
            low_list = [b.get('low', b.get('close', 0)) for b in bars[i - n + 1:i + 1]]
            high = max(high_list)
            low = min(low_list)
            close = bars[i].get('close', 0)
            if high == low:
                rsv = 50
            else:
                rsv = (close - low) / (high - low) * 100
            k_vals.append(rsv)
            d_vals.append(rsv)
        if len(k_vals) < m1:
            k = d = rsv = k_vals[-1] if k_vals else 50
        else:
            k = sum(k_vals[-m1:]) / m1
            d = sum(d_vals[-m1:]) / m1
        j = 3 * k - 2 * d
        return k, d, j


class PositionManager:
    """持仓管理器（轻量级版本）"""

    def __init__(self, strategy=None):
        self.strategy = strategy
        self.long_positions: Dict[str, float] = {}
        self.short_positions: Dict[str, float] = {}

    def update_position(self, trade) -> None:
        pass

    def get_net_pos(self, vt_symbol: str = "default") -> float:
        return self.long_positions.get(vt_symbol, 0) - self.short_positions.get(vt_symbol, 0)

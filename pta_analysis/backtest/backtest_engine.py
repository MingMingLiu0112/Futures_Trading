#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
轻量级回测引擎

与 native_engine.py 的专业回测引擎不同，这个引擎专注于：
1. 与 web_app TradingSystem 集成
2. 支持 StrategyBase 轻量级策略
3. 支持止损/止盈
4. 输出标准化的回测结果

用法:
```python
from backtest.backtest_engine import BacktestEngine
from backtest.strategy_base import StrategyBase

class MyStrategy(StrategyBase):
    def on_bar(self, bar):
        if bar['close'] > bar['open']:
            return self.generate_signal('buy', bar['close'], bar.get('time', ''))
        return None

engine = BacktestEngine(initial_balance=100000, commission_rate=0.0001)
result = engine.run(MyStrategy(), kline_data)
```
"""

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type
import copy

from .strategy_base import StrategyBase, TradeResult
from .performance_metrics import calculate_performance_metrics


@dataclass
class BacktestEngine:
    """
    轻量级回测引擎

    Attributes:
        initial_balance: 初始资金
        commission_rate: 手续费率（按成交金额）
        risk_per_trade: 每笔交易风险比例（用于仓位计算）
    """

    initial_balance: float = 100000.0
    commission_rate: float = 0.0001
    risk_per_trade: float = 0.01
    slippage: float = 0.0   # 滑点（按价格比例，如 0.0005 = 5跳/万分之五）

    def __post_init__(self):
        self.balance: float = self.initial_balance
        self.trades: List[Dict[str, Any]] = []
        self.equity_curve: List[Dict[str, Any]] = []
        self.position: Optional[str] = None  # 'long', 'short'
        self.entry_price: float = 0
        self.entry_time: str = ''
        self.quantity: int = 1
        self.stop_loss: float = 0
        self.take_profit: float = 0
        self.strategy: Optional[StrategyBase] = None
        self.trade_id_counter: int = 0
        self.entry_bar_index: int = -1   # 记录入场K线索引，供前端图表使用

    def reset(self):
        """重置引擎状态"""
        self.balance = self.initial_balance
        self.trades = []
        self.equity_curve = []
        self.position = None
        self.entry_price = 0
        self.entry_time = ''
        self.quantity = 1
        self.stop_loss = 0
        self.take_profit = 0
        self.trade_id_counter = 0
        self.entry_bar_index = -1

    def run(
        self,
        strategy: StrategyBase,
        data: List[Dict[str, Any]],
        initial_balance: float = None
    ) -> Dict[str, Any]:
        """
        运行回测

        Args:
            strategy: 策略实例（StrategyBase 子类）
            data: K线数据列表，每项包含 time, open, high, low, close, volume
            initial_balance: 可覆盖初始资金

        Returns:
            包含 trades, equity_curve, statistics 的字典
        """
        if initial_balance is not None:
            self.initial_balance = initial_balance
        self.reset()
        self.strategy = copy.deepcopy(strategy)

        # 生成权益曲线时间索引
        time_index: Dict[str, int] = {}
        for i, bar in enumerate(data):
            ts = bar.get('time', f'bar_{i}')
            time_index[ts] = i

        # 逐根K线回测
        for i, bar in enumerate(data):
            self._process_bar(bar, data, i)

        # 平仓（如果有持仓）
        if self.position is not None and data:
            last_bar = data[-1]
            self._close_position(last_bar, 'end_of_data', len(data) - 1)

        # 生成权益曲线
        self._generate_equity_curve(data)

        # 计算统计指标
        statistics = calculate_performance_metrics(
            self.trades,
            self.equity_curve,
            self.initial_balance
        )
        statistics['initial_balance'] = self.initial_balance
        statistics['final_balance'] = self.balance

        return {
            'success': True,
            'trades': self.trades,
            'equity_curve': self.equity_curve,
            'statistics': statistics,
            'final_balance': self.balance,
        }

    def _process_bar(
        self,
        bar: Dict[str, Any],
        data: List[Dict[str, Any]],
        index: int
    ):
        """处理单根K线"""
        ts = bar.get('time', f'bar_{index}')
        close = bar.get('close', 0)
        high = bar.get('high', 0)
        low = bar.get('low', 0)

        # ========== 持仓检查：止损/止盈 ==========
        if self.position == 'long':
            # 止损
            if self.stop_loss > 0 and low <= self.stop_loss:
                self._close_position(bar, 'stop_loss', index)
                self.balance += self._calc_pnl('long', self.stop_loss, self.quantity)
                return
            # 止盈
            if self.take_profit > 0 and high >= self.take_profit:
                self._close_position(bar, 'take_profit', index)
                return
        elif self.position == 'short':
            if self.stop_loss > 0 and high >= self.stop_loss:
                self._close_position(bar, 'stop_loss', index)
                return
            if self.take_profit > 0 and low <= self.take_profit:
                self._close_position(bar, 'take_profit', index)
                return

        # ========== 调用策略 ==========
        signal = self.strategy.on_bar(bar)
        if signal is None:
            return

        signal_type = signal.signal_type

        # ========== 执行信号 ==========
        if signal_type in ('buy', 'long'):
            if self.position is None:
                self._open_position('long', signal, bar, index)
            elif self.position == 'short':
                # 平空再开多
                self._close_position(bar, 'reverse', index)
                self._open_position('long', signal, bar, index)

        elif signal_type in ('sell', 'close'):
            if self.position in ('long', 'short'):
                self._close_position(bar, 'signal', index)

        elif signal_type in ('short', 'sell_short'):
            if self.position is None:
                self._open_position('short', signal, bar, index)
            elif self.position == 'long':
                self._close_position(bar, 'reverse', index)
                self._open_position('short', signal, bar, index)

        elif signal_type == 'cover':
            if self.position in ('long', 'short'):
                self._close_position(bar, 'signal', index)

    def _open_position(
        self,
        direction: str,
        signal,
        bar: Dict[str, Any],
        bar_index: int
    ):
        """开仓（考虑滑点）"""
        # 开仓价：做多时高，卖空时低（滑点使开仓成本更差）
        if direction == 'long':
            slippage_price = signal.price * (1 + self.slippage)
        else:
            slippage_price = signal.price * (1 - self.slippage)
        price = slippage_price
        ts = bar.get('time', '')
        quantity = signal.quantity if signal.quantity else 1

        # 计算手续费（计入成本）
        commission = price * quantity * self.commission_rate
        self.balance -= commission

        self.position = direction
        self.entry_price = price
        self.entry_time = ts
        self.quantity = quantity
        self.stop_loss = signal.stop_loss or 0
        self.take_profit = signal.take_profit or 0
        self.entry_bar_index = bar_index  # 记录入场K线索引

    def _close_position(
        self,
        bar: Dict[str, Any],
        reason: str,
        bar_index: int = -1
    ):
        """平仓（考虑滑点：平多时低，平空时高）"""
        if self.position is None:
            return

        # 平仓价：平多时低（更差价格），平空时高（更差价格）
        raw_close = bar.get('close', self.entry_price)
        if self.position == 'long':
            price = raw_close * (1 - self.slippage)
        else:
            price = raw_close * (1 + self.slippage)
        ts = bar.get('time', '')

        # 计算盈亏
        pnl = self._calc_pnl(self.position, price, self.quantity)

        # 扣除手续费
        commission = price * self.quantity * self.commission_rate

        trade_id = f"trade_{self.trade_id_counter}"
        self.trade_id_counter += 1

        trade = {
            'trade_id': trade_id,
            'direction': self.position,
            'entry_time': self.entry_time,
            'exit_time': ts,
            'entry_price': self.entry_price,
            'exit_price': price,
            'quantity': self.quantity,
            'pnl': pnl - commission,
            'pnl_pct': (abs(price - self.entry_price) / self.entry_price * 100
                        if self.entry_price > 0 else 0),
            'exit_reason': reason,
            'stop_loss': self.stop_loss,               # 入场时设置的止损价
            'take_profit': self.take_profit,           # 入场时设置的止盈价
            'commission': commission,
            'entry_bar_index': self.entry_bar_index,   # 供前端图表定位入场点
            'exit_bar_index': bar_index,               # 供前端图表定位出场点
        }
        self.trades.append(trade)

        self.balance += pnl - commission

        # 重置持仓
        self.position = None
        self.entry_price = 0
        self.entry_time = ''
        self.quantity = 1
        self.stop_loss = 0
        self.take_profit = 0
        self.entry_bar_index = -1

    def _calc_pnl(self, direction: str, price: float, quantity: float) -> float:
        """计算盈亏"""
        if direction == 'long':
            return (price - self.entry_price) * quantity
        else:  # short
            return (self.entry_price - price) * quantity

    def _generate_equity_curve(self, data: List[Dict[str, Any]]):
        """生成权益曲线"""
        self.equity_curve = []
        running_balance = self.initial_balance

        # 按时间排序的交易
        time_to_trade: Dict[str, Dict] = {}
        for trade in self.trades:
            time_to_trade[trade['exit_time']] = trade

        for bar in data:
            ts = bar.get('time', '')
            if ts in time_to_trade:
                trade = time_to_trade[ts]
                running_balance += trade['pnl']
            self.equity_curve.append({
                'time': ts,
                'balance': round(running_balance, 2)
            })

    def _calculate_position_size(
        self,
        entry_price: float,
        stop_loss: float
    ) -> int:
        """
        根据风险金额计算仓位大小

        风险金额 = 账户余额 * risk_per_trade
        风险金额 = (入场价 - 止损价) * 仓位
        """
        risk_amount = self.balance * self.risk_per_trade
        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit <= 0:
            return 1
        size = int(risk_amount / risk_per_unit)
        return max(size, 1)

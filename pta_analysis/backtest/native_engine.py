#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VNpy原生回测引擎
================

对照vnpy官方alpha.backtesting实现,
直接使用vnpy.trader组件,避免alpha模块的依赖问题。

用法:

```python
from backtest import BacktestingEngine, AlphaStrategy, df_to_bars
from vnpy.trader.constant import Interval

engine = BacktestingEngine()
engine.set_parameters(
    vt_symbols=["TA.CZCE"],
    interval=Interval.MINUTE,
    start=datetime(2024, 1, 1),
    end=datetime(2024, 12, 31),
    capital=1_000_000,
    risk_free=0.0,
    annual_days=240,
)
engine.add_contract_setting("TA.CZCE", size=10, pricetick=2, long_rate=0.10, short_rate=0.10)
engine.load_data(bars)
engine.add_strategy(MacdStrategy, setting={})
engine.run_backtesting()
df = engine.calculate_result()
stats = engine.calculate_statistics()
engine.show_chart()
```

"""

from collections import defaultdict
from copy import copy
from datetime import date, datetime
from typing import cast, Dict, List, Optional, Tuple
import traceback

import numpy as np
import polars as pl
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from vnpy.trader.constant import Direction, Offset, Interval, Status
from vnpy.trader.object import BarData, TradeData, OrderData
from vnpy.trader.utility import round_to, extract_vt_symbol


# ==================== 合约日结算 ====================

class ContractDailyResult:
    """合约每日盈亏"""

    def __init__(self, result_date: date, close_price: float) -> None:
        self.date: date = result_date
        self.close_price: float = close_price
        self.pre_close: float = 0

        self.trades: List[TradeData] = []
        self.trade_count: int = 0

        self.start_pos: float = 0
        self.end_pos: float = 0

        self.turnover: float = 0
        self.commission: float = 0

        self.trading_pnl: float = 0
        self.holding_pnl: float = 0
        self.total_pnl: float = 0
        self.net_pnl: float = 0

    def add_trade(self, trade: TradeData) -> None:
        self.trades.append(trade)

    def calculate_pnl(
        self,
        pre_close: float,
        start_pos: float,
        size: float,
        long_rate: float,
        short_rate: float
    ) -> None:
        if pre_close:
            self.pre_close = pre_close

        self.start_pos = start_pos
        self.end_pos = start_pos

        self.holding_pnl = self.start_pos * (self.close_price - self.pre_close) * size

        self.trade_count = len(self.trades)

        for trade in self.trades:
            if trade.direction == Direction.LONG:
                pos_change: float = trade.volume
                rate: float = long_rate
            else:
                pos_change = -trade.volume
                rate = short_rate

            self.end_pos += pos_change

            turnover: float = trade.volume * size * trade.price

            self.trading_pnl += pos_change * (self.close_price - trade.price) * size
            self.turnover += turnover
            self.commission += turnover * rate

        self.total_pnl = self.trading_pnl + self.holding_pnl
        self.net_pnl = self.total_pnl - self.commission

    def update_close_price(self, close_price: float) -> None:
        self.close_price = close_price


class PortfolioDailyResult:
    """组合每日盈亏"""

    def __init__(self, result_date: date, close_prices: Dict[str, float]) -> None:
        self.date: date = result_date
        self.close_prices: Dict[str, float] = close_prices
        self.pre_closes: Dict[str, float] = {}
        self.start_poses: Dict[str, float] = {}
        self.end_poses: Dict[str, float] = {}

        self.contract_results: Dict[str, ContractDailyResult] = {}
        for vt_symbol, close_price in close_prices.items():
            self.contract_results[vt_symbol] = ContractDailyResult(result_date, close_price)

        self.trade_count: int = 0
        self.turnover: float = 0
        self.commission: float = 0
        self.trading_pnl: float = 0
        self.holding_pnl: float = 0
        self.total_pnl: float = 0
        self.net_pnl: float = 0

    def add_trade(self, trade: TradeData) -> None:
        contract_result: ContractDailyResult = self.contract_results[trade.vt_symbol]
        contract_result.add_trade(trade)

    def calculate_pnl(
        self,
        pre_closes: Dict[str, float],
        start_poses: Dict[str, float],
        sizes: Dict[str, float],
        long_rates: Dict[str, float],
        short_rates: Dict[str, float]
    ) -> None:
        self.pre_closes = pre_closes
        self.start_poses = start_poses

        for vt_symbol, contract_result in self.contract_results.items():
            contract_result.calculate_pnl(
                pre_closes.get(vt_symbol, 0),
                start_poses.get(vt_symbol, 0),
                sizes[vt_symbol],
                long_rates[vt_symbol],
                short_rates[vt_symbol]
            )

            self.trade_count += contract_result.trade_count
            self.turnover += contract_result.turnover
            self.commission += contract_result.commission
            self.trading_pnl += contract_result.trading_pnl
            self.holding_pnl += contract_result.holding_pnl
            self.total_pnl += contract_result.total_pnl
            self.net_pnl += contract_result.net_pnl

            self.end_poses[vt_symbol] = contract_result.end_pos

    def update_close_prices(self, close_prices: Dict[str, float]) -> None:
        self.close_prices.update(close_prices)
        for vt_symbol, close_price in close_prices.items():
            contract_result: Optional[ContractDailyResult] = self.contract_results.get(vt_symbol)
            if contract_result:
                contract_result.update_close_price(close_price)
            else:
                self.contract_results[vt_symbol] = ContractDailyResult(self.date, close_price)


# ==================== 回测引擎 ====================

class BacktestingEngine:
    """VNpy原生回测引擎"""

    gateway_name: str = "BACKTESTING"

    def __init__(self) -> None:
        self.vt_symbols: List[str] = []
        self.start: datetime
        self.end: datetime

        self.long_rates: Dict[str, float] = {}
        self.short_rates: Dict[str, float] = {}
        self.commission_rates: Dict[str, float] = {}
        self.margin_rates: Dict[str, float] = {}
        self.sizes: Dict[str, float] = {}
        self.priceticks: Dict[str, float] = {}

        self.capital: float = 0
        self.risk_free: float = 0
        self.annual_days: int = 0

        self.strategy_class: type
        self.strategy = None
        self.bars: Dict[str, BarData] = {}
        self.datetime: Optional[datetime] = None

        self.interval: Interval
        self.history_data: Dict[Tuple, BarData] = {}
        self.dts: set = set()

        self.limit_order_count: int = 0
        self.limit_orders: Dict[str, OrderData] = {}
        self.active_limit_orders: Dict[str, OrderData] = {}

        self.trade_count: int = 0
        self.trades: Dict[str, TradeData] = {}

        self.logs: List[str] = []

        self.daily_results: Dict[date, PortfolioDailyResult] = {}
        self.daily_df: pl.DataFrame

        self.pre_closes: defaultdict = defaultdict(float)
        self.cash: float = 0

    def set_parameters(
        self,
        vt_symbols: List[str],
        interval: Interval,
        start: datetime,
        end: datetime,
        capital: float = 1_000_000,
        risk_free: float = 0,
        annual_days: int = 240
    ) -> None:
        """设置回测参数"""
        self.vt_symbols = vt_symbols
        self.interval = interval
        self.start = start
        self.end = end
        self.capital = capital
        self.risk_free = risk_free
        self.annual_days = annual_days
        self.cash = capital

    def add_contract_setting(
        self,
        vt_symbol: str,
        size: float = 10,
        pricetick: float = 1,
        long_rate: float = 0.00005,
        short_rate: float = 0.00005,
        commission_rate: float = 0.00005,
        margin_rate: float = 0.10
    ) -> None:
        """添加合约配置"""
        self.sizes[vt_symbol] = size
        self.priceticks[vt_symbol] = pricetick
        self.long_rates[vt_symbol] = long_rate
        self.short_rates[vt_symbol] = short_rate
        self.commission_rates[vt_symbol] = commission_rate
        self.margin_rates[vt_symbol] = margin_rate

    def load_data(self, bars: List[BarData]) -> None:
        """加载历史K线数据"""
        self.history_data.clear()
        self.dts.clear()

        for bar in bars:
            self.dts.add(bar.datetime)
            self.history_data[(bar.datetime, bar.vt_symbol)] = bar

        print(f"加载了 {len(bars)} 根K线")

    def add_strategy(self, strategy_class: type, setting: dict) -> None:
        """添加策略"""
        self.strategy_class = strategy_class
        self.strategy = strategy_class(
            self, strategy_class.__name__, copy(self.vt_symbols), setting
        )

    def run_backtesting(self) -> None:
        """运行回测"""
        self.strategy.on_init()
        print("策略初始化完成")

        dts: list = list(self.dts)
        dts.sort()

        print("开始回放历史数据")
        for dt in dts:
            try:
                self.new_bars(dt)
            except Exception:
                print("触发异常，回测终止")
                print(traceback.format_exc())
                return

        print(f"历史数据回放结束，共 {len(self.trades)} 笔成交")

    def calculate_result(self) -> Optional[pl.DataFrame]:
        """计算每日盈亏"""
        if not self.trades:
            print("成交记录为空，无法计算")
            return None

        for trade in self.trades.values():
            if not trade.datetime:
                continue

            d: date = trade.datetime.date()
            daily_result: PortfolioDailyResult = self.daily_results[d]
            daily_result.add_trade(trade)

        pre_closes: Dict[str, float] = {}
        start_poses: Dict[str, float] = {}

        for daily_result in self.daily_results.values():
            daily_result.calculate_pnl(
                pre_closes,
                start_poses,
                self.sizes,
                self.long_rates,
                self.short_rates
            )
            pre_closes = daily_result.close_prices
            start_poses = daily_result.end_poses

        results: dict = defaultdict(list)

        for daily_result in self.daily_results.values():
            fields: list = [
                "date", "trade_count", "turnover",
                "commission", "trading_pnl",
                "holding_pnl", "total_pnl", "net_pnl"
            ]
            for key in fields:
                value = getattr(daily_result, key)
                results[key].append(value)

        if results:
            self.daily_df = pl.DataFrame([
                pl.Series("date", results["date"], dtype=pl.Date),
                pl.Series("trade_count", results["trade_count"], dtype=pl.Int64),
                pl.Series("turnover", results["turnover"], dtype=pl.Float64),
                pl.Series("commission", results["commission"], dtype=pl.Float64),
                pl.Series("trading_pnl", results["trading_pnl"], dtype=pl.Float64),
                pl.Series("holding_pnl", results["holding_pnl"], dtype=pl.Float64),
                pl.Series("total_pnl", results["total_pnl"], dtype=pl.Float64),
                pl.Series("net_pnl", results["net_pnl"], dtype=pl.Float64),
            ])

        return self.daily_df

    def calculate_statistics(self) -> dict:
        """计算策略统计指标"""
        df: pl.DataFrame = self.daily_df

        if df is None or df.is_empty():
            return {}

        # 计算基础指标
        df = df.with_columns(
            balance=(pl.col("net_pnl").cum_sum() + self.capital)
        ).with_columns(
            pl.col("balance").pct_change().fill_null(0).alias("return"),
            highlevel=pl.col("balance").cum_max()
        ).with_columns(
            drawdown=pl.col("balance") - pl.col("highlevel"),
            ddpercent=(pl.col("balance") / pl.col("highlevel") - 1) * 100
        )

        # 基本统计
        start_date = str(df["date"][0])
        end_date = str(df["date"][-1])
        total_days = len(df)
        profit_days = int(df.filter(pl.col("net_pnl") > 0).height)
        loss_days = int(df.filter(pl.col("net_pnl") < 0).height)

        end_balance = float(df["balance"][-1])
        max_drawdown = float(df["drawdown"].min())
        max_ddpercent = float(df["ddpercent"].min())

        max_drawdown_end_idx = int(df["drawdown"].arg_min())
        max_drawdown_end = df["date"][max_drawdown_end_idx]

        if isinstance(max_drawdown_end, date):
            max_drawdown_start_idx = int(df.slice(0, max_drawdown_end_idx + 1)["balance"].arg_max())
            max_drawdown_start = df["date"][max_drawdown_start_idx]
            max_drawdown_duration = (max_drawdown_end - max_drawdown_start).days
        else:
            max_drawdown_duration = 0

        total_net_pnl = float(df["net_pnl"].sum())
        daily_net_pnl = total_net_pnl / total_days

        total_commission = float(df["commission"].sum())
        daily_commission = total_commission / total_days

        total_turnover = float(df["turnover"].sum())
        daily_turnover = total_turnover / total_days

        total_trade_count = int(df["trade_count"].sum())
        daily_trade_count = total_trade_count / total_days

        total_return = (end_balance / self.capital - 1) * 100
        annual_return = total_return / total_days * self.annual_days
        daily_return_col = df["return"].fill_null(0)
        daily_return = float(daily_return_col.mean()) * 100
        
        std_val = daily_return_col.std()
        return_std = float(std_val) * 100 if std_val is not None else 0

        if return_std:
            daily_risk_free = self.risk_free / np.sqrt(self.annual_days)
            sharpe_ratio = (daily_return - daily_risk_free) / return_std * np.sqrt(self.annual_days)
        else:
            sharpe_ratio = 0

        return_drawdown_ratio = -total_net_pnl / max_drawdown if max_drawdown else 0

        # 输出结果
        print("-" * 40)
        print("回测统计")
        print("-" * 40)
        print(f"首个交易日：  {start_date}")
        print(f"最后交易日：  {end_date}")
        print(f"总交易日：  {total_days}")
        print(f"盈利交易日：  {profit_days}")
        print(f"亏损交易日：  {loss_days}")
        print(f"起始资金：  {self.capital:,.2f}")
        print(f"结束资金：  {end_balance:,.2f}")
        print(f"总收益率：  {total_return:,.2f}%")
        print(f"年化收益：  {annual_return:,.2f}%")
        print(f"最大回撤:   {max_drawdown:,.2f}")
        print(f"百分比最大回撤: {max_ddpercent:,.2f}%")
        print(f"最长回撤天数:   {max_drawdown_duration}")
        print(f"总盈亏：  {total_net_pnl:,.2f}")
        print(f"总手续费：  {total_commission:,.2f}")
        print(f"总成交金额：  {total_turnover:,.2f}")
        print(f"总成交笔数：  {total_trade_count}")
        print(f"日均盈亏：  {daily_net_pnl:,.2f}")
        print(f"日均手续费：  {daily_commission:,.2f}")
        print(f"日均成交金额：  {daily_turnover:,.2f}")
        print(f"日均成交笔数：  {daily_trade_count:.1f}")
        print(f"日均收益率：  {daily_return:,.2f}%")
        print(f"收益标准差：  {return_std:,.2f}%")
        print(f"夏普比率：  {sharpe_ratio:,.2f}")
        print(f"收益回撤比：  {return_drawdown_ratio:,.2f}")
        print("-" * 40)

        statistics: dict = {
            "start_date": start_date,
            "end_date": end_date,
            "total_days": total_days,
            "profit_days": profit_days,
            "loss_days": loss_days,
            "capital": self.capital,
            "end_balance": end_balance,
            "max_drawdown": max_drawdown,
            "max_ddpercent": max_ddpercent,
            "max_drawdown_duration": max_drawdown_duration,
            "total_net_pnl": total_net_pnl,
            "daily_net_pnl": daily_net_pnl,
            "total_commission": total_commission,
            "daily_commission": daily_commission,
            "total_turnover": total_turnover,
            "daily_turnover": daily_turnover,
            "total_trade_count": total_trade_count,
            "daily_trade_count": daily_trade_count,
            "total_return": total_return,
            "annual_return": annual_return,
            "daily_return": daily_return,
            "return_std": return_std,
            "sharpe_ratio": sharpe_ratio,
            "return_drawdown_ratio": return_drawdown_ratio,
        }

        # 过滤极值
        for key, value in statistics.items():
            if value in (np.inf, -np.inf):
                value = 0
            statistics[key] = np.nan_to_num(value)

        return statistics

    def show_chart(self) -> None:
        """显示图表"""
        df: pl.DataFrame = self.daily_df

        if df is None or df.is_empty():
            print("没有数据")
            return

        fig = make_subplots(
            rows=4,
            cols=1,
            subplot_titles=["Balance", "Drawdown", "Daily Pnl", "Pnl Distribution"],
            vertical_spacing=0.06
        )

        balance_line = go.Scatter(
            x=df["date"], y=df["balance"],
            mode="lines", name="Balance"
        )
        drawdown_scatter = go.Scatter(
            x=df["date"], y=df["drawdown"],
            fillcolor="red", fill='tozeroy',
            mode="lines", name="Drawdown"
        )
        pnl_bar = go.Bar(y=df["net_pnl"], name="Daily Pnl")
        pnl_histogram = go.Histogram(x=df["net_pnl"], nbinsx=100, name="Days")

        fig.add_trace(balance_line, row=1, col=1)
        fig.add_trace(drawdown_scatter, row=2, col=1)
        fig.add_trace(pnl_bar, row=3, col=1)
        fig.add_trace(pnl_histogram, row=4, col=1)

        fig.update_layout(height=1000, width=1000)
        fig.show()

    def update_daily_close(self, bars: Dict[str, BarData], dt: datetime) -> None:
        """更新日线收盘价"""
        d: date = dt.date()

        close_prices: Dict[str, float] = {}
        for bar in bars.values():
            if not bar.close_price:
                close_prices[bar.vt_symbol] = self.pre_closes[bar.vt_symbol]
            else:
                close_prices[bar.vt_symbol] = bar.close_price

        daily_result: Optional[PortfolioDailyResult] = self.daily_results.get(d)

        if daily_result:
            daily_result.update_close_prices(close_prices)
        else:
            self.daily_results[d] = PortfolioDailyResult(d, close_prices)

    def new_bars(self, dt: datetime) -> None:
        """推送新的K线"""
        self.datetime = dt

        bars: Dict[str, BarData] = {}
        for vt_symbol in self.vt_symbols:
            last_bar = self.bars.get(vt_symbol)
            if last_bar:
                if last_bar.close_price:
                    self.pre_closes[vt_symbol] = last_bar.close_price

            bar: Optional[BarData] = self.history_data.get((dt, vt_symbol))

            if bar:
                self.bars[vt_symbol] = bar
                bars[vt_symbol] = bar
            elif vt_symbol in self.bars:
                old_bar: BarData = self.bars[vt_symbol]

                fill_bar: BarData = BarData(
                    symbol=old_bar.symbol,
                    exchange=old_bar.exchange,
                    datetime=dt,
                    open_price=old_bar.close_price,
                    high_price=old_bar.close_price,
                    low_price=old_bar.close_price,
                    close_price=old_bar.close_price,
                    gateway_name=old_bar.gateway_name
                )
                self.bars[vt_symbol] = fill_bar

        self.cross_order()
        self.strategy.on_bars(bars)

        self.update_daily_close(self.bars, dt)

    def cross_order(self) -> None:
        """订单撮合"""
        for order in list(self.active_limit_orders.values()):
            bar: BarData = self.bars[order.vt_symbol]

            long_cross_price: float = bar.low_price
            short_cross_price: float = bar.high_price
            long_best_price: float = bar.open_price
            short_best_price: float = bar.open_price

            if order.status == Status.SUBMITTING:
                order.status = Status.NOTTRADED
                self.strategy.update_order(order)

            pricetick: float = self.priceticks[order.vt_symbol]
            pre_close: float = self.pre_closes.get(order.vt_symbol, 0)

            limit_up: float = round_to(pre_close * 1.1, pricetick)
            limit_down: float = round_to(pre_close * 0.9, pricetick)

            long_cross: bool = (
                order.direction == Direction.LONG
                and order.price >= long_cross_price
                and long_cross_price > 0
                and bar.low_price < limit_up
            )

            short_cross: bool = (
                order.direction == Direction.SHORT
                and order.price <= short_cross_price
                and short_cross_price > 0
                and bar.high_price > limit_down
            )

            if not long_cross and not short_cross:
                continue

            order.traded = order.volume
            order.status = Status.ALLTRADED
            self.strategy.update_order(order)

            if order.vt_orderid in self.active_limit_orders:
                self.active_limit_orders.pop(order.vt_orderid)

            self.trade_count += 1

            if long_cross:
                trade_price = min(order.price, long_best_price)
            else:
                trade_price = max(order.price, short_best_price)

            trade: TradeData = TradeData(
                symbol=order.symbol,
                exchange=order.exchange,
                orderid=order.orderid,
                tradeid=str(self.trade_count),
                direction=order.direction,
                offset=order.offset,
                price=trade_price,
                volume=order.volume,
                datetime=self.datetime,
                gateway_name=self.gateway_name,
            )

            size: float = self.sizes[trade.vt_symbol]
            trade_turnover: float = trade.price * trade.volume * size

            if trade.direction == Direction.LONG:
                trade_commission: float = trade_turnover * self.long_rates[trade.vt_symbol]
            else:
                trade_commission = trade_turnover * self.short_rates[trade.vt_symbol]

            if trade.direction == Direction.LONG:
                self.cash -= trade_turnover
            else:
                self.cash += trade_turnover

            self.cash -= trade_commission

            self.strategy.update_trade(trade)
            self.trades[trade.vt_tradeid] = trade

    def send_order(
        self,
        strategy,
        vt_symbol: str,
        direction: Direction,
        offset: Offset,
        price: float,
        volume: float,
    ) -> List[str]:
        """发送订单"""
        price = round_to(price, self.priceticks[vt_symbol])
        symbol, exchange = extract_vt_symbol(vt_symbol)

        self.limit_order_count += 1

        order: OrderData = OrderData(
            symbol=symbol,
            exchange=exchange,
            orderid=str(self.limit_order_count),
            direction=direction,
            offset=offset,
            price=price,
            volume=volume,
            status=Status.SUBMITTING,
            datetime=self.datetime,
            gateway_name=self.gateway_name,
        )

        self.active_limit_orders[order.vt_orderid] = order
        self.limit_orders[order.vt_orderid] = order

        return [order.vt_orderid]

    def cancel_order(self, strategy, vt_orderid: str) -> None:
        """撤销订单"""
        if vt_orderid not in self.active_limit_orders:
            return
        order: OrderData = self.active_limit_orders.pop(vt_orderid)

        order.status = Status.CANCELLED
        self.strategy.update_order(order)

    def write_log(self, msg: str, strategy=None) -> None:
        """写日志"""
        msg = f"{self.datetime}  {msg}"
        self.logs.append(msg)

    def get_all_trades(self) -> List[TradeData]:
        return list(self.trades.values())

    def get_all_orders(self) -> List[OrderData]:
        return list(self.limit_orders.values())

    def get_cash_available(self) -> float:
        return self.cash

    def get_holding_value(self) -> float:
        holding_value: float = 0
        for vt_symbol, pos in self.strategy.pos_data.items():
            bar: BarData = self.bars[vt_symbol]
            size: float = self.sizes[vt_symbol]
            holding_value += bar.close_price * pos * size
        return holding_value

    def get_portfolio_value(self) -> float:
        return self.get_cash_available() + self.get_holding_value()

    def get_pos(self, vt_symbol: str) -> float:
        if self.strategy:
            return self.strategy.pos_data.get(vt_symbol, 0)
        return 0


# ==================== 策略基类 ====================

class AlphaStrategy:
    """Alpha策略模板 - 与VNpy AlphaStrategy兼容"""

    def __init__(
        self,
        strategy_engine: BacktestingEngine,
        strategy_name: str,
        vt_symbols: List[str],
        setting: dict
    ) -> None:
        self.strategy_engine: BacktestingEngine = strategy_engine
        self.strategy_name: str = strategy_name
        self.vt_symbols: List[str] = vt_symbols

        self.pos_data: dict = defaultdict(float)
        self.target_data: dict = defaultdict(float)

        self.orders: Dict[str, OrderData] = {}
        self.active_orderids: set = set()

        for k, v in setting.items():
            if hasattr(self, k):
                setattr(self, k, v)

    def on_init(self) -> None:
        """初始化回调"""
        pass

    def on_bars(self, bars: Dict[str, BarData]) -> None:
        """K线回调"""
        pass

    def on_trade(self, trade: TradeData) -> None:
        """成交回调"""
        pass

    def update_trade(self, trade: TradeData) -> None:
        """更新成交"""
        if trade.direction == Direction.LONG:
            self.pos_data[trade.vt_symbol] += trade.volume
        else:
            self.pos_data[trade.vt_symbol] -= trade.volume
        self.on_trade(trade)

    def update_order(self, order: OrderData) -> None:
        """更新订单"""
        self.orders[order.vt_orderid] = order
        if not order.is_active() and order.vt_orderid in self.active_orderids:
            self.active_orderids.remove(order.vt_orderid)

    def buy(self, vt_symbol: str, price: float, volume: float) -> List[str]:
        return self.send_order(vt_symbol, Direction.LONG, Offset.OPEN, price, volume)

    def sell(self, vt_symbol: str, price: float, volume: float) -> List[str]:
        return self.send_order(vt_symbol, Direction.SHORT, Offset.CLOSE, price, volume)

    def short(self, vt_symbol: str, price: float, volume: float) -> List[str]:
        return self.send_order(vt_symbol, Direction.SHORT, Offset.OPEN, price, volume)

    def cover(self, vt_symbol: str, price: float, volume: float) -> List[str]:
        return self.send_order(vt_symbol, Direction.LONG, Offset.CLOSE, price, volume)

    def send_order(
        self,
        vt_symbol: str,
        direction: Direction,
        offset: Offset,
        price: float,
        volume: float
    ) -> List[str]:
        vt_orderids = self.strategy_engine.send_order(
            self, vt_symbol, direction, offset, price, volume
        )
        for vt_orderid in vt_orderids:
            self.active_orderids.add(vt_orderid)
        return vt_orderids

    def cancel_order(self, vt_orderid: str) -> None:
        self.strategy_engine.cancel_order(self, vt_orderid)

    def cancel_all(self) -> None:
        for vt_orderid in list(self.active_orderids):
            self.cancel_order(vt_orderid)

    def get_pos(self, vt_symbol: str) -> float:
        return self.pos_data.get(vt_symbol, 0)

    def write_log(self, msg: str) -> None:
        self.strategy_engine.write_log(msg, self)


# ==================== 数据转换工具 ====================

def df_to_bars(
    df: pl.DataFrame,
    vt_symbol: str,
    interval: Interval = Interval.MINUTE
) -> List[BarData]:
    """将Polars DataFrame转换为BarData列表"""
    bars = []
    symbol, exchange = extract_vt_symbol(vt_symbol)

    for row in df.iter_rows(named=True):
        dt = row['datetime']
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace('T', ' '))

        bar = BarData(
            gateway_name="DATA",
            symbol=symbol,
            exchange=exchange,
            datetime=dt,
            interval=interval,
            open_price=float(row['open']),
            high_price=float(row['high']),
            low_price=float(row['low']),
            close_price=float(row['close']),
            volume=float(row.get('volume', 0)),
        )
        bars.append(bar)

    return bars


def pandas_to_bars(
    df,
    vt_symbol: str,
    interval: Interval = Interval.MINUTE
) -> List[BarData]:
    """将Pandas DataFrame转换为BarData列表"""
    bars = []
    symbol, exchange = extract_vt_symbol(vt_symbol)

    for _, row in df.iterrows():
        dt = row['datetime']
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace('T', ' '))

        bar = BarData(
            gateway_name="DATA",
            symbol=symbol,
            exchange=exchange,
            datetime=dt,
            interval=interval,
            open_price=float(row['open']),
            high_price=float(row['high']),
            low_price=float(row['low']),
            close_price=float(row['close']),
            volume=float(row.get('volume', 0)),
        )
        bars.append(bar)

    return bars

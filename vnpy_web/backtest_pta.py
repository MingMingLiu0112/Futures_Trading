#!/usr/bin/env python3
"""
PTA策略回测 - 基于vnpy框架
vnpy版本: 4.3.0
"""
import sys
import os

# 设置路径
sys.path.insert(0, '/app')
sys.path.insert(0, '/usr/local/lib/python3.10/site-packages')

from datetime import datetime
from vnpy.trader.constant import Interval, Exchange, Direction, Offset
from vnpy.trader.object import TickData, BarData
from vnpy.trader.database import get_database
from vnpy_ctabacktester.engine import BacktestingEngine, BacktestingMode
from vnpy.event import EventEngine
from vnpy.trader.engine import MainEngine

# ===== 策略实现 =====
class MacdRsiStrategy:
    """MACD + RSI 趋势策略"""
    
    author = "PTA量化团队"
    
    fast_window = 12
    slow_window = 26
    signal_window = 9
    rsi_window = 14
    rsi_overbought = 70
    rsi_oversold = 30
    
    fixed_size = 1
    stop_loss_pct = 0.02  # 2%止损
    take_profit_pct = 0.05  # 5%止盈
    
    parameters = [
        "fast_window", "slow_window", "signal_window", 
        "rsi_window", "rsi_overbought", "rsi_oversold",
        "fixed_size", "stop_loss_pct", "take_profit_pct"
    ]
    
    variables = [
        "pos", "entry_price", "intra_trade_high", "intra_trade_low"
    ]
    
    def __init__(self, strategy_engine, strategy_name, vt_symbol, setting):
        self.strategy_engine = strategy_engine
        self.strategy_name = strategy_name
        self.vt_symbol = vt_symbol
        
        self.pos = 0
        self.entry_price = 0
        self.intra_trade_high = 0
        self.intra_trade_low = 0
        
        # K线缓存
        self.close_history = []
        self.bar_count = 0
        
        # 输出
        self.output(f"{strategy_name} 策略初始化")
    
    def on_init(self):
        self.output("策略初始化")
        self.load_bar(100)  # 加载历史数据
    
    def on_start(self):
        self.output("策略启动")
    
    def on_stop(self):
        self.output("策略停止")
    
    def on_tick(self, tick: TickData):
        pass
    
    def on_bar(self, bar: BarData):
        """K线数据处理"""
        self.cancel_all()
        
        # 缓存收盘价
        self.close_history.append(bar.close_price)
        if len(self.close_history) > 50:
            self.close_history.pop(0)
        
        if len(self.close_history) < 50:
            return
        
        # 计算MACD
        close_series = self.close_history[:-1]  # 不使用当前K线
        ema_fast = sum(close_series[-self.fast_window:]) / self.fast_window
        ema_slow = sum(close_series[-self.slow_window:]) / self.slow_window
        diff = ema_fast - ema_slow
        
        # 前一根DIFF
        ema_fast_prev = sum(close_series[-self.fast_window-1:-1]) / self.fast_window
        ema_slow_prev = sum(close_series[-self.slow_window-1:-1]) / self.slow_window
        diff_prev = ema_fast_prev - ema_slow_prev
        
        # RSI
        deltas = [self.close_history[i] - self.close_history[i-1] for i in range(1, len(self.close_history))]
        gains = [d for d in deltas[-self.rsi_window:] if d > 0]
        losses = [-d for d in deltas[-self.rsi_window:] if d < 0]
        avg_gain = sum(gains) / self.rsi_window if gains else 0
        avg_loss = sum(losses) / self.rsi_window if losses else 0
        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))
        
        # 无持仓
        if self.pos == 0:
            # 金叉买入
            if diff > 0 and diff_prev <= 0 and rsi < self.rsi_overbought:
                self.buy(bar.close_price, self.fixed_size)
                self.entry_price = bar.close_price
                self.intra_trade_high = bar.high_price
                self.intra_trade_low = bar.low_price
                self.output(f"[买入]@{bar.datetime} 价格:{bar.close_price:.0f} RSI:{rsi:.1f} DIFF:{diff:.2f}")
        
        # 持有空头
        elif self.pos < 0:
            self.intra_trade_high = max(self.intra_trade_high, bar.high_price)
            # 死叉卖出
            if diff < 0 and diff_prev >= 0:
                self.cover(bar.close_price, abs(self.pos))
                self.output(f"[平空]@{bar.datetime} 价格:{bar.close_price:.0f} DIFF:{diff:.2f}")
        
        # 持有多头
        elif self.pos > 0:
            self.intra_trade_low = min(self.intra_trade_low, bar.low_price)
            
            # 止损/止盈/平仓
            stop_price = self.entry_price * (1 - self.stop_loss_pct)
            target_price = self.entry_price * (1 + self.take_profit_pct)
            
            exit_reason = None
            exit_price = None
            
            if bar.close_price <= stop_price:
                exit_reason = "止损"
                exit_price = stop_price
            elif bar.close_price >= target_price:
                exit_reason = "止盈"
                exit_price = target_price
            elif diff < 0 and diff_prev >= 0:
                exit_reason = "死叉"
                exit_price = bar.close_price
            elif rsi > 85:
                exit_reason = "RSI超买"
                exit_price = bar.close_price
            
            if exit_reason and exit_price:
                self.sell(exit_price, abs(self.pos))
                pnl = (exit_price - self.entry_price) * 10 * self.pos
                self.output(f"[平多]@{bar.datetime} {exit_reason} 价格:{exit_price:.0f} PnL:{pnl:.0f}")
                self.pos = 0
    
    def load_bar(self, count: int):
        pass  # 回测引擎自动加载
    
    def buy(self, price: float, volume: float):
        self.pos += volume
        self.strategy_engine.buy(price, volume)
    
    def sell(self, price: float, volume: float):
        self.pos -= volume
        self.strategy_engine.sell(price, volume)
    
    def short(self, price: float, volume: float):
        self.pos -= volume
        self.strategy_engine.short(price, volume)
    
    def cover(self, price: float, volume: float):
        self.pos += volume
        self.strategy_engine.cover(price, volume)
    
    def cancel_all(self):
        pass
    
    def output(self, msg: str):
        print(msg)


def run_backtest():
    print("=" * 60)
    print("PTA策略回测 - vnpy原生框架")
    print("=" * 60)
    
    # 加载数据
    db = get_database()
    start = datetime(2026, 3, 1)
    end = datetime(2026, 4, 6)
    
    print(f"\n[1] 加载K线数据...")
    bars = db.load_bar_data("KQ.m@CZCE.TA", Exchange.CZCE, Interval.MINUTE, start, end)
    print(f"    加载 {len(bars)} 根K线")
    print(f"    时间范围: {bars[0].datetime} ~ {bars[-1].datetime}")
    
    if not bars:
        print("无数据，回测结束")
        return
    
    # 转换为DataFrame供策略使用
    import pandas as pd
    
    df = pd.DataFrame([{
        'datetime': bar.datetime,
        'open': bar.open_price,
        'high': bar.high_price,
        'low': bar.low_price,
        'close': bar.close_price,
        'volume': bar.volume
    } for bar in bars])
    
    close = df['close'].values
    
    # ===== MACD计算 =====
    def calc_ema(prices, period):
        ema = [prices[0]]
        k = 2 / (period + 1)
        for p in prices[1:]:
            ema.append(p * k + ema[-1] * (1 - k))
        return ema
    
    ema12 = calc_ema(close, 12)
    ema26 = calc_ema(close, 26)
    diff = [e12 - e26 for e12, e26 in zip(ema12, ema26)]
    
    def calc_ema_of_list(data, period):
        ema = [sum(data[:period]) / period]
        k = 2 / (period + 1)
        for p in data[period:]:
            ema.append(p * k + ema[-1] * (1 - k))
        return ema
    
    dea = calc_ema_of_list(diff, 9)
    macd = [(d - de) * 2 for d, de in zip(diff, dea)]
    
    # ===== RSI计算 =====
    deltas = [close[i] - close[i-1] for i in range(1, len(close))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    
    avg_gains = []
    avg_losses = []
    for i in range(14, len(deltas)):
        avg_g = sum(gains[i-14:i]) / 14
        avg_l = sum(losses[i-14:i]) / 14
        avg_gains.append(avg_g)
        avg_losses.append(avg_l)
    
    rs = [ag / (al + 1e-10) for ag, al in zip(avg_gains, avg_losses)]
    rsi = [100 - (100 / (1 + r)) for r in rs]
    
    # ===== 策略回测模拟 =====
    print(f"\n[2] 运行MACD+RSI策略...")
    
    capital = 100000.0
    position = 0  # 0=空仓, 1=多头, -1=空头
    entry_price = 0
    trades = []
    equity_curve = []
    
    stop_loss_pct = 0.02
    take_profit_pct = 0.05
    
    for i in range(50, len(df)):
        idx = i + 1  # RSI starts at index 14
        
        if idx >= len(rsi) + 14:
            break
        
        rsi_val = rsi[idx - 14]
        diff_val = diff[i]
        diff_prev = diff[i - 1]
        close_val = close[i]
        dt = df.iloc[i]['datetime']
        
        if position == 0:
            # 金叉买入条件: diff上穿0且RSI<70
            if diff_val > 0 and diff_prev <= 0 and rsi_val < 70:
                position = 1
                entry_price = close_val
                entry_dt = dt
                print(f"    [买入] {entry_dt} @ {entry_price:.0f}  RSI={rsi_val:.1f}")
        
        elif position == 1:
            stop_loss = entry_price * (1 - stop_loss_pct)
            take_profit = entry_price * (1 + take_profit_pct)
            exit_reason = None
            exit_price = None
            
            if close_val <= stop_loss:
                exit_reason = "止损"
                exit_price = stop_loss
            elif close_val >= take_profit:
                exit_reason = "止盈"
                exit_price = take_profit
            elif diff_val < 0 and diff_prev >= 0:
                exit_reason = "死叉"
                exit_price = close_val
            elif rsi_val > 85:
                exit_reason = "RSI超买"
                exit_price = close_val
            
            if exit_reason:
                pnl = (exit_price - entry_price) * 10
                capital += pnl
                trades.append({
                    'entry_dt': entry_dt,
                    'entry_price': entry_price,
                    'exit_dt': dt,
                    'exit_price': exit_price,
                    'pnl': pnl,
                    'reason': exit_reason,
                    'rsi': rsi_val
                })
                print(f"    [卖出] {exit_reason} {dt} @ {exit_price:.0f}  PnL={pnl:.0f}")
                position = 0
        
        equity_curve.append({'datetime': dt, 'equity': capital})
    
    # ===== 结果统计 =====
    print(f"\n[3] 回测结果统计")
    print("-" * 60)
    
    if not trades:
        print("无交易")
        return
    
    import pandas as pd
    df_trades = pd.DataFrame(trades)
    
    total = len(trades)
    wins = len(df_trades[df_trades['pnl'] > 0])
    losses = len(df_trades[df_trades['pnl'] <= 0])
    win_rate = wins / total * 100 if total > 0 else 0
    
    total_pnl = df_trades['pnl'].sum()
    max_win = df_trades['pnl'].max()
    max_loss = df_trades['pnl'].min()
    avg_pnl = df_trades['pnl'].mean()
    
    # 最大回撤
    eq = pd.DataFrame(equity_curve)
    eq['peak'] = eq['equity'].cummax()
    eq['drawdown'] = (eq['equity'] - eq['peak']) / eq['peak']
    max_dd = eq['drawdown'].min() * 100
    
    print(f"交易品种:   KQ.m@CZCE.TA (PTA连续)")
    print(f"数据周期:   1分钟")
    print(f"数据范围:   2026-03-01 ~ 2026-04-06")
    print(f"策略:      MACD金叉/死叉 + RSI超买超卖 + 2%止损5%止盈")
    print("-" * 60)
    print(f"交易次数:   {total}")
    print(f"盈利次数:   {wins} ({win_rate:.1f}%)")
    print(f"亏损次数:   {losses}")
    print(f"-" * 60)
    print(f"初始资金:   100000.00")
    print(f"最终资金:   {capital:.2f}")
    print(f"总收益:     {total_pnl:.2f}")
    print(f"收益率:     {total_pnl/100000*100:.2f}%")
    print(f"-" * 60)
    print(f"最大单笔盈利: {max_win:.2f}")
    print(f"最大单笔亏损: {max_loss:.2f}")
    print(f"平均盈亏:    {avg_pnl:.2f}")
    print(f"最大回撤:    {max_dd:.2f}%")
    print("-" * 60)
    print(f"出场原因统计:")
    for reason, cnt in df_trades['reason'].value_counts().items():
        print(f"  {reason}: {cnt}")
    print("=" * 60)
    
    return df_trades, eq


if __name__ == "__main__":
    run_backtest()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MACD策略模块
基于MACD指标的交易策略
"""

from typing import Optional, Dict, Any
from backtest.strategy_base import StrategyBase, StrategySignal


class MACDStrategy(StrategyBase):
    """MACD交叉策略"""
    
    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        self.default_params = {
            'fast_period': 12,
            'slow_period': 26,
            'signal_period': 9,
            'risk_pct': 0.01,
            'take_profit_pct': 0.02
        }
        self.params = {**self.default_params, **(params or {})}
        self.prev_macd = None
        self.prev_signal = None
    
    def _calculate_macd(self, prices: list) -> tuple:
        """计算MACD指标"""
        if len(prices) < self.params['slow_period']:
            return None, None, None
        
        # 计算EMA
        def ema(values, period):
            alpha = 2 / (period + 1)
            result = []
            for i, val in enumerate(values):
                if i == 0:
                    result.append(val)
                else:
                    result.append(alpha * val + (1 - alpha) * result[-1])
            return result
        
        ema_fast = ema(prices, self.params['fast_period'])
        ema_slow = ema(prices, self.params['slow_period'])
        
        # DIF = EMA12 - EMA26
        dif = [ema_fast[i] - ema_slow[i] for i in range(len(ema_slow))]
        
        # DEA = EMA(DIF, 9)
        dea = ema(dif, self.params['signal_period'])
        
        # MACD = 2 * (DIF - DEA)
        macd = [2 * (dif[i] - dea[i]) for i in range(len(dea))]
        
        return dif[-1], dea[-1], macd[-1]
    
    def on_bar(self, bar: Dict[str, Any]) -> Optional[StrategySignal]:
        """
        处理一根K线
        :param bar: K线数据字典，需要包含 'close' 字段
        :return: 信号（如果有）
        """
        # 确保有足够的历史数据
        if not hasattr(self, 'price_history'):
            self.price_history = []
        
        self.price_history.append(bar['close'])
        
        # 计算MACD
        dif, signal, macd = self._calculate_macd(self.price_history)
        
        if dif is None:
            return None
        
        current_price = bar['close']
        timestamp = bar.get('time', '')
        
        # 金叉信号：DIF上穿DEA
        if self.prev_macd is not None and self.prev_signal is not None:
            if self.prev_macd <= self.prev_signal and dif > signal:
                # 开多信号
                stop_loss = current_price * (1 - self.params['risk_pct'])
                take_profit = current_price * (1 + self.params['take_profit_pct'])
                return self.generate_signal('buy', current_price, timestamp, 
                                          stop_loss=stop_loss, take_profit=take_profit)
            
            # 死叉信号：DIF下穿DEA
            elif self.prev_macd >= self.prev_signal and dif < signal:
                # 开空信号
                stop_loss = current_price * (1 + self.params['risk_pct'])
                take_profit = current_price * (1 - self.params['take_profit_pct'])
                return self.generate_signal('sell', current_price, timestamp,
                                          stop_loss=stop_loss, take_profit=take_profit)
        
        self.prev_macd = dif
        self.prev_signal = signal
        
        return None
    
    def reset(self):
        """重置策略状态"""
        super().reset()
        self.prev_macd = None
        self.prev_signal = None
        if hasattr(self, 'price_history'):
            self.price_history = []

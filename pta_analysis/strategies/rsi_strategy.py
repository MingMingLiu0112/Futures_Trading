#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSI策略模块
基于相对强弱指标的超买超卖策略
"""

from typing import Dict, Any, Optional, List
import numpy as np

from backtest.strategy_base import StrategyBase, StrategySignal


class RSIStrategy(StrategyBase):
    """
    RSI策略实现
    
    策略逻辑：
    - RSI低于超卖阈值（如30）时买入
    - RSI高于超买阈值（如70）时卖出
    - 支持动态止损止盈
    """
    
    def __init__(self, 
                 rsi_period: int = 14, 
                 oversold_threshold: float = 30.0,
                 overbought_threshold: float = 70.0,
                 stop_loss_pct: float = 0.02,
                 take_profit_pct: float = 0.04,
                 params: dict = None):
        """
        初始化RSI策略
        
        :param rsi_period: RSI计算周期，默认14
        :param oversold_threshold: 超卖阈值，默认30
        :param overbought_threshold: 超买阈值，默认70
        :param stop_loss_pct: 止损百分比，默认2%
        :param take_profit_pct: 止盈百分比，默认4%
        :param params: 可选参数字典（用于API兼容性，自动提取策略参数）
        """
        # 兼容API调用：params字典中的参数优先
        if params and isinstance(params, dict):
            rsi_period = params.get('rsi_period', rsi_period)
            oversold_threshold = params.get('oversold_threshold', oversold_threshold)
            overbought_threshold = params.get('overbought_threshold', overbought_threshold)
            stop_loss_pct = params.get('stop_loss_pct', stop_loss_pct)
            take_profit_pct = params.get('take_profit_pct', take_profit_pct)
        
        super().__init__()
        self.rsi_period = rsi_period
        self.oversold_threshold = oversold_threshold
        self.overbought_threshold = overbought_threshold
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        
        # 价格历史用于计算RSI
        self.price_history: List[float] = []
        self.rsi_history: List[float] = []
        
    def _calculate_rsi(self, prices: List[float]) -> Optional[float]:
        """
        计算RSI指标
        
        :param prices: 价格序列
        :return: RSI值，数据不足时返回None
        """
        if len(prices) < self.rsi_period + 1:
            return None
        
        deltas = np.diff(prices)
        gains = deltas.copy()
        losses = deltas.copy()
        
        gains[gains < 0] = 0
        losses[losses > 0] = 0
        losses = abs(losses)
        
        avg_gain = np.mean(gains[-self.rsi_period:])
        avg_loss = np.mean(losses[-self.rsi_period:])
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        
        return rsi
    
    def on_bar(self, bar: Dict[str, Any]) -> Optional[StrategySignal]:
        """
        处理K线数据并生成交易信号
        
        :param bar: K线数据字典，包含 'close', 'high', 'low', 'open', 'timestamp' 等字段
        :return: 交易信号，无信号时返回None
        """
        close_price = bar['close']
        self.price_history.append(close_price)
        
        # 计算RSI
        rsi = self._calculate_rsi(self.price_history)
        
        if rsi is not None:
            self.rsi_history.append(rsi)
            
            # 获取上一根RSI值用于判断穿越
            prev_rsi = self.rsi_history[-2] if len(self.rsi_history) > 1 else None
            
            # 超卖买入信号：RSI低于超卖阈值
            if rsi <= self.oversold_threshold:
                stop_loss = close_price * (1 - self.stop_loss_pct)
                take_profit = close_price * (1 + self.take_profit_pct)
                return self.generate_signal(
                    signal_type='buy',
                    price=close_price,
                    timestamp=bar.get('timestamp', ''),
                    stop_loss=stop_loss,
                    take_profit=take_profit
                )
            
            # 超买卖出信号：RSI高于超买阈值
            if rsi >= self.overbought_threshold:
                stop_loss = close_price * (1 + self.stop_loss_pct)
                take_profit = close_price * (1 - self.take_profit_pct)
                return self.generate_signal(
                    signal_type='sell',
                    price=close_price,
                    timestamp=bar.get('timestamp', ''),
                    stop_loss=stop_loss,
                    take_profit=take_profit
                )
        
        return None
    
    def reset(self):
        """重置策略状态"""
        super().reset()
        self.price_history = []
        self.rsi_history = []
    
    def get_parameters(self) -> Dict[str, Any]:
        """获取策略参数"""
        return {
            'rsi_period': self.rsi_period,
            'oversold_threshold': self.oversold_threshold,
            'overbought_threshold': self.overbought_threshold,
            'stop_loss_pct': self.stop_loss_pct,
            'take_profit_pct': self.take_profit_pct
        }

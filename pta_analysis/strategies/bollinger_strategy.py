#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
布林带策略模块
基于布林带指标的交易策略
"""

from typing import Dict, Any, Optional, List
import numpy as np

from backtest.strategy_base import StrategyBase, StrategySignal


class BollingerStrategy(StrategyBase):
    """
    布林带策略实现
    
    策略逻辑：
    - 价格跌破下轨时买入
    - 价格突破上轨时卖出
    - 价格回归中轨时平仓
    """
    
    def __init__(self, 
                 period: int = 20, 
                 std_dev: float = 2.0,
                 stop_loss_pct: float = 0.02,
                 take_profit_pct: float = 0.04):
        """
        初始化布林带策略
        
        :param period: 计算周期，默认20
        :param std_dev: 标准差倍数，默认2.0
        :param stop_loss_pct: 止损百分比，默认2%
        :param take_profit_pct: 止盈百分比，默认4%
        """
        super().__init__()
        self.period = period
        self.std_dev = std_dev
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        
        # 价格历史用于计算布林带
        self.price_history: List[float] = []
        self.middle_band_history: List[float] = []
        self.upper_band_history: List[float] = []
        self.lower_band_history: List[float] = []
        
    def _calculate_bollinger_bands(self, prices: List[float]) -> Optional[Dict[str, float]]:
        """
        计算布林带指标
        
        :param prices: 价格序列
        :return: 布林带值（中轨、上轨、下轨），数据不足时返回None
        """
        if len(prices) < self.period:
            return None
        
        prices_array = np.array(prices[-self.period:])
        middle_band = np.mean(prices_array)
        std = np.std(prices_array)
        
        upper_band = middle_band + self.std_dev * std
        lower_band = middle_band - self.std_dev * std
        
        return {
            'middle': middle_band,
            'upper': upper_band,
            'lower': lower_band
        }
    
    def on_bar(self, bar: Dict[str, Any]) -> Optional[StrategySignal]:
        """
        处理K线数据并生成交易信号
        
        :param bar: K线数据字典，包含 'close', 'high', 'low', 'open', 'timestamp' 等字段
        :return: 交易信号，无信号时返回None
        """
        close_price = bar['close']
        self.price_history.append(close_price)
        
        # 计算布林带
        bands = self._calculate_bollinger_bands(self.price_history)
        
        if bands is not None:
            self.middle_band_history.append(bands['middle'])
            self.upper_band_history.append(bands['upper'])
            self.lower_band_history.append(bands['lower'])
            
            middle_band = bands['middle']
            upper_band = bands['upper']
            lower_band = bands['lower']
            
            # 跌破下轨买入信号
            if close_price <= lower_band:
                stop_loss = close_price * (1 - self.stop_loss_pct)
                take_profit = middle_band  # 目标为中轨
                return self.generate_signal(
                    signal_type='buy',
                    price=close_price,
                    timestamp=bar.get('timestamp', ''),
                    stop_loss=stop_loss,
                    take_profit=take_profit
                )
            
            # 突破上轨卖出信号
            if close_price >= upper_band:
                stop_loss = close_price * (1 + self.stop_loss_pct)
                take_profit = middle_band  # 目标为中轨
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
        self.middle_band_history = []
        self.upper_band_history = []
        self.lower_band_history = []
    
    def get_parameters(self) -> Dict[str, Any]:
        """获取策略参数"""
        return {
            'period': self.period,
            'std_dev': self.std_dev,
            'stop_loss_pct': self.stop_loss_pct,
            'take_profit_pct': self.take_profit_pct
        }

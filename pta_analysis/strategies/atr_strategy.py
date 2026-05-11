#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ATR策略模块
基于平均真实波动幅度的交易策略
"""

from typing import Dict, Any, Optional, List
import numpy as np

from backtest.strategy_base import StrategyBase, StrategySignal


class ATRStrategy(StrategyBase):
    """
    ATR策略实现
    
    策略逻辑：
    - 使用ATR作为波动性指标
    - 当价格突破近期波动范围时开仓
    - 使用ATR倍数作为止损
    """
    
    def __init__(self, 
                 atr_period: int = 14, 
                 breakout_factor: float = 1.5,
                 stop_loss_multiplier: float = 1.0,
                 take_profit_multiplier: float = 2.0,
                 params: dict = None):
        """
        初始化ATR策略
        
        :param atr_period: ATR计算周期，默认14
        :param breakout_factor: 突破系数，默认1.5
        :param stop_loss_multiplier: 止损ATR倍数，默认1.0
        :param take_profit_multiplier: 止盈ATR倍数，默认2.0
        :param params: 可选参数字典（用于API兼容性，自动提取策略参数）
        """
        # 兼容API调用：params字典中的参数优先
        if params and isinstance(params, dict):
            atr_period = params.get('atr_period', atr_period)
            breakout_factor = params.get('breakout_factor', breakout_factor)
            stop_loss_multiplier = params.get('stop_loss_multiplier', stop_loss_multiplier)
            take_profit_multiplier = params.get('take_profit_multiplier', take_profit_multiplier)
        
        super().__init__()
        self.atr_period = atr_period
        self.breakout_factor = breakout_factor
        self.stop_loss_multiplier = stop_loss_multiplier
        self.take_profit_multiplier = take_profit_multiplier
        
        # 历史数据
        self.high_history: List[float] = []
        self.low_history: List[float] = []
        self.close_history: List[float] = []
        self.atr_history: List[float] = []
        
    def _calculate_atr(self) -> Optional[float]:
        """
        计算ATR指标
        
        :return: ATR值，数据不足时返回None
        """
        if len(self.high_history) < self.atr_period + 1:
            return None
        
        tr_values = []
        for i in range(1, len(self.close_history)):
            high = self.high_history[i]
            low = self.low_history[i]
            prev_close = self.close_history[i-1]
            
            tr1 = high - low
            tr2 = abs(high - prev_close)
            tr3 = abs(low - prev_close)
            
            tr = max(tr1, tr2, tr3)
            tr_values.append(tr)
        
        # 使用简单移动平均计算ATR
        atr = np.mean(tr_values[-self.atr_period:])
        return atr
    
    def _calculate_range(self) -> Optional[Dict[str, float]]:
        """
        计算近期波动范围
        
        :return: 波动范围（最高价、最低价、范围宽度），数据不足时返回None
        """
        if len(self.high_history) < self.atr_period:
            return None
        
        recent_high = max(self.high_history[-self.atr_period:])
        recent_low = min(self.low_history[-self.atr_period:])
        
        return {
            'high': recent_high,
            'low': recent_low,
            'range': recent_high - recent_low
        }
    
    def on_bar(self, bar: Dict[str, Any]) -> Optional[StrategySignal]:
        """
        处理K线数据并生成交易信号
        
        :param bar: K线数据字典，包含 'close', 'high', 'low', 'open', 'timestamp' 等字段
        :return: 交易信号，无信号时返回None
        """
        close_price = bar['close']
        high_price = bar.get('high', close_price)
        low_price = bar.get('low', close_price)
        
        self.high_history.append(high_price)
        self.low_history.append(low_price)
        self.close_history.append(close_price)
        
        # 计算ATR
        atr = self._calculate_atr()
        
        if atr is not None:
            self.atr_history.append(atr)
            
            # 使用固定范围：最近N根K线的最高/最低价
            if len(self.high_history) >= self.atr_period + 1:
                # 使用前N根K线的范围（不包括当前K线）
                recent_high = max(self.high_history[-(self.atr_period + 1):-1])
                recent_low = min(self.low_history[-(self.atr_period + 1):-1])
                
                # 向上突破信号：最高价突破近期高点
                if high_price > recent_high:
                    stop_loss = close_price - self.stop_loss_multiplier * atr
                    take_profit = close_price + self.take_profit_multiplier * atr
                    return self.generate_signal(
                        signal_type='buy',
                        price=close_price,
                        timestamp=bar.get('timestamp', ''),
                        stop_loss=stop_loss,
                        take_profit=take_profit
                    )
                
                # 向下突破信号：最低价跌破近期低点
                if low_price < recent_low:
                    stop_loss = close_price + self.stop_loss_multiplier * atr
                    take_profit = close_price - self.take_profit_multiplier * atr
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
        self.high_history = []
        self.low_history = []
        self.close_history = []
        self.atr_history = []
    
    def get_parameters(self) -> Dict[str, Any]:
        """获取策略参数"""
        return {
            'atr_period': self.atr_period,
            'breakout_factor': self.breakout_factor,
            'stop_loss_multiplier': self.stop_loss_multiplier,
            'take_profit_multiplier': self.take_profit_multiplier
        }

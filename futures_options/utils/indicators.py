"""
工具函数
"""

import pandas as pd
import numpy as np
from typing import Tuple


def calculate_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    计算技术指标（均线、MACD、布林带）
    """
    df = df.copy()
    
    # 均线
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma10'] = df['close'].rolling(10).mean()
    df['ma20'] = df['close'].rolling(20).mean()
    df['ma60'] = df['close'].rolling(60).mean()
    
    # MACD
    exp12 = df['close'].ewm(span=12, adjust=False).mean()
    exp26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp12 - exp26
    df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['histogram'] = df['macd'] - df['signal']
    
    # 布林带
    df['bb_mid'] = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    df['bb_upper'] = df['bb_mid'] + 2 * bb_std
    df['bb_lower'] = df['bb_mid'] - 2 * bb_std
    
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    return df


def detect_momentum(df: pd.DataFrame, lookback: int = 5) -> str:
    """
    检测价格动量方向
    """
    if len(df) < lookback:
        return "neutral"
    
    recent = df.tail(lookback)
    ma5 = recent['close'].mean()
    ma20 = df['close'].rolling(20).mean().iloc[-1]
    
    if ma5 > ma20 * 1.02:
        return "bullish"
    elif ma5 < ma20 * 0.98:
        return "bearish"
    else:
        return "neutral"


def calculate_volume_profile(df: pd.DataFrame) -> Tuple[float, float]:
    """
    计算成交量变化
    返回: (当日成交量, 成交量均线比率)
    """
    volume = df['volume'].iloc[-1] if len(df) > 0 else 0
    volume_ma = df['volume'].rolling(20).mean().iloc[-1] if len(df) >= 20 else volume
    ratio = volume / volume_ma if volume_ma > 0 else 1.0
    return volume, ratio


def format_percentage(value: float, decimals: int = 2) -> str:
    """格式化百分比"""
    return f"{value:.{decimals}f}%"


def format_price(value: float, decimals: int = 2) -> str:
    """格式化价格"""
    return f"{value:.{decimals}f}"

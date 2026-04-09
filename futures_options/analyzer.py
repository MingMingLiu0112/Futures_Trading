"""
期货期权综合分析引擎
"""

from typing import Dict, Optional, List
from datetime import datetime, timedelta
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from .signals.volatility import (
    calculate_iv_rank, calculate_iv_skew, calculate_iv_percentile,
    calculate_basis_iv_signal, composite_signal
)
from .data.futures_data import get_futures_daily, get_futures_basis
from .utils.indicators import (
    calculate_technical_indicators, detect_momentum,
    calculate_volume_profile, format_percentage, format_price
)


class FuturesOptionsAnalyzer:
    """期货期权综合分析器"""
    
    def __init__(self, symbol: str, iv_history: List[float] = None,
                 put_iv: float = None, call_iv: float = None):
        """
        Args:
            symbol: 期货品种代码（如 "CU", "AU"）
            iv_history: 历史IV列表（用于计算IV Rank）
            put_iv: 当前看跌期权隐含波动率
            call_iv: 当前看涨期权隐含波动率
        """
        self.symbol = symbol
        self.iv_history = iv_history or []
        self.put_iv = put_iv
        self.call_iv = call_iv
    
    def analyze(self, futures_data: Dict) -> Dict:
        """
        执行综合分析
        
        Args:
            futures_data: 包含期货数据的字典
                - basis: 基差
                - price: 当前价格
                - df: 日线DataFrame
        """
        result = {
            "title": f"{self.symbol} 期货期权分析",
            "symbol": self.symbol,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "iv_signal": {},
            "composite": {},
            "signals": []
        }
        
        # 1. IV信号
        if self.iv_history and self.put_iv and self.call_iv:
            iv_rank = calculate_iv_rank(
                (self.put_iv + self.call_iv) / 2,
                self.iv_history
            )
            iv_percentile = calculate_iv_percentile(
                (self.put_iv + self.call_iv) / 2,
                self.iv_history
            )
            skew_info = calculate_iv_skew(self.put_iv, self.call_iv)
            
            result["iv_signal"] = {
                "iv_rank": iv_rank,
                "iv_percentile": iv_percentile,
                "skew": skew_info["skew"],
                "sentiment": skew_info["sentiment"],
                "put_iv": self.put_iv,
                "call_iv": self.call_iv
            }
        
        # 2. 基差信号
        basis = futures_data.get("basis", 0)
        if self.iv_history:
            basis_signal = calculate_basis_iv_signal(
                basis,
                (self.put_iv + self.call_iv) / 2 if self.put_iv and self.call_iv else 50,
                self.iv_history
            )
            result["basis_signal"] = basis_signal
        else:
            basis_signal = {"direction": "观望", "reason": "IV数据不足"}
        
        # 3. 技术分析
        df = futures_data.get("df")
        if df is not None and not df.empty:
            df = calculate_technical_indicators(df)
            momentum = detect_momentum(df)
            volume, vol_ratio = calculate_volume_profile(df)
            
            result["technical"] = {
                "momentum": momentum,
                "volume_ratio": round(vol_ratio, 2),
                "ma5": format_price(df['ma5'].iloc[-1]),
                "ma20": format_price(df['ma20'].iloc[-1]),
                "rsi": format_percentage(df['rsi'].iloc[-1], 1),
                "macd_histogram": format_price(df['histogram'].iloc[-1])
            }
        else:
            momentum = "neutral"
        
        # 4. 综合信号
        if self.iv_history:
            composite = composite_signal(
                iv_rank=result["iv_signal"].get("iv_rank", 50),
                skew=result["iv_signal"].get("skew", 0),
                basis_signal=basis_signal,
                momentum=momentum
            )
            result["composite"] = composite
            result["signals"] = composite.get("signals", [])
        
        # 5. 基础行情
        if df is not None and not df.empty:
            result["price"] = format_price(df['close'].iloc[-1])
            result["change"] = format_percentage(
                (df['close'].iloc[-1] - df['open'].iloc[-1]) / df['open'].iloc[-1] * 100
            )
        
        return result
    
    def print_report(self, result: Dict):
        """打印分析报告"""
        print("=" * 50)
        print(f"📊 {result['title']}")
        print("=" * 50)
        
        if "price" in result:
            print(f"价格: {result['price']} ({result['change']})")
        
        if "iv_signal" in result and result["iv_signal"]:
            iv = result["iv_signal"]
            print(f"\n📈 波动率信号:")
            print(f"  IV Rank: {iv['iv_rank']}%")
            print(f"  IV Skew: {iv['skew']}")
            print(f"  市场情绪: {iv['sentiment']}")
        
        if "composite" in result and result["composite"]:
            comp = result["composite"]
            print(f"\n🎯 综合信号:")
            print(f"  建议: {comp['recommendation']}")
            print(f"  评分: {comp['score']:+d}")
            print(f"  置信度: {comp['confidence']}")
        
        if result.get("signals"):
            print(f"\n📋 信号列表:")
            for s in result["signals"]:
                print(f"  • {s}")
        
        print("=" * 50)


def demo_analysis():
    """演示分析"""
    analyzer = FuturesOptionsAnalyzer(
        symbol="CU",
        iv_history=[15, 18, 20, 22, 25, 28, 30, 35, 28, 22],
        put_iv=24.5,
        call_iv=22.3
    )
    
    # 模拟期货数据
    import pandas as pd
    import numpy as np
    
    dates = pd.date_range(end=datetime.now(), periods=60)
    prices = 70000 + np.cumsum(np.random.randn(60) * 200)
    
    df = pd.DataFrame({
        'date': dates,
        'open': prices + np.random.randn(60) * 50,
        'high': prices + abs(np.random.randn(60)) * 100,
        'low': prices - abs(np.random.randn(60)) * 100,
        'close': prices,
        'volume': np.random.randint(10000, 50000, 60)
    })
    
    futures_data = {
        "basis": 500,  # 贴水
        "price": 70200,
        "df": df
    }
    
    result = analyzer.analyze(futures_data)
    analyzer.print_report(result)
    
    return result


if __name__ == "__main__":
    demo_analysis()

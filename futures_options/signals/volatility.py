"""
波动率信号计算模块
计算 IV Rank、IV Skew、基差+IV共振等信号
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional


def calculate_iv_rank(current_iv: float, iv_history: list) -> float:
    """
    计算 IV Rank（隐含波动率在历史区间的位置）
    
    Args:
        current_iv: 当前隐含波动率
        iv_history: 历史IV列表
    
    Returns:
        IV Rank: 0-100 的百分比值
    """
    if len(iv_history) < 2:
        return 50.0  # 数据不足返回中间值
    
    iv_min = min(iv_history)
    iv_max = max(iv_history)
    
    if iv_max == iv_min:
        return 50.0
    
    rank = (current_iv - iv_min) / (iv_max - iv_min) * 100
    return round(rank, 2)


def calculate_iv_percentile(current_iv: float, iv_history: list) -> float:
    """
    计算 IV Percentile（当前IV在历史数据中超过多少比例）
    比 IV Rank 更稳健，不受极端值影响
    """
    if len(iv_history) < 2:
        return 50.0
    
    percentile = sum(1 for iv in iv_history if iv < current_iv) / len(iv_history) * 100
    return round(percentile, 2)


def calculate_iv_skew(put_iv: float, call_iv: float) -> Dict[str, float]:
    """
    计算 IV Skew（看跌/看涨隐含波动率差）
    
    Args:
        put_iv: 看跌期权隐含波动率
        call_iv: 看涨期权隐含波动率
    
    Returns:
        Skew相关指标字典
    """
    skew = put_iv - call_iv
    
    # 判断市场倾向
    if skew > 0.5:
        sentiment = "偏空"  # 市场买入看跌期权做保护
    elif skew < -0.5:
        sentiment = "偏多"  # 市场买入看涨期权博上涨
    else:
        sentiment = "中性"
    
    return {
        "skew": round(skew, 4),
        "sentiment": sentiment,
        "put_iv": put_iv,
        "call_iv": call_iv
    }


def calculate_basis_iv_signal(basis: float, current_iv: float, 
                               iv_history: list) -> Dict[str, any]:
    """
    基差 + IV 共振信号
    判断升贴水状态下IV对期货方向的影响
    
    Args:
        basis: 基差（现货 - 期货），正=贴水，负=升水
        current_iv: 当前IV
        iv_history: 历史IV
    """
    iv_rank = calculate_iv_rank(current_iv, iv_history)
    
    # 共振信号判断
    if basis > 0:  # 贴水（期货 < 现货）
        if iv_rank > 60:
            signal = "多信号共振偏多"
            direction = "多"
            confidence = "高"
            reason = "贴水 + IV偏高，现货紧张预期"
        elif iv_rank < 40:
            signal = "矛盾信号"
            direction = "观望"
            confidence = "低"
            reason = "贴水但IV偏低，分歧较大"
        else:
            signal = "偏多"
            direction = "多"
            confidence = "中"
            reason = "贴水结构，震荡偏多"
    else:  # 升水（期货 > 现货）
        if iv_rank > 60:
            signal = "矛盾信号"
            direction = "观望"
            confidence = "低"
            reason = "升水但IV偏高，谨慎"
        elif iv_rank < 40:
            signal = "空信号共振"
            direction = "空"
            confidence = "高"
            reason = "升水 + IV偏低，产业套保预期"
        else:
            signal = "偏空"
            direction = "空"
            confidence = "中"
            reason = "升水结构，震荡偏空"
    
    return {
        "basis": round(basis, 4),
        "iv_rank": iv_rank,
        "signal": signal,
        "direction": direction,
        "confidence": confidence,
        "reason": reason
    }


def gamma_squeeze_warning(spot_price: float, strike_price: float,
                          days_to_expiry: int, total_gamma: float) -> Optional[Dict]:
    """
    Gamma挤压预警
    检测是否临近到期且标的价格接近行权价
    
    Args:
        spot_price: 标的价格
        strike_price: 关键行权价
        days_to_expiry: 到期天数
        total_gamma: 总Gamma值（来自期权链）
    """
    # 价格偏离度
    price_deviation = abs(spot_price - strike_price) / strike_price * 100
    
    # Gamma挤压条件
    if days_to_expiry <= 7 and price_deviation < 1.0 and total_gamma > 1000:
        return {
            "warning": True,
            "days_to_expiry": days_to_expiry,
            "price_deviation": round(price_deviation, 4),
            "total_gamma": total_gamma,
            "message": f"⚠️ Gamma挤压预警：距到期{days_to_expiry}天，价格偏离行权价仅{price_deviation:.2f}%，注意突破风险"
        }
    
    return None


def composite_signal(iv_rank: float, skew: float, basis_signal: Dict,
                     momentum: str = "neutral") -> Dict:
    """
    综合信号计算
    结合IV Rank、Skew、基差信号，给出最终方向建议
    
    Args:
        iv_rank: IV Rank (0-100)
        skew: IV Skew值
        basis_signal: 基差+IV信号字典
        momentum: 价格动量方向（"bullish"/"bearish"/"neutral"）
    """
    score = 0
    signals = []
    
    # IV Rank 评分
    if iv_rank < 20:
        score += 2
        signals.append("IV极低→波动即将放大")
    elif iv_rank > 80:
        score -= 2
        signals.append("IV极高→注意风险")
    
    # Skew 评分
    if skew > 1:
        score -= 1
        signals.append("看跌Skew→市场担忧下跌")
    elif skew < -1:
        score += 1
        signals.append("看涨Skew→市场看涨")
    
    # 基差信号
    if basis_signal["direction"] == "多":
        score += 2
        signals.append(f"基差信号偏多({basis_signal['reason']})")
    elif basis_signal["direction"] == "空":
        score -= 2
        signals.append(f"基差信号偏空({basis_signal['reason']})")
    
    # 动量
    if momentum == "bullish":
        score += 1
        signals.append("价格动量向上")
    elif momentum == "bearish":
        score -= 1
        signals.append("价格动量向下")
    
    # 最终判断
    if score >= 3:
        recommendation = "建议做多"
        action = "long"
    elif score <= -3:
        recommendation = "建议做空"
        action = "short"
    else:
        recommendation = "建议观望"
        action = "watch"
    
    return {
        "score": score,
        "recommendation": recommendation,
        "action": action,
        "signals": signals,
        "confidence": "高" if abs(score) >= 3 else ("中" if abs(score) >= 1 else "低")
    }

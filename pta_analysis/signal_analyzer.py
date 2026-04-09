#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA三维度信号分析器
基于：宏观+成本基本面 × 技术面 × 期权印证
"""

import sys, os, json, sqlite3, warnings
from datetime import datetime, timedelta
from typing import Optional, Tuple

sys.path.insert(0, '/home/admin/.openclaw/workspace/codeman/pta_analysis')
warnings.filterwarnings('ignore')

import akshare as ak
import numpy as np
import pandas as pd

# ===================== 数据获取 =====================

def get_pta_realtime():
    """PTA期货实时"""
    try:
        df = ak.futures_zh_realtime(symbol="PTA")
        if df is not None and not df.empty:
            row = df[df['symbol'] == 'TA0'].iloc[0] if 'TA0' in df['symbol'].values else df.iloc[0]
            return {
                "price": float(row.get("trade", 0)),
                "open": float(row.get("open", 0)),
                "high": float(row.get("high", 0)),
                "low": float(row.get("low", 0)),
                "close": float(row.get("close", 0)),
                "volume": int(row.get("volume", 0)),
                "open_interest": int(row.get("position", 0)),
                "change_pct": float(row.get("changepercent", 0)),
            }
    except Exception as e:
        print(f"[WARN] PTA实时: {e}")
    return None

def get_brent():
    """布伦特原油"""
    try:
        df = ak.futures_global_spot_em()
        if df is not None and not df.empty:
            brent = df[df['名称'].str.contains('布伦特', na=False)].copy()
            if not brent.empty:
                brent = brent.sort_values('成交量', ascending=False).iloc[0]
                return {
                    "price": float(brent.get("最新价", 0)),
                    "change_pct": float(brent.get("涨跌幅", 0)),
                }
    except Exception as e:
        print(f"[WARN] 布伦特: {e}")
    return None

def get_px_price():
    """PX现货价"""
    try:
        for i in range(7):
            date_str = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
            df = ak.futures_spot_price(date=date_str, vars_list=['PX'])
            if df is not None and not df.empty:
                return float(df.iloc[0].get("spot_price", 0))
    except:
        pass
    return None

def get_pta_spot():
    """PTA现货价"""
    try:
        for i in range(7):
            date_str = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
            df = ak.futures_spot_price(date=date_str, vars_list=['TA'])
            if df is not None and not df.empty:
                return float(df.iloc[0].get("spot_price", 0))
    except:
        pass
    return None

def get_pta_daily(n=60):
    """PTA日K线数据（用于技术分析）"""
    try:
        df = ak.futures_zh_daily_sina(symbol='TA0')
        if df is not None and not df.empty:
            df = df.sort_values('date').tail(n).reset_index(drop=True)
            return df
    except Exception as e:
        print(f"[WARN] PTA日K: {e}")
    return None

def get_ta_options_info():
    """PTA期权链信息"""
    try:
        df = ak.option_contract_info_ctp()
        ta = df[(df['交易所ID'] == 'CZCE') & (df['合约名称'].str.startswith('TA', na=False))]
        if not ta.empty:
            expiry = str(ta['最后交易日'].iloc[0])
            strikes = sorted(ta['行权价'].dropna().unique().tolist())
            return {"count": len(ta), "expiry": expiry, "strikes": strikes}
    except Exception as e:
        print(f"[WARN] PTA期权链: {e}")
    return None

def get_warehouse_receipt():
    """PTA仓单数据"""
    try:
        for i in range(5):
            date_str = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
            df = ak.futures_warehouse_receipt_czce(date=date_str)
            if df is not None and not df.empty:
                if 'PTA' in df.columns:
                    return float(df['PTA'].iloc[0])
                for col in df.columns:
                    if 'PTA' in str(col):
                        return float(df[col].iloc[0])
    except:
        pass
    return None

# ===================== 技术指标 =====================

def calc_ma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n).mean()

def calc_macd(series: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast).mean()
    ema_slow = series.ewm(span=slow).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal).mean()
    macd = (dif - dea) * 2
    return dif, dea, macd

def calc_rsi(series: pd.Series, n=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=n-1).mean()
    avg_loss = loss.ewm(com=n-1).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def analyze_technical(df: pd.DataFrame) -> dict:
    """技术面分析"""
    if df is None or len(df) < 20:
        return {"score": 50, "trend": "震荡", "detail": "数据不足"}

    close = df['close']
    high = df['high']
    low = df['low']

    # 均线
    ma5 = calc_ma(close, 5).iloc[-1]
    ma10 = calc_ma(close, 10).iloc[-1]
    ma20 = calc_ma(close, 20).iloc[-1]
    ma60 = calc_ma(close, 60).iloc[-1] if len(df) >= 60 else None

    latest = close.iloc[-1]
    prev_close = close.iloc[-2]

    # 趋势判断
    if latest > ma5 > ma10 > ma20:
        trend = "上升趋势"
        trend_score = 70
    elif latest < ma5 < ma10 < ma20:
        trend = "下降趋势"
        trend_score = 30
    elif latest > ma20 and ma5 > ma10:
        trend = "偏多"
        trend_score = 60
    elif latest < ma20 and ma5 < ma10:
        trend = "偏空"
        trend_score = 40
    else:
        trend = "震荡"
        trend_score = 50

    # MACD
    dif, dea, macd = calc_macd(close)
    macd_val = macd.iloc[-1]
    macd_prev = macd.iloc[-2]
    macd_cross = "金叉" if macd_val > 0 and macd_prev <= 0 else ("死叉" if macd_val < 0 and macd_prev >= 0 else "无叉")

    # MACD score
    if macd_val > 0 and dif.iloc[-1] > 0:
        macd_score = 65
    elif macd_val < 0 and dif.iloc[-1] < 0:
        macd_score = 35
    else:
        macd_score = 50

    # RSI
    rsi = calc_rsi(close, 14)
    rsi_val = rsi.iloc[-1]
    if rsi_val > 75:
        rsi_status = "超买"
        rsi_score = 30
    elif rsi_val < 25:
        rsi_status = "超卖"
        rsi_score = 70
    elif rsi_val > 60:
        rsi_status = "偏强"
        rsi_score = 60
    elif rsi_val < 40:
        rsi_status = "偏弱"
        rsi_score = 40
    else:
        rsi_status = "中性"
        rsi_score = 50

    # 布林带
    boll_mid = close.rolling(20).mean().iloc[-1]
    boll_std = close.rolling(20).std().iloc[-1]
    boll_upper = boll_mid + 2 * boll_std
    boll_lower = boll_mid - 2 * boll_std
    boll_pos = (latest - boll_lower) / (boll_upper - boll_lower) * 100 if boll_upper > boll_lower else 50

    if latest < boll_lower:
        boll_status = "布林下轨"
        boll_score = 65
    elif latest > boll_upper:
        boll_status = "布林上轨"
        boll_score = 35
    else:
        boll_status = f"布林中轨({boll_pos:.0f}%)"
        boll_score = 50

    # 综合技术分
    tech_score = int(trend_score * 0.4 + macd_score * 0.3 + rsi_score * 0.15 + boll_score * 0.15)

    return {
        "score": tech_score,
        "trend": trend,
        "ma5": round(ma5, 0), "ma10": round(ma10, 0), "ma20": round(ma20, 0),
        "ma60": round(ma60, 0) if ma60 else None,
        "latest": round(latest, 0),
        "rsi": round(rsi_val, 1),
        "rsi_status": rsi_status,
        "macd": round(macd_val, 0),
        "macd_cross": macd_cross,
        "boll_status": boll_status,
        "boll_upper": round(boll_upper, 0),
        "boll_lower": round(boll_lower, 0),
        "boll_mid": round(boll_mid, 0),
        "detail": f"{trend} | RSI {rsi_status} | MACD {macd_cross} | {boll_status}"
    }

# ===================== 宏观+成本分析 =====================

def analyze_macro(pta_future, pta_spot, px_price, brent_price, warehouse_receipt) -> dict:
    """宏观+成本面分析"""
    score = 50
    status = "中性"
    details = []

    # 1. 成本利润分析
    if px_price:
        cost_low = px_price * 0.655 + 600
        cost_high = px_price * 0.655 + 1000
        mid_cost = (cost_low + cost_high) / 2
    else:
        cost_low = cost_high = mid_cost = None

    if pta_spot and mid_cost:
        margin = pta_spot - mid_cost
        margin_pct = margin / mid_cost * 100
        details.append(f"现货-成本差:{margin:+.0f}({margin_pct:+.1f}%)")

        if margin > 300:
            status = "高估"
            score = 75
        elif margin > 150:
            status = "偏贵"
            score = 60
        elif margin < -300:
            status = "低估"
            score = 25
        elif margin < -150:
            status = "偏宜"
            score = 40
        else:
            status = "中性"
            score = 50
    else:
        margin = None

    # 2. 期货vs现货升贴水
    if pta_future and pta_spot:
        basis = pta_future - pta_spot
        details.append(f"基差:{basis:+.0f}")
        if basis > 200:
            details.append("期货升水偏多")
            score = min(80, score + 5)
        elif basis < -200:
            details.append("期货贴水偏空")
            score = max(20, score - 5)

    # 3. 布伦特方向
    if brent_price:
        if brent_price > 80:
            details.append("布伦特>80高油价")
            score = min(80, score + 3)
        elif brent_price < 65:
            details.append("布伦特<65低油价")
            score = max(20, score - 3)

    # 4. 仓单变化
    if warehouse_receipt:
        details.append(f"仓单:{warehouse_receipt:.0f}吨")
        # 仓单变化需要对比前一天，暂时用绝对值判断
        if warehouse_receipt > 150000:
            details.append("仓单高=供应充足")
            score = max(20, score - 5)
        elif warehouse_receipt < 100000:
            details.append("仓单低=去库偏多")
            score = min(80, score + 5)

    return {
        "score": score,
        "status": status,
        "px_price": px_price,
        "cost_low": round(cost_low, 0) if cost_low else None,
        "cost_high": round(cost_high, 0) if cost_high else None,
        "margin": round(margin, 0) if margin is not None else None,
        "warehouse_receipt": warehouse_receipt,
        "detail": " | ".join(details) if details else "数据不足"
    }

# ===================== 三维度综合信号 =====================

def generate_signal(pta_future, tech, macro, options_info) -> dict:
    """三维度综合打分"""
    tech_score = tech["score"]
    macro_score = macro["score"]

    # 权重：平静期 macro=0.4 tech=0.4 options=0.2
    # 杀期权阶段 macro=0.3 tech=0.3 options=0.4
    # 当前默认用平静期
    w_macro = 0.4
    w_tech = 0.4
    w_options = 0.2

    # 期权分暂用固定值（待IV曲面接入后更新）
    options_score = 50

    total_score = int(
        macro_score * w_macro +
        tech_score * w_tech +
        options_score * w_options
    )

    # 信号判定
    if total_score >= 65:
        signal = "做多"
        emoji = "🟢"
        confidence = "高" if total_score >= 75 else "中"
    elif total_score <= 35:
        signal = "做空"
        emoji = "🔴"
        confidence = "高" if total_score <= 25 else "中"
    else:
        signal = "观望"
        emoji = "⚪️"
        confidence = "低"

    # 关键位提醒
    warnings = []
    if pta_future and macro["cost_high"]:
        if pta_future > macro["cost_high"] * 1.05:
            warnings.append("⚠️ 期货高于成本上限5%+，注意高估风险")
        if pta_future < macro["cost_low"] * 0.95:
            warnings.append("⚠️ 期货低于成本下限5%-，低位支撑")

    if tech["rsi_val"] > 75 if "rsi_val" in tech else False:
        warnings.append("⚠️ RSI超买")
    if tech["rsi_val"] < 25 if "rsi_val" in tech else False:
        warnings.append("⚠️ RSI超卖")

    return {
        "signal": signal,
        "emoji": emoji,
        "score": total_score,
        "confidence": confidence,
        "macro_score": macro_score,
        "tech_score": tech_score,
        "options_score": options_score,
        "weights": f"宏观{w_macro}/技术{w_tech}/期权{w_options}",
        "warnings": warnings,
        "timestamp": datetime.now().isoformat()
    }

# ===================== 主分析函数 =====================

def full_analysis() -> dict:
    """完整三维度分析"""
    print("[分析] 开始获取数据...")

    # 1. 实时数据
    quote = get_pta_realtime()
    brent = get_brent()
    px = get_px_price()
    pta_spot = get_pta_spot()
    options = get_ta_options_info()
    warehouse = get_warehouse_receipt()

    pta_future = quote["price"] if quote else None

    print(f"[数据] PTA={pta_future} 布伦特={brent['price'] if brent else 'N/A'} PX={px} 现货={pta_spot}")

    # 2. 技术面
    df_daily = get_pta_daily(60)
    tech = analyze_technical(df_daily)
    print(f"[技术] {tech['detail']}")

    # 3. 宏观成本面
    macro = analyze_macro(pta_future, pta_spot, px, brent['price'] if brent else None, warehouse)
    print(f"[宏观] {macro['detail']}")

    # 4. 综合信号
    signal = generate_signal(pta_future, tech, macro, options)

    return {
        "signal": signal,
        "quote": quote,
        "brent": brent,
        "cost": {
            "px_price": px,
            "pta_spot": pta_spot,
            "pta_future": pta_future,
            "cost_low": macro.get("cost_low"),
            "cost_high": macro.get("cost_high"),
            "margin": macro.get("margin"),
        },
        "macro": macro,
        "tech": tech,
        "options": options,
        "warehouse_receipt": warehouse,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

if __name__ == "__main__":
    result = full_analysis()
    print("\n===== 综合信号 =====")
    s = result["signal"]
    print(f"{s['emoji']} {s['signal']} (得分:{s['score']} 置信:{s['confidence']})")
    print(f"   宏观:{s['macro_score']} 技术:{s['tech_score']} 期权:{s['options_score']}")
    print(f"   权重: {s['weights']}")
    if s['warnings']:
        for w in s['warnings']:
            print(f"   {w}")

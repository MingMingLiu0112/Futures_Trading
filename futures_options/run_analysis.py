#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
期货技术分析 - 纯技术面 + 真实行情
东财API获取期货数据，本地计算技术指标，飞书推送
"""

import os
import sys
import json
import subprocess
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone

def now_beijing():
    return datetime.utcnow() + timedelta(hours=8)
from typing import Dict, List, Optional

# ============================================================
# 数据获取 - 新浪财经API (via AKShare)
# ============================================================

def http_get(url: str, headers: Dict = None, retries: int = 2) -> Optional[str]:
    """发起HTTP GET请求，curl + 重试"""
    default_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://finance.eastmoney.com/",
        "Accept": "application/json, text/plain, */*",
    }
    if headers:
        default_headers.update(headers)

    for attempt in range(retries + 1):
        try:
            cmd = ["curl", "-s", "--max-time", "15"]
            for k, v in default_headers.items():
                cmd += ["-H", f"{k}: {v}"]
            cmd.append(url)
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception as e:
            if attempt == retries:
                print(f"  HTTP请求失败: {e}")
    return None


# 备用：直接用品种代码查询主力合约K线
# 东财K线接口支持 secid=112.M0 格式
DIRECT_CONTRACTS = {
    "M": "112.M0", "I": "112.I0", "RB": "112.RB0",
    "HC": "112.HC0", "AU": "112.AU0", "AG": "112.AG0",
    "CU": "112.CU0", "AL": "112.AL0", "ZN": "112.ZN0",
    "NI": "112.NI0", "SN": "112.SN0", "RU": "112.RU0",
    "SC": "114.SC0", "BU": "112.BU0", "MA": "112.MA0",
    "TA": "112.TA0", "EG": "112.EG0", "V": "112.V0",
    "L": "112.L0", "PP": "112.PP0", "SR": "112.SR0",
    "CF": "112.CF0", "RM": "112.RM0", "OI": "112.OI0",
    "P": "112.P0", "Y": "112.Y0", "C": "112.C0",
    "JM": "112.JM0", "J": "112.J0", "ZC": "112.ZC0",
    "PG": "112.PG0", "SS": "112.SS0",
}


def get_futures_kline(symbol: str, count: int = 60) -> tuple:
    """
    获取期货数据：历史K线
    symbol格式: M2609, CU2605 等
    返回: (DataFrame, 合约代码)
    """
    try:
        import akshare as ak

        print(f"  获取K线: {symbol}...")
        df = ak.futures_zh_daily_sina(symbol=symbol)

        if df.empty or len(df.columns) == 0:
            print(f"  ⚠️ K线为空")
            return pd.DataFrame(), symbol

        rename_map = {
            '日期': 'date', 'date': 'date',
            '开盘': 'open', 'open': 'open',
            '最高': 'high', 'high': 'high',
            '最低': 'low', 'low': 'low',
            '收盘': 'close', 'close': 'close',
            '成交量': 'volume', 'volume': 'volume'
        }
        df = df.rename(columns=rename_map)

        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
            df = df.sort_values('date')

        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # 尝试获取实时价格替换今日收盘价
        current_price = _get_realtime_price(symbol)
        if current_price and current_price > 0:
            today_idx = df['date'].idxmax()
            df.loc[today_idx, 'close'] = current_price
            print(f"  实时价格: {current_price}")
        else:
            print(f"  K线收盘: {df['close'].iloc[-1]}")

        if len(df) > count:
            df = df.tail(count)

        print(f"  ✅ {len(df)}条 最新:{df['date'].iloc[-1].strftime('%Y-%m-%d')} 价:{df['close'].iloc[-1]}")
        return df, symbol

    except Exception as e:
        print(f"  失败: {e}")
        return pd.DataFrame(), symbol


def _get_realtime_price(symbol: str) -> Optional[float]:
    """用新浪财经API获取期货实时价格"""
    try:
        import subprocess, json
        
        # 新浪期货实时行情: nf_M2609
        letters = ''.join([c for c in symbol if c.isalpha()])
        nums = ''.join([c for c in symbol if c.isdigit()])
        # 格式: nf_M2609
        sina_code = f"nf_{letters}{nums}"
        
        url = f"https://hq.sinajs.cn/list={sina_code}"
        cmd = [
            "curl", "-s", "--max-time", "10",
            "-H", "User-Agent: Mozilla/5.0",
            "-H", "Referer: https://finance.sina.com.cn/",
            url
        ]
        result = subprocess.run(cmd, capture_output=True, encoding='gbk', errors='replace', timeout=15)
        if result.returncode != 0 or not result.stdout.strip():
            return None
        
        text = result.stdout.strip()
        # 格式: var hq_str_nf_M2609="豆粕2609,3003,2990,3020,2940,3003,2945,3003,..."
        if "hq_str_" not in text or "none" in text.lower():
            return None
        
        # 提取数据: name, open, close(结算价), high, low, ...
        import re
        match = re.search(r'"([^"]+)"', text)
        if not match:
            return None
        
        fields = match.group(1).split(",")
        if len(fields) < 10:
            return None
        
        # 第6个字段(index=5)是最新价
        price = float(fields[5])
        if price > 0:
            print(f"  新浪实时: {price}")
            return price
    except Exception as e:
        print(f"  新浪API失败: {e}")
    return None


def get_contract_name(contract_code: str, cn_name: str) -> str:
    """合约显示名: M2605 -> 豆粕2605"""
    if contract_code and len(contract_code) > 1:
        nums = ''.join([c for c in contract_code if c.isdigit()])
        if nums:
            # 取年份后4位，如 2609 -> 2609
            return f"{cn_name}{nums[-4:]}"
    return cn_name


# ============================================================
# 技术指标计算
# ============================================================

def calc_ma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n).mean()


def calc_ema(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(span=n, adjust=False).mean()


def calc_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = calc_ema(series, fast)
    ema_slow = calc_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def calc_rsi(series: pd.Series, n: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))
    avg_gain = gain.rolling(n).mean()
    avg_loss = loss.rolling(n).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_bollinger(series: pd.Series, n: int = 20, k: float = 2):
    mid = series.rolling(n).mean()
    std = series.rolling(n).std()
    upper = mid + k * std
    lower = mid - k * std
    return upper, mid, lower


def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14):
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def analyze_technicals(df: pd.DataFrame) -> Dict:
    """计算完整技术分析"""
    if df.empty or len(df) < 10:
        return {}

    close = df["close"]
    high = df["high"]
    low = df["low"]
    vol = df["volume"]

    # 均线
    ma5 = calc_ma(close, 5).iloc[-1]
    ma10 = calc_ma(close, 10).iloc[-1]
    ma20 = calc_ma(close, 20).iloc[-1]
    ma60 = calc_ma(close, min(60, len(df))).iloc[-1]

    # 均线方向
    ma5_prev = calc_ma(close, 5).iloc[-2]
    ma10_prev = calc_ma(close, 10).iloc[-2]
    ma20_prev = calc_ma(close, 20).iloc[-2]

    # MACD
    macd, signal, hist = calc_macd(close)
    macd_val = macd.iloc[-1]
    macd_signal = signal.iloc[-1]
    macd_hist = hist.iloc[-1]
    macd_hist_prev = hist.iloc[-2]

    # RSI
    rsi = calc_rsi(close).iloc[-1]

    # 布林带
    bb_upper, bb_mid, bb_lower = calc_bollinger(close)
    bb_upper_val = bb_upper.iloc[-1]
    bb_mid_val = bb_mid.iloc[-1]
    bb_lower_val = bb_lower.iloc[-1]

    # ATR
    atr = calc_atr(high, low, close).iloc[-1]

    # 成交量分析
    vol_ma5 = vol.rolling(5).mean().iloc[-1]
    vol_ratio = vol.iloc[-1] / vol_ma5 if vol_ma5 > 0 else 1.0

    # 涨跌
    close_cur = close.iloc[-1]
    close_prev = close.iloc[-2] if len(close) > 1 else close_cur
    change_pct = (close_cur - close_prev) / close_prev * 100

    # 关键价位
    high_20 = high.tail(20).max()
    low_20 = low.tail(20).min()
    high_60 = high.tail(60).max() if len(df) >= 60 else high_20
    low_60 = low.tail(60).min() if len(df) >= 60 else low_20

    return {
        "price": round(close_cur, 2),
        "change": round(change_pct, 2),
        "ma5": round(ma5, 2),
        "ma10": round(ma10, 2),
        "ma20": round(ma20, 2),
        "ma60": round(ma60, 2) if not pd.isna(ma60) else None,
        "ma5_dir": "up" if ma5 > ma5_prev else "down",
        "ma10_dir": "up" if ma10 > ma10_prev else "down",
        "ma20_dir": "up" if ma20 > ma20_prev else "down",
        "macd": round(macd_val, 2),
        "macd_signal": round(macd_signal, 2),
        "macd_hist": round(macd_hist, 2),
        "macd_cross": "金叉" if macd_hist > 0 and macd_hist_prev < 0 else ("死叉" if macd_hist < 0 and macd_hist_prev > 0 else "无"),
        "rsi": round(rsi, 1),
        "bb_upper": round(bb_upper_val, 2),
        "bb_mid": round(bb_mid_val, 2),
        "bb_lower": round(bb_lower_val, 2),
        "atr": round(atr, 2),
        "vol_ratio": round(vol_ratio, 2),
        "high_20": round(high_20, 2),
        "low_20": round(low_20, 2),
        "high_60": round(high_60, 2),
        "low_60": round(low_60, 2),
    }


def generate_signal(tech: Dict) -> Dict:
    """基于技术指标生成交易信号"""
    if not tech:
        return {"action": "数据不足", "confidence": "低", "signals": []}

    score = 0
    signals = []

    # MA多头排列
    if tech["ma5"] > tech["ma10"] > tech["ma20"]:
        score += 2
        signals.append("✅ MA多头排列（5>10>20）")
    elif tech["ma5"] < tech["ma10"] < tech["ma20"]:
        score -= 2
        signals.append("🔻 MA空头排列（5<10<20）")

    # 均线支撑/压力
    if tech["price"] > tech["ma5"]:
        score += 1
        signals.append("✅ 价格站上MA5")
    else:
        score -= 1
        signals.append("⚠️ 价格跌破MA5")

    if tech["price"] > tech["ma20"]:
        score += 1
        signals.append("✅ 价格站上MA20")
    else:
        score -= 1
        signals.append("⚠️ 价格跌破MA20")

    # MACD
    if tech["macd_cross"] == "金叉":
        score += 2
        signals.append("✅ MACD金叉")
    elif tech["macd_cross"] == "死叉":
        score -= 2
        signals.append("🔻 MACD死叉")

    if tech["macd_hist"] > 0:
        score += 1
        signals.append("✅ MACD柱正值")
    else:
        score -= 1
        signals.append("⚠️ MACD柱负值")

    # RSI
    rsi = tech["rsi"]
    if rsi > 75:
        score -= 1
        signals.append(f"⚠️ RSI超买({rsi})")
    elif rsi < 25:
        score += 1
        signals.append(f"✅ RSI超卖({rsi})")
    elif rsi > 65:
        signals.append(f"📊 RSI偏强({rsi})")
    elif rsi < 35:
        signals.append(f"📊 RSI偏弱({rsi})")
    else:
        signals.append(f"📊 RSI中性({rsi})")

    # 布林带位置
    if tech["price"] <= tech["bb_lower"] * 1.01:
        score += 1
        signals.append("✅ 触及布林下轨支撑")
    elif tech["price"] >= tech["bb_upper"] * 0.99:
        score -= 1
        signals.append("⚠️ 触及布林上轨压力")

    # 成交量
    if tech["vol_ratio"] > 1.5:
        signals.append(f"📊 成交量放大({tech['vol_ratio']}x)")
        if tech["change"] > 0: score += 1
        else: score -= 1
    elif tech["vol_ratio"] < 0.5:
        signals.append(f"📊 成交量萎缩({tech['vol_ratio']}x)")

    # 综合判断
    if score >= 3:
        action, action_emoji = "做多", "🟢"
    elif score <= -3:
        action, action_emoji = "做空", "🔴"
    else:
        action, action_emoji = "观望", "⚪"

    confidence = "高" if abs(score) >= 4 else ("中" if abs(score) >= 2 else "低")

    return {
        "score": score,
        "action": action,
        "action_emoji": action_emoji,
        "confidence": confidence,
        "signals": signals,
    }


# ============================================================
# 期货合约配置
# ============================================================

# 合约配置：AKShare合约代码 -> 中文显示名
FUTURES_CONFIG = {
    "RU2609": "橡胶2609",
    "P2609": "棕榈油2609",
    "Y2609": "豆油2609",
    "SM2605": "锰硅2605",
    "FU2605": "燃油2605",
    "PP2605": "聚丙烯2605",
    "JM2609": "焦煤2609",
    "I2609": "铁矿2609",
    "AP2610": "苹果2610",
    "SS2605": "不锈钢2605",
    "CF2609": "棉花2609",
    "LH2605": "生猪2605",
    "SP2609": "纸浆2609",
    "SA2609": "纯碱2609",
}

# 品种映射：品种代码 -> 中文名（用于AKShare调用）
FUTURES_MAP = {
    "M": "豆粕", "I": "铁矿石", "RB": "螺纹钢", "HC": "热轧卷板",
    "SS": "不锈钢", "AU": "黄金", "AG": "白银", "CU": "铜",
    "AL": "铝", "ZN": "锌", "NI": "镍", "SN": "锡", "RU": "橡胶",
    "SC": "原油", "BU": "沥青", "MA": "甲醇", "TA": "PTA",
    "EG": "乙二醇", "V": "PVC", "L": "塑料", "PP": "聚丙烯",
    "SR": "白糖", "CF": "棉花", "RM": "菜粕", "OI": "菜油",
    "P": "棕榈油", "Y": "豆油", "C": "玉米", "JM": "焦煤",
    "J": "焦炭", "ZC": "动力煤", "PG": "液化气",
    "SM": "锰硅", "FU": "燃油", "AP": "苹果", "LH": "生猪",
    "SP": "纸浆", "SA": "纯碱",
}

TARGET_SYMBOLS = list(FUTURES_CONFIG.keys())


# ============================================================
# 飞书推送
# ============================================================

FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK", "")


def get_futures_secid(symbol: str, futures_list: List[Dict]) -> Optional[str]:
    """根据品种代码找东财secid"""
    symbol = symbol.upper()
    for item in futures_list:
        code = item.get("f12", "")
        name = item.get("f14", "")
        # 匹配主力合约（名字包含品种代码）
        if symbol in code.upper():
            return f"112.{code}"
    return None


def build_feishu_card(results: List[Dict]) -> Dict:
    """构建飞书卡片"""
    long_cnt = sum(1 for r in results if r.get("signal", {}).get("action") == "做多")
    short_cnt = sum(1 for r in results if r.get("signal", {}).get("action") == "做空")
    watch_cnt = len(results) - long_cnt - short_cnt

    if long_cnt > short_cnt:
        summary_emoji = "🟢"
    elif short_cnt > long_cnt:
        summary_emoji = "🔴"
    else:
        summary_emoji = "⚪"

    summary = f"{summary_emoji} 做多{long_cnt} | 做空{short_cnt} | 观望{watch_cnt}"

    now_str = now_beijing().strftime("%Y-%m-%d %H:%M")

    # 构建简洁表格
    table_lines = ["品种|信号|价格|涨跌|RSI", "---|---|---|---|---"]
    for r in results:
        tech = r.get("tech", {})
        sig = r.get("signal", {})
        if not tech:
            continue
        emoji = sig.get("action_emoji", "⚪")
        name = r.get("display_name", r.get("name", ""))
        action = sig.get("action", "观望")
        price = tech.get("price", 0)
        change = tech.get("change", 0)
        rsi = tech.get("rsi", 0)
        arrow = "📈" if change >= 0 else "📉"
        table_lines.append(f"{emoji}{name}|{action}|{price}|{arrow}{change:+.2f}%|{rsi:.1f}")

    table_md = "\n".join(table_lines)

    elements = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"⏰ **{now_str}** · {summary}\n\n{table_md}"
            }
        }
    ]

    for r in results:
        tech = r.get("tech", {})
        sig = r.get("signal", {})
        if not tech:
            continue

        action = sig.get("action", "观望")
        emoji = sig.get("action_emoji", "⚪")
        arrow = "📈" if tech.get("change", 0) >= 0 else "📉"

        # MA排列
        if tech["ma5"] > tech["ma10"] > tech["ma20"]:
            ma_text = "多头↑"
        elif tech["ma5"] < tech["ma10"] < tech["ma20"]:
            ma_text = "空头↓"
        else:
            ma_text = "纠缠"

        # RSI状态
        rsi = tech["rsi"]
        if rsi >= 70:
            rsi_text = f"⚠️超买{rsi}"
        elif rsi <= 30:
            rsi_text = f"⚠️超卖{rsi}"
        else:
            rsi_text = f"正常{rsi}"

        # MACD状态
        macd_text = sig.get("macd_cross", "无")

        # 成交量
        vr = tech["vol_ratio"]
        vol_text = "放量" if vr > 1.2 else ("缩量" if vr < 0.8 else "正常")

        # 信号列表
        sig_list = sig.get("signals", [])
        sig_md = "\n".join([f"• {s}" for s in sig_list[:5]]) if sig_list else "• 暂无明显信号"

        content = (
            f"{emoji} **{r['display_name']}** {arrow} {tech['change']:+.2f}%\n\n"
            f"💰 **收盘 {tech['price']}** | {ma_text}\n\n"
            f"📊 **技术指标**\n"
            f"• MA5: {tech['ma5']} / MA20: {tech['ma20']}\n"
            f"• RSI: {rsi_text} | MACD: {macd_text}\n"
            f"• 布林带: {tech['bb_lower']}~{tech['bb_upper']}\n"
            f"• ATR: {tech['atr']} | 成交量: {vol_text}({vr}x)\n\n"
            f"🎯 **操作**: **{action}**（置信度:{sig.get('confidence','N/A')}）\n\n"
            f"📋 **信号明细**\n{sig_md}"
        )

        elements.append({"tag": "hr"})
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": content}})

    elements.append({"tag": "hr"})
    elements.append({
        "tag": "note",
        "elements": [{"tag": "plain_text", "content": "⚠️ 仅供参考，不构成投资建议"}]
    })

    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": "📊 期货技术分析日度信号"},
                "template": "purple"
            },
            "elements": elements
        }
    }


def push_feishu(card: Dict) -> bool:
    """推送飞书"""
    if not FEISHU_WEBHOOK:
        print("⚠️ 未配置 FEISHU_WEBHOOK")
        return False
    try:
        import requests
        resp = requests.post(FEISHU_WEBHOOK, json=card, timeout=10)
        result = resp.json()
        ok = result.get("code") == 0 or result.get("StatusCode") == 0
        if ok:
            print("✅ 飞书推送成功")
        else:
            print(f"⚠️ 推送失败: {result}")
        return ok
    except Exception as e:
        print(f"⚠️ 推送异常: {e}")
        return False


# ============================================================
# 主程序
# ============================================================

def main():
    print("=" * 60)
    print("📊 期货技术分析")
    print(f"⏰ {now_beijing().strftime('%Y-%m-%d %H:%M:%S')} 北京时间")
    print("=" * 60)

    # 遍历目标合约
    results = []
    for contract_code in TARGET_SYMBOLS:
        display_name = FUTURES_CONFIG[contract_code]
        # 提取品种代码: M2609 -> M
        letters = ''.join([c for c in contract_code if c.isalpha()])
        cn_name = FUTURES_MAP.get(letters, letters)
        print(f"\n📊 正在分析 {display_name}({contract_code})...")

        # AKShare直接用合约代码
        df, actual_contract = get_futures_kline(contract_code, count=60)
        # 用实际查询到的合约代码
        if actual_contract and actual_contract != contract_code:
            display_name = f"{cn_name}{actual_contract[-4:]}"
        if df.empty:
            print(f"  ⚠️ 获取K线数据失败，跳过")
            continue

        # 技术分析
        tech = analyze_technicals(df)
        sig = generate_signal(tech)

        print(f"  信号: {sig['action']} | MA5={tech['ma5']} | RSI={tech['rsi']} | MACD={sig.get('macd_cross','无')}")

        results.append({
            "symbol": letters,
            "name": cn_name,
            "contract": contract_code,
            "display_name": display_name,
            "tech": tech,
            "signal": sig,
        })

    # 3. 输出结果
    if results:
        print("\n" + "=" * 60)
        print("📊 分析结果汇总")
        print("=" * 60)
        for r in results:
            sig = r["signal"]
            tech = r["tech"]
            print(f"\n{r['display_name']}: {sig['action_emoji']} {sig['action']} | 价格:{tech['price']} | 涨跌:{tech['change']:+.2f}%")
            print(f"  MA5:{tech['ma5']} MA20:{tech['ma20']} RSI:{tech['rsi']} MACD:{sig.get('macd_cross')}")

        # 4. 飞书推送
        print("\n📤 正在推送到飞书...")
        card = build_feishu_card(results)
        push_feishu(card)
    else:
        print("\n⚠️ 没有可用的分析结果")

    print("\n✅ 分析完成!")


if __name__ == "__main__":
    main()

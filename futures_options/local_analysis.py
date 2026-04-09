#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
期货技术分析 - 本地运行版
支持实时行情 + 技术指标 + 飞书推送
直接运行: python3 local_analysis.py
"""

import os
import sys
import re
import json
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ============================================================
# 配置区 - 按需修改
# ============================================================

FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK", "")

# 合约配置：新浪代码 -> 中文显示名
FUTURES_CONFIG = {
    "nf_M2609":  "豆粕2609",
    "nf_RB2610": "螺纹钢2610",
    "nf_HC2610": "热卷2610",
    "nf_I2610":  "铁矿石2610",
    "nf_JM2609": "焦煤2609",
    "nf_J2609":  "焦炭2609",
    "nf_RU2609": "橡胶2609",
    "nf_AU2612": "黄金2612",
    "nf_CU2610": "沪铜2610",
    "nf_NI2610": "沪镍2610",
    "nf_P2610":  "棕榈油2610",
}

# ============================================================
# 新浪实时行情
# ============================================================

def get_realtime_batch(codes: list) -> dict:
    """批量获取新浪期货实时行情"""
    url = f"https://hq.sinajs.cn/list={','.join(codes)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://finance.sina.com.cn/",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = 'gbk'
        text = resp.text.strip()
        
        result = {}
        # var hq_str_nf_M2609="豆粕2609,开盘,最高,最低,最新,买价,卖价,持仓量,成交量,..."
        # 字段: 0名称 1开盘 2前结算 3最高 4最低 5最新/收盘 6买价 7卖价 8持仓量 9成交量 10...
        for match in re.finditer(r'hq_str_(nf_\w+)="([^"]+)"', text):
            code = match.group(1)
            fields = match.group(2).split(",")
            if len(fields) >= 6:
                try:
                    result[code] = {
                        "name": fields[0],
                        "open": float(fields[1]) if fields[1] else 0,
                        "prev_settle": float(fields[2]) if fields[2] else 0,
                        "high": float(fields[3]) if fields[3] else 0,
                        "low": float(fields[4]) if fields[4] else 0,
                        "price": float(fields[5]) if fields[5] else 0,  # 最新价
                        "volume": float(fields[9]) if len(fields) > 9 and fields[9] else 0,
                        "settle": float(fields[10]) if len(fields) > 10 and fields[10] else 0,
                    }
                except (ValueError, IndexError):
                    pass
        return result
    except Exception as e:
        print(f"❌ 获取实时行情失败: {e}")
        return {}


# ============================================================
# 新浪历史K线
# ============================================================

def get_kline_sina(symbol: str, count: int = 60) -> pd.DataFrame:
    """获取新浪期货日K线"""
    # 转换: nf_M2609 -> M2609
    code = symbol.replace("nf_", "")
    url = f"https://stock.finance.sina.com.cn/futures/api/jsonp.php/var%20_{symbol}=/FuturesService.getFutures?symbol={code}"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://finance.sina.com.cn/",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        text = resp.text.strip()
        # 解析 JSONP: var _nf_M2609=(...)
        m = re.search(r'=(\[.*?\]);', text, re.DOTALL)
        if not m:
            # 备用方法
            return _get_kline_akshare(symbol)
        
        data = json.loads(m.group(1))
        if not data:
            return _get_kline_akshare(symbol)
        
        df = pd.DataFrame(data)
        df['date'] = pd.to_datetime(df['date'])
        df['open'] = pd.to_numeric(df['open'], errors='coerce')
        df['high'] = pd.to_numeric(df['high'], errors='coerce')
        df['low'] = pd.to_numeric(df['low'], errors='coerce')
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
        
        if len(df) > count:
            df = df.tail(count)
        return df
    except Exception as e:
        print(f"  K线获取失败({symbol}), 尝试AKShare: {e}")
        return _get_kline_akshare(symbol)


def _get_kline_akshare(symbol: str, count: int = 60) -> pd.DataFrame:
    """AKShare备用获取K线"""
    try:
        import akshare as ak
        code = symbol.replace("nf_", "")
        df = ak.futures_zh_daily_sina(symbol=code)
        if df.empty:
            return pd.DataFrame()
        
        rename = {'日期': 'date', '开盘': 'open', '最高': 'high', '最低': 'low', '收盘': 'close', '成交量': 'volume'}
        df = df.rename(columns=rename)
        for c in ['open', 'high', 'low', 'close', 'volume']:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce')
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        df = df.sort_values('date')
        
        if len(df) > count:
            df = df.tail(count)
        return df
    except Exception as e:
        print(f"  AKShare也失败: {e}")
        return pd.DataFrame()


# ============================================================
# 技术指标
# ============================================================

def calc_ma(s, n): return s.rolling(n).mean()
def calc_ema(s, n): return s.ewm(span=n, adjust=False).mean()

def analyze(df: pd.DataFrame, realtime_price: float = None) -> dict:
    if df.empty or len(df) < 10:
        return {}
    
    close = df['close'].copy()
    high = df['high']
    low = df['low']
    vol = df['volume']
    
    # 替换今日收盘价为实时价
    if realtime_price and realtime_price > 0:
        close.iloc[-1] = realtime_price
    
    ma5 = calc_ma(close, 5).iloc[-1]
    ma10 = calc_ma(close, 10).iloc[-1]
    ma20 = calc_ma(close, 20).iloc[-1]
    
    # MACD
    ema12 = calc_ema(close, 12)
    ema26 = calc_ema(close, 26)
    macd = ema12 - ema26
    sig = calc_ema(macd, 9)
    hist = macd - sig
    macd_val, sig_val, hist_val = macd.iloc[-1], sig.iloc[-1], hist.iloc[-1]
    macd_prev = hist.iloc[-2]
    macd_cross = "金叉" if hist_val > 0 and macd_prev < 0 else ("死叉" if hist_val < 0 and macd_prev > 0 else "无")
    
    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rsi = (100 - 100 / (1 + gain / loss)).iloc[-1]
    
    # 布林带
    bb_mid = calc_ma(close, 20).iloc[-1]
    bb_std = close.rolling(20).std().iloc[-1]
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    
    # ATR
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().iloc[-1]
    
    # 成交量
    vol_ma5 = vol.rolling(5).mean().iloc[-1]
    vol_ratio = vol.iloc[-1] / vol_ma5 if vol_ma5 > 0 else 1.0
    
    # 涨跌
    cur = close.iloc[-1]
    prev = close.iloc[-2] if len(close) > 1 else cur
    change = (cur - prev) / prev * 100
    
    # 综合打分
    score = 0
    signals = []
    
    if ma5 > ma10 > ma20:
        score += 2
        signals.append("✅ MA多头排列")
    elif ma5 < ma10 < ma20:
        score -= 2
        signals.append("🔻 MA空头排列")
    
    if cur > ma5: score += 1; signals.append("✅ 价格站上MA5")
    else: score -= 1; signals.append("⚠️ 价格跌破MA5")
    
    if cur > ma20: score += 1; signals.append("✅ 价格站上MA20")
    else: score -= 1; signals.append("⚠️ 价格跌破MA20")
    
    if macd_cross == "金叉": score += 2; signals.append("✅ MACD金叉")
    elif macd_cross == "死叉": score -= 2; signals.append("🔻 MACD死叉")
    
    if hist_val > 0: score += 1
    else: score -= 1
    
    if rsi > 75: score -= 1; signals.append(f"⚠️ RSI超买({rsi:.1f})")
    elif rsi < 25: score += 1; signals.append(f"✅ RSI超卖({rsi:.1f})")
    else: signals.append(f"📊 RSI中性({rsi:.1f})")
    
    if vol_ratio > 1.5:
        signals.append(f"📊 成交量放大({vol_ratio:.1f}x)")
        if change > 0: score += 1
    
    action = "做多" if score >= 3 else ("做空" if score <= -3 else "观望")
    emoji = {"做多": "🟢", "做空": "🔴", "观望": "⚪"}.get(action, "⚪")
    confidence = "高" if abs(score) >= 4 else ("中" if abs(score) >= 2 else "低")
    
    return {
        "price": round(cur, 2),
        "change": round(change, 2),
        "ma5": round(ma5, 2), "ma10": round(ma10, 2), "ma20": round(ma20, 2),
        "rsi": round(rsi, 1),
        "macd_cross": macd_cross,
        "bb_upper": round(bb_upper, 2), "bb_lower": round(bb_lower, 2),
        "atr": round(atr, 2),
        "vol_ratio": round(vol_ratio, 2),
        "score": score,
        "action": action,
        "emoji": emoji,
        "confidence": confidence,
        "signals": signals,
    }


# ============================================================
# 飞书推送
# ============================================================

def push_feishu(results: list) -> bool:
    if not FEISHU_WEBHOOK:
        print("⚠️ 未设置 FEISHU_WEBHOOK")
        return False
    
    long_c = sum(1 for r in results if r["signal"]["action"] == "做多")
    short_c = sum(1 for r in results if r["signal"]["action"] == "做空")
    watch_c = len(results) - long_c - short_c
    emoji_sum = "🟢" if long_c > short_c else ("🔴" if short_c > long_c else "⚪")
    summary = f"{emoji_sum} 做多{long_c} | 做空{short_c} | 观望{watch_c}"
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    elements = [{"tag": "div", "text": {"tag": "lark_md", "content": f"⏰ **{now_str}** · {summary}"}}]
    
    for r in results:
        s = r["signal"]
        t = r["tech"]
        if not t:
            continue
        
        a = s["action"]
        e = s["emoji"]
        arrow = "📈" if t["change"] >= 0 else "📉"
        
        if t["ma5"] > t["ma10"] > t["ma20"]: ma_text = "多头↑"
        elif t["ma5"] < t["ma10"] < t["ma20"]: ma_text = "空头↓"
        else: ma_text = "纠缠"
        
        rsi = t["rsi"]
        rsi_text = f"⚠️超买{rsi}" if rsi >= 70 else (f"⚠️超卖{rsi}" if rsi <= 30 else f"正常{rsi}")
        
        vr = t["vol_ratio"]
        vol_text = "放量" if vr > 1.2 else ("缩量" if vr < 0.8 else "正常")
        
        sig_md = "\n".join([f"• {x}" for x in s["signals"][:5]]) or "• 暂无明显信号"
        
        content = (
            f"{e} **{r['display']}** {arrow} {t['change']:+.2f}%\n\n"
            f"💰 **收盘 {t['price']}** | {ma_text}\n\n"
            f"📊 **技术指标**\n"
            f"• MA5: {t['ma5']} / MA20: {t['ma20']}\n"
            f"• RSI: {rsi_text} | MACD: {s['macd_cross']}\n"
            f"• 布林带: {t['bb_lower']}~{t['bb_upper']}\n"
            f"• ATR: {t['atr']} | 成交量: {vol_text}({vr}x)\n\n"
            f"🎯 **操作**: **{a}**（置信度:{s['confidence']}）\n\n"
            f"📋 **信号明细**\n{sig_md}"
        )
        
        elements += [{"tag": "hr"}, {"tag": "div", "text": {"tag": "lark_md", "content": content}}]
    
    elements += [{"tag": "hr"}, {"tag": "note", "elements": [{"tag": "plain_text", "content": "⚠️ 仅供参考，不构成投资建议"}]}]
    
    card = {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": "📊 期货技术分析日度信号"}, "template": "purple"},
            "elements": elements
        }
    }
    
    try:
        resp = requests.post(FEISHU_WEBHOOK, json=card, timeout=10)
        result = resp.json()
        ok = result.get("code") == 0 or result.get("StatusCode") == 0
        print("✅ 飞书推送成功" if ok else f"⚠️ 推送失败: {result}")
        return ok
    except Exception as e:
        print(f"⚠️ 推送异常: {e}")
        return False


# ============================================================
# 主程序
# ============================================================

def main():
    print("=" * 60)
    print("📊 期货技术分析（本地版）")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    codes = list(FUTURES_CONFIG.keys())
    
    # 1. 获取实时行情
    print("\n🌐 获取实时行情...")
    realtime = get_realtime_batch(codes)
    success_count = len(realtime)
    print(f"✅ 获取到 {success_count}/{len(codes)} 个品种实时价格")
    
    # 2. 分析每个品种
    results = []
    for code, display in FUTURES_CONFIG.items():
        print(f"\n📊 分析 {display}...")
        
        # 实时价格
        info = realtime.get(code, {})
        price = info.get("price", 0)
        if price > 0:
            print(f"  实时价格: {price}")
        else:
            print(f"  ⚠️ 无实时价格")
        
        # 历史K线
        df = get_kline_sina(code, count=60)
        if df.empty:
            print(f"  ⚠️ K线数据为空，跳过")
            continue
        
        # 用实时价格替换收盘价
        tech = analyze(df, price)
        if not tech:
            print(f"  ⚠️ 技术分析失败，跳过")
            continue
        
        s = tech
        print(f"  信号: {s['emoji']}{s['action']} | 价格:{s['price']} | RSI:{s['rsi']} | MACD:{s['macd_cross']}")
        
        results.append({
            "code": code,
            "display": display,
            "tech": tech,
            "signal": s,
            "realtime_price": price if price > 0 else s['price'],
        })
    
    # 3. 汇总
    if results:
        print("\n" + "=" * 60)
        print("📊 分析结果汇总")
        print("=" * 60)
        for r in results:
            s = r["signal"]
            t = r["tech"]
            print(f"\n{r['display']}: {s['emoji']}{s['action']} | 价格:{t['price']} | 涨跌:{t['change']:+.2f}%")
            print(f"  MA5:{t['ma5']} MA20:{t['ma20']} RSI:{t['rsi']} MACD:{s['macd_cross']}")
        
        # 4. 飞书推送
        print("\n📤 推送到飞书...")
        push_feishu(results)
    else:
        print("\n⚠️ 没有可用结果")
    
    print("\n✅ 完成!")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书推送脚本 - 定时发送PTA分析报告
"""
import requests
import json
import sys
from datetime import datetime

WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/8148922b-04f5-469f-994e-ae3e17d6b256"

def get_data():
    try:
        import requests
        r = requests.get("http://localhost:8000/api/pta/signal", timeout=10)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return None

def send_report(data):
    if not data:
        print("无法获取数据")
        return False

    now = datetime.now().strftime("%H:%M")
    quote = data.get("quote", {})
    cost = data.get("cost", {})
    opts = data.get("options", {})

    price = quote.get("last_price", 0)
    chg = quote.get("change_pct", 0)
    high = quote.get("high", 0)
    low = quote.get("low", 0)
    vol = quote.get("volume", 0)
    oi = quote.get("open_interest", 0)

    brent = cost.get("brent_usd", 0)
    px = cost.get("px_cny", 0)
    pta_spot = cost.get("pta_spot", 0)
    cost_low = cost.get("pta_cost_low", 0)
    cost_high = cost.get("pta_cost_high", 0)
    margin = cost.get("margin", 0)

    signal = data.get("signal", "未知")
    score = data.get("score", 0)
    confidence = data.get("confidence", "低")
    expiry = opts.get("expiry", "")

    # 信号颜色
    if signal == "做多":
        emoji = "🟢"
        signal_text = "做多"
    elif signal == "做空":
        emoji = "🔴"
        signal_text = "做空"
    else:
        emoji = "⚪️"
        signal_text = "观望"

    content = f"""{emoji} **PTA 期权分析** | {now}

**期货行情 TA0**
• 最新价: ¥{price:.0f}  ({chg:+.2f}%)
• 今日: ¥{high:.0f} / ¥{low:.0f}
• 成交量: {vol/1e4:.0f}万手  持仓: {oi/1e4:.0f}万手

**成本监控**
• PX现货: ¥{px:.0f}
• PTA成本: ¥{cost_low:.0f}~¥{cost_high:.0f}
• 现货-成本差: ¥{margin:.0f}

**布伦特原油**: ${brent:.1f}

**综合信号**: {signal_text} {emoji} (得分{score}, 置信度{confidence})
**期权链**: {opts.get('count', 0)}条, 到期{expiry}"""

    payload = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": f"📊 PTA 分析 {now}",
                    "content": [[{"tag": "text", "text": content}]]
                }
            }
        }
    }

    try:
        r = requests.post(WEBHOOK, json=payload, timeout=10)
        result = r.json()
        if result.get("code") == 0:
            print(f"[OK] {now} 推送成功")
            return True
        else:
            print(f"[FAIL] {result}")
            return False
    except Exception as e:
        print(f"[ERROR] {e}")
        return False

if __name__ == "__main__":
    data = get_data()
    send_report(data)

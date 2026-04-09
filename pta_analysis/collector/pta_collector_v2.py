#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA期权数据采集器 v2 - 基于郑商所历史接口
优势：阿里云服务器可直接访问，无需本地代理
数据：持仓量、IV隐波、DELTA、成交量等完整T链数据
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta

# 加载config.env
_config_env_path = os.path.join(os.path.dirname(__file__), "config.env")
if os.path.exists(_config_env_path):
    with open(_config_env_path, "r") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

# ============================================================
# 配置
# ============================================================
CONFIG = {
    "github_token": os.environ.get("GITHUB_TOKEN", ""),
    "github_repo": "MingMingLiu0112/pta-data",
    "github_branch": "main",
    "feishu_webhook": os.environ.get("FEISHU_WEBHOOK", ""),
}

# ============================================================
# 工具函数
# ============================================================
def get_session():
    """判断交易时段"""
    hour = datetime.now().hour
    if 8 <= hour < 11:
        return "morning"
    elif 11 <= hour < 15:
        return "afternoon"
    elif 20 <= hour < 23 or 0 <= hour < 2:
        return "night"
    return "off"

def install_deps():
    """安装依赖"""
    required = ["akshare", "requests"]
    for lib in required:
        try:
            __import__(lib)
        except ImportError:
            subprocess_check_call([sys.executable, "-m", "pip", "install", lib, "-U"])

def subprocess_check_call(cmd):
    import subprocess
    subprocess.check_call(cmd)

# ============================================================
# 数据采集
# ============================================================
def collect_pta_options(date_str=None):
    """
    采集PTA期权完整数据（持仓量/IV/DELTA/成交量）
    date_str: 格式YYYYMMDD，默认昨天
    """
    import akshare as ak

    if date_str is None:
        # 默认取最近交易日（昨天）
        yesterday = datetime.now() - timedelta(days=1)
        date_str = yesterday.strftime("%Y%m%d")

    result = {
        "date": date_str,
        "timestamp": datetime.now().isoformat(),
        "session": get_session(),
    }

    # 采集PTA期权（合并数据，用DELTA区分认购认沽）
    try:
        all_df = ak.option_hist_czce(symbol="PTA期权", trade_date=date_str)
        if not all_df.empty:
            # DELTA > 0.5 → 认购期权
            call_df = all_df[all_df["DELTA"] > 0.5]
            # DELTA < 0.5 → 认沽期权
            put_df = all_df[all_df["DELTA"] < 0.5]

            result["call"] = {
                "count": len(call_df),
                "total_volume": int(call_df["成交量(手)"].sum()),
                "total_open_interest": int(call_df["持仓量"].sum()),
                "top_strikes": get_top_strikes(call_df),
                "iv_stats": get_iv_stats(call_df),
                "delta_stats": get_delta_stats(call_df),
                "sample": call_df.head(5).to_dict("records"),
            }
            result["put"] = {
                "count": len(put_df),
                "total_volume": int(put_df["成交量(手)"].sum()),
                "total_open_interest": int(put_df["持仓量"].sum()),
                "top_strikes": get_top_strikes(put_df),
                "iv_stats": get_iv_stats(put_df),
                "delta_stats": get_delta_stats(put_df),
                "sample": put_df.head(5).to_dict("records"),
            }
    except Exception as e:
        result["error"] = str(e)

    # 计算PCR
    if "call" in result and "put" in result:
        call_oi = result["call"].get("total_open_interest", 0)
        put_oi = result["put"].get("total_open_interest", 0)
        call_vol = result["call"].get("total_volume", 0)
        put_vol = result["put"].get("total_volume", 0)
        result["pcr"] = {
            "position_pcr": round(put_oi / call_oi, 4) if call_oi > 0 else None,
            "volume_pcr": round(put_vol / call_vol, 4) if call_vol > 0 else None,
        }

    return result

def parse_strike_from_code(code):
    """从合约代码解析行权价，如TA505C4300→4300"""
    import re
    m = re.search(r'[CP](\d+)$', str(code))
    return int(m.group(1)) if m else None

def get_top_strikes(df, top_n=5):
    """获取持仓量最大的行权价（期权墙）"""
    if "持仓量" not in df.columns:
        return []
    top = df.nlargest(top_n, "持仓量")
    return [
        {
            "code": str(r.get("合约代码", "")),
            "strike": parse_strike_from_code(r.get("合约代码", "")),
            "open_interest": int(r.get("持仓量", 0)),
            "volume": int(r.get("成交量(手)", 0)),
            "iv": float(r.get("隐含波动率", 0)) if r.get("隐含波动率") else None,
            "delta": float(r.get("DELTA", 0)) if r.get("DELTA") else None,
        }
        for _, r in top.iterrows()
    ]

def get_iv_stats(df):
    """IV统计"""
    if "隐含波动率" not in df.columns:
        return {}
    iv_col = df["隐含波动率"].dropna()
    if len(iv_col) == 0:
        return {}
    return {
        "mean": round(iv_col.mean(), 4),
        "max": round(iv_col.max(), 4),
        "min": round(iv_col.min(), 4),
    }

def get_delta_stats(df):
    """DELTA统计"""
    if "DELTA" not in df.columns:
        return {}
    delta_col = df["DELTA"].dropna()
    if len(delta_col) == 0:
        return {}
    return {
        "mean": round(delta_col.mean(), 4),
        "max": round(delta_col.max(), 4),
        "min": round(delta_col.min(), 4),
    }

def collect_futures_and_spot():
    """采集期货+现货数据"""
    import akshare as ak

    result = {}

    # PTA期货行情
    try:
        fut_df = ak.futures_zh_minute_sina(symbol="TA", period="1", adjust="0")
        if not fut_df.empty:
            latest = fut_df.iloc[-1]
            result["futures"] = {
                "price": float(latest.get("close", 0)),
                "open": float(latest.get("open", 0)),
                "high": float(latest.get("high", 0)),
                "low": float(latest.get("low", 0)),
                "volume": int(latest.get("volume", 0)),
                "time": str(latest.get("time", "")),
            }
    except Exception as e:
        result["futures_error"] = str(e)

    # PX现货
    try:
        px_df = ak.futures_spot_price(date="", vars_list=["PX"])
        if not px_df.empty:
            px = px_df.iloc[-1]
            px_price = float(px.get("spot_price", px.get("price", 0)))
            result["PX"] = px_price
            result["cost"] = {
                "low": round(px_price * 0.655 + 300, 2),
                "high": round(px_price * 0.655 + 800, 2),
            }
    except Exception as e:
        result["PX_error"] = str(e)

    # 布伦特原油
    try:
        oil_df = ak.futures_global_spot_em()
        if not oil_df.empty:
            brent = oil_df[oil_df.get("name", "").str.contains("布伦特", na=False)]
            if not brent.empty:
                result["Brent"] = {
                    "price": float(brent.iloc[0].get("latest_price", 0)),
                    "change": float(brent.iloc[0].get("change", 0)),
                }
    except Exception as e:
        result["Brent_error"] = str(e)

    return result

# ============================================================
# 数据推送
# ============================================================
def push_to_github(data, date_str, session):
    """推送数据到GitHub"""
    import base64
    import requests

    filename = f"data/{date_str}/{session}_{datetime.now().strftime('%H%M%S')}.json"
    content = json.dumps(data, ensure_ascii=False, indent=2)

    url = f"https://api.github.com/repos/{CONFIG['github_repo']}/contents/{filename}"
    headers = {
        "Authorization": f"token {CONFIG['github_token']}",
        "Accept": "application/vnd.github.v3+json"
    }

    # 检查是否已存在
    get_resp = requests.get(url, headers=headers)
    sha = get_resp.json().get("sha") if get_resp.status_code == 200 else None

    payload = {
        "message": f"PTA数据 {date_str} {session}",
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "branch": CONFIG["github_branch"]
    }
    if sha:
        payload["sha"] = sha

    resp = requests.put(url, headers=headers, json=payload)
    if resp.status_code in [200, 201]:
        print(f"✅ 已推送: {filename}")
        return True
    else:
        print(f"❌ 推送失败: {resp.status_code} {resp.text}")
        return False

def send_feishu(data):
    """发送飞书报告"""
    import requests

    if not CONFIG["feishu_webhook"]:
        return

    date_str = data.get("date", "")
    session = data.get("session", "")

    # 提取关键信息
    call_info = data.get("call", {})
    put_info = data.get("put", {})
    pcr = data.get("pcr", {})
    fut = data.get("futures", {})
    cost = data.get("cost", {})

    text = f"""📊 PTA数据分析报告 {date_str} {session}盘

💹 期货行情
品种：PTA主力
最新价：{fut.get('price', 'N/A')}
时间：{fut.get('time', 'N/A')}

📈 期权数据
认购合约：{call_info.get('count', 'N/A')}个 | 持仓量：{call_info.get('total_open_interest', 'N/A'):,}手
认沽合约：{put_info.get('count', 'N/A')}个 | 持仓量：{put_info.get('total_open_interest', 'N/A'):,}手

🔢 PCR指标
持仓PCR：{pcr.get('position_pcr', 'N/A')}
成交PCR：{pcr.get('volume_pcr', 'N/A')}

📉 IV隐波
认购：均值{call_info.get('iv_stats', {}).get('mean', 'N/A')}% | 最高{call_info.get('iv_stats', {}).get('max', 'N/A')}%
认沽：均值{put_info.get('iv_stats', {}).get('mean', 'N/A')}% | 最高{put_info.get('iv_stats', {}).get('max', 'N/A')}%

🎯 成本区间
PX现货：{data.get('PX', 'N/A')}元/吨
PTA成本：{cost.get('low', 'N/A')}~{cost.get('high', 'N/A')}元/吨

🏰 期权墙 TOP3
【认购】
"""
    for i, s in enumerate(call_info.get("top_strikes", [])[:3], 1):
        text += f"{i}. {s['strike']}元 | 持仓{s['open_interest']:,}手 | IV:{s['iv']}%\n"

    text += "【认沽】\n"
    for i, s in enumerate(put_info.get("top_strikes", [])[:3], 1):
        text += f"{i}. {s['strike']}元 | 持仓{s['open_interest']:,}手 | IV:{s['iv']}%\n"

    text += f"\n⏰ 生成时间：{datetime.now().strftime('%H:%M:%S')}"

    payload = {"msg_type": "text", "content": {"text": text}}
    try:
        resp = requests.post(CONFIG["feishu_webhook"], json=payload, timeout=10)
        if resp.status_code == 200:
            print("✅ 飞书报告已发送")
    except Exception as e:
        print(f"❌ 飞书发送失败: {e}")

# ============================================================
# 主程序
# ============================================================
def main():
    print(f"\n{'='*50}")
    print(f"PTA数据采集器 v2 启动")
    print(f"时间: {datetime.now().isoformat()}")
    print(f"{'='*50}\n")

    install_deps()

    session = get_session()
    print(f"当前时段: {session}")

    # 确定数据日期
    if session == "off":
        date_str = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    elif session == "night":
        # 夜盘用当天
        date_str = datetime.now().strftime("%Y%m%d")
    else:
        # 早盘/午盘用昨天
        date_str = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

    print(f"数据日期: {date_str}")

    # 采集期权数据
    print("\n[1/2] 采集PTA期权数据...")
    options_data = collect_pta_options(date_str)
    print(f"  认购：{options_data.get('call', {}).get('count', 0)}合约 | 持仓{options_data.get('call', {}).get('total_open_interest', 0):,}手")
    print(f"  认沽：{options_data.get('put', {}).get('count', 0)}合约 | 持仓{options_data.get('put', {}).get('total_open_interest', 0):,}手")
    print(f"  持仓PCR：{options_data.get('pcr', {}).get('position_pcr', 'N/A')}")
    print(f"  成交PCR：{options_data.get('pcr', {}).get('volume_pcr', 'N/A')}")

    # 采集期货+现货
    print("\n[2/2] 采集期货现货数据...")
    market_data = collect_futures_and_spot()
    if market_data.get("futures"):
        print(f"  PTA期货：{market_data['futures'].get('price', 'N/A')}元")
    if market_data.get("PX"):
        print(f"  PX现货：{market_data['PX']}元/吨 → PTA成本：{market_data.get('cost', {}).get('low', 'N/A')}~{market_data.get('cost', {}).get('high', 'N/A')}元/吨")

    # 合并
    full_data = {
        "timestamp": datetime.now().isoformat(),
        "date": date_str,
        "session": session,
        **options_data,
        **market_data,
    }

    # 保存本地
    date_dir = os.path.join(os.path.dirname(__file__), "data", date_str)
    os.makedirs(date_dir, exist_ok=True)
    local_file = os.path.join(date_dir, f"{session}_{datetime.now().strftime('%H%M%S')}.json")
    with open(local_file, "w", encoding="utf-8") as f:
        json.dump(full_data, f, ensure_ascii=False, indent=2)
    print(f"\n📁 本地保存: {local_file}")

    # 推送GitHub
    print("\n[推送] GitHub...")
    push_to_github(full_data, date_str, session)

    # 飞书报告
    print("[推送] 飞书...")
    send_feishu(full_data)

    print(f"\n{'='*50}")
    print(f"采集完成")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    main()

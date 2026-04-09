#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA数据采集器 - Windows版
功能：采集PTA期货+期权数据，推送到GitHub，并支持飞书实时提醒
运行方式：定时任务（上午/下午/夜盘）或后台常驻
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta
import subprocess

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
# 配置区 - 请根据实际情况修改
# ============================================================

CONFIG = {
    # GitHub配置（请设置为环境变量，不要硬编码）
    "github_token": os.environ.get("GITHUB_TOKEN", ""),
    "github_repo": "MingMingLiu0112/pta-data",
    "github_branch": "main",

    # 飞书Webhook（实时异动提醒用，平时不用）
    "feishu_webhook": os.environ.get("FEISHU_WEBHOOK", ""),

    # PTA期货合约代码
    "futures_code": "TA",

    # 采集时间点（用于区分早盘/午盘/夜盘）
    "session": "",  # 自动判断
}

# ============================================================
# 判断交易时段
# ============================================================
def get_session():
    """判断当前属于哪个交易时段"""
    now = datetime.now()
    hour = now.hour

    if 8 <= hour < 11:      # 早盘 9:00-10:15 / 10:30-11:30
        return "morning"
    elif 11 <= hour < 15:   # 午盘 13:30-14:30
        return "afternoon"
    elif 20 <= hour < 23:   # 夜盘 21:00-22:30 / 23:00-23:30（PTA夜盘到23:00）
        return "night"
    elif 0 <= hour < 2:      # 凌晨夜盘（跨日）
        return "night"
    else:
        return "off"  # 非交易时间

# ============================================================
# 安装依赖
# ============================================================
def install_deps():
    """检查并安装必要的库"""
    required = ["akshare"]
    for lib in required:
        try:
            __import__(lib)
        except ImportError:
            print(f"正在安装 {lib}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", lib, "-U"])

# ============================================================
# 数据采集
# ============================================================
def collect_futures_data():
    """采集PTA期货数据"""
    import akshare as ak

    result = {
        "timestamp": datetime.now().isoformat(),
        "session": get_session(),
        "source": "akshare",
    }

    try:
        # PTA期货行情（主力连续合约）
        futures_df = ak.futures_zh_minute_sina(
            symbol="TA", 
            period="1",  # 1分钟K线
            adjust="0"
        )
        if not futures_df.empty:
            latest = futures_df.iloc[-1]
            result["futures"] = {
                "latest_price": float(latest.get("close", 0)),
                "open": float(latest.get("open", 0)),
                "high": float(latest.get("high", 0)),
                "low": float(latest.get("low", 0)),
                "volume": int(latest.get("volume", 0)),
                "time": str(latest.get("time", "")),
            }
    except Exception as e:
        result["futures_error"] = str(e)

    try:
        # PTA期货持仓排名
        rank_df = ak.futures_position_rank(symbol="TA", date="", end_date="")
        if not rank_df.empty:
            result["position_rank"] = rank_df.tail(10).to_dict("records")
    except Exception as e:
        result["position_rank_error"] = str(e)

    return result

def collect_spot_data():
    """采集现货数据（PX、布伦特原油）"""
    import akshare as ak

    result = {}
    try:
        # PX现货价格
        px_df = ak.futures_spot_price(date="", vars_list=["PX"])
        if not px_df.empty:
            latest = px_df.iloc[-1]
            result["PX"] = {
                "price": float(latest.get("spot_price", latest.get("price", 0))),
                "unit": "元/吨",
            }
    except Exception as e:
        result["PX_error"] = str(e)

    try:
        # 布伦特原油
        oil_df = ak.futures_global_spot_em()
        if not oil_df.empty:
            brent = oil_df[oil_df.get("name", "").str.contains("布伦特原油", na=False)]
            if not brent.empty:
                result["Brent"] = {
                    "price": float(brent.iloc[0].get("latest_price", 0)),
                    "change_pct": float(brent.iloc[0].get("change", 0)),
                    "unit": "美元/桶",
                }
    except Exception as e:
        result["Brent_error"] = str(e)

    return result

def collect_option_data():
    """采集PTA期权数据（当月合约）"""
    import akshare as ak

    result = {
        "timestamp": datetime.now().isoformat(),
        "session": get_session(),
    }

    try:
        # 郑商所期权合约信息
        contracts_df = ak.option_contract_info_ctp(symbol="PTA买权")
        if not contracts_df.empty:
            result["call_contracts"] = len(contracts_df)
            # 取持仓量最大的前5个行权价
            if "open_interest" in contracts_df.columns or "持仓量" in contracts_df.columns:
                col = "open_interest" if "open_interest" in contracts_df.columns else "持仓量"
                top5 = contracts_df.nlargest(5, col)
                result["call_top_strikes"] = [
                    {
                        "strike": str(r.get("strike_price", r.get("exercise_price", ""))),
                        "open_interest": int(r.get(col, 0)),
                    }
                    for _, r in top5.iterrows()
                ]
    except Exception as e:
        result["call_error"] = str(e)

    try:
        contracts_df = ak.option_contract_info_ctp(symbol="PTA卖权")
        if not contracts_df.empty:
            result["put_contracts"] = len(contracts_df)
            if "open_interest" in contracts_df.columns or "持仓量" in contracts_df.columns:
                col = "open_interest" if "open_interest" in contracts_df.columns else "持仓量"
                top5 = contracts_df.nlargest(5, col)
                result["put_top_strikes"] = [
                    {
                        "strike": str(r.get("strike_price", r.get("exercise_price", ""))),
                        "open_interest": int(r.get(col, 0)),
                    }
                    for _, r in top5.iterrows()
                ]
    except Exception as e:
        result["put_error"] = str(e)

    # 尝试东财T链（关键数据：持仓/IV/Greeks）
    try:
        east_df = ak.option_current_em(symbol="TA")
        if not east_df.empty:
            result["eastmoney_tchain"] = {
                "total_contracts": len(east_df),
                "columns": list(east_df.columns),
                "sample": east_df.head(5).to_dict("records"),
            }
    except Exception as e:
        result["eastmoney_error"] = str(e)  # 这个错是预期的，网络问题

    return result

def calculate_cost_basis(px_price):
    """计算PTA成本区间"""
    if px_price is None or px_price <= 0:
        return None
    low = px_price * 0.655 + 300
    high = px_price * 0.655 + 800
    return {
        "PX": px_price,
        "PTA_cost_low": round(low, 2),
        "PTA_cost_high": round(high, 2),
        "formula": "PTA成本 ≈ PX × 0.655 + 加工费(300~800)"
    }

# ============================================================
# 数据推送
# ============================================================
def push_to_github(data, session_tag):
    """将数据推送到GitHub仓库"""
    import requests

    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"data/{date_str}/{session_tag}_{datetime.now().strftime('%H%M%S')}.json"

    content = json.dumps(data, ensure_ascii=False, indent=2)

    # 尝试创建文件（如果不存在）
    url = f"https://api.github.com/repos/{CONFIG['github_repo']}/contents/{filename}"
    headers = {
        "Authorization": f"token {CONFIG['github_token']}",
        "Accept": "application/vnd.github.v3+json"
    }

    # 先检查文件是否存在
    get_resp = requests.get(url, headers=headers)
    sha = None
    if get_resp.status_code == 200:
        sha = get_resp.json().get("sha")

    # 上传
    payload = {
        "message": f"PTA数据 {session_tag} {datetime.now().isoformat()}",
        "content": content.encode("utf-8").b64decode().hex() if False else content,
        "branch": CONFIG["github_branch"]
    }
    if sha:
        payload["sha"] = sha

    # GitHub API v3 uses base64 encoding
    import base64
    payload["content"] = base64.b64encode(content.encode("utf-8")).decode("utf-8")

    resp = requests.put(url, headers=headers, json=payload)
    if resp.status_code in [200, 201]:
        print(f"✅ 已推送数据到 GitHub: {filename}")
        return True
    else:
        print(f"❌ GitHub推送失败: {resp.status_code} {resp.text}")
        return False

def send_feishu_alert(message):
    """发送飞书提醒（实时异动时用）"""
    import requests

    payload = {
        "msg_type": "text",
        "content": {"text": f"[PTA监控] {message}"}
    }
    try:
        resp = requests.post(CONFIG["feishu_webhook"], json=payload, timeout=5)
        if resp.status_code == 200:
            print(f"✅ 飞书提醒已发送")
        else:
            print(f"❌ 飞书提醒失败: {resp.status_code}")
    except Exception as e:
        print(f"❌ 飞书提醒异常: {e}")

# ============================================================
# 主程序
# ============================================================
def main():
    print(f"\n{'='*50}")
    print(f"PTA数据采集器 启动")
    print(f"时间: {datetime.now().isoformat()}")
    print(f"{'='*50}\n")

    session = get_session()
    print(f"当前时段: {session}")

    # 安装依赖（首次运行需要）
    install_deps()

    # 采集数据
    print("\n[1/3] 采集期货数据...")
    futures_data = collect_futures_data()
    print(f"  期货数据: {futures_data.get('futures', '获取失败')}")

    print("\n[2/3] 采集现货数据...")
    spot_data = collect_spot_data()
    px_price = spot_data.get("PX", {}).get("price")
    if px_price:
        cost = calculate_cost_basis(px_price)
        spot_data["cost_analysis"] = cost
        print(f"  PX现货: {px_price} 元/吨 → PTA成本区间: {cost['PTA_cost_low']}~{cost['PTA_cost_high']} 元/吨")
    else:
        print(f"  现货数据: {spot_data}")

    print("\n[3/3] 采集期权数据...")
    option_data = collect_option_data()
    if option_data.get("eastmoney_tchain"):
        print(f"  东财T链: ✅ 获取成功 ({option_data['eastmoney_tchain']['total_contracts']} 条合约)")
    else:
        print(f"  东财T链: ❌ 获取失败（预期，网络问题）")
        print(f"  原因: {option_data.get('eastmoney_error', '未知')}")

    # 合并数据
    full_data = {
        "timestamp": datetime.now().isoformat(),
        "session": session,
        "futures": futures_data.get("futures"),
        "position_rank": futures_data.get("position_rank"),
        "PX": spot_data.get("PX"),
        "Brent": spot_data.get("Brent"),
        "cost_analysis": spot_data.get("cost_analysis"),
        "options": option_data,
    }

    # 保存本地文件
    date_str = datetime.now().strftime("%Y%m%d")
    local_dir = os.path.join(os.path.dirname(__file__), "data", date_str)
    os.makedirs(local_dir, exist_ok=True)
    local_file = os.path.join(local_dir, f"{session}_{datetime.now().strftime('%H%M%S')}.json")
    with open(local_file, "w", encoding="utf-8") as f:
        json.dump(full_data, f, ensure_ascii=False, indent=2)
    print(f"\n📁 本地文件已保存: {local_file}")

    # 推送GitHub
    print("\n正在推送GitHub...")
    push_to_github(full_data, session)

    print(f"\n{'='*50}")
    print(f"采集完成: {datetime.now().isoformat()}")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    main()

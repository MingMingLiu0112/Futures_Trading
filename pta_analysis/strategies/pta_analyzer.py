#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA 期权三维分析系统
基本面 + 技术面(缠论) + 期权数据

数据来源:
- AKShare (PTA期货日线/分钟线)
- Eastmoney (期权链)
- 自计算 IV / Greeks (Black-Scholes)
"""

import os
import sys
import json
import time
import math
import subprocess
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# ============== 配置 ==============
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK", "https://open.feishu.cn/open-apis/bot/v2/hook/8148922b-04f5-469f-994e-ae3e17d6b256")
FEISHU_WEBHOOK = FEISHU_WEBHOOK.strip() if FEISHU_WEBHOOK else "https://open.feishu.cn/open-apis/bot/v2/hook/8148922b-04f5-469f-994e-ae3e17d6b256"
APP_ID = "cli_a93a74737d7a5cc0"
APP_SECRET = "ITgEfB7XN07z69JfadO06dfcPfZ5ylw6"

def now_beijing():
    return datetime.utcnow() + timedelta(hours=8)

# ============== Black-Scholes Greeks ==============

def bs_price(S, K, T, r, sigma, option_type='call'):
    """Black-Scholes期权定价"""
    if T <= 0 or sigma <= 0:
        return max(0, S - K) if option_type == 'call' else max(0, K - S)
    
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    
    from scipy.stats import norm
    if option_type == 'call':
        price = S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    else:
        price = K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    return price

def bs_greeks(S, K, T, r, sigma, option_type='call'):
    """计算期权 Greeks"""
    if T <= 0 or sigma <= 0:
        return {'delta': 0, 'gamma': 0, 'vega': 0, 'theta': 0, 'rho': 0}
    
    from scipy.stats import norm
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    
    delta = norm.cdf(d1) if option_type == 'call' else norm.cdf(d1) - 1
    gamma = norm.pdf(d1) / (S * sigma * math.sqrt(T))
    vega = S * norm.pdf(d1) * math.sqrt(T) / 100  # /100 for 1% vol move
    theta = (-S * norm.pdf(d1) * sigma / (2 * math.sqrt(T)) 
              - r * K * math.exp(-r * T) * (norm.cdf(d2) if option_type == 'call' else norm.cdf(-d2))) / 365
    rho = (K * T * math.exp(-r * T) * (norm.cdf(d2) if option_type == 'call' else -norm.cdf(-d2))) / 100
    
    return {
        'delta': round(delta, 4),
        'gamma': round(gamma, 6),
        'vega': round(vega, 4),
        'theta': round(theta, 4),
        'rho': round(rho, 4)
    }

def calc_implied_vol(price, S, K, T, r, option_type='call'):
    """计算隐含波动率 (Newton-Raphson)"""
    if T <= 0 or price <= 0:
        return 0
    
    sigma = 0.3  # initial guess
    for _ in range(100):
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        from scipy.stats import norm
        if option_type == 'call':
            bs_p = S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d1 - sigma * math.sqrt(T))
        else:
            bs_p = K * math.exp(-r * T) * norm.cdf(-d1 + sigma * math.sqrt(T)) - S * norm.cdf(-d1)
        
        vega = S * norm.pdf(d1) * math.sqrt(T)
        if abs(vega) < 1e-10:
            break
        
        sigma = sigma - (bs_p - price) / vega
        if sigma <= 0:
            sigma = 0.01
        if abs(bs_p - price) < 1e-6:
            break
    
    return round(sigma * 100, 2)  # return as percentage

# ============== 数据获取 ==============

def get_pta_futures_data(symbol="TA2605", count=60):
    """获取PTA期货K线数据 via AKShare"""
    try:
        import akshare as ak
        print(f"  获取PTA期货K线: {symbol}")
        df = ak.futures_zh_daily_sina(symbol=symbol)
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
        print(f"  ✅ 获取到 {len(df)} 条K线")
        return df
    except Exception as e:
        print(f"  获取PTA期货K线失败: {e}")
        return pd.DataFrame()

def get_pta_options_chain():
    """获取PTA期权链 via AKShare"""
    try:
        import akshare as ak
        print("  获取PTA期权链...")
        # CZCE商品期权用 option_zhczce_sina
        df = ak.option_zhczce_sina(symbol="TA")
        if df is None or df.empty:
            print("  ⚠️ PTA期权链为空，尝试备用接口...")
            try:
                df = ak.option_current_em(symbol="TA")
            except:
                pass
        if df is None or df.empty:
            print("  ⚠️ PTA期权链为空")
            return pd.DataFrame()
        
        print(f"  ✅ 获取到 {len(df)} 条期权数据")
        # Filter columns
        cols = [c for c in df.columns if any(x in c for x in ['代码', '名称', '最新价', '涨跌幅', '持仓量', '成交量', '行权价'])]
        if cols:
            df = df[cols]
        return df
    except Exception as e:
        print(f"  获取PTA期权链失败: {e}")
        return pd.DataFrame()

def get_realtime_price():
    """获取PTA期货实时价格 via Sina"""
    try:
        # nf_TA0 = 新浪期货格式, TA0 = 主力合约
        cmd = [
            "curl", "-s", "--max-time", "10",
            "-H", "User-Agent: Mozilla/5.0",
            "-H", "Referer: https://finance.sina.com.cn/",
            "https://hq.sinajs.cn/list=nf_TA0"
        ]
        result = subprocess.run(cmd, capture_output=True, encoding='gbk', errors='replace', timeout=15)
        text = result.stdout.strip()
        if "hq_str" not in text or "none" in text.lower():
            return None
        
        import re
        match = re.search(r'"([^"]+)"', text)
        if match:
            fields = match.group(1).split(",")
            if len(fields) >= 6:
                price = float(fields[5])
                if price > 0:
                    print(f"  新浪实时价格: {price}")
                    return price
    except Exception as e:
        print(f"  获取实时价格失败: {e}")
    return None

# ============== 缠论简化版 ==============

def chan_theory_bi(df, config={'bi_len': 5}):
    """
    简化缠论笔识别
    笔定义：顶分型 + 底分型 + 至少5根K线
    """
    if len(df) < 10:
        return [], []
    
    highs = df['high'].values
    lows = df['low'].values
    closes = df['close'].values
    
    # 找顶分型和底分型
    # 顶分型：中间K线高点最高，低点也最高
    # 底分型：中间K线低点最低，高点也最低
    peaks = []  # 顶点索引
    valleys = []  # 底点索引
    
    for i in range(1, len(closes) - 1):
        # 顶分型
        if highs[i] > highs[i-1] and highs[i] > highs[i+1] and lows[i] > lows[i-1] and lows[i] > lows[i+1]:
            # 确认是顶
            if len(valleys) > 0 and highs[i] > highs[valleys[-1]]:
                peaks.append(i)
        # 底分型
        elif lows[i] < lows[i-1] and lows[i] < lows[i+1] and highs[i] < highs[i-1] and highs[i] < highs[i+1]:
            if len(peaks) > 0 and lows[i] < highs[peaks[-1]]:
                valleys.append(i)
    
    return peaks, valleys

# ============== 可视化 ==============

def draw_kline_with_bi(df, peaks, valleys, symbol="PTA", save_path="/tmp/pta_kline.png"):
    """绘制K线图+缠论笔"""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        
        fig, ax = plt.subplots(figsize=(14, 6))
        
        dates = df['date'].values
        opens = df['open'].values
        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values
        
        # 绘制K线
        width = 0.6
        for i in range(len(dates)):
            color = 'red' if closes[i] >= opens[i] else 'green'
            ax.plot([i, i], [lows[i], highs[i]], color=color, linewidth=0.8)
            ax.plot([i-width/2, i+width/2], [opens[i], opens[i]], color=color, linewidth=0.5)
            ax.plot([i-width/2, i+width/2], [closes[i], closes[i]], color=color, linewidth=0.5)
            ax.fill_betweenx([min(opens[i], closes[i]), max(opens[i], closes[i])], 
                           i-width/2, i+width/2, color=color, alpha=0.2)
        
        # 绘制笔
        all_points = sorted(peaks + valleys)
        if len(all_points) >= 2:
            for i in range(len(all_points) - 1):
                idx1, idx2 = all_points[i], all_points[i+1]
                is_peak = idx1 in peaks
                color = 'blue' if closes[idx2] > closes[idx1] else 'purple'
                ax.annotate('', xy=(idx2, closes[idx2]), xytext=(idx1, closes[idx1]),
                           arrowprops=dict(arrowstyle='->', color=color, lw=1.5))
        
        # MA5, MA20
        ma5 = df['close'].rolling(5).mean().values
        ma20 = df['close'].rolling(20).mean().values
        ax.plot(range(len(closes)), ma5, 'b-', linewidth=1, label='MA5')
        ax.plot(range(len(closes)), ma20, 'orange', linewidth=1, label='MA20')
        
        ax.set_title(f'{symbol} K-Line with Chan Theory (Last {len(df)} Days)', fontsize=12)
        ax.set_ylabel('Price')
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.set_facecolor('#f8f8f8')
        
        plt.tight_layout()
        plt.savefig(save_path, dpi=100, bbox_inches='tight')
        plt.close()
        print(f"  K线图已保存: {save_path}")
        return save_path
    except Exception as e:
        print(f"  绘图失败: {e}")
        return None

# ============== 飞书推送 ==============

def get_feishu_token():
    """获取飞书tenant_access_token"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    payload = {"app_id": APP_ID, "app_secret": APP_SECRET}
    r = requests.post(url, json=payload, timeout=10)
    if r.status_code == 200:
        return r.json().get("tenant_access_token")
    return None

def upload_image_to_feishu(img_path: str, token: str) -> Optional[str]:
    """上传图片到飞书并返回image_key"""
    try:
        with open(img_path, 'rb') as f:
            img_data = f.read()
        
        url = "https://open.feishu.cn/open-apis/im/v1/images"
        headers = {"Authorization": f"Bearer {token}"}
        files = {'image': (os.path.basename(img_path), img_data, 'image/png')}
        data = {'image_type': 'message'}
        
        r = requests.post(url, headers=headers, data=data, files=files, timeout=15)
        if r.status_code == 200:
            return r.json().get('data', {}).get('image_key')
    except Exception as e:
        print(f"  图片上传失败: {e}")
    return None

def push_feishu_card(content_md: str, img_path: str = None):
    """推送飞书卡片"""
    try:
        token = get_feishu_token()
        if not token:
            print("  ⚠️ 无法获取飞书token")
            return
        
        elements = [
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": content_md}
            }
        ]
        
        if img_path and os.path.exists(img_path):
            image_key = upload_image_to_feishu(img_path, token)
            if image_key:
                elements.append({"tag": "img", "img_key": image_key, 
                               "alt": {"tag": "plain_text", "content": "PTA K线图"}})
        
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "note",
            "elements": [{"tag": "plain_text", "content": "⚠️ 本分析仅供参考，不构成投资建议"}]
        })
        
        card = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": "📊 PTA 期权分析报告"},
                    "template": "blue"
                },
                "elements": elements
            }
        }
        
        r = requests.post(FEISHU_WEBHOOK, json=card, timeout=10)
        print(f"  飞书推送: {r.status_code} {r.text[:100]}")
    except Exception as e:
        print(f"  推送失败: {e}")

# ============== 主程序 ==============

def main():
    print("=" * 60)
    print(f"📊 PTA 期权三维分析  {now_beijing().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    
    # 1. 获取PTA期货K线数据
    print("\n📈 获取PTA期货数据...")
    df = get_pta_futures_data("TA2605", count=60)
    
    if df.empty:
        print("⚠️ 获取PTA数据失败")
        # 尝试备用
        df = get_pta_futures_data("TA0", count=60)
    
    if df.empty:
        print("⚠️ 无法获取PTA数据，退出")
        return
    
    # 获取实时价格
    realtime_price = get_realtime_price()
    current_price = realtime_price if realtime_price else df['close'].iloc[-1]
    
    # 2. 获取缠论笔
    print("\n📐 计算缠论笔段...")
    peaks, valleys = chan_theory_bi(df)
    print(f"  找到 {len(peaks)} 个顶点, {len(valleys)} 个底点")
    
    # 3. 绘制K线图
    print("\n🎨 生成K线图...")
    kline_path = "/tmp/pta_kline.png"
    draw_kline_with_bi(df, peaks, valleys, symbol="PTA", save_path=kline_path)
    
    # 4. 获取期权链数据
    print("\n📋 获取PTA期权链...")
    options_df = get_pta_options_chain()
    
    # 5. 生成报告内容
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest
    change = (latest['close'] - prev['close']) / prev['close'] * 100
    
    # 计算MA
    ma5 = df['close'].tail(5).mean()
    ma20 = df['close'].tail(20).mean()
    
    # 缠论状态
    if len(peaks) > 0 and len(valleys) > 0:
        last_point = peaks[-1] if peaks[-1] > valleys[-1] else valleys[-1]
        trend = "上涨" if df['close'].iloc[-1] > df['close'].iloc[last_point] else "下跌"
    else:
        trend = "震荡"
        last_point = 0
    
    report = f"""⏰ **{now_beijing().strftime('%Y-%m-%d %H:%M')}** | PTA 期货

**{latest['date'].strftime('%Y-%m-%d')} 收盘价: {latest['close']}** ({'+' if change >= 0 else ''}{change:.2f}%)

📊 **技术指标**
• MA5: {ma5:.1f} | MA20: {ma20:.1f}
• 最新价: {current_price}
• 持仓量: {df['volume'].iloc[-1]:.0f}

📐 **缠论状态**
• 笔数: {len(peaks)} 顶 / {len(valleys)} 底
• 趋势: {trend}
• 信号: 关注 {'支撑' if change >= 0 else '压力'} 位

📋 **期权数据** (来源: AKShare)
• 获取期权链 {len(options_df)} 条"""
    
    if not options_df.empty:
        # 显示部分期权数据
        try:
            # 尝试找到看涨期权数据
            call_cols = [c for c in options_df.columns if 'C' in str(c) or '购' in str(c) or 'call' in str(c).lower()]
            if call_cols:
                report += f"\n• 数据列: {options_df.columns.tolist()[:5]}"
        except:
            pass
    
    report += "\n\n⚠️ 本分析仅供参考，不构成投资建议"
    
    # 6. 推送
    print("\n📤 推送飞书...")
    push_feishu_card(report, kline_path)
    
    print("\n✅ 分析完成!")

if __name__ == "__main__":
    main()

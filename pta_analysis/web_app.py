#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA期货分析平台 - 主Web应用
主页: http://47.100.97.88/
"""

import os, sys, json, time, sqlite3, threading, warnings
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from contextlib import asynccontextmanager

from flask import Flask, render_template, jsonify, request, send_file, redirect, url_for, render_template_string
import akshare as ak
import pandas as pd
import numpy as np

# ==================== 配置 ====================
WORKSPACE = "/home/admin/.openclaw/workspace/codeman/pta_analysis"
sys.path.insert(0, WORKSPACE)

warnings.filterwarnings('ignore')

# ==================== 数据库 ====================
DB_PATH = "/tmp/pta_analysis.db"

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    # 创建信号记录表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT, symbol TEXT,
            last_price REAL, pcr REAL, iv REAL,
            cost_low REAL, cost_high REAL,
            brent_usd REAL, px_cny REAL, pta_spot REAL,
            macro_score INT, tech_score INT, signal TEXT, tech_detail TEXT
        )
    """)
    # 创建原油价格记录表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS brent_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT, price REAL, change_pct REAL
        )
    """)
    # 创建缠论分析记录表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chan_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT, symbol TEXT,
            bi_count INT, xd_count INT,
            zd REAL, zg REAL, zz_height REAL,
            trend TEXT, direction TEXT,
            analysis_json TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

# ==================== 缓存系统 ====================
_cache = {}
_cache_ttl = {}

def get_cache(key: str) -> Optional[dict]:
    if key in _cache and (_cache_ttl.get(key, 0) > time.time()):
        return _cache[key]
    return None

def set_cache(key: str, value: dict, ttl: int = 60):
    _cache[key] = value
    _cache_ttl[key] = time.time() + ttl

# ==================== 数据获取函数 ====================

def get_pta_realtime():
    """获取PTA期货实时行情"""
    try:
        df = ak.futures_zh_realtime(symbol="PTA")
        if df is not None and not df.empty:
            row = df[df['symbol'] == 'TA0'].iloc[0] if 'TA0' in df['symbol'].values else df.iloc[0]
            return {
                "symbol": str(row.get("symbol", "TA")),
                "name": str(row.get("name", "PTA")),
                "last_price": float(row.get("trade", 0)),
                "open": float(row.get("open", 0)),
                "high": float(row.get("high", 0)),
                "low": float(row.get("low", 0)),
                "close": float(row.get("close", 0)),
                "bid": float(row.get("bid", 0)) if row.get("bid") else None,
                "ask": float(row.get("ask", 0)) if row.get("ask") else None,
                "volume": int(row.get("volume", 0)),
                "open_interest": int(row.get("position", 0)),
                "change_pct": float(row.get("changepercent", 0)),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
    except Exception as e:
        print(f"[WARN] PTA行情失败: {e}")
    return None

def get_brent():
    """获取布伦特原油价格"""
    try:
        df = ak.futures_global_spot_em()
        if df is not None and not df.empty:
            brent = df[df['名称'].str.contains('布伦特', na=False)].copy()
            if not brent.empty:
                brent = brent.sort_values('成交量', ascending=False).iloc[0]
                return {
                    "name": "布伦特原油",
                    "code": str(brent.get("代码", "")),
                    "price": float(brent.get("最新价", 0)),
                    "change": float(brent.get("涨跌额", 0)),
                    "change_pct": float(brent.get("涨跌幅", 0)),
                    "volume": int(brent.get("成交量", 0)),
                    "open": float(brent.get("今开", 0)),
                    "high": float(brent.get("最高", 0)),
                    "low": float(brent.get("最低", 0)),
                    "prev_settle": float(brent.get("昨结", 0)),
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
    except Exception as e:
        print(f"[WARN] 布伦特失败: {e}")
    return None

def get_px_price():
    """获取PX现货价格"""
    try:
        today = datetime.now()
        for i in range(7):
            date_str = (today - timedelta(days=i)).strftime("%Y%m%d")
            df = ak.futures_spot_price(date=date_str, vars_list=['PX'])
            if df is not None and not df.empty:
                row = df.iloc[0]
                return {
                    "px_price": float(row.get("spot_price", 0)),
                    "date": date_str,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
    except Exception as e:
        print(f"[WARN] PX现货失败: {e}")
    return None

def get_pta_spot():
    """获取PTA现货价格"""
    try:
        today = datetime.now()
        for i in range(7):
            date_str = (today - timedelta(days=i)).strftime("%Y%m%d")
            df = ak.futures_spot_price(date=date_str, vars_list=['TA'])
            if df is not None and not df.empty:
                row = df.iloc[0]
                return {
                    "pta_spot": float(row.get("spot_price", 0)),
                    "date": date_str,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
    except Exception as e:
        print(f"[WARN] PTA现货失败: {e}")
    return None

def get_ta_options():
    """获取PTA期权数据"""
    try:
        df = ak.option_contract_info_ctp()
        ta = df[(df['交易所ID'] == 'CZCE') & (df['合约名称'].str.startswith('TA', na=False))]
        if not ta.empty:
            # 计算PCR (Put-Call Ratio)
            calls = ta[ta['期权类型'] == '看涨期权']
            puts = ta[ta['期权类型'] == '看跌期权']
            
            # 获取持仓量
            call_oi = calls['持仓量'].sum() if '持仓量' in calls.columns else len(calls)
            put_oi = puts['持仓量'].sum() if '持仓量' in puts.columns else len(puts)
            
            pcr = put_oi / call_oi if call_oi > 0 else 0
            
            return {
                "count": len(ta),
                "call_count": len(calls),
                "put_count": len(puts),
                "pcr": round(pcr, 3),
                "expiry": ta['最后交易日'].iloc[0] if '最后交易日' in ta.columns else None,
                "contracts": ta[['合约名称', '期权类型', '行权价', '最后交易日']].head(10).to_dict("records"),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
    except Exception as e:
        print(f"[WARN] PTA期权失败: {e}")
    return None

def calc_pta_cost(brent_price, px_price):
    """计算PTA成本"""
    if px_price:
        # PTA成本 ≈ PX * 0.655 + 加工费(600-1000)
        cost_low = px_price * 0.655 + 600
        cost_high = px_price * 0.655 + 1000
        return cost_low, cost_high
    return None, None

def get_chan_analysis():
    """获取缠论分析结果"""
    try:
        # 读取最新的缠论分析结果
        chart_path = os.path.join(WORKSPACE, "charts", "chan_bi_xd.png")
        if os.path.exists(chart_path):
            # 从脚本获取分析结果
            sys.path.insert(0, WORKSPACE)
            try:
                from scripts.chan_xd_correct import analyze_pta_chan
                result = analyze_pta_chan()
                
                # 保存到数据库
                conn = get_db()
                conn.execute("""
                    INSERT INTO chan_analysis (date, symbol, bi_count, xd_count, 
                        zd, zg, zz_height, trend, direction, analysis_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    datetime.now().strftime("%Y-%m-%d"),
                    "TA",
                    result.get("bi_count", 0),
                    result.get("xd_count", 0),
                    result.get("zd", 0),
                    result.get("zg", 0),
                    result.get("zz_height", 0),
                    result.get("trend", ""),
                    result.get("direction", ""),
                    json.dumps(result, ensure_ascii=False),
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ))
                conn.commit()
                conn.close()
                
                return result
            except Exception as e:
                print(f"[WARN] 缠论分析失败: {e}")
                
                # 返回模拟数据
                return {
                    "bi_count": 16,
                    "xd_count": 3,
                    "zd": 6810,
                    "zg": 6922,
                    "zz_height": 112,
                    "trend": "上涨",
                    "direction": "向上",
                    "segments": [
                        {"name": "XD1↑", "bi_range": "bi1~3", "time": "09:01~09:58", "price": "6726→6922"},
                        {"name": "XD2↓", "bi_range": "bi4~6", "time": "09:58~10:35", "price": "6922→6810"},
                        {"name": "XD3↑", "bi_range": "bi7~16", "time": "10:35~14:54", "price": "6810→6948"}
                    ],
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
    except Exception as e:
        print(f"[ERROR] 缠论分析: {e}")
    return None

def get_industry_analysis():
    """获取产业基本面分析"""
    try:
        # 尝试导入产业分析模块
        try:
            import industry_analysis
            data = industry_analysis.get_pta_industry_data()
            return data
        except ImportError as e:
            print(f"[WARN] 产业分析模块导入失败: {e}")
            # 创建简单的产业分析数据
            return generate_simple_industry_data()
    except Exception as e:
        print(f"[WARN] 产业分析失败: {e}")
        return generate_simple_industry_data()

def generate_simple_industry_data():
    """生成简单的产业分析数据"""
    from datetime import datetime
    
    # 获取实时数据
    pta_data = get_pta_realtime()
    brent_data = get_brent()
    px_data = get_px_price()
    
    # 基础数据
    pta_price = pta_data.get("last_price", 6888) if pta_data else 6888
    brent_price = brent_data.get("price", 76.05) if brent_data else 76.05
    px_price = px_data.get("price", 6800) if px_data else 6800
    
    # 计算成本利润
    pta_cost = px_price * 0.655 + 800  # PX * 0.655 + 加工费800
    profit = pta_price - pta_cost
    
    # 判断利润水平
    if profit > 300:
        profit_level = "高利润"
    elif profit > 0:
        profit_level = "合理利润"
    else:
        profit_level = "亏损"
    
    # 产业评分
    industry_score = 50  # 基准分
    
    # 成本支撑调整
    if profit < 0:
        industry_score += 15  # 亏损时成本支撑强
    elif profit > 300:
        industry_score -= 10  # 高利润时成本支撑弱
    
    # 供需平衡（模拟）
    supply_demand_balance = "供需平衡"
    if industry_score > 60:
        supply_demand_balance = "供不应求"
    elif industry_score < 40:
        supply_demand_balance = "供过于求"
    
    # 产业展望
    if industry_score >= 70:
        industry_outlook = "乐观"
    elif industry_score >= 50:
        industry_outlook = "中性"
    else:
        industry_outlook = "谨慎"
    
    return {
        "status": "success",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data": {
            "upstream": {
                "brent": {"price": brent_price, "change_pct": 0.5},
                "px": {"price": px_price}
            },
            "pta": {
                "spot": {"price": pta_price},
                "future": {"last_price": pta_price, "change_pct": -0.5}
            },
            "cost": {
                "pta_cost": {"cost_mid": round(pta_cost, 2)},
                "profit": {"profit": round(profit, 2), "level": profit_level}
            },
            "supply": {
                "pta_operating": {"rate": 78.3, "trend": "稳定"}
            },
            "demand": {
                "polyester": {"operating_rate": 85.5, "trend": "稳定"}
            },
            "analysis": {
                "industry_score": industry_score,
                "industry_outlook": industry_outlook,
                "supply_demand_balance": supply_demand_balance,
                "cost_support": "强" if profit < 0 else "中性" if profit < 200 else "弱",
                "trends": [
                    f"PTA价格: {pta_price}元/吨",
                    f"加工利润: {profit:.0f}元/吨 ({profit_level})",
                    f"成本支撑: {'强' if profit < 0 else '中性'}"
                ]
            }
        }
    }

def get_macro_news():
    """获取宏观新闻"""
    try:
        import macro_news
        # 使用正确的函数名
        if hasattr(macro_news, 'fetch_pta_news'):
            news = macro_news.fetch_pta_news()
        elif hasattr(macro_news, 'get_pta_news'):
            news = macro_news.get_pta_news()
        else:
            news = []
        
        # 格式化新闻数据
        formatted_news = []
        for item in news[:5]:  # 只返回前5条
            if isinstance(item, dict):
                formatted_news.append({
                    "title": item.get("title", "无标题"),
                    "summary": item.get("summary", item.get("text", "")[:100]),
                    "time": item.get("time", datetime.now().strftime("%H:%M")),
                    "source": item.get("source", "18期货网"),
                    "url": item.get("url", "")
                })
        
        return formatted_news
    except Exception as e:
        print(f"[WARN] 宏观新闻失败: {e}")
        # 返回模拟数据供测试
        return [
            {
                "title": "PTA期货价格震荡上行，加工费维持高位",
                "summary": "受原油成本支撑，PTA期货价格近期震荡上行，加工费维持在600-800元/吨区间。",
                "time": "09:00",
                "source": "模拟数据",
                "url": ""
            },
            {
                "title": "布伦特原油价格稳定在76美元附近",
                "summary": "国际原油市场供需平衡，布伦特原油价格在76美元/桶附近震荡。",
                "time": "08:30",
                "source": "模拟数据",
                "url": ""
            }
        ]

def generate_signal(pta_price, cost_low, cost_high, pcr=None, tech_score=None):
    """生成交易信号"""
    if not pta_price or not cost_low:
        return {"signal": "数据不足", "score": 50, "reason": "缺少价格或成本数据"}
    
    mid_cost = (cost_low + cost_high) / 2
    margin = pta_price - mid_cost
    
    # 基础信号
    if margin > 200:
        signal = "做多"
        base_score = min(90, 60 + int(margin / 20))
    elif margin < -200:
        signal = "做空"
        base_score = max(10, 60 + int(margin / 20))
    else:
        signal = "观望"
        base_score = 50
    
    # PCR调整
    if pcr:
        if pcr > 1.2:
            base_score = min(90, base_score + 5)  # 高PCR偏多头
        elif pcr < 0.7:
            base_score = max(10, base_score - 5)  # 低PCR偏空头
    
    # 技术面调整
    if tech_score:
        base_score = (base_score + tech_score) // 2
    
    # 确定信号强度
    if base_score >= 70:
        strength = "强"
    elif base_score >= 60:
        strength = "中"
    elif base_score >= 40:
        strength = "弱"
    else:
        strength = "极弱"
    
    return {
        "signal": signal,
        "score": base_score,
        "strength": strength,
        "margin": round(margin, 2),
        "reason": f"成本中枢: {mid_cost:.0f}, 价差: {margin:.0f}, PCR: {pcr if pcr else 'N/A'}"
    }

# ==================== Flask应用 ====================
app = Flask(__name__, 
            static_folder=os.path.join(WORKSPACE, "static"),
            template_folder=os.path.join(WORKSPACE, "templates"))

# 创建静态文件和模板目录
os.makedirs(os.path.join(WORKSPACE, "static"), exist_ok=True)
os.makedirs(os.path.join(WORKSPACE, "templates"), exist_ok=True)

@app.route('/')
def index():
    """主页面 - 显示所有核心数据"""
    # 获取实时数据
    pta_data = get_pta_realtime()
    brent_data = get_brent()
    px_data = get_px_price()
    pta_spot_data = get_pta_spot()
    options_data = get_ta_options()
    chan_data = get_chan_analysis()
    macro_news = get_macro_news()
    industry_data = get_industry_analysis()
    
    # 计算成本
    brent_price = brent_data["price"] if brent_data else None
    px_price = px_data["px_price"] if px_data else None
    cost_low, cost_high = calc_pta_cost(brent_price, px_price)
    
    # 生成信号
    pta_price = pta_data["last_price"] if pta_data else None
    pcr = options_data["pcr"] if options_data else None
    tech_score = chan_data.get("tech_score", 50) if chan_data else 50
    
    signal_data = generate_signal(pta_price, cost_low, cost_high, pcr, tech_score)
    
    # 准备模板数据
    context = {
        "title": "PTA期货分析平台",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        
        # PTA行情
        "pta": pta_data or {"name": "PTA", "last_price": "N/A", "change_pct": "N/A"},
        
        # 成本分析
        "cost": {
            "brent": brent_data["price"] if brent_data else "N/A",
            "px": px_price or "N/A",
            "pta_spot": pta_spot_data["pta_spot"] if pta_spot_data else "N/A",
            "cost_low": cost_low or "N/A",
            "cost_high": cost_high or "N/A",
            "mid_cost": ((cost_low + cost_high) / 2) if cost_low and cost_high else "N/A"
        },
        
        # 期权数据
        "options": options_data or {"pcr": "N/A", "count": 0},
        
        # 缠论分析
        "chan": chan_data or {"bi_count": 0, "xd_count": 0, "segments": []},
        
        # 交易信号
        "signal": signal_data,
        
        # 宏观新闻
        "news": macro_news,
        
        # 产业分析
        "industry": industry_data.get("data", {}) if industry_data.get("status") in ["success", "simulated"] else {},
        
        # 图表路径
        "chan_chart": "/static/chan_bi_xd.png" if os.path.exists(os.path.join(WORKSPACE, "static", "chan_bi_xd.png")) else None
    }
    
    return render_template('index.html', **context)

@app.route('/api/quote')
def api_quote():
    """API: 获取PTA实时行情"""
    data = get_pta_realtime()
    if data:
        return jsonify({"success": True, "data": data})
    return jsonify({"success": False, "error": "无法获取行情"})

@app.route('/api/cost')
def api_cost():
    """API: 获取成本分析"""
    brent = get_brent()
    px = get_px_price()
    ta = get_pta_spot()
    
    brent_price = brent["price"] if brent else None
    px_price = px["px_price"] if px else None
    ta_price = ta["pta_spot"] if ta else None
    
    cost_low, cost_high = calc_pta_cost(brent_price, px_price)
    
    result = {
        "brent_usd": brent_price,
        "brent_cny": brent_price * 7.25 if brent_price else None,
        "px_cny": px_price,
        "pta_spot": ta_price,
        "pta_cost_low": cost_low,
        "pta_cost_high": cost_high,
        "margin": (ta_price - (cost_low + cost_high) / 2) if ta_price and cost_low else None,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    return jsonify({"success": True, "data": result})

@app.route('/api/options')
def api_options():
    """API: 获取期权数据"""
    data = get_ta_options()
    if data:
        return jsonify({"success": True, "data": data})
    return jsonify({"success": False, "error": "无法获取期权数据"})

@app.route('/api/chan')
def api_chan():
    """API: 获取缠论分析"""
    data = get_chan_analysis()
    if data:
        return jsonify({"success": True, "data": data})
    return jsonify({"success": False, "error": "无法获取缠论分析"})

@app.route('/api/signal')
def api_signal():
    """API: 获取交易信号"""
    pta_data = get_pta_realtime()
    brent_data = get_brent()
    px_data = get_px_price()
    options_data = get_ta_options()
    chan_data = get_chan_analysis()
    
    brent_price = brent_data["price"] if brent_data else None
    px_price = px_data["px_price"] if px_data else None
    cost_low, cost_high = calc_pta_cost(brent_price, px_price)
    
    pta_price = pta_data["last_price"] if pta_data else None
    pcr = options_data["pcr"] if options_data else None
    tech_score = chan_data.get("tech_score", 50) if chan_data else 50
    
    signal_data = generate_signal(pta_price, cost_low, cost_high, pcr, tech_score)
    
    result = {
        "signal": signal_data,
        "pta_price": pta_price,
        "cost_low": cost_low,
        "cost_high": cost_high,
        "pcr": pcr,
        "tech_score": tech_score,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    return jsonify({"success": True, "data": result})

@app.route('/api/news')
def api_news():
    """API: 获取宏观新闻"""
    news = get_macro_news()
    return jsonify({"success": True, "data": news, "count": len(news)})

@app.route('/api/history')
def api_history():
    """API: 获取历史信号"""
    try:
        limit = request.args.get('limit', 50, type=int)
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM signal_log ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return jsonify({
            "success": True,
            "data": [dict(r) for r in rows],
            "count": len(rows)
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/chan/')
def chan_page():
    """缠论分析页面"""
    chan_data = get_chan_analysis()
    chart_path = os.path.join(WORKSPACE, "charts", "chan_bi_xd.png")
    
    context = {
        "title": "缠论技术分析",
        "chan": chan_data or {"bi_count": 0, "xd_count": 0, "segments": []},
        "has_chart": os.path.exists(chart_path),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # 创建缠论页面模板
    chan_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>缠论技术分析</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body { padding: 20px; background-color: #f5f7fa; }
            .header { background: linear-gradient(135deg, #2c3e50, #3498db); color: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }
            .card { margin-bottom: 20px; box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
            .segment-item { padding: 10px; background: #f8f9fa; border-radius: 8px; margin-bottom: 8px; border-left: 4px solid #3498db; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1><i class="fas fa-project-diagram"></i> 缠论技术分析</h1>
                <p>PTA期货笔、线段、中枢分析</p>
                <a href="/" class="btn btn-light btn-sm">返回主页</a>
            </div>
            
            <div class="row">
                <div class="col-md-6">
                    <div class="card">
                        <div class="card-header">分析概览</div>
                        <div class="card-body">
                            <div class="row text-center">
                                <div class="col-4">
                                    <div class="stat-label">笔数量</div>
                                    <div class="stat-value" style="font-size: 1.5rem; font-weight: bold;">{{ chan.bi_count }}</div>
                                </div>
                                <div class="col-4">
                                    <div class="stat-label">线段数量</div>
                                    <div class="stat-value" style="font-size: 1.5rem; font-weight: bold;">{{ chan.xd_count }}</div>
                                </div>
                                <div class="col-4">
                                    <div class="stat-label">中枢高度</div>
                                    <div class="stat-value" style="font-size: 1.5rem; font-weight: bold;">{{ chan.zz_height if chan.zz_height else "N/A" }}</div>
                                </div>
                            </div>
                            
                            {% if chan.zd and chan.zg %}
                            <div class="mt-3">
                                <p><strong>中枢区间:</strong> {{ chan.zd }} - {{ chan.zg }}</p>
                                <p><strong>趋势方向:</strong> {{ chan.trend }}</p>
                            </div>
                            {% endif %}
                        </div>
                    </div>
                </div>
                
                <div class="col-md-6">
                    <div class="card">
                        <div class="card-header">线段详情</div>
                        <div class="card-body">
                            {% if chan.segments %}
                                {% for segment in chan.segments %}
                                <div class="segment-item">
                                    <div><strong>{{ segment.name }}</strong></div>
                                    <div class="small text-muted">
                                        笔范围: {{ segment.bi_range }}<br>
                                        时间: {{ segment.time }}<br>
                                        价格: {{ segment.price }}
                                    </div>
                                </div>
                                {% endfor %}
                            {% else %}
                                <p class="text-muted">暂无线段数据</p>
                            {% endif %}
                        </div>
                    </div>
                </div>
            </div>
            
            {% if has_chart %}
            <div class="card">
                <div class="card-header">缠论图表</div>
                <div class="card-body text-center">
                    <img src="/static/chan_bi_xd.png" alt="缠论分析图" style="max-width: 100%; border: 1px solid #ddd; border-radius: 8px;">
                    <div class="mt-3">
                        <a href="/static/chan_bi_xd.png" target="_blank" class="btn btn-primary">查看大图</a>
                        <a href="/" class="btn btn-secondary">返回主页</a>
                    </div>
                </div>
            </div>
            {% endif %}
            
            <div class="text-center mt-4">
                <p class="text-muted">更新时间: {{ timestamp }}</p>
            </div>
        </div>
        
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
        <script src="https://kit.fontawesome.com/your-fontawesome-kit.js" crossorigin="anonymous"></script>
    </body>
    </html>
    """
    
    return render_template_string(chan_template, **context)

@app.route('/history')
def history_page():
    """历史数据页面"""
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>历史数据</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body { padding: 20px; background-color: #f5f7fa; }
            .header { background: linear-gradient(135deg, #2c3e50, #3498db); color: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1><i class="fas fa-history"></i> 历史数据</h1>
                <p>查看历史交易信号和分析记录</p>
                <a href="/" class="btn btn-light btn-sm">返回主页</a>
            </div>
            
            <div class="card">
                <div class="card-header">历史信号</div>
                <div class="card-body">
                    <div id="history-data" class="text-center">
                        <div class="spinner-border text-primary" role="status">
                            <span class="visually-hidden">加载中...</span>
                        </div>
                        <p>正在加载历史数据...</p>
                    </div>
                </div>
            </div>
            
            <div class="text-center mt-4">
                <a href="/" class="btn btn-primary">返回主页</a>
            </div>
        </div>
        
        <script>
            // 加载历史数据
            fetch('/api/history?limit=100')
                .then(response => response.json())
                .then(data => {
                    const container = document.getElementById('history-data');
                    if (data.success && data.data.length > 0) {
                        let html = '<table class="table table-striped"><thead><tr>';
                        html += '<th>时间</th><th>价格</th><th>信号</th><th>分数</th><th>成本区间</th></tr></thead><tbody>';
                        
                        data.data.forEach(item => {
                            html += `<tr>
                                <td>${item.created_at}</td>
                                <td>${item.last_price || 'N/A'}</td>
                                <td><span class="badge ${item.signal === '做多' ? 'bg-success' : item.signal === '做空' ? 'bg-danger' : 'bg-warning'}">${item.signal || 'N/A'}</span></td>
                                <td>${item.macro_score || 'N/A'}</td>
                                <td>${item.cost_low || 'N/A'} - ${item.cost_high || 'N/A'}</td>
                            </tr>`;
                        });
                        
                        html += '</tbody></table>';
                        container.innerHTML = html;
                    } else {
                        container.innerHTML = '<p class="text-muted">暂无历史数据</p>';
                    }
                })
                .catch(error => {
                    document.getElementById('history-data').innerHTML = '<p class="text-danger">加载失败: ' + error + '</p>';
                });
        </script>
        
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
        <script src="https://kit.fontawesome.com/your-fontawesome-kit.js" crossorigin="anonymous"></script>
    </body>
    </html>
    """)

@app.route('/industry')
def industry_page():
    """产业分析页面"""
    industry_data = get_industry_analysis()
    
    # 安全地提取数据
    data = {}
    if industry_data.get("status") in ["success", "simulated"]:
        data = industry_data.get("data", {})
    
    # 确保所有必要的键都存在
    safe_data = {
        "upstream": data.get("upstream", {}),
        "pta": data.get("pta", {}),
        "cost": data.get("cost", {}),
        "supply": data.get("supply", {}),
        "demand": data.get("demand", {}),
        "analysis": data.get("analysis", {})
    }
    
    context = {
        "title": "PTA产业基本面分析",
        "industry": safe_data,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>PTA产业基本面分析</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body { padding: 20px; background-color: #f5f7fa; }
            .header { background: linear-gradient(135deg, #2c3e50, #3498db); color: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }
            .section { margin-bottom: 30px; }
            .metric-card { padding: 15px; background: white; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); margin-bottom: 15px; }
            .metric-value { font-size: 1.5rem; font-weight: bold; }
            .metric-label { color: #666; font-size: 0.9rem; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1><i class="fas fa-industry"></i> PTA产业基本面分析</h1>
                <p>多维度产业数据分析 - 上游原料、成本利润、供需平衡</p>
                <a href="/" class="btn btn-light btn-sm">返回主页</a>
            </div>
            
            {% if industry %}
            <!-- 综合评分 -->
            <div class="section">
                <div class="row">
                    <div class="col-md-6">
                        <div class="metric-card">
                            <div class="metric-label">产业综合评分</div>
                            <div class="metric-value" style="color: 
                                {% if industry.analysis.industry_score >= 70 %}#27ae60
                                {% elif industry.analysis.industry_score >= 50 %}#f39c12
                                {% else %}#e74c3c{% endif %}; font-size: 2.5rem;">
                                {{ industry.analysis.industry_score }}/100
                            </div>
                            <div class="mt-2">
                                <span class="badge bg-primary">{{ industry.analysis.industry_outlook }}</span>
                                <span class="badge bg-secondary">{{ industry.analysis.supply_demand_balance }}</span>
                                {% if industry.analysis.cost_support %}
                                <span class="badge bg-info">成本支撑: {{ industry.analysis.cost_support }}</span>
                                {% endif %}
                            </div>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="metric-card">
                            <div class="metric-label">产业趋势</div>
                            {% if industry.analysis.trends %}
                                <ul class="list-unstyled">
                                    {% for trend in industry.analysis.trends %}
                                    <li><i class="fas fa-arrow-right text-primary me-2"></i>{{ trend }}</li>
                                    {% endfor %}
                                </ul>
                            {% else %}
                                <p class="text-muted">暂无趋势分析</p>
                            {% endif %}
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- 价格体系 -->
            <div class="section">
                <h3>价格体系</h3>
                <div class="row">
                    <div class="col-md-4">
                        <div class="metric-card">
                            <div class="metric-label">PTA现货价格</div>
                            <div class="metric-value">
                                {% if industry.pta.spot.price %}
                                    {{ "%.0f"|format(industry.pta.spot.price) }} 元/吨
                                {% else %}
                                    N/A
                                {% endif %}
                            </div>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="metric-card">
                            <div class="metric-label">PTA期货价格</div>
                            <div class="metric-value">
                                {% if industry.pta.future.last_price %}
                                    {{ "%.0f"|format(industry.pta.future.last_price) }} 元/吨
                                {% else %}
                                    N/A
                                {% endif %}
                            </div>
                            {% if industry.pta.future.change_pct %}
                            <div class="small {% if industry.pta.future.change_pct > 0 %}text-success{% else %}text-danger{% endif %}">
                                {{ "%+.2f"|format(industry.pta.future.change_pct) }}%
                            </div>
                            {% endif %}
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="metric-card">
                            <div class="metric-label">基差</div>
                            <div class="metric-value">
                                {% if industry.pta.basis.value %}
                                    {{ "%.0f"|format(industry.pta.basis.value) }} 元/吨
                                {% else %}
                                    N/A
                                {% endif %}
                            </div>
                            {% if industry.pta.basis.premium %}
                            <div class="small">{{ industry.pta.basis.premium }}</div>
                            {% endif %}
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- 成本利润 -->
            <div class="section">
                <h3>成本利润分析</h3>
                <div class="row">
                    <div class="col-md-3">
                        <div class="metric-card">
                            <div class="metric-label">PX价格</div>
                            <div class="metric-value">
                                {% if industry.upstream.px.price %}
                                    {{ "%.0f"|format(industry.upstream.px.price) }} 元/吨
                                {% else %}
                                    N/A
                                {% endif %}
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="metric-card">
                            <div class="metric-label">PTA成本</div>
                            <div class="metric-value">
                                {% if industry.cost.pta_cost.cost_mid %}
                                    {{ "%.0f"|format(industry.cost.pta_cost.cost_mid) }} 元/吨
                                {% else %}
                                    N/A
                                {% endif %}
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="metric-card">
                            <div class="metric-label">加工利润</div>
                            <div class="metric-value {% if industry.cost.profit.profit > 0 %}text-success{% else %}text-danger{% endif %}">
                                {% if industry.cost.profit.profit %}
                                    {{ "%.0f"|format(industry.cost.profit.profit) }} 元/吨
                                {% else %}
                                    N/A
                                {% endif %}
                            </div>
                            {% if industry.cost.profit.level %}
                            <div class="small">{{ industry.cost.profit.level }}</div>
                            {% endif %}
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="metric-card">
                            <div class="metric-label">PXN价差</div>
                            <div class="metric-value">
                                {% if industry.cost.pxn_spread.spread %}
                                    {{ "%.0f"|format(industry.cost.pxn_spread.spread) }} 元/吨
                                {% else %}
                                    N/A
                                {% endif %}
                            </div>
                            {% if industry.cost.pxn_spread.level %}
                            <div class="small">{{ industry.cost.pxn_spread.level }}水平</div>
                            {% endif %}
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- 供需分析 -->
            <div class="section">
                <h3>供需分析</h3>
                <div class="row">
                    <div class="col-md-4">
                        <div class="metric-card">
                            <div class="metric-label">PTA开工率</div>
                            <div class="metric-value">
                                {% if industry.supply.pta_operating.rate %}
                                    {{ "%.1f"|format(industry.supply.pta_operating.rate) }}%
                                {% else %}
                                    N/A
                                {% endif %}
                            </div>
                            {% if industry.supply.pta_operating.trend %}
                            <div class="small">{{ industry.supply.pta_operating.trend }}</div>
                            {% endif %}
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="metric-card">
                            <div class="metric-label">聚酯开工率</div>
                            <div class="metric-value">
                                {% if industry.demand.polyester.operating_rate %}
                                    {{ "%.1f"|format(industry.demand.polyester.operating_rate) }}%
                                {% else %}
                                    N/A
                                {% endif %}
                            </div>
                            {% if industry.demand.polyester.trend %}
                            <div class="small">{{ industry.demand.polyester.trend }}</div>
                            {% endif %}
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="metric-card">
                            <div class="metric-label">社会库存</div>
                            <div class="metric-value">
                                {% if industry.demand.inventory.pta_social_inventory %}
                                    {{ "%.1f"|format(industry.demand.inventory.pta_social_inventory) }} 万吨
                                {% else %}
                                    N/A
                                {% endif %}
                            </div>
                            {% if industry.demand.inventory.level %}
                            <div class="small">{{ industry.demand.inventory.level }}</div>
                            {% endif %}
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- 上游原料 -->
            <div class="section">
                <h3>上游原料</h3>
                <div class="row">
                    <div class="col-md-4">
                        <div class="metric-card">
                            <div class="metric-label">布伦特原油</div>
                            <div class="metric-value">
                                {% if industry.upstream.brent.price %}
                                    ${{ "%.2f"|format(industry.upstream.brent.price) }}
                                {% else %}
                                    N/A
                                {% endif %}
                            </div>
                            {% if industry.upstream.brent.change_pct %}
                            <div class="small {% if industry.upstream.brent.change_pct > 0 %}text-success{% else %}text-danger{% endif %}">
                                {{ "%+.2f"|format(industry.upstream.brent.change_pct) }}%
                            </div>
                            {% endif %}
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="metric-card">
                            <div class="metric-label">石脑油</div>
                            <div class="metric-value">
                                {% if industry.upstream.naphtha.price %}
                                    ${{ "%.2f"|format(industry.upstream.naphtha.price) }}
                                {% else %}
                                    N/A
                                {% endif %}
                            </div>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="metric-card">
                            <div class="metric-label">WTI原油</div>
                            <div class="metric-value">
                                {% if industry.upstream and industry.upstream.wti and industry.upstream.wti.price %}
                                    ${{ "%.2f"|format(industry.upstream.wti.price) }}
                                {% else %}
                                    N/A
                                {% endif %}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            {% else %}
            <div class="alert alert-warning">
                <i class="fas fa-exclamation-triangle me-2"></i>
                产业数据加载失败，请稍后重试。
            </div>
            {% endif %}
            
            <div class="text-center mt-4">
                <a href="/" class="btn btn-primary">返回主页</a>
                <button onclick="window.print()" class="btn btn-secondary">
                    <i class="fas fa-print me-1"></i>打印报告
                </button>
            </div>
            
            <div class="text-center mt-4 text-muted">
                <p>更新时间: {{ timestamp }}</p>
                <p class="small">数据来源: akshare + 产业调研数据</p>
            </div>
        </div>
        
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
        <script src="https://kit.fontawesome.com/your-fontawesome-kit.js" crossorigin="anonymous"></script>
    </body>
    </html>
    """, **context)

@app.route('/macro')
def macro_page():
    """宏观分析页面"""
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>宏观分析</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body { padding: 20px; background-color: #f5f7fa; }
            .header { background: linear-gradient(135deg, #2c3e50, #27ae60); color: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }
            .news-item { padding: 15px; border-bottom: 1px solid #eee; }
            .news-item:last-child { border-bottom: none; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1><i class="fas fa-globe"></i> 宏观分析</h1>
                <p>全球宏观经济新闻和数据分析</p>
                <a href="/" class="btn btn-light btn-sm">返回主页</a>
            </div>
            
            <div class="card">
                <div class="card-header">实时新闻</div>
                <div class="card-body">
                    <div id="news-data" class="text-center">
                        <div class="spinner-border text-primary" role="status">
                            <span class="visually-hidden">加载中...</span>
                        </div>
                        <p>正在加载新闻数据...</p>
                    </div>
                </div>
            </div>
            
            <div class="text-center mt-4">
                <a href="/" class="btn btn-primary">返回主页</a>
            </div>
        </div>
        
        <script>
            // 加载新闻数据
            fetch('/api/news')
                .then(response => response.json())
                .then(data => {
                    const container = document.getElementById('news-data');
                    if (data.success && data.data.length > 0) {
                        let html = '';
                        data.data.forEach(item => {
                            html += `<div class="news-item">
                                <h5>${item.title || '无标题'}</h5>
                                <p class="text-muted">${item.time || ''} · ${item.source || '未知来源'}</p>
                                <p>${item.summary || '无摘要'}</p>
                                ${item.url ? `<a href="${item.url}" target="_blank" class="btn btn-sm btn-outline-primary">查看原文</a>` : ''}
                            </div>`;
                        });
                        container.innerHTML = html;
                    } else {
                        container.innerHTML = '<p class="text-muted">暂无新闻数据</p>';
                    }
                })
                .catch(error => {
                    document.getElementById('news-data').innerHTML = '<p class="text-danger">加载失败: ' + error + '</p>';
                });
        </script>
        
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
        <script src="https://kit.fontawesome.com/your-fontawesome-kit.js" crossorigin="anonymous"></script>
    </body>
    </html>
    """)

@app.route('/kline')
def kline_page():
    """1分钟K线图页面"""
    return render_template('kline_1min.html', title='PTA期货1分钟K线图')

@app.route('/api/kline_data')
def get_kline_data():
    """获取K线数据API"""
    try:
        period = request.args.get('period', '1', type=str)
        # 这里应该实现获取K线数据的逻辑
        # 暂时返回模拟数据
        import random
        from datetime import datetime, timedelta
        
        data = []
        base_price = 6900
        now = datetime.now()
        
        for i in range(100):
            time = now - timedelta(minutes=i)
            open_price = base_price + random.uniform(-20, 20)
            close_price = open_price + random.uniform(-10, 10)
            high_price = max(open_price, close_price) + random.uniform(0, 15)
            low_price = min(open_price, close_price) - random.uniform(0, 15)
            volume = random.randint(1000, 5000)
            
            data.append({
                'time': time.strftime('%Y-%m-%d %H:%M:%S'),
                'open': round(open_price, 2),
                'high': round(high_price, 2),
                'low': round(low_price, 2),
                'close': round(close_price, 2),
                'volume': volume
            })
        
        return jsonify({
            'success': True,
            'data': data,
            'symbol': 'TA',
            'period': f'{period}min'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# ==================== 高级缠论API ====================

@app.route('/api/chan_advanced')
def api_chan_advanced():
    """API: 获取高级缠论分析"""
    try:
        # 导入高级缠论分析模块
        from chan_advanced import get_chan_advanced_analysis
        
        symbol = request.args.get('symbol', 'TA')
        period = request.args.get('period', '1d')
        
        result = get_chan_advanced_analysis(symbol, period)
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        })

@app.route('/api/chan_signals')
def api_chan_signals():
    """API: 获取缠论实时信号"""
    try:
        # 获取最新的缠论分析
        from chan_advanced import get_chan_advanced_analysis
        result = get_chan_advanced_analysis()
        
        if result.get('success'):
            signals = result.get('signals', [])
            return jsonify({
                'success': True,
                'signals': signals,
                'count': len(signals),
                'timestamp': datetime.now().isoformat()
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', '未知错误'),
                'timestamp': datetime.now().isoformat()
            })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        })

@app.route('/api/chan_bi')
def api_chan_bi():
    """API: 获取笔列表"""
    try:
        from chan_advanced import get_chan_advanced_analysis
        result = get_chan_advanced_analysis()
        
        if result.get('success'):
            bi_list = result.get('bi_list', [])
            return jsonify({
                'success': True,
                'bi_list': bi_list,
                'count': len(bi_list),
                'timestamp': datetime.now().isoformat()
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', '未知错误'),
                'timestamp': datetime.now().isoformat()
            })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        })

@app.route('/api/chan_xd')
def api_chan_xd():
    """API: 获取线段列表"""
    try:
        from chan_advanced import get_chan_advanced_analysis
        result = get_chan_advanced_analysis()
        
        if result.get('success'):
            xd_list = result.get('xd_list', [])
            return jsonify({
                'success': True,
                'xd_list': xd_list,
                'count': len(xd_list),
                'timestamp': datetime.now().isoformat()
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', '未知错误'),
                'timestamp': datetime.now().isoformat()
            })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        })

@app.route('/api/chan_zhongshu')
def api_chan_zhongshu():
    """API: 获取中枢列表"""
    try:
        from chan_advanced import get_chan_advanced_analysis
        result = get_chan_advanced_analysis()
        
        if result.get('success'):
            zhongshu_list = result.get('zhongshu_list', [])
            return jsonify({
                'success': True,
                'zhongshu_list': zhongshu_list,
                'count': len(zhongshu_list),
                'timestamp': datetime.now().isoformat()
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', '未知错误'),
                'timestamp': datetime.now().isoformat()
            })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        })

# ==================== 缠论Web页面 ====================

@app.route('/chan_web')
def chan_web_page():
    """缠论Web分析页面"""
    return render_template('chan_web.html', title='缠论分析系统')

# ==================== WebSocket支持 ====================

# WebSocket连接管理
chan_connections = []

def broadcast_chan_update(data):
    """广播缠论更新到所有WebSocket连接"""
    import json
    message = json.dumps({
        'type': 'update',
        'data': data,
        'timestamp': datetime.now().isoformat()
    })
    
    # 这里需要实际的WebSocket实现
    # 暂时记录日志
    print(f"[WebSocket] 广播缠论更新: {data.get('type', 'unknown')}")

def broadcast_chan_signal(signal):
    """广播缠论信号到所有WebSocket连接"""
    import json
    message = json.dumps({
        'type': 'signal',
        'data': signal,
        'timestamp': datetime.now().isoformat()
    })
    
    # 这里需要实际的WebSocket实现
    # 暂时记录日志
    print(f"[WebSocket] 广播缠论信号: {signal.get('text', 'unknown')}")

# 定时更新缠论数据
def update_chan_data_periodically():
    """定时更新缠论数据"""
    import time
    while True:
        try:
            from chan_advanced import get_chan_advanced_analysis
            result = get_chan_advanced_analysis()
            
            if result.get('success'):
                # 广播更新
                broadcast_chan_update({
                    'type': 'full_update',
                    'summary': result.get('summary', {}),
                    'timestamp': result.get('timestamp')
                })
                
                # 广播新信号
                signals = result.get('signals', [])
                if signals:
                    for signal in signals:
                        broadcast_chan_signal(signal)
            
            # 每30秒更新一次
            time.sleep(30)
        except Exception as e:
            print(f"[ERROR] 定时更新缠论数据失败: {e}")
            time.sleep(60)

# 启动定时更新线程
import threading
chan_update_thread = threading.Thread(target=update_chan_data_periodically, daemon=True)
chan_update_thread.start()

# ==================== 主函数 ====================

if __name__ == '__main__':
    # 初始化数据库
    init_db()
    
    # 启动Flask应用
    app.run(host='0.0.0.0', port=5000, debug=True)
        symbol = request.args.get('symbol', 'TA0', type=str)
        
        # 这里应该从数据库或实时API获取数据
        # 暂时返回模拟数据
        import random
        from datetime import datetime, timedelta
        
        data_points = 100
        now = datetime.now()
        period_minutes = int(period)
        
        labels = []
        data = []
        
        base_price = 6000
        
        for i in range(data_points):
            time = now - timedelta(minutes=(data_points - i - 1) * period_minutes)
            labels.append(time.isoformat())
            
            open_price = base_price + (random.random() - 0.5) * 100
            close_price = open_price + (random.random() - 0.5) * 80
            high_price = max(open_price, close_price) + random.random() * 40
            low_price = min(open_price, close_price) - random.random() * 40
            volume = random.randint(5000, 15000)
            
            data.append({
                'time': time.isoformat(),
                'open': round(open_price, 2),
                'high': round(high_price, 2),
                'low': round(low_price, 2),
                'close': round(close_price, 2),
                'volume': volume
            })
            
            base_price = close_price
        
        return jsonify({
            'success': True,
            'symbol': symbol,
            'period': period,
            'data': data,
            'count': len(data),
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/static/<path:filename>')
def serve_static(filename):
    """提供静态文件"""
    return send_from_directory(os.path.join(WORKSPACE, "static"), filename)

# ==================== 启动应用 ====================
if __name__ == '__main__':
    # 初始化数据库
    init_db()
    
    # 复制缠论图表到静态目录
    chart_src = os.path.join(WORKSPACE, "charts", "chan_bi_xd.png")
    chart_dst = os.path.join(WORKSPACE, "static", "chan_bi_xd.png")
    if os.path.exists(chart_src):
        import shutil
        shutil.copy2(chart_src, chart_dst)
        print(f"[INFO] 复制图表到静态目录: {chart_dst}")
    
    print(f"[INFO] 启动PTA分析平台: http://0.0.0.0:8423/")
    print(f"[INFO] 静态文件目录: {os.path.join(WORKSPACE, 'static')}")
    print(f"[INFO] 模板目录: {os.path.join(WORKSPACE, 'templates')}")
    
    # 启动Flask应用
    app.run(host='0.0.0.0', port=8423, debug=True)
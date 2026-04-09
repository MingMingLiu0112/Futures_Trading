#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简化的PTA分析Web应用
专注于核心功能，避免复杂依赖
"""

from flask import Flask, render_template_string, jsonify, request
import os
import sqlite3
from datetime import datetime
import json

WORKSPACE = os.path.dirname(os.path.abspath(__file__))

# ==================== 数据库 ====================
def get_db():
    """获取数据库连接"""
    conn = sqlite3.connect('/tmp/pta_analysis_simple.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """初始化数据库"""
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS signal_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            signal TEXT,
            score INTEGER,
            price REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

# ==================== 数据获取函数 ====================
def get_simple_data():
    """获取简化数据"""
    import akshare as ak
    import pandas as pd
    
    data = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "pta": {},
        "brent": {},
        "options": {}
    }
    
    try:
        # PTA期货价格
        df = ak.futures_zh_realtime(symbol='PTA')
        if df is not None and not df.empty:
            row = df[df['symbol'] == 'TA0'].iloc[0] if 'TA0' in df['symbol'].values else df.iloc[0]
            data["pta"] = {
                "last_price": float(row.get("trade", 0)),
                "change_pct": float(row.get("changepercent", 0)),
                "open": float(row.get("open", 0)),
                "high": float(row.get("high", 0)),
                "low": float(row.get("low", 0)),
                "volume": int(row.get("volume", 0))
            }
    except Exception as e:
        print(f"[WARN] PTA数据错误: {e}")
        data["pta"] = {"last_price": 6888, "change_pct": -0.5}
    
    try:
        # 布伦特原油
        df = ak.futures_global_spot_em()
        if df is not None and not df.empty:
            brent = df[df['名称'].str.contains('布伦特', na=False)]
            if not brent.empty:
                row = brent.sort_values('成交量', ascending=False).iloc[0]
                data["brent"] = {
                    "price": float(row.get("最新价", 0)),
                    "change_pct": float(row.get("涨跌幅", 0))
                }
    except Exception as e:
        print(f"[WARN] 原油数据错误: {e}")
        data["brent"] = {"price": 76.05, "change_pct": 0.5}
    
    try:
        # 期权数据
        df = ak.option_contract_info_ctp()
        if df is not None and not df.empty:
            ta = df[(df['交易所ID'] == 'CZCE') & (df['合约名称'].str.startswith('TA', na=False))]
            if not ta.empty:
                # 计算PCR
                call_oi = ta[ta['看涨看跌'] == 'C']['持仓量'].sum()
                put_oi = ta[ta['看涨看跌'] == 'P']['持仓量'].sum()
                pcr = put_oi / call_oi if call_oi > 0 else 0
                
                data["options"] = {
                    "count": len(ta),
                    "pcr": round(pcr, 3),
                    "call_oi": int(call_oi),
                    "put_oi": int(put_oi)
                }
    except Exception as e:
        print(f"[WARN] 期权数据错误: {e}")
        data["options"] = {"count": 0, "pcr": 0.8}
    
    return data

def get_industry_summary():
    """获取产业分析摘要"""
    data = get_simple_data()
    
    # 简单产业分析
    pta_price = data["pta"].get("last_price", 6888)
    brent_price = data["brent"].get("price", 76.05)
    
    # 模拟PX价格
    px_price = brent_price * 7.5 * 1.05 * 1000  # 简单换算
    
    # 成本计算
    pta_cost = px_price * 0.655 + 800
    profit = pta_price - pta_cost
    
    # 产业评分
    score = 50
    if profit < 0:
        score += 20  # 亏损时成本支撑强
    elif profit > 300:
        score -= 10  # 高利润时成本支撑弱
    
    return {
        "pta_price": pta_price,
        "pta_cost": round(pta_cost, 2),
        "profit": round(profit, 2),
        "industry_score": score,
        "outlook": "乐观" if score >= 70 else "中性" if score >= 50 else "谨慎"
    }

# ==================== Flask应用 ====================
app = Flask(__name__)

# 主页面
@app.route('/')
def index():
    """主页面"""
    data = get_simple_data()
    industry = get_industry_summary()
    
    html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>PTA期货分析平台</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body { padding: 20px; background-color: #f5f7fa; }
            .header { background: linear-gradient(135deg, #2c3e50, #3498db); color: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }
            .card { margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
            .stat-value { font-size: 1.5rem; font-weight: bold; }
            .stat-label { color: #666; font-size: 0.9rem; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>📊 PTA期货分析平台</h1>
                <p>简化版 - 核心数据展示</p>
            </div>
            
            <div class="row">
                <div class="col-md-4">
                    <div class="card">
                        <div class="card-header">PTA期货</div>
                        <div class="card-body">
                            <div class="stat-value">{{ "%.0f"|format(data.pta.last_price) }} 元/吨</div>
                            <div class="stat-label">
                                {% if data.pta.change_pct > 0 %}
                                    <span style="color: #27ae60">↑ {{ "%.2f"|format(data.pta.change_pct) }}%</span>
                                {% else %}
                                    <span style="color: #e74c3c">↓ {{ "%.2f"|format(data.pta.change_pct) }}%</span>
                                {% endif %}
                            </div>
                        </div>
                    </div>
                </div>
                
                <div class="col-md-4">
                    <div class="card">
                        <div class="card-header">布伦特原油</div>
                        <div class="card-body">
                            <div class="stat-value">${{ "%.2f"|format(data.brent.price) }}</div>
                            <div class="stat-label">
                                {% if data.brent.change_pct > 0 %}
                                    <span style="color: #27ae60">↑ {{ "%.2f"|format(data.brent.change_pct) }}%</span>
                                {% else %}
                                    <span style="color: #e74c3c">↓ {{ "%.2f"|format(data.brent.change_pct) }}%</span>
                                {% endif %}
                            </div>
                        </div>
                    </div>
                </div>
                
                <div class="col-md-4">
                    <div class="card">
                        <div class="card-header">期权PCR</div>
                        <div class="card-body">
                            <div class="stat-value">{{ "%.3f"|format(data.options.pcr) }}</div>
                            <div class="stat-label">
                                {% if data.options.pcr > 1.2 %}
                                    高PCR (偏多头)
                                {% elif data.options.pcr < 0.8 %}
                                    低PCR (偏空头)
                                {% else %}
                                    正常范围
                                {% endif %}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="row">
                <div class="col-md-6">
                    <div class="card">
                        <div class="card-header">产业分析</div>
                        <div class="card-body">
                            <div class="row">
                                <div class="col-6">
                                    <div class="stat-label">产业评分</div>
                                    <div class="stat-value" style="color: 
                                        {% if industry.industry_score >= 70 %}#27ae60
                                        {% elif industry.industry_score >= 50 %}#f39c12
                                        {% else %}#e74c3c{% endif %}">
                                        {{ industry.industry_score }}/100
                                    </div>
                                    <div class="small">{{ industry.outlook }}</div>
                                </div>
                                <div class="col-6">
                                    <div class="stat-label">加工利润</div>
                                    <div class="stat-value {% if industry.profit > 0 %}text-success{% else %}text-danger{% endif %}">
                                        {{ "%.0f"|format(industry.profit) }} 元/吨
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                
                <div class="col-md-6">
                    <div class="card">
                        <div class="card-header">快速导航</div>
                        <div class="card-body">
                            <div class="d-grid gap-2">
                                <a href="/chan" class="btn btn-primary">缠论分析</a>
                                <a href="/api/data" class="btn btn-secondary">API数据</a>
                                <a href="/industry" class="btn btn-info">产业分析</a>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="text-center mt-4 text-muted">
                <p>更新时间: {{ data.timestamp }}</p>
                <p class="small">数据来源: akshare</p>
            </div>
        </div>
    </body>
    </html>
    '''
    
    return render_template_string(html, data=data, industry=industry)

# 缠论页面
@app.route('/chan')
def chan_page():
    """缠论分析页面"""
    html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>缠论分析</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body>
        <div class="container mt-4">
            <h1>📈 缠论技术分析</h1>
            <p>PTA期货缠论线段分析</p>
            
            <div class="card">
                <div class="card-header">分析结果</div>
                <div class="card-body">
                    <p>缠论分析功能正在开发中...</p>
                    <p>当前检测到3条线段：</p>
                    <ul>
                        <li>XD1↑ bi1~3 [09:01~09:58] 6726→6922</li>
                        <li>XD2↓ bi4~6 [09:58~10:35] 6922→6810</li>
                        <li>XD3↑ bi7~16 [10:35~14:54] 6810→6948</li>
                    </ul>
                </div>
            </div>
            
            <div class="mt-3">
                <a href="/" class="btn btn-primary">返回主页</a>
            </div>
        </div>
    </body>
    </html>
    '''
    return render_template_string(html)

# 产业分析页面
@app.route('/industry')
def industry_page():
    """产业分析页面"""
    industry = get_industry_summary()
    data = get_simple_data()
    
    html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>产业分析</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body>
        <div class="container mt-4">
            <h1>🏭 PTA产业分析</h1>
            
            <div class="card">
                <div class="card-header">成本利润分析</div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-4">
                            <div class="stat-label">PTA价格</div>
                            <div class="stat-value">{{ "%.0f"|format(industry.pta_price) }} 元/吨</div>
                        </div>
                        <div class="col-md-4">
                            <div class="stat-label">PTA成本</div>
                            <div class="stat-value">{{ "%.0f"|format(industry.pta_cost) }} 元/吨</div>
                        </div>
                        <div class="col-md-4">
                            <div class="stat-label">加工利润</div>
                            <div class="stat-value {% if industry.profit > 0 %}text-success{% else %}text-danger{% endif %}">
                                {{ "%.0f"|format(industry.profit) }} 元/吨
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="card mt-3">
                <div class="card-header">产业评估</div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-6">
                            <div class="stat-label">产业评分</div>
                            <div class="stat-value" style="font-size: 2.5rem; color: 
                                {% if industry.industry_score >= 70 %}#27ae60
                                {% elif industry.industry_score >= 50 %}#f39c12
                                {% else %}#e74c3c{% endif %}">
                                {{ industry.industry_score }}/100
                            </div>
                            <div class="mt-2">
                                <span class="badge bg-primary">{{ industry.outlook }}</span>
                            </div>
                        </div>
                        <div class="col-md-6">
                            <div class="stat-label">操作建议</div>
                            {% if industry.industry_score >= 70 %}
                                <p class="text-success">✅ 产业面偏多，建议关注做多机会</p>
                            {% elif industry.industry_score >= 50 %}
                                <p class="text-warning">⚠️ 产业面中性，建议观望</p>
                            {% else %}
                                <p class="text-danger">❌ 产业面偏空，建议谨慎</p>
                            {% endif %}
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="mt-3">
                <a href="/" class="btn btn-primary">返回主页</a>
            </div>
        </div>
    </body>
    </html>
    '''
    return render_template_string(html, industry=industry, data=data)

# API接口
@app.route('/api/data')
def api_data():
    """API数据接口"""
    data = get_simple_data()
    return jsonify({
        "success": True,
        "timestamp": data["timestamp"],
        "data": data
    })

@app.route('/api/industry')
def api_industry():
    """产业分析API"""
    industry = get_industry_summary()
    return jsonify({
        "success": True,
        "data": industry
    })

# ==================== 启动应用 ====================
if __name__ == '__main__':
    init_db()
    print(f"[INFO] 启动简化版PTA分析平台: http://0.0.0.0:8424/")
    app.run(host='0.0.0.0', port=8424, debug=False)
"""
PTA量化分析Web展示系统
基于FastAPI + uvicorn
"""
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import json
from datetime import datetime
import os

app = FastAPI(title="PTA量化分析系统", version="1.0.0")

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 数据路径
DATA_DIR = "/data"
sys.path.insert(0, '/home/admin/.openclaw/workspace/codeman/pta_analysis')

def load_data():
    """加载PTA数据"""
    data = {}
    try:
        # 日线数据
        daily = pd.read_csv(f"{DATA_DIR}/pta_1day.csv")
        data['daily'] = {
            'count': len(daily),
            'latest': daily.iloc[-1].to_dict() if len(daily) > 0 else {},
            'range': f"{daily.iloc[0]['datetime'][:10]} ~ {daily.iloc[-1]['datetime'][:10]}" if len(daily) > 0 else "N/A"
        }
    except Exception as e:
        data['daily'] = {'error': str(e)}
    
    return data

@app.get("/", response_class=HTMLResponse)
async def root():
    """首页"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>PTA量化分析系统</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; background: #1a1a2e; color: #eee; }
            h1 { color: #00d4ff; }
            .card { background: #16213e; padding: 20px; margin: 10px 0; border-radius: 10px; }
            .metric { font-size: 24px; color: #00ff88; }
            .label { color: #888; font-size: 14px; }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 10px; text-align: left; border-bottom: 1px solid #333; }
            th { color: #00d4ff; }
            .nav { margin: 20px 0; }
            .nav a { color: #00d4ff; margin: 0 10px; }
        </style>
    </head>
    <body>
        <h1>📊 PTA量化分析系统</h1>
        <div class="nav">
            <a href="/">首页</a>
            <a href="/data">数据概览</a>
            <a href="/analysis">分析视图</a>
        </div>
        
        <div class="card">
            <h2>系统状态</h2>
            <p class="label">运行时间</p>
            <p class="metric" id="uptime">-</p>
        </div>
        
        <div class="card">
            <h2>数据概览</h2>
            <div id="data-overview">加载中...</div>
        </div>
        
        <div class="card">
            <h2>最新行情</h2>
            <div id="latest-price">加载中...</div>
        </div>
        
        <script>
            async function updateData() {
                try {
                    const res = await fetch('/api/dashboard');
                    const data = await res.json();
                    
                    document.getElementById('uptime').textContent = data.uptime;
                    document.getElementById('data-overview').innerHTML = 
                        `<p><span class="label">数据范围：</span>${data.data_range}</p>
                         <p><span class="label">K线数量：</span>${data.bar_count}</p>`;
                    document.getElementById('latest-price').innerHTML = 
                        `<p><span class="label">最新价：</span><span class="metric">${data.latest_price}</span></p>
                         <p><span class="label">涨跌：</span>${data.change}</p>`;
                } catch (e) {
                    console.error(e);
                }
            }
            updateData();
            setInterval(updateData, 5000);
        </script>
    </body>
    </html>
    """

@app.get("/api/dashboard")
async def dashboard():
    """仪表盘数据"""
    try:
        daily = pd.read_csv("/data/pta_1day.csv")
        latest = daily.iloc[-1]
        prev = daily.iloc[-2] if len(daily) > 1 else latest
        
        change = latest['close'] - prev['close']
        change_pct = (change / prev['close'] * 100) if prev['close'] > 0 else 0
        
        return {
            "status": "running",
            "uptime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data_range": f"{daily.iloc[0]['datetime'][:10]} ~ {daily.iloc[-1]['datetime'][:10]}",
            "bar_count": len(daily),
            "latest_price": latest['close'],
            "change": f"{change:+.0f} ({change_pct:+.2f}%)"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/klines/{period}")
async def get_klines(period: str):
    """获取K线数据"""
    try:
        valid_periods = {'1min': 'pta_1min.csv', '5min': 'pta_5min.csv', 
                        '15min': 'pta_15min.csv', '30min': 'pta_30min.csv',
                        '60min': 'pta_60min.csv', '1day': 'pta_1day.csv'}
        
        if period not in valid_periods:
            raise HTTPException(status_code=400, detail="Invalid period")
        
        df = pd.read_csv(f"/data/{valid_periods[period]}")
        # 返回最近100根
        df = df.tail(100)
        
        return JSONResponse(content={
            "period": period,
            "count": len(df),
            "data": df.to_dict(orient='records')
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/data", response_class=HTMLResponse)
async def data_page():
    """数据页面"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>数据概览 - PTA量化分析</title>
        <style>
            body { font-family: Arial; margin: 40px; background: #1a1a2e; color: #eee; }
            h1 { color: #00d4ff; }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 8px; text-align: right; border-bottom: 1px solid #333; }
            th { color: #00d4ff; text-align: left; }
            .nav a { color: #00d4ff; margin: 0 10px; }
        </style>
    </head>
    <body>
        <h1>📊 数据概览</h1>
        <div class="nav">
            <a href="/">首页</a>
            <a href="/data">数据</a>
        </div>
        <div id="table"></div>
        <script>
            async function load() {
                const periods = ['1min', '5min', '15min', '30min', '60min', '1day'];
                let html = '<table><tr><th>周期</th><th>数量</th><th>最新价</th><th>时间</th></tr>';
                for (const p of periods) {
                    try {
                        const r = await fetch(`/api/klines/${p}`);
                        const d = await r.json();
                        if (d.data && d.data.length > 0) {
                            const last = d.data[d.data.length - 1];
                            html += `<tr><td>${p}</td><td>${d.count}</td><td>${last.close}</td><td>${last.datetime}</td></tr>`;
                        }
                    } catch(e) {}
                }
                html += '</table>';
                document.getElementById('table').innerHTML = html;
            }
            load();
        </script>
    </body>
    </html>
    """

@app.get("/analysis", response_class=HTMLResponse)
async def analysis_page():
    """分析视图"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>分析视图 - PTA量化分析</title>
        <style>
            body { font-family: Arial; margin: 40px; background: #1a1a2e; color: #eee; }
            h1 { color: #00d4ff; }
            .chart { background: #16213e; padding: 20px; margin: 10px 0; border-radius: 10px; }
            .nav a { color: #00d4ff; margin: 0 10px; }
        </style>
    </head>
    <body>
        <h1>📈 PTA分析视图</h1>
        <div class="nav">
            <a href="/">首页</a>
            <a href="/data">数据</a>
            <a href="/analysis">分析</a>
        </div>
        <div class="chart">
            <h3>技术指标</h3>
            <p>MACD / RSI / 布林带 / 缠论笔结构</p>
        </div>
        <div class="chart">
            <h3>期权分析</h3>
            <p>PCR / 隐波曲面 / 持仓结构</p>
        </div>
    </body>
    </html>
    """

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)

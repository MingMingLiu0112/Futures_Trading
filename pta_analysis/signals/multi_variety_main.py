#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多品种期货分析平台 - FastAPI 主程序
支持一键更换不同期货品种，自动选择主力合约和最近月期权合约
"""

import sys, os, json, sqlite3, threading, warnings
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import akshare as ak

WORKSPACE = "/home/admin/.openclaw/workspace/codeman/pta_analysis"
sys.path.insert(0, WORKSPACE)

warnings.filterwarnings('ignore')

# ==================== 导入品种配置 ====================
from variety_config import variety_config

# ==================== 数据库 (SQLite) ====================
DB_PATH = "/tmp/multi_variety.db"

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """初始化数据库"""
    conn = get_db()
    
    # 创建品种数据表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS variety_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            variety_code TEXT,
            variety_name TEXT,
            main_contract TEXT,
            option_contract TEXT,
            last_price REAL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            open_interest INTEGER,
            change_pct REAL,
            timestamp TEXT
        )
    """)
    
    # 创建信号记录表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            variety_code TEXT,
            last_price REAL,
            signal TEXT,
            score INTEGER,
            reason TEXT,
            timestamp TEXT
        )
    """)
    
    conn.commit()
    conn.close()

# ==================== 内存缓存 ====================
_cache = {}
_cache_ttl = {}

def get_cache(key: str) -> Optional[dict]:
    if key in _cache and (_cache_ttl.get(key, 0) > datetime.now().timestamp()):
        return _cache[key]
    return None

def set_cache(key: str, value: dict, ttl: int = 30):
    _cache[key] = value
    _cache_ttl[key] = datetime.now().timestamp() + ttl

# ==================== 数据获取函数 ====================
def get_variety_realtime(variety_code: str) -> Dict:
    """获取品种实时行情数据"""
    cache_key = f"realtime_{variety_code}"
    cached = get_cache(cache_key)
    if cached:
        return cached
    
    variety = variety_config.config["varieties"].get(variety_code)
    if not variety:
        return {}
    
    try:
        # 获取期货实时行情
        df = ak.futures_zh_realtime(symbol=variety["futures_symbol"])
        
        if df is not None and not df.empty:
            # 获取主力合约
            main_contract = variety_config.get_main_contract(variety_code)
            
            # 找到主力合约数据
            main_row = None
            for _, row in df.iterrows():
                if row['symbol'] == main_contract:
                    main_row = row
                    break
            
            if main_row is None:
                main_row = df.iloc[0]
            
            # 获取期权合约
            option_contract = variety_config.get_nearest_option_contract(variety_code)
            
            result = {
                "variety_code": variety_code,
                "variety_name": variety["name"],
                "main_contract": main_contract,
                "option_contract": option_contract,
                "last_price": float(main_row.get("trade", 0)),
                "open": float(main_row.get("open", 0)),
                "high": float(main_row.get("high", 0)),
                "low": float(main_row.get("low", 0)),
                "close": float(main_row.get("close", 0)),
                "volume": int(main_row.get("volume", 0)),
                "open_interest": int(main_row.get("position", 0)),
                "change_pct": float(main_row.get("changepercent", 0)),
                "timestamp": datetime.now().isoformat()
            }
            
            set_cache(cache_key, result)
            return result
            
    except Exception as e:
        print(f"[WARN] 获取{variety_code}行情失败: {e}")
    
    # 返回空数据
    return {
        "variety_code": variety_code,
        "variety_name": variety["name"],
        "main_contract": variety_config.get_main_contract(variety_code),
        "option_contract": variety_config.get_nearest_option_contract(variety_code),
        "timestamp": datetime.now().isoformat()
    }

def get_options_data(variety_code: str) -> Dict:
    """获取期权数据"""
    cache_key = f"options_{variety_code}"
    cached = get_cache(cache_key)
    if cached:
        return cached
    
    variety = variety_config.config["varieties"].get(variety_code)
    if not variety:
        return {}
    
    try:
        df = ak.option_contract_info_ctp()
        if df is not None and not df.empty:
            # 过滤交易所和品种
            exchange = variety["exchange"]
            options_symbol = variety.get("options_symbol", variety["futures_symbol"])
            
            if exchange == "CZCE":
                exchange_filter = 'CZCE'
            elif exchange == "SHFE":
                exchange_filter = 'SHFE'
            else:
                exchange_filter = exchange
            
            filtered = df[(df['交易所ID'] == exchange_filter) & 
                         (df['合约名称'].str.startswith(options_symbol, na=False))]
            
            if not filtered.empty:
                # 计算PCR (Put-Call Ratio)
                call_count = len(filtered[filtered['期权类型'] == '看涨期权'])
                put_count = len(filtered[filtered['期权类型'] == '看跌期权'])
                pcr = put_count / call_count if call_count > 0 else 0
                
                result = {
                    "variety_code": variety_code,
                    "count": len(filtered),
                    "call_count": call_count,
                    "put_count": put_count,
                    "pcr": round(pcr, 3),
                    "contracts": filtered[['合约名称', '期权类型', '行权价', '最后交易日']].head(10).to_dict("records"),
                    "timestamp": datetime.now().isoformat()
                }
                
                set_cache(cache_key, result)
                return result
                
    except Exception as e:
        print(f"[WARN] 获取{variety_code}期权数据失败: {e}")
    
    return {
        "variety_code": variety_code,
        "count": 0,
        "call_count": 0,
        "put_count": 0,
        "pcr": 0,
        "contracts": [],
        "timestamp": datetime.now().isoformat()
    }

def calc_signal(variety_data: Dict) -> Dict:
    """计算交易信号"""
    if not variety_data.get("last_price"):
        return {
            "signal": "数据不足",
            "score": 50,
            "reason": "等待数据加载...",
            "strength": "弱"
        }
    
    price = variety_data["last_price"]
    change_pct = variety_data.get("change_pct", 0)
    
    # 简单信号逻辑
    if change_pct > 1.0:
        signal = "做多"
        score = 70
        reason = "涨幅较大，趋势向上"
        strength = "强"
    elif change_pct < -1.0:
        signal = "做空"
        score = 70
        reason = "跌幅较大，趋势向下"
        strength = "强"
    elif change_pct > 0.3:
        signal = "偏多"
        score = 60
        reason = "小幅上涨"
        strength = "中"
    elif change_pct < -0.3:
        signal = "偏空"
        score = 60
        reason = "小幅下跌"
        strength = "中"
    else:
        signal = "观望"
        score = 50
        reason = "震荡整理"
        strength = "弱"
    
    return {
        "signal": signal,
        "score": score,
        "reason": reason,
        "strength": strength,
        "timestamp": datetime.now().isoformat()
    }

# ==================== FastAPI 应用 ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化
    print("[INFO] 初始化多品种期货分析平台...")
    init_db()
    print("[INFO] 数据库初始化完成")
    yield
    # 关闭时清理
    print("[INFO] 关闭多品种期货分析平台...")

app = FastAPI(
    title="多品种期货分析平台",
    description="支持一键更换不同期货品种，自动选择主力合约和最近月期权合约",
    version="1.0.0",
    lifespan=lifespan
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 模板引擎
templates = Jinja2Templates(directory=os.path.join(WORKSPACE, "templates"))

# ==================== 路由定义 ====================
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """多品种分析平台首页"""
    current_variety = variety_config.current_variety
    current_variety_info = variety_config.get_current_variety()
    enabled_varieties = variety_config.get_enabled_varieties()
    
    # 获取当前品种数据
    variety_data = get_variety_realtime(current_variety)
    
    return templates.TemplateResponse(
        "multi_variety.html",
        {
            "request": request,
            "title": "多品种期货分析平台",
            "current_variety": current_variety,
            "current_variety_info": current_variety_info,
            "varieties": enabled_varieties,
            "variety_data": variety_data,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    )

@app.get("/api/variety/current", response_class=JSONResponse)
async def get_current_variety():
    """获取当前品种信息"""
    current_variety = variety_config.current_variety
    current_variety_info = variety_config.get_current_variety()
    
    return {
        "success": True,
        "current_variety": current_variety,
        "variety_info": current_variety_info,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/variety/list", response_class=JSONResponse)
async def get_variety_list():
    """获取品种列表"""
    enabled_varieties = variety_config.get_enabled_varieties()
    
    return {
        "success": True,
        "varieties": enabled_varieties,
        "count": len(enabled_varieties),
        "timestamp": datetime.now().isoformat()
    }

@app.post("/api/variety/switch/{variety_code}", response_class=JSONResponse)
async def switch_variety(variety_code: str):
    """切换当前品种"""
    try:
        success = variety_config.set_current_variety(variety_code)
        if success:
            return {
                "success": True,
                "message": f"已切换到 {variety_code}",
                "current_variety": variety_code,
                "timestamp": datetime.now().isoformat()
            }
        else:
            return {
                "success": False,
                "error": f"品种 {variety_code} 不存在或未启用",
                "timestamp": datetime.now().isoformat()
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

@app.get("/api/variety/{variety_code}/data", response_class=JSONResponse)
async def get_variety_data(variety_code: str):
    """获取指定品种的实时数据"""
    if variety_code not in variety_config.config["varieties"]:
        raise HTTPException(status_code=404, detail=f"品种 {variety_code} 不存在")
    
    variety_data = get_variety_realtime(variety_code)
    
    return {
        "success": True,
        "variety_code": variety_code,
        "data": variety_data,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/variety/{variety_code}/options", response_class=JSONResponse)
async def get_variety_options(variety_code: str):
    """获取指定品种的期权数据"""
    if variety_code not in variety_config.config["varieties"]:
        raise HTTPException(status_code=404, detail=f"品种 {variety_code} 不存在")
    
    options_data = get_options_data(variety_code)
    
    return {
        "success": True,
        "variety_code": variety_code,
        "options": options_data,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/variety/{variety_code}/signal", response_class=JSONResponse)
async def get_variety_signal(variety_code: str):
    """获取指定品种的交易信号"""
    if variety_code not in variety_config.config["varieties"]:
        raise HTTPException(status_code=404, detail=f"品种 {variety_code} 不存在")
    
    variety_data = get_variety_realtime(variety_code)
    signal = calc_signal(variety_data)
    
    # 保存到数据库
    conn = get_db()
    conn.execute(
        """
        INSERT INTO signal_log (created_at, variety_code, last_price, signal, score, reason, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            variety_code,
            variety_data.get("last_price"),
            signal["signal"],
            signal["score"],
            signal["reason"],
            datetime.now().isoformat()
        )
    )
    conn.commit()
    conn.close()
    
    return {
        "success": True,
        "variety_code": variety_code,
        "signal": signal,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/variety/{variety_code}/history", response_class=JSONResponse)
async def get_variety_history(variety_code: str, limit: int = 100):
    """获取指定品种的历史数据"""
    if variety_code not in variety_config.config["varieties"]:
        raise HTTPException(status_code=404, detail=f"品种 {variety_code} 不存在")
    
    conn = get_db()
    cursor = conn.execute(
        """
        SELECT * FROM variety_data 
        WHERE variety_code = ? 
        ORDER BY created_at DESC 
        LIMIT ?
        """,
        (variety_code, limit)
    )
    rows = cursor.fetchall()
    conn.close()
    
    history = [dict(row) for row in rows]
    
    return {
        "success": True,
        "variety_code": variety_code,
        "history": history,
        "count": len(history),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/config", response_class=JSONResponse)
async def get_config():
    """获取平台配置"""
    return {
        "success": True,
        "config": {
            "current_variety": variety_config.current_variety,
            "varieties": variety_config.get_enabled_varieties(),
            "total_varieties": len(variety_config.config["varieties"]),
            "enabled_varieties": len(variety_config.get_enabled_varieties())
        },
        "timestamp": datetime.now().isoformat()
    }

@app.get("/health", response_class=JSONResponse)
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "service": "multi-variety-futures-analysis",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat()
    }

# ==================== 主程序入口 ====================
if __name__ == "__main__":
    import uvicorn
    
    print("=" * 60)
    print("多品种期货分析平台")
    print("=" * 60)
    print(f"当前品种: {variety_config.current_variety}")
    print(f"可用品种: {', '.join(variety_config.get_enabled_varieties().keys())}")
    print(f"服务地址: http://0.0.0.0:8001")
    print("=" * 60)
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8001,
        log_level="info"
    )
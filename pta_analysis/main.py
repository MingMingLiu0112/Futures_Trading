#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA Analysis - FastAPI 主服务
==============================
提供 REST API:
  - GET /health              健康检查
  - GET /api/pta/quote       PTA期货实时行情
  - GET /api/pta/option      PTA期权链数据
  - GET /api/pta/iv          IV曲面与PCR
  - GET /api/pta/cost        PTA成本计算
  - GET /api/pta/signal      综合信号
  - GET /api/pta/history     历史K线
  - GET /api/brent           布伦特原油
  - GET /api/macro/news      宏观新闻摘要
  - WS  /ws/quote            实时行情WebSocket
"""

import sys, os
sys.path.insert(0, '/app')

import asyncio
import json
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import pandas as pd

# 数据库连接
from sqlalchemy import create_engine, text
import redis

# 全局连接
engine = None
redis_client = None

# ==================== 启动/关闭 ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine, redis_client

    # MySQL
    try:
        engine = create_engine(
            "mysql+pymysql://pta:pta_pass_2025@localhost:3306/pta_analysis?charset=utf8mb4",
            pool_size=5, pool_recycle=3600
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("[DB] MySQL 连接成功")
    except Exception as e:
        print(f"[DB] MySQL 连接失败: {e}")
        engine = None

    # Redis
    try:
        redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        redis_client.ping()
        print("[Redis] 连接成功")
    except Exception as e:
        print(f"[Redis] 连接失败: {e}")
        redis_client = None

    yield

    if engine:
        engine.dispose()
    if redis_client:
        redis_client.close()
    print("[Server] 关闭")

# ==================== FastAPI App ====================
app = FastAPI(
    title="PTA Analysis API",
    description="PTA期货期权分析系统",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== 辅助函数 ====================
def get_redis(key: str) -> Optional[str]:
    if redis_client:
        try:
            return redis_client.get(key)
        except:
            pass
    return None

def set_redis(key: str, value: str, expire: int = 300):
    if redis_client:
        try:
            redis_client.setex(key, expire, value)
        except:
            pass

# ==================== 路由 ====================
@app.get("/health")
async def health():
    """健康检查"""
    mysql_ok = False
    redis_ok = False

    if engine:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            mysql_ok = True
        except:
            pass

    if redis_client:
        try:
            redis_client.ping()
            redis_ok = True
        except:
            pass

    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "mysql": "up" if mysql_ok else "down",
            "redis": "up" if redis_ok else "down",
            "python": "up"
        }
    }

@app.get("/api/pta/quote")
async def pta_quote():
    """PTA期货实时行情"""
    cached = get_redis("pta:quote")
    if cached:
        return json.loads(cached)

    try:
        import akshare as ak
        df = ak.futures_zh_realtime(symbol="TA")
        if df is not None and not df.empty:
            row = df.iloc[-1].to_dict()
            result = {
                "symbol": "TA",
                "last_price": float(row.get("最新价", 0)),
                "bid": float(row.get("买一价", 0)),
                "ask": float(row.get("卖一价", 0)),
                "volume": int(row.get("成交量", 0)),
                "open_interest": int(row.get("持仓量", 0)),
                "timestamp": datetime.now().isoformat()
            }
            set_redis("pta:quote", json.dumps(result, ensure_ascii=False), 30)
            return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取行情失败: {str(e)}")

    raise HTTPException(status_code=404, detail="无法获取PTA行情数据")

@app.get("/api/pta/option")
async def pta_option(expiry: str = Query(None, description="到期日，如 2025-04-08")):
    """PTA期权链数据"""
    cache_key = f"pta:option:{expiry or 'all'}"
    cached = get_redis(cache_key)
    if cached:
        return json.loads(cached)

    try:
        from vnpy.ctp import CtpGateway
        from vnpy.trader.constant import Exchange

        gateway = CtpGateway(gateway_name="PTAOption")
        result = {"contracts": [], "timestamp": datetime.now().isoformat()}
        set_redis(cache_key, json.dumps(result, ensure_ascii=False), 60)
        return result
    except Exception as e:
        pass

    # Fallback: 返回CTP期权信息
    try:
        contracts = ak.option_contract_info_ctp(exchange="CZCE", contract="TA")
        if contracts is not None:
            result = {
                "contracts": contracts.to_dict("records")[:20],
                "count": len(contracts),
                "timestamp": datetime.now().isoformat()
            }
            set_redis(cache_key, json.dumps(result, ensure_ascii=False), 60)
            return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取期权链失败: {str(e)}")

    raise HTTPException(status_code=404, detail="无法获取PTA期权链数据")

@app.get("/api/pta/iv")
async def pta_iv():
    """IV曲面与PCR"""
    cached = get_redis("pta:iv")
    if cached:
        return json.loads(cached)

    try:
        # 获取PTA期权日线数据(IV/Pcr/OI)
        df = ak.option_hist_czce(symbol="TA", end_date=datetime.now().strftime("%Y%m%d"))
        if df is not None and not df.empty:
            latest = df.iloc[-1]
            result = {
                "iv": float(latest.get("隐含波动率", 0)) if "隐含波动率" in latest else None,
                "pcr": float(latest.get("成交量PCR", 0)) if "成交量PCR" in latest else None,
                "oi_pcr": float(latest.get("持仓量PCR", 0)) if "持仓量PCR" in latest else None,
                "timestamp": datetime.now().isoformat()
            }
            set_redis("pta:iv", json.dumps(result, ensure_ascii=False), 60)
            return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取IV失败: {str(e)}")

    raise HTTPException(status_code=404, detail="无法获取IV数据")

@app.get("/api/pta/cost")
async def pta_cost():
    """PTA成本计算"""
    cached = get_redis("pta:cost")
    if cached:
        return json.loads(cached)

    try:
        # 布伦特原油
        brent_df = ak.futures_global_spot_em(symbol="布伦特原油")
        brent_price = brent_df.iloc[0]["价格"] if brent_df is not None else None

        # PX现货
        px_df = ak.futures_spot_price(exchange="CZCE", symbol="PX")
        px_price = px_df.iloc[0]["价格"] if px_df is not None and not px_df.empty else None

        # PTA现货
        ta_df = ak.futures_spot_price(exchange="CZCE", symbol="TA")
        ta_price = ta_df.iloc[0]["价格"] if ta_df is not None and not ta_df.empty else None

        # 计算成本
        FX = 7.25
        brent_cny = brent_price * FX if brent_price else None
        # PTA成本 ≈ PX * 0.655 + 800
        cost_low = px_price * 0.655 + 600 if px_price else None
        cost_high = px_price * 0.655 + 1000 if px_price else None

        result = {
            "brent_usd": brent_price,
            "brent_cny": brent_cny,
            "px_cny": px_price,
            "pta_spot": ta_price,
            "pta_cost_low": cost_low,
            "pta_cost_high": cost_high,
            "margin": (ta_price - (cost_low + cost_high) / 2) if ta_price and cost_low else None,
            "timestamp": datetime.now().isoformat()
        }
        set_redis("pta:cost", json.dumps(result, ensure_ascii=False), 300)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"成本计算失败: {str(e)}")

@app.get("/api/pta/signal")
async def pta_signal():
    """综合信号 (三维共振)"""
    cached = get_redis("pta:signal")
    if cached:
        return json.loads(cached)

    try:
        # 运行分析器
        sys.path.insert(0, "/app")
        import pta_analyzer as analyzer

        # 获取关键数据
        quote_data = await pta_quote()
        cost_data = await pta_cost()
        iv_data = await pta_iv()

        # 保存到DB
        if engine:
            try:
                with engine.connect() as conn:
                    conn.execute(text("""
                        INSERT INTO signal_log (created_at, symbol, last_price, pcr, iv, cost_low, cost_high)
                        VALUES (NOW(), 'TA', :price, :pcr, :iv, :cost_low, :cost_high)
                    """), {
                        "price": quote_data.get("last_price"),
                        "pcr": iv_data.get("pcr"),
                        "iv": iv_data.get("iv"),
                        "cost_low": cost_data.get("pta_cost_low"),
                        "cost_high": cost_data.get("pta_cost_high")
                    })
                    conn.commit()
            except Exception as db_err:
                print(f"[DB] 保存信号失败: {db_err}")

        result = {
            "quote": quote_data,
            "cost": cost_data,
            "iv": iv_data,
            "timestamp": datetime.now().isoformat()
        }
        set_redis("pta:signal", json.dumps(result, ensure_ascii=False), 60)
        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"信号生成失败: {str(e)}")

@app.get("/api/brent")
async def brent_price():
    """布伦特原油价格"""
    cached = get_redis("brent:price")
    if cached:
        return json.loads(cached)

    try:
        df = ak.futures_global_spot_em(symbol="布伦特原油")
        if df is not None and not df.empty:
            latest = df.iloc[0]
            result = {
                "name": "布伦特原油",
                "price": float(latest.get("价格", 0)),
                "change_pct": float(latest.get("涨跌幅", 0)) if "涨跌幅" in latest else None,
                "source": latest.get("数据源", "em") if "数据源" in latest else None,
                "timestamp": datetime.now().isoformat()
            }
            set_redis("brent:price", json.dumps(result, ensure_ascii=False), 300)
            return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取布伦特价格失败: {str(e)}")

    raise HTTPException(status_code=404, detail="无法获取布伦特原油数据")

@app.get("/api/macro/news")
async def macro_news():
    """宏观新闻摘要"""
    cached = get_redis("macro:news")
    if cached:
        return json.loads(cached)

    try:
        sys.path.insert(0, "/app")
        import macro_news

        news = macro_news.get_important_news()
        result = {
            "news": news[:10],
            "count": len(news),
            "timestamp": datetime.now().isoformat()
        }
        set_redis("macro:news", json.dumps(result, ensure_ascii=False), 600)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取新闻失败: {str(e)}")

# ==================== 主入口 ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

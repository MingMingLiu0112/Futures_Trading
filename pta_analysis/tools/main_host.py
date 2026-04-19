#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA Analysis - FastAPI 精简版 (SQLite + 内存缓存)
修复版 - 适配 akshare 最新 API
"""

import sys, os, json, sqlite3, threading, warnings
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

WORKSPACE = "/home/admin/.openclaw/workspace/codeman/pta_analysis"
sys.path.insert(0, WORKSPACE)

warnings.filterwarnings('ignore')

# ==================== 数据库 (SQLite) ====================
DB_PATH = "/tmp/pta_analysis.db"

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    # 重建signal_log表（新增tech_score列）
    conn.execute("DROP TABLE IF EXISTS signal_log_new")
    conn.execute("""
        CREATE TABLE signal_log_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT, symbol TEXT,
            last_price REAL, pcr REAL, iv REAL,
            cost_low REAL, cost_high REAL,
            brent_usd REAL, px_cny REAL, pta_spot REAL,
            macro_score INT, tech_score INT, signal TEXT, tech_detail TEXT
        )
    """)
    # 如果旧表存在则迁移数据
    try:
        conn.execute("""
            INSERT OR IGNORE INTO signal_log_new
            SELECT id, created_at, symbol, last_price, pcr, iv,
                   cost_low, cost_high, brent_usd, px_cny, pta_spot,
                   macro_score, NULL, signal, NULL
            FROM signal_log
        """)
        conn.execute("DROP TABLE IF EXISTS signal_log")
    except Exception:
        pass
    conn.execute("ALTER TABLE signal_log_new RENAME TO signal_log")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS brent_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT, price REAL, change_pct REAL
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

def set_cache(key: str, value: dict, ttl: int = 60):
    _cache[key] = value
    _cache_ttl[key] = datetime.now().timestamp() + ttl

# ==================== 数据获取 (akshare 适配) ====================
import akshare as ak

def get_pta_realtime():
    """PTA期货实时行情 - futures_zh_realtime(symbol='PTA')"""
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
                "timestamp": datetime.now().isoformat()
            }
    except Exception as e:
        print(f"[WARN] PTA行情失败: {e}")
    return None

def get_brent():
    """布伦特原油 - futures_global_spot_em() 无参数"""
    try:
        df = ak.futures_global_spot_em()
        if df is not None and not df.empty:
            # 找主力合约(成交量最大的近月合约)
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
                    "timestamp": datetime.now().isoformat()
                }
    except Exception as e:
        print(f"[WARN] 布伦特失败: {e}")
    return None

def get_px_price():
    """PX现货价 - futures_spot_price(date, vars_list)"""
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
                    "timestamp": datetime.now().isoformat()
                }
    except Exception as e:
        print(f"[WARN] PX现货失败: {e}")
    return None

def get_pta_spot():
    """PTA现货价 - futures_spot_price"""
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
                    "timestamp": datetime.now().isoformat()
                }
    except Exception as e:
        print(f"[WARN] PTA现货失败: {e}")
    return None

def get_ta_options_contracts():
    """PTA期权合约列表 - option_contract_info_ctp()"""
    try:
        df = ak.option_contract_info_ctp()
        ta = df[(df['交易所ID'] == 'CZCE') & (df['合约名称'].str.startswith('TA', na=False))]
        if not ta.empty:
            return {
                "count": len(ta),
                "expiry": ta['最后交易日'].iloc[0] if '最后交易日' in ta.columns else None,
                "contracts": ta[['合约名称', '期权类型', '行权价', '最后交易日']].head(20).to_dict("records"),
                "timestamp": datetime.now().isoformat()
            }
    except Exception as e:
        print(f"[WARN] PTA期权合约失败: {e}")
    return None

def calc_cost(brent_price, px_price):
    """PTA成本计算: PTA成本 ≈ PX * 0.655 + 800"""
    FX = 7.25
    if px_price:
        cost_low = px_price * 0.655 + 600
        cost_high = px_price * 0.655 + 1000
        return cost_low, cost_high
    return None, None

def calc_signal(pta_price, cost_low, cost_high, pcr=None, iv=None):
    """简单信号逻辑"""
    if not pta_price or not cost_low:
        return "数据不足", 50

    mid_cost = (cost_low + cost_high) / 2
    margin = pta_price - mid_cost

    if margin > 200:
        signal = "做多"
        score = min(90, 60 + int(margin / 20))
    elif margin < -200:
        signal = "做空"
        score = max(10, 60 + int(margin / 20))
    else:
        signal = "观望"
        score = 50

    # PCR 调整
    if pcr:
        if pcr > 1.2:
            score = min(90, score + 5)  # 高PCR偏多头
        elif pcr < 0.7:
            score = max(10, score - 5)  # 低PCR偏空头

    return signal, score

# ==================== FastAPI ====================
from datetime import timedelta

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    print(f"[Server] SQLite DB: {DB_PATH}")
    yield
    print("[Server] 关闭")

app = FastAPI(title="PTA Analysis", version="1.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/health")
async def health():
    conn = get_db()
    row = conn.execute("SELECT COUNT(*) as cnt FROM signal_log").fetchone()
    conn.close()
    return {"status": "ok", "time": datetime.now().strftime("%H:%M:%S"), "total_signals": row["cnt"] if row else 0}

@app.get("/api/pta/quote")
async def pta_quote():
    cached = get_cache("pta:quote")
    if cached:
        return cached
    data = get_pta_realtime()
    if data:
        set_cache("pta:quote", data, 30)
        return data
    raise HTTPException(status_code=404, detail="无法获取PTA行情")

@app.get("/api/pta/options")
async def pta_options():
    """PTA期权合约列表"""
    cached = get_cache("pta:options")
    if cached:
        return cached
    data = get_ta_options_contracts()
    if data:
        set_cache("pta:options", data, 3600)
        return data
    raise HTTPException(status_code=404, detail="无法获取PTA期权合约")

@app.get("/api/pta/cost")
async def pta_cost():
    """PTA成本计算"""
    cached = get_cache("pta:cost")
    if cached:
        return cached

    brent = get_brent()
    px = get_px_price()
    ta = get_pta_spot()

    brent_price = brent["price"] if brent else None
    px_price = px["px_price"] if px else None
    ta_price = ta["pta_spot"] if ta else None

    cost_low, cost_high = calc_cost(brent_price, px_price)

    result = {
        "brent_usd": brent_price,
        "brent_cny": brent_price * 7.25 if brent_price else None,
        "px_cny": px_price,
        "pta_spot": ta_price,
        "pta_cost_low": cost_low,
        "pta_cost_high": cost_high,
        "margin": (ta_price - (cost_low + cost_high) / 2) if ta_price and cost_low else None,
        "timestamp": datetime.now().isoformat()
    }
    set_cache("pta:cost", result, 300)
    return result

@app.get("/api/brent")
async def brent():
    cached = get_cache("brent")
    if cached:
        return cached
    data = get_brent()
    if data:
        set_cache("brent", data, 300)
        try:
            conn = get_db()
            conn.execute("INSERT INTO brent_log (created_at, price, change_pct) VALUES (?, ?, ?)",
                (datetime.now().isoformat(), data["price"], data.get("change_pct")))
            conn.commit()
            conn.close()
        except: pass
        return data
    raise HTTPException(status_code=404, detail="无法获取布伦特原油")

@app.get("/api/pta/signal")
async def signal():
    """综合信号 - 三维度分析"""
    cached = get_cache("pta:signal")
    if cached:
        return cached

    try:
        sys.path.insert(0, WORKSPACE)
        import signal_analyzer as sa
        result = sa.full_analysis()
        signal_info = result["signal"]

        # 写入DB
        try:
            conn = get_db()
            conn.execute("""
                INSERT INTO signal_log (created_at, symbol, last_price, pcr, iv,
                    cost_low, cost_high, brent_usd, pta_spot,
                    macro_score, tech_score, signal, tech_detail)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (datetime.now().isoformat(), "TA",
                  result["quote"]["price"] if result["quote"] else None,
                  None, None,
                  result["cost"]["cost_low"], result["cost"]["cost_high"],
                  result["brent"]["price"] if result["brent"] else None,
                  result["cost"]["pta_spot"],
                  signal_info["macro_score"],
                  signal_info["tech_score"],
                  signal_info["signal"],
                  result["tech"]["detail"]))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[WARN] DB写入: {e}")

        set_cache("pta:signal", result, 60)
        return result
    except Exception as e:
        print(f"[ERROR] signal: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/history")
async def history(limit: int = 50):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM signal_log ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return {"data": [dict(r) for r in rows], "count": len(rows)}

@app.get("/api/macro/news")
async def macro_news():
    cached = get_cache("macro:news")
    if cached:
        return cached
    try:
        import macro_news
        news = macro_news.get_important_news()
        result = {"news": news[:10], "count": len(news)}
    except Exception as e:
        result = {"news": [], "count": 0, "error": str(e)}
    set_cache("macro:news", result, 600)
    return result

if __name__ == "__main__":
    import uvicorn
    print("[Server] 启动 PTA Analysis API :8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

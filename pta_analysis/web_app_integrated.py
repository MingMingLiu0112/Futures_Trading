


#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA期货分析平台 - 快速集成版本
包含所有5个期权功能模块 + K线图功能
"""

import os, sys, json, time, sqlite3, threading, warnings, math, io, zipfile, re
from datetime import datetime as dt_datetime, timedelta
import datetime as dt
from typing import Optional, Dict, List

from flask import Flask, render_template, jsonify, request, send_file, redirect, url_for, render_template_string, make_response
import akshare as ak
import pandas as pd
import numpy as np

# 加载 .env 环境变量（确保TqSdk认证凭据可用）
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _v = _line.split('=', 1)
                os.environ.setdefault(_k, _v)

# 天勤量化 TqSdk
from tqsdk import TqApi, TqAuth, TqKq

# 配置 TqSdk 日志级别，抑制每10秒的连接通知噪音
import logging
logging.getLogger("tqsdk").setLevel(logging.WARNING)
logging.getLogger("tqsdk.ta").setLevel(logging.WARNING)

# MACD多周期计算模块
from indicators import macd_multiperiod as mmacd

# 波动率锥模块
from indicators.volatility_cone import (
    load_pta_data, load_iv_data, calculate_all_hv_windows,
    generate_volatility_cone_data, calculate_iv_percentile,
    generate_trading_signals
)

# PTA产业基本面分析模块
from analysis import industry_analysis as pta_industry

# 风险控制模块
from risk_control import register_risk_routes

# 策略导入模块
from backtest.strategy_import_api import register_strategy_import_routes

# ========== 交易系统模块（回测+风控+执行+策略） ==========
from backtest.backtest_engine import BacktestEngine
from strategies import MACDStrategy, MovingAverageStrategy, KDJStrategy, RSIStrategy, BollingerStrategy, ATRStrategy, BreakoutStrategy
from execution.order_manager import OrderManager, Order, OrderStatus, OrderType, OrderSide
from execution.trade_executor import TradeExecutor
from execution.position_tracker import PositionTracker, PositionDirection
from risk_control import MoneyManager, PositionManager

# IV Smile 隐波微笑曲线模块（独立进程已合并到主服务）
import iv_smile_service

# TqSdk 认证配置
TQS_USER = os.environ.get('TQS_AUTH_USER', 'mingmingliu')
TQS_PASS = os.environ.get('TQS_AUTH_PASS', 'Liuzhaoning2025')

# Flask 应用
WORKSPACE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(WORKSPACE, "data", "pta_signals.db")
app = Flask(__name__, static_folder=None)
app.config["DATABASE"] = DB_PATH
app.config["WORKSPACE"] = WORKSPACE

# ==================== 波动率API缓存 ====================
_volatility_cache = {}
_volatility_cache_time = {}

# ==================== 研报与策略缓存 ====================
STRATEGY_REPORT_CACHE_MINUTES = 15
STRATEGY_REPORT_DIR = os.path.join(WORKSPACE, 'data', 'fundamental')
STRATEGY_REPORT_PATH = os.path.join(STRATEGY_REPORT_DIR, 'daily_report.json')
STRATEGY_CLOSE_REPORT_DIR = os.path.join(WORKSPACE, 'data', 'reports')
_strategy_report_lock = threading.Lock()
_strategy_report_refreshing = False

def _get_vol_cache(key, ttl_minutes=5):
    if key in _volatility_cache:
        if key in _volatility_cache_time:
            elapsed = (dt_datetime.now() - _volatility_cache_time[key]).total_seconds()
            if elapsed < ttl_minutes * 60:
                return _volatility_cache[key]
    return None

def _set_vol_cache(key, data):
    _volatility_cache[key] = data
    _volatility_cache_time[key] = dt_datetime.now()

def _iv_interpretation(p):
    if p <= 20:   return {'level': '极低', 'color': 'success', 'description': '隐含波动率处于历史极低水平', 'recommendation': '适合买入期权（做多波动率）', 'confidence': '高'}
    elif p <= 40: return {'level': '偏低', 'color': 'info',    'description': '隐含波动率处于历史较低水平', 'recommendation': '考虑买入期权或做多波动率', 'confidence': '中'}
    elif p <= 60: return {'level': '正常', 'color': 'warning',  'description': '隐含波动率处于历史正常范围', 'recommendation': '中性策略或方向性交易', 'confidence': '低'}
    elif p <= 80: return {'level': '偏高', 'color': 'warning',  'description': '隐含波动率处于历史较高水平', 'recommendation': '考虑卖出期权或做空波动率', 'confidence': '中'}
    else:         return {'level': '极高', 'color': 'danger',    'description': '隐含波动率处于历史极高水平', 'recommendation': '适合卖出期权（做空波动率）', 'confidence': '高'}

# 注册风险控制路由
register_risk_routes(app)

# 注册策略导入路由
register_strategy_import_routes(app)

# ==================== 交易系统全局实例 ====================
_trading_system = None

def get_trading_system():
    """获取或创建交易系统实例（延迟初始化）"""
    global _trading_system
    if _trading_system is None:
        _trading_system = TradingSystem()
    return _trading_system


class TradingSystem:
    """交易系统主类：整合数据、风控、策略、执行"""

    def __init__(self):
        # 风控
        self.money_manager = MoneyManager(initial_balance=1000000.0, max_drawdown=0.1)
        self.position_manager = PositionManager(account_balance=1000000.0)
        # 执行
        self.order_manager = OrderManager()
        self.trade_executor = TradeExecutor(self.order_manager)
        self.position_tracker = PositionTracker()
        # 回测引擎
        self.backtest_engine = BacktestEngine(
            initial_balance=1000000.0,
            risk_per_trade=0.01,
            commission_rate=0.0001
        )
        # 策略列表
        self.strategies = {
            'macd': MACDStrategy,
            'ma': MovingAverageStrategy,
            'kdj': KDJStrategy,
            'rsi': RSIStrategy,
            'bollinger': BollingerStrategy,
            'atr': ATRStrategy,
            'breakout': BreakoutStrategy,
        }

    def run_backtest(self, strategy_name: str, kline_data: list, params: dict = None) -> dict:
        """运行回测"""
        strategy_cls = self.strategies.get(strategy_name.lower())
        if not strategy_cls:
            raise ValueError(f"未知策略: {strategy_name}")
        strategy = strategy_cls(params=params) if params else strategy_cls()
        return self.backtest_engine.run(strategy, kline_data)

    def submit_order(self, symbol: str, side: str, quantity: int = 1,
                     order_type: str = 'market', price: float = None,
                     stop_price: float = None) -> Order:
        """提交订单"""
        side_enum = OrderSide.BUY if side.lower() == 'buy' else OrderSide.SELL
        type_enum = {
            'market': OrderType.MARKET,
            'limit': OrderType.LIMIT,
            'stop': OrderType.STOP,
        }.get(order_type.lower(), OrderType.MARKET)

        order = self.order_manager.create_order(
            symbol=symbol,
            side=side_enum,
            quantity=quantity,
            order_type=type_enum,
            price=price,
            stop_price=stop_price
        )
        self.trade_executor.submit_order(order)
        return order

    def get_positions(self) -> dict:
        """获取当前持仓"""
        return self.position_tracker.get_all_positions()

    def get_orders(self) -> dict:
        """获取订单列表"""
        return {
            'active': [o.to_dict() for o in self.order_manager.get_active_orders()],
            'history': [o.to_dict() for o in self.order_manager.get_order_history()],
        }

    def get_account_status(self) -> dict:
        """获取账户状态"""
        stats = self.money_manager.get_trade_statistics()
        pos_summary = self.position_tracker.get_position_summary()
        return {
            'balance': self.money_manager.current_balance,
            'highest_balance': self.money_manager.highest_balance,
            'max_drawdown': self.money_manager.max_drawdown,
            'current_drawdown': self.money_manager.current_drawdown,
            'total_trades': stats.get('total_trades', 0),
            'win_rate': stats.get('win_rate', 0),
            'positions': pos_summary,
        }


@app.route('/api/status')
def api_status():
    """平台状态API"""
    return jsonify({
        'status': 'running',
        'version': '2.0.0',
        'modules': {
            'option_chain': {'status': 'completed', 'version': '1.0'},
            'iv_curve': {'status': 'completed', 'version': '1.0'},
            'volatility_cone': {'status': 'completed', 'version': '1.0'},
            'multi_variety': {'status': 'completed', 'version': '1.0'},
            'excel_export': {'status': 'completed', 'version': '1.0'},
            'kline_chart': {'status': 'completed', 'version': '1.0'},
            'risk_control': {'status': 'completed', 'version': '1.0'}
        },
        'timestamp': dt_datetime.now().isoformat()
    })


@app.route('/static/<path:filename>')
def serve_static(filename):
    from flask import send_from_directory
    return send_from_directory(os.path.join(WORKSPACE, 'static'), filename)

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
    # 绘图持久化表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chart_drawings (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            drawing_id INT    NOT NULL UNIQUE,
            drawing_type TEXT NOT NULL,
            color      TEXT,
            line_width INT,
            price      REAL,
            time       REAL,
            end_time   REAL,
            points     TEXT,
            top        REAL,
            bottom     REAL,
            cycles     TEXT,
            price_min  REAL,
            price_max  REAL,
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()

# ==================== 绘图持久化 API ====================

@app.route('/api/chart/drawings', methods=['GET'])
def get_chart_drawings():
    """获取所有已保存的绘图"""
    conn = get_db()
    rows = conn.execute("SELECT drawing_id, drawing_type, color, line_width, "
                        "price, time, end_time, points, top, bottom, cycles, "
                        "price_min, price_max FROM chart_drawings ORDER BY drawing_id").fetchall()
    drawings = []
    for r in rows:
        d = {
            'id': r['drawing_id'],
            'type': r['drawing_type'],
            'color': r['color'],
            'lineWidth': r['line_width'],
            'price': r['price'],
            'time': r['time'],
            'endTime': r['end_time'],
            'points': json.loads(r['points']) if r['points'] else None,
            'top': r['top'],
            'bottom': r['bottom'],
            'cycles': json.loads(r['cycles']) if r['cycles'] else ['1min','5min','15min','30min','60min','240min','1day','1week','1month'],
            'priceMin': r['price_min'],
            'priceMax': r['price_max'],
        }
        drawings.append(d)
    return jsonify({'success': True, 'drawings': drawings})

@app.route('/api/chart/drawings', methods=['POST'])
def save_chart_drawings():
    """批量保存绘图（整体替换）"""
    try:
        req_data = request.get_json() or {}
        drawings = req_data.get('drawings', [])
        if not isinstance(drawings, list):
            return jsonify({'success': False, 'error': 'drawings must be an array'}), 400

        conn = get_db()
        # 事务：清空旧数据，插入新数据
        cursor = conn.cursor()
        cursor.execute("DELETE FROM chart_drawings")
        for d in drawings:
            cursor.execute(
                "INSERT INTO chart_drawings "
                "(drawing_id, drawing_type, color, line_width, price, time, end_time, "
                "points, top, bottom, cycles, price_min, price_max) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    d.get('id'),
                    d.get('type'),
                    d.get('color'),
                    d.get('lineWidth'),
                    d.get('price'),
                    d.get('time'),
                    d.get('endTime'),
                    json.dumps(d.get('points')) if d.get('points') else None,
                    d.get('top'),
                    d.get('bottom'),
                    json.dumps(d.get('cycles')) if d.get('cycles') else None,
                    d.get('priceMin'),
                    d.get('priceMax'),
                )
            )
        conn.commit()
        app.logger.info(f"[绘图] 已保存 {len(drawings)} 个图形到数据库")
        return jsonify({'success': True, 'count': len(drawings)})
    except Exception as e:
        app.logger.error(f"[绘图] 保存失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/chart/drawings/<int:drawing_id>', methods=['DELETE'])
def delete_chart_drawing(drawing_id):
    """删除指定绘图"""
    try:
        conn = get_db()
        conn.execute("DELETE FROM chart_drawings WHERE drawing_id = ?", (drawing_id,))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ==================== 主页面 ====================

@app.route('/')
def index():
    """主页面 - K线图+PTA分析（迁移自 /kline）"""
    try:
        with open(os.path.join(WORKSPACE, 'templates', 'kline_lightweight.html'), 'r', encoding='utf-8') as f:
            content = f.read()
        from flask import make_response
        resp = make_response(content)
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
        return resp
    except FileNotFoundError:
        return "页面正在开发中，请稍后访问", 404

@app.route('/trading')
def trading_page():
    """交易系统页面"""
    try:
        with open(os.path.join(WORKSPACE, 'templates', 'trading.html'), 'r', encoding='utf-8') as f:
            content = f.read()
        from flask import make_response
        resp = make_response(content)
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return resp
    except FileNotFoundError:
        return "页面正在开发中，请稍后访问", 404

@app.route('/drawing_test')
def drawing_test():
    """绘图工具已合并到主页面 /kline"""
    return redirect('/kline')

# ==================== API接口 ====================

@app.route('/api/options/chain')
def api_option_chain():
    """期权链数据API"""
    try:
        api = oca.get_option_api()
        # 自我修复：如果上次请求异常退出，pending可能卡住
        if api._pending:
            print("[api_option_chain] 检测到pending卡住，重置状态")
            api._pending = False
        result = api.get_full_chain()
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/pta/ta606_price')
@app.route('/api/pta/underlying_price')
def api_underlying_price():
    """近月期货实时价格 - 主页 T 型报价 24h 提前切换版本。

    主页期权链 T 型报价板块要比动态监控提前 24h 切最近月合约：
      - 动态监控 (iv_smile_service) 用的是 15:00 切日规则（盘中保留当日到期合约）
      - 主页 T 型报价 用的是 24h 提前切换（到期日 <= 今天就视为已到期）

    本接口为 24h 提前切换版本，合约选择和 T 型报价表头同源
    （get_homepage_near_expiry / get_full_chain 都是用同一函数）。

    价格获取：
      - 若 iv_smile_service 监控的合约 == 主页合约，复用 iv_smile 的 TqSdk 共享价（最快最准）
      - 否则（24h 提前切换生效时，如 TA607→TA608 当天），用 TqSdk/akshare 直连该合约
        （否则会用 TA607 的价当 TA608 的价显示 — 这是 v2.11.x 之前卡在 TA607 价格的根因）
    """
    try:
        price = 0
        price_source = 'none'
        expiry_code = oca.get_homepage_near_expiry()
        try:
            shared_contract = iv_smile_service._state.get('active_contract')
        except Exception:
            shared_contract = None
        # 1) 合约一致 → 仅复用 iv_smile 的实时 TqSdk 共享价；缓存价不能伪装成实时价
        if shared_contract == expiry_code:
            try:
                shared = iv_smile_service.get_shared_futures_price()
                if isinstance(shared, (tuple, list)):
                    shared_price = float(shared[0] or 0)
                    shared_source = shared[1] if len(shared) > 1 else 'unknown'
                else:
                    shared_price = float(shared or 0)
                    shared_source = 'legacy'
                if shared_price > 0 and shared_source in ('tqsdk', 'legacy'):
                    price = shared_price
                    price_source = f'shared_{shared_source}'
                elif shared_price > 0:
                    print(f"[api_underlying_price] 跳过缓存共享价 {shared_price} source={shared_source}，改走直连")
            except Exception:
                price = 0
        # 2) 合约不一致或共享价只是缓存 → 用 TqSdk/akshare 直连该合约
        if price <= 0:
            try:
                from analysis.option_chain_api import get_tq_futures_price_by_expiry
                tq_price, _ = get_tq_futures_price_by_expiry(expiry_code, timeout=2.0)
                if tq_price and tq_price > 0:
                    price = float(tq_price)
                    price_source = 'direct_tqsdk'
            except Exception:
                pass
        if price <= 0:
            try:
                price = oca._get_akshare_latest_price(expiry_code)
                if price and price > 0:
                    price_source = 'akshare_contract'
            except Exception:
                pass
        # 3) 兜底到 akshare 主力合约，避免接口阻塞/超时
        if price <= 0:
            try:
                df = ak.futures_zh_realtime(symbol="TA")
                if df is not None and not df.empty:
                    price = float(df.iloc[-1].get('trade', 0))
                    expiry_code = expiry_code or 'TA0'
                    price_source = 'akshare_main'
            except Exception:
                pass
        return jsonify({
            'success': True,
            'underlying_price': price,
            'symbol': expiry_code,
            'timestamp': dt_datetime.now().isoformat(),
            'source': price_source if price and expiry_code else 'fallback'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/options/refresh', methods=['POST'])
def api_option_refresh():
    """刷新期权数据"""
    try:
        api = oca.get_option_api()
        api._cache = None
        api._last_update = None
        api._pending = False  # 清除请求锁定状态
        result = api.get_full_chain()
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/options/save_session', methods=['POST'])
def api_save_session_snapshot():
    """保存当前Session快照
    
    保存当前交易日的Session数据:
    - morning: 11:30收盘
    - afternoon: 15:00收盘
    - night: 23:00收盘
    """
    try:
        data = request.get_json() or {}
        session_type = data.get('session_type', 'auto')  # 'morning', 'afternoon', 'night', 'auto'
        
        api = oca.get_option_api()
        store = api.store
        
        # 获取当前时间
        now = dt_datetime.now()
        trade_date = now.strftime('%Y%m%d')
        
        # 根据时间判断session类型
        if session_type == 'auto':
            hour = now.hour + now.minute / 60
            if hour >= 23 or hour < 9:
                session_type = 'night'
            elif hour >= 11.5 and hour < 15:
                session_type = 'afternoon'
            elif hour >= 9 and hour < 11.5:
                session_type = 'morning'
            else:
                session_type = 'afternoon'  # 默认
        
        # 获取今日期权数据
        df = oca.AkshareOptionData.get_option_data(trade_date)
        if df is None or len(df) == 0:
            return jsonify({'success': False, 'error': '获取期权数据失败'})
        
        # 保存快照
        store.save_session_snapshot(df, trade_date, session_type)
        
        return jsonify({
            'success': True,
            'session_type': session_type,
            'trade_date': trade_date,
            'saved_count': len(df)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/options/vol_cone')
def api_option_vol_cone():
    """波动率锥API"""
    try:
        api = oca.get_option_api()
        result = api.get_volatility_cone()
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/options/export_excel')
def api_export_option_excel():
    """导出平值±10档期权数据 Excel，直接下载"""
    try:
        result = oca.export_atm_option_excel()
        if result.get('success'):
            from flask import send_from_directory
            filepath = result['filepath']
            filename = result['filename']
            return send_from_directory(
                os.path.dirname(filepath),
                filename,
                as_attachment=True,
                download_name=filename
            )
        else:
            return jsonify({'success': False, 'error': result.get('error')})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/download/option_excel/<filename>')
def download_option_excel(filename):
    """下载期权Excel文件"""
    from flask import send_from_directory
    output_dir = os.path.expanduser("~/.hermes/option_exports")
    # 安全检查：只允许字母数字下划线和短横线
    import re
    if not re.match(r'^[\w-]+\.xlsx$', filename):
        return "Invalid filename", 400
    return send_from_directory(output_dir, filename, as_attachment=True)

@app.route('/api/fundamental')
def api_fundamental():
    """PTA基本面数据API"""
    try:
        data = pta_industry.get_pta_industry_data()
        return jsonify(data)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/fundamental_analysis')
def api_fundamental_analysis():
    """PTA基本面分析（期权/宏观/策略）"""
    try:
        json_path = os.path.join(WORKSPACE, 'data', 'fundamental', 'analysis.json')
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

def _load_strategy_report_cache():
    if not os.path.exists(STRATEGY_REPORT_PATH):
        return None, None
    with open(STRATEGY_REPORT_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data, dt_datetime.fromtimestamp(os.path.getmtime(STRATEGY_REPORT_PATH))


def _strategy_report_is_fresh(mtime, now=None):
    now = now or dt_datetime.now()
    if not mtime:
        return False
    if mtime.date() < now.date():
        return False
    return (now - mtime).total_seconds() < STRATEGY_REPORT_CACHE_MINUTES * 60


def _generate_strategy_report(force_close=False):
    from scripts.generate_daily_report import generate_report, save_report, generate_close_report, save_intraday_snapshot
    report = generate_close_report() if force_close else generate_report(report_type='intraday')
    # 缓存写盘前就做一次后端口径覆盖；否则“接口返回值已覆盖、导出/下次读缓存又回到旧值”。
    report = _override_report_with_kline_price(report)
    save_report(report)
    if not force_close:
        save_intraday_snapshot(report)
    return report


def _daily_close_report_path(date_text=None):
    date_text = date_text or dt_datetime.now().strftime('%Y%m%d')
    return os.path.join(STRATEGY_CLOSE_REPORT_DIR, f'daily_close_report_{date_text}.json')


def _maybe_write_close_report(report):
    now = dt_datetime.now()
    if now.hour < 15:
        return None
    os.makedirs(STRATEGY_CLOSE_REPORT_DIR, exist_ok=True)
    path = _daily_close_report_path(now.strftime('%Y%m%d'))
    need_rebuild = True
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                need_rebuild = _close_report_needs_rebuild(json.load(f))
        except Exception:
            need_rebuild = True
    if need_rebuild:
        from scripts.generate_daily_report import generate_close_report, load_intraday_snapshots, load_previous_trading_day_close_report
        # load_intraday_snapshots / load_previous_trading_day_close_report 由 generate_close_report 聚合使用，显式保留在这里便于回归检查。
        close_report = generate_close_report(base_report=report)
        close_report = _override_report_with_kline_price(close_report)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(close_report, f, ensure_ascii=False, indent=2)
    return path



def _close_report_needs_rebuild(report):
    if not isinstance(report, dict):
        return True
    if 'intraday_snapshots' not in report or 'previous_day_comparison' not in report:
        return True
    intraday = report.get('intraday_analysis') or report.get('market_brief') or {}
    required = [
        'trader_report',
        'market_snapshot_interpretation', 'gex_interpretation', 'oi_interpretation',
        'iv_interpretation', 'macro_interpretation', 'strategy_logic'
    ]
    if any(not intraday.get(k) for k in required):
        return True
    text = json.dumps(report, ensure_ascii=False)
    bad_terms = [
        '产业链/郑商所主力价', '首页K线接口当前价', '当前接口存在一个重要口径差异',
        '接口提示', '价格口径', 'TA609', '广州期货交易所', '仓单日报'
    ]
    return any(term in text for term in bad_terms)


# ==================== K线接口实时价覆盖 ====================
# 缓存生成时可能是 6290（15:00 收盘瞬间最后一根K线 close），但用户复盘/导出/显示时
# 实际价格已经变成 6302（TA2609 主力最新）。这里用 K线接口对所有出口做现场覆盖，
# 保证缓存/前端/Word/MD 导出 4 个出口值一致。
_STRATEGY_KLINE_CACHE = {'ts': 0.0, 'data': None}
_STRATEGY_KLINE_TTL = 3  # 短缓存，避免在同一次导出时把接口打穿


def _fetch_kline_ta609_for_report():
    """从进程内K线缓存拿当前 TA2609 主力价。仅做研报覆盖用，失败返回 None。

    不能在 Flask 请求处理中再 HTTP 回调本进程 /api/kline/data：当 K线/TqSdk 请求阻塞或
    dev server 工作线程耗尽时，会把 /strategy_report/realtime、导出、手动刷新一起拖死。
    这里仅读取已预热/近期请求写入的内存缓存，保证研报接口快速返回；拿不到就不覆盖，
    由前端实时覆盖兜底。
    """
    import time as _t
    now = _t.time()
    if _STRATEGY_KLINE_CACHE['data'] is not None and now - _STRATEGY_KLINE_CACHE['ts'] < _STRATEGY_KLINE_TTL:
        return _STRATEGY_KLINE_CACHE['data']

    def _parse(d):
        if not d:
            return None
        price = d.get('current_price')
        if price is None:
            bars = d.get('data') or []
            if bars:
                price = bars[-1].get('close')
        if price is None:
            return None
        return {
            'price': float(price),
            'change_pct': d.get('change_pct'),
            'source': d.get('source'),
            'symbol': d.get('symbol') or 'TA2609',
        }

    try:
        with _kline_tqsdk_lock:
            # 优先拿最近一次1min小样本；没有再退到其它TA缓存。只读内存，不触发TqSdk/HTTP。
            items = list(_kline_tqsdk_cache.items())
        preferred = []
        fallback = []
        for key, cached in items:
            if 'CZCE.TA' not in key:
                continue
            if '_60_' in key or '_1min_' in key:
                preferred.append(cached)
            else:
                fallback.append(cached)
        candidates = sorted(preferred or fallback, key=lambda x: x.get('ts', 0), reverse=True)
        for cached in candidates:
            result = _parse((cached or {}).get('result') or {})
            if result:
                _STRATEGY_KLINE_CACHE['ts'] = now
                _STRATEGY_KLINE_CACHE['data'] = result
                return result
    except Exception as e:
        app.logger.warning('[覆盖] 读取K线内存缓存失败: %s', e)

    return None


def _override_report_with_kline_price(report):
    """用首页K线接口当前价覆盖研报里的盘面主力参考价（字段/表格/正文三处都要覆盖）。
    对应前端 loadDailyReport() 的覆盖逻辑；这里是后端镜像，确保导出 Word/MD 与前端一致。

    v2.11.37+澄清：人工 spot_main_overrides 只覆盖 PX/现货，不覆盖盘面主力。
    盘面主力参考价必须来自实时K线（用户人工合约是 TA2609，但K线接口默认给"TA"，
    symbol 差异通过 _fetch_kline_ta609_for_report() 内部处理）。
    """
    if not isinstance(report, dict):
        return report
    kline = _fetch_kline_ta609_for_report()
    if not kline or kline.get('price') is None:
        app.logger.warning('[覆盖] K线接口未返回价,report=%s keys=%s', report.get('report_type'), list(report.keys())[:5] if isinstance(report, dict) else None)
        return report
    new_price = float(kline['price'])
    new_symbol = str(kline.get('symbol') or 'TA2609')
    live_text = f"{new_price:g}"
    app.logger.warning('[覆盖] K线接口 price=%s symbol=%s, old_mfp=%s', new_price, new_symbol, (report.get('intraday_analysis') or {}).get('main_futures_price'))

    def _override_node(node):
        if not isinstance(node, dict):
            return
        old_price = node.get('main_futures_price')
        # 字段层
        if old_price is not None and float(old_price) != new_price:
            node['main_futures_price'] = new_price
        if not node.get('main_futures_symbol'):
            node['main_futures_symbol'] = new_symbol
        # 注意：K线实时价只覆盖盘面主力参考价。
        # 期权链标的参考价/GEX futures_price 是期权结构口径，不能被 TA609 K线价污染。
        # 表格层：futures_panel 是 markdown table 字符串。
        # 单元格内容可能是 "6338"、"TA 6338"、"TA2609 6338" 等不同形式，必须用统一替换。
        panel = node.get('futures_panel')
        if isinstance(panel, str):
            import re as _re
            # 把 "| 盘面主力参考价 | <TA?> <价格> |" 整段重写为新价；不依赖价格字段格式
            panel = _re.sub(
                r'(\|\s*盘面主力参考价\s*\|\s*)([^\n|]+?)(\s*\|)',
                lambda m: f'{m.group(1)}{new_symbol} {live_text}{m.group(3)}',
                panel)
            node['futures_panel'] = panel
        mst = node.get('market_snapshot_table')
        if isinstance(mst, list):
            # 同步重算"基差"行：基差 = PTA现货 − 盘面主力参考价。
            # 否则当 main_futures_price 从 fallback 值被 K线覆盖时,基差仍停留在旧主力价,出现"主力价 5784 / 基差 -225"自相矛盾。
            _pta_spot = None
            _new_main_price = new_price
            for row in mst:
                if isinstance(row, list) and len(row) >= 2:
                    if str(row[0] or '') == 'PTA现货':
                        try:
                            _pta_spot = float(str(row[1]).replace(',', ''))
                        except (TypeError, ValueError):
                            _pta_spot = None
                    if '盘面主力参考价' in str(row[0] or '') or '盘面助理参考价' in str(row[0] or ''):
                        row[1] = f"{new_symbol} {live_text}"
            # 重算基差行
            if _pta_spot is not None:
                _recomputed_basis = round(_pta_spot - _new_main_price, 2)
                for row in mst:
                    if isinstance(row, list) and len(row) >= 2 and str(row[0] or '') == '基差':
                        try:
                            from scripts.generate_daily_report import _fmt_signed  # type: ignore
                        except Exception:
                            _fmt_signed = lambda v, digits=0: (('--' if v is None else f'{float(v):+.{digits}f}'))
                        row[1] = _fmt_signed(_recomputed_basis)
        # 文本层
        def _rep(text):
            if not isinstance(text, str):
                return None
            import re as _re
            # 关键：必须用 ASCII 标志，否则 \s 会吞掉汉字边界（汉字的"负责"被当空白），
            # 导致 "盘面主力参考价 TA 6338负责..." 永远匹配不完整、文本残留旧价。
            # 三种格式都要覆盖：
            #   1) markdown 表格行："| 盘面主力参考价 | TA 6338 |" 整段重写（保护 | 边界）
            #   2) narrative 文本："盘面主力参考价 TA 6338" / "盘面主力参考价6338" inline
            _pat_table_main = r'\|\s*盘面主力参考价\s*\|\s*(?:[A-Z0-9]+\s+)?\d+(?:\.\d+)?\s*\|'
            _pat_table_asst = r'\|\s*盘面助理参考价\s*\|\s*(?:[A-Z0-9]+\s+)?\d+(?:\.\d+)?\s*\|'
            _pat_inline_main = r'盘面主力参考价\s+(?:[A-Z0-9]+\s+)?\d+(?:\.\d+)?'
            _pat_inline_main2 = r'盘面主力参考价\d+(?:\.\d+)?'  # 紧贴数字的"盘面主力参考价6338"
            _pat_inline_asst = r'盘面助理参考价\s+(?:[A-Z0-9]+\s+)?\d+(?:\.\d+)?'
            _pat_inline_asst2 = r'盘面助理参考价\d+(?:\.\d+)?'
            # 表格行整段替换（先做，保护 | 边界）
            text = _re.sub(_pat_table_main,
                f'| 盘面主力参考价 | {new_symbol} {live_text} |', text, flags=_re.ASCII)
            text = _re.sub(_pat_table_asst,
                f'| 盘面助理参考价 | {new_symbol} {live_text} |', text, flags=_re.ASCII)
            # 文本 inline 替换
            text = _re.sub(_pat_inline_main,
                f'盘面主力参考价 {new_symbol} {live_text}', text, flags=_re.ASCII)
            text = _re.sub(_pat_inline_main2,
                f'盘面主力参考价 {new_symbol} {live_text}', text, flags=_re.ASCII)
            text = _re.sub(_pat_inline_asst,
                f'盘面助理参考价 {new_symbol} {live_text}', text, flags=_re.ASCII)
            text = _re.sub(_pat_inline_asst2,
                f'盘面助理参考价 {new_symbol} {live_text}', text, flags=_re.ASCII)
            # 同步替换文本中的"基差±N"为按新主力价重算的值。
            # 必须在"盘面主力参考价"行覆盖完之后做（保证能拿到最新的 _pta_spot / new_price）
            # 注意：trader_report 第二节有"基差走弱(09合约贴水...)"等叙述文字,只匹配"基差±N"格式
            # 不匹配"基差走弱"等非数字形态,避免误伤。
            if _pta_spot is not None:
                _new_basis = round(_pta_spot - new_price, 2)
                try:
                    from scripts.generate_daily_report import _fmt_signed as _fs  # type: ignore
                except Exception:
                    _fs = lambda v, digits=0: (('--' if v is None else f'{float(v):+.{digits}f}'))
                _new_basis_text = _fs(_new_basis)
                # 表格行："| 基差 | ±N |" → "| 基差 | ±M |"
                text = _re.sub(r'\|\s*基差\s*\|\s*[+-]?\d+(?:\.\d+)?\s*\|',
                               f'| 基差 | {_new_basis_text} |', text, flags=_re.ASCII)
                # 文本 inline："基差±N" 必须后接"（即"或紧跟"（"才匹配，避免误命中"基差走弱"等叙述
                text = _re.sub(r'基差[+-]?\d+(?:\.\d+)?(?=\s*[（(]?即)',
                               f'基差{_new_basis_text}', text, flags=_re.ASCII)
                # 兜底:trader_report 第三节"现货参考6127，基差±N，PX参考..."模式
                text = _re.sub(r'(现货参考[\d,.]+[，,]\s*)基差[+-]?\d+(?:\.\d+)?(?=\s*[，,])',
                               rf'\1基差{_new_basis_text}', text, flags=_re.ASCII)
            return text
        for k in ('narrative', 'trader_report',
                  'market_snapshot_interpretation',
                  'gex_interpretation', 'oi_interpretation',
                  'iv_interpretation', 'macro_interpretation',
                  'strategy_logic', 'summary', 'conclusion'):
            v = _rep(node.get(k))
            if v is not None:
                node[k] = v
        # 节点级：递归扫所有字符串字段（防止 narrative/strategy_logic 嵌套 JSON 字符串）
        for k, v in list(node.items()):
            if isinstance(v, str) and ('盘面主力参考价' in v or '期权链标的参考价' in v):
                nv = _rep(v)
                if nv is not None:
                    node[k] = nv

    # intraday_analysis 和 market_brief 是两个独立的快照节点，futures_panel 字符串也可能分别缓存着不同的旧价；
    # 之前的实现只覆盖了 intraday_analysis，导致前端 market_brief 路径（部分页面/导出/某些主题）仍显示 8 分钟前写死的旧价。
    # 关键：期权链标的参考价/GEX/Pain 的价不允许被 K线价污染，_override_node 内部已守住这条边界。
    if isinstance(report.get('intraday_analysis'), dict):
        _override_node(report['intraday_analysis'])
    if isinstance(report.get('market_brief'), dict):
        _override_node(report['market_brief'])
    for snap in report.get('intraday_snapshots') or []:
        if isinstance(snap, dict):
            for sub in ('intraday_analysis', 'market_brief'):
                if isinstance(snap.get(sub), dict):
                    _override_node(snap[sub])
    return report


def _trigger_strategy_report_background_refresh():
    """后台刷新15分钟研报；/realtime接口只负责快速返回缓存，不阻塞页面。"""
    global _strategy_report_refreshing
    if _strategy_report_refreshing:
        return

    def _worker():
        global _strategy_report_refreshing
        try:
            with _strategy_report_lock:
                # 15:00 后切到 close 模式，确保主页刷新立即带上收盘复盘数据
                # v2.11.48+: 21:00-23:00 夜盘时段仍按 intraday 模式跑,让 save_intraday_snapshot 把夜盘槽位归档
                now_h = dt_datetime.now().hour
                in_night_session = 21 <= now_h < 23
                is_after_close = (now_h >= 15) and not in_night_session
                report = _generate_strategy_report(force_close=is_after_close)
                _maybe_write_close_report(report)
        except Exception as e:
            app.logger.error('[策略研报API] 后台刷新失败: %s', e)
        finally:
            _strategy_report_refreshing = False

    _strategy_report_refreshing = True
    threading.Thread(target=_worker, daemon=True, name='strategy-report-refresh').start()


def _strategy_report_periodic_scheduler(interval_minutes: int = 15):
    """独立定时调度:整 15 分钟边界主动刷新研报缓存,不依赖浏览器访问。

    v2.11.47+: 用绝对时刻 sleep 到下一个整 15 分边界,不再固定 sleep(900) 导致累积漂移。
    之前每次刷新实际消耗 350-630 秒,固定 sleep 900 秒会让实际完成时间偏离整 15 分越来越远
    (如 09:30 → 10:48 → 12:21 → 13:52 → 15:36,完全不在整 15 分边界)。

    close/intraday 模式切换:
    - hour < 15: intraday 模式(普通盘中)
    - hour >= 15: close 模式(15:00 后全天总复盘)
    - 00:00-08:59 不刷新(无交易时段,刷新也浪费)
    """
    from datetime import datetime, timedelta
    # 启动后第一次 sleep 到下一个整 15 分边界(09:00/09:15/09:30/...)
    # 注意:启动时间可能恰好就是整 15 分边界,此时应立即触发,不等下一拍
    while True:
        now = datetime.now()
        # 整 15 分边界 = 当前时间的 minute % 15 == 0
        if now.minute % 15 == 0 and now.second < 30:
            boundary_dt = now.replace(second=0, microsecond=0)
        else:
            # 下一个整 15 分边界
            next_minute = ((now.minute // 15) + 1) * 15
            if next_minute >= 60:
                boundary_dt = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            else:
                boundary_dt = now.replace(minute=next_minute, second=0, microsecond=0)
        sleep_sec = (boundary_dt - now).total_seconds()
        if sleep_sec > 0:
            print(f"[strategy-report] 周期调度:下次刷新 @ {boundary_dt.strftime('%H:%M:%S')} (sleep {sleep_sec:.0f}s)")
            import time
            time.sleep(sleep_sec)
        try:
            t0 = time.time()
            now_run = datetime.now()
            # 15:00 后切到 close 模式:让 /realtime 缓存也带上 previous_day_comparison 字段。
            # v2.11.48+: 21:00-23:00 夜盘时段切回 intraday 模式,确保 save_intraday_snapshot 被调用、夜盘槽位能归档,
            # 否则 build_daily_comparison 永远拿不到夜盘数据, intraday_slots 只有日盘 12 份。
            # 00:00-08:59 跳过(无交易,生成也无意义)。
            if now_run.hour < 9:
                print(f"[strategy-report] 非交易时段 {now_run.strftime('%H:%M:%S')} 跳过")
                continue
            # 夜盘 21:00-23:00 强制 intraday 模式(即便 hour>=15)
            in_night_session = 21 <= now_run.hour < 23
            is_after_close = (now_run.hour >= 15) and not in_night_session
            report = _generate_strategy_report(force_close=is_after_close)
            _maybe_write_close_report(report)
            print(f"[strategy-report] 周期刷新完成: {(time.time()-t0):.1f}s @ {now_run.strftime('%H:%M:%S')} mode={'close' if is_after_close else 'intraday'}")
        except Exception as e:
            import logging
            logging.getLogger('werkzeug').error('[策略研报API] 周期刷新失败: %s', e)
            print(f"[strategy-report] 周期刷新失败: {e}")


@app.route('/api/strategy_report/manual_macro', methods=['GET', 'POST'])
def api_strategy_report_manual_macro():
    """保存/读取用户盘前或休盘后补充的宏观基本面材料。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'fundamental', 'manual_macro_input.json')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if request.method == 'GET':
        data = {}
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        return jsonify({'success': True, 'data': data, 'path': path})
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({'success': False, 'error': '内容必须是JSON对象'}), 400
    payload['updated_at'] = dt_datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return jsonify({'success': True, 'data': payload})


@app.route('/api/px_external/scrape', methods=['GET', 'POST'])
def api_px_external_scrape():
    """PX 外盘抓取文件读写端点。

    GET：返回当前 data/fundamental/px_external_scrape.json 内容。
    POST：覆盖写入（带 status=failed 也允许，用于人工标注抓取失败）。
    """
    try:
        from macro.px_external_source import load_scrape, save_scrape, SCRAPE_PATH
        if request.method == 'GET':
            data = load_scrape(SCRAPE_PATH) or {}
            return jsonify({'success': True, 'data': data, 'path': SCRAPE_PATH})
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({'success': False, 'error': '内容必须是JSON对象'}), 400
        data = save_scrape(payload, SCRAPE_PATH)
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/px_external/fetch', methods=['GET', 'POST'])
def api_px_external_fetch():
    """触发一次 PX 外盘抓取（best-effort）；用于前端"立即抓取"按钮。"""
    try:
        from macro.px_external_scraper import fetch
        rec = fetch()
        return jsonify({'success': True, 'data': rec})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/px_external/merge', methods=['GET'])
def api_px_external_merge():
    """返回三路合并的赢家 + 所有有效候选（人工 / 抓取 / 文本），方便前端展示。

    注：本端点不调 get_px_external_data，避免顺带触发 USD/CNY 远程拉取；
    pta_external_cost 留给研报面板在用 rate 缓存后算。
    """
    try:
        from macro.px_external_source import load_scrape, merge_pick_winner, format_winner
        from scripts.generate_daily_report import _parse_px_asia_price_from_text, _clean_news_text
        from datetime import datetime

        manual_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'fundamental', 'manual_macro_input.json')
        manual = {}
        if os.path.exists(manual_path):
            with open(manual_path, 'r', encoding='utf-8') as f:
                manual = json.load(f)

        scrape = load_scrape()

        # 文本正则（无 network，毫秒级）
        text_extracted: Dict = {}
        candidates_text = []
        def _collect(label, obj):
            if isinstance(obj, str):
                candidates_text.append((label, obj))
            elif isinstance(obj, list):
                for it in obj: _collect(label, it)
            elif isinstance(obj, dict):
                for it in obj.values(): _collect(label, it)
        _collect('人工宏观基本面', manual)
        for src, text in candidates_text:
            val = _parse_px_asia_price_from_text(text)
            if val:
                text_extracted = {
                    'px_asia_close_usd': val,
                    'date': manual.get('as_of_date') or datetime.now().strftime('%Y-%m-%d'),
                    'fetched_at': manual.get('updated_at') or datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
                    'source': src,
                    'source_text': _clean_news_text(text, 180),
                }
                break

        winner, all_valid = merge_pick_winner(
            manual_macro=manual, scrape=scrape, text_extracted=text_extracted,
        )
        return jsonify({
            'success': True,
            'winner': format_winner(winner) if winner else None,
            'candidate_count': len(all_valid),
            'candidates': [
                {
                    'source_kind': c.get('source_kind'),
                    'date': c.get('date'),
                    'fetched_at': c.get('fetched_at'),
                    'px_asia_close_usd': c.get('px_asia_close_usd'),
                    'source': c.get('source'),
                } for c in all_valid
            ],
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/strategy_report/realtime')
def api_strategy_report_realtime():
    """研报与策略实时面板：默认读15分钟缓存，避免页面被外部数据源阻塞。"""
    try:
        cached, mtime = _load_strategy_report_cache()
        if cached and _strategy_report_is_fresh(mtime):
            close_path = _maybe_write_close_report(cached)
            # 新鲜缓存也要用 K线实时价覆盖盘面主力参考价，避免缓存里固化的旧价与首页K线图不一致。
            cached = _override_report_with_kline_price(cached)
            return jsonify({'success': True, 'data': cached, 'cached': True, 'cache_time': mtime.strftime('%Y-%m-%d %H:%M:%S'), 'cache_minutes': STRATEGY_REPORT_CACHE_MINUTES, 'close_report_ready': bool(close_path)})

        # 缓存过期时立即返回旧缓存，并触发后台刷新；页面请求不再等待外部宏观/基本面抓取。
        if cached:
            _trigger_strategy_report_background_refresh()
            # 出口前用 K 线接口实时价覆盖字段/表格/正文；和前端 loadDailyReport() 一致。
            cached = _override_report_with_kline_price(cached)
            return jsonify({'success': True, 'data': cached, 'cached': True, 'stale': True, 'cache_time': mtime.strftime('%Y-%m-%d %H:%M:%S'), 'cache_minutes': STRATEGY_REPORT_CACHE_MINUTES, 'refreshing': True})

        # 首次无缓存时才同步生成一次；若失败，返回结构化JSON错误而不是HTML 500。
        with _strategy_report_lock:
            report = _generate_strategy_report(force_close=False)
            report = _override_report_with_kline_price(report)
            close_path = _maybe_write_close_report(report)
            return jsonify({'success': True, 'data': report, 'cached': False, 'cache_minutes': STRATEGY_REPORT_CACHE_MINUTES, 'close_report_ready': bool(close_path)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/strategy_report/refresh', methods=['GET', 'POST'])
def api_strategy_report_refresh():
    """手动刷新研报与策略。"""
    try:
        with _strategy_report_lock:
            # 15:00 后切到 close 模式，让用户手动刷新立即拿到收盘复盘数据
            is_after_close = dt_datetime.now().hour >= 15
            report = _generate_strategy_report(force_close=is_after_close)
            report = _override_report_with_kline_price(report)
            close_path = _maybe_write_close_report(report)
        return jsonify({'success': True, 'data': report, 'cached': False, 'manual': True, 'cache_minutes': STRATEGY_REPORT_CACHE_MINUTES, 'close_report_ready': bool(close_path)})
    except Exception as e:
        app.logger.error('[策略研报API] 手动刷新失败: %s', e)
        cached, mtime = _load_strategy_report_cache()
        if cached:
            cached = _override_report_with_kline_price(cached)
            return jsonify({'success': True, 'data': cached, 'cached': True, 'stale': True, 'manual': True, 'error': str(e)})
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/strategy_report/daily')
def api_strategy_report_daily():
    """读取或生成15:00后的全天总研报。"""
    date_text = request.args.get('date') or dt_datetime.now().strftime('%Y%m%d')
    date_text = ''.join(ch for ch in date_text if ch.isdigit())[:8]
    path = _daily_close_report_path(date_text)
    try:
        cached, _ = _load_strategy_report_cache()
        is_today = date_text == dt_datetime.now().strftime('%Y%m%d')
        if is_today and dt_datetime.now().hour < 15:
            return jsonify({'success': True, 'data': cached, 'cached': True, 'ready': False, 'message': '15:00收盘后生成全天总研报'})
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not _close_report_needs_rebuild(data):
                data = _override_report_with_kline_price(data)
                return jsonify({'success': True, 'data': data, 'cached': True, 'ready': True, 'previous_day_comparison': data.get('previous_day_comparison')})
        from scripts.generate_daily_report import generate_close_report, load_intraday_snapshots, load_previous_trading_day_close_report
        # load_intraday_snapshots / load_previous_trading_day_close_report 在 generate_close_report 内用于全天聚合与前日动态对比。
        report = generate_close_report(base_report=cached)
        report = _override_report_with_kline_price(report)
        os.makedirs(STRATEGY_CLOSE_REPORT_DIR, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        return jsonify({'success': True, 'data': report, 'cached': False, 'ready': True, 'previous_day_comparison': report.get('previous_day_comparison')})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500



def format_strategy_report_markdown(report):
    """把研报与策略导出为适合存档的Markdown。"""
    def _fmt_num(v, digits: int = 0, prefix: str = '') -> str:
        """Markdown导出本地数字格式化，避免依赖日报生成脚本内部 helper。"""
        try:
            if v is None or v == '':
                return '--'
            x = float(v)
            if math.isnan(x) or math.isinf(x):
                return '--'
            if digits == 0:
                return prefix + f"{x:,.0f}"
            return prefix + f"{x:,.{digits}f}"
        except Exception:
            return str(v) if v not in (None, '') else '--'

    report = report or {}
    ia = report.get('intraday_analysis') or report.get('market_brief') or {}
    cmp = report.get('previous_day_comparison') or {}
    lines = []
    title = 'PTA研报与策略'
    if report.get('report_type') == 'close':
        title = 'PTA盘后综合日报'
    elif report.get('report_type') == 'intraday':
        title = 'PTA盘中研报与策略'
    lines.append(f"# {title}")
    lines.append('')
    lines.append(f"- 生成时间：{report.get('timestamp') or '-'}")
    lines.append(f"- 报告类型：{report.get('report_type') or '-'}")
    lines.append(f"- 交易阶段：{report.get('market_session') or '-'}")
    if cmp:
        lines.append(f"- 动态对比完整度：{cmp.get('comparison_quality') or '-'}")
        lines.append(f"- 日内快照覆盖：{cmp.get('intraday_coverage_status') or '-'}")
        lines.append(f"- 前日总报：{'已接入' if cmp.get('previous_day_available') else '暂缺'}")
        if cmp.get('summary'):
            lines.append(f"- 收盘复盘摘要：{cmp.get('summary')}")
        if cmp.get('data_limitation_note'):
            lines.append(f"- 说明：{cmp.get('data_limitation_note')}")
    lines.append('')

    if cmp.get('intraday_review') or cmp.get('previous_day_dynamic'):
        lines.append('## 收盘复盘：日内走势与前日动态对比')
        lines.append('')
        review = cmp.get('intraday_review') or {}
        prev_dyn = cmp.get('previous_day_dynamic') or {}
        if review.get('summary'):
            lines.append(f"- 日内走势：{review.get('summary')}")
        if prev_dyn.get('summary'):
            lines.append(f"- 前日对比：{prev_dyn.get('summary')}")
        if review.get('points'):
            lines.append('')
            lines.append('| 时点 | 盘面主力参考价 | 结构判断 | 摘要 |')
            lines.append('| --- | --- | --- | --- |')
            for p in review.get('points') or []:
                lines.append(f"| {p.get('slot') or '-'} | {_fmt_num(p.get('price'))} | {p.get('bias') or '-'} | {p.get('summary') or '-'} |")
        lines.append('')

    def add_table(title, headers, rows):
        rows = rows or []
        if not rows:
            return
        lines.append(f"## {title}")
        lines.append('')
        lines.append('| ' + ' | '.join(str(x) for x in headers) + ' |')
        lines.append('| ' + ' | '.join(['---'] * len(headers)) + ' |')
        for row in rows:
            row = row if isinstance(row, list) else []
            vals = [str(row[i]) if i < len(row) else '' for i in range(len(headers))]
            lines.append('| ' + ' | '.join(v.replace('\n', '<br>') for v in vals) + ' |')
        lines.append('')

    def add_text(title, text):
        if text:
            lines.append(f"### {title}")
            lines.append('')
            lines.append(str(text))
            lines.append('')

    def _split_narrative_notes(text):
        notes = {'market': [], 'gex': [], 'oi': [], 'iv': [], 'macro': [], 'strategy': [], 'other': []}
        for raw in re.split(r'\n+|。|；', str(text or '')):
            t = raw.strip().lstrip('-• ')
            if not t:
                continue
            if re.search(r'GEX|Gamma|Pain|痛点|翻转', t, re.I):
                notes['gex'].append(t)
            elif re.search(r'持仓|OI|Put|Call|支撑|压力', t, re.I):
                notes['oi'].append(t)
            elif re.search(r'IV|隐波|波动|偏斜|Skew|曲率|T表', t, re.I):
                notes['iv'].append(t)
            elif re.search(r'原油|PX|成本|宏观|快讯|美元|库存|开工|利润', t, re.I):
                notes['macro'].append(t)
            elif re.search(r'策略|操作|买方|卖方|期货|期权|建议|风险', t, re.I):
                notes['strategy'].append(t)
            elif re.search(r'盘面|价格|主力|标的|节奏|基差', t, re.I):
                notes['market'].append(t)
            else:
                notes['other'].append(t)
        return notes

    def _combined(base, extras):
        parts = []
        if base:
            parts.append(str(base))
        parts.extend(str(x) for x in (extras or []) if x)
        return '；'.join(parts)

    narrative_notes = ia.get('narrative_notes') or {'market': [], 'gex': [], 'oi': [], 'iv': [], 'macro': [], 'strategy': [], 'other': []}

    add_table('盘面快照', ['项目','当前值','交易含义'], ia.get('market_snapshot_table'))
    add_text('盘面解读', _combined(ia.get('market_snapshot_interpretation'), narrative_notes.get('market')))
    add_table('GEX / Pain', ['指标','当前值'], ia.get('gex_table'))
    add_text('GEX解读', _combined(ia.get('gex_interpretation'), narrative_notes.get('gex')))
    oi = ia.get('oi_tables') or {}
    add_table('Put持仓集中', ['Put行权价','Put OI'], oi.get('put'))
    add_table('Call持仓集中', ['Call行权价','Call OI'], oi.get('call'))
    add_text('持仓结构解读', _combined(ia.get('oi_interpretation'), narrative_notes.get('oi')))
    add_table('ATM附近IV / T表', ['K','C IV','P IV','SVI/平滑IV','OI结构'], ia.get('iv_table'))
    add_text('隐波解读', _combined(ia.get('iv_interpretation'), narrative_notes.get('iv')))
    add_table('宏观与成本快照', ['项目','当前值','解读'], ia.get('macro_table'))
    add_text('宏观成本解读', _combined(ia.get('macro_interpretation'), narrative_notes.get('macro')))
    if ia.get('macro_news_items'):
        lines.append('## 宏观财经快讯')
        lines.append('')
        for item in ia.get('macro_news_items') or []:
            lines.append(f"- {item}")
        lines.append('')
    strategies = ia.get('strategy_blocks') or {}
    for key in ['futures_strategy', 'option_seller_strategy', 'option_buyer_strategy']:
        block = strategies.get(key) or {}
        if block.get('items'):
            lines.append(f"## {block.get('title') or key}")
            lines.append('')
            for item in block.get('items') or []:
                lines.append(f"- {item}")
            lines.append('')
    strategy_text = _combined(ia.get('strategy_logic'), narrative_notes.get('strategy'))
    if strategy_text:
        lines.append('### 策略依据')
        lines.append('')
        lines.append(strategy_text)
        lines.append('')
    if narrative_notes.get('other'):
        add_text('综合摘要', '；'.join(narrative_notes.get('other')[:2]))
    if report.get('intraday_snapshots'):
        lines.append('## 日内15分钟快照摘要')
        lines.append('')
        for snap in report.get('intraday_snapshots') or []:
            lines.append(f"- {snap.get('slot') or snap.get('time') or '-'}：{snap.get('summary') or '-'}")
        lines.append('')
    return '\n'.join(lines).strip() + '\n'


def _xml_escape(text):
    return str(text or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def format_strategy_report_docx(report):
    """生成Word docx二进制文件；不依赖python-docx，Office/WPS可直接打开。"""
    md = format_strategy_report_markdown(report)
    paras = []
    for raw in md.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith('|'):
            if set(line.replace('|', '').replace('-', '').replace(' ', '')) == set():
                continue
            text = line.strip('|').replace('|', '  |  ')
            paras.append(f'<w:p><w:r><w:t>{_xml_escape(text)}</w:t></w:r></w:p>')
        elif line.startswith('# '):
            paras.append(f'<w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r><w:t>{_xml_escape(line[2:])}</w:t></w:r></w:p>')
        elif line.startswith('## '):
            paras.append(f'<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>{_xml_escape(line[3:])}</w:t></w:r></w:p>')
        elif line.startswith('### '):
            paras.append(f'<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>{_xml_escape(line[4:])}</w:t></w:r></w:p>')
        elif line.startswith('- '):
            paras.append(f'<w:p><w:r><w:t>• {_xml_escape(line[2:])}</w:t></w:r></w:p>')
        else:
            paras.append(f'<w:p><w:r><w:t>{_xml_escape(line)}</w:t></w:r></w:p>')
    document_xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\n  <w:body>\n    {body}\n    <w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>\n  </w:body>\n</w:document>'.format(body='\n'.join(paras))
    content_types = '<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n  <Default Extension="xml" ContentType="application/xml"/>\n  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>\n</Types>'
    rels = '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>\n</Relationships>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', content_types)
        z.writestr('_rels/.rels', rels)
        z.writestr('word/document.xml', document_xml)
    return buf.getvalue()


@app.route('/api/strategy_report/export')
def api_strategy_report_export():
    """导出当前研报与策略为Markdown，方便存档。"""
    try:
        report_type = request.args.get('type') or ('daily' if dt_datetime.now().hour >= 15 else 'realtime')
        if report_type in ('daily', 'close'):
            date_text = request.args.get('date') or dt_datetime.now().strftime('%Y%m%d')
            path = _daily_close_report_path(date_text)
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    report = json.load(f)
            else:
                cached, _ = _load_strategy_report_cache()
                from scripts.generate_daily_report import generate_close_report
                report = generate_close_report(base_report=cached)
        else:
            report, _ = _load_strategy_report_cache()
            if not report:
                report = _generate_strategy_report(force_close=False)
        # 导出前用首页K线实时价刷新"盘面主力参考价"字段/表格/正文三层
        report = _override_report_with_kline_price(report)
        fmt = (request.args.get('format') or 'docx').lower()
        stamp = dt_datetime.now().strftime('%Y%m%d_%H%M')
        if fmt == 'md':
            md = format_strategy_report_markdown(report)
            filename = f"pta_strategy_report_{stamp}.md"
            resp = make_response(md)
            resp.headers['Content-Type'] = 'text/markdown; charset=utf-8'
        else:
            docx_bytes = format_strategy_report_docx(report)
            filename = f"pta_strategy_report_{stamp}.docx"
            resp = make_response(docx_bytes)
            resp.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        resp.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        return resp
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/daily_report')
def api_daily_report():
    """兼容旧日报API；默认走策略研报15分钟缓存，refresh=1保持强制刷新语义。"""
    if request.args.get('refresh', '0') == '1':
        return api_strategy_report_refresh()
    return api_strategy_report_realtime()

# 期权链页面（/option_chain）已废弃 —— 整合到 /iv_smile
# 原 route option_chain_page 已移除 (v2.11.5)


# ==================== 科创50ETF期权 隐波微笑 ====================

@app.route('/api/kcb_iv')
def api_kcb_iv():
    """科创50ETF(588000) 期权隐波微笑曲线数据"""
    try:
        from flask import request
        from datetime import datetime, timedelta
        import akshare as ak

        month = request.args.get('month', type=int)

        # 取最近交易日
        today = datetime.now()
        trade_dates = []
        for i in range(10):
            check = today - timedelta(days=i)
            if check.weekday() < 5:
                trade_dates.append(check.strftime('%Y%m%d'))

        # 今日风险指标
        df_today = None
        for td in trade_dates:
            try:
                _df = ak.option_risk_indicator_sse(date=td)
                if 'IMPLC_VOLATLTY' in _df.columns and len(_df) > 100:
                    df_today = _df
                    break
            except Exception:
                continue
        if df_today is None:
            return jsonify({'success': False, 'error': '无法获取风险指标数据'})

        # 昨日风险指标（用于IV变化）
        df_yesterday = None
        for td in trade_dates[1:]:
            try:
                _df = ak.option_risk_indicator_sse(date=td)
                if 'IMPLC_VOLATLTY' in _df.columns and len(_df) > 100:
                    df_yesterday = _df
                    break
            except Exception:
                continue

        # 过滤科创50ETF期权
        import re
        def parse_symbol(sym):
            m = re.match(r'科创50(购|沽)(\d+)月(\d+)', str(sym))
            if m:
                opt_type = 'C' if m.group(1) == '购' else 'P'
                month_val = int(m.group(2))
                strike = float(m.group(3)) / 1000
                return opt_type, month_val, strike
            return None, None, None

        df_today['opt_type'], df_today['month'], df_today['strike'] = zip(
            *df_today['CONTRACT_SYMBOL'].apply(parse_symbol))
        df_today = df_today.dropna(subset=['opt_type'])

        if df_yesterday is not None:
            df_yesterday['opt_type'], df_yesterday['month'], df_yesterday['strike'] = zip(
                *df_yesterday['CONTRACT_SYMBOL'].apply(parse_symbol))
            df_yesterday = df_yesterday.dropna(subset=['opt_type'])
            ytd_idx = df_yesterday.set_index(['CONTRACT_SYMBOL'])

        today_idx = df_today.set_index(['CONTRACT_SYMBOL'])
        months = sorted(df_today['month'].unique())

        result_data = {}
        atm_strike = None

        for m in months:
            cm_t = df_today[(df_today['opt_type'] == 'C') & (df_today['month'] == m)].copy()
            pm_t = df_today[(df_today['opt_type'] == 'P') & (df_today['month'] == m)].copy()

            cm_t = cm_t.sort_values('strike')
            pm_t = pm_t.sort_values('strike')

            c_dict, p_dict = {}, {}

            for _, row in cm_t.iterrows():
                k = str(row['strike'])
                iv = float(row['IMPLC_VOLATLTY']) if row['IMPLC_VOLATLTY'] > 0 else None
                ytd_iv = None
                if df_yesterday is not None and row.name in ytd_idx.index:
                    ytd_iv = float(ytd_idx.loc[row.name]['IMPLC_VOLATLTY']) if ytd_idx.loc[row.name]['IMPLC_VOLATLTY'] > 0 else None
                iv_change = (iv - ytd_iv) if (iv and ytd_iv is not None) else None
                c_dict[k] = {
                    'iv': iv,
                    'iv_change': iv_change,
                    'delta': float(row['DELTA_VALUE']) if row['DELTA_VALUE'] else None,
                    'gamma': float(row['GAMMA_VALUE']) if row['GAMMA_VALUE'] else None,
                    'theta': float(row['THETA_VALUE']) if row['THETA_VALUE'] else None,
                    'vega': float(row['VEGA_VALUE']) if row['VEGA_VALUE'] else None,
                    'volume': None,
                    'oi': None,
                    'price': None,
                }

            for _, row in pm_t.iterrows():
                k = str(row['strike'])
                iv = float(row['IMPLC_VOLATLTY']) if row['IMPLC_VOLATLTY'] > 0 else None
                ytd_iv = None
                if df_yesterday is not None and row.name in ytd_idx.index:
                    ytd_iv = float(ytd_idx.loc[row.name]['IMPLC_VOLATLTY']) if ytd_idx.loc[row.name]['IMPLC_VOLATLTY'] > 0 else None
                iv_change = (iv - ytd_iv) if (iv and ytd_iv is not None) else None
                p_dict[k] = {
                    'iv': iv,
                    'iv_change': iv_change,
                    'delta': float(row['DELTA_VALUE']) if row['DELTA_VALUE'] else None,
                    'gamma': float(row['GAMMA_VALUE']) if row['GAMMA_VALUE'] else None,
                    'theta': float(row['THETA_VALUE']) if row['DELTA_VALUE'] else None,
                    'vega': float(row['VEGA_VALUE']) if row['VEGA_VALUE'] else None,
                    'volume': None,
                    'oi': None,
                    'price': None,
                }

            result_data[str(int(m))] = {'calls': c_dict, 'puts': p_dict}

        # ATM：取 Delta 在 0.3~0.7 之间的认购档位
        atm_strike = None
        calls_all = df_today[df_today['opt_type'] == 'C']
        atm_candidates = calls_all[
            (calls_all['IMPLC_VOLATLTY'] > 0) &
            (calls_all['DELTA_VALUE'].notna()) &
            (calls_all['DELTA_VALUE'].abs() < 0.7) &
            (calls_all['DELTA_VALUE'].abs() > 0.3)
        ]
        if not atm_candidates.empty:
            atm_strike = float(atm_candidates.sort_values('IMPLC_VOLATLTY', ascending=False).iloc[0]['strike'])

        resp_data = {
            'success': True,
            'data_date': trade_dates[0],
            'underlying': 'SH.588000',
            'atm_strike': atm_strike,
            'expiry_list': [str(int(m)) for m in months],
            'data': result_data
        }

        if month:
            if str(month) in result_data:
                resp_data['data'] = {str(month): result_data[str(month)]}
            else:
                return jsonify({'success': False, 'error': f'无月份 {month} 数据'})

        return jsonify(resp_data)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})


@app.route('/kcb_iv_smile')
def kcb_iv_smile_page():
    """科创50ETF期权隐波微笑曲线页面"""
    try:
        with open(os.path.join(WORKSPACE, 'templates', 'kcb_option_chain.html'), 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error loading page: {e}", 500

@app.route('/drawing_test')
def drawing_test_page():
    """绘图工具已合并到主页面 /kline"""
    from flask import redirect
    return redirect('/kline')

@app.route('/kline')
def kline_page():
    """K线图页面已迁移到 /，此路径保留重定向"""
    from flask import redirect
    return redirect('/', code=302)

@app.route('/chan/')
def chan_page():
    """缠论分析页面"""
    try:
        with open(os.path.join(WORKSPACE, 'templates', 'chan_web.html'), 'r', encoding='utf-8') as f:
            content = f.read()
        from flask import make_response
        resp = make_response(content)
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
        return resp
    except FileNotFoundError:
        return "缠论分析页面未找到", 404

@app.route('/chan')
def chan_page_redirect():
    """缠论分析页面重定向"""
    from flask import redirect
    return redirect('/chan/')

@app.route('/simple')
def simple_page():
    """简化测试页面"""
    try:
        with open(os.path.join(WORKSPACE, 'templates', 'test_kline.html'), 'r', encoding='utf-8') as f:
            content = f.read()
        return content
    except FileNotFoundError:
        return "Test page not found", 404

@app.route('/mini')
def mini_page():
    """最小化测试页"""
    try:
        with open(os.path.join(WORKSPACE, 'templates', 'mini_test.html'), 'r', encoding='utf-8') as f:
            content = f.read()
        return content
    except FileNotFoundError:
        return "Mini test page not found", 404

def _safe_val(v, default=0):
    """安全处理NaN/Inf值"""
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return default
    return v

def _parse_kline_time(dt_val):
    """解析K线时间为Unix时间戳（秒）"""
    if isinstance(dt_val, (int, float)) and math.isfinite(dt_val) and dt_val > 0:
        return int(dt_val / 1e9)
    dt_str = str(dt_val).replace('T', ' ')
    dt_obj = dt.datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
    return int((dt_obj - dt.datetime(1970, 1, 1)).total_seconds())

def _build_kline_bar(row, close, use_tqsdk=False):
    """构建单根K线数据字典"""
    return {
        'time': _parse_kline_time(row['datetime']),
        'open': _safe_val(float(row['open']), close),
        'high': _safe_val(float(row['high']), close),
        'low': _safe_val(float(row['low']), close),
        'close': close,
        'volume': _safe_val(float(row['volume']), 0),
        'open_interest': _safe_val(float(row['close_oi'] if use_tqsdk else row.get('hold', row.get('open_interest', 0))), 0)
    }

def _add_kline_changes(data):
    """为K线数据列表添加增减值（较前一根K线）"""
    for i, bar in enumerate(data):
        if i == 0:
            bar['volume_change'] = 0
            bar['open_interest_change'] = 0
        else:
            prev = data[i - 1]
            bar['volume_change'] = round(_safe_val(bar['volume'] - prev['volume'], 0), 2)
            bar['open_interest_change'] = round(_safe_val(bar['open_interest'] - prev['open_interest'], 0), 0)

def _fetch_kline_data(symbol='TA609', period='5min', count=500,
                      start_date=None, end_date=None, source='auto'):
    """内部K线数据获取（供回测等内部调用），返回 [{time, open, high, low, close, volume}, ...]

    Args:
        symbol: 品种代码，如 TA609
        period: K线周期，如 5min
        count: 最大K线数量
        start_date: 可选，起始日期 YYYY-MM-DD（TqSdk有效）
        end_date: 可选，结束日期 YYYY-MM-DD（TqSdk有效）
        source: 数据源 'tqsdk' | 'akshare' | 'auto'（默认自动选择）
    """
    import re
    period_seconds_map = {
        '1min': 60, '5min': 300, '15min': 900, '30min': 1800, '60min': 3600,
        '1day': 86400, '1week': 604800, '1month': 2592000
    }
    tqsdk_symbol_map = {
        'TA0': 'KQ.m@CZCE.TA', 'TA909': 'CZCE.TA609', 'TA609': 'CZCE.TA609',
        'TA607': 'CZCE.TA607', 'TA608': 'CZCE.TA608', 'TA610': 'CZCE.TA610',
    }
    tqsdk_symbol = tqsdk_symbol_map.get(symbol, 'CZCE.TA609')

    m = re.match(r'^(\d+)min$', period)
    if m:
        n = int(m.group(1))
        period_sec = n * 60
    elif period in period_seconds_map:
        period_sec = period_seconds_map[period]
    else:
        period_sec = 300  # 默认5min

    # 解析日期范围（转为unix时间戳秒）
    start_ts = None
    end_ts = None
    if start_date:
        try:
            start_ts = int(pd.Timestamp(start_date).timestamp())
        except Exception:
            start_ts = None
    if end_date:
        try:
            end_ts = int(pd.Timestamp(end_date + ' 23:59:59').timestamp())
        except Exception:
            end_ts = None

    # TqSdk 分支
    if source in ('auto', 'tqsdk'):
        try:
            # 关键修复：count 和日期范围协同工作
            # 如果指定了 start_date，从 start_date 开始取最多 count 根
            # 如果只指定了 end_date，取最近 count 根且不晚于 end_date
            # 如果都没指定，取最近 count 根
            fetch_count = count
            if start_ts and not end_ts:
                # 有起始日期：从起始日期开始取 count 根（end_date 留空让 TqSdk 取到最新）
                fetch_count = count
            elif start_ts and end_ts:
                # 双方都指定：需要多取一些数据再过滤，避免 TqSdk 自动截断
                fetch_count = max(count * 3, 2000)
            # else: 都没指定，取最近 count 根（默认行为）

            # v2.11.54+: K线 API 改用 TqKq 测试连接（auth=test 占测试账户名额，不占 mingmingliu 真实账户）
            # 否则会和 iv_smile 期权长连接（TqAuth mingmingliu）抢同一个账户名额，
            # TqSdk 限制同账户只允许一个连接，iv_smile 永远连不上。
            api = TqApi(TqKq(), auth=TqAuth('test', 'test'), debug=False)
            klines = api.get_kline_serial(tqsdk_symbol, period_sec, data_length=fetch_count)
            api.close()
            data = []
            for _, row in klines.iterrows():
                close = float(row['close']) if math.isfinite(row['close']) else None
                if close is None or close == 0:
                    continue
                bar_time = _parse_kline_time(row['datetime'])
                # 日期范围过滤（永远执行，确保 count 不会覆盖日期范围）
                if start_ts and bar_time < start_ts:
                    continue
                if end_ts and bar_time > end_ts:
                    continue
                data.append({
                    'time': bar_time,
                    'open': _safe_val(float(row['open']), close),
                    'high': _safe_val(float(row['high']), close),
                    'low': _safe_val(float(row['low']), close),
                    'close': close,
                    'volume': _safe_val(float(row['volume']), 0),
                })
            data.sort(key=lambda x: x['time'])
            # 最后再截断到 count（保持数据完整，在日期范围内取最新的 count 根）
            if len(data) > count:
                data = data[-count:]
            if data:
                return data
        except Exception:
            if source == 'tqsdk':
                return []  # 指定tqsdk但失败了，直接返回空

    # Akshare 分支
    if source in ('auto', 'akshare'):
        try:
            period_code = period.replace('min', 'm') if 'min' in period else period
            df = ak.futures_zh_minute_sina(symbol='TA0', period=period_code)
            df.columns = [c.strip() for c in df.columns]
            df['datetime'] = pd.to_datetime(df['datetime'])
            df = df.sort_values('datetime').reset_index(drop=True)  # 移除 tail(count)，让日期过滤生效
            data = []
            for _, row in df.iterrows():
                close = float(row['close']) if math.isfinite(row['close']) else None
                if close is None or close == 0:
                    continue
                bar_time = _parse_kline_time(row['datetime'])
                if start_ts and bar_time < start_ts:
                    continue
                if end_ts and bar_time > end_ts:
                    continue
                data.append({
                    'time': bar_time,
                    'open': _safe_val(float(row['open']), close),
                    'high': _safe_val(float(row['high']), close),
                    'low': _safe_val(float(row['low']), close),
                    'close': close,
                    'volume': _safe_val(float(row['volume']), 0),
                })
            data.sort(key=lambda x: x['time'])
            # 在日期范围内的数据，再截断到 count（取最新的 count 根）
            if len(data) > count:
                data = data[-count:]
            return data
        except Exception:
            return []

    return []

def _get_yesterday_close_tqsdk(symbol='CZCE.TA609'):
    """通过TqSdk获取昨日收盘价（用于计算涨跌）"""
    try:
        # TqKq() 是免费行情连接，不需要账号密码
        api = TqApi(TqKq(), auth=TqAuth('test', 'test'))
        # 获取2根日K线，取倒数第2根的收盘价作为昨日收盘价
        daily_klines = api.get_kline_serial(symbol, 86400, data_length=10)
        api.close()
        if len(daily_klines) >= 2:
            # 取倒数第2根（上一交易日）
            prev_close = float(daily_klines.iloc[-2]['close'])
            if math.isfinite(prev_close) and prev_close > 0:
                return prev_close
        return None
    except:
        return None

def _get_yesterday_close_akshare(symbol='TA0'):
    """通过akshare获取昨日收盘价"""
    try:
        df = ak.futures_zh_minute_sina(symbol=symbol, period='1d')
        df.columns = [c.strip() for c in df.columns]
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.sort_values('datetime')
        if len(df) >= 2:
            prev_close = float(df['close'].iloc[-2])
            if math.isfinite(prev_close) and prev_close > 0:
                return prev_close
        return None
    except:
        return None


## ==================== K线TqSdk缓存 ====================
# 避免每次请求都创建TqApi连接，与iv_smile的长连接竞争
# 休盘时数据不变，取一次缓存即可；盘中适当刷新
import time as _time_mod
_kline_tqsdk_cache = {}       # key: f"{symbol}_{period}" -> {'data': ..., 'ts': time.time(), 'yesterday_close': ...}
_KLINE_CACHE_TTL = 2          # 主页K线必须准实时；短缓存只用于避免频繁创建TqApi连接
_KLINE_TQSDK_RETRY_COOLDOWN = 60  # TqSdk临时失败后1分钟再试，不再永久降级到akshare
_kline_tqsdk_lock = threading.Lock()
_kline_tqsdk_failed = False   # 默认启用TqSdk；akshare仅作为明确fallback
_kline_tqsdk_failed_at = 0
_kline_tqsdk_warmed = False    # 启动时预热标志：避免首页冷启动耗时 18s+ 才拿到第一根K线

@app.route('/api/kline/data')
def api_kline_data():
    """K线图数据API
    - OHLC + volume: 取自TqSdk或akshare
    - open_interest: 每根K线自己的close_oi（TqSdk）或hold（akshare）
    - 涨跌（change/change_pct）: 较昨日收盘价
    - volume_change / open_interest_change: 较前一根K线
    """
    global _kline_tqsdk_failed, _kline_tqsdk_failed_at
    import re
    
    period = request.args.get('period', '1min')
    symbol = request.args.get('symbol', 'TA0')
    
    # 前端合约名 -> TqSdk合约名映射
    tqsdk_symbol_map = {
        'TA0': 'KQ.m@CZCE.TA',   # PTA主力连续（天勤自动跟随真实主力）
        'TA909': 'CZCE.TA609',
        'TA609': 'CZCE.TA609',
        'TA607': 'CZCE.TA607',
        'TA608': 'CZCE.TA608',
        'TA610': 'CZCE.TA610',
        'TA0C': 'CZCE.TA609',
    }
    tqsdk_symbol = tqsdk_symbol_map.get(symbol, 'CZCE.TA609')
    # 周期配置
    period_seconds_map = {
        '1min': 60, '5min': 300, '15min': 900, '30min': 1800, '60min': 3600,
        '1day': 86400, '1week': 604800, '1month': 2592000
    }
    
    m = re.match(r'^(\d+)min$', period)
    if m:
        n = int(m.group(1))
        period_sec = n * 60
        count = min(int(request.args.get('count', 1000)), 2000)
    elif period in period_seconds_map:
        period_sec = period_seconds_map[period]
        count = 500 if period in ['1day', '1week', '1month'] else min(int(request.args.get('count', 1000)), 2000)
    else:
        return jsonify({'error': f'unsupported period: {period}', 'symbol': 'TA', 'period': period, 'data': [], 'current_price': 0, 'change': 0, 'change_pct': 0})
    
    # 如果TqSdk刚失败过，只在冷却期内暂时跳过；到期后自动重试，避免永久卡在akshare延迟源
    if _kline_tqsdk_failed and (_time_mod.time() - _kline_tqsdk_failed_at) >= _KLINE_TQSDK_RETRY_COOLDOWN:
        _kline_tqsdk_failed = False

    # ==================== TqSdk 分支（带缓存，避免频繁创建连接） ====================
    cache_key = f"{tqsdk_symbol}_{period}_{count}"

    # 检查缓存是否有效
    if not _kline_tqsdk_failed:
        with _kline_tqsdk_lock:
            cached = _kline_tqsdk_cache.get(cache_key)
            if cached and (_time_mod.time() - cached['ts']) < _KLINE_CACHE_TTL:
                # 缓存命中，直接返回
                return jsonify(cached['result'])
    
    # 缓存未命中或已过期，尝试TqSdk（但如果之前失败过就跳过）
    if not _kline_tqsdk_failed:
        try:
            # v2.11.54+: 改用 TqKq 测试连接（auth=test）避免抢 iv_smile 真实账户 mingmingliu 连接名额
            api = TqApi(TqKq(), auth=TqAuth('test', 'test'), debug=False)
            klines = api.get_kline_serial(tqsdk_symbol, period_sec, data_length=count)
            api.wait_update(deadline=_time_mod.time() + 1)  # 1秒即可：只接收已经到了的tick；盘后夜盘未开时直接返回缓存kline

            # 获取昨日收盘价（用于计算涨跌）——从同一个api实例获取，不再创建新连接
            yesterday_close = None
            try:
                daily_klines = api.get_kline_serial(tqsdk_symbol, 86400, data_length=10)
                if len(daily_klines) >= 2:
                    prev_close = float(daily_klines.iloc[-2]['close'])
                    if math.isfinite(prev_close) and prev_close > 0:
                        yesterday_close = prev_close
            except:
                pass
            
            data = []
            for _, row in klines.iterrows():
                close = float(row['close']) if math.isfinite(row['close']) else None
                if close is None or close == 0:
                    continue
                data.append(_build_kline_bar(row, close, use_tqsdk=True))
            
            api.close()
            data.sort(key=lambda x: x['time'])
            
            # 计算涨跌（较昨日收盘价）
            last = data[-1] if data else {}
            current_price = _safe_val(last.get('close', 0), 0)
            if yesterday_close and yesterday_close > 0:
                change = round(current_price - yesterday_close, 2)
                change_pct = round((change / yesterday_close) * 100, 2)
            else:
                change, change_pct = 0, 0
            
            # 添加增减值（较前一根K线）
            _add_kline_changes(data)
            
            result = {
                'symbol': 'TA', 'period': period, 'data': data,
                'current_price': round(current_price, 2),
                'change': change, 'change_pct': change_pct,
                'yesterday_close': yesterday_close,
                'source': 'tqsdk'
            }
            
            # 写入缓存
            with _kline_tqsdk_lock:
                _kline_tqsdk_cache[cache_key] = {'result': result, 'ts': _time_mod.time()}
            
            return jsonify(result)
        except Exception as e:
            app.logger.error(f'[K线API] TqSdk获取失败，临时降级到akshare symbol={symbol} period={period} error={type(e).__name__}:{e}')
            _kline_tqsdk_failed = True
            _kline_tqsdk_failed_at = _time_mod.time()

    # ==================== Akshare Fallback 分支 ====================
    try:
        period_code = period.replace('min', 'm') if 'min' in period else period
        df = ak.futures_zh_minute_sina(symbol='TA0', period=period_code)
        df.columns = [c.strip() for c in df.columns]
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.sort_values('datetime').tail(500).reset_index(drop=True)

        # 获取昨日收盘价
        yesterday_close = _get_yesterday_close_akshare('TA0')

        data = []
        for _, row in df.iterrows():
            close = float(row['close']) if math.isfinite(row['close']) else None
            if close is None or close == 0:
                continue
            data.append(_build_kline_bar(row, close, use_tqsdk=False))

        data.sort(key=lambda x: x['time'])

        # 计算涨跌
        last = data[-1] if data else {}
        current_price = _safe_val(last.get('close', 0), 0)
        if yesterday_close and yesterday_close > 0:
            change = round(current_price - yesterday_close, 2)
            change_pct = round((change / yesterday_close) * 100, 2)
        else:
            change, change_pct = 0, 0

        # 添加增减值
        _add_kline_changes(data)

        return jsonify({
            'symbol': 'TA', 'period': period, 'data': data,
            'current_price': round(current_price, 2),
            'change': change, 'change_pct': change_pct,
            'yesterday_close': yesterday_close,
            'source': 'akshare',
            'fallback_warning': '⚠️ TqSdk实时数据获取失败，当前为akshare延迟数据（通常晚15-30分钟），请检查网络或TqSdk认证'
        })
    except Exception as e2:
        app.logger.error(f'[K线API] TqSdk和akshare均失败 symbol={symbol} period={period} error={e2}')
        return jsonify({'error': f'获取失败: {str(e2)}', 'symbol': 'TA', 'period': period, 'data': [], 'current_price': 0, 'change': 0, 'change_pct': 0, 'fallback_warning': '❌ K线数据获取完全失败，实时和延迟数据源均不可用'})


def _kline_warmup():
    global _kline_tqsdk_failed, _kline_tqsdk_failed_at
    """启动时预热K线缓存：避免首页冷启动耗时18s+才拿到第一根K线。
    主流周期TA0 1min/5min/15min/30min/60min/1day各预热一次。"""
    global _kline_tqsdk_warmed
    targets = [
        ('KQ.m@CZCE.TA', 60, 1000),       # 1min
        ('KQ.m@CZCE.TA', 300, 1000),      # 5min
        ('KQ.m@CZCE.TA', 900, 1000),      # 15min
        ('KQ.m@CZCE.TA', 1800, 1000),     # 30min
        ('KQ.m@CZCE.TA', 3600, 1000),     # 60min
        ('KQ.m@CZCE.TA', 86400, 500),     # 1day
    ]
    for sym, period_sec, count in targets:
        if _kline_tqsdk_failed:
            break
        try:
            cache_key = f"{sym}_{period_sec}_{count}"
            with _kline_tqsdk_lock:
                if _kline_tqsdk_cache.get(cache_key):
                    continue
            # v2.11.54+: 改用 TqKq 测试连接（auth=test）避免抢 iv_smile 真实账户连接名额
            api = TqApi(TqKq(), auth=TqAuth('test', 'test'), debug=False)
            try:
                klines = api.get_kline_serial(sym, period_sec, data_length=count)
                api.wait_update(deadline=_time_mod.time() + 5)
                yesterday_close = None
                try:
                    daily = api.get_kline_serial(sym, 86400, data_length=10)
                    if len(daily) >= 2:
                        prev_close = float(daily.iloc[-2]['close'])
                        if math.isfinite(prev_close) and prev_close > 0:
                            yesterday_close = prev_close
                except Exception:
                    pass
                data = []
                for _, row in klines.iterrows():
                    close = float(row['close']) if math.isfinite(row['close']) else None
                    if close is None or close == 0:
                        continue
                    data.append(_build_kline_bar(row, close, use_tqsdk=True))
                data.sort(key=lambda x: x['time'])
                last = data[-1] if data else {}
                current_price = _safe_val(last.get('close', 0), 0)
                if yesterday_close and yesterday_close > 0:
                    change = round(current_price - yesterday_close, 2)
                    change_pct = round((change / yesterday_close) * 100, 2)
                else:
                    change, change_pct = 0, 0
                _add_kline_changes(data)
                result = {
                    'symbol': 'TA', 'period': _kline_period_label(period_sec),
                    'data': data, 'current_price': round(current_price, 2),
                    'change': change, 'change_pct': change_pct,
                    'yesterday_close': yesterday_close, 'source': 'tqsdk',
                }
                with _kline_tqsdk_lock:
                    _kline_tqsdk_cache[cache_key] = {'result': result, 'ts': _time_mod.time()}
                app.logger.info(f'[K线预热] 完成 {sym} {period_sec}s count={count} last={current_price}')
            finally:
                try:
                    api.close()
                except Exception:
                    pass
        except Exception as e:
            app.logger.warning(f'[K线预热] 失败 {sym} {period_sec}s: {type(e).__name__}:{e}')
            _kline_tqsdk_failed = True
            _kline_tqsdk_failed_at = _time_mod.time()
            break
    _kline_tqsdk_warmed = True
    app.logger.info('[K线预热] 全部完成')


def _kline_period_label(period_sec: int) -> str:
    if period_sec < 60: return f'{period_sec}s'
    if period_sec < 3600: return f'{period_sec // 60}min'
    if period_sec < 86400: return f'{period_sec // 3600}h'
    if period_sec < 604800: return f'{period_sec // 86400}day'
    return f'{period_sec // 604800}week'


# 启动后延迟2秒预热，避免和server boot日志抢资源
def _kline_warmup_scheduler():
    import time as _t
    _t.sleep(2)
    try:
        _kline_warmup()
    except Exception as e:
        app.logger.warning(f'[K线预热] 线程异常: {e}')
threading.Thread(target=_kline_warmup_scheduler, daemon=True, name='kline-warmup').start()



@app.route('/api/kline/indicators')
def api_kline_indicators():
    """技术指标API - 支持周期自适应MACD参数"""
    period = request.args.get('period', '1min')
    symbol = request.args.get('symbol', 'TA0')
    
    # 获取用户指定的MACD参数（可选）
    user_fast = request.args.get('fast', type=int)
    user_slow = request.args.get('slow', type=int)
    user_signal = request.args.get('signal', type=int)
    auto_scale = request.args.get('auto_scale', 'false').lower() == 'true'
    
    try:
        # 获取K线数据
        period_code = period.replace('min', 'm') if 'min' in period else period
        df = ak.futures_zh_minute_sina(symbol=symbol, period=period_code)
        df.columns = [c.strip() for c in df.columns]
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.sort_values('datetime').tail(500).reset_index(drop=True)
        
        # 获取MACD参数（周期自适应或用户指定）
        macd_params = mmacd.get_macd_params_for_period(
            period,
            user_fast=user_fast,
            user_slow=user_slow,
            user_signal=user_signal,
            auto_scale=auto_scale
        )
        
        # 计算MACD
        close_series = df['close']
        dif, dea, macd_hist = mmacd.calculate_macd(
            close_series,
            fast=macd_params['fast'],
            slow=macd_params['slow'],
            signal=macd_params['signal']
        )
        
        # 计算面积
        summary = mmacd.get_macd_summary(macd_hist)
        
        # 获取最新值
        last_dif = float(dif.iloc[-1])
        last_dea = float(dea.iloc[-1])
        last_macd = float(macd_hist.iloc[-1])
        
        return jsonify({
            'success': True,
            'period': period,
            'symbol': symbol,
            'macd': {
                'fast': macd_params['fast'],
                'slow': macd_params['slow'],
                'signal': macd_params['signal'],
                'dif': round(last_dif, 4),
                'dea': round(last_dea, 4),
                'macd': round(last_macd, 4),
                'state': '多头' if last_macd > 0 else '空头',
                'positive_area': summary['positive_area'],
                'negative_area': summary['negative_area'],
                'area_ratio': summary['area_ratio']
            },
            'kdj': {
                'k_period': 9,
                'd_period': 3,
                'j_period': 3,
                'k_value': 65.2,
                'd_value': 58.7,
                'j_value': 78.1
            },
            'ma': {
                'ma5': round(float(df['close'].tail(5).mean()), 2),
                'ma10': round(float(df['close'].tail(10).mean()), 2),
                'ma20': round(float(df['close'].tail(20).mean()), 2)
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/kline/macd/all_periods')
def api_kline_macd_all_periods():
    """获取所有时间周期的MACD指标（周期自适应参数）"""
    symbol = request.args.get('symbol', 'TA0')
    
    # 获取用户指定的MACD参数（可选）
    user_fast = request.args.get('fast', type=int)
    user_slow = request.args.get('slow', type=int)
    user_signal = request.args.get('signal', type=int)
    auto_scale = request.args.get('auto_scale', 'false').lower() == 'true'
    
    try:
        # 获取1分钟原始数据
        df = ak.futures_zh_minute_sina(symbol=symbol, period='1m')
        df.columns = [c.strip() for c in df.columns]
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.sort_values('datetime').tail(2000).reset_index(drop=True)
        
        # 获取所有周期的MACD
        results = {}
        for period in ['1min', '5min', '15min', '30min', '60min']:
            try:
                # 获取该周期的MACD参数
                macd_params = mmacd.get_macd_params_for_period(
                    period,
                    user_fast=user_fast,
                    user_slow=user_slow,
                    user_signal=user_signal,
                    auto_scale=auto_scale
                )
                
                # 分析该周期MACD
                result = mmacd.analyze_macd_for_period(
                    df, period,
                    fast=macd_params['fast'],
                    slow=macd_params['slow'],
                    signal=macd_params['signal']
                )
                results[period] = {
                    'success': True,
                    **result
                }
            except Exception as e:
                results[period] = {'success': False, 'error': str(e)}
        
        return jsonify({
            'success': True,
            'symbol': symbol,
            'periods': results
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})


# ==================== 启动应用 ====================

# ==================== 缠论分析 API ====================
from core import chan_core_wrapper as cw
from analysis import option_chain_api as oca

@app.route('/api/chan/analysis')
def api_chan_analysis():
    """缠论完整分析API - 使用 chan_core 引擎
    
    参数:
        period: K线周期 ('1min', '5min', '15min', '30min', '60min', '1day')
        macd_algo: MACD算法 ('area', 'peak', 'slope', 'amp', 'diff', 'half')
        divergence_rate: 背驰比率阈值 (默认inf表示不限制)
        max_bs2_rate: 2买回落比率上限 (默认0.9999)
    """
    period = request.args.get('period', '1min')
    
    # 获取买卖点配置参数
    macd_algo = request.args.get('macd_algo', 'area')
    divergence_rate = request.args.get('divergence_rate', type=float)  # None表示默认
    max_bs2_rate = request.args.get('max_bs2_rate', type=float)  # None表示默认
    
    # 构建bs_config
    bs_config = {}
    if macd_algo:
        bs_config['macd_algo'] = macd_algo
    if divergence_rate is not None:
        bs_config['divergence_rate'] = divergence_rate
    if max_bs2_rate is not None:
        bs_config['max_bs2_rate'] = max_bs2_rate
    
    try:
        result = cw.get_chan_result(period, **bs_config)
        return jsonify(result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'period': period})


@app.route('/api/chan_advanced')
def api_chan_advanced():
    """缠论高级分析API - 支持自定义买卖点配置参数
    
    参数:
        period: K线周期 ('1min', '5min', '15min', '30min', '60min', '1day')
        macd_algo: MACD算法 ('area', 'peak', 'slope', 'amp', 'diff', 'half')
        divergence_rate: 背驰比率阈值 (默认inf表示不限制)
        max_bs2_rate: 2买回落比率上限 (默认0.9999)
        
    返回:
        包含完整分析结果的字典
    """
    period = request.args.get('period', '1min')
    
    # 获取买卖点配置参数
    macd_algo = request.args.get('macd_algo', 'area')
    divergence_rate = request.args.get('divergence_rate', type=float)
    max_bs2_rate = request.args.get('max_bs2_rate', type=float)
    
    # 构建bs_config
    bs_config = {}
    if macd_algo:
        bs_config['macd_algo'] = macd_algo
    if divergence_rate is not None:
        bs_config['divergence_rate'] = divergence_rate
    if max_bs2_rate is not None:
        bs_config['max_bs2_rate'] = max_bs2_rate
    
    try:
        result = cw.get_chan_result(period, **bs_config)
        
        # 转换为前端期望的格式
        stats = result.get('stats', {})
        bi_data = result.get('bi_markline', [])
        seg_data = result.get('seg_markline', [])
        zs_data = result.get('zs_data', [])
        bs_data = result.get('bs_data', [])
        
        # 构建 signals 格式
        signals = []
        for bp in bs_data:
            sig_type = 'buy' if 'buy' in bp.get('type', '') else 'sell'
            signals.append({
                'type': sig_type,
                'text': f"{bp.get('type', '').upper()} @{bp.get('yAxis', 0):.2f}",
                'time': result.get('klines', [{}])[bp.get('xAxis', 0)].get('time', '') if bp.get('xAxis', 0) < len(result.get('klines', [])) else '',
                'price': bp.get('yAxis', 0)
            })
        
        # 构建 bi_list 格式
        bi_list = []
        for bi in bi_data:
            bi_list.append({
                'idx': bi.get('idx', 0),
                'dir': bi.get('dir', ''),
                'begin_idx': bi.get('xAxis', 0),
                'end_idx': bi.get('xAxis2', 0),
                'begin_price': bi.get('yAxis', 0),
                'end_price': bi.get('yAxis2', 0),
                'is_sure': True
            })
        
        # 构建 xd_list 格式
        xd_list = []
        for seg in seg_data:
            xd_list.append({
                'idx': seg.get('idx', 0),
                'dir': seg.get('dir', ''),
                'begin_idx': seg.get('xAxis', 0),
                'end_idx': seg.get('xAxis2', 0),
                'begin_price': seg.get('yAxis', 0),
                'end_price': seg.get('yAxis2', 0)
            })
        
        # 返回前端期望的格式
        return jsonify({
            'success': True,
            'period': period,
            'klines': result.get('klines', []),  # K线数据
            'bi_count': stats.get('bi_count', 0),
            'xd_count': stats.get('seg_count', 0),
            'zhongshu_count': stats.get('zs_count', 0),
            'bs_count': stats.get('bs_count', 0),
            'current_price': stats.get('current_price', 0),
            'last_time': stats.get('last_time', ''),
            'signals': signals,
            'bi_list': bi_list,
            'xd_list': xd_list,
            'bs_config': result.get('bs_config', {}),
            'analysis': {
                'bi_markline': bi_data,
                'seg_markline': seg_data,
                'zs_data': zs_data,
                'bs_data': bs_data
            }
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'period': period})


@app.route('/api/contracts/list')
def api_contracts_list():
    """获取所有可交易期货合约列表（按交易所/品种分组）"""
    import akshare as ak
    try:
        all_contracts = {}
        
        # CZCE 郑商所（ PTA、甲醇、短纤等）
        try:
            czce_df = ak.futures_contract_info_czce()
            for _, row in czce_df.iterrows():
                product = str(row.get('产品名称', '')).strip()
                code = str(row.get('合约代码', '')).strip()
                if not code or not product:
                    continue
                if product not in all_contracts:
                    all_contracts[product] = []
                all_contracts[product].append(code)
        except Exception as e:
            print(f"CZCE fetch error: {e}")
        
        # DCE 大商所
        try:
            dce_df = ak.futures_contract_info_dce()
            for _, row in dce_df.iterrows():
                product = str(row.get('产品名称', '')).strip()
                code = str(row.get('合约代码', '')).strip()
                if not code or not product:
                    continue
                if product not in all_contracts:
                    all_contracts[product] = []
                all_contracts[product].append(code)
        except Exception as e:
            print(f"DCE fetch error: {e}")
        
        # SHFE 上期所
        try:
            shfe_df = ak.futures_contract_info_shfe()
            for _, row in shfe_df.iterrows():
                product = str(row.get('产品名称', '')).strip()
                code = str(row.get('合约代码', '')).strip()
                if not code or not product:
                    continue
                if product not in all_contracts:
                    all_contracts[product] = []
                all_contracts[product].append(code)
        except Exception as e:
            print(f"SHFE fetch error: {e}")
        
        # 构建前端需要的扁平列表
        result = []
        for product, codes in sorted(all_contracts.items()):
            # 去重 + 排序（按合约代码数字部分排序）
            seen = set()
            unique_codes = []
            for c in codes:
                if c not in seen:
                    seen.add(c)
                    unique_codes.append(c)
            unique_codes.sort()
            for code in unique_codes:
                result.append({'code': code, 'name': product})
        
        return jsonify({'success': True, 'contracts': result})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(e), 'contracts': []})


# ==================== 波动率锥 API（集成自 indicators/volatility_api.py） ====================

@app.route('/api/volatility/cone', methods=['GET'])
def api_volatility_cone():
    """获取波动锥数据"""
    cached = _get_vol_cache('volatility_cone')
    if cached:
        return jsonify(cached)
    try:
        pta_data = load_pta_data()
        if pta_data is None:
            return jsonify({'success': False, 'error': '无法加载PTA数据'}), 500
        df_hv = calculate_all_hv_windows(pta_data)
        cone_data = generate_volatility_cone_data(df_hv)
        if cone_data is None:
            return jsonify({'success': False, 'error': '无法生成波动锥数据'}), 500
        windows, stats_data = [], []
        for window, stats in cone_data.items():
            windows.append(window)
            stats_data.append({
                'window': window, 'current': stats['current'], 'mean': stats['mean'],
                'median': stats['median'], 'min': stats['min'], 'max': stats['max'],
                'q1': stats['q1'], 'q3': stats['q3'], 'std': stats['std']
            })
        short = cone_data.get(20, {}).get('current')
        long  = cone_data.get(120, {}).get('current')
        ratio = round(short / long, 2) if short and long else None
        response = {
            'success': True,
            'timestamp': dt_datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'windows': windows, 'data': stats_data,
            'summary': {'short_term': short, 'long_term': long, 'volatility_ratio': ratio}
        }
        _set_vol_cache('volatility_cone', response)
        return jsonify(response)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/volatility/iv-percentile', methods=['GET'])
def api_iv_percentile():
    """获取IV百分位数据"""
    cached = _get_vol_cache('iv_percentile')
    if cached:
        return jsonify(cached)
    try:
        iv_data_dict = load_iv_data()
        iv_data = iv_data_dict.get('1min')
        if iv_data is None or len(iv_data) == 0:
            return jsonify({'success': False, 'error': '无法加载IV数据'}), 500
        latest_iv = iv_data[(iv_data['strike'] >= 6900) & (iv_data['strike'] <= 7100) & (iv_data['iv_pct'].notna())]
        if len(latest_iv) == 0:
            return jsonify({'success': False, 'error': '无法获取当前IV值'}), 500
        current_iv = latest_iv['iv_pct'].iloc[-1]
        percentile, stats = calculate_iv_percentile(iv_data, current_iv)
        if percentile is None:
            return jsonify({'success': False, 'error': '无法计算IV百分位'}), 500
        response = {
            'success': True,
            'timestamp': dt_datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'current_iv': current_iv, 'percentile': percentile, 'stats': stats,
            'interpretation': _iv_interpretation(percentile)
        }
        _set_vol_cache('iv_percentile', response)
        return jsonify(response)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/volatility/signals', methods=['GET'])
def api_volatility_signals():
    """获取波动率交易信号"""
    cached = _get_vol_cache('trading_signals')
    if cached:
        return jsonify(cached)
    try:
        cone_resp = api_volatility_cone().get_json()
        cone_data = None
        if cone_resp.get('success'):
            cone_data = {item['window']: {'current': item['current'], 'mean': item['mean'],
                                          'min': item['min'], 'max': item['max']}
                         for item in cone_resp['data']}
        iv_resp = api_iv_percentile().get_json()
        iv_pct  = iv_resp.get('percentile') if iv_resp.get('success') else None
        iv_stats = iv_resp.get('stats')     if iv_resp.get('success') else None
        signals  = generate_trading_signals(cone_data, iv_pct, iv_stats)
        response = {
            'success': True,
            'timestamp': dt_datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'signals': signals, 'count': len(signals)
        }
        _set_vol_cache('trading_signals', response)
        return jsonify(response)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/volatility/summary', methods=['GET'])
def api_volatility_summary():
    """获取波动率综合分析摘要"""
    results, errors = {}, []
    for key, fn in [('cone', api_volatility_cone), ('iv', api_iv_percentile), ('signals', api_volatility_signals)]:
        try:
            r = fn().get_json()
            results[key] = r if r.get('success') else None
            if not r.get('success'):
                errors.append(f"{key}: {r.get('error')}")
        except Exception as e:
            errors.append(f"{key}: {str(e)}")
    return jsonify({
        'success': len(errors) < 3,
        'timestamp': dt_datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'data': results, 'errors': errors if errors else None
    })


@app.route('/api/volatility/refresh', methods=['POST'])
def api_volatility_refresh():
    """刷新波动率缓存"""
    try:
        _volatility_cache.clear()
        _volatility_cache_time.clear()
        return jsonify({'success': True, 'message': '缓存已刷新',
                        'timestamp': dt_datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== 交易系统 API ==========

@app.route('/api/trading/backtest', methods=['POST'])
def api_trading_backtest():
    """运行回测"""
    import traceback
    try:
        req_data = request.get_json() or {}
        strategy_name = req_data.get('strategy', 'macd')
        symbol = req_data.get('symbol', 'TA609')
        period = req_data.get('period', '5min')
        count = min(req_data.get('count', 500), 2000)
        params = req_data.get('params', {})
        start_date = req_data.get('start_date')  # YYYY-MM-DD
        end_date = req_data.get('end_date')      # YYYY-MM-DD
        source = req_data.get('source', 'auto')  # tqsdk / akshare / auto

        app.logger.info(f"[回测] 开始 | strategy={strategy_name} symbol={symbol} period={period} count={count} source={source}")

        # 获取K线数据（直接调内部数据获取逻辑，不走HTTP）
        kline_data = _fetch_kline_data(symbol, period, count,
                                        start_date=start_date, end_date=end_date, source=source)

        if not kline_data:
            app.logger.error(f"[回测] K线数据为空 | symbol={symbol} period={period} source={source}")
            return jsonify({'success': False, 'error': f'无法获取K线数据（品种:{symbol} 周期:{period} 数据源:{source}），请尝试切换数据源或检查网络连接'}), 400

        app.logger.info(f"[回测] K线获取成功 | count={len(kline_data)}")

        ts = get_trading_system()
        result = ts.run_backtest(strategy_name, kline_data, params)

        # 把K线数据也返回给前端，用于绘制信号图表
        result['kline_data'] = kline_data

        # 将 trades 转换为前端期望的 trade_entries 格式（入场+出场拆成两条记录）
        trade_entries = []
        for t in result.get('trades', []):
            # 入场记录
            if t.get('entry_bar_index', -1) >= 0:
                trade_entries.append({
                    'type': 'entry',
                    'direction': t['direction'],
                    'price': t['entry_price'],
                    'bar_index': t['entry_bar_index'],
                    'stop_loss': t.get('stop_loss', 0),
                    'take_profit': t.get('take_profit', 0),
                    'exit_reason': '',  # 入场时还不知道出场原因，留空
                })
            # 出场记录
            if t.get('exit_bar_index', -1) >= 0:
                trade_entries.append({
                    'type': 'exit',
                    'direction': t['direction'],
                    'price': t['exit_price'],
                    'bar_index': t['exit_bar_index'],
                    'exit_reason': t.get('exit_reason', ''),
                    'pnl': t.get('pnl', 0),
                })
        result['trade_entries'] = trade_entries

        return jsonify({
            'success': True,
            'strategy': strategy_name,
            'symbol': symbol,
            'period': period,
            'data_count': len(kline_data),
            'result': result
        })
    except Exception as e:
        tb = traceback.format_exc()
        app.logger.error(f"[回测] 异常: {e}\n{tb}")
        return jsonify({'success': False, 'error': f'回测执行异常: {str(e)}'}), 500


@app.route('/api/trading/optimize', methods=['POST'])
def api_trading_optimize():
    """参数优化（网格搜索）"""
    try:
        req_data = request.get_json() or {}
        strategy_name = req_data.get('strategy', 'macd')
        symbol = req_data.get('symbol', 'TA609')
        period = req_data.get('period', '5min')
        count = min(req_data.get('count', 500), 2000)
        start_date = req_data.get('start_date')
        end_date = req_data.get('end_date')
        source = req_data.get('source', 'auto')
        
        # 参数网格定义
        param_grid_config = req_data.get('param_grid', {})
        if not param_grid_config:
            return jsonify({'success': False, 'error': '缺少参数网格定义 param_grid'}), 400
        
        # 目标指标和模式
        objective = req_data.get('objective', 'total_return')
        mode = req_data.get('mode', 'max')  # 'max' 或 'min'
        top_n = min(req_data.get('top_n', 5), 20)
        
        # 获取K线数据
        kline_data = _fetch_kline_data(symbol, period, count,
                                        start_date=start_date, end_date=end_date, source=source)
        if not kline_data:
            return jsonify({'success': False, 'error': '无K线数据'}), 400
        
        # 获取策略类
        ts = get_trading_system()
        strategy_class = ts.strategies.get(strategy_name)
        if not strategy_class:
            return jsonify({'success': False, 'error': f'未找到策略: {strategy_name}'}), 400
        
        # 执行优化
        from backtest import GridOptimizer, ParameterGrid, run_backtest_for_optimization
        
        grid = ParameterGrid(param_grid_config)
        optimizer = GridOptimizer(objective=objective, mode=mode, top_n=top_n)
        
        opt_result = optimizer.optimize(
            backtest_func=run_backtest_for_optimization,
            param_grid=grid,
            strategy_class=strategy_class,
            data=kline_data,
            fixed_params={},
            initial_balance=100000.0
        )
        
        # 补充 best_statistics 和 best_params（前端依赖这两个字段）
        if opt_result.get('top_results') and len(opt_result['top_results']) > 0:
            best = opt_result['top_results'][0]
            opt_result['best_statistics'] = best.get('statistics', {})
            opt_result['best_params'] = best.get('_params', {})
        
        return jsonify({
            'success': True,
            'strategy': strategy_name,
            'symbol': symbol,
            'period': period,
            'objective': objective,
            'mode': mode,
            'total_combinations': len(grid),
            'result': opt_result
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/trading/compare', methods=['POST'])
def api_trading_compare():
    """多策略对比"""
    try:
        req_data = request.get_json() or {}
        strategies = req_data.get('strategies', [])  # ['macd', 'kdj', 'rsi']
        symbol = req_data.get('symbol', 'TA609')
        period = req_data.get('period', '5min')
        count = min(req_data.get('count', 500), 2000)
        start_date = req_data.get('start_date')
        end_date = req_data.get('end_date')
        source = req_data.get('source', 'auto')
        
        if len(strategies) < 2:
            return jsonify({'success': False, 'error': '至少需要2个策略进行对比'}), 400
        
        # 获取K线数据
        kline_data = _fetch_kline_data(symbol, period, count,
                                        start_date=start_date, end_date=end_date, source=source)
        if not kline_data:
            return jsonify({'success': False, 'error': '无K线数据'}), 400
        
        # 获取策略类并创建实例
        ts = get_trading_system()
        strategy_instances = {}
        for name in strategies:
            strategy_class = ts.strategies.get(name)
            if strategy_class:
                strategy_instances[name] = strategy_class()
        
        if len(strategy_instances) < 2:
            return jsonify({'success': False, 'error': '有效的策略少于2个'}), 400
        
        # 执行对比
        from backtest import StrategyComparator
        comparator = StrategyComparator(initial_balance=100000.0)
        result = comparator.run_multiple_strategies(strategy_instances, kline_data)
        
        return jsonify({
            'success': True,
            'strategies': list(strategy_instances.keys()),
            'symbol': symbol,
            'period': period,
            'data_count': len(kline_data),
            'result': result
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/trading/export', methods=['POST'])
def api_trading_export():
    """导出回测报告"""
    try:
        req_data = request.get_json() or {}
        export_format = req_data.get('format', 'json')  # 'json', 'excel'
        result_data = req_data.get('result_data')
        
        if not result_data:
            return jsonify({'success': False, 'error': '缺少回测结果数据'}), 400
        
        from backtest import BacktestExporter
        
        exporter = BacktestExporter(result_data)
        
        if export_format == 'excel':
            # 返回 base64 编码的 Excel 文件
            import base64
            excel_bytes = exporter.to_excel(None)
            return jsonify({
                'success': True,
                'format': 'excel',
                'data': base64.b64encode(excel_bytes).decode('utf-8'),
                'filename': f"backtest_report_{dt_datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            })
        elif export_format == 'pdf':
            # 返回 base64 编码的 PDF 文件
            import base64
            import io
            buffer = io.BytesIO()
            exporter.to_pdf_buffer(buffer)
            buffer.seek(0)
            return jsonify({
                'success': True,
                'format': 'pdf',
                'data': base64.b64encode(buffer.getvalue()).decode('utf-8'),
                'filename': f"backtest_report_{dt_datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            })
        else:
            # 返回 JSON
            return jsonify({
                'success': True,
                'format': 'json',
                'data': exporter.to_dict()
            })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/trading/walkforward', methods=['POST'])
def api_trading_walkforward():
    """Walk-Forward 滚动验证（防止过拟合）"""
    try:
        req_data = request.get_json() or {}
        strategy_name = req_data.get('strategy', 'macd')
        symbol = req_data.get('symbol', 'TA609')
        period = req_data.get('period', '5min')
        count = min(req_data.get('count', 500), 2000)
        start_date = req_data.get('start_date')
        end_date = req_data.get('end_date')
        source = req_data.get('source', 'auto')

        # Walk-Forward 参数
        train_window = max(req_data.get('train_window', 240), 30)
        test_window = max(req_data.get('test_window', 60), 10)
        step = max(req_data.get('step', 60), 10)
        top_n = min(req_data.get('top_n', 5), 20)
        objective = req_data.get('objective', 'total_return')
        mode = req_data.get('mode', 'max')

        # 参数网格
        param_grid_config = req_data.get('param_grid', {})
        if not param_grid_config:
            return jsonify({'success': False, 'error': '缺少 param_grid'}), 400

        app.logger.info(f"[WF] 开始 | strategy={strategy_name} train={train_window} test={test_window} step={step}")

        # 获取K线
        kline_data = _fetch_kline_data(symbol, period, count,
                                       start_date=start_date, end_date=end_date, source=source)
        if not kline_data:
            return jsonify({'success': False, 'error': '无K线数据'}), 400

        if len(kline_data) < train_window + test_window:
            return jsonify({'success': False,
                            'error': f'数据不足（{len(kline_data)}根），需要至少 train_window({train_window}) + test_window({test_window})'}), 400

        ts = get_trading_system()
        strategy_class = ts.strategies.get(strategy_name)
        if not strategy_class:
            return jsonify({'success': False, 'error': f'未找到策略: {strategy_name}'}), 400

        # 执行 Walk-Forward
        from backtest import WalkForwardAnalyzer, WalkForwardConfig
        from backtest.optimizer_extension import run_backtest_for_optimization

        config = WalkForwardConfig(
            train_window=train_window,
            test_window=test_window,
            step=step,
            top_n=top_n,
            objective=objective,
            mode=mode,
        )
        analyzer = WalkForwardAnalyzer(config)
        wf_result = analyzer.run(
            strategy_class=strategy_class,
            data=kline_data,
            param_grid=param_grid_config,
            backtest_func=run_backtest_for_optimization,
            initial_balance=100000.0,
        )

        # 序列化结果
        rounds_data = []
        for r in wf_result.rounds:
            rounds_data.append({
                'round_index': r.round_index,
                'train_start': r.train_start,
                'train_end': r.train_end,
                'test_start': r.test_start,
                'test_end': r.test_end,
                'best_params': r.best_params,
                'train_stats': r.train_stats,
                'test_stats': r.test_stats,
                'train_score': r.train_score,
                'test_score': r.test_score,
                'degradation': r.degradation,
                'degradation_pct': r.degradation_pct,
            })

        return jsonify({
            'success': True,
            'strategy': strategy_name,
            'data_count': len(kline_data),
            'config': {
                'train_window': train_window,
                'test_window': test_window,
                'step': step,
                'top_n': top_n,
                'objective': objective,
            },
            'result': {
                'rounds': rounds_data,
                'train_degradation_avg': wf_result.train_degradation_avg,
                'test_score_avg': wf_result.test_score_avg,
                'train_score_avg': wf_result.train_score_avg,
                'is_robust': wf_result.is_robust,
                'consistency': wf_result.consistency,
                'conclusion': wf_result.conclusion,
            }
        })

    except Exception as e:
        import traceback
        app.logger.error(f"[WF] 异常: {e}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/trading/montecarlo', methods=['POST'])
def api_trading_montecarlo():
    """Monte Carlo 模拟（策略稳健性验证）"""
    try:
        req_data = request.get_json() or {}
        strategy_name = req_data.get('strategy', 'macd')
        symbol = req_data.get('symbol', 'TA609')
        period = req_data.get('period', '5min')
        count = min(req_data.get('count', 500), 2000)
        start_date = req_data.get('start_date')
        end_date = req_data.get('end_date')
        source = req_data.get('source', 'auto')
        n_simulations = min(req_data.get('n_simulations', 1000), 5000)

        app.logger.info(f"[MC] 开始 | strategy={strategy_name} simulations={n_simulations}")

        # 先跑一次回测获取交易记录
        kline_data = _fetch_kline_data(symbol, period, count,
                                       start_date=start_date, end_date=end_date, source=source)
        if not kline_data:
            return jsonify({'success': False, 'error': '无K线数据'}), 400

        ts = get_trading_system()
        strategy_class = ts.strategies.get(strategy_name)
        if not strategy_class:
            return jsonify({'success': False, 'error': f'未找到策略: {strategy_name}'}), 400

        result = ts.run_backtest(strategy_name, kline_data, {})
        trades = result.get('trades', [])

        if len(trades) < 10:
            return jsonify({'success': False,
                            'error': f'交易次数不足（{len(trades)}笔），Monte Carlo 需要至少10笔交易'}), 400

        from backtest import run_monte_carlo, MonteCarloConfig
        config = MonteCarloConfig(n_simulations=n_simulations)
        mc_result = run_monte_carlo(trades, initial_balance=100000.0, config=config)

        return jsonify({
            'success': True,
            'strategy': strategy_name,
            'trade_count': len(trades),
            'n_simulations': n_simulations,
            'result': {
                'p5_final_balance': round(mc_result.p5_final_balance, 2),
                'p25_final_balance': round(mc_result.p25_final_balance, 2),
                'p50_final_balance': round(mc_result.p50_final_balance, 2),
                'p75_final_balance': round(mc_result.p75_final_balance, 2),
                'p95_final_balance': round(mc_result.p95_final_balance, 2),
                'p5_max_drawdown': round(mc_result.p5_max_drawdown, 2),
                'p95_max_drawdown': round(mc_result.p95_max_drawdown, 2),
                'probability_of_ruin': round(mc_result.probability_of_ruin, 4),
                'sharpe_ratios_summary': {
                    'mean': round(sum(mc_result.sharpe_ratios) / len(mc_result.sharpe_ratios), 4),
                    'min': round(min(mc_result.sharpe_ratios), 4),
                    'max': round(max(mc_result.sharpe_ratios), 4),
                },
                'final_balance_pcts': [round(p, 2) for p in mc_result.final_balance_pcts[:100]],  # 限制返回量
            }
        })

    except Exception as e:
        import traceback
        app.logger.error(f"[MC] 异常: {e}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/trading/strategies', methods=['GET'])
def api_trading_strategies():
    """获取可用策略列表"""
    ts = get_trading_system()
    return jsonify({
        'success': True,
        'strategies': list(ts.strategies.keys())
    })


@app.route('/api/trading/order', methods=['POST'])
def api_trading_order():
    """提交订单"""
    try:
        data = request.get_json() or {}
        symbol = data.get('symbol', 'TA609')
        side = data.get('side', 'buy')
        quantity = int(data.get('quantity', 1))
        order_type = data.get('type', 'market')
        price = data.get('price')
        stop_price = data.get('stop_price')

        ts = get_trading_system()
        order = ts.submit_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            price=price,
            stop_price=stop_price
        )

        return jsonify({
            'success': True,
            'order': order.to_dict()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/trading/order/<order_id>', methods=['DELETE'])
def api_trading_cancel_order(order_id):
    """取消订单"""
    try:
        ts = get_trading_system()
        order = ts.order_manager.get_order(order_id)
        if not order:
            return jsonify({'success': False, 'error': '订单不存在'}), 404
        ts.trade_executor.cancel_order(order_id)
        return jsonify({'success': True, 'order_id': order_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/trading/orders', methods=['GET'])
def api_trading_orders():
    """获取订单列表"""
    try:
        ts = get_trading_system()
        return jsonify({
            'success': True,
            **ts.get_orders()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/trading/positions', methods=['GET'])
def api_trading_positions():
    """获取持仓"""
    try:
        ts = get_trading_system()
        return jsonify({
            'success': True,
            'positions': ts.get_positions()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/trading/account', methods=['GET'])
def api_trading_account():
    """获取账户状态"""
    try:
        ts = get_trading_system()
        return jsonify({
            'success': True,
            **ts.get_account_status()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# IV Smile 隐波微笑曲线模块 - 注册路由到主 app
iv_smile_service.register_routes(app)

if __name__ == '__main__':
    init_db()

    # 初始化 IV Smile 服务（TqSdk 线程 + 调度器，内部自愈重连）
    import threading
    iv_smile_service._state['running'] = True
    tqsdk_t = threading.Thread(target=iv_smile_service.tqsdk_loop, daemon=True)
    tqsdk_t.start()
    print("[iv_smile] TqSdk线程已启动（内部自愈重连已启用）")

    # 调度器也立即启动，data_ready后compute_once会自动生效
    iv_smile_service.start_scheduler(interval_minutes=1)

    # 预热期权链缓存（后台，提前触发首次计算，避免第一个用户请求卡住）
    def prewarm_option_chain():
        import time
        time.sleep(3)  # 等服务完全启动
        try:
            from analysis.option_chain_api import get_option_api
            api = get_option_api()
            result = api.get_full_chain()
            print(f"[option_chain] 预热完成: {'成功' if result.get('success') else '失败 - ' + str(result.get('error', ''))}")
        except Exception as e:
            print(f"[option_chain] 预热失败: {e}")

    pt = threading.Thread(target=prewarm_option_chain, daemon=True)
    pt.start()

    # 策略研报独立周期调度：整 15 分钟主动刷新，不依赖浏览器访问
    srt = threading.Thread(target=_strategy_report_periodic_scheduler, kwargs={'interval_minutes': 15}, daemon=True, name='strategy-report-periodic')
    srt.start()

    app.run(host='0.0.0.0', port=8424, debug=False, threaded=True)
else:
    # gunicorn / uwsgi 等 WSGI 服务器启动时初始化数据库
    with app.app_context():
        init_db()
        # IV Smile 服务初始化（WSGI 模式下启动 TqSdk 线程）
        import threading
        iv_smile_service._state['running'] = True
        tqsdk_t = threading.Thread(target=iv_smile_service.tqsdk_loop, daemon=True)
        tqsdk_t.start()
        print("[iv_smile] WSGI模式：TqSdk线程已启动（内部自愈重连已启用）")
        # 调度器立即启动，data_ready后compute_once自动生效
        iv_smile_service.start_scheduler(interval_minutes=1)
        # 策略研报独立周期调度（WSGI 模式同样启用）
        srt = threading.Thread(target=_strategy_report_periodic_scheduler, kwargs={'interval_minutes': 15}, daemon=True, name='strategy-report-periodic')
        srt.start()

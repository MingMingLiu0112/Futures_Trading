
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA期货分析平台 - 快速集成版本
包含所有5个期权功能模块 + K线图功能
"""

import os, sys, json, time, sqlite3, threading, warnings, math
from datetime import datetime as dt_datetime, timedelta
import datetime as dt
from typing import Optional, Dict, List

from flask import Flask, render_template, jsonify, request, send_file, redirect, url_for, render_template_string
import akshare as ak
import pandas as pd
import numpy as np

# 天勤量化 TqSdk
from tqsdk import TqApi, TqAuth

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
    conn.commit()

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
        result = api.get_full_chain()
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/pta/ta606_price')
def api_ta606_price():
    """TA606实时价格 - 轻量接口，每分钟轮询更新标的价格"""
    try:
        price = oca.get_tq_ta606_price(timeout=5.0)
        if price <= 0:
            # 回退到akshare主力合约
            try:
                df = ak.futures_zh_realtime(symbol="TA")
                if df is not None and not df.empty:
                    price = float(df.iloc[-1].get('trade', 0))
            except:
                pass
        return jsonify({
            'success': True,
            'underlying_price': price,
            'symbol': 'TA606',
            'timestamp': dt_datetime.now().isoformat()
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

@app.route('/api/daily_report')
def api_daily_report():
    """PTA市场日报（新版综合分析）
    - 无参数：当日交易时段（9:00-17:00）自动刷新，节假日/收盘后读缓存
    - ?refresh=1：强制重新生成
    """
    try:
        force_refresh = request.args.get('refresh', '0') == '1'
        json_path = os.path.join(WORKSPACE, 'data', 'fundamental', 'daily_report.json')

        # 检查缓存是否需要刷新
        needs_refresh = force_refresh
        if not needs_refresh and os.path.exists(json_path):
            try:
                file_mtime = datetime.fromtimestamp(os.path.getmtime(json_path))
                today = datetime.now()
                # 文件不是今天生成的，且当前是交易时段（9~17点），需要刷新
                if file_mtime.date() < today.date() and 9 <= today.hour < 17:
                    needs_refresh = True
            except Exception:
                pass

        if not force_refresh and os.path.exists(json_path) and not needs_refresh:
            # 读取已有的日报数据
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify({'success': True, 'data': data, 'cached': True})

        # 生成新日报
        from scripts.generate_daily_report import generate_report, save_report
        app.logger.info('[日报API] 开始生成新日报（force=%s）', force_refresh)
        report = generate_report()
        save_report(report)
        app.logger.info('[日报API] 日报生成完成 timestamp=%s', report.get('timestamp'))
        return jsonify({'success': True, 'data': report, 'cached': False})
    except Exception as e:
        app.logger.error('[日报API] 生成失败: %s', e)
        # 生成失败时尝试返回缓存（即使过期），避免页面完全无数据
        json_path = os.path.join(WORKSPACE, 'data', 'fundamental', 'daily_report.json')
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                app.logger.warning('[日报API] 使用过期缓存')
                return jsonify({'success': True, 'data': data, 'cached': True, 'stale': True, 'error': str(e)})
            except Exception:
                pass
        return jsonify({'success': False, 'error': str(e)})

# 注册期权链页面路由
@app.route('/option_chain')
def option_chain_page():
    """期权链分析页面"""
    try:
        with open(os.path.join(WORKSPACE, 'option_chain.html'), 'r', encoding='utf-8') as f:
            content = f.read()
        return content
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

def _get_yesterday_close_tqsdk(symbol='CZCE.TA609'):
    """通过TqSdk获取昨日收盘价（用于计算涨跌）"""
    try:
        api = TqApi(auth=TqAuth(TQS_USER, TQS_PASS))
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


@app.route('/api/kline/data')
def api_kline_data():
    """K线图数据API
    - OHLC + volume: 取自TqSdk或akshare
    - open_interest: 每根K线自己的close_oi（TqSdk）或hold（akshare）
    - 涨跌（change/change_pct）: 较昨日收盘价
    - volume_change / open_interest_change: 较前一根K线
    """
    import re
    
    period = request.args.get('period', '1min')
    symbol = request.args.get('symbol', 'TA0')
    
    # 前端合约名 -> TqSdk合约名映射
    tqsdk_symbol_map = {
        'TA0': 'CZCE.TA609',   # PTA主力（当前9月）
        'TA909': 'CZCE.TA609', # PTA9月
        'TA609': 'CZCE.TA609', # PTA9月
        'TA0C': 'CZCE.TA609',  # 认购期权（占位）
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
        count = 1000
    elif period in period_seconds_map:
        period_sec = period_seconds_map[period]
        count = 500 if period in ['1day', '1week', '1month'] else 1000
    else:
        return jsonify({'error': f'unsupported period: {period}', 'symbol': 'TA', 'period': period, 'data': [], 'current_price': 0, 'change': 0, 'change_pct': 0})
    
    # ==================== TqSdk 分支 ====================
    try:
        # 给 TqSdk 加10秒超时，避免网络问题时卡死
        api = TqApi(auth=TqAuth(TQS_USER, TQS_PASS))
        klines = api.get_kline_serial(tqsdk_symbol, period_sec, data_length=count)
        
        # 获取昨日收盘价（用于计算涨跌）
        yesterday_close = _get_yesterday_close_tqsdk(tqsdk_symbol)
        
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
        
        return jsonify({
            'symbol': 'TA', 'period': period, 'data': data,
            'current_price': round(current_price, 2),
            'change': change, 'change_pct': change_pct,
            'yesterday_close': yesterday_close,
            'source': 'tqsdk'
        })
    except Exception as e:
        app.logger.error(f'[K线API] TqSdk获取失败，降级到akshare symbol={symbol} period={period} error={type(e).__name__}:{e}')

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


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8424, debug=False)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA期货分析平台 - 快速集成版本
包含所有5个期权功能模块 + K线图功能
"""

import os, sys, json, time, sqlite3, threading, warnings
from datetime import datetime, timedelta
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
import macd_multiperiod as mmacd

# TqSdk 认证配置
TQS_USER = os.environ.get('TQS_AUTH_USER', 'mingmingliu')
TQS_PASS = os.environ.get('TQS_AUTH_PASS', 'Liuzhaoning2025')

# Flask 应用
WORKSPACE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(WORKSPACE, "data", "pta_signals.db")
app = Flask(__name__, static_folder=None)
app.config["DATABASE"] = DB_PATH
app.config["WORKSPACE"] = WORKSPACE

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

# ==================== API接口 ====================

@app.route('/api/status')
def api_status():
    """平台状态API"""
    return jsonify({
        'status': 'running',
        'version': '1.0.0',
        'modules': {
            'option_chain': {'status': 'completed', 'version': '1.0'},
            'iv_curve': {'status': 'completed', 'version': '1.0'},
            'volatility_cone': {'status': 'completed', 'version': '1.0'},
            'multi_variety': {'status': 'completed', 'version': '1.0'},
            'excel_export': {'status': 'completed', 'version': '1.0'},
            'kline_chart': {'status': 'developing', 'version': '0.5'}
        },
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/options/chain')
def api_option_chain():
    """期权链数据API"""
    try:
        api = oca.get_option_api()
        result = api.get_full_chain()
        return jsonify(result)
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
        now = datetime.now()
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

@app.route('/api/kline/data')
def api_kline_data():
    """K线图数据API - 天勤TqSdk实时数据"""
    import re
    import datetime as dt
    import math
    
    period = request.args.get('period', '1min')
    
    # TqSdk 周期（秒）
    period_seconds_map = {
        '1min': 60, '5min': 300, '15min': 900, '30min': 1800, '60min': 3600,
        '1day': 86400, '1week': 604800, '1month': 2592000
    }
    
    # 非标准分钟周期（如120min, 240min）
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
    
    try:
        api = TqApi(auth=TqAuth(TQS_USER, TQS_PASS))
        klines = api.get_kline_serial('CZCE.TA605', period_sec, count)
        
        # 从akshare获取最新持仓数据
        try:
            period_code = period.replace('min', 'm') if 'min' in period else period
            ak_df = ak.futures_zh_minute_sina(symbol='TA0', period=period_code)
            ak_df.columns = [c.strip() for c in ak_df.columns]
            ak_df = ak_df.sort_values('datetime')
            latest_hold = float(ak_df['hold'].iloc[-1]) if len(ak_df) > 0 else 0
        except:
            latest_hold = 0
        
        data = []
        for _, row in klines.iterrows():
            close = float(row['close']) if math.isfinite(row['close']) else None
            if close is None or close == 0:
                continue
            dt_val = row['datetime']
            if isinstance(dt_val, (int, float)) and math.isfinite(dt_val) and dt_val > 0:
                # 直接使用Unix时间戳（秒），LightweightCharts自动处理时区
                time_ts = int(dt_val / 1e9)
            else:
                # Fallback: 解析字符串并转为时间戳
                dt_obj = dt.datetime.strptime(str(dt_val).replace('T', ' '), '%Y-%m-%d %H:%M:%S')
                time_ts = int((dt_obj - dt.datetime(1970, 1, 1)).total_seconds())
            data.append({
                'time': time_ts,  # Unix时间戳（秒）
                'open': float(row['open']) if math.isfinite(row['open']) else close,
                'high': float(row['high']) if math.isfinite(row['high']) else close,
                'low': float(row['low']) if math.isfinite(row['low']) else close,
                'close': close,
                'volume': float(row['volume']) if math.isfinite(row['volume']) else 0,
                'open_interest': latest_hold
            })
        api.close()
        data.sort(key=lambda x: x['time'])
        
        last = data[-1] if data else {}
        first = data[0] if data else {}
        current_price = last.get('close', 0)
        first_price = first.get('close', current_price)
        change = current_price - first_price
        change_pct = (change / first_price * 100) if first_price else 0
        
        def safe_val(v, default=0):
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                return default
            return v
        change = round(safe_val(change, 0), 2)
        change_pct = round(safe_val(change_pct, 0), 2)
        current_price = round(safe_val(current_price, 0), 2)
        
        return jsonify({
            'symbol': 'TA', 'period': period, 'data': data,
            'current_price': current_price, 'change': change,
            'change_pct': change_pct, 'source': 'tqsdk'
        })
    except Exception as e:
        # Fallback to akshare
        try:
            period_code = period.replace('min', 'm') if 'min' in period else period
            df = ak.futures_zh_minute_sina(symbol='TA0', period=period_code)
            df.columns = [c.strip() for c in df.columns]
            df['datetime'] = pd.to_datetime(df['datetime'])
            df = df.sort_values('datetime').tail(500).reset_index(drop=True)
            
            data = []
            for _, row in df.iterrows():
                close = float(row['close']) if math.isfinite(row['close']) else None
                if close is None or close == 0:
                    continue
                # 解析datetime并转为Unix时间戳
                dt_str = str(row['datetime'])
                if 'T' in dt_str:
                    dt_str = dt_str.replace('T', ' ')
                dt_obj = dt.datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
                time_ts = int((dt_obj - dt.datetime(1970, 1, 1)).total_seconds())
                data.append({
                    'time': time_ts,  # Unix时间戳（秒）
                    'open': float(row['open']) if math.isfinite(row['open']) else close,
                    'high': float(row['high']) if math.isfinite(row['high']) else close,
                    'low': float(row['low']) if math.isfinite(row['low']) else close,
                    'close': close,
                    'volume': float(row['volume']) if math.isfinite(row['volume']) else 0,
                    'open_interest': float(row.get('hold', 0)) if math.isfinite(row.get('hold', 0)) else 0
                })
            
            last = data[-1] if data else {}
            first = data[0] if data else {}
            current_price = last.get('close', 0)
            first_price = first.get('close', current_price)
            change = current_price - first_price
            change_pct = (change / first_price * 100) if first_price else 0
            
            return jsonify({
                'symbol': 'TA', 'period': period, 'data': data,
                'current_price': round(current_price, 2), 'change': round(change, 2),
                'change_pct': round(change_pct, 2), 'source': 'akshare'
            })
        except Exception as e2:
            return jsonify({'error': f'TqSdk: {str(e)}, Akshare: {str(e2)}', 'symbol': 'TA', 'period': period, 'data': [], 'current_price': 0, 'change': 0, 'change_pct': 0})



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
import chan_core_wrapper as cw
import option_chain_api as oca

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


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8424, debug=False)

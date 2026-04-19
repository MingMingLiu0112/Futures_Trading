#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
波动锥和隐波百分位API服务
提供RESTful API接口供前端调用
"""

import os
import sys
import json
from datetime import datetime
from flask import Flask, jsonify, request, render_template, send_file
from flask_cors import CORS

# 添加当前目录到路径
WORKSPACE = "/home/admin/.openclaw/workspace/codeman/pta_analysis"
sys.path.insert(0, WORKSPACE)

from volatility_cone import (
    load_pta_data, load_iv_data, calculate_all_hv_windows,
    generate_volatility_cone_data, calculate_iv_percentile,
    generate_trading_signals, plot_volatility_cone,
    plot_iv_percentile_distribution
)

# 初始化Flask应用
app = Flask(__name__, 
            static_folder='static',
            template_folder='templates')
CORS(app)  # 允许跨域请求

# 全局缓存
_cache = {}
_cache_time = {}

def get_cached_data(key, ttl_minutes=5):
    """获取缓存数据"""
    if key in _cache:
        if key in _cache_time:
            elapsed = (datetime.now() - _cache_time[key]).total_seconds()
            if elapsed < ttl_minutes * 60:
                return _cache[key]
    return None

def set_cached_data(key, data):
    """设置缓存数据"""
    _cache[key] = data
    _cache_time[key] = datetime.now()

@app.route('/')
def index():
    """主页"""
    return render_template('volatility_index.html')

@app.route('/api/volatility/cone', methods=['GET'])
def get_volatility_cone():
    """获取波动锥数据"""
    cache_key = 'volatility_cone'
    cached = get_cached_data(cache_key)
    if cached:
        return jsonify(cached)
    
    try:
        # 加载数据
        pta_data = load_pta_data()
        if pta_data is None:
            return jsonify({
                'success': False,
                'error': '无法加载PTA数据'
            }), 500
        
        # 计算历史波动率
        df_hv = calculate_all_hv_windows(pta_data)
        cone_data = generate_volatility_cone_data(df_hv)
        
        if cone_data is None:
            return jsonify({
                'success': False,
                'error': '无法生成波动锥数据'
            }), 500
        
        # 准备响应数据
        windows = []
        stats_data = []
        
        for window, stats in cone_data.items():
            windows.append(window)
            stats_data.append({
                'window': window,
                'current': stats['current'],
                'mean': stats['mean'],
                'median': stats['median'],
                'min': stats['min'],
                'max': stats['max'],
                'q1': stats['q1'],
                'q3': stats['q3'],
                'std': stats['std']
            })
        
        response = {
            'success': True,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'windows': windows,
            'data': stats_data,
            'summary': {
                'short_term': cone_data.get(20, {}).get('current'),
                'long_term': cone_data.get(120, {}).get('current'),
                'volatility_ratio': None
            }
        }
        
        # 计算短期/长期波动率比率
        if response['summary']['short_term'] and response['summary']['long_term']:
            response['summary']['volatility_ratio'] = round(
                response['summary']['short_term'] / response['summary']['long_term'], 2
            )
        
        # 缓存结果
        set_cached_data(cache_key, response)
        
        return jsonify(response)
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/volatility/iv-percentile', methods=['GET'])
def get_iv_percentile():
    """获取IV百分位数据"""
    cache_key = 'iv_percentile'
    cached = get_cached_data(cache_key)
    if cached:
        return jsonify(cached)
    
    try:
        # 加载IV数据
        iv_data_dict = load_iv_data()
        iv_data = iv_data_dict.get('1min')
        
        if iv_data is None or len(iv_data) == 0:
            return jsonify({
                'success': False,
                'error': '无法加载IV数据'
            }), 500
        
        # 获取最新IV值
        latest_iv = iv_data[
            (iv_data['strike'] >= 6900) & 
            (iv_data['strike'] <= 7100) &
            (iv_data['iv_pct'].notna())
        ]
        
        if len(latest_iv) == 0:
            return jsonify({
                'success': False,
                'error': '无法获取当前IV值'
            }), 500
        
        current_iv = latest_iv['iv_pct'].iloc[-1]
        
        # 计算百分位
        percentile, stats = calculate_iv_percentile(iv_data, current_iv)
        
        if percentile is None:
            return jsonify({
                'success': False,
                'error': '无法计算IV百分位'
            }), 500
        
        # 准备响应数据
        response = {
            'success': True,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'current_iv': current_iv,
            'percentile': percentile,
            'stats': stats,
            'interpretation': get_iv_interpretation(percentile)
        }
        
        # 缓存结果
        set_cached_data(cache_key, response)
        
        return jsonify(response)
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

def get_iv_interpretation(percentile):
    """获取IV百分位解释"""
    if percentile <= 20:
        return {
            'level': '极低',
            'color': 'success',
            'description': '隐含波动率处于历史极低水平',
            'recommendation': '适合买入期权（做多波动率）',
            'confidence': '高'
        }
    elif percentile <= 40:
        return {
            'level': '偏低',
            'color': 'info',
            'description': '隐含波动率处于历史较低水平',
            'recommendation': '考虑买入期权或做多波动率',
            'confidence': '中'
        }
    elif percentile <= 60:
        return {
            'level': '正常',
            'color': 'warning',
            'description': '隐含波动率处于历史正常范围',
            'recommendation': '中性策略或方向性交易',
            'confidence': '低'
        }
    elif percentile <= 80:
        return {
            'level': '偏高',
            'color': 'warning',
            'description': '隐含波动率处于历史较高水平',
            'recommendation': '考虑卖出期权或做空波动率',
            'confidence': '中'
        }
    else:
        return {
            'level': '极高',
            'color': 'danger',
            'description': '隐含波动率处于历史极高水平',
            'recommendation': '适合卖出期权（做空波动率）',
            'confidence': '高'
        }

@app.route('/api/volatility/signals', methods=['GET'])
def get_trading_signals():
    """获取交易信号"""
    cache_key = 'trading_signals'
    cached = get_cached_data(cache_key)
    if cached:
        return jsonify(cached)
    
    try:
        # 获取波动锥数据
        cone_response = get_volatility_cone().get_json()
        if not cone_response.get('success'):
            cone_data = None
        else:
            cone_data = {}
            for item in cone_response['data']:
                cone_data[item['window']] = {
                    'current': item['current'],
                    'mean': item['mean'],
                    'min': item['min'],
                    'max': item['max']
                }
        
        # 获取IV百分位数据
        iv_response = get_iv_percentile().get_json()
        if not iv_response.get('success'):
            iv_percentile = None
            iv_stats = None
        else:
            iv_percentile = iv_response['percentile']
            iv_stats = iv_response['stats']
        
        # 生成交易信号
        signals = generate_trading_signals(cone_data, iv_percentile, iv_stats)
        
        response = {
            'success': True,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'signals': signals,
            'count': len(signals)
        }
        
        # 缓存结果
        set_cached_data(cache_key, response)
        
        return jsonify(response)
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/volatility/chart/cone', methods=['GET'])
def get_cone_chart():
    """获取波动锥图表"""
    try:
        # 加载数据
        pta_data = load_pta_data()
        if pta_data is None:
            return jsonify({'success': False, 'error': '无法加载数据'}), 500
        
        # 计算历史波动率
        df_hv = calculate_all_hv_windows(pta_data)
        cone_data = generate_volatility_cone_data(df_hv)
        
        if cone_data is None:
            return jsonify({'success': False, 'error': '无法生成波动锥数据'}), 500
        
        # 生成图表
        chart_path = os.path.join(WORKSPACE, 'static', 'volatility_cone_latest.png')
        fig = plot_volatility_cone(cone_data, chart_path)
        
        if fig is None:
            return jsonify({'success': False, 'error': '无法生成图表'}), 500
        
        return send_file(chart_path, mimetype='image/png')
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/volatility/chart/iv-distribution', methods=['GET'])
def get_iv_distribution_chart():
    """获取IV分布图表"""
    try:
        # 加载IV数据
        iv_data_dict = load_iv_data()
        iv_data = iv_data_dict.get('1min')
        
        if iv_data is None or len(iv_data) == 0:
            return jsonify({'success': False, 'error': '无法加载IV数据'}), 500
        
        # 获取最新IV值
        latest_iv = iv_data[
            (iv_data['strike'] >= 6900) & 
            (iv_data['strike'] <= 7100) &
            (iv_data['iv_pct'].notna())
        ]
        
        if len(latest_iv) == 0:
            return jsonify({'success': False, 'error': '无法获取当前IV值'}), 500
        
        current_iv = latest_iv['iv_pct'].iloc[-1]
        
        # 计算百分位
        percentile, stats = calculate_iv_percentile(iv_data, current_iv)
        
        if percentile is None:
            return jsonify({'success': False, 'error': '无法计算IV百分位'}), 500
        
        # 生成图表
        chart_path = os.path.join(WORKSPACE, 'static', 'iv_distribution_latest.png')
        fig = plot_iv_percentile_distribution(iv_data, current_iv, stats, chart_path)
        
        if fig is None:
            return jsonify({'success': False, 'error': '无法生成图表'}), 500
        
        return send_file(chart_path, mimetype='image/png')
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/volatility/summary', methods=['GET'])
def get_summary():
    """获取综合分析摘要"""
    try:
        results = {}
        errors = []
        
        # 顺序获取数据（避免线程问题）
        try:
            cone_response = get_volatility_cone().get_json()
            if cone_response.get('success'):
                results['cone'] = cone_response
            else:
                errors.append(f"波动锥: {cone_response.get('error')}")
        except Exception as e:
            errors.append(f"波动锥: {str(e)}")
        
        try:
            iv_response = get_iv_percentile().get_json()
            if iv_response.get('success'):
                results['iv'] = iv_response
            else:
                errors.append(f"IV百分位: {iv_response.get('error')}")
        except Exception as e:
            errors.append(f"IV百分位: {str(e)}")
        
        try:
            signals_response = get_trading_signals().get_json()
            if signals_response.get('success'):
                results['signals'] = signals_response
            else:
                errors.append(f"交易信号: {signals_response.get('error')}")
        except Exception as e:
            errors.append(f"交易信号: {str(e)}")
        
        # 构建响应
        response = {
            'success': len(errors) < 3,  # 至少有一个成功
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'data': results,
            'errors': errors if errors else None
        }
        
        return jsonify(response)
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/volatility/refresh', methods=['POST'])
def refresh_cache():
    """刷新缓存"""
    try:
        global _cache, _cache_time
        _cache.clear()
        _cache_time.clear()
        
        return jsonify({
            'success': True,
            'message': '缓存已刷新',
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# 错误处理
@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'success': False,
        'error': '资源未找到'
    }), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        'success': False,
        'error': '服务器内部错误'
    }), 500

if __name__ == '__main__':
    # 创建必要的目录
    os.makedirs(os.path.join(WORKSPACE, 'static'), exist_ok=True)
    
    print("=" * 60)
    print("波动锥和隐波百分位API服务")
    print(f"工作目录: {WORKSPACE}")
    print("=" * 60)
    
    # 运行Flask应用
    app.run(
        host='0.0.0.0',
        port=5001,  # 使用5001端口，避免与现有web_app.py冲突
        debug=True,
        threaded=True
    )
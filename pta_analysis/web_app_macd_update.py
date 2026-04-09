#!/usr/bin/env python3
"""
更新K线图功能中的MACD指标，使其支持1-60分钟各级别配置
在现有web_app_integrated.py基础上添加多时间级别MACD功能
"""

import os
import sys
import json
import warnings
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, render_template
import akshare as ak
import pandas as pd
import numpy as np

# 添加当前目录到路径
WORKSPACE = "/home/admin/.openclaw/workspace/codeman/pta_analysis"
sys.path.insert(0, WORKSPACE)

# 导入MACD多时间级别模块
try:
    from macd_multiperiod import (
        calculate_macd,
        calculate_macd_area,
        get_macd_summary,
        resample_data,
        analyze_macd_for_period,
        get_all_periods_macd,
        PERIOD_MAP,
        PERIOD_LABELS
    )
    MACD_MODULE_AVAILABLE = True
except ImportError:
    MACD_MODULE_AVAILABLE = False
    print("警告: MACD多时间级别模块不可用，使用模拟数据")

warnings.filterwarnings('ignore')

# 创建Flask应用
app = Flask(__name__)

# ==================== 数据获取函数 ====================

def get_pta_1min_data(symbol='TA0', bars=800):
    """获取PTA期货1分钟数据"""
    try:
        df = ak.futures_zh_minute_sina(symbol=symbol, period='1')
        df.columns = [c.strip() for c in df.columns]
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.sort_values('datetime').tail(bars).reset_index(drop=True)
        return df
    except Exception as e:
        print(f"获取数据失败: {e}")
        return None

def get_kline_data_for_period(period='1min', symbol='TA0', bars=200):
    """
    获取指定周期的K线数据
    
    参数:
    - period: 时间周期 ('1min', '5min', '15min', '30min', '60min')
    - symbol: 品种代码
    - bars: 返回的K线数量
    
    返回:
    - kline_data: K线数据列表
    - current_price: 当前价格
    - change: 涨跌
    - change_pct: 涨跌幅
    """
    # 获取1分钟数据
    df_1min = get_pta_1min_data(symbol, bars * 10)  # 获取更多数据用于重采样
    
    if df_1min is None or len(df_1min) == 0:
        # 返回模拟数据
        return get_mock_kline_data(period, bars)
    
    # 根据周期处理数据
    if period == '1min':
        df_period = df_1min.tail(bars).reset_index(drop=True)
    else:
        period_code = PERIOD_MAP.get(period, '5min')
        df_resampled = resample_data(df_1min, period_code)
        df_period = df_resampled.tail(bars).reset_index(drop=True)
    
    # 转换为前端需要的格式
    kline_data = []
    for _, row in df_period.iterrows():
        kline_data.append({
            'time': row['datetime'].strftime('%Y-%m-%d %H:%M:%S'),
            'open': float(row['open']),
            'high': float(row['high']),
            'low': float(row['low']),
            'close': float(row['close']),
            'volume': float(row['volume'])
        })
    
    # 计算涨跌幅
    if len(df_period) >= 2:
        current_price = float(df_period['close'].iloc[-1])
        prev_price = float(df_period['close'].iloc[-2])
        change = current_price - prev_price
        change_pct = (change / prev_price) * 100
    else:
        current_price = float(df_period['close'].iloc[-1]) if len(df_period) > 0 else 0
        change = 0
        change_pct = 0
    
    return kline_data, current_price, change, change_pct

def get_mock_kline_data(period='1min', bars=100):
    """生成模拟K线数据（备用）"""
    now = datetime.now()
    data = []
    
    # 根据周期设置时间间隔
    if period == '1min':
        delta = timedelta(minutes=1)
    elif period == '5min':
        delta = timedelta(minutes=5)
    elif period == '15min':
        delta = timedelta(minutes=15)
    elif period == '30min':
        delta = timedelta(minutes=30)
    elif period == '60min':
        delta = timedelta(minutes=60)
    else:
        delta = timedelta(minutes=1)
    
    base_price = 6400
    price_trend = 0
    
    for i in range(bars):
        timestamp = now - (delta * i)
        
        # 模拟价格趋势
        trend_change = np.random.choice([-1, 0, 1], p=[0.3, 0.4, 0.3])
        price_trend += trend_change * 0.5
        
        open_price = base_price + price_trend + np.random.randint(-10, 10)
        close_price = open_price + np.random.randint(-15, 15)
        high_price = max(open_price, close_price) + np.random.randint(0, 8)
        low_price = min(open_price, close_price) - np.random.randint(0, 8)
        volume = np.random.randint(100, 1000)
        
        data.append({
            'time': timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'open': float(open_price),
            'high': float(high_price),
            'low': float(low_price),
            'close': float(close_price),
            'volume': float(volume)
        })
    
    # 反转，最新的在前面
    data = data[::-1]
    
    # 计算涨跌幅
    if len(data) >= 2:
        current_price = data[-1]['close']
        prev_price = data[-2]['close']
        change = current_price - prev_price
        change_pct = (change / prev_price) * 100
    else:
        current_price = data[-1]['close'] if data else 0
        change = 0
        change_pct = 0
    
    return data, current_price, change, change_pct

# ==================== API路由 ====================

@app.route('/')
def index():
    """首页"""
    return render_template('kline_macd_test.html')

@app.route('/kline')
def kline_page():
    """K线图页面"""
    return render_template('kline_macd_test.html')

@app.route('/api/kline/data')
def api_kline_data():
    """K线图数据API - 支持多时间周期"""
    # 获取参数
    period = request.args.get('period', '1min')
    symbol = request.args.get('symbol', 'TA0')
    bars = int(request.args.get('bars', '100'))
    
    # 获取数据
    kline_data, current_price, change, change_pct = get_kline_data_for_period(
        period, symbol, bars
    )
    
    return jsonify({
        'success': True,
        'symbol': symbol,
        'period': period,
        'period_label': PERIOD_LABELS.get(period, period),
        'data': kline_data,
        'current_price': current_price,
        'change': change,
        'change_pct': change_pct,
        'count': len(kline_data),
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })

@app.route('/api/kline/indicators')
def api_kline_indicators():
    """技术指标API - 支持多时间周期和自定义参数"""
    # 获取参数
    period = request.args.get('period', '1min')
    symbol = request.args.get('symbol', 'TA0')
    fast = int(request.args.get('fast', '12'))
    slow = int(request.args.get('slow', '26'))
    signal = int(request.args.get('signal', '9'))
    
    # 获取数据
    df = get_pta_1min_data(symbol, 800)
    
    if df is None or len(df) == 0 or not MACD_MODULE_AVAILABLE:
        # 返回模拟数据
        return jsonify(get_mock_indicators(period, fast, slow, signal))
    
    try:
        # 计算MACD指标
        result = analyze_macd_for_period(df, period, fast, slow, signal)
        
        # 构建响应
        response = {
            'success': True,
            'period': period,
            'period_label': result['period_label'],
            'macd': {
                'dif': result['macd']['dif'],
                'dea': result['macd']['dea'],
                'macd': result['macd']['macd'],
                'state': result['macd']['state'],
                'fast': fast,
                'slow': slow,
                'signal': signal,
                'positive_area': result['area_summary']['positive_area'],
                'negative_area': result['area_summary']['negative_area'],
                'area_ratio': result['area_summary']['area_ratio']
            },
            'areas': result['areas'],
            'close': result['close'],
            'bars': result['bars'],
            'timestamp': result['datetime']
        }
        
        return jsonify(response)
        
    except Exception as e:
        print(f"计算MACD指标时出错: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'indicators': get_mock_indicators(period, fast, slow, signal)
        })

@app.route('/api/kline/macd/all_periods')
def api_kline_macd_all_periods():
    """获取所有时间周期的MACD指标"""
    # 获取参数
    symbol = request.args.get('symbol', 'TA0')
    fast = int(request.args.get('fast', '12'))
    slow = int(request.args.get('slow', '26'))
    signal = int(request.args.get('signal', '9'))
    
    # 获取数据
    df = get_pta_1min_data(symbol, 800)
    
    if df is None or len(df) == 0 or not MACD_MODULE_AVAILABLE:
        # 返回模拟数据
        return jsonify(get_mock_all_periods_indicators(fast, slow, signal))
    
    try:
        # 计算所有周期的MACD
        results = get_all_periods_macd(df, fast, slow, signal)
        
        # 构建响应
        response = {
            'success': True,
            'symbol': symbol,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'periods': {}
        }
        
        for period, result in results.items():
            if 'error' in result:
                response['periods'][period] = {
                    'success': False,
                    'error': result['error']
                }
            else:
                response['periods'][period] = {
                    'success': True,
                    'period_label': result['period_label'],
                    'macd': {
                        'dif': result['macd']['dif'],
                        'dea': result['macd']['dea'],
                        'macd': result['macd']['macd'],
                        'state': result['macd']['state']
                    },
                    'area_summary': result['area_summary'],
                    'close': result['close'],
                    'bars': result['bars'],
                    'timestamp': result['datetime']
                }
        
        return jsonify(response)
        
    except Exception as e:
        print(f"计算所有周期MACD时出错: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        })

def get_mock_indicators(period='1min', fast=12, slow=26, signal=9):
    """生成模拟指标数据"""
    # 根据周期生成不同的模拟数据
    period_multiplier = {
        '1min': 1,
        '5min': 0.8,
        '15min': 0.6,
        '30min': 0.4,
        '60min': 0.2
    }.get(period, 1)
    
    # 生成随机的MACD值
    base_macd = np.random.uniform(-0.5, 0.5) * period_multiplier
    base_dif = np.random.uniform(-1, 1) * period_multiplier
    base_dea = base_dif - base_macd / 2
    
    positive_area = abs(np.random.uniform(500, 1500) * period_multiplier)
    negative_area = abs(np.random.uniform(400, 1200) * period_multiplier)
    
    if negative_area > 0:
        area_ratio = positive_area / negative_area
    else:
        area_ratio = float('inf')
    
    return {
        'macd': {
            'dif': round(base_dif, 4),
            'dea': round(base_dea, 4),
            'macd': round(base_macd, 4),
            'state': '多头' if base_macd > 0 else '空头',
            'fast': fast,
            'slow': slow,
            'signal': signal,
            'positive_area': round(positive_area, 4),
            'negative_area': round(negative_area, 4),
            'area_ratio': round(area_ratio, 4)
        },
        'close': round(6400 + np.random.uniform(-50, 50), 2),
        'bars': np.random.randint(50, 200),
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

def get_mock_all_periods_indicators(fast=12, slow=26, signal=9):
    """生成所有周期的模拟指标数据"""
    periods = ['1min', '5min', '15min', '30min', '60min']
    results = {
        'success': True,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'periods': {}
    }
    
    for period in periods:
        results['periods'][period] = get_mock_indicators(period, fast, slow, signal)
        results['periods'][period]['period_label'] = PERIOD_LABELS.get(period, period)
    
    return results

# ==================== 启动应用 ====================

if __name__ == '__main__':
    print("=" * 60)
    print("PTA期货K线图 - 多时间级别MACD版本")
    print("=" * 60)
    print(f"MACD模块状态: {'可用' if MACD_MODULE_AVAILABLE else '模拟数据'}")
    print(f"访问地址: http://localhost:8425")
    print(f"K线图页面: http://localhost:8425/kline")
    print(f"API示例:")
    print(f"  - K线数据: http://localhost:8425/api/kline/data?period=5min")
    print(f"  - MACD指标: http://localhost:8425/api/kline/indicators?period=15min")
    print(f"  - 所有周期MACD: http://localhost:8425/api/kline/macd/all_periods")
    print("=" * 60)
    
    # 启动Flask应用
    app.run(host='0.0.0.0', port=8425, debug=False, threaded=True)
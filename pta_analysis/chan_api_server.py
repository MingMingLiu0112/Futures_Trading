#!/usr/bin/env python3
"""
缠论分析 Flask API
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request, jsonify, Blueprint
import akshare as ak
import pandas as pd
from chan_analysis.engine import KLine, full_chan_analysis, analyze_multi_level, find_interval_nesting

app = Flask(__name__)
chan_bp = Blueprint('chan', __name__)

def fetch_klines(symbol="TA0", period="1min", count=200):
    """从akshare获取K线数据"""
    try:
        if period in ["1min", "5min", "15min", "30min", "60min"]:
            period_map = {"1min": "1", "5min": "5", "15min": "15", "30min": "30", "60min": "60"}
            df = ak.futures_zh_minute_sina(symbol=symbol, period=period_map.get(period, "1"))
        else:
            df = ak.futures_zh_daily_sina(symbol=symbol)
        
        df = df.sort_values('datetime').tail(count).reset_index(drop=True)
        
        klines = []
        for i, row in df.iterrows():
            klines.append(KLine(
                idx=i,
                time=str(row['datetime']),
                open=float(row['open']),
                high=float(row['high']),
                low=float(row['low']),
                close=float(row['close']),
                volume=float(row['volume'])
            ))
        return klines
    except Exception as e:
        print(f"获取K线数据失败: {e}")
        return []

@chan_bp.route('/api/chan/analysis')
def chan_analysis():
    """单级别缠论分析"""
    period = request.args.get('period', '1min')
    
    klines = fetch_klines("TA0", period, count=300)
    if not klines:
        return jsonify({'error': '无法获取数据', 'period': period})
    
    result = full_chan_analysis(klines, period)
    return jsonify(result)

@chan_bp.route('/api/chan/multi')
def chan_multi():
    """多级别联立分析"""
    periods = request.args.get('periods', '1min,5min,15min,30min,60min,1day').split(',')
    
    period_klines = {}
    for p in periods:
        p = p.strip()
        klines = fetch_klines("TA0", p, count=200)
        if klines:
            period_klines[p] = klines
    
    if not period_klines:
        return jsonify({'error': '无法获取任何周期数据'})
    
    results = analyze_multi_level(period_klines, periods)
    nesting = find_interval_nesting(results)
    
    return jsonify({
        'levels': {p: {
            'stats': r.stats,
            'echarts': r.echarts,
            'current_price': r.current_price,
            'change': r.change,
            'change_pct': r.change_pct
        } for p, r in results.items()},
        'nesting': nesting
    })

@chan_bp.route('/api/chan/status')
def chan_status():
    """缠论模块状态"""
    return jsonify({
        'status': 'running',
        'features': [
            '笔计算 (Bi)',
            '线段计算 (Seg)', 
            '中枢计算 (ZS)',
            '买卖点识别 (BS)',
            '多级别联立',
            '区间套分析',
            'ECharts数据导出'
        ]
    })

# 注册蓝图
app.register_blueprint(chan_bp)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8426, debug=False)

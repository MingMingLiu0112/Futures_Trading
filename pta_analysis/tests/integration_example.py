#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
波动锥功能集成示例
展示如何将波动锥功能集成到现有的Flask应用中
"""

from flask import Flask, render_template, jsonify, request
import sys
import os

# 添加当前目录到路径
WORKSPACE = "/home/admin/.openclaw/workspace/codeman/pta_analysis"
sys.path.insert(0, WORKSPACE)

# 导入波动锥模块
try:
    from volatility_cone import (
        load_pta_data, load_iv_data, calculate_all_hv_windows,
        generate_volatility_cone_data, calculate_iv_percentile,
        generate_trading_signals
    )
    VOLATILITY_AVAILABLE = True
except ImportError as e:
    print(f"警告: 无法导入波动锥模块: {e}")
    VOLATILITY_AVAILABLE = False

app = Flask(__name__)

@app.route('/')
def index():
    """主页 - 显示集成示例"""
    return render_template('integration_demo.html',
                          volatility_available=VOLATILITY_AVAILABLE)

@app.route('/api/volatility/quick-analysis')
def quick_volatility_analysis():
    """快速波动率分析（简化版）"""
    if not VOLATILITY_AVAILABLE:
        return jsonify({
            'success': False,
            'error': '波动锥模块不可用'
        }), 500
    
    try:
        # 加载数据
        pta_data = load_pta_data()
        iv_data_dict = load_iv_data()
        iv_data = iv_data_dict.get('1min')
        
        if pta_data is None:
            return jsonify({
                'success': False,
                'error': '无法加载PTA数据'
            }), 500
        
        # 计算历史波动率
        df_hv = calculate_all_hv_windows(pta_data)
        cone_data = generate_volatility_cone_data(df_hv)
        
        # 计算IV百分位
        current_iv = None
        iv_percentile = None
        if iv_data is not None and len(iv_data) > 0:
            latest_iv = iv_data[
                (iv_data['strike'] >= 6900) & 
                (iv_data['strike'] <= 7100) &
                (iv_data['iv_pct'].notna())
            ]
            if len(latest_iv) > 0:
                current_iv = float(latest_iv['iv_pct'].iloc[-1])
                iv_percentile, _ = calculate_iv_percentile(iv_data, current_iv)
        
        # 生成交易信号
        signals = generate_trading_signals(cone_data, iv_percentile, None)
        
        # 准备响应
        response = {
            'success': True,
            'volatility_cone': {
                'short_term': cone_data.get(20, {}).get('current') if cone_data else None,
                'long_term': cone_data.get(120, {}).get('current') if cone_data else None,
                'ratio': None
            },
            'iv_analysis': {
                'current': current_iv,
                'percentile': iv_percentile,
                'level': get_iv_level(iv_percentile) if iv_percentile else None
            },
            'signals': signals[:3] if signals else [],  # 只返回前3个信号
            'summary': generate_summary(cone_data, iv_percentile, signals)
        }
        
        # 计算波动率比率
        if response['volatility_cone']['short_term'] and response['volatility_cone']['long_term']:
            response['volatility_cone']['ratio'] = round(
                response['volatility_cone']['short_term'] / response['volatility_cone']['long_term'], 2
            )
        
        return jsonify(response)
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

def get_iv_level(percentile):
    """根据百分位获取IV等级"""
    if percentile <= 25:
        return {'level': '低', 'color': 'success', 'action': '买入期权'}
    elif percentile <= 75:
        return {'level': '中', 'color': 'warning', 'action': '中性策略'}
    else:
        return {'level': '高', 'color': 'danger', 'action': '卖出期权'}

def generate_summary(cone_data, iv_percentile, signals):
    """生成分析摘要"""
    summary_parts = []
    
    if cone_data:
        short_term = cone_data.get(20, {}).get('current')
        long_term = cone_data.get(120, {}).get('current')
        if short_term and long_term:
            ratio = short_term / long_term
            if ratio > 1.2:
                summary_parts.append("短期波动率显著高于长期")
            elif ratio < 0.8:
                summary_parts.append("短期波动率显著低于长期")
            else:
                summary_parts.append("波动率结构相对平衡")
    
    if iv_percentile is not None:
        if iv_percentile <= 25:
            summary_parts.append("隐含波动率处于历史低位")
        elif iv_percentile >= 75:
            summary_parts.append("隐含波动率处于历史高位")
        else:
            summary_parts.append("隐含波动率处于历史正常范围")
    
    if signals:
        signal_count = len(signals)
        high_confidence = sum(1 for s in signals if s.get('confidence') == '高')
        summary_parts.append(f"生成{signal_count}个交易信号（{high_confidence}个高置信度）")
    
    return " | ".join(summary_parts) if summary_parts else "暂无分析结果"

@app.route('/api/volatility/status')
def volatility_status():
    """波动锥功能状态检查"""
    return jsonify({
        'available': VOLATILITY_AVAILABLE,
        'data_sources': {
            'pta_data': os.path.exists(f"{WORKSPACE}/data/pta_1day.csv"),
            'iv_data': os.path.exists(f"{WORKSPACE}/data/ta_iv_1min.csv")
        },
        'modules': {
            'volatility_cone': VOLATILITY_AVAILABLE,
            'pandas': check_module('pandas'),
            'numpy': check_module('numpy'),
            'scipy': check_module('scipy')
        }
    })

def check_module(module_name):
    """检查模块是否可用"""
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False

if __name__ == '__main__':
    print("=" * 60)
    print("波动锥功能集成示例")
    print("=" * 60)
    
    if not VOLATILITY_AVAILABLE:
        print("警告: 波动锥模块不可用，部分功能将受限")
        print("请确保已安装所需依赖:")
        print("  pip install pandas numpy matplotlib scipy")
    
    app.run(
        host='0.0.0.0',
        port=5002,  # 使用不同端口避免冲突
        debug=True
    )
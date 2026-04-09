"""
主路由 - 页面和K线图
"""
from flask import Blueprint, render_template, jsonify, request, send_from_directory, current_app
import os
import glob

bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    """PTA主页面"""
    return render_template('index.html')

@bp.route('/kline')
def kline_page():
    """K线图页面"""
    return render_template('kline.html')

@bp.route('/chan')
def chan_page():
    """缠论分析页面"""
    return render_template('chan.html')

@bp.route('/data/<path:filename>')
def data_files(filename):
    """数据文件访问"""
    data_dir = current_app.config.get('DATA_DIR', '/app/data')
    return send_from_directory(data_dir, filename)

@bp.route('/api/status')
def status():
    """系统状态"""
    redis_status = 'disconnected'
    if current_app.redis:
        try:
            current_app.redis.ping()
            redis_status = 'connected'
        except:
            redis_status = 'error'

    return jsonify({
        'service': 'pta-backend',
        'status': 'running',
        'redis': redis_status,
        'vnpy_rpc': f"{current_app.config['VNPY_RPC_HOST']}:{current_app.config['VNPY_RPC_PORT']}",
        'data_dir': current_app.config['DATA_DIR'],
    })

@bp.route('/api/pta/summary')
def pta_summary():
    """PTA品种汇总"""
    return jsonify({
        'symbol': 'TA',
        'name': 'PTA精对苯二甲酸',
        'exchange': 'CZCE',
        'unit': '元/吨',
        'contract_size': 5,  # 吨/手
        'tick_size': 2,  # 元
    })

#!/usr/bin/env python3
"""
PTA分析平台 - Flask后端
chan.py缠论引擎 + vnpy RPC + Redis缓存
"""
import os
import sys

# chan.py路径
chan_py_path = '/app/chan_py'
if os.path.exists(chan_py_path) and chan_py_path not in sys.path:
    sys.path.insert(0, chan_py_path)

from flask import Flask
import redis

def create_app():
    app = Flask(__name__)

    # 配置
    app.config['REDIS_HOST'] = os.getenv('REDIS_HOST', 'localhost')
    app.config['REDIS_PORT'] = int(os.getenv('REDIS_PORT', 6379))
    app.config['VNPY_RPC_HOST'] = os.getenv('VNPY_RPC_HOST', 'vnpy-container')
    app.config['VNPY_RPC_PORT'] = int(os.getenv('VNPY_RPC_PORT', 2014))
    app.config['DATA_DIR'] = os.getenv('DATA_DIR', '/app/data')

    # Redis连接
    try:
        app.redis = redis.Redis(
            host=app.config['REDIS_HOST'],
            port=app.config['REDIS_PORT'],
            db=0,
            decode_responses=True,
            socket_connect_timeout=5
        )
        app.redis.ping()
        print(f"[Redis] 连接成功: {app.config['REDIS_HOST']}:{app.config['REDIS_PORT']}")
    except Exception as e:
        print(f"[Redis] 连接失败: {e}，继续无缓存模式")
        app.redis = None

    # 注册蓝图
    from app.main import bp as main_bp
    from app.chan_api import bp as chan_bp
    from app.kline_api import bp as kline_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(chan_bp, url_prefix='/api/chan')
    app.register_blueprint(kline_bp, url_prefix='/api/kline')

    @app.route('/api/health')
    def health():
        return {'status': 'ok', 'service': 'pta-backend'}

    return app

#!/usr/bin/env python3
"""
vnpy Web Dashboard - Professional K-line Chart with ECharts
"""
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from vnpy.trader.database import get_database
from vnpy.trader.constant import Interval, Exchange
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

db = get_database()

@app.route("/")
def index():
    return send_file("/tmp/dashboard.html")

@app.route("/api/status")
def status():
    return jsonify({
        "server": "vnpy.mingmingliu.cn",
        "status": "running",
        "version": "4.3.0",
        "symbol": "KQ.m@CZCE.TA",
        "data_loaded": True
    })

@app.route("/api/kline")
def kline():
    symbol = request.args.get('symbol', 'KQ.m@CZCE.TA')
    interval = request.args.get('interval', '1min')
    limit = min(int(request.args.get('limit', 1000)), 2000)
    end = datetime.now()
    
    # All minute bars use Interval.MINUTE in vnpy
    bar_interval = Interval.MINUTE
    
    if interval in ['5min', '15min', '30min', '60min']:
        start = end - timedelta(days=90)
    elif interval == '1min':
        start = end - timedelta(days=7)
    else:
        start = end - timedelta(days=365)
    
    bars = db.load_bar_data(symbol, Exchange.CZCE, bar_interval, start, end)
    bars = sorted(bars, key=lambda x: x.datetime)[-limit:]
    
    return jsonify([{
        'datetime': b.datetime.isoformat(),
        'open': b.open_price,
        'high': b.high_price,
        'low': b.low_price,
        'close': b.close_price,
        'volume': b.volume,
        'open_interest': b.open_interest
    } for b in bars])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8765, debug=False)

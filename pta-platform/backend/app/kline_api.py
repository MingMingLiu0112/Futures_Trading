"""
K线数据API - akshare实时数据
"""
from flask import Blueprint, jsonify, request
import akshare as ak
import pandas as pd

bp = Blueprint('kline_api', __name__)

@bp.route('/data')
def kline_data():
    """K线图数据"""
    period = request.args.get('period', '1min')

    try:
        if period in ['1min', '5min', '15min', '30min', '60min']:
            period_map = {"1min": "1", "5min": "5", "15min": "15", "30min": "30", "60min": "60"}
            df = ak.futures_zh_minute_sina(symbol="TA0", period=period_map.get(period, "1"))
        elif period == '1day':
            df = ak.futures_zh_daily_sina(symbol="TA0")
        else:
            return jsonify({'error': f'不支持的周期: {period}'})

        df = df.sort_values('datetime').tail(1500).reset_index(drop=True)

        data = []
        for _, row in df.iterrows():
            data.append({
                'time': str(row['datetime']),
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': float(row['volume'])
            })

        last = data[-1] if data else {}
        first = data[0] if data else {}
        current_price = last.get('close', 0)
        first_price = first.get('close', current_price)
        change = current_price - first_price
        change_pct = (change / first_price * 100) if first_price else 0

        return jsonify({
            'symbol': 'TA',
            'period': period,
            'data': data,
            'current_price': current_price,
            'change': round(change, 2),
            'change_pct': round(change_pct, 2),
            'source': 'akshare'
        })
    except Exception as e:
        return jsonify({'error': str(e), 'symbol': 'TA', 'period': period, 'data': []})


@bp.route('/realtime')
def kline_realtime():
    """实时行情（单条）"""
    try:
        df = ak.futures_zh_minute_sina(symbol="TA0", period="1")
        df = df.sort_values('datetime').tail(1)
        row = df.iloc[0]
        return jsonify({
            'symbol': 'TA',
            'time': str(row['datetime']),
            'price': float(row['close']),
            'open': float(row['open']),
            'high': float(row['high']),
            'low': float(row['low']),
            'volume': float(row['volume']),
            'source': 'akshare'
        })
    except Exception as e:
        return jsonify({'error': str(e)})

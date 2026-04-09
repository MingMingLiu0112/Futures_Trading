#!/usr/bin/env python3
"""
PTA期权数据API服务器
为React期权链组件提供实时数据
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import random
from datetime import datetime, timedelta
import threading
import time
from typing import Dict, List, Any

app = Flask(__name__)
CORS(app)  # 允许跨域请求

# 模拟数据存储
option_data_cache = []
market_stats_cache = {}
last_update_time = None
update_interval = 30  # 数据更新间隔（秒）

def generate_mock_option_data() -> List[Dict[str, Any]]:
    """生成模拟期权数据"""
    data = []
    underlying_price = 6920
    atm_strike = 6900
    strikes = [atm_strike + i * 50 for i in range(-5, 6)]
    
    # 生成看涨期权
    for strike in strikes:
        is_atm = strike == atm_strike
        price = max(50, 100 - abs(strike - underlying_price) * 0.5)
        
        data.append({
            'contractCode': f'TA605C{strike}',
            'strikePrice': strike,
            'optionType': 'C',
            'price': round(price + random.uniform(-5, 5), 2),
            'priceChange': round(random.uniform(-10, 10), 2),
            'priceChangePercent': round(random.uniform(-5, 5), 2),
            'openInterest': random.randint(1000, 10000),
            'oiChange': random.randint(-500, 500),
            'oiChangePercent': round(random.uniform(-10, 10), 2),
            'volume': random.randint(500, 5000),
            'volumeChange': random.randint(-200, 200),
            'volumeChangePercent': round(random.uniform(-15, 15), 2),
            'impliedVol': round(0.2 + random.uniform(-0.05, 0.1), 4),
            'ivChange': round(random.uniform(-0.02, 0.02), 4),
            'ivChangeAbs': round(abs(random.uniform(-0.02, 0.02)), 4),
            'greeks': {
                'delta': round(0.5 + (underlying_price - strike) / 1000 + random.uniform(-0.1, 0.1), 4),
                'gamma': round(0.01 + random.uniform(0, 0.02), 4),
                'theta': round(-0.05 - random.uniform(0, 0.02), 4),
                'vega': round(0.1 + random.uniform(0, 0.05), 4),
                'rho': round(0.03 + random.uniform(0, 0.02), 4)
            },
            'underlyingPrice': underlying_price,
            'timeToExpiry': 30,
            'isATM': is_atm
        })
    
    # 生成看跌期权
    for strike in strikes:
        is_atm = strike == atm_strike
        price = max(30, 80 - abs(strike - underlying_price) * 0.4)
        
        data.append({
            'contractCode': f'TA605P{strike}',
            'strikePrice': strike,
            'optionType': 'P',
            'price': round(price + random.uniform(-3, 3), 2),
            'priceChange': round(random.uniform(-8, 8), 2),
            'priceChangePercent': round(random.uniform(-4, 4), 2),
            'openInterest': random.randint(800, 8000),
            'oiChange': random.randint(-400, 400),
            'oiChangePercent': round(random.uniform(-8, 8), 2),
            'volume': random.randint(400, 4000),
            'volumeChange': random.randint(-150, 150),
            'volumeChangePercent': round(random.uniform(-12, 12), 2),
            'impliedVol': round(0.22 + random.uniform(-0.05, 0.12), 4),
            'ivChange': round(random.uniform(-0.025, 0.025), 4),
            'ivChangeAbs': round(abs(random.uniform(-0.025, 0.025)), 4),
            'greeks': {
                'delta': round(-0.5 + (strike - underlying_price) / 1000 + random.uniform(-0.1, 0.1), 4),
                'gamma': round(0.01 + random.uniform(0, 0.02), 4),
                'theta': round(-0.04 - random.uniform(0, 0.02), 4),
                'vega': round(0.12 + random.uniform(0, 0.06), 4),
                'rho': round(-0.02 - random.uniform(0, 0.01), 4)
            },
            'underlyingPrice': underlying_price,
            'timeToExpiry': 30,
            'isATM': is_atm
        })
    
    return data

def generate_market_stats() -> Dict[str, Any]:
    """生成市场统计数据"""
    calls = [d for d in option_data_cache if d['optionType'] == 'C']
    puts = [d for d in option_data_cache if d['optionType'] == 'P']
    
    total_volume = sum(d['volume'] for d in option_data_cache)
    total_oi = sum(d['openInterest'] for d in option_data_cache)
    
    put_volume = sum(d['volume'] for d in puts)
    call_volume = sum(d['volume'] for d in calls)
    put_call_ratio = put_volume / call_volume if call_volume > 0 else 0
    
    put_iv = sum(d['impliedVol'] for d in puts) / len(puts) if puts else 0.22
    call_iv = sum(d['impliedVol'] for d in calls) / len(calls) if calls else 0.2
    iv_skew = put_iv - call_iv
    
    # 找到最活跃的行权价作为最大痛点（简化）
    strike_volumes = {}
    for option in option_data_cache:
        strike = option['strikePrice']
        strike_volumes[strike] = strike_volumes.get(strike, 0) + option['volume']
    
    max_pain = max(strike_volumes.items(), key=lambda x: x[1])[0] if strike_volumes else 6900
    
    return {
        'underlyingPrice': 6920,
        'atmStrike': 6900,
        'totalVolume': total_volume,
        'totalOI': total_oi,
        'putCallRatio': round(put_call_ratio, 3),
        'ivSkew': round(iv_skew, 4),
        'maxPain': max_pain,
        'updateTime': datetime.now().strftime('%H:%M:%S')
    }

def update_data():
    """定期更新数据"""
    global option_data_cache, market_stats_cache, last_update_time
    
    while True:
        try:
            option_data_cache = generate_mock_option_data()
            market_stats_cache = generate_market_stats()
            last_update_time = datetime.now()
            
            print(f"[{last_update_time.strftime('%H:%M:%S')}] 数据已更新")
            print(f"  期权数量: {len(option_data_cache)}")
            print(f"  总成交量: {market_stats_cache['totalVolume']}")
            print(f"  Put/Call比率: {market_stats_cache['putCallRatio']}")
            
        except Exception as e:
            print(f"更新数据时出错: {e}")
        
        time.sleep(update_interval)

@app.route('/api/options/chain', methods=['GET'])
def get_option_chain():
    """获取期权链数据"""
    try:
        response = {
            'options': option_data_cache,
            'stats': market_stats_cache,
            'metadata': {
                'count': len(option_data_cache),
                'lastUpdate': last_update_time.isoformat() if last_update_time else None,
                'updateInterval': update_interval
            }
        }
        return jsonify(response)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/options/stats', methods=['GET'])
def get_market_stats():
    """获取市场统计数据"""
    try:
        return jsonify(market_stats_cache)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/options/<contract_code>', methods=['GET'])
def get_option_detail(contract_code):
    """获取单个期权详情"""
    try:
        option = next((opt for opt in option_data_cache if opt['contractCode'] == contract_code), None)
        if option:
            return jsonify(option)
        else:
            return jsonify({'error': '期权未找到'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """健康检查"""
    return jsonify({
        'status': 'healthy',
        'service': 'pta-option-api',
        'timestamp': datetime.now().isoformat(),
        'dataAvailable': len(option_data_cache) > 0
    })

@app.route('/api/config', methods=['GET'])
def get_config():
    """获取配置信息"""
    return jsonify({
        'updateInterval': update_interval,
        'fields': {
            'price': '期权价格及涨跌幅',
            'oiChangePercent': '持仓量变化百分比',
            'volumeChangePercent': '成交量变化百分比',
            'ivChangeAbs': '隐含波动率绝对值变化',
            'greeks': '希腊字母值'
        },
        'sortOptions': ['strike', 'volume', 'oi', 'iv'],
        'maxDisplay': 20
    })

if __name__ == '__main__':
    # 初始化数据
    print("初始化期权数据...")
    option_data_cache = generate_mock_option_data()
    market_stats_cache = generate_market_stats()
    last_update_time = datetime.now()
    
    # 启动数据更新线程
    update_thread = threading.Thread(target=update_data, daemon=True)
    update_thread.start()
    
    print(f"PTA期权数据API服务器启动")
    print(f"服务地址: http://localhost:8000")
    print(f"数据更新间隔: {update_interval}秒")
    print(f"可用端点:")
    print(f"  GET /api/options/chain      - 获取期权链数据")
    print(f"  GET /api/options/stats      - 获取市场统计数据")
    print(f"  GET /api/options/<code>     - 获取单个期权详情")
    print(f"  GET /api/health             - 健康检查")
    print(f"  GET /api/config             - 获取配置信息")
    print("\n按 Ctrl+C 停止服务器")
    
    # 启动Flask服务器
    app.run(host='0.0.0.0', port=8000, debug=False)
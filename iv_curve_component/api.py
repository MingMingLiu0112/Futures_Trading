"""
IV曲线数据API服务
提供隐含波动率曲线数据给前端可视化组件
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import json
import os

app = Flask(__name__)
CORS(app)  # 允许跨域请求

# 模拟数据存储
class IVDataGenerator:
    def __init__(self):
        self.symbols = ['TA', 'CU', 'AU', 'AG', 'RU', 'SC']
        self.expiries = ['current', 'next', 'quarter', 'half']
        
        # 初始化历史数据
        self.history_data = {}
        self.init_history_data()
    
    def init_history_data(self):
        """初始化历史IV数据"""
        for symbol in self.symbols:
            self.history_data[symbol] = {}
            for expiry in self.expiries:
                # 生成30天的历史数据
                dates = [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d') 
                        for i in range(30, 0, -1)]
                
                history = []
                for date in dates:
                    history.append({
                        'date': date,
                        'iv_curve': self.generate_iv_curve(symbol, expiry, date),
                        'atm_iv': np.random.uniform(15, 35),
                        'skew': np.random.uniform(-2, 2),
                        'kurtosis': np.random.uniform(-1, 1)
                    })
                
                self.history_data[symbol][expiry] = history
    
    def generate_iv_curve(self, symbol, expiry, date_str=None):
        """生成IV曲线数据"""
        # 基础参数
        base_params = {
            'TA': {'base_iv': 22, 'volatility': 5, 'smile_strength': 0.2},
            'CU': {'base_iv': 18, 'volatility': 4, 'smile_strength': 0.15},
            'AU': {'base_iv': 16, 'volatility': 3, 'smile_strength': 0.1},
            'AG': {'base_iv': 25, 'volatility': 6, 'smile_strength': 0.25},
            'RU': {'base_iv': 20, 'volatility': 5, 'smile_strength': 0.18},
            'SC': {'base_iv': 30, 'volatility': 8, 'smile_strength': 0.3}
        }
        
        params = base_params.get(symbol, base_params['TA'])
        
        # 生成行权价范围 (80% - 120%)
        strike_prices = list(range(80, 121, 2))
        iv_values = []
        
        for strike in strike_prices:
            # 基础IV
            base_iv = params['base_iv']
            
            # 微笑曲线效果
            distance_from_atm = abs(strike - 100)
            smile_effect = distance_from_atm * params['smile_strength']
            
            # 到期时间影响
            expiry_multiplier = {
                'current': 1.0,
                'next': 0.9,
                'quarter': 0.8,
                'half': 0.7
            }.get(expiry, 1.0)
            
            # 随机波动
            random_noise = np.random.normal(0, params['volatility'] * 0.1)
            
            # 日期影响（模拟市场变化）
            date_factor = 1.0
            if date_str:
                try:
                    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                    # 周内效应：周一IV较高，周五IV较低
                    weekday = date_obj.weekday()
                    date_factor = 1.0 + (0.1 if weekday == 0 else -0.05 if weekday == 4 else 0)
                except:
                    pass
            
            # 计算最终IV
            iv = (base_iv + smile_effect) * expiry_multiplier * date_factor + random_noise
            iv = max(10, min(50, iv))  # 限制范围
            iv_values.append(round(iv, 2))
        
        return {
            'strike_prices': strike_prices,
            'iv_values': iv_values,
            'atm_strike': 100,
            'atm_iv': iv_values[strike_prices.index(100)],
            'skew': self.calculate_skew(iv_values),
            'kurtosis': self.calculate_kurtosis(iv_values)
        }
    
    def calculate_skew(self, iv_values):
        """计算IV偏度"""
        atm_index = 10  # 100%行权价
        left_avg = np.mean(iv_values[:atm_index])
        right_avg = np.mean(iv_values[atm_index+1:])
        return round(right_avg - left_avg, 2)
    
    def calculate_kurtosis(self, iv_values):
        """计算IV峰度"""
        mean = np.mean(iv_values)
        std = np.std(iv_values)
        if std == 0:
            return 0
        fourth_moment = np.mean([((x - mean) / std) ** 4 for x in iv_values])
        return round(fourth_moment - 3, 2)
    
    def get_current_iv(self, symbol, expiry):
        """获取当前IV曲线"""
        return self.generate_iv_curve(symbol, expiry, datetime.now().strftime('%Y-%m-%d'))
    
    def get_previous_iv(self, symbol, expiry):
        """获取前一日IV曲线"""
        prev_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        return self.generate_iv_curve(symbol, expiry, prev_date)
    
    def get_iv_history(self, symbol, expiry, days=7):
        """获取历史IV数据"""
        if symbol in self.history_data and expiry in self.history_data[symbol]:
            history = self.history_data[symbol][expiry]
            return history[-days:] if days > 0 else history
        return []
    
    def analyze_curve_movement(self, current_curve, previous_curve):
        """分析曲线移动"""
        current_iv = current_curve['iv_values']
        previous_iv = previous_curve['iv_values']
        
        # 垂直移动（整体水平变化）
        vertical_shift = np.mean(current_iv) - np.mean(previous_iv)
        
        # 水平移动（微笑中心移动）
        current_min_idx = np.argmin(current_iv)
        previous_min_idx = np.argmin(previous_iv)
        strike_prices = current_curve['strike_prices']
        horizontal_shift = strike_prices[current_min_idx] - strike_prices[previous_min_idx]
        
        # 扭曲分析（两端变化差异）
        left_change = current_iv[0] - previous_iv[0]
        right_change = current_iv[-1] - previous_iv[-1]
        twist = abs(left_change - right_change)
        
        # ATM IV变化
        atm_change = current_curve['atm_iv'] - previous_curve['atm_iv']
        
        # 微笑变化
        skew_change = current_curve['skew'] - previous_curve['skew']
        
        return {
            'vertical_shift': round(vertical_shift, 2),
            'horizontal_shift': round(horizontal_shift, 1),
            'twist': round(twist, 2),
            'atm_change': round(atm_change, 2),
            'skew_change': round(skew_change, 2),
            'market_sentiment': self.get_market_sentiment(vertical_shift, horizontal_shift, skew_change)
        }
    
    def get_market_sentiment(self, vertical_shift, horizontal_shift, skew_change):
        """根据曲线移动判断市场情绪"""
        if vertical_shift > 1 and horizontal_shift > 0 and skew_change > 0:
            return '强烈看涨'
        elif vertical_shift > 1 and horizontal_shift < 0 and skew_change > 0:
            return '波动加大，方向不明'
        elif vertical_shift < -1 and horizontal_shift < 0 and skew_change < 0:
            return '强烈看跌'
        elif vertical_shift > 0.5:
            return '偏多波动'
        elif vertical_shift < -0.5:
            return '偏空波动'
        else:
            return '中性'

# 初始化数据生成器
data_gen = IVDataGenerator()

# API路由
@app.route('/')
def serve_index():
    """提供前端页面"""
    return send_from_directory('.', 'index.html')

@app.route('/api/iv/current')
def get_current_iv():
    """获取当前IV曲线"""
    symbol = request.args.get('symbol', 'TA')
    expiry = request.args.get('expiry', 'current')
    
    curve = data_gen.get_current_iv(symbol, expiry)
    curve['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    curve['symbol'] = symbol
    curve['expiry'] = expiry
    
    return jsonify(curve)

@app.route('/api/iv/previous')
def get_previous_iv():
    """获取前一日IV曲线"""
    symbol = request.args.get('symbol', 'TA')
    expiry = request.args.get('expiry', 'current')
    
    curve = data_gen.get_previous_iv(symbol, expiry)
    curve['timestamp'] = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d 15:00:00')
    curve['symbol'] = symbol
    curve['expiry'] = expiry
    
    return jsonify(curve)

@app.route('/api/iv/history')
def get_iv_history():
    """获取历史IV数据"""
    symbol = request.args.get('symbol', 'TA')
    expiry = request.args.get('expiry', 'current')
    days = int(request.args.get('days', 7))
    
    history = data_gen.get_iv_history(symbol, expiry, days)
    return jsonify(history)

@app.route('/api/iv/analyze')
def analyze_curve_movement():
    """分析曲线移动"""
    symbol = request.args.get('symbol', 'TA')
    expiry = request.args.get('expiry', 'current')
    
    current_curve = data_gen.get_current_iv(symbol, expiry)
    previous_curve = data_gen.get_previous_iv(symbol, expiry)
    
    analysis = data_gen.analyze_curve_movement(current_curve, previous_curve)
    
    return jsonify({
        'symbol': symbol,
        'expiry': expiry,
        'analysis': analysis,
        'current_timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'previous_timestamp': (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d 15:00:00')
    })

@app.route('/api/symbols')
def get_symbols():
    """获取可交易品种列表"""
    return jsonify(data_gen.symbols)

@app.route('/api/expiries')
def get_expiries():
    """获取到期月份列表"""
    return jsonify(data_gen.expiries)

@app.route('/api/iv/animation')
def get_animation_frames():
    """获取动画帧数据"""
    symbol = request.args.get('symbol', 'TA')
    expiry = request.args.get('expiry', 'current')
    frames = int(request.args.get('frames', 10))
    
    current_curve = data_gen.get_current_iv(symbol, expiry)
    previous_curve = data_gen.get_previous_iv(symbol, expiry)
    
    animation_data = []
    for i in range(frames + 1):
        progress = i / frames
        
        # 插值生成中间状态
        interpolated_iv = []
        for j in range(len(current_curve['iv_values'])):
            prev_iv = previous_curve['iv_values'][j]
            curr_iv = current_curve['iv_values'][j]
            interpolated = prev_iv + (curr_iv - prev_iv) * progress
            interpolated_iv.append(round(interpolated, 2))
        
        frame_data = {
            'frame': i,
            'total_frames': frames,
            'progress': round(progress, 2),
            'strike_prices': current_curve['strike_prices'],
            'iv_values': interpolated_iv,
            'timestamp': f'动画帧 {i}/{frames}'
        }
        
        animation_data.append(frame_data)
    
    return jsonify(animation_data)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
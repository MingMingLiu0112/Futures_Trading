"""
期权链数据Excel导出Flask应用 - 主文件
"""

import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_file
import json
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['EXPORT_FOLDER'] = 'exports'
os.makedirs(app.config['EXPORT_FOLDER'], exist_ok=True)

class OptionChainExporter:
    """期权链数据导出器"""
    
    def __init__(self):
        self.sample_data = self._generate_sample_data()
    
    def _generate_sample_data(self):
        """生成示例期权链数据"""
        current_price = 100.0
        strike_prices = np.arange(80, 121, 5)
        expiration_dates = [
            (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d'),
            (datetime.now() + timedelta(days=60)).strftime('%Y-%m-%d'),
            (datetime.now() + timedelta(days=90)).strftime('%Y-%m-%d')
        ]
        
        option_chain = []
        for expiry in expiration_dates:
            for strike in strike_prices:
                # 看涨期权
                call_data = {
                    'symbol': f'C_{strike}_{expiry.replace("-", "")}',
                    'type': 'call', 'strike': strike, 'expiry': expiry,
                    'last_price': round(np.random.uniform(0.5, 20.0), 2),
                    'bid': round(np.random.uniform(0.4, 19.0), 2),
                    'ask': round(np.random.uniform(0.6, 21.0), 2),
                    'volume': np.random.randint(100, 10000),
                    'open_interest': np.random.randint(1000, 50000),
                    'implied_volatility': round(np.random.uniform(0.15, 0.45), 4),
                    'delta': round(np.random.uniform(0.1, 0.9), 4),
                    'gamma': round(np.random.uniform(0.01, 0.05), 4),
                    'theta': round(np.random.uniform(-0.05, -0.01), 4),
                    'vega': round(np.random.uniform(0.01, 0.03), 4),
                    'rho': round(np.random.uniform(0.01, 0.02), 4),
                    'moneyness': 'ITM' if strike < current_price else ('ATM' if strike == current_price else 'OTM')
                }
                
                # 看跌期权
                put_data = {
                    'symbol': f'P_{strike}_{expiry.replace("-", "")}',
                    'type': 'put', 'strike': strike, 'expiry': expiry,
                    'last_price': round(np.random.uniform(0.5, 20.0), 2),
                    'bid': round(np.random.uniform(0.4, 19.0), 2),
                    'ask': round(np.random.uniform(0.6, 21.0), 2),
                    'volume': np.random.randint(100, 10000),
                    'open_interest': np.random.randint(1000, 50000),
                    'implied_volatility': round(np.random.uniform(0.15, 0.45), 4),
                    'delta': round(np.random.uniform(-0.9, -0.1), 4),
                    'gamma': round(np.random.uniform(0.01, 0.05), 4),
                    'theta': round(np.random.uniform(-0.05, -0.01), 4),
                    'vega': round(np.random.uniform(0.01, 0.03), 4),
                    'rho': round(np.random.uniform(-0.02, -0.01), 4),
                    'moneyness': 'ITM' if strike > current_price else ('ATM' if strike == current_price else 'OTM')
                }
                
                option_chain.extend([call_data, put_data])
        
        # PCR数据
        pcr_data = []
        for expiry in expiration_dates:
            expiry_options = [opt for opt in option_chain if opt['expiry'] == expiry]
            calls = [opt for opt in expiry_options if opt['type'] == 'call']
            puts = [opt for opt in expiry_options if opt['type'] == 'put']
            
            pcr_volume = sum(p['volume'] for p in puts) / sum(c['volume'] for c in calls) if sum(c['volume'] for c in calls) > 0 else 0
            pcr_oi = sum(p['open_interest'] for p in puts) / sum(c['open_interest'] for c in calls) if sum(c['open_interest'] for c in calls) > 0 else 0
            
            pcr_data.append({
                'expiry': expiry,
                'pcr_volume': round(pcr_volume, 4),
                'pcr_open_interest': round(pcr_oi, 4),
                'total_volume': sum(opt['volume'] for opt in expiry_options),
                'total_open_interest': sum(opt['open_interest'] for opt in expiry_options),
                'avg_iv_call': round(np.mean([c['implied_volatility'] for c in calls]), 4),
                'avg_iv_put': round(np.mean([p['implied_volatility'] for p in puts]), 4),
                'iv_skew': round(np.mean([p['implied_volatility'] for p in puts]) - np.mean([c['implied_volatility'] for c in calls]), 4)
            })
        
        # 历史数据
        history_days = 30
        history_data = []
        base_date = datetime.now() - timedelta(days=history_days)
        
        for i in range(history_days):
            date = base_date + timedelta(days=i)
            history_data.append({
                'date': date.strftime('%Y-%m-%d'),
                'underlying_price': round(current_price + np.random.uniform(-5, 5), 2),
                'total_volume': np.random.randint(100000, 500000),
                'total_open_interest': np.random.randint(1000000, 5000000),
                'avg_iv': round(np.random.uniform(0.2, 0.4), 4),
                'pcr_volume': round(np.random.uniform(0.8, 1.2), 4),
                'pcr_oi': round(np.random.uniform(0.9, 1.1), 4)
            })
        
        return {
            'underlying': {
                'symbol': 'AAPL',
                'current_price': current_price,
                'change': 1.5,
                'change_percent': 1.52,
                'volume': 4567890,
                'market_cap': '2.8T'
            },
            'option_chain': option_chain,
            'pcr_data': pcr_data,
            'history_data': history_data,
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
    
    def export_to_excel(self, data, filename=None):
        """导出数据到Excel文件"""
        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'option_chain_export_{timestamp}.xlsx'
        
        filepath = os.path.join(app.config['EXPORT_FOLDER'], filename)
        
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            # 基础信息
            pd.DataFrame([data['underlying']]).to_excel(writer, sheet_name='基础信息', index=False)
            
            # 期权链数据
            option_df = pd.DataFrame(data['option_chain'])
            option_df.to_excel(writer, sheet_name='期权链数据', index=False)
            
            # PCR数据
            pd.DataFrame(data['pcr_data']).to_excel(writer, sheet_name='PCR数据', index=False)
            
            # 历史数据
            pd.DataFrame(data['history_data']).to_excel(writer, sheet_name='历史数据', index=False)
            
            # 希腊字母汇总
            greek_summary = self._create_greek_summary(option_df)
            greek_summary.to_excel(writer, sheet_name='希腊字母汇总', index=False)
            
            # 波动率曲面
            vol_surface = self._create_volatility_surface(option_df)
            vol_surface.to_excel(writer, sheet_name='波动率曲面', index=False)
        
        logger.info(f"Excel文件已生成: {filepath}")
        return filepath
    
    def _create_greek_summary(self, option_df):
        """创建希腊字母汇总表"""
        summary_data = []
        
        for expiry in option_df['expiry'].unique():
            for option_type in ['call', 'put']:
                mask = (option_df['expiry'] == expiry) & (option_df['type'] == option_type)
                df_subset = option_df[mask]
                
                if len(df_subset) > 0:
                    summary_data.append({
                        '到期日': expiry,
                        '类型': '看涨' if option_type == 'call' else '看跌',
                        '数量': len(df_subset),
                        '平均Delta': round(df_subset['delta'].mean(), 4),
                        '平均Gamma': round(df_subset['gamma'].mean(), 4),
                        '平均Theta': round(df_subset['theta'].mean(), 4),
                        '平均Vega': round(df_subset['vega'].mean(), 4),
                        '平均Rho': round(df_subset['rho'].mean(), 4),
                        '平均IV': round(df_subset['implied_volatility'].mean(), 4),
                        'Delta范围': f"{round(df_subset['delta'].min(), 4)} - {round(df_subset['delta'].max(), 4)}",
                        'IV范围': f"{round(df_subset['implied_volatility'].min(), 4)} - {round(df_subset['implied_volatility'].max(), 4)}"
                    })
        
        return pd.DataFrame(summary_data)
    
    def _create_volatility_surface(self, option_df):
        """创建波动率曲面数据"""
        surface_data = []
        
        expiries = sorted(option_df['expiry'].unique())
        strikes = sorted(option_df['strike'].unique())
        
        for expiry in expiries:
            for strike in strikes:
                calls = option_df[(option_df['expiry'] == expiry) & 
                                 (option_df['strike'] == strike) & 
                                 (option_df['type'] == 'call')]
                puts = option_df[(option_df['expiry'] == expiry) & 
                                (option_df['strike'] == strike) & 
                                (option_df['type'] == 'put')]
                
                call_iv = calls['implied_volatility'].mean() if not calls.empty else None
                put_iv = puts['implied_volatility'].mean() if not puts.empty else None
                avg_iv = np.mean([iv for iv in [call_iv, put_iv] if iv is not None]) if any([call_iv, put_iv]) else None
                
                surface_data.append({
                    '到期日': expiry,
                    '行权价': strike,
                    '看涨IV': round(call_iv, 4) if call_iv else '',
                    '看跌IV': round(put_iv, 4) if put_iv else '',
                    '平均IV': round(avg_iv, 4) if avg_iv else '',
                    'IV偏度': round(put_iv - call_iv, 4) if call_iv and put_iv else ''
                })
        
        return pd.DataFrame(surface_data)

# 创建导出器实例
exporter = OptionChainExporter()

# Flask路由
@app.route('/')
def index():
    """首页"""
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>期权链数据Excel导出系统</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; }
            .container { max-width: 800px; margin: 0 auto; }
            .header { background: #366092; color: white; padding: 20px; border-radius: 5px; }
            .card { border: 1px solid #ddd; padding: 20px; margin: 20px 0; border-radius: 5px; }
            .btn { background: #366092; color: white; padding: 10px 20px; border: none; border-radius: 3px; cursor: pointer; margin: 5px; }
            .btn:hover { background: #2a4a7a; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>期权链数据Excel导出系统</h1>
                <p>支持完整期权链数据、PCR数据、希腊字母、历史数据导出</p>
            </div>
            
            <div class="card">
                <h2>功能说明</h2>
                <ul>
                    <li>完整期权链数据导出（看涨/看跌期权）</li>
                    <li>PCR（Put-Call Ratio）数据分析</li>
                    <li>希腊字母（Delta, Gamma, Theta, Vega, Rho）汇总</li>
                    <li>历史数据趋势分析</li>
                    <li>波动率曲面数据</li>
                    <li>多Sheet Excel导出</li>
                </ul>
            </div>
            
            <div class="card">
                <h2>快速导出</h2>
                <p>点击下方按钮生成示例数据Excel文件：</p>
                <button class="btn" onclick="window.open('/api/export/sample', '_blank')">生成示例Excel文件</button>
                
                <div style="margin-top: 20px;">
                    <h3>API接口</h3>
                    <ul>
                        <li><code>GET /api/export/sample</code> - 导出示例数据</li>
                        <li><code>GET /api/data/sample</code> - 获取示例数据JSON</li>
                        <li><code>GET /api/health</code> - 健康检查</li>
                    </ul>
                </div>
            </div>
        </div>
    </body>
    </html>
    '''

@app.route('/api/data/sample')
def get_sample_data():
    """获取示例数据"""
    return jsonify(exporter.sample_data)

@app.route('/api/export/sample')
def export_sample():
    """导出示例数据"""
    try:
        filepath = exporter.export_to_excel(exporter.sample_data)
        return send_file(filepath, as_attachment=True)
    except Exception as e:
        logger.error(f"导出失败: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/health')
def health_check():
    """健康检查"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0"
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
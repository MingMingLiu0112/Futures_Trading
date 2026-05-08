#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
风险控制API集成测试
"""

import pytest
import sys
import os
import json

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web_app_integrated import app


class TestRiskApiIntegration:
    """风险控制API集成测试"""
    
    @pytest.fixture
    def client(self):
        """创建测试客户端"""
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client
    
    def test_api_status_includes_risk_control(self, client):
        """测试状态API包含风险控制模块"""
        response = client.get('/api/status')
        assert response.status_code == 200
        
        data = response.get_json()
        assert data['status'] == 'running'
        assert data['version'] == '2.0.0'
        assert 'risk_control' in data['modules']
        assert data['modules']['risk_control']['status'] == 'completed'
    
    def test_stop_loss_calculate_fixed(self, client):
        """测试固定止损计算API"""
        response = client.post(
            '/api/risk/stop-loss/calculate',
            data=json.dumps({
                'symbol': 'TA',
                'initial_price': 5000,
                'strategy_type': 'fixed',
                'stop_pct': 0.02,
                'current_price': 5050
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = response.get_json()
        
        assert data['success'] == True
        assert data['symbol'] == 'TA'
        assert data['strategy_type'] == 'fixed'
        assert data['stop_price'] == 4900  # 5000 * (1 - 0.02)
        assert data['is_triggered'] == False
    
    def test_stop_loss_calculate_trailing(self, client):
        """测试移动止损计算API"""
        response = client.post(
            '/api/risk/stop-loss/calculate',
            data=json.dumps({
                'symbol': 'TA',
                'initial_price': 5000,
                'strategy_type': 'trailing',
                'stop_pct': 0.02,
                'current_price': 5100
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = response.get_json()
        
        assert data['success'] == True
        assert data['symbol'] == 'TA'
        assert data['strategy_type'] == 'trailing'
        assert data['stop_price'] == 4998  # 5100 * (1 - 0.02)
        assert data['trailing_count'] == 1
    
    def test_take_profit_calculate_fixed(self, client):
        """测试固定止盈计算API"""
        response = client.post(
            '/api/risk/take-profit/calculate',
            data=json.dumps({
                'symbol': 'TA',
                'initial_price': 5000,
                'strategy_type': 'fixed',
                'target_pct': 0.03,
                'current_price': 5050
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = response.get_json()
        
        assert data['success'] == True
        assert data['target_price'] == 5150  # 5000 * (1 + 0.03)
        assert data['is_triggered'] == False
    
    def test_take_profit_calculate_trailing(self, client):
        """测试追踪止盈计算API"""
        response = client.post(
            '/api/risk/take-profit/calculate',
            data=json.dumps({
                'symbol': 'TA',
                'initial_price': 5000,
                'strategy_type': 'trailing',
                'target_pct': 0.02,
                'current_price': 5100
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = response.get_json()
        
        assert data['success'] == True
        assert data['target_price'] == 4998  # 5100 * (1 - 0.02)
        assert data['trailing_count'] == 1
    
    def test_position_calculate_risk(self, client):
        """测试风险百分比仓位计算API"""
        response = client.post(
            '/api/risk/position/calculate',
            data=json.dumps({
                'account_id': 'test_account',
                'calculation_type': 'risk',
                'entry_price': 5000,
                'stop_price': 4900
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = response.get_json()
        
        assert data['success'] == True
        assert data['position_size'] == 10  # 100000 * 0.01 / 100 = 10
    
    def test_position_calculate_fixed(self, client):
        """测试固定金额仓位计算API"""
        response = client.post(
            '/api/risk/position/calculate',
            data=json.dumps({
                'account_id': 'test_account',
                'calculation_type': 'fixed',
                'entry_price': 5000,
                'position_value': 10000
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = response.get_json()
        
        assert data['success'] == True
        assert data['position_size'] == 2  # 10000 / 5000 = 2
    
    def test_position_open(self, client):
        """测试开仓API"""
        response = client.post(
            '/api/risk/position/open',
            data=json.dumps({
                'account_id': 'test_account',
                'symbol': 'TA',
                'direction': 'long',
                'quantity': 10,
                'entry_price': 5000,
                'stop_loss_price': 4900,
                'take_profit_price': 5100
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = response.get_json()
        
        assert data['success'] == True
        assert data['symbol'] == 'TA'
        assert data['direction'] == 'long'
        assert data['quantity'] == 10
    
    def test_account_status(self, client):
        """测试账户状态API"""
        # 先开仓
        client.post(
            '/api/risk/position/open',
            data=json.dumps({
                'account_id': 'test_status',
                'symbol': 'TA',
                'direction': 'long',
                'quantity': 10,
                'entry_price': 5000
            }),
            content_type='application/json'
        )
        
        # 获取账户状态
        response = client.get('/api/risk/account/status?account_id=test_status')
        
        assert response.status_code == 200
        data = response.get_json()
        
        assert data['success'] == True
        assert data['account_id'] == 'test_status'
        assert data['position_count'] == 1
        assert len(data['positions']) == 1
        assert data['positions'][0]['symbol'] == 'TA'
    
    def test_position_close(self, client):
        """测试平仓API"""
        # 先开仓
        client.post(
            '/api/risk/position/open',
            data=json.dumps({
                'account_id': 'test_close',
                'symbol': 'TA',
                'direction': 'long',
                'quantity': 10,
                'entry_price': 5000
            }),
            content_type='application/json'
        )
        
        # 平仓
        response = client.post(
            '/api/risk/position/close',
            data=json.dumps({
                'account_id': 'test_close',
                'symbol': 'TA',
                'exit_price': 5100
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = response.get_json()
        
        assert data['success'] == True
        assert data['pnl'] == 1000  # (5100 - 5000) * 10
        assert data['pnl_pct'] == 2.0  # 2%
    
    def test_stop_loss_trigger(self, client):
        """测试止损触发"""
        response = client.post(
            '/api/risk/stop-loss/calculate',
            data=json.dumps({
                'symbol': 'TA',
                'initial_price': 5000,
                'strategy_type': 'fixed',
                'stop_pct': 0.02,
                'current_price': 4899  # 低于止损价4900
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = response.get_json()
        
        assert data['success'] == True
        assert data['is_triggered'] == True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据模块单元测试
"""

import pytest
import sys
import os
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.data_collector import DataCollector, SimulatedDataSource
from data.data_processor import DataProcessor
from data.data_store import DataStore


class TestDataCollector:
    """数据采集器测试"""
    
    def test_data_collector_init(self):
        """测试数据采集器初始化"""
        collector = DataCollector()
        assert collector.sources == []
    
    def test_add_source(self):
        """测试添加数据源"""
        collector = DataCollector()
        source = SimulatedDataSource()
        collector.add_source(source)
        assert len(collector.sources) == 1
    
    def test_collect_simulated_data(self):
        """测试采集模拟数据"""
        collector = DataCollector()
        collector.add_source(SimulatedDataSource())
        
        data = collector.collect('TEST')
        
        assert len(data) == 100
        assert 'time' in data[0]
        assert 'close' in data[0]
        assert 'high' in data[0]
        assert 'low' in data[0]


class TestDataProcessor:
    """数据处理器测试"""
    
    def test_clean_data(self):
        """测试数据清洗"""
        raw_data = [
            {'time': '2024-01-01', 'close': 5000},
            {'time': '2024-01-02', 'close': -100},  # 无效价格
            {'time': '2024-01-03'},  # 缺少close
            {'time': '2024-01-04', 'close': 'invalid'},  # 无效类型
            {'time': '2024-01-05', 'close': 6000}
        ]
        
        cleaned = DataProcessor.clean_data(raw_data)
        
        assert len(cleaned) == 2
        assert cleaned[0]['close'] == 5000
        assert cleaned[1]['close'] == 6000
    
    def test_calculate_ma(self):
        """测试计算均线"""
        data = [
            {'time': f'2024-01-0{i+1}', 'close': 100 + i * 10}
            for i in range(25)
        ]
        
        result = DataProcessor.calculate_indicators(data, ['ma'])
        
        # MA5应该在前4个为None
        assert result[3]['ma5'] is None
        # 第5个应该是前5个的平均值
        assert result[4]['ma5'] == 120.0  # (100+110+120+130+140)/5
    
    def test_calculate_macd(self):
        """测试计算MACD"""
        data = []
        for i in range(30):
            data.append({'time': f'2024-01-0{i+1}', 'close': 5000 - i * 10})
        for i in range(30):
            data.append({'time': f'2024-01-{31+i}', 'close': 4700 + i * 15})
        
        result = DataProcessor.calculate_indicators(data, ['macd'])
        
        # 前25个应该没有MACD
        assert result[24]['macd'] is None
        # 后面应该有MACD值
        assert result[-1]['macd'] is not None
    
    def test_resample(self):
        """测试频率转换"""
        data = [
            {'time': f'2024-01-01 09:{i:02d}', 'open': 5000 + i, 'high': 5010 + i,
             'low': 4990 + i, 'close': 5005 + i, 'volume': 100 + i, 'symbol': 'TEST', 'frequency': '1min'}
            for i in range(10)
        ]
        
        result = DataProcessor.resample(data, '5min')
        
        assert len(result) == 2
        assert result[0]['frequency'] == '5min'
        assert result[0]['high'] == max(5010 + i for i in range(5))
        assert result[0]['low'] == min(4990 + i for i in range(5))


class TestDataStore:
    """数据存储测试"""
    
    def test_data_store_init(self):
        """测试数据存储初始化"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            store = DataStore(db_path)
            assert os.path.exists(db_path)
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)
    
    def test_save_and_get_klines(self):
        """测试保存和查询K线数据"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            store = DataStore(db_path)
            
            # 保存数据
            data = [
                {'symbol': 'TEST', 'time': '2024-01-01 09:00', 'open': 5000, 'high': 5020,
                 'low': 4980, 'close': 5010, 'volume': 1000, 'frequency': '1min'},
                {'symbol': 'TEST', 'time': '2024-01-01 09:01', 'open': 5010, 'high': 5030,
                 'low': 4990, 'close': 5020, 'volume': 1200, 'frequency': '1min'}
            ]
            store.save_klines(data)
            
            # 查询数据
            result = store.get_klines('TEST')
            
            assert len(result) == 2
            assert result[0]['close'] == 5010
            assert result[1]['close'] == 5020
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)
    
    def test_get_latest_kline(self):
        """测试获取最新K线"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            store = DataStore(db_path)
            
            data = [
                {'symbol': 'TEST', 'time': '2024-01-01 09:00', 'open': 5000, 'high': 5020,
                 'low': 4980, 'close': 5010, 'volume': 1000, 'frequency': '1min'},
                {'symbol': 'TEST', 'time': '2024-01-01 09:01', 'open': 5010, 'high': 5030,
                 'low': 4990, 'close': 5020, 'volume': 1200, 'frequency': '1min'}
            ]
            store.save_klines(data)
            
            latest = store.get_latest_kline('TEST')
            
            assert latest['time'] == '2024-01-01 09:01'
            assert latest['close'] == 5020
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)
    
    def test_get_symbol_list(self):
        """测试获取合约列表"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            store = DataStore(db_path)
            
            data = [
                {'symbol': 'TEST1', 'time': '2024-01-01', 'open': 5000, 'high': 5020,
                 'low': 4980, 'close': 5010, 'volume': 1000, 'frequency': '1min'},
                {'symbol': 'TEST2', 'time': '2024-01-01', 'open': 6000, 'high': 6020,
                 'low': 5980, 'close': 6010, 'volume': 1500, 'frequency': '1min'}
            ]
            store.save_klines(data)
            
            symbols = store.get_symbol_list()
            
            assert len(symbols) == 2
            assert 'TEST1' in symbols
            assert 'TEST2' in symbols
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

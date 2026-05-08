#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据采集器模块
负责从各种数据源获取行情数据
"""

from typing import List, Dict, Any, Optional
import time
import datetime


class DataCollector:
    """数据采集器"""
    
    def __init__(self):
        self.sources = []
    
    def add_source(self, source):
        """添加数据源"""
        self.sources.append(source)
    
    def collect(self, symbol: str, start_time: Optional[str] = None, 
               end_time: Optional[str] = None, frequency: str = '1min') -> List[Dict[str, Any]]:
        """
        采集数据
        :param symbol: 合约代码
        :param start_time: 开始时间
        :param end_time: 结束时间
        :param frequency: 数据频率
        :return: K线数据列表
        """
        all_data = []
        
        for source in self.sources:
            try:
                data = source.fetch(symbol, start_time, end_time, frequency)
                if data:
                    all_data.extend(data)
            except Exception as e:
                print(f"Error fetching from {source.name}: {e}")
        
        # 去重并按时间排序
        if all_data:
            all_data = sorted(all_data, key=lambda x: x['time'])
            # 去重
            seen = set()
            unique_data = []
            for bar in all_data:
                key = bar['time']
                if key not in seen:
                    seen.add(key)
                    unique_data.append(bar)
            return unique_data
        
        return all_data


class BaseDataSource:
    """数据源基类"""
    
    def __init__(self, name: str):
        self.name = name
    
    def fetch(self, symbol: str, start_time: Optional[str] = None, 
             end_time: Optional[str] = None, frequency: str = '1min') -> List[Dict[str, Any]]:
        """获取数据"""
        raise NotImplementedError("Subclasses must implement fetch method")


class SimulatedDataSource(BaseDataSource):
    """模拟数据源（用于测试）"""
    
    def __init__(self):
        super().__init__('simulated')
    
    def fetch(self, symbol: str, start_time: Optional[str] = None, 
             end_time: Optional[str] = None, frequency: str = '1min') -> List[Dict[str, Any]]:
        """生成模拟数据"""
        data = []
        base_price = 5000
        current_time = datetime.datetime.now()
        
        for i in range(100):
            time_str = (current_time - datetime.timedelta(minutes=i)).strftime('%Y-%m-%d %H:%M:%S')
            price_change = (i % 5 - 2) * 10
            open_price = base_price + price_change
            close_price = base_price + price_change + (i % 3 - 1) * 5
            high_price = max(open_price, close_price) + 10
            low_price = min(open_price, close_price) - 10
            
            data.append({
                'symbol': symbol,
                'time': time_str,
                'open': open_price,
                'high': high_price,
                'low': low_price,
                'close': close_price,
                'volume': 100 + i * 10,
                'frequency': frequency
            })
        
        return data[::-1]  # 反转，让时间从早到晚


class TqSdkDataSource(BaseDataSource):
    """天勤量化数据源"""
    
    def __init__(self):
        super().__init__('tqsdk')
        self._api = None
    
    def _get_api(self):
        """获取TqSdk API实例"""
        if self._api is None:
            try:
                from tqsdk import TqApi
                self._api = TqApi()
            except ImportError:
                raise ImportError("tqsdk not installed. Please install with: pip install tqsdk")
        return self._api
    
    def fetch(self, symbol: str, start_time: Optional[str] = None, 
             end_time: Optional[str] = None, frequency: str = '1min') -> List[Dict[str, Any]]:
        """从TqSdk获取数据"""
        api = self._get_api()
        
        try:
            klines = api.get_kline_serial(symbol, duration_seconds=self._get_duration(frequency))
            
            if start_time:
                klines = klines[klines['datetime'] >= start_time]
            if end_time:
                klines = klines[klines['datetime'] <= end_time]
            
            data = []
            for _, row in klines.iterrows():
                data.append({
                    'symbol': symbol,
                    'time': row['datetime'],
                    'open': row['open'],
                    'high': row['high'],
                    'low': row['low'],
                    'close': row['close'],
                    'volume': row['volume'],
                    'frequency': frequency
                })
            
            return data
        finally:
            # 不关闭API，保持连接
            pass
    
    def _get_duration(self, frequency: str) -> int:
        """将频率转换为秒数"""
        frequency_map = {
            '1min': 60,
            '5min': 300,
            '15min': 900,
            '30min': 1800,
            '1h': 3600,
            '4h': 14400,
            '1d': 86400
        }
        return frequency_map.get(frequency, 60)


class AkShareDataSource(BaseDataSource):
    """AkShare数据源"""
    
    def __init__(self):
        super().__init__('akshare')
    
    def fetch(self, symbol: str, start_time: Optional[str] = None, 
             end_time: Optional[str] = None, frequency: str = '1min') -> List[Dict[str, Any]]:
        """从AkShare获取数据"""
        try:
            import akshare as ak
        except ImportError:
            raise ImportError("akshare not installed. Please install with: pip install akshare")
        
        data = []
        
        try:
            # 尝试获取期货数据
            df = ak.futures_zh_minute(symbol=symbol, period=frequency)
            
            if not df.empty:
                for _, row in df.iterrows():
                    data.append({
                        'symbol': symbol,
                        'time': str(row.name),
                        'open': row['open'],
                        'high': row['high'],
                        'low': row['low'],
                        'close': row['close'],
                        'volume': row['volume'],
                        'frequency': frequency
                    })
        except Exception as e:
            print(f"AkShare fetch error: {e}")
        
        return data

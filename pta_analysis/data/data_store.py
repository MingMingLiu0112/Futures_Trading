#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据存储模块
负责数据的持久化存储和查询
"""

from typing import List, Dict, Any, Optional
import sqlite3
import os


class DataStore:
    """数据存储"""
    
    def __init__(self, db_path: str = 'data/futures_data.db'):
        self.db_path = db_path
        self._ensure_dir()
        self._init_db()
    
    def _ensure_dir(self):
        """确保目录存在"""
        dir_path = os.path.dirname(self.db_path)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path)
    
    def _init_db(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 创建K线数据表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS klines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                time TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume INTEGER NOT NULL,
                frequency TEXT NOT NULL,
                ma5 REAL,
                ma10 REAL,
                ma20 REAL,
                macd_dif REAL,
                macd_dea REAL,
                macd REAL,
                kdj_k REAL,
                kdj_d REAL,
                kdj_j REAL,
                UNIQUE(symbol, time, frequency)
            )
        ''')
        
        # 创建索引
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_klines_symbol ON klines(symbol)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_klines_time ON klines(time)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_klines_symbol_time ON klines(symbol, time)')
        
        conn.commit()
        conn.close()
    
    def save_klines(self, data: List[Dict[str, Any]]):
        """
        保存K线数据
        :param data: K线数据列表
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for bar in data:
            cursor.execute('''
                INSERT OR REPLACE INTO klines (
                    symbol, time, open, high, low, close, volume, frequency,
                    ma5, ma10, ma20, macd_dif, macd_dea, macd, kdj_k, kdj_d, kdj_j
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                bar.get('symbol', ''),
                bar.get('time', ''),
                bar.get('open', 0),
                bar.get('high', 0),
                bar.get('low', 0),
                bar.get('close', 0),
                bar.get('volume', 0),
                bar.get('frequency', '1min'),
                bar.get('ma5'),
                bar.get('ma10'),
                bar.get('ma20'),
                bar.get('macd_dif'),
                bar.get('macd_dea'),
                bar.get('macd'),
                bar.get('kdj_k'),
                bar.get('kdj_d'),
                bar.get('kdj_j')
            ))
        
        conn.commit()
        conn.close()
    
    def get_klines(self, symbol: str, start_time: Optional[str] = None, 
                  end_time: Optional[str] = None, frequency: str = '1min',
                  limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        查询K线数据
        :param symbol: 合约代码
        :param start_time: 开始时间
        :param end_time: 结束时间
        :param frequency: 数据频率
        :param limit: 返回数量限制
        :return: K线数据列表
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        query = '''
            SELECT symbol, time, open, high, low, close, volume, frequency,
                   ma5, ma10, ma20, macd_dif, macd_dea, macd, kdj_k, kdj_d, kdj_j
            FROM klines
            WHERE symbol = ? AND frequency = ?
        '''
        
        params = [symbol, frequency]
        
        if start_time:
            query += ' AND time >= ?'
            params.append(start_time)
        
        if end_time:
            query += ' AND time <= ?'
            params.append(end_time)
        
        query += ' ORDER BY time ASC'
        
        if limit:
            query += ' LIMIT ?'
            params.append(limit)
        
        cursor.execute(query, params)
        
        columns = [desc[0] for desc in cursor.description]
        result = []
        
        for row in cursor.fetchall():
            record = dict(zip(columns, row))
            # 转换None值
            for key in record:
                if record[key] is None:
                    record[key] = None
            result.append(record)
        
        conn.close()
        return result
    
    def get_latest_kline(self, symbol: str, frequency: str = '1min') -> Optional[Dict[str, Any]]:
        """
        获取最新一根K线
        :param symbol: 合约代码
        :param frequency: 数据频率
        :return: K线数据
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT symbol, time, open, high, low, close, volume, frequency,
                   ma5, ma10, ma20, macd_dif, macd_dea, macd, kdj_k, kdj_d, kdj_j
            FROM klines
            WHERE symbol = ? AND frequency = ?
            ORDER BY time DESC
            LIMIT 1
        ''', (symbol, frequency))
        
        row = cursor.fetchone()
        
        if row:
            columns = [desc[0] for desc in cursor.description]
            record = dict(zip(columns, row))
            conn.close()
            return record
        
        conn.close()
        return None
    
    def get_symbol_list(self) -> List[str]:
        """获取所有合约代码列表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT DISTINCT symbol FROM klines')
        result = [row[0] for row in cursor.fetchall()]
        
        conn.close()
        return result
    
    def delete_klines(self, symbol: str, frequency: str = '1min'):
        """
        删除指定合约的K线数据
        :param symbol: 合约代码
        :param frequency: 数据频率
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM klines WHERE symbol = ? AND frequency = ?', (symbol, frequency))
        
        conn.commit()
        conn.close()

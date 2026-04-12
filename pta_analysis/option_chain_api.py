#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA期权链API模块
提供期权链T型报价、希腊字母、隐波、PCR等数据

数据源：
- akshare: 日频历史数据
- tqsdk: 实时数据（需要认证）
"""

from __future__ import annotations
import json
import math
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from scipy.stats import norm
import pandas as pd
import numpy as np
import akshare as ak

# ==================== 常量定义 ====================

# PCR阈值
PCR_LOUD_THRESHOLD = 0.8   # 偏多阈值
PCR_BEAR_THRESHOLD = 1.0   # 偏空阈值

# 持仓变化阈值 (%)
OI_CHANGE_NOISE = 0.10      # 噪音区间
OI_CHANGE_SIGNIFICANT = 0.25 # 显著变化

# 隐波变化阈值 (按波环境)
IV_CHANGE_LOW = 1.5       # 低波环境(<20%)
IV_CHANGE_MID = 2.0       # 中波环境(20-30%)
IV_CHANGE_HIGH = 3.0      # 高波环境(>30%)

# 希腊字母计算用
RISK_FREE_RATE = 0.03

# ==================== 数据结构 ====================

@dataclass
class ExpiryData:
    """到期日数据"""
    expiry: str           # 到期日 YYYYMMDD
    trading_date: str      # 交易日期
    call_count: int        # 认购合约数
    put_count: int         # 认沽合约数
    total_volume_call: int
    total_volume_put: int
    total_oi_call: int
    total_oi_put: int
    volume_pcr: float    # 成交PCR
    position_pcr: float   # 持仓PCR

@dataclass
class StrikeRow:
    """T型报价单行"""
    strike: float
    call_code: str
    call_price: float
    call_iv: float
    call_iv_change: float
    call_delta: float
    call_gamma: float
    call_theta: float
    call_vega: float
    call_volume: int
    call_oi: int
    call_oi_change: float
    put_code: str
    put_price: float
    put_iv: float
    put_iv_change: float
    put_delta: float
    put_gamma: float
    put_theta: float
    put_vega: float
    put_volume: int
    put_oi: int
    put_oi_change: float

# ==================== 希腊字母计算 ====================

def calculate_days_to_expiry(expiry: str, trade_date: str = None) -> float:
    """计算剩余到期时间(年)
    
    Args:
        expiry: 到期日 YYYYMMDD
        trade_date: 交易日期 YYYYMMDD，默认今日
    """
    if trade_date is None:
        trade_date = datetime.now().strftime('%Y%m%d')
    
    try:
        expiry_dt = datetime.strptime(expiry, '%Y%m%d')
        trade_dt = datetime.strptime(trade_date, '%Y%m%d')
        days = (expiry_dt - trade_dt).days
        return max(days / 365.0, 1/365)  # 至少1天
    except:
        return 0.25  # 默认3个月

def bs_price(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    """Black-Scholes期权定价"""
    if T <= 0 or sigma <= 0:
        return 0.0
    
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    
    if option_type == 'C':
        price = S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    else:
        price = K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    
    return price

def calculate_greeks(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> Dict[str, float]:
    """计算希腊字母
    
    Args:
        S: 标的价格
        K: 行权价
        T: 到期时间(年)
        r: 无风险利率
        sigma: 波动率
        option_type: 'C' 或 'P'
        
    Returns:
        dict: {delta, gamma, theta, vega}
    """
    if T <= 0 or sigma <= 0:
        return {'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0}
    
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    
    if option_type == 'C':
        delta = norm.cdf(d1)
        theta = (-S * norm.pdf(d1) * sigma / (2 * sqrtT) 
                 - r * K * math.exp(-r * T) * norm.cdf(d2)) / 365
    else:
        delta = norm.cdf(d1) - 1
        theta = (-S * norm.pdf(d1) * sigma / (2 * sqrtT) 
                 + r * K * math.exp(-r * T) * norm.cdf(-d2)) / 365
    
    gamma = norm.pdf(d1) / (S * sigma * sqrtT)
    vega = S * sqrtT * norm.pdf(d1) / 100  # 每1%波动率
    
    return {
        'delta': delta,
        'gamma': gamma,
        'theta': theta,
        'vega': vega
    }

def parse_option_code(code: str) -> Tuple[Optional[str], Optional[str], Optional[float]]:
    """解析期权合约代码
    
    Args:
        code: 合约代码，如 'TA605C4100'
        
    Returns:
        (expiry, option_type, strike)
    """
    # 匹配模式: TA605C4100 -> expiry=TA605, type=C, strike=4100
    m = re.match(r'([A-Z]+)(\d+)([CP])(\d+)', code)
    if m:
        symbol = m.group(1)
        month = m.group(2)
        option_type = m.group(3)
        strike = float(m.group(4))
        expiry = symbol + month
        return expiry, option_type, strike
    return None, None, None

def get_iv_from_data(row: pd.Series) -> float:
    """从akshare数据行获取IV"""
    iv = row.get('隐含波动率')
    if iv is None or pd.isna(iv):
        return 0.0
    return float(iv) / 100  # akshare返回的是百分比

def get_delta_from_data(row: pd.Series) -> float:
    """从akshare数据行获取Delta"""
    delta = row.get('DELTA')
    if delta is None or pd.isna(delta):
        return 0.0
    return float(delta)

# ==================== 数据获取 ====================

class AkshareOptionData:
    """使用akshare获取期权数据"""
    
    @staticmethod
    def get_recent_trade_date(days: int = 15) -> str:
        """获取最近交易日（跳过周末）"""
        today = datetime.now()
        weekday = today.weekday()  # 0=Monday, 6=Sunday
        
        # 如果今天是周末，从上周五开始
        if weekday == 6:  # Sunday
            start_offset = 2  # 从上周五开始
        elif weekday == 5:  # Saturday
            start_offset = 1  # 从昨天(周五)开始
        else:
            start_offset = 1  # 从昨天开始
        
        for i in range(start_offset, days):
            dt = today - timedelta(days=i)
            date_str = dt.strftime('%Y%m%d')
            try:
                df = ak.option_hist_czce(symbol='PTA期权', trade_date=date_str)
                if df is not None and len(df) > 0:
                    return date_str
            except:
                continue
        return None
    
    @staticmethod
    def get_option_data(trade_date: str = None) -> pd.DataFrame:
        """获取PTA期权数据
        
        Args:
            trade_date: 交易日期 YYYYMMDD，默认最近交易日
        """
        if trade_date is None:
            trade_date = AkshareOptionData.get_recent_trade_date()
            if trade_date is None:
                return pd.DataFrame()
        
        try:
            df = ak.option_hist_czce(symbol='PTA期权', trade_date=trade_date)
            if df is None or len(df) == 0:
                return pd.DataFrame()
            
            # 解析合约代码
            parsed = df['合约代码'].apply(lambda x: parse_option_code(str(x)))
            df['expiry'] = parsed.apply(lambda x: x[0] if x else None)
            df['option_type'] = parsed.apply(lambda x: x[1] if x else None)
            df['strike'] = parsed.apply(lambda x: x[2] if x else None)
            
            # 过滤无效数据
            df = df[df['option_type'].isin(['C', 'P'])]
            df = df[df['strike'].notna()]
            
            return df
        except Exception as e:
            print(f"akshare get_option_data error: {e}")
            return pd.DataFrame()

# ==================== 期权链分析 ====================

class OptionChainAnalyzer:
    """期权链分析器"""
    
    def __init__(self, underlying_price: float = 0):
        self.underlying_price = underlying_price
        self.risk_free_rate = RISK_FREE_RATE
        self.trade_date = datetime.now().strftime('%Y%m%d')
    
    def build_t_type_quote(self, df: pd.DataFrame, 
                           prev_df: pd.DataFrame = None) -> Tuple[List[ExpiryData], List[StrikeRow]]:
        """构建T型报价
        
        Args:
            df: 当前日期的期权数据
            prev_df: 昨日数据
            
        Returns:
            (expiry_list, strike_rows)
        """
        if df is None or len(df) == 0:
            return [], []
        
        # 获取标的价格
        if self.underlying_price <= 0:
            # 从ATM期权的含义反推：ATM期权价格 ≈ 期权价值
            # 简单取成交量最大的期权的strike作为ATM参考
            try:
                atm_strike = df.loc[df['成交量(手)'].idxmax(), 'strike']
                self.underlying_price = atm_strike
            except:
                self.underlying_price = 6500  # 默认
        
        # 按到期日分组计算PCR
        expiry_groups = df.groupby('expiry')
        expiry_list = []
        
        for expiry, group in expiry_groups:
            calls = group[group['option_type'] == 'C']
            puts = group[group['option_type'] == 'P']
            
            vol_call = int(calls['成交量(手)'].sum()) if len(calls) > 0 else 0
            vol_put = int(puts['成交量(手)'].sum()) if len(puts) > 0 else 0
            oi_call = int(calls['持仓量'].sum()) if len(calls) > 0 else 0
            oi_put = int(puts['持仓量'].sum()) if len(puts) > 0 else 0
            
            expiry_list.append(ExpiryData(
                expiry=expiry,
                trading_date=self.trade_date,
                call_count=len(calls),
                put_count=len(puts),
                total_volume_call=vol_call,
                total_volume_put=vol_put,
                total_oi_call=oi_call,
                total_oi_put=oi_put,
                volume_pcr=round(vol_put / vol_call, 4) if vol_call > 0 else 0,
                position_pcr=round(oi_put / oi_call, 4) if oi_call > 0 else 0
            ))
        
        # 按到期日排序
        expiry_list.sort(key=lambda x: x.expiry)
        
        # 获取所有行权价
        all_strikes = sorted(df['strike'].unique())
        
        # 获取昨日数据用于计算变化
        prev_dict = {}
        if prev_df is not None and len(prev_df) > 0:
            for _, row in prev_df.iterrows():
                code = row['合约代码']
                prev_dict[code] = {
                    'close': row.get('今结算', 0) or row.get('今收盘', 0),
                    'iv': get_iv_from_data(row),
                    'oi': row.get('持仓量', 0)
                }
        
        # 构建T型报价行
        strike_rows = []
        
        for strike in all_strikes:
            call_row = df[(df['option_type'] == 'C') & (df['strike'] == strike)]
            put_row = df[(df['option_type'] == 'P') & (df['strike'] == strike)]
            
            # Call数据
            if len(call_row) > 0:
                cr = call_row.iloc[0]
                call_code = cr['合约代码']
                call_price = cr.get('今结算') or cr.get('今收盘') or 0
                call_iv = get_iv_from_data(cr)
                call_delta = get_delta_from_data(cr)
                call_volume = int(cr.get('成交量(手)', 0) or 0)
                call_oi = int(cr.get('持仓量', 0) or 0)
                
                # 计算希腊字母（如果数据没有）
                if call_delta == 0 and call_iv > 0:
                    T = calculate_days_to_expiry(call_code[:5] + call_code[-8:-4] if len(call_code) > 8 else 'TA605', self.trade_date)
                    greeks = calculate_greeks(self.underlying_price, strike, T, self.risk_free_rate, call_iv, 'C')
                    call_delta = greeks['delta']
                
                # 计算IV变化
                prev_call = prev_dict.get(call_code, {})
                call_iv_change = (call_iv - prev_call.get('iv', 0)) * 100 if prev_call else 0
                call_oi_change = ((call_oi - prev_call.get('oi', 0)) / prev_call.get('oi', 1) * 100) if prev_call and prev_call.get('oi', 0) > 0 else 0
                
                # 计算其他希腊字母
                T = calculate_days_to_expiry(cr['expiry'], self.trade_date)
                greeks = calculate_greeks(self.underlying_price, strike, T, self.risk_free_rate, call_iv if call_iv > 0 else 0.2, 'C')
                call_gamma = greeks['gamma']
                call_theta = greeks['theta']
                call_vega = greeks['vega']
            else:
                call_code = ''
                call_price = call_iv = call_delta = call_gamma = call_theta = call_vega = 0
                call_volume = call_oi = call_iv_change = call_oi_change = 0
            
            # Put数据
            if len(put_row) > 0:
                pr = put_row.iloc[0]
                put_code = pr['合约代码']
                put_price = pr.get('今结算') or pr.get('今收盘') or 0
                put_iv = get_iv_from_data(pr)
                put_delta = get_delta_from_data(pr)
                put_volume = int(pr.get('成交量(手)', 0) or 0)
                put_oi = int(pr.get('持仓量', 0) or 0)
                
                # 计算希腊字母
                if put_delta == 0 and put_iv > 0:
                    T = calculate_days_to_expiry(put_code[:5] + put_code[-8:-4] if len(put_code) > 8 else 'TA605', self.trade_date)
                    greeks = calculate_greeks(self.underlying_price, strike, T, self.risk_free_rate, put_iv, 'P')
                    put_delta = greeks['delta']
                
                # 计算IV变化
                prev_put = prev_dict.get(put_code, {})
                put_iv_change = (put_iv - prev_put.get('iv', 0)) * 100 if prev_put else 0
                put_oi_change = ((put_oi - prev_put.get('oi', 0)) / prev_put.get('oi', 1) * 100) if prev_put and prev_put.get('oi', 0) > 0 else 0
                
                # 计算其他希腊字母
                T = calculate_days_to_expiry(pr['expiry'], self.trade_date)
                greeks = calculate_greeks(self.underlying_price, strike, T, self.risk_free_rate, put_iv if put_iv > 0 else 0.2, 'P')
                put_gamma = greeks['gamma']
                put_theta = greeks['theta']
                put_vega = greeks['vega']
            else:
                put_code = ''
                put_price = put_iv = put_delta = put_gamma = put_theta = put_vega = 0
                put_volume = put_oi = put_iv_change = put_oi_change = 0
            
            strike_rows.append(StrikeRow(
                strike=float(strike),
                call_code=str(call_code),
                call_price=float(call_price),
                call_iv=float(call_iv) * 100 if call_iv else 0,
                call_iv_change=float(call_iv_change),
                call_delta=float(call_delta),
                call_gamma=float(call_gamma),
                call_theta=float(call_theta),
                call_vega=float(call_vega),
                call_volume=int(call_volume),
                call_oi=int(call_oi),
                call_oi_change=float(call_oi_change),
                put_code=str(put_code),
                put_price=float(put_price),
                put_iv=float(put_iv) * 100 if put_iv else 0,
                put_iv_change=float(put_iv_change),
                put_delta=float(put_delta),
                put_gamma=float(put_gamma),
                put_theta=float(put_theta),
                put_vega=float(put_vega),
                put_volume=int(put_volume),
                put_oi=int(put_oi),
                put_oi_change=float(put_oi_change)
            ))
        
        return expiry_list, strike_rows
    
    def calculate_thresholds(self, iv: float) -> Dict[str, float]:
        """计算IV变化阈值
        
        Args:
            iv: 当前IV (%)
        """
        if iv < 20:
            return {'noise': IV_CHANGE_LOW, 'significant': IV_CHANGE_LOW * 2, 'extreme': IV_CHANGE_LOW * 3}
        elif iv < 30:
            return {'noise': IV_CHANGE_MID, 'significant': IV_CHANGE_MID * 2, 'extreme': IV_CHANGE_MID * 3}
        else:
            return {'noise': IV_CHANGE_HIGH, 'significant': IV_CHANGE_HIGH * 2, 'extreme': IV_CHANGE_HIGH * 3}

# ==================== 数据库存储 ====================

class OptionDataStore:
    """期权数据存储 (SQLite)"""
    
    def __init__(self, db_path: str = 'option_data.db'):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # 期权日线数据
        c.execute('''CREATE TABLE IF NOT EXISTS option_daily
                     (symbol TEXT, trade_date TEXT, last_price REAL, 
                      iv REAL, delta REAL, gamma REAL, theta REAL, vega REAL,
                      volume INTEGER, oi INTEGER, PRIMARY KEY (symbol, trade_date))''')
        
        # 期权Session快照数据（用于日内变化计算）
        c.execute('''CREATE TABLE IF NOT EXISTS option_session_snapshots
                     (symbol TEXT, trade_date TEXT, session_type TEXT,
                      last_price REAL, iv REAL, volume INTEGER, oi INTEGER,
                      created_at TEXT,
                      PRIMARY KEY (symbol, trade_date, session_type))''')
        
        conn.commit()
        conn.close()
    
    def save_option_data(self, df: pd.DataFrame, trade_date: str):
        """保存期权数据"""
        if df is None or len(df) == 0 or not trade_date:
            return
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        for _, row in df.iterrows():
            code = row['合约代码']
            try:
                c.execute('''INSERT OR REPLACE INTO option_daily 
                             (symbol, trade_date, last_price, iv, delta, volume, oi)
                             VALUES (?, ?, ?, ?, ?, ?, ?)''',
                         (code, trade_date,
                          row.get('今结算') or row.get('今收盘'),
                          get_iv_from_data(row),
                          get_delta_from_data(row),
                          int(row.get('成交量(手)', 0) or 0),
                          int(row.get('持仓量', 0) or 0)))
            except:
                continue
        
        conn.commit()
        conn.close()
    
    def save_session_snapshot(self, df: pd.DataFrame, trade_date: str, session_type: str):
        """保存Session快照"""
        if df is None or len(df) == 0 or not trade_date:
            return
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for _, row in df.iterrows():
            code = row['合约代码']
            try:
                c.execute('''INSERT OR REPLACE INTO option_session_snapshots 
                             (symbol, trade_date, session_type, last_price, iv, volume, oi, created_at)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                         (code, trade_date, session_type,
                          row.get('今结算') or row.get('今收盘'),
                          get_iv_from_data(row),
                          int(row.get('成交量(手)', 0) or 0),
                          int(row.get('持仓量', 0) or 0),
                          now_str))
            except:
                continue
        conn.commit()
        conn.close()
    
    def get_session_snapshot(self, trade_date: str, session_type: str) -> pd.DataFrame:
        """获取指定Session的快照数据"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''SELECT symbol, last_price, iv, volume, oi, session_type
                     FROM option_session_snapshots WHERE trade_date = ? AND session_type = ?''',
                   (trade_date, session_type))
        rows = []
        for row in c.fetchall():
            rows.append({
                '合约代码': row[0], 'last_price': row[1], 'iv': row[2],
                'volume': row[3], 'oi': row[4], 'session_type': row[5]
            })
        conn.close()
        return pd.DataFrame(rows) if rows else pd.DataFrame()
    
    def get_latest_session_close(self, trade_date: str = None) -> tuple:
        """获取最近一次Session收盘的数据"""
        if trade_date is None:
            trade_date = datetime.now().strftime('%Y%m%d')
        now = datetime.now()
        hour = now.hour + now.minute / 60
        if hour >= 15:
            session_type = 'afternoon'
        elif hour >= 11.5:
            session_type = 'morning'
        else:
            dt = datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=1)
            trade_date = dt.strftime('%Y%m%d')
            session_type = 'afternoon'
        df = self.get_session_snapshot(trade_date, session_type)
        return session_type, df
    
    def get_prev_day_data(self, trade_date: str = None) -> pd.DataFrame:
        """获取昨日数据"""
        if trade_date is None:
            trade_date = datetime.now().strftime('%Y%m%d')
        
        # 计算昨天
        dt = datetime.strptime(trade_date, '%Y%m%d')
        dt -= timedelta(days=1)
        prev_date = dt.strftime('%Y%m%d')
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''SELECT symbol, last_price, iv, volume, oi 
                     FROM option_daily WHERE trade_date = ?''', (prev_date,))
        
        rows = []
        for row in c.fetchall():
            rows.append({
                '合约代码': row[0],
                'trade_date': row[1],
                'last_price': row[2],
                'iv': row[3],
                'volume': row[4],
                'oi': row[5]
            })
        
        conn.close()
        return pd.DataFrame(rows) if rows else pd.DataFrame()

# ==================== 主API类 ====================

class OptionChainAPI:
    """期权链API"""
    
    def __init__(self):
        self.analyzer = OptionChainAnalyzer()
        self.store = OptionDataStore()
        self.trade_date = None
        self._lock = threading.Lock()
        self._cache = {}
        self._cache_ttl = 300  # 缓存5分钟
    
    def get_full_chain(self) -> Dict[str, Any]:
        """获取完整期权链数据"""
        import warnings
        warnings.filterwarnings('ignore')
        
        with self._lock:
            now = time.time()
            
            # 检查缓存
            if self._cache and self._last_update:
                if now - self._last_update < self._cache_ttl:
                    return self._cache
            
            # 获取交易日期
            today = datetime.now()
            weekday = today.weekday()
            start_offset = 2 if weekday == 6 else (1 if weekday == 5 else 1)
            
            trade_date = None
            for i in range(start_offset, 15):
                dt = today - timedelta(days=i)
                date_str = dt.strftime('%Y%m%d')
                try:
                    df_test = ak.option_hist_czce(symbol='PTA期权', trade_date=date_str)
                    if df_test is not None and len(df_test) > 0:
                        trade_date = date_str
                        break
                except:
                    continue
            
            if trade_date is None:
                    return {'success': False, 'error': '无法获取交易日'}
            
            self.trade_date = trade_date
            
            # 获取当前数据
            df = AkshareOptionData.get_option_data(self.trade_date)
            
            if df is None or len(df) == 0:
                    return {'success': False, 'error': '获取期权数据失败'}
            
            # 获取最近Session收盘数据用于计算变化
            session_type, session_df = self.store.get_latest_session_close(self.trade_date)
            
            # 保存今日数据
            self.store.save_option_data(df, trade_date)
            
            # 构建T型报价（使用session数据计算变化）
            expiry_list, strike_rows = self.analyzer.build_t_type_quote(df, session_df)
            
            if len(strike_rows) == 0:
                return {'success': False, 'error': '解析期权数据失败'}
            
            # 计算ATM行权价
            S = self.analyzer.underlying_price
            atm_strike = round(S / 50) * 50  # PTA最小跳动50
            
            # 计算统计数据
            stats = self._calculate_stats(expiry_list, strike_rows)
            stats['session基准'] = session_type
            
            # 构建返回
            result = {
                'success': True,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'trade_date': self.trade_date,
                'underlying': 'CZCE.TA',
                'underlying_price': S,
                'atm_strike': atm_strike,
                'expiry_list': [asdict(e) for e in expiry_list],
                'strike_rows': [asdict(r) for r in strike_rows],
                'stats': stats
            }
            
            self._cache = result
            self._last_update = now
            
            return result
    
    def _last_update(self):
        return getattr(self, '_last_update', None)
    
    def _calculate_stats(self, expiry_list: List[ExpiryData], 
                         strike_rows: List[StrikeRow]) -> Dict[str, Any]:
        """计算统计数据"""
        if not expiry_list or not strike_rows:
            return {}
        
        # 近月数据
        near_expiry = expiry_list[0]
        
        # ATM附近的IV
        atm_row = next((r for r in strike_rows if r.strike == self.analyzer.underlying_price), None)
        if atm_row:
            call_iv = atm_row.call_iv
            put_iv = atm_row.put_iv
        else:
            call_ivs = [r.call_iv for r in strike_rows if r.call_iv > 0]
            put_ivs = [r.put_iv for r in strike_rows if r.put_iv > 0]
            call_iv = sum(call_ivs) / len(call_ivs) if call_ivs else 0
            put_iv = sum(put_ivs) / len(put_ivs) if put_ivs else 0
        
        return {
            'near_expiry': near_expiry.expiry,
            'volume_pcr': near_expiry.volume_pcr,
            'position_pcr': near_expiry.position_pcr,
            'avg_call_iv': round(call_iv, 2),
            'avg_put_iv': round(put_iv, 2),
            'iv_diff': round(put_iv - call_iv, 2),
            'total_call_oi': near_expiry.total_oi_call,
            'total_put_oi': near_expiry.total_oi_put
        }
    
    def get_volatility_cone(self) -> Dict[str, Any]:
        """获取波动率锥"""
        return {
            'success': True,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'note': '波动率锥需要历史数据积累'
        }


# ==================== 全局实例 ====================

_option_api = None
_option_api_lock = threading.Lock()

def get_option_api() -> OptionChainAPI:
    """获取API单例"""
    global _option_api
    with _option_api_lock:
        if _option_api is None:
            _option_api = OptionChainAPI()
        return _option_api


# ==================== Flask路由 ====================

def register_option_routes(app):
    """注册Flask路由"""
    from flask import Blueprint, jsonify
    
    option_bp = Blueprint('option', __name__, url_prefix='/api/option')
    
    @option_bp.route('/chain', methods=['GET'])
    def get_option_chain():
        """获取期权链T型报价"""
        api = get_option_api()
        result = api.get_full_chain()
        return jsonify(result)
    
    @option_bp.route('/stats', methods=['GET'])
    def get_option_stats():
        """获取期权统计数据"""
        api = get_option_api()
        result = api.get_full_chain()
        return jsonify(result.get('stats', {}))
    
    @option_bp.route('/vol_cone', methods=['GET'])
    def get_vol_cone():
        """获取波动率锥"""
        api = get_option_api()
        result = api.get_volatility_cone()
        return jsonify(result)
    
    @option_bp.route('/refresh', methods=['POST'])
    def refresh():
        """刷新数据"""
        api = get_option_api()
        api._cache = None
        api._last_update = None
        result = api.get_full_chain()
        return jsonify(result)
    
    app.register_blueprint(option_bp)
    
    return option_bp


# ==================== 测试 ====================

if __name__ == '__main__':
    import akshare as ak
    
    print("Option Chain API Test")
    print("=" * 50)
    
    api = OptionChainAPI()
    
    print("Fetching option chain...")
    result = api.get_full_chain()
    
    if result.get('success'):
        print(f"Timestamp: {result['timestamp']}")
        print(f"Trade Date: {result['trade_date']}")
        print(f"Underlying: {result['underlying']}")
        print(f"Underlying Price: {result['underlying_price']}")
        print(f"ATM Strike: {result['atm_strike']}")
        print(f"Expiry dates: {len(result['expiry_list'])}")
        print(f"Strike rows: {len(result['strike_rows'])}")
        
        stats = result.get('stats', {})
        print(f"\nStats:")
        print(f"  Near Expiry: {stats.get('near_expiry')}")
        print(f"  Volume PCR: {stats.get('volume_pcr')}")
        print(f"  Position PCR: {stats.get('position_pcr')}")
        print(f"  Avg Call IV: {stats.get('avg_call_iv')}%")
        print(f"  Avg Put IV: {stats.get('avg_put_iv')}%")
        print(f"  IV Diff: {stats.get('iv_diff')}%")
    else:
        print(f"Error: {result.get('error')}")
"""
期货数据获取模块
"""

import akshare as ak
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime


def get_futures_daily(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    获取期货日线数据
    
    Args:
        symbol: 期货合约代码，如 "CU"（铜）、"AU"（黄金）
        start_date: 开始日期，格式 YYYYMMDD
        end_date: 结束日期，格式 YYYYMMDD
    """
    try:
        df = ak.futures_zh_daily_sina(symbol=symbol)
        # 筛选日期范围
        df['date'] = pd.to_datetime(df['date'])
        start = datetime.strptime(start_date, "%Y%m%d")
        end = datetime.strptime(end_date, "%Y%m%d")
        df = df[(df['date'] >= start) & (df['date'] <= end)]
        return df
    except Exception as e:
        print(f"获取期货数据失败: {e}")
        return pd.DataFrame()


def get_futures_main(symbol_list: List[str]) -> Dict[str, str]:
    """
    获取各品种主力合约
    """
    result = {}
    try:
        df = ak.futuresZhMainHis(symbol="所有")
        for symbol in symbol_list:
            # 匹配主力合约
            match = df[df['symbol'].str.contains(symbol.upper(), na=False)]
            if not match.empty:
                result[symbol] = match.iloc[-1]['symbol']
    except Exception as e:
        print(f"获取主力合约失败: {e}")
    return result


def get_futures_basis(symbol: str, date: str) -> Optional[Dict]:
    """
    获取期货升贴水（基差）数据
    """
    try:
        # 现货价格
        spot_df = ak.spot_hist(symbol=symbol)
        # 期货价格
        futures_df = get_futures_daily(symbol, date, date)
        
        if spot_df.empty or futures_df.empty:
            return None
        
        spot_price = spot_df.iloc[-1]['close']
        futures_price = futures_df.iloc[-1]['close']
        basis = spot_price - futures_price
        
        return {
            "spot_price": spot_price,
            "futures_price": futures_price,
            "basis": basis,
            "date": date,
            "basis_type": "贴水" if basis > 0 else "升水"
        }
    except Exception as e:
        print(f"获取基差数据失败: {e}")
        return None


def get_futures_continuous(futures_code: str, start_date: str, 
                           end_date: str) -> pd.DataFrame:
    """
    获取期货连续合约数据（用于技术分析）
    """
    try:
        df = ak.futures_zh_daily_sina(symbol=futures_code)
        df['date'] = pd.to_datetime(df['date'])
        start = datetime.strptime(start_date, "%Y%m%d")
        end = datetime.strptime(end_date, "%Y%m%d")
        df = df[(df['date'] >= start) & (df['date'] <= end)]
        return df
    except Exception as e:
        print(f"获取连续合约失败: {e}")
        return pd.DataFrame()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AlphaLab - 统一数据加载接口

对标vnpy.alpha.lab.AlphaLab,提供统一的历史数据加载接口。

用法:
```python
from backtest.lab import AlphaLab

lab = AlphaLab()

# 加载K线数据
bars = lab.load_bar_data(
    vt_symbol="TA.CZCE",
    interval=Interval.MINUTE,
    start=datetime(2024, 1, 1),
    end=datetime(2024, 6, 30)
)

# 获取合约配置
settings = lab.load_contract_settings()
```
"""

from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Any
import json
import os

from vnpy.trader.constant import Interval, Exchange
from vnpy.trader.object import BarData


class AlphaLab:
    """
    Alpha量化实验室数据接口
    
    提供:
    - 历史K线数据加载
    - Tick数据加载
    - 合约配置管理
    - 数据缓存
    """
    
    def __init__(self, data_path: Optional[str] = None):
        """
        初始化AlphaLab
        
        Args:
            data_path: 数据目录路径,默认为项目data目录
        """
        if data_path is None:
            # 默认使用项目data目录
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            data_path = os.path.join(project_root, 'data')
        
        self.data_path = data_path
        
        # 数据缓存
        self._bar_cache: Dict[str, List[BarData]] = defaultdict(list)
        self._tick_cache: Dict[str, List] = defaultdict(list)
        
        # 合约配置
        self._contract_settings: Dict[str, Dict] = {}
        self._load_contract_settings()
    
    def _load_contract_settings(self) -> None:
        """加载合约配置"""
        # 默认配置
        default_settings = {
            "TA.CZCE": {
                "name": "PTA",
                "exchange": "CZCE",
                "size": 10,
                "pricetick": 2,
                "long_rate": 0.00005,
                "short_rate": 0.00005,
                "commission_rate": 0.00005,
                "margin_rate": 0.10,
            },
            "MA.CZCE": {
                "name": "甲醇",
                "exchange": "CZCE",
                "size": 10,
                "pricetick": 1,
                "long_rate": 0.00005,
                "short_rate": 0.00005,
                "commission_rate": 0.00005,
                "margin_rate": 0.10,
            },
            "RM.CZCE": {
                "name": "菜粕",
                "exchange": "CZCE",
                "size": 10,
                "pricetick": 1,
                "long_rate": 0.00005,
                "short_rate": 0.00005,
                "commission_rate": 0.00005,
                "margin_rate": 0.10,
            },
            "CF.CZCE": {
                "name": "棉花",
                "exchange": "CZCE",
                "size": 5,
                "pricetick": 5,
                "long_rate": 0.00005,
                "short_rate": 0.00005,
                "commission_rate": 0.00005,
                "margin_rate": 0.10,
            },
            "CU.SHF": {
                "name": "铜",
                "exchange": "SHFE",
                "size": 5,
                "pricetick": 10,
                "long_rate": 0.00005,
                "short_rate": 0.00005,
                "commission_rate": 0.000025,
                "margin_rate": 0.10,
            },
            "AU.SHF": {
                "name": "黄金",
                "exchange": "SHFE",
                "size": 1000,
                "pricetick": 0.02,
                "long_rate": 0.00005,
                "short_rate": 0.00005,
                "commission_rate": 0.00002,
                "margin_rate": 0.08,
            },
            "AG.SHF": {
                "name": "白银",
                "exchange": "SHFE",
                "size": 15,
                "pricetick": 1,
                "long_rate": 0.00005,
                "short_rate": 0.00005,
                "commission_rate": 0.00002,
                "margin_rate": 0.08,
            },
            "RB.SHF": {
                "name": "螺纹钢",
                "exchange": "SHFE",
                "size": 10,
                "pricetick": 1,
                "long_rate": 0.00005,
                "short_rate": 0.00005,
                "commission_rate": 0.00002,
                "margin_rate": 0.08,
            },
            "I.DCE": {
                "name": "铁矿石",
                "exchange": "DCE",
                "size": 100,
                "pricetick": 0.5,
                "long_rate": 0.00005,
                "short_rate": 0.00005,
                "commission_rate": 0.00002,
                "margin_rate": 0.08,
            },
            "M.DCE": {
                "name": "豆粕",
                "exchange": "DCE",
                "size": 10,
                "pricetick": 1,
                "long_rate": 0.00005,
                "short_rate": 0.00005,
                "commission_rate": 0.00005,
                "margin_rate": 0.07,
            },
        }
        
        self._contract_settings = default_settings
        
        # 尝试从文件加载用户配置
        config_file = os.path.join(self.data_path, 'contracts.json')
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    user_settings = json.load(f)
                    self._contract_settings.update(user_settings)
            except Exception as e:
                print(f"加载合约配置失败: {e}")
    
    def load_contract_setttings(self) -> Dict[str, Dict]:
        """获取所有合约配置"""
        return self._contract_settings.copy()
    
    def get_contract_setting(self, vt_symbol: str) -> Optional[Dict]:
        """获取指定合约配置"""
        return self._contract_settings.get(vt_symbol)
    
    def add_contract_setting(self, vt_symbol: str, setting: Dict) -> None:
        """添加/更新合约配置"""
        self._contract_settings[vt_symbol] = setting
    
    def load_bar_data(
        self,
        vt_symbol: str,
        interval: Interval,
        start: datetime,
        end: datetime
    ) -> List[BarData]:
        """
        加载K线数据
        
        Args:
            vt_symbol: 合约代码,如"TA.CZCE"
            interval: K线周期
            start: 开始时间
            end: 结束时间
            
        Returns:
            List[BarData]: K线数据列表
        """
        # 尝试从缓存加载
        cache_key = f"{vt_symbol}_{interval.value}"
        if cache_key in self._bar_cache:
            cached_bars = self._bar_cache[cache_key]
            return [b for b in cached_bars if start <= b.datetime <= end]
        
        # 尝试从CSV文件加载
        bars = self._load_bar_from_csv(vt_symbol, interval, start, end)
        
        if bars:
            self._bar_cache[cache_key] = bars
        
        return bars
    
    def _load_bar_from_csv(
        self,
        vt_symbol: str,
        interval: Interval,
        start: datetime,
        end: datetime
    ) -> List[BarData]:
        """从CSV文件加载K线数据"""
        import pandas as pd
        from vnpy.trader.utility import extract_vt_symbol
        
        symbol, exchange = extract_vt_symbol(vt_symbol)
        
        # 构造可能的文件名
        interval_str = self._interval_to_str(interval)
        possible_paths = [
            os.path.join(self.data_path, f"{symbol}_{interval_str}.csv"),
            os.path.join(self.data_path, f"{vt_symbol.replace('.', '_')}_{interval_str}.csv"),
            os.path.join(self.data_path, "bars", f"{symbol}_{interval_str}.csv"),
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                try:
                    df = pd.read_csv(path)
                    
                    if 'datetime' in df.columns:
                        df['datetime'] = pd.to_datetime(df['datetime'])
                    elif 'date' in df.columns:
                        df['datetime'] = pd.to_datetime(df['date'])
                    
                    # 过滤时间范围
                    df = df[(df['datetime'] >= start) & (df['datetime'] <= end)]
                    
                    # 转换为BarData
                    bars = []
                    for _, row in df.iterrows():
                        bar = BarData(
                            symbol=symbol,
                            exchange=Exchange[exchange] if isinstance(exchange, str) else exchange,
                            datetime=row['datetime'].to_pydatetime(),
                            interval=interval,
                            open_price=float(row['open']),
                            high_price=float(row['high']),
                            low_price=float(row['low']),
                            close_price=float(row['close']),
                            volume=float(row.get('volume', 0)),
                            gateway_name="CSV"
                        )
                        bars.append(bar)
                    
                    return bars
                    
                except Exception as e:
                    print(f"加载CSV失败 {path}: {e}")
                    continue
        
        return []
    
    def _interval_to_str(self, interval: Interval) -> str:
        """将Interval转换为字符串"""
        interval_map = {
            Interval.TICK: "tick",
            Interval.MINUTE: "1min",
            Interval.HOUR: "1h",
            Interval.DAILY: "1d",
        }
        return interval_map.get(interval, str(interval))
    
    def save_bar_data(
        self,
        vt_symbol: str,
        interval: Interval,
        bars: List[BarData],
        path: Optional[str] = None
    ) -> str:
        """
        保存K线数据到CSV
        
        Args:
            vt_symbol: 合约代码
            interval: K线周期
            bars: K线数据
            path: 保存路径
            
        Returns:
            保存的文件路径
        """
        import pandas as pd
        
        if path is None:
            interval_str = self._interval_to_str(interval)
            path = os.path.join(self.data_path, f"{vt_symbol.replace('.', '_')}_{interval_str}.csv")
        
        data = []
        for bar in bars:
            data.append({
                'datetime': bar.datetime,
                'symbol': bar.symbol,
                'exchange': bar.exchange.value if hasattr(bar.exchange, 'value') else bar.exchange,
                'interval': bar.interval.value if hasattr(bar.interval, 'value') else bar.interval,
                'open': bar.open_price,
                'high': bar.high_price,
                'low': bar.low_price,
                'close': bar.close_price,
                'volume': bar.volume,
            })
        
        df = pd.DataFrame(data)
        df.to_csv(path, index=False)
        
        print(f"已保存 {len(bars)} 根K线到 {path}")
        
        return path
    
    def clear_cache(self) -> None:
        """清空缓存"""
        self._bar_cache.clear()
        self._tick_cache.clear()
    
    def get_data_info(self) -> Dict[str, Any]:
        """获取数据信息"""
        info = {
            "data_path": self.data_path,
            "contract_count": len(self._contract_settings),
            "bar_cache_count": len(self._bar_cache),
            "tick_cache_count": len(self._tick_cache),
        }
        return info


# ==================== 数据转换 ====================

def bars_to_dataframe(bars: List[BarData]) -> "pd.DataFrame":
    """将BarData列表转换为DataFrame"""
    import pandas as pd
    
    data = []
    for bar in bars:
        data.append({
            'datetime': bar.datetime,
            'symbol': bar.vt_symbol,
            'open': bar.open_price,
            'high': bar.high_price,
            'low': bar.low_price,
            'close': bar.close_price,
            'volume': bar.volume,
        })
    
    return pd.DataFrame(data)


def dataframe_to_bars(
    df,
    vt_symbol: str,
    interval: Interval = Interval.MINUTE
) -> List[BarData]:
    """将DataFrame转换为BarData列表"""
    from vnpy.trader.utility import extract_vt_symbol
    
    bars = []
    symbol, exchange = extract_vt_symbol(vt_symbol)
    
    for _, row in df.iterrows():
        dt = row['datetime']
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace('T', ' '))
        
        bar = BarData(
            gateway_name="DATA",
            symbol=symbol,
            exchange=exchange,
            datetime=dt,
            interval=interval,
            open_price=float(row['open']),
            high_price=float(row['high']),
            low_price=float(row['low']),
            close_price=float(row['close']),
            volume=float(row.get('volume', 0)),
        )
        bars.append(bar)
    
    return bars


if __name__ == "__main__":
    # 测试
    print("AlphaLab 测试")
    print("=" * 50)
    
    lab = AlphaLab()
    
    # 获取合约配置
    settings = lab.load_contract_setttings()
    print(f"已加载 {len(settings)} 个合约配置")
    
    # 获取数据信息
    info = lab.get_data_info()
    print(f"数据路径: {info['data_path']}")
    
    print()
    print("支持的合约:")
    for vt_symbol, setting in list(settings.items())[:5]:
        print(f"  {vt_symbol}: {setting.get('name', setting.get('symbol', ''))}")

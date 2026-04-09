#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
期货品种配置管理
支持一键更换不同期货品种，自动选择主力合约和最近月期权合约
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import akshare as ak
import pandas as pd

class VarietyConfig:
    """期货品种配置管理类"""
    
    def __init__(self, config_file: str = "variety_config.json"):
        self.config_file = os.path.join(os.path.dirname(__file__), config_file)
        self.config = self._load_config()
        self.current_variety = self.config.get("current_variety", "PTA")
        
    def _load_config(self) -> Dict:
        """加载配置文件"""
        default_config = {
            "current_variety": "PTA",
            "varieties": {
                "PTA": {
                    "name": "精对苯二甲酸",
                    "exchange": "CZCE",
                    "futures_symbol": "TA",
                    "options_symbol": "TA",
                    "unit": "元/吨",
                    "contract_size": 5,
                    "tick_size": 2,
                    "margin_rate": 0.08,
                    "description": "PTA期货，郑州商品交易所",
                    "enabled": True,
                    "color": "#3498db",
                    "icon": "fas fa-flask"
                },
                "MA": {
                    "name": "甲醇",
                    "exchange": "CZCE",
                    "futures_symbol": "MA",
                    "options_symbol": "MA",
                    "unit": "元/吨",
                    "contract_size": 10,
                    "tick_size": 1,
                    "margin_rate": 0.08,
                    "description": "甲醇期货，郑州商品交易所",
                    "enabled": True,
                    "color": "#e74c3c",
                    "icon": "fas fa-gas-pump"
                },
                "SR": {
                    "name": "白糖",
                    "exchange": "CZCE",
                    "futures_symbol": "SR",
                    "options_symbol": "SR",
                    "unit": "元/吨",
                    "contract_size": 10,
                    "tick_size": 1,
                    "margin_rate": 0.07,
                    "description": "白糖期货，郑州商品交易所",
                    "enabled": True,
                    "color": "#f39c12",
                    "icon": "fas fa-candy-cane"
                },
                "CF": {
                    "name": "棉花",
                    "exchange": "CZCE",
                    "futures_symbol": "CF",
                    "options_symbol": "CF",
                    "unit": "元/吨",
                    "contract_size": 5,
                    "tick_size": 5,
                    "margin_rate": 0.07,
                    "description": "棉花期货，郑州商品交易所",
                    "enabled": True,
                    "color": "#9b59b6",
                    "icon": "fas fa-seedling"
                },
                "CU": {
                    "name": "铜",
                    "exchange": "SHFE",
                    "futures_symbol": "CU",
                    "options_symbol": "CU",
                    "unit": "元/吨",
                    "contract_size": 5,
                    "tick_size": 10,
                    "margin_rate": 0.10,
                    "description": "铜期货，上海期货交易所",
                    "enabled": True,
                    "color": "#d35400",
                    "icon": "fas fa-bolt"
                },
                "AL": {
                    "name": "铝",
                    "exchange": "SHFE",
                    "futures_symbol": "AL",
                    "options_symbol": "AL",
                    "unit": "元/吨",
                    "contract_size": 5,
                    "tick_size": 5,
                    "margin_rate": 0.08,
                    "description": "铝期货，上海期货交易所",
                    "enabled": True,
                    "color": "#7f8c8d",
                    "icon": "fas fa-cube"
                },
                "ZN": {
                    "name": "锌",
                    "exchange": "SHFE",
                    "futures_symbol": "ZN",
                    "options_symbol": "ZN",
                    "unit": "元/吨",
                    "contract_size": 5,
                    "tick_size": 5,
                    "margin_rate": 0.08,
                    "description": "锌期货，上海期货交易所",
                    "enabled": True,
                    "color": "#16a085",
                    "icon": "fas fa-shield-alt"
                },
                "NI": {
                    "name": "镍",
                    "exchange": "SHFE",
                    "futures_symbol": "NI",
                    "options_symbol": "NI",
                    "unit": "元/吨",
                    "contract_size": 1,
                    "tick_size": 10,
                    "margin_rate": 0.12,
                    "description": "镍期货，上海期货交易所",
                    "enabled": True,
                    "color": "#8e44ad",
                    "icon": "fas fa-magnet"
                }
            }
        }
        
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    # 合并配置，确保新添加的品种有默认值
                    for variety_code, variety_info in default_config["varieties"].items():
                        if variety_code not in loaded_config.get("varieties", {}):
                            loaded_config.setdefault("varieties", {})[variety_code] = variety_info
                    return loaded_config
        except Exception as e:
            print(f"[WARN] 加载品种配置失败: {e}")
        
        return default_config
    
    def save_config(self):
        """保存配置文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"[ERROR] 保存品种配置失败: {e}")
            return False
    
    def get_current_variety(self) -> Dict:
        """获取当前品种配置"""
        return self.config["varieties"].get(self.current_variety, {})
    
    def set_current_variety(self, variety_code: str) -> bool:
        """设置当前品种"""
        if variety_code in self.config["varieties"]:
            self.current_variety = variety_code
            self.config["current_variety"] = variety_code
            return self.save_config()
        return False
    
    def get_all_varieties(self) -> Dict[str, Dict]:
        """获取所有品种配置"""
        return self.config["varieties"]
    
    def get_enabled_varieties(self) -> Dict[str, Dict]:
        """获取启用的品种"""
        return {code: info for code, info in self.config["varieties"].items() 
                if info.get("enabled", True)}
    
    def add_variety(self, variety_code: str, variety_info: Dict) -> bool:
        """添加新品种"""
        if variety_code not in self.config["varieties"]:
            self.config["varieties"][variety_code] = variety_info
            return self.save_config()
        return False
    
    def update_variety(self, variety_code: str, updates: Dict) -> bool:
        """更新品种配置"""
        if variety_code in self.config["varieties"]:
            self.config["varieties"][variety_code].update(updates)
            return self.save_config()
        return False
    
    def enable_variety(self, variety_code: str, enabled: bool = True) -> bool:
        """启用/禁用品种"""
        return self.update_variety(variety_code, {"enabled": enabled})
    
    def get_main_contract(self, variety_code: str = None) -> Optional[str]:
        """获取主力合约代码"""
        if variety_code is None:
            variety_code = self.current_variety
        
        variety = self.config["varieties"].get(variety_code)
        if not variety:
            return None
        
        futures_symbol = variety.get("futures_symbol")
        
        if not futures_symbol:
            return None
        
        # akshare品种名称映射
        akshare_symbol_map = {
            'TA': 'PTA',      # PTA
            'MA': 'MA',       # 甲醇
            'SR': 'SR',       # 白糖
            'CF': 'CF',       # 棉花
            'CU': 'CU',       # 铜
            'AL': 'AL',       # 铝
            'ZN': 'ZN',       # 锌
            'NI': 'NI',       # 镍
            'AG': 'AG',       # 白银
            'AU': 'AU',       # 黄金
            'RB': 'RB',       # 螺纹钢
            'HC': 'HC',       # 热轧卷板
            'BU': 'BU',       # 沥青
            'RU': 'RU',       # 橡胶
            'SC': 'SC',       # 原油
            'FU': 'FU',       # 燃料油
        }
        
        try:
            # 获取期货实时行情
            akshare_symbol = akshare_symbol_map.get(futures_symbol, futures_symbol)
            df = ak.futures_zh_realtime(symbol=akshare_symbol)
            
            if df is not None and not df.empty:
                # 按成交量排序，取最大的作为主力合约
                if 'volume' in df.columns and df['volume'].notna().any():
                    df_sorted = df.sort_values('volume', ascending=False)
                    main_contract = df_sorted.iloc[0]['symbol']
                else:
                    # 如果没有成交量数据，取第一个合约
                    main_contract = df.iloc[0]['symbol']
                return main_contract
        except Exception as e:
            print(f"[WARN] 获取主力合约失败 {variety_code} (symbol={akshare_symbol}): {e}")
        
        # 返回默认合约
        return f"{futures_symbol}0"
    
    def get_nearest_option_contract(self, variety_code: str = None) -> Optional[str]:
        """获取最近月期权合约"""
        if variety_code is None:
            variety_code = self.current_variety
        
        variety = self.config["varieties"].get(variety_code)
        if not variety:
            return None
        
        options_symbol = variety.get("options_symbol")
        exchange = variety.get("exchange")
        
        if not options_symbol:
            return None
        
        try:
            # 获取期权合约列表
            df = ak.option_contract_info_ctp()
            if df is not None and not df.empty:
                # 过滤交易所和品种
                if exchange == "CZCE":
                    exchange_filter = 'CZCE'
                elif exchange == "SHFE":
                    exchange_filter = 'SHFE'
                else:
                    exchange_filter = exchange
                
                filtered = df[(df['交易所ID'] == exchange_filter) & 
                             (df['合约名称'].str.startswith(options_symbol, na=False))]
                
                if not filtered.empty:
                    # 按最后交易日排序，取最近的
                    filtered['最后交易日'] = pd.to_datetime(filtered['最后交易日'])
                    nearest = filtered.sort_values('最后交易日').iloc[0]
                    return nearest['合约名称']
        except Exception as e:
            print(f"[WARN] 获取期权合约失败 {variety_code}: {e}")
        
        return None
    
    def get_variety_data(self, variety_code: str = None) -> Dict:
        """获取品种的实时数据"""
        if variety_code is None:
            variety_code = self.current_variety
        
        variety = self.config["varieties"].get(variety_code)
        if not variety:
            return {}
        
        main_contract = self.get_main_contract(variety_code)
        option_contract = self.get_nearest_option_contract(variety_code)
        
        # 获取实时行情
        try:
            # akshare品种名称映射
            akshare_symbol_map = {
                'TA': 'PTA',      # PTA
                'MA': 'MA',       # 甲醇
                'SR': 'SR',       # 白糖
                'CF': 'CF',       # 棉花
                'CU': 'CU',       # 铜
                'AL': 'AL',       # 铝
                'ZN': 'ZN',       # 锌
                'NI': 'NI',       # 镍
                'AG': 'AG',       # 白银
                'AU': 'AU',       # 黄金
                'RB': 'RB',       # 螺纹钢
                'HC': 'HC',       # 热轧卷板
                'BU': 'BU',       # 沥青
                'RU': 'RU',       # 橡胶
                'SC': 'SC',       # 原油
                'FU': 'FU',       # 燃料油
            }
            
            futures_symbol = variety["futures_symbol"]
            akshare_symbol = akshare_symbol_map.get(futures_symbol, futures_symbol)
            df = ak.futures_zh_realtime(symbol=akshare_symbol)
            
            if df is not None and not df.empty:
                # 找到主力合约
                main_row = None
                for _, row in df.iterrows():
                    if row['symbol'] == main_contract:
                        main_row = row
                        break
                
                if main_row is None:
                    main_row = df.iloc[0]
                
                return {
                    "variety_code": variety_code,
                    "variety_name": variety["name"],
                    "main_contract": main_contract,
                    "option_contract": option_contract,
                    "last_price": float(main_row.get("trade", 0)),
                    "open": float(main_row.get("open", 0)),
                    "high": float(main_row.get("high", 0)),
                    "low": float(main_row.get("low", 0)),
                    "close": float(main_row.get("close", 0)),
                    "volume": int(main_row.get("volume", 0)),
                    "open_interest": int(main_row.get("position", 0)),
                    "change_pct": float(main_row.get("changepercent", 0)),
                    "timestamp": datetime.now().isoformat(),
                    "variety_info": variety
                }
        except Exception as e:
            print(f"[WARN] 获取品种数据失败 {variety_code}: {e}")
        
        return {
            "variety_code": variety_code,
            "variety_name": variety["name"],
            "main_contract": main_contract,
            "option_contract": option_contract,
            "timestamp": datetime.now().isoformat(),
            "variety_info": variety
        }


# 全局实例
variety_config = VarietyConfig()

if __name__ == "__main__":
    # 测试代码
    config = VarietyConfig()
    print("当前品种:", config.current_variety)
    print("当前品种配置:", config.get_current_variety())
    print("主力合约:", config.get_main_contract())
    print("最近月期权:", config.get_nearest_option_contract())
    
    # 测试切换品种
    config.set_current_variety("MA")
    print("\n切换后品种:", config.current_variety)
    print("甲醇主力合约:", config.get_main_contract("MA"))
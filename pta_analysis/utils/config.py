#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置管理模块
提供统一的配置加载和管理
"""

import os
import json
from typing import Dict, Any, Optional


class ConfigManager:
    """
    配置管理器
    支持从文件加载配置，支持默认值
    """
    
    def __init__(self, config_file: Optional[str] = None):
        """
        初始化配置管理器
        
        :param config_file: 配置文件路径
        """
        self._config: Dict[str, Any] = {}
        if config_file and os.path.exists(config_file):
            self.load_from_file(config_file)
    
    def load_from_file(self, config_file: str):
        """
        从文件加载配置
        
        :param config_file: 配置文件路径
        """
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                self._config = json.load(f)
        except Exception as e:
            print(f"加载配置文件失败: {e}")
    
    def save_to_file(self, config_file: str):
        """
        保存配置到文件
        
        :param config_file: 配置文件路径
        """
        try:
            # 确保目录存在
            dir_path = os.path.dirname(config_file)
            if dir_path and not os.path.exists(dir_path):
                os.makedirs(dir_path)
            
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存配置文件失败: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值
        
        :param key: 配置键，可以使用点分隔嵌套键，如 'database.host'
        :param default: 默认值
        :return: 配置值
        """
        keys = key.split('.')
        value = self._config
        
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default
    
    def set(self, key: str, value: Any):
        """
        设置配置值
        
        :param key: 配置键，可以使用点分隔嵌套键
        :param value: 配置值
        """
        keys = key.split('.')
        config = self._config
        
        for i, k in enumerate(keys[:-1]):
            if k not in config:
                config[k] = {}
            config = config[k]
        
        config[keys[-1]] = value
    
    def update(self, config_dict: Dict[str, Any]):
        """
        更新配置
        
        :param config_dict: 配置字典
        """
        self._config.update(config_dict)
    
    def get_all(self) -> Dict[str, Any]:
        """
        获取所有配置
        
        :return: 配置字典
        """
        return self._config


# 默认配置
DEFAULT_CONFIG = {
    'database': {
        'type': 'sqlite',
        'path': 'data/trading_data.sqlite',
        'host': 'localhost',
        'port': 3306,
        'username': '',
        'password': ''
    },
    'risk_control': {
        'max_drawdown': 0.1,
        'risk_per_trade': 0.01,
        'max_position_size': 0.1,
        'stop_loss_pct': 0.02,
        'take_profit_pct': 0.04
    },
    'backtest': {
        'initial_balance': 1000000.0,
        'commission_rate': 0.0001,
        'slippage': 0.0001
    },
    'trading': {
        'exchange': 'simulated',
        'api_key': '',
        'secret_key': '',
        'test_mode': True
    },
    'logging': {
        'level': 'INFO',
        'file': 'logs/trading.log',
        'console_output': True
    },
    'data': {
        'sources': ['simulated', 'tqsdk', 'akshare'],
        'update_interval': 60,
        'cache_duration': 3600
    }
}


def get_default_config() -> Dict[str, Any]:
    """
    获取默认配置
    
    :return: 默认配置字典
    """
    return DEFAULT_CONFIG.copy()


# 全局配置实例
config_manager = ConfigManager()
config_manager.update(DEFAULT_CONFIG)

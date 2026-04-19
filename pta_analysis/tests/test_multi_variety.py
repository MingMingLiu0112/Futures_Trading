#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试多品种期货分析平台
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from variety_config import VarietyConfig

def test_variety_config():
    """测试品种配置管理"""
    print("=" * 60)
    print("测试多品种期货分析平台")
    print("=" * 60)
    
    # 创建配置实例
    config = VarietyConfig()
    
    # 测试1: 获取当前品种
    print("1. 当前品种:", config.current_variety)
    current_info = config.get_current_variety()
    print(f"   名称: {current_info.get('name')}")
    print(f"   交易所: {current_info.get('exchange')}")
    print(f"   期货代码: {current_info.get('futures_symbol')}")
    
    # 测试2: 获取所有品种
    print("\n2. 可用品种列表:")
    enabled_varieties = config.get_enabled_varieties()
    for code, info in enabled_varieties.items():
        print(f"   {code}: {info.get('name')} ({info.get('exchange')})")
    
    # 测试3: 获取主力合约
    print("\n3. 主力合约测试:")
    for code in ['PTA', 'MA', 'SR', 'CU']:
        if code in enabled_varieties:
            main_contract = config.get_main_contract(code)
            print(f"   {code}: {main_contract}")
    
    # 测试4: 获取期权合约
    print("\n4. 期权合约测试:")
    for code in ['PTA', 'MA', 'SR', 'CU']:
        if code in enabled_varieties:
            option_contract = config.get_nearest_option_contract(code)
            print(f"   {code}: {option_contract or '无期权数据'}")
    
    # 测试5: 切换品种
    print("\n5. 品种切换测试:")
    test_codes = ['MA', 'SR', 'PTA']
    for code in test_codes:
        if code in enabled_varieties:
            success = config.set_current_variety(code)
            print(f"   切换到 {code}: {'成功' if success else '失败'}")
            if success:
                current = config.get_current_variety()
                print(f"     当前品种: {config.current_variety} - {current.get('name')}")
    
    # 测试6: 获取品种数据
    print("\n6. 品种数据获取测试:")
    for code in ['PTA', 'MA']:
        if code in enabled_varieties:
            data = config.get_variety_data(code)
            print(f"\n   {code} 数据:")
            print(f"     品种名称: {data.get('variety_name')}")
            print(f"     主力合约: {data.get('main_contract')}")
            print(f"     期权合约: {data.get('option_contract') or '无'}")
            if data.get('last_price'):
                print(f"     最新价: {data.get('last_price')}")
                print(f"     涨跌幅: {data.get('change_pct', 0):.2f}%")
    
    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)

if __name__ == "__main__":
    test_variety_config()
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试PTA品种功能
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from variety_config import VarietyConfig

def test_pta():
    """测试PTA品种"""
    print("=" * 60)
    print("测试PTA品种功能")
    print("=" * 60)
    
    # 创建配置实例
    config = VarietyConfig()
    
    # 确保当前品种是PTA
    config.set_current_variety("PTA")
    
    # 测试1: 获取当前品种
    print("1. 当前品种:", config.current_variety)
    current_info = config.get_current_variety()
    print(f"   名称: {current_info.get('name')}")
    print(f"   交易所: {current_info.get('exchange')}")
    print(f"   期货代码: {current_info.get('futures_symbol')}")
    
    # 测试2: 获取主力合约
    print("\n2. 获取主力合约:")
    main_contract = config.get_main_contract("PTA")
    print(f"   主力合约: {main_contract}")
    
    # 测试3: 获取期权合约
    print("\n3. 获取期权合约:")
    option_contract = config.get_nearest_option_contract("PTA")
    print(f"   最近月期权: {option_contract}")
    
    # 测试4: 获取品种数据
    print("\n4. 获取品种数据:")
    variety_data = config.get_variety_data("PTA")
    print(f"   品种名称: {variety_data.get('variety_name')}")
    print(f"   主力合约: {variety_data.get('main_contract')}")
    print(f"   期权合约: {variety_data.get('option_contract')}")
    
    if variety_data.get('last_price'):
        print(f"   最新价: {variety_data.get('last_price')}")
        print(f"   开盘价: {variety_data.get('open')}")
        print(f"   最高价: {variety_data.get('high')}")
        print(f"   最低价: {variety_data.get('low')}")
        print(f"   涨跌幅: {variety_data.get('change_pct', 0):.2f}%")
        print(f"   成交量: {variety_data.get('volume', 0):,}")
        print(f"   持仓量: {variety_data.get('open_interest', 0):,}")
    
    # 测试5: 测试切换功能
    print("\n5. 测试品种切换:")
    test_codes = ['MA', 'SR', 'CF', 'CU']
    for code in test_codes:
        if code in config.config["varieties"]:
            success = config.set_current_variety(code)
            print(f"   切换到 {code}: {'成功' if success else '失败'}")
            if success:
                current = config.get_current_variety()
                print(f"     当前品种: {config.current_variety} - {current.get('name')}")
    
    # 切换回PTA
    config.set_current_variety("PTA")
    
    print("\n" + "=" * 60)
    print("PTA测试完成!")
    print("=" * 60)

if __name__ == "__main__":
    test_pta()
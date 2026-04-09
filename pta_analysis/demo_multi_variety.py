#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多品种期货分析平台演示脚本
"""

import sys
import os
import time
import requests

sys.path.insert(0, os.path.dirname(__file__))

BASE_URL = "http://localhost:8001"

def print_header(title):
    """打印标题"""
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)

def demo_health_check():
    """演示健康检查"""
    print_header("1. 健康检查")
    
    try:
        response = requests.get(f"{BASE_URL}/health")
        data = response.json()
        print(f"状态: {data['status']}")
        print(f"服务: {data['service']}")
        print(f"版本: {data['version']}")
        print(f"时间: {data['timestamp']}")
    except Exception as e:
        print(f"错误: {e}")

def demo_variety_list():
    """演示品种列表"""
    print_header("2. 品种列表")
    
    try:
        response = requests.get(f"{BASE_URL}/api/variety/list")
        data = response.json()
        
        if data['success']:
            print(f"共有 {data['count']} 个品种:")
            for code, info in data['varieties'].items():
                print(f"  {code}: {info['name']} ({info['exchange']})")
                print(f"     单位: {info['unit']}, 合约大小: {info['contract_size']}吨/手")
                print(f"     最小变动: {info['tick_size']}, 保证金率: {info['margin_rate']*100}%")
        else:
            print(f"获取失败: {data.get('error', '未知错误')}")
    except Exception as e:
        print(f"错误: {e}")

def demo_current_variety():
    """演示当前品种"""
    print_header("3. 当前品种")
    
    try:
        response = requests.get(f"{BASE_URL}/api/variety/current")
        data = response.json()
        
        if data['success']:
            print(f"当前品种: {data['current_variety']}")
            info = data['variety_info']
            print(f"名称: {info['name']}")
            print(f"交易所: {info['exchange']}")
            print(f"描述: {info['description']}")
            print(f"图标: {info['icon']}, 颜色: {info['color']}")
        else:
            print(f"获取失败: {data.get('error', '未知错误')}")
    except Exception as e:
        print(f"错误: {e}")

def demo_switch_variety():
    """演示切换品种"""
    print_header("4. 切换品种演示")
    
    test_varieties = ['MA', 'SR', 'CF', 'PTA']
    
    for variety in test_varieties:
        try:
            print(f"\n切换到 {variety}...")
            response = requests.post(f"{BASE_URL}/api/variety/switch/{variety}")
            data = response.json()
            
            if data['success']:
                print(f"  成功: {data['message']}")
                
                # 获取切换后的数据
                time.sleep(0.5)  # 等待一下
                data_response = requests.get(f"{BASE_URL}/api/variety/{variety}/data")
                data_info = data_response.json()
                
                if data_info['success']:
                    variety_data = data_info['data']
                    print(f"  主力合约: {variety_data['main_contract']}")
                    print(f"  期权合约: {variety_data['option_contract'] or '无'}")
                else:
                    print(f"  获取数据失败")
            else:
                print(f"  失败: {data.get('error', '未知错误')}")
                
        except Exception as e:
            print(f"  错误: {e}")

def demo_variety_data():
    """演示品种数据"""
    print_header("5. PTA品种数据演示")
    
    try:
        # 确保切换到PTA
        requests.post(f"{BASE_URL}/api/variety/switch/PTA")
        time.sleep(1)
        
        # 获取PTA数据
        response = requests.get(f"{BASE_URL}/api/variety/PTA/data")
        data = response.json()
        
        if data['success']:
            variety_data = data['data']
            print(f"品种: {variety_data['variety_name']} ({variety_data['variety_code']})")
            print(f"主力合约: {variety_data['main_contract']}")
            print(f"期权合约: {variety_data['option_contract']}")
            print(f"更新时间: {variety_data['timestamp']}")
            
            # 如果有价格数据
            if variety_data.get('last_price'):
                print(f"\n实时行情:")
                print(f"  最新价: {variety_data['last_price']}")
                print(f"  开盘价: {variety_data['open']}")
                print(f"  最高价: {variety_data['high']}")
                print(f"  最低价: {variety_data['low']}")
                print(f"  涨跌幅: {variety_data['change_pct']:.2f}%")
                print(f"  成交量: {variety_data['volume']:,}")
                print(f"  持仓量: {variety_data['open_interest']:,}")
        else:
            print(f"获取失败: {data.get('error', '未知错误')}")
    except Exception as e:
        print(f"错误: {e}")

def demo_signal():
    """演示交易信号"""
    print_header("6. 交易信号演示")
    
    try:
        response = requests.get(f"{BASE_URL}/api/variety/PTA/signal")
        data = response.json()
        
        if data['success']:
            signal = data['signal']
            print(f"信号: {signal['signal']}")
            print(f"评分: {signal['score']}/100")
            print(f"理由: {signal['reason']}")
            print(f"强度: {signal['strength']}")
            print(f"时间: {signal['timestamp']}")
        else:
            print(f"获取失败: {data.get('error', '未知错误')}")
    except Exception as e:
        print(f"错误: {e}")

def demo_config():
    """演示配置信息"""
    print_header("7. 平台配置")
    
    try:
        response = requests.get(f"{BASE_URL}/api/config")
        data = response.json()
        
        if data['success']:
            config = data['config']
            print(f"当前品种: {config['current_variety']}")
            print(f"总品种数: {config['total_varieties']}")
            print(f"启用品种数: {config['enabled_varieties']}")
            print(f"\n启用品种:")
            for code, info in config['varieties'].items():
                print(f"  {code}: {info['name']}")
        else:
            print(f"获取失败: {data.get('error', '未知错误')}")
    except Exception as e:
        print(f"错误: {e}")

def main():
    """主函数"""
    print("=" * 60)
    print("多品种期货分析平台演示")
    print("=" * 60)
    print(f"API地址: {BASE_URL}")
    print("=" * 60)
    
    # 检查服务是否运行
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        if response.status_code == 200:
            print("✓ 服务运行正常")
        else:
            print("✗ 服务异常")
            return
    except:
        print("✗ 无法连接到服务，请先启动服务")
        print("启动命令: python3 multi_variety_main.py")
        return
    
    # 执行演示
    demo_health_check()
    demo_variety_list()
    demo_current_variety()
    demo_switch_variety()
    demo_variety_data()
    demo_signal()
    demo_config()
    
    print_header("演示完成")
    print("\n访问以下地址使用完整界面:")
    print(f"  http://localhost:8001")
    print("\nAPI文档:")
    print(f"  {BASE_URL}/docs (Swagger UI)")
    print(f"  {BASE_URL}/redoc (ReDoc)")

if __name__ == "__main__":
    main()
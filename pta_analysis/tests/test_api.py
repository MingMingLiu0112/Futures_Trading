#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试波动锥API端点
"""

import requests
import json
import time

BASE_URL = "http://localhost:5001/api/volatility"

def test_endpoint(endpoint, name):
    """测试API端点"""
    print(f"\n测试 {name} ({endpoint})...")
    try:
        start_time = time.time()
        response = requests.get(f"{BASE_URL}{endpoint}", timeout=10)
        elapsed = time.time() - start_time
        
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                print(f"  ✓ 成功 (耗时: {elapsed:.2f}s)")
                print(f"     数据大小: {len(json.dumps(data))} 字节")
                
                # 显示关键信息
                if 'data' in data:
                    if isinstance(data['data'], list):
                        print(f"     返回 {len(data['data'])} 条记录")
                    elif isinstance(data['data'], dict):
                        print(f"     返回字典数据")
                
                if 'timestamp' in data:
                    print(f"     时间戳: {data['timestamp']}")
                
                return True
            else:
                print(f"  ✗ 失败: {data.get('error', '未知错误')}")
                return False
        else:
            print(f"  ✗ HTTP错误: {response.status_code}")
            print(f"     响应: {response.text[:200]}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"  ✗ 请求异常: {e}")
        return False
    except json.JSONDecodeError as e:
        print(f"  ✗ JSON解析错误: {e}")
        return False

def main():
    print("=" * 60)
    print("波动锥API测试")
    print("=" * 60)
    
    # 测试各个端点
    endpoints = [
        ("/cone", "波动锥数据"),
        ("/iv-percentile", "IV百分位"),
        ("/signals", "交易信号"),
        ("/summary", "综合分析")
    ]
    
    results = []
    for endpoint, name in endpoints:
        success = test_endpoint(endpoint, name)
        results.append((name, success))
    
    # 测试图表端点
    print("\n测试图表端点...")
    chart_endpoints = [
        ("/chart/cone", "波动锥图表"),
        ("/chart/iv-distribution", "IV分布图表")
    ]
    
    for endpoint, name in chart_endpoints:
        print(f"\n测试 {name} ({endpoint})...")
        try:
            response = requests.get(f"{BASE_URL}{endpoint}", timeout=10)
            if response.status_code == 200:
                content_type = response.headers.get('content-type', '')
                if 'image' in content_type:
                    print(f"  ✓ 成功 - 返回图像 ({len(response.content)} 字节)")
                    results.append((name, True))
                else:
                    print(f"  ✗ 失败 - 未返回图像: {content_type}")
                    results.append((name, False))
            else:
                print(f"  ✗ HTTP错误: {response.status_code}")
                results.append((name, False))
        except Exception as e:
            print(f"  ✗ 异常: {e}")
            results.append((name, False))
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("测试结果汇总:")
    print("=" * 60)
    
    total = len(results)
    passed = sum(1 for _, success in results if success)
    
    for name, success in results:
        status = "✓ 通过" if success else "✗ 失败"
        print(f"  {status}: {name}")
    
    print(f"\n总计: {passed}/{total} 通过 ({passed/total*100:.1f}%)")
    
    if passed == total:
        print("\n🎉 所有测试通过!")
    else:
        print("\n⚠️  部分测试失败，请检查API服务")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
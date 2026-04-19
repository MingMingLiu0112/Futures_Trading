#!/usr/bin/env python3
"""
缠论Web界面测试脚本
"""

import requests
import json
import sys

def test_api_endpoints():
    """测试API接口"""
    base_url = "http://localhost:5000"
    
    endpoints = [
        "/api/chan_advanced",
        "/api/chan_signals",
        "/api/chan_bi",
        "/api/chan_xd",
        "/api/chan_zhongshu"
    ]
    
    print("=== 缠论API接口测试 ===\n")
    
    for endpoint in endpoints:
        try:
            url = base_url + endpoint
            print(f"测试 {endpoint}...")
            
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    print(f"  ✓ 成功: {data.get('count', 'N/A')} 条数据")
                    
                    # 显示部分数据
                    if 'summary' in data:
                        print(f"     摘要: {json.dumps(data['summary'], ensure_ascii=False)}")
                    elif 'signals' in data and data['signals']:
                        print(f"     最新信号: {data['signals'][0]['text']}")
                    elif 'bi_list' in data and data['bi_list']:
                        print(f"     笔数量: {len(data['bi_list'])}")
                    elif 'xd_list' in data and data['xd_list']:
                        print(f"     线段数量: {len(data['xd_list'])}")
                    elif 'zhongshu_list' in data and data['zhongshu_list']:
                        print(f"     中枢数量: {len(data['zhongshu_list'])}")
                else:
                    print(f"  ✗ 失败: {data.get('error', '未知错误')}")
            else:
                print(f"  ✗ HTTP错误: {response.status_code}")
                
        except requests.exceptions.ConnectionError:
            print(f"  ✗ 连接失败: 请确保Flask应用正在运行")
            break
        except Exception as e:
            print(f"  ✗ 异常: {e}")
        
        print()

def test_web_page():
    """测试Web页面"""
    print("=== Web页面测试 ===\n")
    
    try:
        response = requests.get("http://localhost:5000/chan_web", timeout=10)
        
        if response.status_code == 200:
            print("✓ 缠论Web页面可访问")
            
            # 检查页面内容
            content = response.text
            if "缠论分析系统" in content:
                print("✓ 页面标题正确")
            if "Chart.js" in content:
                print("✓ Chart.js已加载")
            if "Bootstrap" in content:
                print("✓ Bootstrap已加载")
            if "WebSocket" in content:
                print("✓ WebSocket支持已配置")
        else:
            print(f"✗ HTTP错误: {response.status_code}")
            
    except requests.exceptions.ConnectionError:
        print("✗ 连接失败: 请确保Flask应用正在运行")
    except Exception as e:
        print(f"✗ 异常: {e}")

def test_chan_advanced_module():
    """测试缠论分析模块"""
    print("\n=== 缠论分析模块测试 ===\n")
    
    try:
        from chan_advanced import ChanAdvancedAnalyzer
        
        analyzer = ChanAdvancedAnalyzer()
        
        # 测试数据获取
        print("测试数据获取...")
        df = analyzer.get_kline_data("TA", "1d")
        if not df.empty:
            print(f"✓ 获取到 {len(df)} 条K线数据")
            print(f"  时间范围: {df['datetime'].min()} 到 {df['datetime'].max()}")
        else:
            print("✗ 未获取到数据，使用模拟数据")
        
        # 测试完整分析
        print("\n测试完整分析...")
        result = analyzer.analyze("TA", "1d")
        
        if result.get('success'):
            summary = result.get('summary', {})
            print(f"✓ 分析成功")
            print(f"  笔数量: {summary.get('bi_count', 0)}")
            print(f"  线段数量: {summary.get('xd_count', 0)}")
            print(f"  中枢数量: {summary.get('zhongshu_count', 0)}")
            print(f"  分型数量: {summary.get('fenxing_count', 0)}")
            
            # 显示信号
            signals = result.get('signals', [])
            if signals:
                print(f"  最新信号: {signals[0]['text']}")
            
            # 显示分析结果
            analysis = result.get('analysis', {})
            if analysis:
                print(f"  趋势: {analysis.get('trend_text', '未知')}")
                print(f"  建议: {analysis.get('suggestion', '无')}")
        else:
            print(f"✗ 分析失败: {result.get('error', '未知错误')}")
            
    except ImportError as e:
        print(f"✗ 导入模块失败: {e}")
    except Exception as e:
        print(f"✗ 测试异常: {e}")

def main():
    """主函数"""
    print("缠论Web界面集成测试")
    print("=" * 50)
    
    # 检查Flask是否运行
    try:
        response = requests.get("http://localhost:5000/", timeout=2)
        if response.status_code == 200:
            print("✓ Flask应用正在运行\n")
        else:
            print("⚠ Flask应用可能未运行或端口被占用\n")
    except:
        print("⚠ 请先启动Flask应用: python web_app.py\n")
        return
    
    # 运行测试
    test_api_endpoints()
    test_web_page()
    test_chan_advanced_module()
    
    print("\n" + "=" * 50)
    print("测试完成！")
    print("\n访问以下地址查看缠论Web界面:")
    print("  http://localhost:5000/chan_web")
    print("\nAPI接口:")
    print("  http://localhost:5000/api/chan_advanced")

if __name__ == "__main__":
    main()
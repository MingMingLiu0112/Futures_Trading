#!/usr/bin/env python3
"""
期权链数据导出使用示例
"""

import requests
import json
import pandas as pd
from io import BytesIO

def example_usage():
    """使用示例"""
    print("=== 期权链数据导出系统使用示例 ===\n")
    
    base_url = "http://localhost:5000"
    
    # 1. 获取示例数据
    print("1. 获取示例数据JSON:")
    try:
        response = requests.get(f"{base_url}/api/data/sample")
        if response.status_code == 200:
            data = response.json()
            print(f"   ✓ 获取成功")
            print(f"   - 标的资产: {data['underlying']['symbol']}")
            print(f"   - 期权数量: {len(data['option_chain'])}")
            print(f"   - 数据生成时间: {data['generated_at']}")
        else:
            print(f"   ✗ 获取失败: {response.status_code}")
    except Exception as e:
        print(f"   ✗ 连接失败: {e}")
        print("   请先启动服务: python main.py")
        return
    
    # 2. 导出Excel文件
    print("\n2. 导出Excel文件:")
    try:
        response = requests.get(f"{base_url}/api/export/sample")
        if response.status_code == 200:
            # 保存文件
            filename = "option_chain_sample.xlsx"
            with open(filename, 'wb') as f:
                f.write(response.content)
            print(f"   ✓ 文件已保存: {filename}")
            
            # 读取并显示文件信息
            xls = pd.ExcelFile(filename)
            print(f"   - 包含Sheet: {', '.join(xls.sheet_names)}")
            
            # 显示各sheet数据量
            for sheet in xls.sheet_names:
                df = pd.read_excel(filename, sheet_name=sheet)
                print(f"   - {sheet}: {len(df)}行")
                
        else:
            print(f"   ✗ 导出失败: {response.status_code}")
    except Exception as e:
        print(f"   ✗ 导出失败: {e}")
    
    # 3. 健康检查
    print("\n3. 健康检查:")
    try:
        response = requests.get(f"{base_url}/api/health")
        if response.status_code == 200:
            health = response.json()
            print(f"   ✓ 系统状态: {health['status']}")
            print(f"   ✓ 版本: {health['version']}")
            print(f"   ✓ 时间: {health['timestamp']}")
        else:
            print(f"   ✗ 健康检查失败: {response.status_code}")
    except Exception as e:
        print(f"   ✗ 健康检查失败: {e}")
    
    # 4. 数据分析示例
    print("\n4. 数据分析示例:")
    try:
        # 读取导出的Excel文件
        df_options = pd.read_excel("option_chain_sample.xlsx", sheet_name='期权链数据')
        df_pcr = pd.read_excel("option_chain_sample.xlsx", sheet_name='PCR数据')
        
        # 分析看涨看跌比例
        call_count = len(df_options[df_options['type'] == 'call'])
        put_count = len(df_options[df_options['type'] == 'put'])
        print(f"   - 看涨期权: {call_count}个")
        print(f"   - 看跌期权: {put_count}个")
        print(f"   - 看涨看跌比例: {call_count/put_count:.2f}:1")
        
        # 分析IV分布
        avg_iv = df_options['implied_volatility'].mean()
        max_iv = df_options['implied_volatility'].max()
        min_iv = df_options['implied_volatility'].min()
        print(f"   - 平均IV: {avg_iv:.4f}")
        print(f"   - IV范围: {min_iv:.4f} - {max_iv:.4f}")
        
        # 分析PCR数据
        print(f"   - PCR数据天数: {len(df_pcr)}")
        for _, row in df_pcr.iterrows():
            print(f"   - {row['expiry']}: PCR成交量={row['pcr_volume']:.4f}, IV偏度={row['iv_skew']:.4f}")
            
    except Exception as e:
        print(f"   ✗ 数据分析失败: {e}")
    
    print("\n=== 使用示例完成 ===")
    print("\n下一步建议:")
    print("1. 查看生成的Excel文件: option_chain_sample.xlsx")
    print("2. 修改main.py中的_generate_sample_data()方法，接入真实数据源")
    print("3. 扩展API接口，支持更多数据格式和查询参数")

if __name__ == '__main__':
    example_usage()
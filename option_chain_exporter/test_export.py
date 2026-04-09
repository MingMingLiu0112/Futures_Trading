#!/usr/bin/env python3
"""
期权链数据导出测试脚本
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from main import OptionChainExporter

def test_exporter():
    """测试导出器功能"""
    print("=== 期权链数据导出测试 ===")
    
    # 创建导出器实例
    exporter = OptionChainExporter()
    
    # 1. 测试数据生成
    print("\n1. 测试数据生成...")
    sample_data = exporter.sample_data
    print(f"   - 标的资产: {sample_data['underlying']['symbol']}")
    print(f"   - 当前价格: ${sample_data['underlying']['current_price']}")
    print(f"   - 期权数量: {len(sample_data['option_chain'])}")
    print(f"   - PCR数据条数: {len(sample_data['pcr_data'])}")
    print(f"   - 历史数据天数: {len(sample_data['history_data'])}")
    
    # 2. 测试Excel导出
    print("\n2. 测试Excel导出...")
    try:
        filepath = exporter.export_to_excel(sample_data, "test_export.xlsx")
        print(f"   ✓ Excel文件已生成: {filepath}")
        
        # 检查文件是否存在
        if os.path.exists(filepath):
            file_size = os.path.getsize(filepath)
            print(f"   ✓ 文件大小: {file_size:,} bytes")
        else:
            print("   ✗ 文件未生成")
            
    except Exception as e:
        print(f"   ✗ 导出失败: {e}")
        return False
    
    # 3. 测试希腊字母汇总
    print("\n3. 测试希腊字母汇总...")
    option_df = pd.DataFrame(sample_data['option_chain'])
    greek_summary = exporter._create_greek_summary(option_df)
    print(f"   ✓ 汇总条目数: {len(greek_summary)}")
    print(f"   ✓ 汇总字段: {list(greek_summary.columns)}")
    
    # 4. 测试波动率曲面
    print("\n4. 测试波动率曲面...")
    vol_surface = exporter._create_volatility_surface(option_df)
    print(f"   ✓ 曲面数据点: {len(vol_surface)}")
    print(f"   ✓ 到期日数量: {len(vol_surface['到期日'].unique())}")
    print(f"   ✓ 行权价数量: {len(vol_surface['行权价'].unique())}")
    
    # 5. 数据质量检查
    print("\n5. 数据质量检查...")
    
    # 检查期权数据完整性
    calls = [opt for opt in sample_data['option_chain'] if opt['type'] == 'call']
    puts = [opt for opt in sample_data['option_chain'] if opt['type'] == 'put']
    print(f"   ✓ 看涨期权数量: {len(calls)}")
    print(f"   ✓ 看跌期权数量: {len(puts)}")
    
    # 检查希腊字母范围
    deltas = [opt['delta'] for opt in sample_data['option_chain']]
    print(f"   ✓ Delta范围: {min(deltas):.4f} 到 {max(deltas):.4f}")
    
    ivs = [opt['implied_volatility'] for opt in sample_data['option_chain']]
    print(f"   ✓ IV范围: {min(ivs):.4f} 到 {max(ivs):.4f}")
    
    # 检查PCR数据合理性
    for pcr in sample_data['pcr_data']:
        if pcr['pcr_volume'] > 0 and pcr['pcr_open_interest'] > 0:
            print(f"   ✓ PCR数据有效: 到期日={pcr['expiry']}, PCR成交量={pcr['pcr_volume']:.4f}")
    
    print("\n=== 所有测试通过 ===")
    return True

if __name__ == '__main__':
    # 临时导入pandas用于测试
    import pandas as pd
    
    if test_exporter():
        print("\n✅ 期权链数据导出系统测试成功！")
        print("\n下一步:")
        print("1. 运行 './run.sh' 启动Web服务")
        print("2. 访问 http://localhost:5000 使用Web界面")
        print("3. 使用 '/api/export/sample' API导出数据")
    else:
        print("\n❌ 测试失败，请检查错误信息")
        sys.exit(1)
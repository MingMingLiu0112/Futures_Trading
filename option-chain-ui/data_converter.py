#!/usr/bin/env python3
"""
PTA期权数据转换脚本
将现有PTA分析平台的期权数据转换为React组件所需格式
"""

import json
import pandas as pd
from datetime import datetime
from typing import Dict, List, Any
import numpy as np

def load_pta_option_data(csv_path: str) -> pd.DataFrame:
    """加载PTA平台的期权数据CSV文件"""
    try:
        df = pd.read_csv(csv_path)
        print(f"成功加载数据: {len(df)} 行, {len(df.columns)} 列")
        print("列名:", df.columns.tolist())
        return df
    except Exception as e:
        print(f"加载数据失败: {e}")
        # 返回示例数据
        return create_sample_data()

def create_sample_data() -> pd.DataFrame:
    """创建示例数据用于测试"""
    data = {
        '合约代码': ['TA605C4050', 'TA605C4100', 'TA605C4150', 'TA605P4050', 'TA605P4100', 'TA605P4150'],
        '行权价': [4050, 4100, 4150, 4050, 4100, 4150],
        '最新价': [85.5, 72.3, 60.1, 45.2, 55.8, 68.4],
        '涨跌幅': [2.5, 1.8, -0.5, -1.2, 0.8, 2.1],
        '持仓量': [1250, 2340, 1890, 1560, 2100, 1780],
        '持仓量变化': [120, -80, 150, -60, 90, -120],
        '成交量': [450, 320, 280, 380, 290, 410],
        '成交量变化': [50, -30, 40, -20, 60, -40],
        '隐含波动率': [0.215, 0.208, 0.202, 0.225, 0.218, 0.212],
        '隐波变化': [0.005, -0.003, 0.002, -0.004, 0.003, -0.002],
        'delta': [0.65, 0.58, 0.52, -0.45, -0.52, -0.58],
        'gamma': [0.012, 0.014, 0.016, 0.013, 0.015, 0.017],
        'theta': [-0.052, -0.048, -0.045, -0.046, -0.049, -0.053],
        'vega': [0.125, 0.118, 0.112, 0.128, 0.122, 0.118],
        'rho': [0.035, 0.032, 0.029, -0.028, -0.031, -0.035]
    }
    return pd.DataFrame(data)

def calculate_derived_fields(df: pd.DataFrame, underlying_price: float = 6920) -> pd.DataFrame:
    """计算衍生字段"""
    df = df.copy()
    
    # 计算百分比变化
    if '持仓量变化' in df.columns and '持仓量' in df.columns:
        df['持仓量变化率'] = (df['持仓量变化'] / (df['持仓量'] - df['持仓量变化']).replace(0, 1)) * 100
    
    if '成交量变化' in df.columns and '成交量' in df.columns:
        df['成交量变化率'] = (df['成交量变化'] / (df['成交量'] - df['成交量变化']).replace(0, 1)) * 100
    
    # 确定期权类型
    df['期权类型'] = df['合约代码'].apply(lambda x: 'C' if 'C' in str(x) else 'P')
    
    # 计算是否为平值期权（最接近标的物价格的行权价）
    if '行权价' in df.columns:
        atm_strike = find_atm_strike(df, underlying_price)
        df['平值期权'] = df['行权价'] == atm_strike
    
    # 标的物价格
    df['标的物价格'] = underlying_price
    
    return df

def find_atm_strike(df: pd.DataFrame, underlying_price: float) -> float:
    """找到最接近标的物价格的行权价"""
    if '行权价' not in df.columns:
        return underlying_price
    
    strikes = df['行权价'].unique()
    if len(strikes) == 0:
        return underlying_price
    
    # 找到最接近的行权价
    closest_strike = min(strikes, key=lambda x: abs(x - underlying_price))
    return closest_strike

def convert_to_component_format(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """转换为React组件所需格式"""
    result = []
    
    for _, row in df.iterrows():
        option_data = {
            'contractCode': str(row.get('合约代码', '')),
            'strikePrice': float(row.get('行权价', 0)),
            'optionType': str(row.get('期权类型', 'C')),
            'price': float(row.get('最新价', 0)),
            'priceChange': float(row.get('涨跌幅', 0)) if '涨跌幅' in row else 0,
            'priceChangePercent': float(row.get('涨跌幅', 0)),
            
            'openInterest': int(row.get('持仓量', 0)),
            'oiChange': int(row.get('持仓量变化', 0)),
            'oiChangePercent': float(row.get('持仓量变化率', 0)) if '持仓量变化率' in row else 0,
            
            'volume': int(row.get('成交量', 0)),
            'volumeChange': int(row.get('成交量变化', 0)),
            'volumeChangePercent': float(row.get('成交量变化率', 0)) if '成交量变化率' in row else 0,
            
            'impliedVol': float(row.get('隐含波动率', 0)),
            'ivChange': float(row.get('隐波变化', 0)),
            'ivChangeAbs': abs(float(row.get('隐波变化', 0))),
            
            'greeks': {
                'delta': float(row.get('delta', 0)),
                'gamma': float(row.get('gamma', 0)),
                'theta': float(row.get('theta', 0)),
                'vega': float(row.get('vega', 0)),
                'rho': float(row.get('rho', 0))
            },
            
            'underlyingPrice': float(row.get('标的物价格', 6920)),
            'timeToExpiry': 30,  # 默认30天到期
            'isATM': bool(row.get('平值期权', False))
        }
        result.append(option_data)
    
    return result

def calculate_market_stats(df: pd.DataFrame, underlying_price: float = 6920) -> Dict[str, Any]:
    """计算市场统计数据"""
    if df.empty:
        return get_default_stats()
    
    # 分离看涨和看跌
    calls = df[df['期权类型'] == 'C'] if '期权类型' in df.columns else pd.DataFrame()
    puts = df[df['期权类型'] == 'P'] if '期权类型' in df.columns else pd.DataFrame()
    
    # 计算总成交量和持仓量
    total_volume = df['成交量'].sum() if '成交量' in df.columns else 0
    total_oi = df['持仓量'].sum() if '持仓量' in df.columns else 0
    
    # Put/Call比率
    put_volume = puts['成交量'].sum() if not puts.empty and '成交量' in puts.columns else 0
    call_volume = calls['成交量'].sum() if not calls.empty and '成交量' in calls.columns else 0
    put_call_ratio = put_volume / call_volume if call_volume > 0 else 0
    
    # IV偏斜（看跌IV - 看涨IV）
    put_iv = puts['隐含波动率'].mean() if not puts.empty and '隐含波动率' in puts.columns else 0.2
    call_iv = calls['隐含波动率'].mean() if not calls.empty and '隐含波动率' in calls.columns else 0.2
    iv_skew = put_iv - call_iv
    
    # 最大痛点（简化计算）
    max_pain = find_atm_strike(df, underlying_price)
    
    return {
        'underlyingPrice': underlying_price,
        'atmStrike': find_atm_strike(df, underlying_price),
        'totalVolume': int(total_volume),
        'totalOI': int(total_oi),
        'putCallRatio': round(put_call_ratio, 3),
        'ivSkew': round(iv_skew, 4),
        'maxPain': float(max_pain),
        'updateTime': datetime.now().strftime('%H:%M:%S')
    }

def get_default_stats() -> Dict[str, Any]:
    """获取默认统计数据"""
    return {
        'underlyingPrice': 6920,
        'atmStrike': 6900,
        'totalVolume': 125430,
        'totalOI': 892150,
        'putCallRatio': 0.85,
        'ivSkew': -0.035,
        'maxPain': 6850,
        'updateTime': datetime.now().strftime('%H:%M:%S')
    }

def save_as_json(data: List[Dict], stats: Dict, output_path: str):
    """保存为JSON文件"""
    result = {
        'options': data,
        'stats': stats,
        'metadata': {
            'generatedAt': datetime.now().isoformat(),
            'count': len(data),
            'source': 'PTA期权分析平台'
        }
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"数据已保存到: {output_path}")
    print(f"期权数量: {len(data)}")
    print(f"看涨期权: {len([d for d in data if d['optionType'] == 'C'])}")
    print(f"看跌期权: {len([d for d in data if d['optionType'] == 'P'])}")

def main():
    """主函数"""
    print("PTA期权数据转换工具")
    print("=" * 50)
    
    # 输入文件路径（使用PTA平台的期权数据）
    input_csv = input("请输入PTA期权数据CSV文件路径（留空使用示例数据）: ").strip()
    
    if input_csv:
        df = load_pta_option_data(input_csv)
    else:
        print("使用示例数据...")
        df = create_sample_data()
    
    # 标的物价格
    try:
        underlying_price = float(input("请输入标的物价格（默认6920）: ") or "6920")
    except ValueError:
        underlying_price = 6920
        print(f"使用默认价格: {underlying_price}")
    
    # 处理数据
    print("\n处理数据...")
    df_processed = calculate_derived_fields(df, underlying_price)
    
    # 转换为组件格式
    component_data = convert_to_component_format(df_processed)
    
    # 计算市场统计
    market_stats = calculate_market_stats(df_processed, underlying_price)
    
    # 保存结果
    output_file = "option_data.json"
    save_as_json(component_data, market_stats, output_file)
    
    # 显示示例数据
    print("\n前3个期权数据示例:")
    for i, option in enumerate(component_data[:3]):
        print(f"\n{i+1}. {option['contractCode']}")
        print(f"   行权价: {option['strikePrice']}")
        print(f"   价格: {option['price']} ({option['priceChangePercent']:+}%)")
        print(f"   持仓变化: {option['oiChangePercent']:+}%")
        print(f"   成交变化: {option['volumeChangePercent']:+}%")
        print(f"   隐波变化: {option['ivChangeAbs']:+}")
    
    print("\n市场统计数据:")
    for key, value in market_stats.items():
        print(f"   {key}: {value}")
    
    print("\n转换完成！")
    print(f"JSON文件已生成: {output_file}")
    print("\n使用方法:")
    print("1. 将JSON文件放入React项目的public目录")
    print("2. 在组件中通过fetch('/option_data.json')加载数据")
    print("3. 或配置后端API返回相同格式的数据")

if __name__ == "__main__":
    main()
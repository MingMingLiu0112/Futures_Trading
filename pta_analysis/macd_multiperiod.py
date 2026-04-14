#!/usr/bin/env python3
"""
多时间级别MACD指标计算模块
支持1、5、15、30、60分钟级别的MACD计算
包含MACD柱体面积值计算功能
"""

import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

# 时间周期映射
PERIOD_MAP = {
    '1min': '1min',
    '5min': '5min', 
    '15min': '15min',
    '30min': '30min',
    '60min': '60min'
}

PERIOD_LABELS = {
    '1min': '1分钟',
    '5min': '5分钟',
    '15min': '15分钟', 
    '30min': '30分钟',
    '60min': '60分钟'
}

# MACD参数随周期调整配置
# 短周期用较小参数（响应更快），长周期用较大参数（更平滑，避免噪声）
# 原理：周期分钟数越大，EMA参数也应该越大以保持相似的信号特性
PERIOD_MACD_PARAMS = {
    '1min':  {'fast': 6,  'slow': 13, 'signal': 4},   # 最短周期，用较小参数
    '5min':  {'fast': 12, 'slow': 26, 'signal': 9},   # 标准参数
    '15min': {'fast': 12, 'slow': 26, 'signal': 9},   # 15分钟周期
    '30min': {'fast': 24, 'slow': 52, 'signal': 18},  # 30分钟用较大参数，更平滑
    '60min': {'fast': 24, 'slow': 52, 'signal': 18},  # 60分钟（日线级别参数）
}

# 周期分钟数映射
PERIOD_MINUTES = {
    '1min': 1,
    '5min': 5,
    '15min': 15,
    '30min': 30,
    '60min': 60
}

def get_macd_params_for_period(period='1min', user_fast=None, user_slow=None, user_signal=None, auto_scale=False):
    """
    获取指定周期的MACD参数
    
    如果用户指定了参数，使用用户参数；否则使用周期默认参数
    auto_scale=True时，根据周期分钟数自动计算参数
    
    参数:
        period: 时间周期 ('1min', '5min', '15min', '30min', '60min')
        user_fast: 用户指定的快线周期（可选）
        user_slow: 用户指定的慢线周期（可选）
        user_signal: 用户指定的信号线周期（可选）
        auto_scale: 是否自动根据周期缩放参数（默认False）
    
    返回:
        dict: 包含 fast, slow, signal 的字典
    """
    # 如果用户指定了参数，使用用户参数
    if user_fast is not None and user_slow is not None and user_signal is not None:
        return {'fast': user_fast, 'slow': user_slow, 'signal': user_signal}
    
    # 如果启用自动缩放，根据周期分钟数计算（平方根缩放，更平滑）
    if auto_scale:
        minutes = PERIOD_MINUTES.get(period, 1)
        # 使用平方根缩放：60min周期参数约为1min的√60≈7.7倍，但限制最大为4倍
        factor = min(4.0, max(0.5, (minutes ** 0.5) / 2.2))  # 归一化使5min的factor≈1
        base = {'fast': 12, 'slow': 26, 'signal': 9}
        return {
            'fast': max(4, int(base['fast'] * factor / 2 + 0.5)),
            'slow': max(8, int(base['slow'] * factor / 2 + 0.5)),
            'signal': max(3, int(base['signal'] * factor / 2 + 0.5))
        }
    
    # 否则使用周期适配参数
    return PERIOD_MACD_PARAMS.get(period, PERIOD_MACD_PARAMS['5min']).copy()

def calculate_macd(close_series, fast=12, slow=26, signal=9):
    """
    计算MACD指标
    
    参数:
    - close_series: 收盘价序列 (pandas Series)
    - fast: 快线周期 (默认12)
    - slow: 慢线周期 (默认26)
    - signal: 信号线周期 (默认9)
    
    返回:
    - dif: DIF线
    - dea: DEA线  
    - macd: MACD柱状图 (DIF-DEA)*2
    """
    # 计算EMA
    ema_fast = close_series.ewm(span=fast, adjust=False).mean()
    ema_slow = close_series.ewm(span=slow, adjust=False).mean()
    
    # 计算DIF和DEA
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    
    # 计算MACD柱状图
    macd = (dif - dea) * 2
    
    return dif, dea, macd

def calculate_macd_area(macd_series):
    """
    计算MACD柱体面积值
    
    参数:
    - macd_series: MACD柱状图序列
    
    返回:
    - areas: 面积列表，每个元素包含:
        - sign: 1表示正面积(红色)，-1表示负面积(绿色)
        - area: 面积值
        - bars: 包含的K线数量
    """
    areas = []
    current_area = 0
    current_sign = 0
    bars_in_current = 0
    
    for i, val in enumerate(macd_series):
        sign = 1 if val >= 0 else -1
        
        if sign == current_sign:
            # 同方向，累加面积
            current_area += val
            bars_in_current += 1
        else:
            # 方向改变，保存当前面积
            if current_sign != 0:
                areas.append({
                    'sign': current_sign,
                    'area': round(float(current_area), 6),
                    'bars': bars_in_current
                })
            
            # 开始新的面积计算
            current_area = val
            current_sign = sign
            bars_in_current = 1
    
    # 保存最后一个面积
    if current_sign != 0:
        areas.append({
            'sign': current_sign,
            'area': round(float(current_area), 6),
            'bars': bars_in_current
        })
    
    return areas

def get_macd_summary(macd_series):
    """
    获取MACD摘要信息
    
    参数:
    - macd_series: MACD柱状图序列
    
    返回:
    - summary: 包含正负面积和比例的字典
    """
    positive_area = sum(val for val in macd_series if val > 0)
    negative_area = sum(val for val in macd_series if val < 0)
    
    if negative_area != 0:
        area_ratio = abs(positive_area / negative_area)
    else:
        area_ratio = float('inf') if positive_area > 0 else 0
    
    return {
        'positive_area': round(float(positive_area), 4),
        'negative_area': round(float(abs(negative_area)), 4),
        'area_ratio': round(float(area_ratio), 4)
    }

def resample_data(df, period='5min'):
    """
    重采样数据到指定周期
    
    参数:
    - df: 原始DataFrame，包含datetime, open, high, low, close, volume列
    - period: 重采样周期，如'5min'表示5分钟
    
    返回:
    - resampled_df: 重采样后的DataFrame
    """
    if 'datetime' not in df.columns:
        raise ValueError("DataFrame必须包含'datetime'列")
    
    # 设置datetime为索引
    df_resample = df.set_index('datetime')
    
    # 重采样
    resampled = df_resample.resample(period).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()
    
    # 重置索引
    resampled = resampled.reset_index()
    
    return resampled

def analyze_macd_for_period(df, period='1min', fast=None, slow=None, signal=None):
    """
    分析指定周期的MACD指标
    
    参数:
    - df: 原始1分钟数据DataFrame
    - period: 时间周期 ('1min', '5min', '15min', '30min', '60min')
    - fast, slow, signal: MACD参数（可选，不指定时自动适配周期）
    
    返回:
    - result: 包含MACD分析结果的字典
    """
    # 获取周期适配的MACD参数
    macd_params = get_macd_params_for_period(period, fast, slow, signal)
    fast = macd_params['fast']
    slow = macd_params['slow']
    signal = macd_params['signal']
    
    # 获取周期代码
    period_code = PERIOD_MAP.get(period, '1min')
    
    # 重采样数据
    if period == '1min':
        period_df = df.copy()
    else:
        period_df = resample_data(df, period_code)
    
    # 计算MACD
    close_series = period_df['close']
    dif, dea, macd = calculate_macd(close_series, fast, slow, signal)
    
    # 计算面积
    areas = calculate_macd_area(macd)
    summary = get_macd_summary(macd)
    
    # 获取最新值
    last_idx = len(period_df) - 1
    last_row = period_df.iloc[-1]
    
    # 构建结果
    result = {
        'period': period,
        'period_label': PERIOD_LABELS.get(period, period),
        'datetime': last_row['datetime'].strftime('%Y-%m-%d %H:%M:%S'),
        'close': round(float(last_row['close']), 2),
        'bars': len(period_df),
        'macd': {
            'dif': round(float(dif.iloc[-1]), 4),
            'dea': round(float(dea.iloc[-1]), 4),
            'macd': round(float(macd.iloc[-1]), 4),
            'state': '多头' if macd.iloc[-1] > 0 else '空头',
            'fast': fast,
            'slow': slow,
            'signal': signal
        },
        'areas': areas[-5:],  # 返回最近5个面积
        'area_summary': summary
    }
    
    return result

def get_all_periods_macd(df, fast=None, slow=None, signal=None):
    """
    获取所有时间周期的MACD分析
    
    参数:
    - df: 原始1分钟数据DataFrame
    - fast, slow, signal: MACD参数（可选，不指定时自动适配周期）
    
    返回:
    - results: 各周期MACD分析结果的字典
    """
    results = {}
    
    for period in ['1min', '5min', '15min', '30min', '60min']:
        try:
            # 如果用户指定了参数，则使用用户参数；否则自动适配周期
            result = analyze_macd_for_period(df, period, fast, slow, signal)
            results[period] = result
        except Exception as e:
            print(f"计算{period}周期MACD时出错: {e}")
            results[period] = {'error': str(e)}
    
    return results

# 测试函数
if __name__ == '__main__':
    import akshare as ak
    
    print("测试多时间级别MACD计算模块...")
    
    # 获取测试数据
    df = ak.futures_zh_minute_sina(symbol='TA0', period='1')
    df.columns = [c.strip() for c in df.columns]
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.sort_values('datetime').tail(800).reset_index(drop=True)
    
    print(f"加载数据: {len(df)} 条1分钟K线")
    print(f"时间范围: {df['datetime'].iloc[0]} 到 {df['datetime'].iloc[-1]}")
    
    # 测试各周期MACD
    results = get_all_periods_macd(df)
    
    for period, result in results.items():
        if 'error' in result:
            print(f"\n{PERIOD_LABELS.get(period, period)}: 错误 - {result['error']}")
            continue
            
        macd_info = result['macd']
        summary = result['area_summary']
        
        print(f"\n【{result['period_label']}】{result['datetime']} 价格={result['close']:.0f} ({result['bars']}根)")
        print(f"  MACD: DIF={macd_info['dif']:.4f} DEA={macd_info['dea']:.4f} MACD={macd_info['macd']:.4f} [{macd_info['state']}]")
        print(f"  面积: 正面积={summary['positive_area']:.4f} 负面积={summary['negative_area']:.4f} 比例={summary['area_ratio']:.2f}")
        
        # 显示最近的面积
        for i, area in enumerate(result['areas']):
            sign_str = "红" if area['sign'] == 1 else "绿"
            print(f"  面积{i+1}: {sign_str} 面积={area['area']:.4f} {area['bars']}根")
    
    print("\n测试完成！")
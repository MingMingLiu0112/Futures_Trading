#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
历史波动锥和隐波百分位计算模块
功能：
1. 多时间窗口历史波动率分布计算
2. 当前隐波百分位计算
3. 可视化展示
4. 策略建议
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats
import warnings
import json
import os

warnings.filterwarnings('ignore')

# 配置
WORKSPACE = "/home/admin/.openclaw/workspace/codeman/pta_analysis"
DATA_DIR = f"{WORKSPACE}/data"
OUTPUT_DIR = f"{WORKSPACE}/static"

# 时间窗口配置（单位：天）
WINDOWS = [5, 10, 20, 30, 60, 90, 120, 250]

# 颜色配置
COLORS = {
    'cone': '#3498db',
    'current': '#e74c3c',
    'percentile': '#2ecc71',
    'median': '#f39c12',
    'q1_q3': '#95a5a6'
}


def load_pta_data():
    """加载PTA期货数据"""
    try:
        # 尝试加载日线数据
        df = pd.read_csv(f"{DATA_DIR}/pta_1day.csv")
        # 检查列名
        if 'datetime' in df.columns:
            df['date'] = pd.to_datetime(df['datetime'])
        elif 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
        else:
            # 尝试第一列
            df['date'] = pd.to_datetime(df.iloc[:, 0])
        
        df = df.sort_values('date')
        print(f"加载PTA日线数据: {len(df)}条记录，时间范围: {df['date'].min()} 到 {df['date'].max()}")
        return df
    except Exception as e:
        print(f"加载PTA日线数据失败: {e}")
        # 尝试其他数据文件
        try:
            df = pd.read_csv(f"{DATA_DIR}/pta_1min.csv")
            # 重采样为日线数据
            df['datetime'] = pd.to_datetime(df['datetime'])
            df.set_index('datetime', inplace=True)
            daily_df = df['close'].resample('D').last().reset_index()
            daily_df.rename(columns={'datetime': 'date'}, inplace=True)
            print(f"从1分钟数据生成日线数据: {len(daily_df)}条记录")
            return daily_df
        except Exception as e2:
            print(f"从1分钟数据生成日线数据也失败: {e2}")
            return None


def load_iv_data():
    """加载隐含波动率数据"""
    iv_data = {}
    for freq in ['1min', '5min', '15min', '30min', '60min']:
        try:
            file_path = f"{DATA_DIR}/ta_iv_{freq}.csv"
            if os.path.exists(file_path):
                df = pd.read_csv(file_path)
                df['datetime'] = pd.to_datetime(df['datetime'])
                df = df.sort_values('datetime')
                iv_data[freq] = df
                print(f"加载{freq} IV数据: {len(df)}条记录")
        except Exception as e:
            print(f"加载{freq} IV数据失败: {e}")
    return iv_data


def calculate_historical_volatility(df, window_days):
    """
    计算历史波动率
    Args:
        df: 包含'date'和'close'列的DataFrame
        window_days: 时间窗口（天）
    Returns:
        DataFrame with historical volatility
    """
    if df is None or len(df) < window_days:
        return None
    
    # 计算对数收益率
    df = df.copy()
    df['returns'] = np.log(df['close'] / df['close'].shift(1))
    
    # 计算滚动年化波动率（假设252个交易日）
    df[f'hv_{window_days}d'] = df['returns'].rolling(window=window_days).std() * np.sqrt(252) * 100
    
    return df


def calculate_all_hv_windows(df):
    """计算所有时间窗口的历史波动率"""
    if df is None:
        return None
    
    df_hv = df.copy()
    for window in WINDOWS:
        df_hv = calculate_historical_volatility(df_hv, window)
    
    return df_hv


def calculate_iv_percentile(iv_data, current_iv, lookback_days=250):
    """
    计算当前隐波百分位
    Args:
        iv_data: IV数据DataFrame
        current_iv: 当前IV值（百分比）
        lookback_days: 回溯天数
    Returns:
        percentile: 百分位（0-100）
        stats_dict: 统计信息
    """
    if iv_data is None or len(iv_data) == 0:
        return None, None
    
    # 获取最近lookback_days的数据
    cutoff_date = datetime.now() - timedelta(days=lookback_days)
    recent_iv = iv_data[iv_data['datetime'] >= cutoff_date]
    
    if len(recent_iv) == 0:
        return None, None
    
    # 获取ATM附近的IV（行权价在7000±100）
    atm_iv = recent_iv[
        (recent_iv['strike'] >= 6900) & 
        (recent_iv['strike'] <= 7100) &
        (recent_iv['iv_pct'].notna())
    ]['iv_pct']
    
    if len(atm_iv) == 0:
        return None, None
    
    # 计算百分位
    percentile = stats.percentileofscore(atm_iv.values, current_iv)
    
    # 统计信息
    stats_dict = {
        'current': current_iv,
        'mean': float(atm_iv.mean()),
        'median': float(atm_iv.median()),
        'std': float(atm_iv.std()),
        'min': float(atm_iv.min()),
        'max': float(atm_iv.max()),
        'q1': float(atm_iv.quantile(0.25)),
        'q3': float(atm_iv.quantile(0.75)),
        'count': int(len(atm_iv)),
        'percentile': float(percentile)
    }
    
    return percentile, stats_dict


def generate_volatility_cone_data(df_hv):
    """
    生成波动锥数据
    Returns:
        cone_data: 波动锥数据字典
    """
    if df_hv is None:
        return None
    
    cone_data = {}
    
    for window in WINDOWS:
        col_name = f'hv_{window}d'
        if col_name not in df_hv.columns:
            continue
        
        hv_series = df_hv[col_name].dropna()
        if len(hv_series) == 0:
            continue
        
        cone_data[window] = {
            'mean': float(hv_series.mean()),
            'median': float(hv_series.median()),
            'std': float(hv_series.std()),
            'min': float(hv_series.min()),
            'max': float(hv_series.max()),
            'q1': float(hv_series.quantile(0.25)),
            'q3': float(hv_series.quantile(0.75)),
            'current': float(hv_series.iloc[-1]) if not pd.isna(hv_series.iloc[-1]) else None,
            'count': int(len(hv_series))
        }
    
    return cone_data


def plot_volatility_cone(cone_data, output_path=None):
    """
    绘制波动锥图
    """
    if not cone_data:
        return None
    
    plt.figure(figsize=(12, 8))
    
    windows = list(cone_data.keys())
    means = [cone_data[w]['mean'] for w in windows]
    mins = [cone_data[w]['min'] for w in windows]
    maxs = [cone_data[w]['max'] for w in windows]
    q1s = [cone_data[w]['q1'] for w in windows]
    q3s = [cone_data[w]['q3'] for w in windows]
    currents = [cone_data[w]['current'] for w in windows if cone_data[w]['current'] is not None]
    
    # 绘制波动锥
    plt.fill_between(windows, mins, maxs, alpha=0.2, color=COLORS['cone'], label='波动范围')
    plt.fill_between(windows, q1s, q3s, alpha=0.4, color=COLORS['q1_q3'], label='25%-75%分位')
    plt.plot(windows, means, 'o-', color=COLORS['median'], linewidth=2, label='均值')
    
    # 绘制当前值
    if currents:
        current_windows = [w for w in windows if cone_data[w]['current'] is not None]
        plt.plot(current_windows, currents, 's-', color=COLORS['current'], 
                linewidth=3, markersize=10, label='当前值')
    
    plt.xlabel('时间窗口（天）', fontsize=12)
    plt.ylabel('年化波动率（%）', fontsize=12)
    plt.title('PTA期货历史波动锥', fontsize=16, fontweight='bold')
    plt.grid(True, alpha=0.3)
    plt.legend(fontsize=11)
    plt.xticks(windows)
    
    # 添加统计信息
    stats_text = f"数据统计（最新）:\n"
    for w in windows:
        if cone_data[w]['current'] is not None:
            stats_text += f"{w}天: {cone_data[w]['current']:.1f}%\n"
    
    plt.text(0.02, 0.98, stats_text, transform=plt.gca().transAxes,
             fontsize=10, verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    plt.tight_layout()
    
    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"波动锥图已保存: {output_path}")
    
    return plt.gcf()


def plot_iv_percentile_distribution(iv_data, current_iv, stats_dict, output_path=None):
    """
    绘制IV百分位分布图
    """
    if iv_data is None or stats_dict is None:
        return None
    
    # 获取ATM IV数据
    atm_iv = iv_data[
        (iv_data['strike'] >= 6900) & 
        (iv_data['strike'] <= 7100) &
        (iv_data['iv_pct'].notna())
    ]['iv_pct']
    
    if len(atm_iv) == 0:
        return None
    
    plt.figure(figsize=(12, 8))
    
    # 绘制分布直方图
    n, bins, patches = plt.hist(atm_iv, bins=50, alpha=0.7, 
                                color=COLORS['cone'], edgecolor='black')
    
    # 添加统计线
    plt.axvline(stats_dict['mean'], color=COLORS['median'], linestyle='--', 
                linewidth=2, label=f"均值: {stats_dict['mean']:.1f}%")
    plt.axvline(stats_dict['median'], color='orange', linestyle=':', 
                linewidth=2, label=f"中位数: {stats_dict['median']:.1f}%")
    plt.axvline(stats_dict['q1'], color=COLORS['q1_q3'], linestyle=':', 
                linewidth=1, alpha=0.7, label=f"25%分位: {stats_dict['q1']:.1f}%")
    plt.axvline(stats_dict['q3'], color=COLORS['q1_q3'], linestyle=':', 
                linewidth=1, alpha=0.7, label=f"75%分位: {stats_dict['q3']:.1f}%")
    
    # 添加当前值
    plt.axvline(current_iv, color=COLORS['current'], linestyle='-', 
                linewidth=3, label=f"当前IV: {current_iv:.1f}% ({stats_dict['percentile']:.1f}%)")
    
    # 填充百分位区域
    percentile = stats_dict['percentile']
    if percentile <= 25:
        color = 'green'
        region_label = f"低波动区域 ({percentile:.1f}%)"
    elif percentile <= 75:
        color = 'yellow'
        region_label = f"正常波动区域 ({percentile:.1f}%)"
    else:
        color = 'red'
        region_label = f"高波动区域 ({percentile:.1f}%)"
    
    plt.fill_betweenx([0, max(n)*1.1], current_iv-0.5, current_iv+0.5, 
                      alpha=0.3, color=color, label=region_label)
    
    plt.xlabel('隐含波动率（%）', fontsize=12)
    plt.ylabel('频数', fontsize=12)
    plt.title(f'PTA期权隐含波动率分布（{stats_dict["count"]}个样本）', fontsize=16, fontweight='bold')
    plt.grid(True, alpha=0.3)
    plt.legend(fontsize=11)
    
    # 添加统计信息
    stats_text = f"统计信息:\n"
    stats_text += f"当前IV: {current_iv:.1f}%\n"
    stats_text += f"百分位: {percentile:.1f}%\n"
    stats_text += f"均值: {stats_dict['mean']:.1f}%\n"
    stats_text += f"标准差: {stats_dict['std']:.1f}%\n"
    stats_text += f"范围: {stats_dict['min']:.1f}%-{stats_dict['max']:.1f}%"
    
    plt.text(0.02, 0.98, stats_text, transform=plt.gca().transAxes,
             fontsize=10, verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    plt.tight_layout()
    
    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"IV分布图已保存: {output_path}")
    
    return plt.gcf()


def generate_trading_signals(cone_data, iv_percentile, iv_stats):
    """
    生成交易策略建议
    """
    signals = []
    
    # 基于波动锥的信号
    if cone_data:
        # 检查短期 vs 长期波动率
        short_term = cone_data.get(20, {}).get('current')
        long_term = cone_data.get(120, {}).get('current')
        
        if short_term is not None and long_term is not None:
            if short_term > long_term * 1.2:
                signals.append({
                    'type': '波动率',
                    'signal': '短期波动率偏高',
                    'recommendation': '考虑卖出期权或做空波动率',
                    'confidence': '中'
                })
            elif short_term < long_term * 0.8:
                signals.append({
                    'type': '波动率',
                    'signal': '短期波动率偏低',
                    'recommendation': '考虑买入期权或做多波动率',
                    'confidence': '中'
                })
    
    # 基于IV百分位的信号
    if iv_percentile is not None:
        if iv_percentile <= 25:
            signals.append({
                'type': '隐含波动率',
                'signal': 'IV处于历史低位',
                'recommendation': '适合买入期权（做多波动率）',
                'confidence': '高'
            })
        elif iv_percentile >= 75:
            signals.append({
                'type': '隐含波动率',
                'signal': 'IV处于历史高位',
                'recommendation': '适合卖出期权（做空波动率）',
                'confidence': '高'
            })
        else:
            signals.append({
                'type': '隐含波动率',
                'signal': 'IV处于历史正常范围',
                'recommendation': '中性策略或方向性交易',
                'confidence': '低'
            })
    
    # 综合建议
    if signals:
        # 根据置信度排序
        confidence_map = {'高': 3, '中': 2, '低': 1}
        signals.sort(key=lambda x: confidence_map.get(x['confidence'], 0), reverse=True)
    
    return signals


def save_results(cone_data, iv_stats, signals, output_dir=OUTPUT_DIR):
    """保存结果到JSON文件"""
    results = {
        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'volatility_cone': cone_data,
        'iv_percentile': iv_stats,
        'trading_signals': signals,
        'metadata': {
            'windows': WINDOWS,
            'lookback_days': 250
        }
    }
    
    output_path = f"{output_dir}/volatility_analysis.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"分析结果已保存: {output_path}")
    return output_path


def main():
    """主函数"""
    print("=" * 60)
    print("PTA期货历史波动锥和隐波百分位分析")
    print("=" * 60)
    
    # 1. 加载数据
    print("\n1. 加载数据...")
    pta_data = load_pta_data()
    iv_data_dict = load_iv_data()
    
    if pta_data is None:
        print("错误: 无法加载PTA数据")
        return
    
    # 使用1分钟IV数据作为主要分析
    iv_data = iv_data_dict.get('1min')
    if iv_data is None:
        print("警告: 无法加载IV数据，将仅分析历史波动率")
    
    # 2. 计算历史波动率
    print("\n2. 计算历史波动率...")
    df_hv = calculate_all_hv_windows(pta_data)
    
    # 3. 生成波动锥数据
    print("\n3. 生成波动锥数据...")
    cone_data = generate_volatility_cone_data(df_hv)
    
    if cone_data:
        print(f"波动锥数据生成完成，包含{len(cone_data)}个时间窗口")
        for window, stats in cone_data.items():
            if stats['current'] is not None:
                print(f"  {window}天窗口: {stats['current']:.1f}% (范围: {stats['min']:.1f}%-{stats['max']:.1f}%)")
    
    # 4. 计算IV百分位
    print("\n4. 计算IV百分位...")
    current_iv = None
    iv_percentile = None
    iv_stats = None
    
    if iv_data is not None and len(iv_data) > 0:
        # 获取最新IV值（ATM附近）
        latest_iv = iv_data[
            (iv_data['strike'] >= 6900) & 
            (iv_data['strike'] <= 7100) &
            (iv_data['iv_pct'].notna())
        ]
        
        if len(latest_iv) > 0:
            current_iv = latest_iv['iv_pct'].iloc[-1]
            iv_percentile, iv_stats = calculate_iv_percentile(iv_data, current_iv)
            
            if iv_percentile is not None:
                print(f"当前IV: {current_iv:.1f}%")
                print(f"IV百分位: {iv_percentile:.1f}%")
                print(f"IV统计: 均值={iv_stats['mean']:.1f}%, 范围={iv_stats['min']:.1f}%-{iv_stats['max']:.1f}%")
    
    # 5. 生成交易信号
    print("\n5. 生成交易信号...")
    signals = generate_trading_signals(cone_data, iv_percentile, iv_stats)
    
    if signals:
        print(f"生成{len(signals)}个交易信号:")
        for i, signal in enumerate(signals, 1):
            print(f"  {i}. [{signal['type']}] {signal['signal']}")
            print(f"     建议: {signal['recommendation']} (置信度: {signal['confidence']})")
    
    # 6. 可视化
    print("\n6. 生成可视化图表...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # 波动锥图
    if cone_data:
        cone_chart_path = f"{OUTPUT_DIR}/volatility_cone.png"
        plot_volatility_cone(cone_data, cone_chart_path)
    
    # IV分布图
    if current_iv is not None and iv_stats is not None:
        iv_chart_path = f"{OUTPUT_DIR}/iv_percentile.png"
        plot_iv_percentile_distribution(iv_data, current_iv, iv_stats, iv_chart_path)
    
    # 7. 保存结果
    print("\n7. 保存分析结果...")
    json_path = save_results(cone_data, iv_stats, signals)
    
    print("\n" + "=" * 60)
    print("分析完成!")
    print("=" * 60)
    
    return {
        'cone_data': cone_data,
        'iv_percentile': iv_percentile,
        'iv_stats': iv_stats,
        'signals': signals,
        'charts': {
            'cone': cone_chart_path if cone_data else None,
            'iv_dist': iv_chart_path if current_iv else None
        }
    }


if __name__ == '__main__':
    main()
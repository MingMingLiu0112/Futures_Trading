#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA期权隐波(IV)高效计算
- merge_asof 快速匹配期货价格
- numpy向量化计算
"""
import numpy as np
import pandas as pd
from scipy.stats import norm
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')
import sys, os

WORKSPACE = '/home/admin/.openclaw/workspace/codeman/pta_analysis'
DATA_DIR = f'{WORKSPACE}/data'
EXPIRY_DATE = pd.Timestamp('2026-04-13')
RATE = 0.02

def calc_iv_batch(S, K, T, r, market_price, opt_type, max_iter=15):
    """批量IV计算（对每个单独计算但用numpy加速）"""
    result = np.full(len(S), np.nan)
    for i in range(len(S)):
        s, k, t, mp, ot = S[i], K[i], T[i], market_price[i], opt_type[i]
        if t <= 0 or mp <= 0 or s <= 0 or k <= 0:
            continue
        intrinsic = max(s - k, 0) if ot == 'C' else max(k - s, 0)
        if mp < intrinsic * 0.9:
            continue
        sigma = 0.3
        for _ in range(max_iter):
            d1 = (np.log(s / k) + (r + 0.5 * sigma**2) * t) / (sigma * np.sqrt(t))
            d2 = d1 - sigma * np.sqrt(t)
            c = s * norm.cdf(d1) - k * np.exp(-r * t) * norm.cdf(d2)
            p_val = k * np.exp(-r * t) * norm.cdf(-d2) - s * norm.cdf(-d1)
            p = c if ot == 'C' else p_val
            diff = p - mp
            if abs(diff) < 0.01:
                break
            vega = s * np.sqrt(t) * norm.pdf(d1)
            if abs(vega) < 1e-6:
                break
            sigma = max(0.01, min(sigma - diff / vega * 0.5, 3.0))
        result[i] = sigma
    return result


def process_level(in_file, out_file, sample_rate=1):
    """处理单个级别"""
    print(f'\n处理: {in_file}')
    df = pd.read_csv(in_file)

    # 只保留有效数据
    has_data = df[df['close'].notna() & (df['close'] > 0)].copy()
    has_data['datetime'] = pd.to_datetime(has_data['datetime'])
    print(f'  有效数据: {len(has_data)}行')

    # 采样（避免全部处理，减少时间）
    if sample_rate > 1:
        has_data = has_data.set_index('datetime')
        has_data = has_data.groupby([pd.Grouper(freq=f'{sample_rate}min'), 'symbol']).last().reset_index()
        print(f'  采样后: {len(has_data)}行')

    # 加载期货价格，用merge_asof快速匹配
    try:
        df_fut = pd.read_csv(f'{DATA_DIR}/pta_1min.csv')
        df_fut['datetime'] = pd.to_datetime(df_fut['datetime'])
        df_fut = df_fut[['datetime', 'close']].rename(columns={'close': 'S'})
        df_fut = df_fut.sort_values('datetime').reset_index(drop=True)

        has_data = has_data.sort_values('datetime').reset_index(drop=True)
        merged = pd.merge_asof(
            has_data,
            df_fut,
            on='datetime',
            direction='nearest',
            tolerance=pd.Timedelta('5min')
        )
        merged['S'] = merged['S'].fillna(6988.0)  # 默认PTA价格
        print(f'  期货价格匹配完成')
    except Exception as e:
        print(f'  期货价格匹配失败，使用默认值: {e}')
        merged = has_data.copy()
        merged['S'] = 6988.0

    # 计算T（年）
    T = (EXPIRY_DATE - merged['datetime']).total_seconds() / (365.25 * 24 * 3600)
    T = T.clip(lower=1e-6)

    # 提取数组
    S_arr = merged['S'].values.astype(float)
    K_arr = merged['strike'].values.astype(float)
    price_arr = merged['close'].values.astype(float)
    opt_type_arr = merged['opt_type'].values
    datetime_arr = merged['datetime'].values

    # IV计算
    print(f'  计算IV中 ({len(S_arr)}行)...')
    t0 = pd.Timestamp.now()
    iv_arr = calc_iv_batch(S_arr, K_arr, T.values, RATE, price_arr, opt_type_arr)
    elapsed = (pd.Timestamp.now() - t0).total_seconds()
    print(f'  IV计算完成，耗时 {elapsed:.1f}s')

    # 组装结果
    result = merged.copy()
    result['S_futures'] = S_arr
    result['iv'] = iv_arr
    result['iv_pct'] = iv_arr * 100
    result = result.dropna(subset=['iv'])

    result.to_csv(out_file, index=False)
    print(f'  → 保存: {out_file} ({len(result)}行有效IV)')

    # IV统计
    atm_mask = (np.abs(result['strike'].values - 7000) <= 150)
    atm_ivs = result.loc[atm_mask & (result['opt_type'] == 'C'), 'iv_pct']
    atm_ivp = result.loc[atm_mask & (result['opt_type'] == 'P'), 'iv_pct']
    if len(atm_ivs) > 0:
        print(f'\n  Call ATM IV: 均值={atm_ivs.mean():.1f}% 中位数={atm_ivs.median():.1f}%')
    if len(atm_ivp) > 0:
        print(f'  Put ATM IV:  均值={atm_ivp.mean():.1f}% 中位数={atm_ivp.median():.1f}%')

    # IV曲面
    latest_dt = result['datetime'].max()
    latest_df = result[result['datetime'] == latest_dt]
    print(f'\n  === IV曲面 ({latest_dt}) ===')
    print(f'  {"行权价":>6} | {"Call IV":>8} | {"Put IV":>8}')
    for strike in sorted(latest_df['strike'].unique()):
        s_df = latest_df[latest_df['strike'] == strike]
        c_iv = s_df[s_df['opt_type'] == 'C']['iv_pct'].mean()
        p_iv = s_df[s_df['opt_type'] == 'P']['iv_pct'].mean()
        print(f'  {strike:>6.0f} | {c_iv:>7.1f}% | {p_iv:>7.1f}%')

    return result


def main():
    print("=" * 60)
    print("PTA期权隐波(IV)反推计算")
    print("=" * 60)

    levels = [
        # (input, output, sample_rate_min)
        ('ta_option_60min.csv', 'ta_iv_60min.csv', 1),
        ('ta_option_30min.csv', 'ta_iv_30min.csv', 1),
        ('ta_option_15min.csv', 'ta_iv_15min.csv', 1),
        ('ta_option_5min.csv',  'ta_iv_5min.csv',  1),
        ('ta_option_1min.csv', 'ta_iv_1min.csv',  5),   # 1min每5分钟采样
    ]

    for in_f, out_f, sample in levels:
        in_path = f'{DATA_DIR}/{in_f}'
        out_path = f'{DATA_DIR}/{out_f}'
        if os.path.exists(in_path):
            try:
                process_level(in_path, out_path, sample_rate=sample)
            except Exception as e:
                print(f'  错误: {e}')
                import traceback
                traceback.print_exc()
        else:
            print(f'  跳过: {in_f} 不存在')

    print("\n" + "=" * 60)
    print("完成!")

if __name__ == '__main__':
    main()

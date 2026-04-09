#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA期权隐波(IV)反推计算
使用 Black-Scholes 模型 + Brent's Method 反推隐含波动率
"""
import pandas as pd
import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

WORKSPACE = '/home/admin/.openclaw/workspace/codeman/pta_analysis'
DATA_DIR = f'{WORKSPACE}/data'

EXPIRY = datetime(2026, 4, 13)
RATE = 0.02  # 近似无风险利率


def black_scholes_price(S, K, T, r, sigma, option_type='C'):
    """Black-Scholes期权定价公式"""
    if T <= 0 or sigma <= 0:
        return np.nan
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if option_type == 'C':
        price = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:
        price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    return price


def bs_iv_brent(S, K, T, r, market_price, option_type='C'):
    """用Brent方法反推隐含波动率"""
    if T <= 0 or market_price <= 0 or S <= 0 or K <= 0:
        return np.nan

    # 内在价值
    if option_type == 'C':
        intrinsic = max(S - K, 0)
    else:
        intrinsic = max(K - S, 0)

    # 最低价不能低于内在价值
    if market_price < intrinsic * 0.95:
        return np.nan

    def objective(sigma):
        return black_scholes_price(S, K, T, r, sigma, option_type) - market_price

    try:
        # IV范围: 0.01 (1%) ~ 2.0 (200%)
        iv = brentq(objective, 0.01, 2.0, maxiter=100)
        return iv
    except (ValueError, RuntimeError):
        return np.nan


def load_futures_price(dt):
    """从期货分钟数据获取对应时间的价格"""
    try:
        # 1min数据
        df_f = pd.read_csv(f'{DATA_DIR}/pta_1min.csv')
        df_f['datetime'] = pd.to_datetime(df_f['datetime'])
        # 找最接近的时间
        diff = (df_f['datetime'] - dt).abs()
        idx = diff.idxmin()
        price = df_f.loc[idx, 'close'] if not pd.isna(df_f.loc[idx, 'close']) else None
        return price
    except:
        return None


def compute_iv_for_level(level='1min', sample=False):
    """计算指定级别的IV"""
    print(f'\n=== {level} IV计算 ===')

    df = pd.read_csv(f'{DATA_DIR}/ta_option_{level}.csv')
    has_data = df[df['close'].notna() & (df['close'] > 0)].copy()
    print(f'有效数据: {len(has_data)}行')

    if sample:
        has_data = has_data.sample(n=min(5000, len(has_data)), random_state=42)
        print(f'采样: {len(has_data)}行')

    # 获取期货价格（只加载一次）
    df_fut = None
    try:
        df_fut = pd.read_csv(f'{DATA_DIR}/pta_1min.csv')
        df_fut['datetime'] = pd.to_datetime(df_fut['datetime'])
        print(f'期货数据: {len(df_fut)}条, {df_fut["datetime"].min()} ~ {df_fut["datetime"].max()}')
    except Exception as e:
        print(f'期货数据加载失败: {e}')

    results = []
    ivs = []

    for i, (_, row) in enumerate(has_data.iterrows()):
        if i > 0 and i % 5000 == 0:
            print(f'  进度: {i}/{len(has_data)}')

        dt = pd.to_datetime(row['datetime'])
        S = None

        # 匹配期货价格
        if df_fut is not None:
            try:
                diff = (df_fut['datetime'] - dt).abs()
                idx = diff.idxmin()
                s_val = df_fut.loc[idx, 'close']
                S = float(s_val) if not pd.isna(s_val) and s_val > 0 else None
            except:
                S = None

        # 备选：用固定价格（6988）
        if S is None:
            S = 6988.0

        K = float(row['strike'])
        market_price = float(row['close'])
        opt_type = 'C' if row['opt_type'] == 'C' else 'P'

        # 计算剩余期限(年)
        T = (EXPIRY - dt).total_seconds() / (365.25 * 24 * 3600)
        if T <= 0:
            continue

        iv = bs_iv_brent(S, K, T, RATE, market_price, opt_type)

        results.append({
            'datetime': dt,
            'symbol': row['symbol'],
            'strike': K,
            'opt_type': opt_type,
            'S': S,
            'option_price': market_price,
            'T': T,
            'iv': iv,
            'iv_pct': iv * 100 if iv and not np.isnan(iv) else np.nan
        })

        if iv and not np.isnan(iv):
            ivs.append(iv * 100)

    result_df = pd.DataFrame(results)

    # 保存
    out_file = f'{DATA_DIR}/ta_iv_{level}.csv'
    result_df.to_csv(out_file, index=False)
    print(f'  → 保存: {out_file}')

    if ivs:
        print(f'\n  IV统计 ({len(ivs)}个有效样本):')
        print(f'    ATM附近IV:')
        atm_strike = 7000
        atm_ivs = result_df[(result_df['strike'] >= atm_strike - 100) &
                              (result_df['strike'] <= atm_strike + 100) &
                              result_df['iv'].notna()]['iv_pct']
        if len(atm_ivs) > 0:
            print(f'      均值: {atm_ivs.mean():.1f}%')
            print(f'      中位数: {atm_ivs.median():.1f}%')
            print(f'      最新: {atm_ivs.iloc[-1]:.1f}%')
        print(f'    全合约IV均值: {np.mean(ivs):.1f}%')
        print(f'    IV范围: {np.min(ivs):.1f}% ~ {np.max(ivs):.1f}%')

    return result_df


def main():
    print("=" * 60)
    print("PTA期权隐波(IV)反推计算")
    print("=" * 60)

    # 先看期货数据
    try:
        df_f = pd.read_csv(f'{DATA_DIR}/pta_1min.csv')
        df_f['datetime'] = pd.to_datetime(df_f['datetime'])
        print(f"\nPTA期货1min: {len(df_f)}条")
        print(f"  价格范围: {df_f['close'].min():.0f} ~ {df_f['close'].max():.0f}")
        print(f"  时间范围: {df_f['datetime'].min()} ~ {df_f['datetime'].max()}")
    except Exception as e:
        print(f"  期货数据加载失败: {e}")

    # 计算各级别IV
    for level in ['1min', '5min', '15min', '30min', '60min']:
        try:
            compute_iv_for_level(level, sample=False)
        except Exception as e:
            print(f'{level} 计算失败: {e}')

    print("\n" + "=" * 60)
    print("完成!")
    print("=" * 60)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA期权历史数据采集
日线 + 各级别K线（尽量从TQSdk/东财获取）
"""
import sys, os, time, warnings
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

sys.path.insert(0, '/home/admin/.openclaw/workspace/codeman/pta_analysis')
warnings.filterwarnings('ignore')

WORKSPACE = '/home/admin/.openclaw/workspace/codeman/pta_analysis'
DATA_DIR = f'{WORKSPACE}/data'
os.makedirs(DATA_DIR, exist_ok=True)

PTA_FUTURE_PRICE = 6988  # 当前期货价

# ===================== TQSdk 获取期权K线 =====================
def fetch_option_kline_tqsdk(symbol, duration_sec, data_length=8000):
    """用TQSdk获取期权K线"""
    try:
        from tqsdk import TqApi, TqAuth, TqKq

        api = TqApi(TqKq(), auth=TqAuth('mingmingliu', 'Liuzhaoning2025'))
        duration_map = {
            60: '60s', 300: '300s', 900: '900s',
            1800: '1800s', 3600: '3600s', 86400: '86400s'
        }
        dur = duration_map.get(duration_sec, f'{duration_sec}s')

        klines = api.get_kline_serial(symbol, dur, data_length=data_length)
        api.close()

        # 转换
        if klines is not None and not klines.empty:
            df = klines.copy()
            if 'datetime' in df.columns:
                df['datetime'] = pd.to_datetime(df['datetime'])
            return df
    except Exception as e:
        print(f"  TQSdk {symbol} ({dur}) error: {e}")
    return None

# ===================== 东财期权日线 =====================
def fetch_option_daily_em():
    """从东财获取期权日线数据"""
    import requests

    records = []
    # 遍历主要行权价
    atm_strike = round(PTA_FUTURE_PRICE / 100) * 100
    strikes_to_fetch = list(range(atm_strike - 600, atm_strike + 700, 100))

    for strike in strikes_to_fetch:
        for opt_type, suffix in [('C', 'C'), ('P', 'P')]:
            # 东财期权代码格式
            # 需要先查合约ID，再拿历史
            pass

    return records

# ===================== 用akshare CZCE期权历史 =====================
def fetch_option_hist_czce_daily():
    """akshare CZCE期权历史 - 尝试不同合约"""
    import akshare as ak

    all_data = []

    # TA605 到期日4/13，当前主力
    # akshare option_hist_czce 签名: (symbol='白糖期权', trade_date='20191017')
    # symbol参数似乎是品种名而非合约名

    # 先查所有可用的symbol
    # 试几个可能的品种名格式
    test_symbols = ['TA', 'PTA', 'TA605', 'TA605C', 'TA605P']

    for sym in test_symbols:
        try:
            df = ak.option_hist_czce(symbol=sym, trade_date='20260403')
            if df is not None and not df.empty:
                print(f"  {sym}: {df.shape} ✓")
                all_data.append((sym, df))
        except Exception as e:
            print(f"  {sym}: {str(e)[:50]}")

    return all_data

# ===================== 主采集逻辑 =====================
def main():
    print("=" * 60)
    print("PTA期权数据采集")
    print("=" * 60)

    # 1. 保存期权合约信息
    print("\n[1] 期权合约信息...")
    import akshare as ak
    df_ctp = ak.option_contract_info_ctp()
    ta_ctp = df_ctp[(df_ctp['交易所ID'] == 'CZCE') &
                     (df_ctp['合约名称'].str.startswith('TA', na=False))].copy()
    ta_ctp['opt_type'] = ta_ctp['期权类型'].map({'1': 'C', '2': 'P'})
    ta_ctp.to_csv(f'{DATA_DIR}/ta_option_contracts.csv', index=False)
    print(f"  合约数: {len(ta_ctp)}, 到期: {ta_ctp['最后交易日'].iloc[0]}")

    # 2. 用TQSdk获取主力期权K线数据
    print("\n[2] TQSdk获取期权K线...")
    atm_strike = round(PTA_FUTURE_PRICE / 100) * 100  # 7000
    durations = [
        (60, '1min', 8000),
        (300, '5min', 8000),
        (900, '15min', 8000),
        (1800, '30min', 8000),
        (3600, '60min', 8000),
        (86400, '1day', 2488),
    ]

    # 获取几个关键行权价的期权
    key_strikes = [atm_strike - 200, atm_strike, atm_strike + 200]  # 6800, 7000, 7200
    opt_types = [('C', 'C'), ('P', 'P')]

    for dur_sec, dur_name, data_len in durations:
        print(f"\n  === {dur_name} ===")
        dur_records = []

        for strike in key_strikes:
            for opt_label, opt_suffix in opt_types:
                # TQSdk合约代码格式: CZCE.TA605C6800
                # 当前主力是TA605 (4/13到期)
                symbol = f'CZCE.TA605{opt_suffix}{strike}'
                df = fetch_option_kline_tqsdk(symbol, dur_sec, data_len)
                if df is not None and not df.empty:
                    df = df.copy()
                    df['strike'] = strike
                    df['opt_type'] = opt_label
                    df['symbol'] = symbol
                    dur_records.append(df)
                    print(f"    {symbol}: {len(df)}条")
                time.sleep(0.3)

        if dur_records:
            combined = pd.concat(dur_records, ignore_index=True)
            combined = combined.sort_values('datetime').reset_index(drop=True)
            out_file = f'{DATA_DIR}/ta_option_{dur_name}.csv'
            combined.to_csv(out_file, index=False)
            print(f"    → 保存: {out_file} ({len(combined)}条)")

    # 3. CZCE期权历史
    print("\n[3] CZCE期权历史(akshare)...")
    results = fetch_option_hist_czce_daily()
    for name, df in results:
        out = f'{DATA_DIR}/ta_option_czce_{name}.csv'
        df.to_csv(out, index=False)
        print(f"  → {out}: {df.shape}")

    print("\n" + "=" * 60)
    print("采集完成!")
    print("=" * 60)

    # 打印数据总览
    print("\n数据总览:")
    for f in sorted(os.listdir(DATA_DIR)):
        if 'option' in f:
            fpath = f'{DATA_DIR}/{f}'
            size = os.path.getsize(fpath)
            rows = sum(1 for _ in open(fpath)) - 1
            print(f"  {f}: {rows}行 ({size/1024:.0f}KB)")

if __name__ == '__main__':
    main()

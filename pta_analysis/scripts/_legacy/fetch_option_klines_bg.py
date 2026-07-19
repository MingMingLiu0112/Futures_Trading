#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA期权数据采集 - 后台运行版
用TQSdk获取期权分钟K线数据，写入CSV
"""
import sys, os, time, warnings
from datetime import datetime
import pandas as pd

sys.path.insert(0, '/home/admin/.openclaw/workspace/codeman/pta_analysis')
warnings.filterwarnings('ignore')

DATA_DIR = '/home/admin/.openclaw/workspace/codeman/pta_analysis/data'
os.makedirs(DATA_DIR, exist_ok=True)

LOG_FILE = f'{DATA_DIR}/option_fetch.log'

def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')

def fetch_option_klines():
    """用TQSdk获取ATM附近期权的各级别K线"""
    from tqsdk import TqApi, TqAuth, TqKq

    PTA_PRICE = 6988
    atm = round(PTA_PRICE / 100) * 100  # 7000

    # TA605 (4月13日到期) ATM±3档
    strikes = [atm - 200, atm - 100, atm, atm + 100, atm + 200, atm + 300]
    opt_types = [('C', 'C'), ('P', 'P')]

    # 级别: (duration_sec, name, data_length)
    durations = [
        (60, '1min', 8000),
        (300, '5min', 8000),
        (900, '15min', 8000),
        (1800, '30min', 8000),
        (3600, '60min', 8000),
    ]

    log('TQSdk 连接...')
    try:
        api = TqApi(TqKq(), auth=TqAuth('mingmingliu', 'Liuzhaoning2025'))
        log('TQSdk 连接成功')
    except Exception as e:
        log(f'TQSdk 连接失败: {e}')
        return

    all_results = {}

    for dur_sec, dur_name, data_len in durations:
        log(f'--- {dur_name} ---')
        dur_records = []

        for strike in strikes:
            for opt_label, opt_suffix in opt_types:
                symbol = f'CZCE.TA605{opt_suffix}{strike}'
                try:
                    klines = api.get_kline_serial(symbol, dur_sec, data_length=data_len)
                    # 等待数据
                    for _ in range(30):
                        api.wait_update(deadline=time.time() + 1)
                        if klines is not None and not klines.empty:
                            break

                    if klines is not None and not klines.empty:
                        df = klines.copy()
                        if 'datetime' in df.columns:
                            df['datetime'] = pd.to_datetime(df['datetime'])
                        df['strike'] = strike
                        df['opt_type'] = opt_label
                        df['symbol'] = symbol
                        dur_records.append(df)
                        log(f'  {symbol}: {len(df)}条 ✓')
                    else:
                        log(f'  {symbol}: 无数据')
                except Exception as e:
                    log(f'  {symbol}: 错误 {e}')

        if dur_records:
            combined = pd.concat(dur_records, ignore_index=True)
            combined = combined.sort_values('datetime').reset_index(drop=True)
            out_file = f'{DATA_DIR}/ta_option_{dur_name}.csv'
            combined.to_csv(out_file, index=False)
            all_results[dur_name] = len(combined)
            log(f'  → 保存 {out_file} ({len(combined)}条)')

    api.close()
    log(f'完成! 保存: {all_results}')

if __name__ == '__main__':
    log('=== 期权数据采集开始 ===')
    log(f'PTA价格: 6988')
    try:
        fetch_option_klines()
    except Exception as e:
        log(f'采集异常: {e}')
    log('=== 期权数据采集结束 ===')

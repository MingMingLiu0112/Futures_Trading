#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA期货历史数据采集 - 扩充版
优先用 akshare TA0（2006年至今），分钟线用 TQSdk
"""
import sys, os, time, warnings
from datetime import datetime
import pandas as pd

sys.path.insert(0, '/home/admin/.openclaw/workspace/codeman/pta_analysis')
warnings.filterwarnings('ignore')

WORKSPACE = '/home/admin/.openclaw/workspace/codeman/pta_analysis'
DATA_DIR = f'{WORKSPACE}/data'
os.makedirs(DATA_DIR, exist_ok=True)

LOG_FILE = f'{DATA_DIR}/data_fetch.log'

def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')

def fetch_futures_daily_akshare():
    """用akshare获取PTA日线（2006年至今）"""
    import akshare as ak

    log('[期货日线] akshare TA0 (2006-至今)...')
    try:
        df = ak.futures_zh_daily_sina(symbol='TA0')
        if df is not None and not df.empty:
            df = df.sort_values('date').reset_index(drop=True)
            df['symbol'] = 'TA0'
            df['duration'] = 86400
            out = f'{DATA_DIR}/pta_1day_akshare.csv'
            df.to_csv(out, index=False)
            log(f'  → {out}: {len(df)}条 ({df["date"].min()} ~ {df["date"].max()})')
            return df
    except Exception as e:
        log(f'  错误: {e}')
    return None

def fetch_futures_minute_tqsdk():
    """用TQSdk获取PTA各级别分钟数据"""
    from tqsdk import TqApi, TqAuth, TqKq

    log('[期货分钟] TQSdk CZCE.TA...')

    try:
        api = TqApi(TqKq(), auth=TqAuth('mingmingliu', 'Liuzhaoning2025'))
    except Exception as e:
        log(f'  TQSdk连接失败: {e}')
        return

    durations = [
        (60, 'pta_1min', 8000),
        (300, 'pta_5min', 8000),
        (900, 'pta_15min', 8000),
        (1800, 'pta_30min', 8000),
        (3600, 'pta_60min', 8000),
    ]

    for dur_sec, name, data_len in durations:
        try:
            klines = api.get_kline_serial('KQ.m@CZCE.TA', dur_sec, data_length=data_len)
            for _ in range(30):
                api.wait_update(deadline=time.time() + 1)
                if klines is not None and not klines.empty:
                    break

            if klines is not None and not klines.empty:
                df = klines.copy()
                if 'datetime' in df.columns:
                    df['datetime'] = pd.to_datetime(df['datetime'])
                df['symbol'] = 'KQ.m@CZCE.TA'
                out = f'{DATA_DIR}/{name}.csv'
                df.to_csv(out, index=False)
                valid = df[df['close'].notna() & (df['close'] > 0)]
                log(f'  {name}: {len(df)}条, 有效{len(valid)}条 ({valid["datetime"].min()} ~ {valid["datetime"].max()})')
            else:
                log(f'  {name}: 无数据')
        except Exception as e:
            log(f'  {name} 错误: {e}')

    api.close()

def main():
    log('=== PTA数据采集开始 ===')

    # 1. 期货日线（akshare，更长历史）
    df_daily = fetch_futures_daily_akshare()

    # 2. 期货分钟线（TQSdk）
    fetch_futures_minute_tqsdk()

    log('=== PTA数据采集完成 ===')

    # 汇总
    log('\n数据汇总:')
    for f in sorted(os.listdir(DATA_DIR)):
        if f.startswith('pta_') or f.startswith('ta_option_'):
            fp = f'{DATA_DIR}/{f}'
            size = os.path.getsize(fp)
            rows = sum(1 for _ in open(fp)) - 1
            log(f'  {f}: {rows}行 ({size/1024:.0f}KB)')

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA期权数据采集脚本
从 TQSdk 获取期权链行情 + 历史数据
"""
import sys, os, json, warnings
from datetime import datetime, timedelta
import pandas as pd

sys.path.insert(0, '/home/admin/.openclaw/workspace/codeman/pta_analysis')
warnings.filterwarnings('ignore')

WORKSPACE = '/home/admin/.openclaw/workspace/codeman/pta_analysis'
DATA_DIR = f'{WORKSPACE}/data'

def fetch_option_chain_tqsdk():
    """用TQSdk获取PTA期权链实时行情"""
    from tqsdk import TqApi, TqAuth, TqKq

    api = TqApi(TqKq(), auth=TqAuth('mingmingliu', 'Liuzhaoning2025'))

    records = []
    # TA605期权 - C=认购, P=认沽
    strikes = list(range(3800, 4700, 50))  # 3800~4650

    for strike in strikes:
        for opt_type in ['C', 'P']:
            symbol_c = f'CZCE.TA605{opt_type}{strike}'
            try:
                q = api.get_quote(symbol_c)
                if q and q.last_price and q.last_price > 0:
                    records.append({
                        'symbol': symbol_c,
                        'strike': strike,
                        'type': 'Call' if opt_type == 'C' else 'Put',
                        'last_price': q.last_price,
                        'bid': q.bid_price1 if hasattr(q, 'bid_price1') else None,
                        'ask': q.ask_price1 if hasattr(q, 'ask_price1') else None,
                        'volume': q.volume if hasattr(q, 'volume') else None,
                        'open_interest': q.open_interest if hasattr(q, 'open_interest') else None,
                        'iv': q.implied_volatility if hasattr(q, 'implied_volatility') and q.implied_volatility > 0 else None,
                        'delta': q.delta if hasattr(q, 'delta') else None,
                        'gamma': q.gamma if hasattr(q, 'gamma') else None,
                        'theta': q.theta if hasattr(q, 'theta') else None,
                        'vega': q.vega if hasattr(q, 'vega') else None,
                        'timestamp': datetime.now().isoformat()
                    })
            except Exception as e:
                pass

    api.close()
    return records

def fetch_option_chain_ctp():
    """从CTP接口获取期权链信息"""
    import akshare as ak

    df = ak.option_contract_info_ctp()
    ta = df[(df['交易所ID'] == 'CZCE') & (df['合约名称'].str.startswith('TA', na=False))]
    return ta

def fetch_option_greeks():
    """从东财获取期权希腊值数据（风险分析）"""
    import requests

    # 东财期权风险分析接口
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": "RPT_OPT_HV",
        "columns": "ALL",
        "quoteColumns": "q1,q2",
        "filter": "(品种代码=\"TA\")",
        "pageNumber": 1,
        "pageSize": 100,
        "sortTypes": -1,
        "sortColumns": "行权价",
        "source": "WEB",
        "client": "WEB"
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if data.get('result'):
            return data['result']['data']
    except Exception as e:
        print(f"[WARN] 东财期权数据: {e}")
    return []

def save_option_data():
    """保存期权数据"""
    print("[期权] 开始采集...")

    # 1. CTP合约信息
    print("[1/3] CTP期权链...")
    ctp_df = fetch_option_chain_ctp()
    if ctp_df is not None and not ctp_df.empty:
        ctp_df.to_csv(f'{DATA_DIR}/ta_option_contracts.csv', index=False)
        print(f"  合约数: {len(ctp_df)}")

        # 到期日
        if '最后交易日' in ctp_df.columns:
            expiry = ctp_df['最后交易日'].iloc[0]
            print(f"  到期日: {expiry}")

            # 行权价分布
            strikes = sorted(ctp_df['行权价'].dropna().unique())
            print(f"  行权价范围: {strikes[0]:.0f} ~ {strikes[-1]:.0f} ({len(strikes)}档)")

    # 2. TQSdk实时行情
    print("[2/3] TQSdk实时行情...")
    try:
        records = fetch_option_chain_tqsdk()
        if records:
            df = pd.DataFrame(records)
            df.to_csv(f'{DATA_DIR}/ta_option_realtime.csv', index=False)
            print(f"  有效合约: {len(df)}")
            print(f"  IV范围: {df['iv'].min():.2%} ~ {df['iv'].max():.2%}" if df['iv'].notna().any() else "  IV数据: 暂无可用")
        else:
            print("  无数据（TQSdk需要交易时间才能获取行情）")
    except Exception as e:
        print(f"  TQSdk错误: {e}")

    # 3. 东财希腊值
    print("[3/3] 东财希腊值数据...")
    greeks = fetch_option_greeks()
    if greeks:
        df_g = pd.DataFrame(greeks)
        df_g.to_csv(f'{DATA_DIR}/ta_option_greeks.csv', index=False)
        print(f"  条数: {len(df_g)}")
    else:
        print("  暂无可用")

    print("[完成] 数据已保存到 data/ 目录")

if __name__ == '__main__':
    os.makedirs(DATA_DIR, exist_ok=True)
    save_option_data()

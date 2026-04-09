#!/usr/bin/env python3
from tqsdk import TqApi, TqAuth, TqKq
import pandas as pd
import time

api = TqApi(TqKq(), auth=TqAuth('test', 'test'))
klines = api.get_kline_serial('CZCE.TA509', 86400, data_length=300)

# 等待数据
for _ in range(20):
    time.sleep(1)
    if len(klines) > 100:
        break

print(f"Got {len(klines)} bars")

# 直接保存
klines.to_csv('/home/admin/.openclaw/workspace/codeman/pta_analysis/ta509_daily.csv', index=False)
print("Saved!")

api.close()
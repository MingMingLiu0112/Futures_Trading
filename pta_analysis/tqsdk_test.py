#!/usr/bin/env python3
"""TqSdk天勤量化测试脚本"""
import asyncio
from tqsdk import TqApi, TqAuth, TqKq

async def main():
    api = TqApi(TqKq(), auth=TqAuth('test', 'test'))
    
    # 获取行情
    ta = api.get_quote('CZCE.TA509')
    print(f'PTA价格: {ta.last_price}')
    
    # 获取K线
    klines = api.get_kline_serial('CZCE.TA509', 60, data_length=100)
    await api._wait_update()
    
    print(f'K线数量: {len(klines)}')
    print(f'最新收盘: {klines.close.iloc[-1]}')
    
    await api.close()
    print('测试成功!')

if __name__ == '__main__':
    asyncio.run(main())
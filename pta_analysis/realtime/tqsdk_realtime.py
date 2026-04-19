#!/usr/bin/env python3
"""
TqSdk PTA 实时行情服务
通过 WebSocket 推送实时数据到前端
"""
import sys
import asyncio
import json
import threading
import time
from collections import deque

# 尝试导入 TqSdk
try:
    from tqsdk import TqApi, TqAuth, TqKq
    TQSDK_AVAILABLE = True
except ImportError:
    TQSDK_AVAILABLE = False
    print("TqSdk not available, using simulation mode")

# 全局变量
latest_data = {
    'price': 0,
    'bid': 0,
    'ask': 0,
    'volume': 0,
    'open': 0,
    'high': 0,
    'low': 0,
    'datetime': '',
    'klines': [],
    'timestamp': 0
}
klines_buffer = deque(maxlen=500)
data_lock = threading.Lock()
ws_clients = []
ws_clients_lock = threading.Lock()

def get_kline_symbol(period):
    """获取对应周期的合约代码"""
    symbol_map = {
        '1min': 'KQ.m@CZCE.TA',
        '5min': 'KQ.m@CZCE.TA', 
        '15min': 'KQ.m@CZCE.TA',
        '30min': 'KQ.m@CZCE.TA',
        '60min': 'KQ.m@CZCE.TA',
    }
    return symbol_map.get(period, 'KQ.m@CZCE.TA')

def get_duration_seconds(period):
    """获取周期对应的秒数"""
    duration_map = {
        '1min': 60,
        '5min': 300,
        '15min': 900,
        '30min': 1800,
        '60min': 3600,
    }
    return duration_map.get(period, 60)

def start_tqsdk_thread():
    """在新线程中运行TqSdk主循环"""
    if not TQSDK_AVAILABLE:
        print("TqSdk not available, skipping TqSdk thread")
        return
    
    def tqsdk_loop():
        print("[TqSdk] 启动天勤实时行情线程...")
        try:
            api = TqApi(TqKq(), auth=TqAuth("mingmingliu", "Liuzhaoning2025"), debug=False)
            print("[TqSdk] 天勤API连接成功")
            
            quote = api.get_quote('KQ.m@CZCE.TA')
            klines = api.get_kline_serial('KQ.m@CZCE.TA', 60, data_length=500)
            
            print("[TqSdk] 已订阅 CZCE.TA 行情和K线")
            
            while True:
                api.wait_update(deadline=time.time() + 5)
                
                with data_lock:
                    latest_data['price'] = float(quote.last_price) if quote.last_price else 0
                    latest_data['bid'] = float(quote.bid_price1) if quote.bid_price1 else 0
                    latest_data['ask'] = float(quote.ask_price1) if quote.ask_price1 else 0
                    latest_data['volume'] = int(quote.volume) if quote.volume else 0
                    latest_data['datetime'] = str(quote.datetime) if quote.datetime else ''
                    latest_data['timestamp'] = time.time()
                    
                    # 更新K线
                    if len(klines) > 0:
                        klines_buffer.clear()
                        for i in range(len(klines)):
                            dt = klines.iloc[i]['datetime']
                            klines_buffer.append({
                                'time': str(dt),
                                'open': float(klines.iloc[i]['open']),
                                'high': float(klines.iloc[i]['high']),
                                'low': float(klines.iloc[i]['low']),
                                'close': float(klines.iloc[i]['close']),
                                'volume': float(klines.iloc[i]['volume'])
                            })
                        latest_data['klines'] = list(klines_buffer)
                
        except Exception as e:
            print(f"[TqSdk] 线程异常: {e}")
            import traceback
            traceback.print_exc()
    
    thread = threading.Thread(target=tqsdk_loop, daemon=True)
    thread.start()
    return thread

def get_latest_price():
    """获取最新价格（用于HTTP轮询备选）"""
    with data_lock:
        return {
            'price': latest_data['price'],
            'bid': latest_data['bid'],
            'ask': latest_data['ask'],
            'volume': latest_data['volume'],
            'datetime': latest_data['datetime'],
            'timestamp': latest_data['timestamp']
        }

def get_klines(count=500):
    """获取K线数据"""
    with data_lock:
        klines = list(latest_data['klines'])
    # 返回最新的count条
    if len(klines) > count:
        klines = klines[-count:]
    return klines

if __name__ == '__main__':
    # 启动TqSdk线程
    start_tqsdk_thread()
    
    # 保持运行
    print("TqSdk PTA 实时行情服务已启动")
    print("按 Ctrl+C 停止")
    
    try:
        while True:
            time.sleep(10)
            data = get_latest_price()
            print(f"[{data['datetime']}] 最新价: {data['price']} | 成交量: {data['volume']}")
    except KeyboardInterrupt:
        print("\n停止服务")

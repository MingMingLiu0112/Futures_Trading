#!/usr/bin/env python3
"""
通过vnpy API导入PTA历史K线数据
"""
import csv
from datetime import datetime
from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.object import BarData
from vnpy.trader.database import get_database

DATA_DIR = "/tmp"

def load_csv_bars(csv_path):
    bars = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                dt = datetime.strptime(row['datetime'], '%Y-%m-%d %H:%M:%S')
                bar = BarData(
                    symbol=row['symbol'].strip(),
                    exchange=Exchange.CZCE,
                    datetime=dt,
                    interval=Interval.MINUTE,
                    open_price=float(row['open']),
                    high_price=float(row['high']),
                    low_price=float(row['low']),
                    close_price=float(row['close']),
                    volume=float(row['volume']),
                    open_interest=float(row.get('close_oi', 0)) or 0,
                    gateway_name="DB"
                )
                bars.append(bar)
            except Exception as e:
                pass
    return bars

def main():
    db = get_database()
    files = [
        f'{DATA_DIR}/pta_1min.csv',
        f'{DATA_DIR}/pta_5min.csv',
        f'{DATA_DIR}/pta_15min.csv',
        f'{DATA_DIR}/pta_30min.csv',
        f'{DATA_DIR}/pta_60min.csv',
    ]
    
    total = 0
    for path in files:
        bars = load_csv_bars(path)
        if bars:
            print(f"Saving {len(bars)} bars from {path.split('/')[-1]}...")
            db.save_bar_data(bars)
            total += len(bars)
            print(f"  First: {bars[0].datetime}, Last: {bars[-1].datetime}")
    
    print(f"\nTotal: {total} bars imported")

if __name__ == "__main__":
    main()

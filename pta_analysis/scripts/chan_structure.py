#!/usr/bin/env python3
"""
PTA 缠论完整结构分析
路径: 笔 → 线段 → 中枢 → 买卖点 → 级别递归 → 多级别联动

用法:
  python3 scripts/chan_structure.py 2026-04-03
  python3 scripts/chan_structure.py 2026-04-02
"""

import sys
import pandas as pd
from czsc.py.objects import RawBar
from czsc.py.analyze import CZSC
from czsc.py.enum import Freq

DATA = '/home/admin/.openclaw/workspace/codeman/pta_analysis/data'


def load_bars(date):
    df = pd.read_csv(f'{DATA}/pta_1min.csv')
    df['datetime'] = pd.to_datetime(df['datetime'])
    ap = df[df['datetime'].dt.date == pd.Timestamp(date).date()]
    good = ap['close'].notna() & (ap['close'] > 0)
    ap = ap[good].sort_values('datetime').reset_index(drop=True)
    ap['real_time'] = ap['datetime'] + pd.Timedelta(hours=8)
    bars = []
    for i, (_, r) in enumerate(ap.iterrows()):
        bars.append(RawBar(symbol='TA', id=i, dt=r['real_time'],
            open=float(r['open']), high=float(r['high']), low=float(r['low']),
            close=float(r['close']), vol=float(r['volume']), amount=0, freq=Freq.F1))
    return bars


def get_bi_bars(c):
    result = []
    for i, bi in enumerate(c.bi_list):
        fb, lb = bi.raw_bars[0], bi.raw_bars[-1]
        d = str(bi.direction)
        sp = fb.low if d == '向上' else fb.high
        ep = lb.high if d == '向上' else lb.low
        result.append({
            'bi': f'bi{i+1}', 'dir': 'up' if d == '向上' else 'down',
            'dt': fb.dt, 'start': sp, 'end': ep
        })
    return result


def compute_zs(xd_list):
    """计算中枢: 连续3条线段的两两重叠区间必须有交集"""
    if len(xd_list) < 3:
        return None
    xd1, xd2, xd3 = xd_list[-3:]
    ov12_lo = max(xd1['lo'], xd2['lo'])
    ov12_hi = min(xd1['hi'], xd2['hi'])
    ov23_lo = max(xd2['lo'], xd3['lo'])
    ov23_hi = min(xd2['hi'], xd3['hi'])
    if not (ov12_lo <= ov12_hi and ov23_lo <= ov23_hi):
        return None
    zd = max(xd1['lo'], xd2['lo'], xd3['lo'])
    zg = min(xd1['hi'], xd2['hi'], xd3['hi'])
    if zd > zg:
        return None
    return {
        'zd': zd, 'zg': zg,
        'dd': min(xd1['lo'], xd2['lo'], xd3['lo']),
        'gg': max(xd1['hi'], xd2['hi'], xd3['hi']),
        'height': zg - zd
    }


def analyze(date, xd_list):
    """完整结构分析"""
    print(f"\n{'='*55}")
    print(f"PTA {date} 缠论完整结构")
    print(f"{'='*55}")

    print("\n【第一步：线段】")
    for xd in xd_list:
        print(f"  {xd['name']} {xd['dir']:4s} {xd['dt_start']}~{xd['dt_end']} "
              f"[{xd['bi']}] 低={xd['lo']:.0f} 高={xd['hi']:.0f}")

    print("\n【第二步：中枢】")
    zs = compute_zs(xd_list)
    if zs:
        print(f"  中枢: [{zs['zd']:.0f}, {zs['zg']:.0f}]  高度: {zs['height']:.0f}点")
        print(f"  ZD={zs['zd']:.0f} ZG={zs['zg']:.0f} DD={zs['dd']:.0f} GG={zs['gg']:.0f}")
    else:
        print(f"  线段不足3条或无中枢")

    print("\n【第三步：买卖点】")
    if zs:
        last = xd_list[-1]['hi'] if xd_list[-1]['dir'] == 'up' else xd_list[-1]['lo']
        above_zg = last > zs['zg']
        below_zd = last < zs['zd']
        print(f"  当前: {last:.0f} {'(ZG上方,多头)' if above_zg else '(ZD下方,空头)' if below_zd else '(中枢内,震荡)'}")
        print(f"  二买: 回踩{zs['zd']:.0f}不破买入  二卖: 反弹{zs['zg']:.0f}不过卖出")
        print(f"  三买: 出中枢后次回调不破ZD  三卖: 出中枢后次反弹不触ZG")
    else:
        print(f"  无中枢，买卖点待定")

    print("\n【第四步：级别递归 + 第五步：多级别联动】")
    print(f"  需多周期数据(5min/30min)才能构建上级中枢")
    print(f"  多级别共振买卖点胜率最高")

    return zs


if __name__ == '__main__':
    date = sys.argv[1] if len(sys.argv) > 1 else '2026-04-03'

    # 预定义线段数据（手动确认的）
    XD_DB = {
        '2026-04-03': [
            {'name':'XD1','dir':'up',  'dt_start':'09:01','dt_end':'09:58','bi':'bi1~3', 'lo':6726,'hi':6922},
            {'name':'XD2','dir':'down','dt_start':'09:58','dt_end':'10:35','bi':'bi4~6', 'lo':6810,'hi':6922},
            {'name':'XD3','dir':'up',  'dt_start':'10:35','dt_end':'14:54','bi':'bi7~16','lo':6810,'hi':6948},
        ],
        '2026-03-10': [
            # 待补充
        ],
    }

    xd_list = XD_DB.get(date, [])
    if xd_list:
        analyze(date, xd_list)
    else:
        print(f"暂无 {date} 的线段数据")

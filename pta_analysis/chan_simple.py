#!/usr/bin/env python3
"""PTA缠论实时分析 - 简单快速版本"""
import sys
import time

def chan_analysis(period='1min'):
    """
    使用天勤TqSDK获取实时PTA数据并计算缠论
    """
    try:
        sys.path.insert(0, '/home/admin/.openclaw/workspace/codeman/pta_analysis')
        sys.path.insert(0, '/home/admin/.openclaw/workspace/vnpy_tqsdk/src')
        from tqsdk.data_source import TqDataSource
    except ImportError:
        return {'error': 'tqsdk未安装', 'period': period}

    try:
        # 获取天勤数据
        ds = TqDataSource()
        period_map = {
            "1min": ("TA", "600"),
            "5min": ("TA", "5min"),
            "15min": ("TA", "15min"),
            "30min": ("TA", "30min"),
            "60min": ("TA", "60min"),
            "1day": ("TA", "1d"),
        }
        symbol, tq_period = period_map.get(period, ("TA", "600"))
        df = ds.get_kline_series(symbol, tq_period, count=2000)

        if df is None or df.empty:
            return {'error': f'无{tq_period}数据', 'period': period}

        # 转换为K线列表（正序：旧→新）
        klines = []
        for _, row in df.iterrows():
            klines.append({
                'time': str(row.get('datetime', row.get('date', ''))),
                'open': float(row.get('open', 0)),
                'high': float(row.get('high', 0)),
                'low': float(row.get('low', 0)),
                'close': float(row.get('close', 0)),
                'volume': float(row.get('volume', 0))
            })

        # 计算缠论
        result = compute_chan(klines)
        result['period'] = period
        result['source'] = 'tqsdk (实时)'
        result['latest_time'] = klines[-1]['time'] if klines else ''
        return result

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {'error': str(e), 'period': period}


def compute_chan(klines):
    """计算缠论笔、线段、中枢"""
    n = len(klines)
    if n < 10:
        return {'error': '数据太少', 'klines': klines}

    # ===== 1. K线标准化（包含处理） =====
    std = standardize(list(range(n)), klines)
    if len(std) < 10:
        return {'error': '标准化后数据太少', 'klines': klines}

    # ===== 2. 找分型 =====
    fractals = find_fractals(std)
    if len(fractals) < 2:
        return make_result(klines, [], [], [], [])

    # ===== 3. 构建笔 (J-I+1>=4) =====
    bis = build_bis(fractals, std)
    if len(bis) < 2:
        return make_result(klines, [], [], [], bis)

    # ===== 4. 构建线段 =====
    segs = build_segs(bis)
    if len(segs) < 1:
        return make_result(klines, [], [], [], bis)

    # ===== 5. 构建中枢 =====
    zss = build_zss(bis)

    # ===== 6. 缠论标记数据 =====
    bi_ml = []
    for b in bis:
        color = '#f23645' if b['dir'] == 'up' else '#089981'
        bi_ml.append({
            'xAxis': b['begin'], 'yAxis': b['begin_price'],
            'xAxis2': b['end'], 'yAxis2': b['end_price'],
            'lineStyle': {'color': color, 'width': 2}
        })

    seg_ml = []
    for s in segs:
        seg_ml.append({
            'xAxis': s['begin'], 'yAxis': s['begin_price'],
            'xAxis2': s['end'], 'yAxis2': s['end_price'],
            'lineStyle': {'color': '#ffd93d', 'width': 3}
        })

    zs_ma = []
    for z in zss:
        zs_ma.append({
            'xAxis': z['begin'], 'xAxis2': z['end'],
            'yAxis': z['low'], 'yAxis2': z['high'],
            'itemStyle': {'color': 'rgba(233,69,96,0.1)', 'borderColor': '#e94560', 'borderWidth': 1, 'borderType': 'dashed'}
        })

    cp = klines[-1]['close']
    fp = klines[0]['close']
    chg = cp - fp
    pct = (chg / fp * 100) if fp else 0

    return {
        'klines': klines,
        'echarts': {
            'bi_markline': bi_ml,
            'seg_markline': seg_ml,
            'zs_markarea': zs_ma,
            'bs_scatter': []
        },
        'stats': {
            'bi_count': len(bis),
            'seg_count': len(segs),
            'zs_count': len(zss),
            'bs_count': 0,
            'current_price': round(cp, 2),
            'change': round(chg, 2),
            'change_pct': round(pct, 2)
        }
    }


def make_result(klines, fractals, bis, segs, zss):
    cp = klines[-1]['close'] if klines else 0
    fp = klines[0]['close'] if klines else cp
    chg = cp - fp
    pct = (chg / fp * 100) if fp else 0
    return {
        'klines': klines,
        'echarts': {'bi_markline': [], 'seg_markline': [], 'zs_markarea': [], 'bs_scatter': []},
        'stats': {
            'bi_count': len(bis), 'seg_count': len(segs), 'zs_count': len(zss),
            'bs_count': 0, 'current_price': round(cp, 2),
            'change': round(chg, 2), 'change_pct': round(pct, 2)
        }
    }


def standardize(ids, klines):
    """K线包含处理"""
    result = []
    for idx in ids:
        k = klines[idx]
        result.append({'idx': idx, 'open': k['open'], 'high': k['high'], 'low': k['low'], 'close': k['close']})

    i = 2
    while i < len(result):
        prev = result[i - 1]
        curr = result[i]
        # 判断是否包含
        if not (curr['high'] <= prev['high'] and curr['low'] >= prev['low'] or
                curr['high'] >= prev['high'] and curr['low'] <= prev['low']):
            i += 1
            continue
        # 包含处理
        if len(result) >= 2:
            pprev = result[-2]
            if pprev['high'] > (result[-3]['high'] if len(result) >= 3 else pprev['high']):
                result[-1] = {'idx': prev['idx'], 'open': prev['open'],
                              'high': max(curr['high'], prev['high']),
                              'low': max(curr['low'], prev['low']), 'close': curr['close']}
            else:
                result[-1] = {'idx': prev['idx'], 'open': prev['open'],
                              'high': min(curr['high'], prev['high']),
                              'low': min(curr['low'], prev['low']), 'close': curr['close']}
        i += 1
    return result


def find_fractals(std):
    """顶底分型"""
    fractals = []
    for i in range(1, len(std) - 1):
        prev, curr, nx = std[i-1], std[i], std[i+1]
        if prev['high'] < curr['high'] > nx['high']:
            fractals.append({'idx': i, 'type': 'top', 'price': curr['high']})
        elif prev['low'] > curr['low'] < nx['low']:
            fractals.append({'idx': i, 'type': 'bottom', 'price': curr['low']})
    return fractals


def build_bis(fractals, std):
    """笔: 顶底交替 + 空间 + 时间(J-I+1>=4)"""
    if len(fractals) < 2:
        return []
    bis = []
    i = 0
    while i <= len(fractals) - 2:
        f1, f2 = fractals[i], fractals[i+1]
        if f1['type'] == f2['type']:
            i += 1
            continue
        # 空间
        high = f1['price'] if f1['type'] == 'top' else f2['price']
        low = f2['price'] if f1['type'] == 'top' else f1['price']
        if high <= low:
            i += 1
            continue
        # 时间: I=顶分型第一根(index-1), J=底分型最后一根(index+1)
        I = f1['idx'] - 1
        J = f2['idx'] + 1
        if J - I + 1 < 4:  # 严格至少4根K线
            i += 1
            continue
        bis.append({
            'idx': len(bis),
            'dir': 'down' if f1['type'] == 'top' else 'up',
            'begin': f1['idx'],
            'end': f2['idx'],
            'begin_price': f1['price'],
            'end_price': f2['price']
        })
        i += 1
    return bis


def build_segs(bis):
    """线段: 3笔交替+重叠, 线段破坏"""
    if len(bis) < 3:
        return []
    segs = []
    i = 0
    while i <= len(bis) - 3:
        b1, b2, b3 = bis[i], bis[i+1], bis[i+2]
        dirs = [b1['dir'], b2['dir'], b3['dir']]
        if not ((dirs == ['up', 'down', 'up']) or (dirs == ['down', 'up', 'down'])):
            i += 1
            continue
        # 重叠
        ranges = [(b1['begin_price'], b1['end_price']), (b2['begin_price'], b2['end_price']), (b3['begin_price'], b3['end_price'])]
        if b1['dir'] == 'up':
            ranges = [(b['begin_price'], b['end_price']) for b in [b1, b2, b3]]
        else:
            ranges = [(b['end_price'], b['begin_price']) for b in [b1, b2, b3]]
        ov_h = min(r[1] for r in ranges)
        ov_l = max(r[0] for r in ranges)
        if ov_h <= ov_l:
            i += 1
            continue
        seg_dir = 'up' if dirs[0] == 'up' else 'down'
        segs.append({
            'idx': len(segs), 'dir': seg_dir,
            'begin': b1['begin'], 'end': b3['end'],
            'begin_price': b1['begin_price'], 'end_price': b3['end_price']
        })
        # 线段破坏检查
        broken = False
        seg_end = segs[-1]['end_price']
        for j in range(i + 3, len(bis)):
            bj = bis[j]
            if seg_dir == 'up' and bj['dir'] == 'down' and bj['end_price'] < seg_end:
                if j + 1 < len(bis) and bis[j+1]['dir'] == 'up' and bis[j+1]['end_price'] > seg_end:
                    broken = True
                    break
            elif seg_dir == 'down' and bj['dir'] == 'up' and bj['end_price'] > seg_end:
                if j + 1 < len(bis) and bis[j+1]['dir'] == 'down' and bis[j+1]['end_price'] < seg_end:
                    broken = True
                    break
        i = i + 3 if broken else i + 1
    return segs


def build_zss(bis):
    """中枢: 三笔交替+重叠"""
    if len(bis) < 3:
        return []
    zss = []
    for i in range(len(bis) - 2):
        b1, b2, b3 = bis[i], bis[i+1], bis[i+2]
        dirs = [b1['dir'], b2['dir'], b3['dir']]
        if not ((dirs == ['up', 'down', 'up']) or (dirs == ['down', 'up', 'down'])):
            continue
        ranges = [(b['begin_price'], b['end_price']) for b in [b1, b2, b3]]
        if b1['dir'] == 'down':
            ranges = [(b['end_price'], b['begin_price']) for b in [b1, b2, b3]]
        ov_h = min(r[1] for r in ranges)
        ov_l = max(r[0] for r in ranges)
        if ov_h >= ov_l:
            zss.append({
                'idx': len(zss), 'low': ov_l, 'high': ov_h, 'mid': (ov_l + ov_h) / 2,
                'begin': b1['begin'], 'end': b3['end']
            })
    return zss

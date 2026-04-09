"""PTA技术分析模块 - 缠论多级别联动"""
import pandas as pd
import numpy as np
import akshare as ak
import warnings
import re
from datetime import datetime, timedelta

warnings.filterwarnings('ignore')

# ─────────────────────────────────────────
# 数据获取
# ─────────────────────────────────────────

def get_daily_ta():
    """获取PTA日线数据"""
    df = ak.futures_zh_daily_sina(symbol='TA0')
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').tail(300).reset_index(drop=True)
    return df

def get_minute_ta(period='5'):
    """获取PTA分钟数据"""
    df = ak.futures_zh_minute_sina(symbol='TA0', period=period)
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.sort_values('datetime').reset_index(drop=True)
    return df

def resample_to_h30():
    """5分钟→30分钟合成"""
    m5 = get_minute_ta('5')
    m5.set_index('datetime', inplace=True)
    h30 = m5.resample('30min').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna().reset_index()
    return h30

def resample_to_h1():
    """5分钟→1小时合成（辅助用）"""
    m5 = get_minute_ta('5')
    m5.set_index('datetime', inplace=True)
    h1 = m5.resample('1h').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna().reset_index()
    return h1

# ─────────────────────────────────────────
# 缠论核心：分型 → 笔 → 段 → 中枢
# ─────────────────────────────────────────

def ping(df, key='datetime'):
    """识别顶底分型"""
    df = df.copy()
    df['fen'] = ''
    n = len(df)
    i = 2
    while i < n - 2:
        high = df['high'].values
        low = df['low'].values
        # 顶分型
        if high[i] > high[i-1] and high[i] > high[i+1] and high[i-1] >= high[i-2] and high[i+1] >= high[i+2]:
            df.loc[df.index[i], 'fen'] = 'D'  # 顶
            i += 3
            continue
        # 底分型
        if low[i] < low[i-1] and low[i] < low[i+1] and low[i-1] <= low[i-2] and low[i+1] <= low[i+2]:
            df.loc[df.index[i], 'fen'] = 'G'  # 底
            i += 3
            continue
        i += 1
    return df

def resolve_bx(df):
    """处理包含关系，合并K线，返回笔序列 [(type, high/low, idx)]"""
    d = df.copy().reset_index(drop=True)
    d['hx'] = d['high']
    d['lx'] = d['low']
    result = []
    i = 0
    while i < len(d):
        if d.loc[i, 'fen'] == 'D':
            result.append(('D', d.loc[i, 'high'], i))
            i += 1
        elif d.loc[i, 'fen'] == 'G':
            result.append(('G', d.loc[i, 'low'], i))
            i += 1
        else:
            i += 1
    # 笔：连续的顶和底配对，中间不需要其他分型
    bi = []
    j = 0
    while j < len(result) - 1:
        t1, v1, i1 = result[j]
        t2, v2, i2 = result[j+1]
        if t1 == 'D' and t2 == 'G':
            bi.append(('up', v1, v2, i1, i2))
            j += 2
        elif t1 == 'G' and t2 == 'D':
            bi.append(('dn', v1, v2, i1, i2))
            j += 2
        else:
            j += 1
    return bi, result

def build_zs(bi_list):
    """从笔序列构建中枢"""
    # 中枢：连续3笔重叠区间
    zs = []
    if len(bi_list) < 3:
        return zs
    i = 0
    while i <= len(bi_list) - 3:
        b1 = bi_list[i]
        b2 = bi_list[i+1]
        b3 = bi_list[i+2]
        # b1和b2方向相同
        if b1[0] != b2[0] or b2[0] != b3[0]:
            i += 1
            continue
        # 重叠区间
        segs = [(b1[1], b1[2]), (b2[1], b2[2]), (b3[1], b3[2])]
        lo = max(min(s[0] for s in segs), max(s[0] for s in segs) - 0)
        hi = min(max(s[1] for s in segs), min(s[1] for s in segs) + 0)
        # 重叠=高中取高，低中取低
        gg = max(b1[1], b2[1], b3[1])  # 最高点
        dd = min(b1[2], b2[2], b3[2])  # 最低点
        if dd < gg:  # 重叠则成中枢
            zs.append({'type': b1[0], 'zs_lo': dd, 'zs_hi': gg, 'b1': b1, 'b2': b2, 'b3': b3})
            i += 2
        else:
            i += 1
    return zs

def calc_beichi(bi_list, zs, direction='up'):
    """背驰判断：比较离开段和进入段的力度（用笔的高度和持续长度）"""
    if len(zs) == 0 or len(bi_list) < 5:
        return False, 0
    last_zs = zs[-1]
    # 进入段和离开段
    enter = bi_list[-3] if len(bi_list) >= 3 else None
    leave = bi_list[-1] if len(bi_list) >= 1 else None
    if not enter or not leave:
        return False, 0
    enter_range = abs(enter[1] - enter[2])
    leave_range = abs(leave[1] - leave[2])
    # 离开段不能回到中枢
    if direction == 'up' and leave[2] < last_zs['zs_lo']:
        return True, round(leave_range / enter_range, 2) if enter_range > 0 else 0
    if direction == 'dn' and leave[1] > last_zs['zs_hi']:
        return True, round(leave_range / enter_range, 2) if enter_range > 0 else 0
    return False, 0

# ─────────────────────────────────────────
# 辅助指标
# ─────────────────────────────────────────

def calc_ma(series, n):
    return series.rolling(n).mean()

def calc_macd(series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast).mean()
    ema_slow = series.ewm(span=slow).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal).mean()
    macd = (dif - dea) * 2
    return dif, dea, macd

def calc_rsi(series, n=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(n).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(n).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)

def calc_boll(series, n=20, k=2):
    mid = series.rolling(n).mean()
    std = series.rolling(n).std()
    upper = mid + k * std
    lower = mid - k * std
    return upper, mid, lower

def calc_pivot(df):
    """经典Pivot计算"""
    h = df['high'].values
    l = df['low'].values
    c = df['close'].values
    if len(h) < 2:
        return None
    p = (h[-2] + l[-2] + c[-2]) / 3
    s1 = 2*p - h[-2]
    s2 = p - (h[-2] - l[-2])
    s3 = l[-2] - 2*(h[-2] - p)
    r1 = 2*p - l[-2]
    r2 = p + (h[-2] - l[-2])
    r3 = h[-2] + 2*(p - l[-2])
    return {'pivot': round(p, 0), 's1': round(s1, 0), 's2': round(s2, 0), 's3': round(s3, 0),
            'r1': round(r1, 0), 'r2': round(r2, 0), 'r3': round(r3, 0)}

# ─────────────────────────────────────────
# 主分析函数
# ─────────────────────────────────────────

def analyze_ta():
    """多级别缠论技术分析"""
    result = {}

    # 30分钟线
    h30 = resample_to_h30()
    h30 = ping(h30, 'datetime')
    bi30, fen30 = resolve_bx(h30)
    zs30 = build_zs(bi30)
    beichi30, ratio30 = calc_beichi(bi30, zs30, direction='up')

    # 5分钟线
    m5 = get_minute_ta('5')
    m5 = ping(m5, 'datetime')
    bi5, fen5 = resolve_bx(m5)
    zs5 = build_zs(bi5)
    beichi5, ratio5 = calc_beichi(bi5, zs5, direction='up')

    # 1分钟线
    m1 = get_minute_ta('1')
    m1 = ping(m1, 'datetime')
    bi1, fen1 = resolve_bx(m1)
    zs1 = build_zs(bi1)

    # 日线
    daily = get_daily_ta()
    piv = calc_pivot(daily)

    # MA
    close_d = daily['close']
    ma5 = calc_ma(close_d, 5).iloc[-1]
    ma10 = calc_ma(close_d, 10).iloc[-1]
    ma20 = calc_ma(close_d, 20).iloc[-1]
    ma60 = calc_ma(close_d, 60).iloc[-1] if len(close_d) >= 60 else None

    # MACD
    dif, dea, macd = calc_macd(close_d)
    dif_v = round(dif.iloc[-1], 2)
    dea_v = round(dea.iloc[-1], 2)
    macd_v = round(macd.iloc[-1], 2)

    # RSI
    rsi14 = round(calc_rsi(close_d, 14).iloc[-1], 1)

    # 布林带
    upper, mid, lower = calc_boll(close_d)
    boll_upper = round(upper.iloc[-1], 0)
    boll_mid = round(mid.iloc[-1], 0)
    boll_lower = round(lower.iloc[-1], 0)

    # 30分钟方向判断
    if len(bi30) >= 2:
        last_bi = bi30[-1]
        prev_bi = bi30[-2]
        if last_bi[0] == 'up':
            dir30 = '上涨' if last_bi[1] > prev_bi[1] else '上涨减速'
        else:
            dir30 = '下跌' if last_bi[2] < prev_bi[2] else '下跌减速'
    else:
        dir30 = '震荡'

    # 缠论文字描述
    zs_desc = ''
    if zs30:
        z = zs30[-1]
        zs_desc = '中枢[%d~%d]' % (int(z['zs_lo']), int(z['zs_hi']))
    else:
        zs_desc = '无中枢'

    beichi_desc = ''
    if beichi30:
        beichi_desc = '背驰(力度比%.2f)' % ratio30

    # 5分钟买卖点提示
    bi5_desc = ''
    if len(bi5) >= 2:
        last5 = bi5[-1]
        if last5[0] == 'up':
            bi5_desc = '5分钟上涨笔%d→%d' % (int(last5[2]), int(last5[1]))
        else:
            bi5_desc = '5分钟下跌笔%d→%d' % (int(last5[1]), int(last5[2]))

    result = {
        'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'close': close_d.iloc[-1],
        'pivot': piv,
        'ma': {'ma5': round(ma5,0), 'ma10': round(ma10,0), 'ma20': round(ma20,0), 'ma60': round(ma60,0) if ma60 else None},
        'macd': {'dif': dif_v, 'dea': dea_v, 'macd': macd_v},
        'rsi14': rsi14,
        'boll': {'upper': boll_upper, 'mid': boll_mid, 'lower': boll_lower},
        'chan': {
            'dir30': dir30,
            'zs30': zs_desc,
            'zs30_lo': int(zs30[-1]['zs_lo']) if zs30 else None,
            'zs30_hi': int(zs30[-1]['zs_hi']) if zs30 else None,
            'beichi30': beichi_desc,
            'bi5': bi5_desc,
            'bi_count_30': len(bi30),
            'bi_count_5': len(bi5),
            'zs_count_30': len(zs30),
        }
    }
    return result

def report_ta(r):
    """文字报告"""
    if not r:
        return '技术数据不可用'
    c = r['chan']
    p = r['pivot']
    ma = r['ma']
    macd = r['macd']
    boll = r['boll']
    close = r['close']

    lines = []
    lines.append('=== 技术面 ===')
    lines.append('PTA收盘 %.0f' % close)
    if p:
        lines.append('Pivot=%.0f | S1=%.0f S2=%.0f S3=%.0f | R1=%.0f R2=%.0f R3=%.0f' % (
            p['pivot'], p['s1'], p['s2'], p['s3'], p['r1'], p['r2'], p['r3']))

    # 均线
    ma_str = 'MA5=%.0f MA10=%.0f MA20=%.0f' % (ma['ma5'], ma['ma10'], ma['ma20'])
    if ma['ma60']:
        ma_str += ' MA60=%.0f' % ma['ma60']
    # 多头排列判断
    if ma['ma5'] > ma['ma20']:
        ma_str += ' ↑多头'
    elif ma['ma5'] < ma['ma20']:
        ma_str += ' ↓空头'
    lines.append(ma_str)

    # MACD
    macd_state = '金叉' if macd['dif'] > macd['dea'] else '死叉'
    lines.append('MACD dif=%.2f dea=%.2f %s MACD=%.2f' % (
        macd['dif'], macd['dea'], macd_state, macd['macd']))

    # RSI
    rsi_state = '超买' if r['rsi14'] > 70 else ('超卖' if r['rsi14'] < 30 else '中性')
    lines.append('RSI14=%.1f(%s)' % (r['rsi14'], rsi_state))

    # 布林带
    lines.append('BOLL[%.0f~%.0f~%.0f]' % (boll['lower'], boll['mid'], boll['upper']))
    if close < boll['lower']:
        lines.append('  ⚠价格跌破BOLL下轨')
    elif close > boll['upper']:
        lines.append('  ⚠价格突破BOLL上轨')

    # 缠论
    lines.append('')
    lines.append('--- 缠论结构 ---')
    lines.append('方向(30分钟): %s' % c['dir30'])
    lines.append('30分钟中枢: %s' % c['zs30'])
    if c['beichi30']:
        lines.append('背驰提示: %s' % c['beichi30'])
    lines.append('5分钟笔: %s' % c['bi5'])
    lines.append('30分钟笔数: %d | 5分钟笔数: %d' % (c['bi_count_30'], c['bi_count_5']))
    lines.append('30分钟中枢数: %d' % c['zs_count_30'])

    return '\n'.join(lines)

# ─────────────────────────────────────────
# 测试
# ─────────────────────────────────────────

if __name__ == '__main__':
    print('正在获取数据...')
    r = analyze_ta()
    print(report_ta(r))

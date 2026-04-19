#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缠论多级别递归算法 - 完整重写版
L1(1分钟): K线→笔→线段
L2(5分钟): 线段→K线→笔→线段
L3(15分钟): 线段→K线→笔→线段
L4(60分钟): 线段→K线→笔
"""

import time
from typing import List, Dict, Tuple, Optional

# ── 数据结构 ────────────────────────────────────────────────────────────────

class KL:
    __slots__ = ('idx', 'time', 'open', 'high', 'low', 'close', 'volume')
    def __init__(self, idx, time, open_, high, low, close, volume=0.0):
        self.idx = idx; self.time = time; self.open = open_
        self.high = high; self.low = low; self.close = close; self.volume = volume

class Bi:
    __slots__ = ('idx', 'dir', 'begin_idx', 'end_idx', 'begin_price', 'end_price', 'level')
    def __init__(self, idx, dir_, begin_idx, end_idx, begin_price, end_price, level=1):
        self.idx = idx; self.dir = dir_; self.begin_idx = begin_idx
        self.end_idx = end_idx; self.begin_price = begin_price
        self.end_price = end_price; self.level = level

class Seg:
    __slots__ = ('idx', 'dir', 'begin_idx', 'end_idx', 'begin_price', 'end_price',
                  'seg_high', 'seg_low', 'level')
    def __init__(self, idx, dir_, begin_idx, end_idx, begin_price, end_price,
                 seg_high, seg_low, level=1):
        self.idx = idx; self.dir = dir_; self.begin_idx = begin_idx
        self.end_idx = end_idx; self.begin_price = begin_price
        self.end_price = end_price; self.seg_high = seg_high
        self.seg_low = seg_low; self.level = level

class ZS:
    __slots__ = ('idx', 'low', 'high', 'mid', 'begin_idx', 'end_idx', 'level')
    def __init__(self, idx, low, high, begin_idx, end_idx, level=1):
        self.idx = idx; self.low = low; self.high = high
        self.mid = (low + high) / 2; self.begin_idx = begin_idx
        self.end_idx = end_idx; self.level = level

# ── K线包含处理 ─────────────────────────────────────────────────────────────

def standardize(klines: List[KL]) -> List[KL]:
    """处理K线包含关系: 上升取max, 下降取min"""
    if not klines:
        return []
    result = [klines[0]]
    for cur in klines[1:]:
        last = result[-1]
        # 判断是否有包含关系
        has_inc = not (cur.high > last.high and cur.low < last.low or
                       cur.high < last.high and cur.low > last.low)
        if has_inc:
            # 无包含关系: 保留
            result.append(cur)
            continue
        # 有包含关系: 合并
        if len(result) >= 2 and result[-2].high < last.high:
            nh = max(last.high, cur.high); nl = max(last.low, cur.low)
        else:
            nh = min(last.high, cur.high); nl = min(last.low, cur.low)
        result[-1] = KL(last.idx, last.time, last.open, nh, nl, cur.close, last.volume + cur.volume)
    for i, k in enumerate(result):
        k.idx = i
    return result

# ── 分型识别 ────────────────────────────────────────────────────────────────

def find_fractals(klines: List[KL]) -> List[Tuple[int, str, float]]:
    """返回 [(kline_idx, 'top'/'bottom', price)]"""
    res = []
    for i in range(1, len(klines) - 1):
        p, c, n = klines[i-1], klines[i], klines[i+1]
        if p.high < c.high > n.high:
            res.append((i, 'top', c.high))
        elif p.low > c.low < n.low:
            res.append((i, 'bottom', c.low))
    return res

# ── 笔构建 ──────────────────────────────────────────────────────────────────

def build_bi(fractals: List[Tuple[int, str, float]], level: int = 1) -> List[Bi]:
    """
    从分型构建笔.
    笔时间条件: J-I+1>=4 (顶分型第一根I到底分型最后一根J, 至少4根K线)
    顶分型→底分型=向下笔, 底分型→顶分型=向上笔
    """
    if len(fractals) < 2:
        return []
    bis = []
    bi_idx = 0
    i = 0
    while i <= len(fractals) - 2:
        f1_idx, f1_type, f1_price = fractals[i]
        f2_idx, f2_type, f2_price = fractals[i+1]
        if f1_type == f2_type:
            i += 1; continue
        # 顶分型在左,底分型在右 → 向下笔
        if f1_type == 'top':
            if f2_price >= f1_price:
                i += 1; continue
            I = f1_idx - 1   # 顶分型第一根
            J = f2_idx + 1   # 底分型最后一根
            if J - I + 1 < 4:
                i += 1; continue
            bis.append(Bi(bi_idx, 'down', f1_idx, f2_idx, f1_price, f2_price, level))
            bi_idx += 1
        else:
            # 底分型在左,顶分型在右 → 向上笔
            if f1_price >= f2_price:
                i += 1; continue
            I = f1_idx - 1
            J = f2_idx + 1
            if J - I + 1 < 4:
                i += 1; continue
            bis.append(Bi(bi_idx, 'up', f1_idx, f2_idx, f1_price, f2_price, level))
            bi_idx += 1
        i += 1
    return bis

# ── 线段构建 ────────────────────────────────────────────────────────────────

def build_seg(bis: List[Bi], level: int = 1) -> List[Seg]:
    """
    从笔构建线段.
    三笔重叠构成中枢; 中枢不重叠时构成线段.
    线段被线段破坏: 反向线段反向创出新高/新低则原线段被破坏.
    """
    if len(bis) < 3:
        return []
    segs = []
    seg_idx = 0
    i = 0
    while i <= len(bis) - 3:
        b1, b2, b3 = bis[i], bis[i+1], bis[i+2]
        dirs = [b1.dir, b2.dir, b3.dir]
        if not ((dirs == ['up', 'down', 'up']) or (dirs == ['down', 'up', 'down'])):
            i += 1; continue
        # 三笔区间重叠
        r1 = (b1.begin_price, b1.end_price) if b1.dir == 'up' else (b1.end_price, b1.begin_price)
        r2 = (b2.begin_price, b2.end_price) if b2.dir == 'up' else (b2.end_price, b2.begin_price)
        r3 = (b3.begin_price, b3.end_price) if b3.dir == 'up' else (b3.end_price, b3.begin_price)
        ov_l = max(r1[0], r2[0], r3[0])
        ov_h = min(r1[1], r2[1], r3[1])
        if ov_h <= ov_l:
            i += 1; continue
        seg_dir = 'up' if dirs[0] == 'up' else 'down'
        seg_high = max(r1[1], r2[1], r3[1])
        seg_low = min(r1[0], r2[0], r3[0])
        segs.append(Seg(seg_idx, seg_dir, b1.idx, b3.idx,
                        b1.begin_price, b3.end_price, seg_high, seg_low, level))
        seg_idx += 1
        # 线段被线段破坏检查
        broken = False
        end_price = b3.end_price
        for j in range(i + 3, len(bis)):
            bj = bis[j]
            if seg_dir == 'up' and bj.dir == 'down' and bj.end_price < end_price:
                if j + 1 < len(bis):
                    bj1 = bis[j+1]
                    if bj1.dir == 'up' and bj1.end_price > end_price:
                        broken = True; break
            elif seg_dir == 'down' and bj.dir == 'up' and bj.end_price > end_price:
                if j + 1 < len(bis):
                    bj1 = bis[j+1]
                    if bj1.dir == 'down' and bj1.end_price < end_price:
                        broken = True; break
        i = i + 3 if broken else i + 1
    return segs

# ── 中枢构建 ────────────────────────────────────────────────────────────────

def build_zs(bis: List[Bi], level: int = 1) -> List[ZS]:
    """三笔重叠即为中枢(笔中枢)"""
    if len(bis) < 3:
        return []
    zs_list = []
    zs_idx = 0
    for i in range(len(bis) - 2):
        b1, b2, b3 = bis[i], bis[i+1], bis[i+2]
        dirs = [b1.dir, b2.dir, b3.dir]
        if not ((dirs == ['up', 'down', 'up']) or (dirs == ['down', 'up', 'down'])):
            continue
        r1 = (b1.begin_price, b1.end_price) if b1.dir == 'up' else (b1.end_price, b1.begin_price)
        r2 = (b2.begin_price, b2.end_price) if b2.dir == 'up' else (b2.end_price, b2.begin_price)
        r3 = (b3.begin_price, b3.end_price) if b3.dir == 'up' else (b3.end_price, b3.begin_price)
        low = max(r1[0], r2[0], r3[0])
        high = min(r1[1], r2[1], r3[1])
        if high > low:
            zs_list.append(ZS(zs_idx, low, high, b1.idx, b3.idx, level))
            zs_idx += 1
    return zs_list

# ── 线段 → 上一级K线 ─────────────────────────────────────────────────────────

def segs_to_klines(segs: List[Seg], bis: List[Bi], src_kl: List[KL]) -> List[KL]:
    """将线段序列转换为上一级K线: 一段 = 上一级一根K线"""
    if not segs:
        return []
    result = []
    for i, seg in enumerate(segs):
        seg_bis = [b for b in bis if b.idx >= seg.begin_idx and b.idx <= seg.end_idx]
        if not seg_bis:
            continue
        bi0 = seg_bis[0]
        t = src_kl[bi0.begin_idx].time if bi0.begin_idx < len(src_kl) else f'Lv{i}'
        result.append(KL(i, t,
                        seg_bis[0].begin_price,  # open = seg start
                        seg.seg_high,             # high = seg max
                        seg.seg_low,              # low = seg min
                        seg_bis[-1].end_price,    # close = seg end
                        0.0))
    return result

# ── MACD ────────────────────────────────────────────────────────────────────

def calc_macd(klines: List[KL]) -> Tuple[List[float], List[float]]:
    closes = [k.close for k in klines]
    n = len(closes)
    dif, dea = [0.0] * n, [0.0] * n
    if n == 0:
        return dif, dea
    ema_fast = closes[0]
    ema_slow = closes[0]
    k = 2.0 / 13   # fast=12
    sk = 2.0 / 27  # slow=26
    dk = 2.0 / 10  # signal=9
    dif[0] = 0.0
    dea[0] = 0.0
    for i in range(1, n):
        ema_fast = closes[i] * k + ema_fast * (1 - k)
        ema_slow = closes[i] * sk + ema_slow * (1 - sk)
        dif[i] = ema_fast - ema_slow
        dea[i] = dif[i] * dk + dea[i-1] * (1 - dk)
    return dif, dea

def macd_area(dif: List[float], dea: List[float], start: int, end: int) -> float:
    """计算区间内MACD柱面积总和"""
    if end <= start or start < 0:
        return 0.0
    total = 0.0
    for i in range(start, min(end, len(dif))):
        total += (dif[i] - dea[i]) * 2
    return total

# ── 单级别分析 ─────────────────────────────────────────────────────────────

def analyze_level(klines: List[KL], level: int) -> Dict:
    std = standardize(klines)
    fractals = find_fractals(std)
    bis = build_bi(fractals, level)
    segs = build_seg(bis, level)
    zs_list = build_zs(bis, level)
    dif, dea = calc_macd(std)
    return {
        'level': level, 'bis': bis, 'segs': segs, 'zs': zs_list,
        'std_klines': std, 'dif': dif, 'dea': dea,
    }

# ── 买卖点检测 ──────────────────────────────────────────────────────────────

def find_bs(bis: List[Bi], segs: List[Seg], dif: List[float], dea: List[float],
            std_kl: List[KL]) -> List[Dict]:
    """
    MACD面积背驰 + 快慢线回抽零轴.
    比较相邻同向段面积, 反向面积小于正向 → 背驰.
    """
    bs_list = []
    if len(segs) < 2 or len(dif) == 0 or len(bis) == 0:
        return bs_list
    # 用bis的索引范围映射到std_kl的K线位置
    for i in range(len(segs) - 1):
        s_a = segs[i]
        s_b = segs[i + 1]
        if s_a.dir == s_b.dir:
            continue
        # seg_a是主力方向, seg_b是反向
        # 获取seg_a对应的K线区间
        ba = bis[s_a.begin_idx] if s_a.begin_idx < len(bis) else bis[-1]
        bb = bis[s_b.begin_idx] if s_b.begin_idx < len(bis) else bis[-1]
        kl_a_s = ba.begin_idx
        kl_a_e = ba.end_idx
        kl_b_s = bb.begin_idx
        kl_b_e = bb.end_idx
        if kl_a_e <= kl_a_s or kl_b_e <= kl_b_s:
            continue
        if kl_a_e >= len(std_kl) or kl_b_e >= len(std_kl):
            continue
        area_a = macd_area(dif, dea, kl_a_s, kl_a_e + 1)
        area_b = macd_area(dif, dea, kl_b_s, kl_b_e + 1)
        if abs(area_b) < 0.01:
            continue
        # 向上段后的向下背驰 → 卖出
        if s_a.dir == 'up' and area_a > 0 and area_b < 0 and abs(area_b) < abs(area_a):
            # 快慢线回抽零轴检查
            if abs(dea[kl_b_e]) < abs(dea[kl_a_s]) * 0.5 or (dea[kl_a_s] * dea[kl_b_e] < 0):
                bs_list.append({
                    'xAxis': kl_b_e, 'yAxis': std_kl[kl_b_e].close,
                    'level': s_a.level, 'type': 'sell', 'dir': 'down',
                    'area_ratio': round(abs(area_b / area_a), 3),
                })
        # 向下段后的向上背驰 → 买进
        elif s_a.dir == 'down' and area_a < 0 and area_b > 0 and abs(area_b) < abs(area_a):
            if abs(dea[kl_b_e]) < abs(dea[kl_a_s]) * 0.5 or (dea[kl_a_s] * dea[kl_b_e] < 0):
                bs_list.append({
                    'xAxis': kl_b_e, 'yAxis': std_kl[kl_b_e].close,
                    'level': s_a.level, 'type': 'buy', 'dir': 'up',
                    'area_ratio': round(abs(area_b / area_a), 3),
                })
    return bs_list

# ── ECharts数据构建 ─────────────────────────────────────────────────────────

L_COLORS = {
    1: {'bi': '#f23645', 'seg': '#ff6b6b', 'zs': 'rgba(243,70,101,0.12)'},
    2: {'bi': '#4f4', 'seg': '#4ecdc4', 'zs': 'rgba(68,255,68,0.12)'},
    3: {'bi': '#44f', 'seg': '#7b8cde', 'zs': 'rgba(68,68,244,0.12)'},
    4: {'bi': '#ffd93d', 'seg': '#c084fc', 'zs': 'rgba(255,217,61,0.12)'},
}

def build_echarts(levels_data: List[Dict]) -> Dict:
    bi_ml, seg_ml, zs_ma, bs_sc = [], [], [], []
    for ld in levels_data:
        lv = ld['level']
        c = L_COLORS.get(lv, L_COLORS[1])
        std = ld['std_klines']
        for b in ld['bis']:
            bi_ml.append({
                'xAxis': b.begin_idx, 'yAxis': b.begin_price,
                'xAxis2': b.end_idx, 'yAxis2': b.end_price,
                'lineStyle': {'color': c['bi'], 'width': max(1, 3 - lv * 0.5)},
                'level': lv,
                'label': {'formatter': f"{'↑' if b.dir=='up' else '↓'}{b.idx}",
                          'color': c['bi'], 'fontSize': 7}
            })
        for s in ld['segs']:
            seg_ml.append({
                'xAxis': s.begin_idx, 'yAxis': s.begin_price,
                'xAxis2': s.end_idx, 'yAxis2': s.end_price,
                'lineStyle': {'color': c['seg'], 'width': max(1, 2 - lv * 0.3), 'type': 'dashed'},
                'level': lv
            })
        for z in ld['zs']:
            zs_ma.append({
                'xAxis': z.begin_idx, 'xAxis2': z.end_idx,
                'yAxis': z.low, 'yAxis2': z.high,
                'itemStyle': {'color': c['zs'], 'borderColor': c['seg'],
                              'borderWidth': 1, 'borderType': 'dashed'},
                'level': lv
            })
        for b in ld.get('bs', []):
            color = '#ff4757' if b['type'] == 'sell' else '#2ed573'
            bs_sc.append({
                'xAxis': b['xAxis'], 'yAxis': b['yAxis'],
                'value': b['yAxis'],
                'itemStyle': {'color': color},
                'level': b['level'],
                'type': b['type'],
            })
    return {'bi_markline': bi_ml, 'seg_markline': seg_ml,
            'zs_markarea': zs_ma, 'bs_scatter': bs_sc}

# ── 多级别递归分析器 ───────────────────────────────────────────────────────

class ChanAnalyzer:
    def __init__(self, raw_klines: List[Dict], max_level: int = 4):
        self.max_level = max_level
        # 构建K线对象
        self.raw_kl = []
        for i, d in enumerate(raw_klines):
            self.raw_kl.append(KL(
                i, str(d['time']), float(d['open']), float(d['high']),
                float(d['low']), float(d['close']), float(d.get('volume', 0))
            ))
        self.levels_data: List[Dict] = []
        self._run_analysis()

    def _run_analysis(self):
        """多级别递归: L1用真实K线, L2+用上一级线段转换"""
        # L1: 1分钟K线 → 笔 → 线段
        klines = self.raw_kl
        for lv in range(1, self.max_level + 1):
            if len(klines) < 5:
                break
            ld = analyze_level(klines, lv)
            # 买卖点
            if ld['segs']:
                ld['bs'] = find_bs(ld['bis'], ld['segs'], ld['dif'], ld['dea'], ld['std_klines'])
            else:
                ld['bs'] = []
            self.levels_data.append(ld)
            # 递归: 用线段生成上一级K线
            if lv >= self.max_level or len(ld['segs']) < 3:
                break
            klines = segs_to_klines(ld['segs'], ld['bis'], klines)
            if len(klines) < 5:
                break

    def to_json(self) -> Dict:
        klines_out = [{'idx': k.idx, 'time': k.time, 'open': k.open,
                       'high': k.high, 'low': k.low, 'close': k.close, 'volume': k.volume}
                      for k in self.raw_kl]
        cp = klines_out[-1]['close'] if klines_out else 0
        fp = klines_out[0]['close'] if klines_out else cp
        all_bs = [b for ld in self.levels_data for b in ld.get('bs', [])]
        return {
            'period': '1min',
            'klines': klines_out,
            'levels': [{'level': ld['level'],
                        'bi_count': len(ld['bis']),
                        'seg_count': len(ld['segs']),
                        'zs_count': len(ld['zs'])} for ld in self.levels_data],
            'echarts': build_echarts(self.levels_data),
            'stats': {
                'bi_count': sum(len(ld['bis']) for ld in self.levels_data),
                'seg_count': sum(len(ld['segs']) for ld in self.levels_data),
                'zs_count': sum(len(ld['zs']) for ld in self.levels_data),
                'bs_count': len(all_bs),
                'current_price': round(cp, 2),
                'change': round(cp - fp, 2),
                'change_pct': round((cp - fp) / fp * 100, 2) if fp else 0,
            }
        }

# ── 入口函数 ───────────────────────────────────────────────────────────────

_chan_cache: Dict = {}

def chan_analysis(period: str = '1min', max_level: int = 4) -> Dict:
    """
    主入口: 获取PTA数据并进行多级别缠论分析.
    返回格式:
      {period, klines, levels, echarts, stats}
    """
    import akshare as ak
    cache_key = f"pta_{period}_{max_level}"
    now = time.time()
    if cache_key in _chan_cache:
        cached, ts = _chan_cache[cache_key]
        if now - ts < 60:
            return cached
    try:
        if period == '1day':
            df = ak.futures_zh_daily_sina(symbol="TA0")
            df = df.sort_values('date').tail(500).reset_index(drop=True)
            kl_data = [{'time': str(r['date']), 'open': float(r['open']),
                        'high': float(r['high']), 'low': float(r['low']),
                        'close': float(r['close']), 'volume': float(r.get('volume', 0))}
                       for _, r in df.iterrows()]
        else:
            pmap = {"1min": "1", "5min": "5", "15min": "15", "30min": "30", "60min": "60"}
            pval = pmap.get(period, "1")
            df = ak.futures_zh_minute_sina(symbol="TA0", period=pval)
            df = df.sort_values('datetime').tail(2000).reset_index(drop=True)
            kl_data = [{'time': str(r['datetime']), 'open': float(r['open']),
                        'high': float(r['high']), 'low': float(r['low']),
                        'close': float(r['close']), 'volume': float(r.get('volume', 0))}
                       for _, r in df.iterrows()]
        if not kl_data:
            return {'error': 'No data', 'period': period}
        analyzer = ChanAnalyzer(kl_data, max_level=max_level)
        result = analyzer.to_json()
        result['period'] = period
        _chan_cache[cache_key] = (result, now)
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {'error': str(e), 'period': period}

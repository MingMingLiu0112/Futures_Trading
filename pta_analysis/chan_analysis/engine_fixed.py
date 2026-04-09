#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA缠论分析引擎 - 修复版
使用 open/close 数据正确判断趋势
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List
from enum import Enum
from datetime import datetime

class FX_TYPE(Enum):
    TOP = "top"
    BOTTOM = "bottom"

class BI_DIR(Enum):
    UP = "up"
    DOWN = "down"

class SEG_DIR(Enum):
    UP = "up"
    DOWN = "down"

@dataclass
class KLine:
    idx: int
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float

@dataclass
class MKLine:
    begin: int
    end: int
    high: float
    low: float
    open: float
    close: float
    fx: FX_TYPE = FX_TYPE.TOP

@dataclass
class Bi:
    idx: int
    dir: BI_DIR
    begin: int
    end: int
    begin_val: float
    end_val: float
    is_sure: bool = True

@dataclass
class Seg:
    idx: int
    dir: SEG_DIR
    begin: int
    end: int
    is_sure: bool = True

@dataclass
class ZhongShu:
    idx: int
    begin: int
    end: int
    low: float
    high: float
    is_sure: bool = True

@dataclass
class BSPoint:
    idx: int
    type: str
    direction: str
    price: float
    bi_idx: int
    is_sure: bool = True
    beichi: bool = False

# ─────────────────────────────────────────
# 第一步：包含关系处理
# ─────────────────────────────────────────

def process_baohan(klines: List[KLine]) -> List[MKLine]:
    """
    处理K线包含关系，使用open/close判断趋势
    规则：
    - 上升趋势（含包含后）：高高原则
    - 下降趋势（含包含后）：低低原则
    趋势判断：前一合并K线，收盘 > 开盘 = 上升，收盘 < 开盘 = 下降
    """
    result: List[MKLine] = []

    for i, kl in enumerate(klines):
        if not result:
            result.append(MKLine(
                begin=i, end=i,
                high=kl.high, low=kl.low,
                open=kl.open, close=kl.close
            ))
            continue

        prev = result[-1]
        curr_h, curr_l = kl.high, kl.low
        curr_o, curr_c = kl.open, kl.close

        # 判断包含：当前K线完全在之前K线内部
        hasContain = (curr_h <= prev.high and curr_l >= prev.low) or \
                     (curr_h >= prev.high and curr_l <= prev.low)

        if not hasContain:
            # 无包含，根据前一K线判断趋势
            trend_up = prev.close >= prev.open
            result.append(MKLine(
                begin=prev.end + 1, end=i,
                high=curr_h, low=curr_l,
                open=curr_o, close=curr_c
            ))
        else:
            # 有包含
            trend_up = prev.close >= prev.open
            if trend_up:
                # 上升趋势：高高低原则
                new_h = max(prev.high, curr_h)
                new_l = max(prev.low, curr_l)
            else:
                # 下降趋势：低低原则
                new_h = min(prev.high, curr_h)
                new_l = min(prev.low, curr_l)
            result[-1] = MKLine(
                begin=prev.begin, end=i,
                high=new_h, low=new_l,
                open=prev.open, close=curr_c  # 保留原始开盘，用当前收盘
            )

    # 标记分型
    n = len(result)
    for i in range(n):
        if i > 0 and i < n - 1:
            p = result[i - 1]
            c = result[i]
            ne = result[i + 1]

            # 顶分型：中间K线高点最高，低点也高于左右
            if c.high > p.high and c.high > ne.high and c.low > p.low and c.low > ne.low:
                result[i].fx = FX_TYPE.TOP
            # 底分型：中间K线高点最低，低点也低于左右
            elif c.high < p.high and c.high < ne.high and c.low < p.low and c.low < ne.low:
                result[i].fx = FX_TYPE.BOTTOM

    return result

# ─────────────────────────────────────────
# 第二步：笔构建
# ─────────────────────────────────────────

def build_bi(mklines: List[MKLine], min_bars: int = 4) -> List[Bi]:
    """
    笔构建：严格顶底交替
    顶分型后跟底分型 = 下降笔
    底分型后跟顶分型 = 上升笔
    """
    fenxing = [(i, m.fx) for i, m in enumerate(mklines) if m.fx != FX_TYPE.TOP and m.fx != FX_TYPE.BOTTOM]
    # Re-filter correctly
    fenxing = []
    for i, m in enumerate(mklines):
        if m.fx == FX_TYPE.TOP or m.fx == FX_TYPE.BOTTOM:
            fenxing.append((i, m.fx))

    if len(fenxing) < 2:
        return []

    bi_list: List[Bi] = []
    i = 0
    while i < len(fenxing) - 1:
        idx1, fx1 = fenxing[i]
        idx2, fx2 = fenxing[i + 1]

        # 必须是顶底交替
        if not ((fx1 == FX_TYPE.TOP and fx2 == FX_TYPE.BOTTOM) or
                (fx1 == FX_TYPE.BOTTOM and fx2 == FX_TYPE.TOP)):
            i += 1
            continue

        bars = idx2 - idx1 - 1  # 中间K线数

        if bars >= min_bars:
            if fx1 == FX_TYPE.TOP:
                # 下降笔
                bi_list.append(Bi(
                    idx=len(bi_list),
                    dir=BI_DIR.DOWN,
                    begin=idx1,
                    end=idx2,
                    begin_val=mklines[idx1].high,
                    end_val=mklines[idx2].low
                ))
            else:
                # 上升笔
                bi_list.append(Bi(
                    idx=len(bi_list),
                    dir=BI_DIR.UP,
                    begin=idx1,
                    end=idx2,
                    begin_val=mklines[idx1].low,
                    end_val=mklines[idx2].high
                ))
            i += 2  # 跳到下一对
        else:
            i += 1

    return bi_list

# ─────────────────────────────────────────
# 第三步：线段构建
# ─────────────────────────────────────────

def build_seg(bi_list: List[Bi]) -> List[Seg]:
    """线段：连续三笔有重叠"""
    if len(bi_list) < 3:
        return []

    segs: List[Seg] = []
    i = 0
    while i <= len(bi_list) - 3:
        b1, b2, b3 = bi_list[i], bi_list[i+1], bi_list[i+2]

        if b1.dir == b2.dir == b3.dir:
            seg_dir = SEG_DIR.UP if b1.dir == BI_DIR.UP else SEG_DIR.DOWN
            segs.append(Seg(idx=len(segs), dir=seg_dir, begin=i, end=i+2))
            i += 2
        else:
            i += 1

    return segs

# ─────────────────────────────────────────
# 第四步：中枢构建
# ─────────────────────────────────────────

def build_zs(segs: List[Seg], bi_list: List[Bi]) -> List[ZhongShu]:
    """中枢：连续三段重叠"""
    if len(segs) < 3:
        return []

    zss: List[ZhongShu] = []
    i = 0
    while i <= len(segs) - 3:
        s1, s2, s3 = segs[i], segs[i+1], segs[i+2]

        if s1.dir == s2.dir == s3.dir:
            # 计算三段的高低区间
            def bi_range(bi_idx):
                b = bi_list[bi_idx]
                return (min(b.begin_val, b.end_val), max(b.begin_val, b.end_val))

            r1 = bi_range(s1.begin)
            r2 = bi_range(s2.begin)
            r3 = bi_range(s3.begin)

            # 重叠区间
            overlap_low = max(r1[0], r2[0], r3[0])
            overlap_high = min(r1[1], r2[1], r3[1])

            if overlap_low < overlap_high:
                zss.append(ZhongShu(
                    idx=len(zss), begin=i, end=i+2,
                    low=overlap_low, high=overlap_high
                ))
                i += 2
            else:
                i += 1
        else:
            i += 1

    return zss

# ─────────────────────────────────────────
# 第五步：背驰判断 & 买卖点
# ─────────────────────────────────────────

def find_bs(bi_list: List[Bi], zs_list: List[ZhongShu]) -> List[BSPoint]:
    """买卖点识别"""
    if len(bi_list) < 3 or not zs_list:
        return []

    bs_points: List[BSPoint] = []
    zs = zs_list[-1]
    last_bi = bi_list[-1]

    # 一买：下跌后底分型创出新低
    if last_bi.dir == BI_DIR.DOWN and len(bi_list) >= 3:
        prev_bi = bi_list[-2]
        if prev_bi.dir == BI_DIR.UP:
            bs_points.append(BSPoint(
                idx=len(bs_points), type="buy1", direction="long",
                price=last_bi.end_val, bi_idx=last_bi.idx, beichi=False
            ))

    # 一卖：上涨后顶分型创出新高
    if last_bi.dir == BI_DIR.UP and len(bi_list) >= 3:
        prev_bi = bi_list[-2]
        if prev_bi.dir == BI_DIR.DOWN:
            bs_points.append(BSPoint(
                idx=len(bs_points), type="sell1", direction="short",
                price=last_bi.end_val, bi_idx=last_bi.idx, beichi=False
            ))

    return bs_points

# ─────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────

def full_chan_analysis(klines: List[KLine], period: str = "1min") -> dict:
    mklines = process_baohan(klines)
    bi_list = build_bi(mklines)
    segs = build_seg(bi_list)
    zss = build_zs(segs, bi_list)
    bs_points = find_bs(bi_list, zss)

    current_price = klines[-1].close if klines else 0
    first_price = klines[0].open if klines else current_price
    change = current_price - first_price
    change_pct = (change / first_price * 100) if first_price else 0

    # ECharts数据
    bi_markline = []
    for b in bi_list:
        color = '#f23645' if b.dir == BI_DIR.UP else '#089981'
        bi_markline.append({
            'xAxis': b.begin, 'yAxis': b.begin_val,
            'xAxis2': b.end, 'yAxis2': b.end_val,
            'lineStyle': {'color': color, 'width': 2},
            'label': {'show': True, 'formatter': f"{'↑' if b.dir==BI_DIR.UP else '↓'}{b.idx}", 'color': color}
        })

    seg_markline = []
    for s in segs:
        seg_markline.append({
            'xAxis': bi_list[s.begin].begin, 'yAxis': bi_list[s.begin].begin_val,
            'xAxis2': bi_list[s.end].end, 'yAxis2': bi_list[s.end].end_val,
            'lineStyle': {'color': '#ffd93d', 'width': 3},
            'label': {'show': True, 'formatter': f"S{s.idx}", 'color': '#ffd93d'}
        })

    zs_markarea = []
    for z in zss:
        zs_markarea.append({
            'xAxis': bi_list[z.begin].begin,
            'xAxis2': bi_list[z.end].end,
            'yAxis': z.low, 'yAxis2': z.high,
            'itemStyle': {'color': 'rgba(233,69,96,0.1)', 'borderColor': '#e94560', 'borderWidth': 1, 'borderType': 'dashed'}
        })

    bs_scatter = []
    for p in bs_points:
        color = '#ff6b6b' if 'buy' in p.type else '#6bcb77'
        bs_scatter.append({
            'value': [bi_list[p.bi_idx].end if p.bi_idx < len(bi_list) else 0, p.price],
            'symbol': 'circle', 'symbolSize': 12,
            'itemStyle': {'color': color}
        })

    return {
        'period': period,
        'klines': [{'idx': k.idx, 'time': k.time, 'open': k.open, 'high': k.high, 'low': k.low, 'close': k.close, 'volume': k.volume} for k in klines],
        'mklines': [{'begin': m.begin, 'end': m.end, 'high': m.high, 'low': m.low, 'fx': m.fx.value} for m in mklines],
        'bi': [{'idx': b.idx, 'dir': b.dir.value, 'begin': b.begin, 'end': b.end, 'begin_val': b.begin_val, 'end_val': b.end_val} for b in bi_list],
        'seg': [{'idx': s.idx, 'dir': s.dir.value, 'begin': s.begin, 'end': s.end} for s in segs],
        'zs': [{'idx': z.idx, 'low': z.low, 'high': z.high, 'begin': z.begin, 'end': z.end} for z in zss],
        'bs': [{'idx': p.idx, 'type': p.type, 'direction': p.direction, 'price': p.price, 'bi_idx': p.bi_idx} for p in bs_points],
        'current_price': round(current_price, 2),
        'change': round(change, 2),
        'change_pct': round(change_pct, 2),
        'timestamp': datetime.now().isoformat(),
        'echarts': {
            'bi_markline': bi_markline,
            'seg_markline': seg_markline,
            'zs_markarea': zs_markarea,
            'bs_scatter': bs_scatter,
        },
        'stats': {
            'bi_count': len(bi_list),
            'seg_count': len(segs),
            'zs_count': len(zss),
            'bs_count': len(bs_points),
            'current_price': round(current_price, 2),
            'change': round(change, 2),
            'change_pct': round(change_pct, 2),
        }
    }

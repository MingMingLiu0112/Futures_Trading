#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA缠论分析引擎 - 严格版
基于缠论原文算法：
1. 包含关系处理
2. 分型识别（顶分型/底分型）
3. 笔构建（严格隔三数）
4. 线段构建
5. 中枢构建
6. 买卖点识别
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Literal
from enum import Enum
from datetime import datetime

# ─────────────────────────────────────────
# 枚举类型
# ─────────────────────────────────────────

class FX_TYPE(Enum):
    TOP = "top"      # 顶分型
    BOTTOM = "bottom" # 底分型

class BI_DIR(Enum):
    UP = "up"
    DOWN = "down"

class SEG_DIR(Enum):
    UP = "up"
    DOWN = "down"

# ─────────────────────────────────────────
# 核心数据类
# ─────────────────────────────────────────

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
    """合并后的K线"""
    begin: int
    end: int
    high: float
    low: float
    fx: FX_TYPE = FX_TYPE.TOP
    dir: BI_DIR | None = None

@dataclass
class Bi:
    """笔"""
    idx: int
    dir: BI_DIR
    begin: int      # 起点(合并K线索引)
    end: int        # 终点(合并K线索引)
    begin_val: float
    end_val: float
    is_sure: bool = True

@dataclass
class Seg:
    """线段"""
    idx: int
    dir: SEG_DIR
    begin: int      # 起始笔索引
    end: int        # 结束笔索引
    is_sure: bool = True

@dataclass
class ZhongShu:
    """中枢"""
    idx: int
    begin: int      # 起始线段索引
    end: int        # 结束线段索引
    low: float
    high: float
    is_sure: bool = True

@dataclass
class BSPoint:
    """买卖点"""
    idx: int
    type: str       # buy1, buy2, sell1, sell2
    direction: str   # long, short
    price: float
    bi_idx: int
    is_sure: bool = True
    beichi: bool = False

# ─────────────────────────────────────────
# 第一步：包含关系处理
# ─────────────────────────────────────────

def process_baohan(klines: List[KLine]) -> List[MKLine]:
    """处理包含关系，返回合并K线序列"""
    if not klines:
        return []

    rows = [(kl.high, kl.low) for kl in klines]
    result: List[Tuple[float, float]] = []
    trend = None  # None, "up", "down"

    i = 0
    trend = None  # "up" or "down"
    while i < len(rows):
        if not result:
            result.append(rows[i])
            trend = "up"  # 初始趋势向上（上涨）
            i += 1
            continue

        h1, l1 = result[-1]
        h2, l2 = rows[i]

        # 判断包含关系
        hasContain = (h2 <= h1 and l2 >= l1) or (h2 >= h1 and l2 <= l1)

        if not hasContain:
            # 无包含，根据两K线高低判断趋势
            if h2 > h1 and l2 >= l1:
                trend = "up"
            elif l2 < l1 and h2 <= h1:
                trend = "down"
            elif h2 > h1:
                trend = "up"
            else:
                trend = "down"
            result.append(rows[i])
            i += 1
        else:
            # 有包含关系，根据趋势判断处理
            if trend == "up":
                # 上升趋势：高高低原则（取高高）
                new_h = max(h1, h2)
                new_l = max(l1, l2)
            else:
                # 下降趋势：低低原则（取低低）
                new_h = min(h1, h2)
                new_l = min(l1, l2)

            result[-1] = (new_h, new_l)
            i += 1

    # 标记分型
    n = len(result)
    mklines: List[MKLine] = []
    for i, (h, l) in enumerate(result):
        mk = MKLine(begin=i, end=i, high=h, low=l)
        if i > 0 and i < n - 1:
            h_prev, l_prev = result[i - 1]
            h_next, l_next = result[i + 1]
            # 顶分型
            if h > h_prev and h > h_next and l > l_prev and l > l_next:
                mk.fx = FX_TYPE.TOP
            # 底分型
            elif h < h_prev and h < h_next and l < l_prev and l < l_next:
                mk.fx = FX_TYPE.BOTTOM
        mklines.append(mk)

    return mklines

# ─────────────────────────────────────────
# 第二步：笔构建（严格缠论）
# ─────────────────────────────────────────

def build_bi_strict(mklines: List[MKLine], min_bars: int = 4) -> List[Bi]:
    """
    严格缠论笔构建
    规则：
    1. 笔必须有顶分型和底分型（或底分型和顶分型）构成
    2. 顶分型和底分型之间不能有包含关系（隔三数）
    3. 顶底之间至少有min_bars根不参与分型的K线
    
    算法：找到一对顶底分型后，隔三数中间K线数，满足条件才成笔
    """
    bi_list: List[Bi] = []

    # 提取所有分型
    fenxing = [(i, m.fx) for i, m in enumerate(mklines) if m.fx != FX_TYPE.TOP or m.fx != FX_TYPE.BOTTOM]
    # Re-filter properly
    fenxing = []
    for i, m in enumerate(mklines):
        if m.fx == FX_TYPE.TOP or m.fx == FX_TYPE.BOTTOM:
            fenxing.append((i, m.fx))

    if len(fenxing) < 2:
        return []

    i = 0
    while i < len(fenxing) - 1:
        idx1, fx1 = fenxing[i]
        idx2, fx2 = fenxing[i + 1]

        # 必须顶底交替
        if not ((fx1 == FX_TYPE.TOP and fx2 == FX_TYPE.BOTTOM) or
                (fx1 == FX_TYPE.BOTTOM and fx2 == FX_TYPE.TOP)):
            i += 1
            continue

        # 隔三数：检查中间K线是否有包含关系
        # "隔三" = 顶分型后数三根K线，如果这中间有包含关系，需要处理
        # 简化：直接用idx差值判断
        bars = idx2 - idx1 - 1  # 中间K线数（不含顶底分型自身）

        if bars >= min_bars:
            # 成笔
            dir = BI_DIR.DOWN if fx1 == FX_TYPE.TOP else BI_DIR.UP
            if dir == BI_DIR.DOWN:
                begin_val = mklines[idx1].high
                end_val = mklines[idx2].low
            else:
                begin_val = mklines[idx1].low
                end_val = mklines[idx2].high

            bi_list.append(Bi(
                idx=len(bi_list),
                dir=dir,
                begin=idx1,
                end=idx2,
                begin_val=begin_val,
                end_val=end_val
            ))
            i += 2  # 跳到下一对分型
        else:
            # 不成笔，继续找下一对
            i += 1

    return bi_list

# ─────────────────────────────────────────
# 第三步：线段构建
# ─────────────────────────────────────────

def build_seg(bi_list: List[Bi]) -> List[Seg]:
    """
    缠论线段构建
    规则：连续三笔有重叠，构成线段
    """
    if len(bi_list) < 3:
        return []

    segs: List[Seg] = []
    i = 0

    while i <= len(bi_list) - 3:
        b1, b2, b3 = bi_list[i], bi_list[i+1], bi_list[i+2]

        # 三笔方向相同
        if b1.dir == b2.dir == b3.dir:
            seg_dir = SEG_DIR.UP if b1.dir == BI_DIR.UP else SEG_DIR.DOWN

            segs.append(Seg(
                idx=len(segs),
                dir=seg_dir,
                begin=i,
                end=i+2
            ))
            i += 2
        else:
            i += 1

    return segs

# ─────────────────────────────────────────
# 第四步：中枢构建
# ─────────────────────────────────────────

def build_zs(segs: List[Seg], bi_list: List[Bi]) -> List[ZhongShu]:
    """
    缠论中枢构建
    规则：连续三段重叠，构成中枢
    """
    if len(segs) < 3:
        return []

    zss: List[ZhongShu] = []
    i = 0

    while i <= len(segs) - 3:
        s1, s2, s3 = segs[i], segs[i+1], segs[i+2]

        # 三段方向相同
        if s1.dir == s2.dir == s3.dir:
            # 计算每段的高低点
            if s1.dir == SEG_DIR.UP:
                segs_range = [
                    (s1.begin, s1.end, s1.begin),
                    (s2.begin, s2.end, s2.begin),
                    (s3.begin, s3.end, s3.begin)
                ]
            else:
                segs_range = [
                    (s1.begin, s1.end, s1.begin),
                    (s2.begin, s2.end, s2.begin),
                    (s3.begin, s3.end, s3.begin)
                ]

            # 中枢区间 = 三段高低点的重叠部分
            # 对于上涨段：取进入段最低点和离开段最高点
            if s1.dir == SEG_DIR.UP:
                g1 = bi_list[s1.begin].end_val  # 第一笔终点
                d1 = bi_list[s1.begin].begin_val  # 第一笔起点
                g2 = bi_list[s2.begin].end_val
                d2 = bi_list[s2.begin].begin_val
                g3 = bi_list[s3.begin].end_val
                d3 = bi_list[s3.begin].begin_val

                # 中枢 = 三段重叠区间
                zz = sorted([g1, g2, g3])  # 上沿
                zd = sorted([d1, d2, d3])   # 下沿

                z_high = zz[1]  # 中间值
                z_low = zd[1]

                if z_low < z_high:  # 重叠
                    zss.append(ZhongShu(
                        idx=len(zss),
                        begin=i,
                        end=i+2,
                        low=z_low,
                        high=z_high
                    ))
                    i += 2
                else:
                    i += 1
            else:
                i += 1
        else:
            i += 1

    return zss

# ─────────────────────────────────────────
# 第五步：背驰判断
# ─────────────────────────────────────────

def check_beichi(bi_list: List[Bi], zs: ZhongShu | None, last_bi: Bi) -> Tuple[bool, float]:
    """背驰判断"""
    if len(bi_list) < 5 or zs is None:
        return False, 0.0

    # 找到进入段
    enter_bi = None
    for bi in reversed(bi_list[:-1]):
        if bi.end <= zs.end:
            enter_bi = bi
            break

    if enter_bi is None:
        return False, 0.0

    enter_range = abs(enter_bi.end_val - enter_bi.begin_val)
    leave_range = abs(last_bi.end_val - last_bi.begin_val)

    ratio = leave_range / enter_range if enter_range > 0 else 0
    is_beichi = ratio < 0.8 and last_bi.end > zs.end

    return is_beichi, round(ratio, 3)

# ─────────────────────────────────────────
# 第六步：买卖点
# ─────────────────────────────────────────

def find_bs_points(bi_list: List[Bi], zs_list: List[ZhongShu]) -> List[BSPoint]:
    """买卖点识别"""
    if len(bi_list) < 3 or not zs_list:
        return []

    bs_points: List[BSPoint] = []
    zs = zs_list[-1]
    last_bi = bi_list[-1]
    beichi, ratio = check_beichi(bi_list, zs, last_bi)

    # 一买（下跌背驰）
    if last_bi.dir == BI_DIR.DOWN and beichi:
        bs_points.append(BSPoint(
            idx=len(bs_points), type="buy1", direction="long",
            price=last_bi.end_val, bi_idx=last_bi.idx, beichi=True
        ))

    # 二买（回调不破前低）
    if last_bi.dir == BI_DIR.UP and len(bi_list) >= 3:
        prev_down = bi_list[-2]
        if prev_down.dir == BI_DIR.DOWN:
            if last_bi.end_val > prev_down.end_val * 0.99:
                bs_points.append(BSPoint(
                    idx=len(bs_points), type="buy2", direction="long",
                    price=last_bi.end_val, bi_idx=last_bi.idx, beichi=False
                ))

    # 一卖（上涨背驰）
    if last_bi.dir == BI_DIR.UP and beichi:
        bs_points.append(BSPoint(
            idx=len(bs_points), type="sell1", direction="short",
            price=last_bi.end_val, bi_idx=last_bi.idx, beichi=True
        ))

    return bs_points

# ─────────────────────────────────────────
# 主分析函数
# ─────────────────────────────────────────

def full_chan_analysis(klines: List[KLine], period: str = "1min") -> dict:
    """完整缠论分析"""
    # 1. 包含关系处理
    mklines = process_baohan(klines)

    # 2. 笔构建
    bi_list = build_bi_strict(mklines, min_bars=4)

    # 3. 线段
    segs = build_seg(bi_list)
    zss = build_zs(segs, bi_list)

    # 4. 中枢

    # 5. 买卖点
    bs_points = find_bs_points(bi_list, zss)

    current_price = klines[-1].close if klines else 0
    first_price = klines[0].open if klines else current_price
    change = current_price - first_price
    change_pct = (change / first_price * 100) if first_price else 0

    # ECharts可视化数据
    bi_markline = []
    for b in bi_list:
        color = '#f23645' if b.dir == BI_DIR.UP else '#089981'
        bi_markline.append({
            'name': f"笔{b.idx}",
            'xAxis': b.begin, 'yAxis': b.begin_val,
            'xAxis2': b.end, 'yAxis2': b.end_val,
            'lineStyle': {'color': color, 'width': 2, 'type': 'solid'},
            'label': {'show': True, 'formatter': f"{'↑' if b.dir==BI_DIR.UP else '↓'}{b.idx}", 'color': color}
        })

    seg_markline = []
    for s in segs:
        seg_markline.append({
            'name': f"线段{s.idx}",
            'seg_idx': s.idx,
            'xAxis': bi_list[s.begin].begin,
            'yAxis': bi_list[s.begin].begin_val,
            'xAxis2': bi_list[s.end].end,
            'yAxis2': bi_list[s.end].end_val,
            'lineStyle': {'color': '#ffd93d', 'width': 3, 'type': 'solid'},
            'label': {'show': True, 'formatter': f"S{s.idx}", 'color': '#ffd93d'}
        })

    zs_markarea = []
    for z in zss:
        zs_markarea.append({
            'name': f"中枢{z.idx}",
            'xAxis': bi_list[z.begin].begin,
            'xAxis2': bi_list[z.end].end,
            'yAxis': z.low,
            'yAxis2': z.high,
            'itemStyle': {'color': 'rgba(233,69,96,0.1)', 'borderColor': '#e94560', 'borderWidth': 1, 'borderType': 'dashed'}
        })

    bs_scatter = []
    for p in bs_points:
        color = '#ff6b6b' if 'buy' in p.type else '#6bcb77'
        symbol = 'circle' if p.beichi else ('arrowUp' if 'buy' in p.type else 'arrowDown')
        bs_scatter.append({
            'name': p.type,
            'value': [bi_list[p.bi_idx].end if p.bi_idx < len(bi_list) else 0, p.price],
            'symbol': symbol,
            'symbolSize': 15 if p.beichi else 10,
            'itemStyle': {'color': color, 'shadowBlur': 10, 'shadowColor': color}
        })

    return {
        'period': period,
        'klines': [{'idx': k.idx, 'time': k.time, 'open': k.open, 'high': k.high, 'low': k.low, 'close': k.close, 'volume': k.volume} for k in klines],
        'mklines': [{'begin': m.begin, 'end': m.end, 'high': m.high, 'low': m.low, 'fx': m.fx.value} for m in mklines],
        'bi': [{'idx': b.idx, 'dir': b.dir.value, 'begin': b.begin, 'end': b.end, 'begin_val': b.begin_val, 'end_val': b.end_val, 'is_sure': b.is_sure} for b in bi_list],
        'seg': [{'idx': s.idx, 'dir': s.dir.value, 'begin': s.begin, 'end': s.end, 'is_sure': s.is_sure} for s in segs],
        'zs': [{'idx': z.idx, 'low': z.low, 'high': z.high, 'begin': z.begin, 'end': z.end, 'is_sure': z.is_sure} for z in zss],
        'bs': [{'idx': p.idx, 'type': p.type, 'direction': p.direction, 'price': p.price, 'bi_idx': p.bi_idx, 'is_sure': p.is_sure, 'beichi': p.beichi} for p in bs_points],
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

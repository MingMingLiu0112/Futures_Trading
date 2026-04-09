#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA缠论分析引擎 - 完整版
包含：笔 → 线段 → 中枢 → 买卖点 → 多级别联立 → 区间套
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Literal
from enum import Enum
import json
from datetime import datetime

# ─────────────────────────────────────────
# 枚举类型
# ─────────────────────────────────────────

class FX_TYPE(Enum):
    """分型类型"""
    TOP = "top"      # 顶分型
    BOTTOM = "bottom" # 底分型
    UNKNOWN = "unknown"

class BI_DIR(Enum):
    """笔方向"""
    UP = "up"
    DOWN = "down"

class SEG_DIR(Enum):
    """线段方向"""
    UP = "up"
    DOWN = "down"

# ─────────────────────────────────────────
# 核心数据类
# ─────────────────────────────────────────

@dataclass
class KLine:
    """单根K线"""
    idx: int
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    raw_high: float = 0
    raw_low: float = 0

@dataclass
class MergedKLine:
    """合并后的K线"""
    begin_idx: int
    end_idx: int
    high: float
    low: float
    fx: FX_TYPE = FX_TYPE.UNKNOWN
    dir: BI_DIR | None = None

@dataclass
class Bi:
    """笔"""
    idx: int
    dir: BI_DIR
    begin_idx: int
    end_idx: int
    begin_val: float  # 起点价格
    end_val: float   # 终点价格
    is_sure: bool = True  # 是否确认

@dataclass
class EigenFX:
    """特征序列分型"""
    type: FX_TYPE
    idx: int  # 在特征序列中的位置
    high: float
    low: float

@dataclass
class Seg:
    """线段"""
    idx: int
    dir: SEG_DIR
    begin_bi: Bi
    end_bi: Bi
    eigen_list: List[EigenFX] = field(default_factory=list)
    is_sure: bool = True

@dataclass
class ZhongShu:
    """中枢"""
    idx: int
    begin_seg: Seg
    end_seg: Seg
    low: float   # 中枢低
    high: float  # 中枢高
    is_sure: bool = True
    # 中枢区间 [low, high]

@dataclass
class BSPoint:
    """买卖点"""
    idx: int
    type: Literal["buy1", "buy2", "sell1", "sell2"]
    direction: Literal["long", "short"]
    price: float
    bi_idx: int
    is_sure: bool = True
    level: str = "bi"  # "bi" or "seg"
    beichi: bool = False  # 是否背驰

# ─────────────────────────────────────────
# 包含关系处理
# ─────────────────────────────────────────

def process_baohan(klines: List[KLine]) -> List[MergedKLine]:
    """
    处理K线包含关系，返回合并后的K线序列
    规则：
    - 上升趋势中包含：高高原则 (max high, max low)
    - 下降趋势中包含：低低原则 (min high, min low)
    趋势判断：看包含处理后K线的低点
    """
    if not klines:
        return []

    result: List[MergedKLine] = []

    for i, kl in enumerate(klines):
        if not result:
            result.append(MergedKLine(
                begin_idx=i, end_idx=i,
                high=kl.high, low=kl.low
            ))
            continue

        prev = result[-1]
        curr_high, curr_low = kl.high, kl.low
        prev_high, prev_low = prev.high, prev.low

        # 判断是否存在包含关系
        has_contain = (
            (curr_high <= prev_high and curr_low >= prev_low) or
            (curr_high >= prev_high and curr_low <= prev_low)
        )

        if not has_contain:
            result.append(MergedKLine(
                begin_idx=prev.end_idx + 1, end_idx=i,
                high=curr_high, low=curr_low
            ))
        else:
            # 判断趋势：比较处理后K线与当前K线的低点
            if curr_low > prev_low:
                # 上升趋势 → 高高原则
                new_high = max(prev_high, curr_high)
                new_low = max(prev_low, curr_low)
            else:
                # 下降趋势 → 低低原则
                new_high = min(prev_high, curr_high)
                new_low = min(prev_low, curr_low)

            result[-1] = MergedKLine(
                begin_idx=prev.begin_idx, end_idx=i,
                high=new_high, low=new_low
            )

    # 标记分型
    n = len(result)
    for i in range(1, n - 1):
        p = result[i - 1]
        c = result[i]
        ne = result[i + 1]

        # 顶分型：中间K线高点最高，低点也高于左右
        if c.high > p.high and c.high > ne.high and c.low > p.low and c.low > ne.low:
            c.fx = FX_TYPE.TOP
        # 底分型：中间K线高点最低，低点也低于左右
        elif c.high < p.high and c.high < ne.high and c.low < p.low and c.low < ne.low:
            c.fx = FX_TYPE.BOTTOM

    return result

# ─────────────────────────────────────────
# 笔构建
# ─────────────────────────────────────────

def build_bi(mklines: List[MergedKLine], bi_min_bars: int = 5) -> List[Bi]:
    """
    从合并K线构建笔
    笔：连续顶底分型之间，至少bi_min_bars根不包含分型的K线
    """
    if len(mklines) < 3:
        return []

    bi_list: List[Bi] = []
    fenxing = [(i, m.fx) for i, m in enumerate(mklines) if m.fx != FX_TYPE.UNKNOWN]

    i = 0
    while i < len(fenxing) - 1:
        idx1, fx1 = fenxing[i]
        idx2, fx2 = fenxing[i + 1]

        # 顶底交替
        if fx1 == FX_TYPE.TOP and fx2 == FX_TYPE.BOTTOM:
            # 笔：从顶到下一底（下降笔）
            bars = idx2 - idx1
            if bars >= bi_min_bars:
                bi_list.append(Bi(
                    idx=len(bi_list),
                    dir=BI_DIR.DOWN,
                    begin_idx=idx1,
                    end_idx=idx2,
                    begin_val=mklines[fenxing[i][0]].high,
                    end_val=mklines[idx2].low,
                    is_sure=True
                ))
            i += 2

        elif fx1 == FX_TYPE.BOTTOM and fx2 == FX_TYPE.TOP:
            # 笔：从底到下一顶（上升笔）
            bars = idx2 - idx1
            if bars >= bi_min_bars:
                bi_list.append(Bi(
                    idx=len(bi_list),
                    dir=BI_DIR.UP,
                    begin_idx=idx1,
                    end_idx=idx2,
                    begin_val=mklines[fenxing[i][0]].low,
                    end_val=mklines[idx2].high,
                    is_sure=True
                ))
            i += 2
        else:
            i += 1

    return bi_list

# ─────────────────────────────────────────
# 线段构建
# ─────────────────────────────────────────

def build_seg(bi_list: List[Bi], mklines: List[MergedKLine]) -> List[Seg]:
    """
    从笔构建线段
    线段：连续三笔重叠，形成特征序列，由特征序列分型确认
    """
    if len(bi_list) < 3:
        return []

    segs: List[Seg] = []

    # 构造特征序列
    eigen_list: List[EigenFX] = []

    for i, bi in enumerate(bi_list):
        # 上升笔 → 特征序列取最高点
        # 下降笔 → 特征序列取最低点
        if bi.dir == BI_DIR.UP:
            eigen_list.append(EigenFX(
                type=FX_TYPE.TOP if i > 0 and bi_list[i-1].dir == BI_DIR.DOWN else FX_TYPE.UNKNOWN,
                idx=i,
                high=bi.end_val,
                low=bi.end_val
            ))
        else:
            eigen_list.append(EigenFX(
                type=FX_TYPE.BOTTOM if i > 0 and bi_list[i-1].dir == BI_DIR.UP else FX_TYPE.UNKNOWN,
                idx=i,
                high=bi.begin_val,
                low=bi.begin_val
            ))

    # 简化线段：直接用三笔重叠构建
    i = 0
    while i <= len(bi_list) - 3:
        b1, b2, b3 = bi_list[i], bi_list[i+1], bi_list[i+2]

        # 三笔方向相同则成线段
        if b1.dir == b2.dir == b3.dir:
            seg_dir = SEG_DIR.UP if b1.dir == BI_DIR.UP else SEG_DIR.DOWN

            segs.append(Seg(
                idx=len(segs),
                dir=seg_dir,
                begin_bi=b1,
                end_bi=b3,
                eigen_list=eigen_list[i:i+3],
                is_sure=True
            ))
            i += 2
        else:
            i += 1

    return segs

# ─────────────────────────────────────────
# 中枢构建
# ─────────────────────────────────────────

def build_zs(segs: List[Seg]) -> List[ZhongShu]:
    """
    从线段构建中枢
    中枢：连续三段重叠区间
    """
    if len(segs) < 3:
        return []

    zss: List[ZhongShu] = []

    i = 0
    while i <= len(segs) - 3:
        s1, s2, s3 = segs[i], segs[i+1], segs[i+2]

        # 三段方向相同才构成中枢
        if s1.dir == s2.dir == s3.dir:
            # 取三段的高低点区间
            seg_highs = []
            seg_lows = []

            for s in [s1, s2, s3]:
                if s.dir == SEG_DIR.UP:
                    seg_highs.append(s.end_bi.end_val)
                    seg_lows.append(s.begin_bi.begin_val)
                else:
                    seg_highs.append(s.begin_bi.begin_val)
                    seg_lows.append(s.end_bi.end_val)

            # 重叠区间
            overlap_high = min(seg_highs)
            overlap_low = max(seg_lows)

            if overlap_low < overlap_high:  # 有重叠
                zss.append(ZhongShu(
                    idx=len(zss),
                    begin_seg=s1,
                    end_seg=s3,
                    low=overlap_low,
                    high=overlap_high,
                    is_sure=True
                ))
                i += 2
            else:
                i += 1
        else:
            i += 1

    return zss

# ─────────────────────────────────────────
# 背驰判断
# ─────────────────────────────────────────

def check_beichi(bi_list: List[Bi], zs: ZhongShu | None, last_bi: Bi) -> Tuple[bool, float]:
    """
    背驰判断
    比较离开段和进入段的力度（用价格距离和持续笔数）
    返回：(是否背驰, 力度比)
    """
    if len(bi_list) < 5 or zs is None:
        return False, 0.0

    # 取最近在中枢内的笔作为进入段
    enter_bi = None
    for bi in reversed(bi_list[:-1]):
        if zs.begin_seg.begin_bi.idx <= bi.idx <= zs.end_seg.end_bi.idx:
            if bi.dir != last_bi.dir:
                enter_bi = bi
                break

    if enter_bi is None:
        return False, 0.0

    # 计算力度
    enter_range = abs(enter_bi.end_val - enter_bi.begin_val)
    leave_range = abs(last_bi.end_val - last_bi.begin_val)
    enter_bars = enter_bi.end_idx - enter_bi.begin_idx
    leave_bars = last_bi.end_idx - last_bi.begin_idx

    # 力度 = 价格距离 * 持续K线数
    enter_power = enter_range * (enter_bars / 5.0)
    leave_power = leave_range * (leave_bars / 5.0)

    ratio = leave_power / enter_power if enter_power > 0 else 0

    # 背驰条件：离开段力度 < 进入段力度，且离开段不再回到中枢
    is_beichi = (
        ratio < 0.8 and
        last_bi.end_idx > zs.end_seg.end_bi.end_idx
    )

    return is_beichi, round(ratio, 3)

# ─────────────────────────────────────────
# 买卖点计算
# ─────────────────────────────────────────

def find_bs_points(bi_list: List[Bi], zs_list: List[ZhongShu]) -> List[BSPoint]:
    """
    识别买卖点
    一买：离开中枢后的背驰低点
    二买：回调不破前低的点
    一卖：离开中枢后的背驰高点
    二卖：反弹不破前高的点
    """
    if len(bi_list) < 5 or not zs_list:
        return []

    bs_points: List[BSPoint] = []
    zs = zs_list[-1]  # 最近的中枢

    last_bi = bi_list[-1]
    beichi, ratio = check_beichi(bi_list, zs, last_bi)

    # 一买（下降趋势背驰）
    if last_bi.dir == BI_DIR.DOWN and beichi:
        bs_points.append(BSPoint(
            idx=len(bs_points),
            type="buy1",
            direction="long",
            price=last_bi.end_val,
            bi_idx=last_bi.idx,
            is_sure=True,
            level="bi",
            beichi=True
        ))

    # 二买（回调不破一买低点）
    if last_bi.dir == BI_DIR.UP and len(bi_list) >= 3:
        prev_down = bi_list[-2]
        if prev_down.dir == BI_DIR.DOWN:
            if last_bi.end_val > prev_down.end_val * 0.98:  # 不破前低2%
                bs_points.append(BSPoint(
                    idx=len(bs_points),
                    type="buy2",
                    direction="long",
                    price=last_bi.end_val,
                    bi_idx=last_bi.idx,
                    is_sure=True,
                    level="bi",
                    beichi=False
                ))

    # 一卖（上升趋势背驰）
    if last_bi.dir == BI_DIR.UP and beichi:
        bs_points.append(BSPoint(
            idx=len(bs_points),
            type="sell1",
            direction="short",
            price=last_bi.end_val,
            bi_idx=last_bi.idx,
            is_sure=True,
            level="bi",
            beichi=True
        ))

    # 二卖（反弹不破一卖高点）
    if last_bi.dir == BI_DIR.DOWN and len(bi_list) >= 3:
        prev_up = bi_list[-2]
        if prev_up.dir == BI_DIR.UP:
            if last_bi.end_val < prev_up.end_val * 1.02:  # 不破前高2%
                bs_points.append(BSPoint(
                    idx=len(bs_points),
                    type="sell2",
                    direction="short",
                    price=last_bi.end_val,
                    bi_idx=last_bi.idx,
                    is_sure=True,
                    level="bi",
                    beichi=False
                ))

    return bs_points

# ─────────────────────────────────────────
# 多级别联立分析
# ─────────────────────────────────────────

@dataclass
class MultiLevelResult:
    """多级别分析结果"""
    period: str
    klines: List[dict]
    mklines: List[dict]
    bi_list: List[dict]
    seg_list: List[dict]
    zs_list: List[dict]
    bs_points: List[dict]
    current_price: float
    change: float
    change_pct: float
    timestamp: str

def analyze_multi_level(period_klines: Dict[str, List[KLine]], periods: List[str]) -> Dict[str, MultiLevelResult]:
    """
    多级别联立分析
    periods: 如 ["1min", "5min", "15min", "30min", "60min", "1day"]
    """
    results = {}

    for period in periods:
        klines = period_klines.get(period, [])
        if len(klines) < 10:
            continue

        # 1. 合并K线
        mklines = process_baohan(klines)

        # 2. 笔
        bi_list = build_bi(mklines)

        # 3. 线段
        seg_list = build_seg(bi_list, mklines)

        # 4. 中枢
        zs_list = build_zs(seg_list)

        # 5. 买卖点
        bs_points = find_bs_points(bi_list, zs_list)

        # 当前价格
        current_price = klines[-1].close if klines else 0
        first_price = klines[0].open if klines else current_price
        change = current_price - first_price
        change_pct = (change / first_price * 100) if first_price else 0

        results[period] = MultiLevelResult(
            period=period,
            klines=[{
                'idx': k.idx, 'time': k.time, 'open': k.open,
                'high': k.high, 'low': k.low, 'close': k.close, 'volume': k.volume
            } for k in klines],
            mklines=[{
                'begin': m.begin_idx, 'end': m.end_idx,
                'high': m.high, 'low': m.low,
                'fx': m.fx.value if m.fx else 'unknown'
            } for m in mklines],
            bi_list=[{
                'idx': b.idx, 'dir': b.dir.value, 'begin': b.begin_idx,
                'end': b.end_idx, 'begin_val': b.begin_val,
                'end_val': b.end_val, 'is_sure': b.is_sure
            } for b in bi_list],
            seg_list=[{
                'idx': s.idx, 'dir': s.dir.value,
                'begin_bi': s.begin_bi.idx, 'end_bi': s.end_bi.idx,
                'begin_val': s.begin_bi.begin_val,
                'end_val': s.end_bi.end_val,
                'is_sure': s.is_sure
            } for s in seg_list],
            zs_list=[{
                'idx': z.idx, 'low': z.low, 'high': z.high,
                'begin': z.begin_seg.idx, 'end': z.end_seg.idx,
                'is_sure': z.is_sure
            } for z in zs_list],
            bs_points=[{
                'idx': p.idx, 'type': p.type, 'direction': p.direction,
                'price': p.price, 'bi_idx': p.bi_idx,
                'is_sure': p.is_sure, 'beichi': p.beichi
            } for p in bs_points],
            current_price=round(current_price, 2),
            change=round(change, 2),
            change_pct=round(change_pct, 2),
            timestamp=datetime.now().isoformat()
        )

    return results

# ─────────────────────────────────────────
# 区间套分析（用小级别递归分析大级别关键位）
# ─────────────────────────────────────────

def find_interval_nesting(multi_results: Dict[str, MultiLevelResult]) -> Dict:
    """
    区间套分析
    在大级别关键位置（中枢边界、前高前低），用小级别递归确认
    """
    nesting_result = {
        'key_levels': [],  # 关键价位
        'nested_confirm': [],  # 嵌套确认信号
    }

    if not multi_results:
        return nesting_result

    # 获取各级别最后一个中枢
    for period, result in multi_results.items():
        if result.zs_list:
            last_zs = result.zs_list[-1]
            nesting_result['key_levels'].append({
                'period': period,
                'type': 'zs',
                'low': last_zs['low'],
                'high': last_zs['high'],
                'mid': round((last_zs['low'] + last_zs['high']) / 2, 2)
            })

        if result.bs_points:
            last_bs = result.bs_points[-1]
            nesting_result['key_levels'].append({
                'period': period,
                'type': 'bs',
                'bs_type': last_bs['type'],
                'price': last_bs['price'],
                'beichi': last_bs['beichi']
            })

    return nesting_result

# ─────────────────────────────────────────
# ECharts 可视化数据导出
# ─────────────────────────────────────────

def export_for_echarts(result: MultiLevelResult) -> dict:
    """导出缠论元素为 ECharts markLine/markArea 格式"""
    bi_markline = []
    for b in result.bi_list:
        color = '#f23645' if b['dir'] == 'up' else '#089981'
        bi_markline.append({
            'name': f"笔{b['idx']}",
            'xAxis': b['begin'],
            'yAxis': b['begin_val'],
            'xAxis2': b['end'],
            'yAxis2': b['end_val'],
            'lineStyle': {'color': color, 'width': 2, 'type': 'solid' if b['is_sure'] else 'dashed'},
            'label': {'show': True, 'formatter': f"{'↑' if b['dir']=='up' else '↓'}{b['idx']}", 'color': color}
        })

    seg_markline = []
    for s in result.seg_list:
        seg_markline.append({
            'name': f"线段{s['idx']}",
            'seg_idx': s['idx'],
            'xAxis': s['begin_bi'],
            'yAxis': s['begin_val'],
            'xAxis2': s['end_bi'],
            'yAxis2': s['end_val'],
            'lineStyle': {'color': '#ffd93d', 'width': 3, 'type': 'solid'},
            'label': {'show': True, 'formatter': f"S{s['idx']}", 'color': '#ffd93d'}
        })

    zs_markarea = []
    for z in result.zs_list:
        color = 'rgba(233,69,96,0.15)'
        zs_markarea.append({
            'name': f"中枢{z['idx']}",
            'xAxis': z['begin'],
            'xAxis2': z['end'],
            'yAxis': z['low'],
            'yAxis2': z['high'],
            'itemStyle': {'color': color, 'borderColor': '#e94560', 'borderWidth': 1, 'borderType': 'dashed'},
            'label': {'show': True, 'formatter': f"Z{z['idx']}", 'color': '#e94560', 'fontSize': 10}
        })

    bs_scatter = []
    for p in result.bs_points:
        color = '#ff6b6b' if 'buy' in p['type'] else '#6bcb77'
        symbol = 'circle' if p['beichi'] else 'arrowUp' if 'buy' in p['type'] else 'arrowDown'
        bs_scatter.append({
            'name': p['type'],
            'value': [p.get('bi_idx', 0), p['price']],
            'symbol': symbol,
            'symbolSize': 15 if p['beichi'] else 10,
            'itemStyle': {'color': color, 'shadowBlur': 10, 'shadowColor': color}
        })

    return {
        'bi_markline': bi_markline,
        'seg_markline': seg_markline,
        'zs_markarea': zs_markarea,
        'bs_scatter': bs_scatter,
        'summary': {
            'bi_count': len(result.bi_list),
            'seg_count': len(result.seg_list),
            'zs_count': len(result.zs_list),
            'bs_count': len(result.bs_points),
            'current_price': result.current_price,
            'change': result.change,
            'change_pct': result.change_pct,
        }
    }

# ─────────────────────────────────────────
# 主分析入口
# ─────────────────────────────────────────

def full_chan_analysis(klines: List[KLine], period: str = "1min") -> dict:
    """
    完整缠论分析
    返回：klines原始 + 合并K线 + 笔 + 线段 + 中枢 + 买卖点 + ECharts数据
    """
    # 1. 合并K线
    mklines = process_baohan(klines)

    # 2. 笔
    bi_list = build_bi(mklines)

    # 3. 线段
    seg_list = build_seg(bi_list, mklines)

    # 4. 中枢
    zs_list = build_zs(seg_list)

    # 5. 买卖点
    bs_points = find_bs_points(bi_list, zs_list)

    current_price = klines[-1].close if klines else 0
    first_price = klines[0].open if klines else current_price
    change = current_price - first_price
    change_pct = (change / first_price * 100) if first_price else 0

    result = MultiLevelResult(
        period=period,
        klines=[{
            'idx': k.idx, 'time': k.time, 'open': k.open,
            'high': k.high, 'low': k.low, 'close': k.close, 'volume': k.volume
        } for k in klines],
        mklines=[{
            'begin': m.begin_idx, 'end': m.end_idx,
            'high': m.high, 'low': m.low,
            'fx': m.fx.value if m.fx else 'unknown'
        } for m in mklines],
        bi_list=[{
            'idx': b.idx, 'dir': b.dir.value, 'begin': b.begin_idx,
            'end': b.end_idx, 'begin_val': b.begin_val,
            'end_val': b.end_val, 'is_sure': b.is_sure
        } for b in bi_list],
        seg_list=[{
            'idx': s.idx, 'dir': s.dir.value,
            'begin_bi': s.begin_bi.idx, 'end_bi': s.end_bi.idx,
            'begin_val': s.begin_bi.begin_val,
            'end_val': s.end_bi.end_val,
            'is_sure': s.is_sure
        } for s in seg_list],
        zs_list=[{
            'idx': z.idx, 'low': z.low, 'high': z.high,
            'begin': z.begin_seg.idx, 'end': z.end_seg.idx,
            'is_sure': z.is_sure
        } for z in zs_list],
        bs_points=[{
            'idx': p.idx, 'type': p.type, 'direction': p.direction,
            'price': p.price, 'bi_idx': p.bi_idx,
            'is_sure': p.is_sure, 'beichi': p.beichi
        } for p in bs_points],
        current_price=round(current_price, 2),
        change=round(change, 2),
        change_pct=round(change_pct, 2),
        timestamp=datetime.now().isoformat()
    )

    echarts_data = export_for_echarts(result)

    return {
        'period': period,
        'klines': result.klines,
        'mklines': result.mklines,
        'bi': result.bi_list,
        'seg': result.seg_list,
        'zs': result.zs_list,
        'bs': result.bs_points,
        'current_price': result.current_price,
        'change': result.change,
        'change_pct': result.change_pct,
        'timestamp': result.timestamp,
        'echarts': echarts_data,
        'stats': echarts_data['summary']
    }

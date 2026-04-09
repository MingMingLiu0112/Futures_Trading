#!/usr/bin/env python3
"""PTA缠论分析 - chan_core 封装 (支持多级别)"""
import sys, time

# chan_core 在同目录
from chan_core import (
    kl_to_kls, merge_include, find_fenxing,
    build_bi, build_seg, build_zs, find_bs_points,
    aggregate_klines_fixed, aggregate_by_bi, multi_level_analysis,
    analyze_level
)

# 全局缓存
_cache = {}


def _build_markline_from_bis(bis):
    """从笔列表构建 echarts markLine 格式"""
    bi_markline = []
    for b in bis:
        bi_markline.append({
            'idx': b.idx, 'dir': b.dir,
            'xAxis': b.begin_idx, 'xAxis2': b.end_idx,
            'yAxis': b.begin_price, 'yAxis2': b.end_price,
            'lineStyle': {'color': '#f36' if b.dir == 'up' else '#3af', 'width': 2}
        })
    return bi_markline


def _build_markline_from_segs(segs):
    """从线段列表构建 echarts markLine 格式"""
    seg_markline = []
    for s in segs:
        seg_markline.append({
            'idx': s.idx, 'dir': s.dir,
            'xAxis': s.begin_idx, 'xAxis2': s.end_idx,
            'yAxis': s.begin_price, 'yAxis2': s.end_price,
            'lineStyle': {'color': '#ff1493' if s.dir == 'up' else '#00ced1', 'width': 3}
        })
    return seg_markline


def _build_zs_data(zss):
    """从中枢列表构建 echarts markArea 格式"""
    zs_data = []
    for z in zss:
        zs_data.append({
            'idx': z.idx,
            'xAxis': z.begin_idx, 'xAxis2': z.end_idx,
            'yAxis': z.low, 'yAxis2': z.high
        })
    return zs_data


def _build_bs_scatter(bs_points, bis):
    """从买卖点列表构建 echarts scatter 格式"""
    bs_data = []
    for bp in bs_points:
        bi_kline_idx = bis[bp.bi_idx].end_idx if bp.bi_idx < len(bis) else bp.bi_idx
        bs_data.append({
            'idx': bp.idx, 'type': bp.type,
            'direction': bp.direction,
            'xAxis': bi_kline_idx, 'yAxis': bp.price,
            'value': [bi_kline_idx, bp.price],
            'itemStyle': {'color': '#ff4757' if 'sell' in bp.type else '#2ed573'},
            'label': {'formatter': bp.type.upper()}
        })
    return bs_data


def _kls_to_dict(kls):
    """KL列表转换为字典格式（用于序列化）"""
    return [{
        'idx': k.idx,
        'time': k.time,
        'open': k.open,
        'high': k.high,
        'low': k.low,
        'close': k.close,
        'volume': k.volume,
        'dif': k.dif,
        'dea': k.dea,
        'macd': k.macd
    } for k in kls]


def get_chan_result(period='1min', level=1):
    """缠论分析主入口 - 兼容 chan_wrapper 接口
    
    Args:
        period: K线周期 ('1min', '5min', '15min', '30min', '60min', '1day')
        level: 分析级别 (1=原始/单级别, 2/3/4=多级别聚合分析)
               当 level > 1 时，返回包含多级别分析结果的字典
        
    Returns:
        单级别(默认): 兼容原接口的结果字典
        多级别(level>1): {
            'success': True,
            'period': period,
            'level': level,  # 请求的级别
            'klines': [...],  # 原始K线数据
            'multi_level': {
                1: {'klines': [...], 'bi_markline': [...], 'seg_markline': [...], 'zs_data': [...], 'bs_data': [...]},
                2: {...},
                ...
            },
            'stats': {...},
            ...
        }
    """
    cache_key = f"pta_{period}_level{level}_{id(period)}"
    now = time.time()
    
    if cache_key in _cache:
        cached, ts = _cache[cache_key]
        if now - ts < 60:
            return cached
    
    import akshare as ak
    
    try:
        if period == '1day':
            df = ak.futures_zh_daily_sina(symbol="TA0")
            df = df.sort_values('date').tail(500).reset_index(drop=True)
            kl_data = [{
                'time': str(r['date']),
                'open': float(r['open']),
                'high': float(r['high']),
                'low': float(r['low']),
                'close': float(r['close']),
                'volume': float(r.get('volume', 0))
            } for _, r in df.iterrows()]
        else:
            pmap = {"1min": "1", "5min": "5", "15min": "15", "30min": "30", "60min": "60"}
            pval = pmap.get(period, "1")
            df = ak.futures_zh_minute_sina(symbol="TA0", period=pval)
            df = df.sort_values('datetime').tail(1000).reset_index(drop=True)
            kl_data = [{
                'time': str(r['datetime']),
                'open': float(r['open']),
                'high': float(r['high']),
                'low': float(r['low']),
                'close': float(r['close']),
                'volume': float(r.get('volume', 0))
            } for _, r in df.iterrows()]
    except Exception as e:
        return {'error': f'数据获取失败: {e}', 'period': period}
    
    if not kl_data:
        return {'error': 'No data', 'period': period}
    
    import pandas as pd
    df2 = pd.DataFrame(kl_data)
    
    if level <= 1:
        # ===== 单级别分析（保持向后兼容）=====
        kls = kl_to_kls(df2)
        mkls = merge_include(kls)
        fxs = find_fenxing(mkls)
        bis = build_bi(mkls, fxs, min_k=4, small_bi_points=30)
        segs = build_seg(bis)
        zss = build_zs(segs)
        bs_points = find_bs_points(bis, zss, mkls)
        
        bi_markline = _build_markline_from_bis(bis)
        seg_markline = _build_markline_from_segs(segs)
        zs_data = _build_zs_data(zss)
        bs_data = _build_bs_scatter(bs_points, bis)
        
        result = {
            'success': True,
            'period': period,
            'level': 1,
            'klines': kl_data,
            'stats': {
                'bi_count': len(bis),
                'seg_count': len(segs),
                'zs_count': len(zss),
                'bs_count': len(bs_points),
                'current_price': kl_data[-1]['close'] if kl_data else 0,
                'last_time': kl_data[-1]['time'] if kl_data else ''
            },
            'bi_markline': bi_markline,
            'seg_markline': seg_markline,
            'zs_data': zs_data,
            'bs_data': bs_data,
            'echarts': {
                'bi_markline': bi_markline,
                'seg_markline': seg_markline,
                'zs_markarea': zs_data,
                'bs_scatter': bs_data
            }
        }
    else:
        # ===== 多级别分析 =====
        # Step 1: 获取原始K线
        kls = kl_to_kls(df2)
        
        # Step 2: 根据请求的级别，聚合K线
        if level == 2:
            agg_kls = aggregate_klines_fixed(kls, level=2)
        elif level == 3:
            agg_kls = aggregate_klines_fixed(kls, level=3)
        elif level == 4:
            # 级别4需要先做级别2的笔分析，然后用笔来聚合
            agg_kls = aggregate_klines_fixed(kls, level=2)
        else:
            agg_kls = aggregate_klines_fixed(kls, level=2)
        
        # Step 3: 分析指定级别的K线
        result_level = analyze_level(agg_kls, level=level, min_k=4, small_bi_points=30)
        
        bis = result_level['bis']
        segs = result_level['segs']
        zss = result_level['zss']
        bs_points = result_level['bs_points']
        
        bi_markline = _build_markline_from_bis(bis)
        seg_markline = _build_markline_from_segs(segs)
        zs_data = _build_zs_data(zss)
        bs_data = _build_bs_scatter(bs_points, bis)
        
        # 聚合K线数据
        agg_kl_data = _kls_to_dict(agg_kls)
        
        result = {
            'success': True,
            'period': period,
            'level': level,
            'klines': kl_data,           # 原始K线
            'aggregated_klines': agg_kl_data,  # 聚合后K线
            'stats': {
                'bi_count': len(bis),
                'seg_count': len(segs),
                'zs_count': len(zss),
                'bs_count': len(bs_points),
                'current_price': kl_data[-1]['close'] if kl_data else 0,
                'last_time': kl_data[-1]['time'] if kl_data else '',
                'kls_count': len(kls),
                'agg_kls_count': len(agg_kls)
            },
            'bi_markline': bi_markline,
            'seg_markline': seg_markline,
            'zs_data': zs_data,
            'bs_data': bs_data,
            'echarts': {
                'bi_markline': bi_markline,
                'seg_markline': seg_markline,
                'zs_markarea': zs_data,
                'bs_scatter': bs_data
            }
        }
        
        # 如果请求的级别 >= 4，额外计算级别2的笔合并结果
        if level >= 4:
            # 先获取级别2的笔
            level2_kls = aggregate_klines_fixed(kls, level=2)
            level2_result = analyze_level(level2_kls, level=2, min_k=4, small_bi_points=30)
            level2_bis = level2_result['bis']
            
            # 用级别2的笔来聚合K线
            bi_agg_kls = aggregate_by_bi(kls, level2_bis)
            bi_agg_kl_data = _kls_to_dict(bi_agg_kls)
            
            result['aggregated_klines'] = bi_agg_kl_data
            result['stats']['bi_agg_kls_count'] = len(bi_agg_kls)
    
    _cache[cache_key] = (result, now)
    return result


def get_multi_level_result(period='1min', max_level=4):
    """获取多级别完整分析结果
    
    Args:
        period: K线周期
        max_level: 最大级别数 (1=原始, 2=3合1, 3=5合1, 4=笔合并)
        
    Returns:
        包含所有级别分析结果的字典
    """
    cache_key = f"pta_{period}_multilevel_{max_level}"
    now = time.time()
    
    if cache_key in _cache:
        cached, ts = _cache[cache_key]
        if now - ts < 60:
            return cached
    
    import akshare as ak
    
    try:
        if period == '1day':
            df = ak.futures_zh_daily_sina(symbol="TA0")
            df = df.sort_values('date').tail(500).reset_index(drop=True)
        else:
            pmap = {"1min": "1", "5min": "5", "15min": "15", "30min": "30", "60min": "60"}
            pval = pmap.get(period, "1")
            df = ak.futures_zh_minute_sina(symbol="TA0", period=pval)
            df = df.sort_values('datetime').tail(1000).reset_index(drop=True)
    except Exception as e:
        return {'error': f'数据获取失败: {e}', 'period': period}
    
    if df.empty:
        return {'error': 'No data', 'period': period}
    
    # 调用多级别分析
    results = multi_level_analysis(df, max_level=max_level)
    
    # 构建返回格式
    multi_level_data = {}
    for lvl, r in results.items():
        bis = r['bis']
        segs = r['segs']
        zss = r['zss']
        bs_points = r['bs_points']
        
        multi_level_data[lvl] = {
            'klines': _kls_to_dict(r['kls']),
            'kls_count': len(r['kls']),
            'bi_count': len(bis),
            'seg_count': len(segs),
            'zs_count': len(zss),
            'bs_count': len(bs_points),
            'bi_markline': _build_markline_from_bis(bis),
            'seg_markline': _build_markline_from_segs(segs),
            'zs_data': _build_zs_data(zss),
            'bs_data': _build_bs_scatter(bs_points, bis)
        }
    
    result = {
        'success': True,
        'period': period,
        'max_level': max_level,
        'multi_level': multi_level_data,
        'stats': {
            lvl: {
                'kls_count': d['kls_count'],
                'bi_count': d['bi_count'],
                'seg_count': d['seg_count'],
                'zs_count': d['zs_count']
            }
            for lvl, d in multi_level_data.items()
        }
    }
    
    _cache[cache_key] = (result, now)
    return result

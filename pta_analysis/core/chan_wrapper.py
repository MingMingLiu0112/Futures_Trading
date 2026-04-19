#!/usr/bin/env python3
"""PTA缠论分析 - 简单封装"""
import sys
sys.path.insert(0, '/home/admin/.openclaw/workspace/codeman/pta_analysis')

def get_chan_result(period='1min', max_level=4):
    from chan_analyzer import chan_analysis as _ca
    result = _ca(period=period, max_level=max_level)
    # 将 current_price 提升到顶层，方便前端直接取用
    if 'stats' in result and 'current_price' in result['stats']:
        result['current_price'] = result['stats']['current_price']
    return result

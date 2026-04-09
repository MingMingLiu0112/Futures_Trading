#!/usr/bin/env python3
"""PTA缠论分析 - 简单封装"""
import sys
sys.path.insert(0, '/home/admin/.openclaw/workspace/codeman/pta_analysis')

def get_chan_result(period='1min', max_level=4):
    from chan_analyzer import chan_analysis as _ca
    return _ca(period=period, max_level=max_level)

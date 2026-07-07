#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA 决策层单测（v2.11.68）

覆盖：
  1. compute_pain_slope: 9 象限 regime
  2. _get_intraday_slot_pair: 整点匹配
  3. _build_intraday_change: 1h 变化 dict
  4. _build_daily_change: vs 昨日 15:00 变化 dict
  5. L1 PAIN: 4 斜率字段 + 1h + daily 变化
  6. L2 GEX: net_gex 变化 + gex_flip 迁移
  7. L3 资金意图: B 方案 detail_section_ref
  8. L4 情绪: trend_1h
  9. synthesize_decision: 5 分支决策

跑法：
  cd /home/admin/.openclaw/workspace/Futures_Trading/pta_analysis
  /home/admin/.pyenv/versions/3.11.9/bin/python3 -m pytest scripts/test_judge_state.py -v
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest
from judge_state import (
    compute_pain_slope,
    _get_intraday_slot_pair,
    _build_intraday_change,
    _build_daily_change,
    judge_layer1_pain_structure,
    judge_layer2_gex,
    judge_layer3_funding_intent,
    judge_layer4_emotion,
    synthesize_decision,
    label_standardize,
    SCORE_STRONG, SCORE_MEDIUM, SCORE_WEAK,
    # v2.11.84 双门槛工具函数
    _strike_meets_threshold, _compute_strike_weight,
    STRIKE_MIN_OI_ABS, STRIKE_MIN_IV_PCT,
)


# ============================================================
# Test 1: compute_pain_slope
# ============================================================
def test_compute_pain_slope_leftSteep():
    """MP 左侧斜率大 → leftSteep"""
    # 模拟 pain_curve: 左侧斜率 > 右侧斜率
    pain_curve = [
        {'strike': 4800, 'pain': 100},
        {'strike': 5000, 'pain': 500},   # 左陡（看跌阻力大）
        {'strike': 5200, 'pain': 800},
        {'strike': 5400, 'pain': 900},
        {'strike': 5600, 'pain': 100},   # ← MP
        {'strike': 5800, 'pain': 300},   # 右缓（看涨阻力小）
        {'strike': 6000, 'pain': 500},
    ]
    r = compute_pain_slope(pain_curve, mp_strike=5600)
    assert r['slope_down'] > 0, f"左斜率应为正: {r}"
    assert r['slope_up'] > 0, f"右斜率应为正: {r}"
    assert r['slope_down'] > r['slope_up'], f"左斜率应大于右斜率: {r}"
    assert r['slope_ratio'] > 1.0


def test_compute_pain_slope_rightSteep():
    """MP 右侧斜率大 → rightSteep"""
    pain_curve = [
        {'strike': 4800, 'pain': 100},
        {'strike': 5000, 'pain': 150},
        {'strike': 5200, 'pain': 200},
        {'strike': 5400, 'pain': 100},   # ← MP
        {'strike': 5600, 'pain': 400},   # 右陡
        {'strike': 5800, 'pain': 800},
        {'strike': 6000, 'pain': 1200},
    ]
    r = compute_pain_slope(pain_curve, mp_strike=5400)
    assert r['slope_up'] > r['slope_down']


def test_compute_pain_slope_symmetric():
    """对称 → ratio < 1.2 → '对称'"""
    pain_curve = [
        {'strike': 4800, 'pain': 100},
        {'strike': 5000, 'pain': 200},
        {'strike': 5200, 'pain': 300},
        {'strike': 5400, 'pain': 100},   # ← MP
        {'strike': 5600, 'pain': 300},
        {'strike': 5800, 'pain': 400},
        {'strike': 6000, 'pain': 500},
    ]
    r = compute_pain_slope(pain_curve, mp_strike=5400)
    assert r['slope_ratio'] < 1.2
    assert r['slope_regime'] == '对称'


def test_compute_pain_slope_empty():
    """空 pain_curve → unknown"""
    r = compute_pain_slope([], mp_strike=0)
    assert r['slope_regime'] == 'unknown'


# ============================================================
# Test 2: _get_intraday_slot_pair
# ============================================================
def test_get_intraday_slot_pair_normal():
    """正常情况：找 1h 前的 slot"""
    slots = [
        {'slot': '10:00', 'F': 5680, 'ts': '2026-07-01T10:00:00'},
        {'slot': '11:00', 'F': 5600, 'ts': '2026-07-01T11:00:00'},
    ]
    now, old = _get_intraday_slot_pair(slots, hours=1)
    assert now is not None
    assert old is not None
    assert now['slot'] == '11:00'
    assert old['slot'] == '10:00'


def test_get_intraday_slot_pair_too_few():
    """少于 2 个 slot → (None, None)"""
    slots = [{'slot': '10:00', 'F': 5680, 'ts': '2026-07-01T10:00:00'}]
    now, old = _get_intraday_slot_pair(slots, hours=1)
    assert now is None
    assert old is None


def test_get_intraday_slot_pair_empty():
    """空 → (None, None)"""
    now, old = _get_intraday_slot_pair(None, hours=1)
    assert now is None
    assert old is None


# ============================================================
# Test 3: _build_intraday_change
# ============================================================
def test_build_intraday_change_normal():
    slot_old = {'slot': '10:00', 'F': 5680, 'max_pain': 5800, 'net_gex': -5e6,
                'gex_flip': 5664, 'slope_ratio': 0.6, 'slope_regime': '略不对称'}
    slot_new = {'slot': '11:00', 'F': 5600, 'max_pain': 5800, 'net_gex': -8e6,
                'gex_flip': 5662, 'slope_ratio': 0.57, 'slope_regime': '略不对称'}
    r = _build_intraday_change(slot_old, slot_new, layer='L1')
    assert r['F_change'] == -80
    assert r['net_gex_change'] == -3e6
    assert r['gex_flip_change'] == -2
    assert r['slope_ratio_change'] == -0.03
    assert r['slope_regime_change'] is False
    assert r['layer'] == 'L1'


def test_build_intraday_change_regime_change():
    """regime 变化 → slope_regime_change=True"""
    slot_old = {'slot': '10:00', 'F': 5680, 'slope_ratio': 1.0, 'slope_regime': '略不对称'}
    slot_new = {'slot': '11:00', 'F': 5600, 'slope_ratio': 1.6, 'slope_regime': '一边主导'}
    r = _build_intraday_change(slot_old, slot_new, layer='L2')
    assert r['slope_regime_change'] is True


def test_build_intraday_change_none():
    """任一为 None → None"""
    assert _build_intraday_change(None, {'slot': '11:00'}) is None
    assert _build_intraday_change({'slot': '10:00'}, None) is None


# ============================================================
# Test 4: _build_daily_change
# ============================================================
def test_build_daily_change_normal():
    prev = {'max_pain': 5800, 'gex_flip': 5664, 'net_gex': -5.7e6, 'slope_ratio': 0.6, 'slope_regime': '略不对称'}
    cur  = {'max_pain': 5800, 'gex_flip': 5662, 'net_gex': -35.5e6, 'slope_ratio': 0.56, 'slope_regime': '略不对称'}
    r = _build_daily_change(prev, cur, layer='L1')
    assert r['max_pain_migration'] == 0
    assert r['gex_flip_migration'] == -2
    assert r['net_gex_change'] == -29.8e6
    assert r['net_gex_change_pct'] < -500  # -522%
    assert r['slope_regime_change'] is False
    assert r['layer'] == 'L1'


def test_build_daily_change_mp_migration():
    """MP 迁移"""
    prev = {'max_pain': 5800, 'gex_flip': 5664, 'net_gex': 0, 'slope_ratio': 0, 'slope_regime': ''}
    cur  = {'max_pain': 5850, 'gex_flip': 5664, 'net_gex': 0, 'slope_ratio': 0, 'slope_regime': ''}
    r = _build_daily_change(prev, cur, layer='L1')
    assert r['max_pain_migration'] == 50


def test_build_daily_change_empty():
    assert _build_daily_change(None, {'max_pain': 5800}) is None
    assert _build_daily_change({'max_pain': 5800}, None) is None


# ============================================================
# Test 5: L1 judge_layer1_pain_structure
# ============================================================
def test_layer1_with_slope_prev():
    """L1: 有 4 斜率 prev 字段 + 1h + daily 变化"""
    gex = {
        'summary': {'max_pain': 5800, 'futures_price': 5594, 'gex_flip': 5662,
                    'gex_direction': 'negative', 'net_gex': -35.5e6},
        'prev_summary': {'slope_down': 252000, 'slope_up': 422000, 'slope_ratio': 0.6,
                         'slope_regime': '略不对称', 'max_pain': 5800, 'gex_flip': 5664,
                         'net_gex': -5.7e6},
        # pain_curve 设计：左陡右缓，MP=5800
        # 左侧 5300-5750（5档）斜率陡：pain 200→300→400→500→600→800（5档区间 pain 涨 600）
        # 右侧 5850-6300（5档）斜率缓：pain 320→360→400→440→480→520（5档区间 pain 涨 200）
        'pain_curve': [
            {'strike': 5300, 'pain': 200}, {'strike': 5400, 'pain': 300},
            {'strike': 5500, 'pain': 400}, {'strike': 5600, 'pain': 500},
            {'strike': 5700, 'pain': 600}, {'strike': 5750, 'pain': 800},
            {'strike': 5800, 'pain': 100},   # ← MP
            {'strike': 5850, 'pain': 120}, {'strike': 5900, 'pain': 160},
            {'strike': 6000, 'pain': 200}, {'strike': 6100, 'pain': 240},
            {'strike': 6200, 'pain': 280}, {'strike': 6300, 'pain': 320},
        ],
    }
    intraday_slots = [
        {'slot': '10:00', 'F': 5680, 'max_pain': 5800, 'net_gex': -5e6,
         'gex_flip': 5664, 'slope_ratio': 0.6, 'slope_regime': '略不对称',
         'ts': '2026-07-01T10:00:00'},
        {'slot': '11:00', 'F': 5600, 'max_pain': 5800, 'net_gex': -8e6,
         'gex_flip': 5662, 'slope_ratio': 0.57, 'slope_regime': '略不对称',
         'ts': '2026-07-01T11:00:00'},
    ]
    r = judge_layer1_pain_structure(gex, {}, intraday_slots=intraday_slots)
    # 左陡: slope_down 应该是大值
    assert r['slope_down_now'] > 0, f"左斜率应为正，实际 {r['slope_down_now']}"
    assert r['slope_up_now'] > 0, f"右斜率应为正，实际 {r['slope_up_now']}"
    assert r['slope_ratio_prev'] == 0.6
    assert r['slope_regime_prev'] == '略不对称'
    assert r['intraday_change'] is not None
    assert r['intraday_change']['F_change'] == -80
    assert r['daily_change'] is not None
    assert r['daily_change']['max_pain_migration'] == 0
    assert r['summary'] is not None
    assert r['prev_summary'] is not None


def test_layer1_no_slope_data():
    """L1: 无 pain_curve / prev_summary → 兜底"""
    gex = {'summary': {'max_pain': 5800, 'futures_price': 5594, 'gex_flip': 5662,
                        'net_gex': -35.5e6}, 'prev_summary': {}}
    r = judge_layer1_pain_structure(gex, {})
    assert r['layer_score'] is not None
    assert r['intraday_change'] is None
    # prev_summary 为空时 daily_change 应为 None（无基准可比）
    assert r['daily_change'] is None


def test_layer1_with_prev_summary_only():
    """L1: 有 prev_summary 但无 pain_curve → daily_change 有（max_pain/gex_flip/net_gex 维度）"""
    gex = {
        'summary': {'max_pain': 5800, 'futures_price': 5594, 'gex_flip': 5662, 'net_gex': -35.5e6},
        'prev_summary': {'max_pain': 5800, 'gex_flip': 5664, 'net_gex': -5.7e6,
                          'slope_down': 0, 'slope_up': 0, 'slope_ratio': 0, 'slope_regime': ''},
    }
    r = judge_layer1_pain_structure(gex, {})
    assert r['daily_change'] is not None
    assert r['daily_change']['max_pain_migration'] == 0
    assert r['daily_change']['gex_flip_migration'] == -2


# ============================================================
# Test 6: L2 judge_layer2_gex
# ============================================================
def test_layer2_with_net_gex_change():
    """L2: net_gex 变化业务解读"""
    layer1 = {
        'gex_dir': 'negative', 'p_vs_flip': 'below',
        'summary': {'net_gex': -35.5e6, 'gex_flip': 5662, 'max_pain': 5800},
        'prev_summary': {'net_gex': -5.7e6, 'gex_flip': 5664, 'max_pain': 5800},
    }
    r = judge_layer2_gex(layer1)
    assert r['net_gex_now'] == -35.5e6
    assert r['net_gex_prev'] == -5.7e6
    assert r['net_gex_change'] == -29.8e6
    assert r['gex_flip_migration'] == -2
    assert '净GEX 恶化' in r['score_detail']


def test_layer2_with_intraday_slots():
    """L2: intraday_change 字段"""
    layer1 = {
        'gex_dir': 'negative', 'p_vs_flip': 'below',
        'summary': {'net_gex': -35.5e6, 'gex_flip': 5662, 'max_pain': 5800},
        'prev_summary': {'net_gex': -5.7e6, 'gex_flip': 5664, 'max_pain': 5800},
    }
    intraday_slots = [
        {'slot': '10:00', 'F': 5680, 'max_pain': 5800, 'net_gex': -5e6,
         'gex_flip': 5664, 'slope_ratio': 0.6, 'slope_regime': '略不对称',
         'ts': '2026-07-01T10:00:00'},
        {'slot': '11:00', 'F': 5600, 'max_pain': 5800, 'net_gex': -8e6,
         'gex_flip': 5662, 'slope_ratio': 0.57, 'slope_regime': '略不对称',
         'ts': '2026-07-01T11:00:00'},
    ]
    r = judge_layer2_gex(layer1, intraday_slots=intraday_slots)
    assert r['intraday_change'] is not None
    assert r['intraday_change']['F_change'] == -80


# ============================================================
# Test 7: L3 B 方案
# ============================================================
def test_layer3_b_plan():
    """L3: detail_section_ref 标记 + 1h PCR delta"""
    alert_data = {
        'rows': [
            {'strike': 5500, 'oi_call': 1000, 'oi_put': 800, 'iv_call': 0.25, 'iv_put': 0.26,
             'oi_call_prev': 1000, 'oi_put_prev': 800, 'iv_call_prev': 0.25, 'iv_put_prev': 0.26,
             'vol_call': 100, 'vol_put': 80, 'vol_call_prev': 100, 'vol_put_prev': 80},
        ]
    }
    gex = {
        'summary': {'futures_price': 5600, 'max_pain': 5800},
        'prev_summary': {},
    }
    r = judge_layer3_funding_intent(alert_data, gex, layer1={})
    assert r['detail_section_ref'] == 'section_3'
    assert 'pcr_delta_1h' in r


# ============================================================
# Test 8: L4 trend_1h
# ============================================================
def test_layer4_trend_1h():
    """L4: trend_1h 字段"""
    curve = {'futures_price': 5600, 'atm_strike': 5600, 'curve': []}
    alert_data = {'rows': []}
    gex = {
        'summary': {},
        'prev_summary': {'futures_price': 5688},
    }
    intraday_slots = [
        {'slot': '10:00', 'F': 5680, 'ts': '2026-07-01T10:00:00'},
        {'slot': '11:00', 'F': 5600, 'ts': '2026-07-01T11:00:00'},
    ]
    r = judge_layer4_emotion(curve, alert_data, layer1={'futures_price': 5600}, gex=gex,
                              intraday_slots=intraday_slots)
    assert r['trend_1h'] == 'down'  # 5680 → 5600 = -80
    assert r['F_1h_ago'] == 5680
    assert r['trend_diff_1h'] == -80


# ============================================================
# Test 9: synthesize_decision 5 分支
# ============================================================
def test_synthesize_decision_buy():
    """买入：total >= 0.5, contradiction=False"""
    layers = [
        {'layer': 1, 'layer_name': 'PAIN', 'weight': 0.35, 'layer_score': 0.6, 'logic_brief': 'X'},
        {'layer': 2, 'layer_name': 'GEX',  'weight': 0.25, 'layer_score': 0.5, 'logic_brief': 'X'},
        {'layer': 3, 'layer_name': 'L3',   'weight': 0.25, 'layer_score': 0.5, 'logic_brief': 'X'},
        {'layer': 4, 'layer_name': 'L4',   'weight': 0.15, 'layer_score': 0.3, 'logic_brief': 'X'},
    ]
    r = synthesize_decision(layers)
    assert r['decision'] == '买入'
    assert r['confidence'] == '高'
    assert r['contradiction'] is False


def test_synthesize_decision_contradiction():
    """观望（四层矛盾）"""
    layers = [
        {'layer': 1, 'layer_name': 'PAIN', 'weight': 0.35, 'layer_score':  0.1, 'logic_brief': 'X'},
        {'layer': 2, 'layer_name': 'GEX',  'weight': 0.25, 'layer_score': -0.6, 'logic_brief': 'X'},
        {'layer': 3, 'layer_name': 'L3',   'weight': 0.25, 'layer_score':  0.3, 'logic_brief': 'X'},
        {'layer': 4, 'layer_name': 'L4',   'weight': 0.15, 'layer_score': -0.1, 'logic_brief': 'X'},
    ]
    r = synthesize_decision(layers)
    assert r['decision'] == '观望（四层矛盾）'
    assert r['confidence'] == '低'
    assert r['contradiction'] is True


def test_synthesize_decision_short():
    """强空：所有层都 -0.6 → total = -0.6 → 观望或做空"""
    layers = [
        {'layer': 1, 'layer_name': 'PAIN', 'weight': 0.35, 'layer_score': -0.6, 'logic_brief': 'X'},
        {'layer': 2, 'layer_name': 'GEX',  'weight': 0.25, 'layer_score': -0.6, 'logic_brief': 'X'},
        {'layer': 3, 'layer_name': 'L3',   'weight': 0.25, 'layer_score': -0.6, 'logic_brief': 'X'},
        {'layer': 4, 'layer_name': 'L4',   'weight': 0.15, 'layer_score': -0.6, 'logic_brief': 'X'},
    ]
    r = synthesize_decision(layers)
    assert r['decision'] == '观望或做空'
    assert r['confidence'] == '高'


def test_synthesize_decision_mid_short():
    """中等空：total 在 (-0.5, -0.2] → 观望（中置信）"""
    layers = [
        {'layer': 1, 'layer_name': 'PAIN', 'weight': 0.35, 'layer_score': -0.3, 'logic_brief': 'X'},
        {'layer': 2, 'layer_name': 'GEX',  'weight': 0.25, 'layer_score': -0.6, 'logic_brief': 'X'},
        {'layer': 3, 'layer_name': 'L3',   'weight': 0.25, 'layer_score': -0.5, 'logic_brief': 'X'},
        {'layer': 4, 'layer_name': 'L4',   'weight': 0.15, 'layer_score': -0.3, 'logic_brief': 'X'},
    ]
    r = synthesize_decision(layers)
    assert r['decision'] == '观望'
    assert r['confidence'] == '中'


def test_synthesize_decision_weak_wait():
    """弱信号观望：total 在 (-0.2, +0.2), no contradiction"""
    layers = [
        {'layer': 1, 'layer_name': 'PAIN', 'weight': 0.35, 'layer_score':  0.05, 'logic_brief': 'X'},
        {'layer': 2, 'layer_name': 'GEX',  'weight': 0.25, 'layer_score':  0.0,  'logic_brief': 'X'},
        {'layer': 3, 'layer_name': 'L3',   'weight': 0.25, 'layer_score':  0.05, 'logic_brief': 'X'},
        {'layer': 4, 'layer_name': 'L4',   'weight': 0.15, 'layer_score':  0.0,  'logic_brief': 'X'},
    ]
    r = synthesize_decision(layers)
    assert r['decision'] == '观望'


# ============================================================
# v2.11.84 双门槛工具函数单测(4 个)
# ============================================================

def test_strike_meets_threshold_pass():
    """OI≥1000 + IV≥5% 双门槛通过

    注意: alert_data 里 IV 字段是百分比整数(21.57 = 21.57%),不是 0.21 这种小数
    """
    assert _strike_meets_threshold(1200, 1500, 27.0, 25.0) is True    # 正常 IV
    assert _strike_meets_threshold(1000, 1000, 5.0, 5.0) is True     # 边界双门槛
    assert _strike_meets_threshold(1500, 1200, 35.0, 28.0) is True   # OI 涨,IV 也涨

def test_strike_meets_threshold_fail_oi():
    """OI 不达标(任一 OI < 1000)= 失败"""
    assert _strike_meets_threshold(900, 1500, 27.0, 25.0) is False   # oi_cur 不够
    assert _strike_meets_threshold(1500, 900, 27.0, 25.0) is False   # oi_prev 不够
    assert _strike_meets_threshold(0, 0, 50.0, 50.0) is False        # 全 0
    assert _strike_meets_threshold(None, None, 50.0, 50.0) is False  # None

def test_strike_meets_threshold_fail_iv():
    """IV 不达标(<5% 或 None)= 失败"""
    assert _strike_meets_threshold(1500, 1500, 4.9, 27.0) is False    # iv_cur < 5%
    assert _strike_meets_threshold(1500, 1500, 27.0, 4.9) is False    # iv_prev < 5%
    assert _strike_meets_threshold(1500, 1500, None, 27.0) is False    # iv_cur None
    assert _strike_meets_threshold(1500, 1500, 27.0, None) is False    # iv_prev None
    assert _strike_meets_threshold(1500, 1500, 0.0, 0.0) is False      # IV 全 0

def test_compute_strike_weight_practical():
    """综合权重公式 W = Impact × Contribution(飞书文档附录)

    Impact = e^(-0.08 × |K-F|): 平值=1.0, 距离 130 点 ≈ 0(指数衰减极快)
    Contribution = |ΔOI_i| / Σ|ΔOI_j|: 该 strike OI 变化占端总变化的比重

    实战值都在 [0.001, 0.05] 区间 — 用于"重/中/轻"分级(累计前 60%/90% 边界)
    """
    # 平值附近 strike vs 远 strike: 远 strike 权重应显著小于近 strike(至少 10x 差距)
    w_atm = _compute_strike_weight(5500, 5630, +1200, [+1200, +800, +2000, +500])
    w_far = _compute_strike_weight(8100, 5630, +100, [+1200, +800, +2000, +500])
    # 距离 130 vs 2470: 远 strike 权重应至少 < 平值的 1/10
    assert w_atm > w_far * 10, f"平值权重 {w_atm:.6f} 应 > 远距离权重 {w_far:.6f} * 10"
    # 全 0 变化: 应该返回 0(避免除零)
    w_zero = _compute_strike_weight(5500, 5630, 0, [0, 0, 0, 0])
    assert w_zero == 0.0
    # 距离越远权重越小(单调性)
    w_300 = _compute_strike_weight(5930, 5630, +100, [+100])
    w_500 = _compute_strike_weight(6130, 5630, +100, [+100])
    assert w_300 > w_500 > 0, f"距离 300 点权重应 > 500 点: {w_300} vs {w_500}"
    print(f'compute_strike_weight: atm={w_atm:.6f}, far={w_far:.6f}, weight衰减正确')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

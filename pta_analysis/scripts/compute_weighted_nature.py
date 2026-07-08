#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2.11.85a Strike 级别权重 + 性质分组聚合算法（飞书文档 §2.3.1 + 附录）

输入: T 表 strike_rows (来自 /api/options/chain, 含 call_oi_change/iv_change/prev_call_iv)
输出: strike_role[] + weighted_pct{} + final_label
       (对原有 _compute_nature_and_synthesis 输出无侵入, 独立函数)

保护: 函数任何异常被 try/except 捕获, 返回 None. iv_smile 页面不受影响.
"""
import math
import logging

logger = logging.getLogger(__name__)

# 飞书文档 §2.3.1 双门槛
MIN_OI = 1000
MIN_IV_PCT = 5.0
# 综合权重衰减系数 (飞书附录表数据对应 0.0008, 公式栏写的 0.08 与表数据不一致)
# F1 待拍板: 0.08 vs 0.0008 vs 纯 contribution
DECAY = 0.0008
# IV 阈值 (飞书 §全档判定 0.5pp)
IV_THRESH_PP = 0.5
# OI 阈值 (飞书 §全档判定 1%)
OI_THRESH_PCT = 1.0
# 主导阈值 (飞书 §规则 2)
PCT_STRONG = 60.0
PCT_MID = 40.0


def _moneyness(K, F, side):
    """虚实值 5 档 (飞书 §虚实值状态, F=5500 举例)
    ITM_deep: |K-F| >= F*0.10 (10%)
    ATM:      |K-F| < F*0.015 (1.5%)
    OTM_deep: |K-F| >= F*0.10
    其余 ITM_slight / OTM_slight
    """
    diff = K - F
    ad = abs(diff)
    if ad < F * 0.015:
        return 'ATM'
    if side == 'Call':
        if diff >= F * 0.10:
            return 'OTM_deep'
        if diff >= 0:
            return 'OTM_slight'
        if diff <= -F * 0.10:
            return 'ITM_deep'
        return 'ITM_slight'
    # Put
    if -diff >= F * 0.10:
        return 'OTM_deep'
    if -diff >= 0:
        return 'OTM_slight'
    if diff >= F * 0.10:
        return 'ITM_deep'
    return 'ITM_slight'


def _judge(oi_pct, iv_pp, mn):
    """飞书 §2.3.1 单合约性质判定"""
    if oi_pct is None or iv_pp is None:
        return 'static', 'ignore'
    oi_up = oi_pct >= OI_THRESH_PCT
    oi_dn = oi_pct <= -OI_THRESH_PCT
    oi_flat = not oi_up and not oi_dn
    iv_up = iv_pp >= IV_THRESH_PP
    iv_dn = iv_pp <= -IV_THRESH_PP
    iv_flat = not iv_up and not iv_dn

    # OI↑ IV↑
    if oi_up and iv_up:
        if mn == 'OTM_deep':
            return 'spec_buy_lotto', '轻'
        if mn in ('ATM', 'OTM_slight', 'ITM_slight'):
            return 'spec_buy_directional', '重'
        if mn == 'ITM_deep':
            return 'hedge_rolling', '轻'
    # OI↑ IV↓
    if oi_up and iv_dn:
        return 'hedge_sell', '重'
    # OI↑ IV—
    if oi_up and iv_flat:
        if mn in ('OTM_deep', 'ITM_deep'):
            return 'noise_open', '忽略'
        return 'hedge_buy', '中'
    # OI↓ IV↑
    if oi_dn and iv_up:
        if mn == 'OTM_deep':
            return 'noise_close', '忽略'
        return 'close_push', '中'
    # OI↓ IV↓
    if oi_dn and iv_dn:
        return 'double_exit', '中'
    # OI↓ IV—
    if oi_dn and iv_flat:
        return 'passive_close', '忽略'
    # OI— IV↑
    if oi_flat and iv_up:
        return 'quote_adjust', '忽略'
    # OI— IV↓
    if oi_flat and iv_dn:
        if mn == 'OTM_deep':
            return 'theta_decay', '忽略'
        return 'supply_overhang', '中'
    return 'static', '忽略'


def _compute_side(strike_rows, futures_price, side):
    """单端 (Call/Put) 达标 strike + 综合权重 + SCORE_性质

    v2.11.85e: 数据源统一为 /api/iv_smile/alert_data.rows
      alert_data 字段: oi_call / oi_call_prev / iv_call / iv_call_prev
      (Put 端: oi_put / oi_put_prev / iv_put / iv_put_prev)
      IV 变化用 iv_cur - iv_prev (alert_data 里 iv_call_chg 是 null)
      OI 绝对变化用 oi_cur - oi_prev (不依赖 oi_chg 百分比反推)
      alert_data 没有 OI 变化 % → 把 oi_pct 设为 oi_chg_abs/prev_oi*100 给 _judge 用
      兼容: 如果 r 里没有 oi_call 而有 call_oi → fallback 回原 chain schema
    """
    if not strike_rows or futures_price <= 0:
        return None
    lower = side.lower()
    # v2.11.85e: 检测数据源 schema — alert_data 用 oi_call/oi_put, chain 用 call_oi/put_oi
    if any(('oi_' + lower) in r for r in strike_rows[:3] if isinstance(r, dict)):
        oi_fld = 'oi_' + lower           # alert_data: oi_call / oi_put
        oi_prev_fld = 'oi_' + lower + '_prev'
        iv_fld = 'iv_' + lower           # alert_data: iv_call / iv_put
        iv_prev_fld = 'iv_' + lower + '_prev'
        schema = 'alert_data'
    else:
        oi_fld = lower + '_oi'           # chain: call_oi / put_oi
        oi_chg_fld = lower + '_oi_change'
        iv_fld = lower + '_iv'
        iv_chg_fld = lower + '_iv_change'
        schema = 'chain_legacy'

    rows = []
    for r in strike_rows:
        try:
            oi_cur = float(r.get(oi_fld) or 0)
            iv_cur = float(r.get(iv_fld) or 0)
            if oi_cur < MIN_OI or iv_cur < MIN_IV_PCT:
                continue
            s = int(r['strike'])

            if schema == 'alert_data':
                # v2.11.85e: alert_data 直接给 prev 值, 不再用 % 反推
                prev_oi = float(r.get(oi_prev_fld) or 0)
                oi_chg_abs = oi_cur - prev_oi
                # _judge 要 % 形式, alert_data 没 oi_chg % → 现算
                if prev_oi > 0:
                    oi_pct = (oi_chg_abs / prev_oi) * 100.0
                else:
                    oi_pct = -100.0 if oi_chg_abs < 0 else 0.0
                prev_iv = float(r.get(iv_prev_fld) or 0)
                iv_pp = iv_cur - prev_iv
            else:
                # 原 chain schema 兼容路径
                oi_pct = float(r.get(oi_chg_fld) or 0)  # T 表字段: %
                iv_pp = float(r.get(iv_chg_fld) or 0)   # T 表字段: pp
                if iv_pp is None:
                    continue
                if abs(oi_pct - (-100)) < 1e-9:
                    prev_oi = 0
                else:
                    prev_oi = oi_cur / (1.0 + oi_pct / 100.0)
                oi_chg_abs = oi_cur - prev_oi

            mn = _moneyness(s, futures_price, side)
            nat, w_sig = _judge(oi_pct, iv_pp, mn)
            rows.append({
                'strike': s, 'oi_cur': oi_cur, 'iv_cur': iv_cur,
                'oi_pct': oi_pct, 'iv_pp': iv_pp,
                'oi_chg_abs': oi_chg_abs,
                'moneyness': mn, 'nature': nat,
                'weight_signal': w_sig,
                '_schema': schema,
            })
        except Exception as e:
            logger.debug('[compute_weighted] skip row: %s', e)
            continue

    if not rows:
        return None

    # Impact 因子 (飞书 §附录, 0.0008)
    for r in rows:
        r['impact'] = math.exp(-DECAY * abs(r['strike'] - futures_price))

    # Contribution 因子
    denom = sum(abs(r['oi_chg_abs']) for r in rows)
    for r in rows:
        r['contribution'] = abs(r['oi_chg_abs']) / denom if denom > 0 else 0
        r['weight'] = r['impact'] * r['contribution']

    # SCORE_性质
    scores = {}
    for r in rows:
        scores.setdefault(r['nature'], 0.0)
        scores[r['nature']] += r['weight']

    return {
        'rows': rows,
        'scores': scores,
        'total_w': sum(scores.values()),
        'denom_abs_oi_chg': denom,
    }


def _to_dir(scores, side):
    """性质 → 方向 (飞书 §规则 4 方向映射)"""
    if not scores:
        return '中性'
    sorted_nats = sorted(scores.items(), key=lambda x: -x[1])
    main_nat = sorted_nats[0][0]
    if main_nat in ('spec_buy_directional', 'close_push'):
        return '看多' if side == 'Call' else '看空'
    if main_nat == 'spec_buy_lotto':
        return '偏多(弱)' if side == 'Call' else '偏空(弱)'
    if main_nat == 'hedge_sell':
        return '中性'
    if main_nat == 'hedge_buy':
        return '偏空(防御)' if side == 'Call' else '偏多(防御)'
    if main_nat == 'double_exit':
        return '中性'
    if main_nat == 'supply_overhang':
        return '中性'
    return '中性'


# ============================================================
# v2.11.85d: 持仓 PCR + Skew 交叉验证框架辅助函数
# 飞书文档 §2.3.2 附录"持仓PCR+SKEW交叉验证框架优化"
# ============================================================

# 资金活跃度等级（基于单方向总 OI 增量，单位：手）
FUND_ACTIVITY_THRESHOLDS = [
    ('极低', 0,      2000),    # < 2000 手
    ('低',   2000,   5000),    # 2000-5000 手
    ('中',   5000,   15000),   # 5000-15000 手
    ('高',   15000,  float('inf')),  # > 15000 手
]

# Skew 变化可靠性（基于 IV 变化绝对幅度，单位：pp）
IV_RELIABILITY_THRESHOLDS = [
    ('弱信号', 0,   0.5),
    ('中等',   0.5, 1.5),
    ('强信号', 1.5, float('inf')),
]


def _calc_fund_activity(strike_rows, side):
    """计算单方向（Call/Put）的资金活跃度等级

    输入: T 表 strike_rows + side ('Call'/'Put')
    输出: dict {
        'level': '极低'/'低'/'中'/'高',
        'abs_oi_chg': 总绝对变化量（手）,
        'avg_iv_pp':  加权平均 IV 变化（pp）,
    }

    计算方法: 达标 strike 的 |ΔOI_绝对量| 之和
       - OI 过滤: oi_call / oi_put >= MIN_OI (1000 手)  [v2.11.85e: alert_data schema]
       - IV 过滤: iv_call / iv_put >= MIN_IV_PCT (5%)
       - 只统计合格 strike 的变化量
    v2.11.85e: 数据源统一为 alert_data, OI 直接相减, IV 用 cur - prev
    """
    if not strike_rows:
        return {'level': '极低', 'abs_oi_chg': 0, 'avg_iv_pp': 0.0}

    lower = side.lower()
    if any(('oi_' + lower) in r for r in strike_rows[:3] if isinstance(r, dict)):
        oi_fld = 'oi_' + lower
        oi_prev_fld = 'oi_' + lower + '_prev'
        iv_fld = 'iv_' + lower
        iv_prev_fld = 'iv_' + lower + '_prev'
        schema = 'alert_data'
    else:
        oi_fld = lower + '_oi'
        iv_fld = lower + '_iv'
        oi_chg_fld = lower + '_oi_change'
        iv_chg_fld = lower + '_iv_change'
        schema = 'chain_legacy'

    abs_oi_sum = 0.0
    iv_pp_weighted_sum = 0.0
    weight_sum = 0.0

    for r in strike_rows:
        oi_cur = float(r.get(oi_fld) or 0)
        iv_cur = float(r.get(iv_fld) or 0)
        if oi_cur < MIN_OI or iv_cur < MIN_IV_PCT:
            continue

        if schema == 'alert_data':
            prev_oi = float(r.get(oi_prev_fld) or 0)
            oi_chg_abs = abs(oi_cur - prev_oi)
            prev_iv = float(r.get(iv_prev_fld) or 0)
            iv_pp = iv_cur - prev_iv
        else:
            oi_pct = float(r.get(oi_chg_fld) or 0)
            iv_pp = float(r.get(iv_chg_fld) or 0)
            if abs(oi_pct - (-100)) < 1e-9:
                prev_oi = 0
            else:
                prev_oi = oi_cur / (1.0 + oi_pct / 100.0)
            oi_chg_abs = abs(oi_cur - prev_oi)

        abs_oi_sum += oi_chg_abs

        # 用 |ΔOI| 加权平均 IV 变化（更重视大资金 strike 的 IV 变化）
        iv_pp_weighted_sum += abs(iv_pp) * oi_chg_abs
        weight_sum += oi_chg_abs

    avg_iv_pp = iv_pp_weighted_sum / weight_sum if weight_sum > 0 else 0.0

    level = '极低'
    for lv, lo, hi in FUND_ACTIVITY_THRESHOLDS:
        if lo <= abs_oi_sum < hi:
            level = lv
            break

    return {
        'level': level,
        'abs_oi_chg': round(abs_oi_sum, 1),
        'avg_iv_pp': round(avg_iv_pp, 3),
    }


def _classify_iv_reliability(iv_pp):
    """根据 IV 变化绝对幅度判定可靠性等级

    输入: iv_pp (绝对值)
    输出: '弱信号' / '中等' / '强信号'
    """
    abs_iv = abs(iv_pp) if iv_pp is not None else 0
    for lv, lo, hi in IV_RELIABILITY_THRESHOLDS:
        if lo <= abs_iv < hi:
            return lv
    return '弱信号'


# ============================================================
# v2.11.85d: PCR × Skew 交叉验证综合判定（飞书 §2.3.2 附录）
# 4 个子规则 + 6 档置信度等级
# ============================================================

# 综合置信度等级（输出字符串）
CV_LEVELS = ['强确认', '确认', '弱确认', '无修正', '忽略噪音']
CV_LEVEL_RANK = {lv: i for i, lv in enumerate(CV_LEVELS)}  # 越小越强
# 资金活跃度 → 排序值（越小越强）
FUND_RANK = {'高': 0, '中': 1, '低': 2, '极低': 3}
# IV 可靠性 → 排序值（越小越强）
IV_RANK = {'强信号': 0, '中等': 1, '弱信号': 2}


def _cv_min(a, b):
    """综合置信度：取较弱的那一档（保守）"""
    return a if CV_LEVEL_RANK[a] > CV_LEVEL_RANK[b] else b


def _cv_apply_rule_consistent(fund_level, iv_rel):
    """子规则 1：方向一致时，资金活跃度 × IV 变化幅度 → 综合置信度

    飞书附录 表"子规则 1" 8 行映射
    """
    f = FUND_RANK.get(fund_level, 3)
    i = IV_RANK.get(iv_rel, 2)

    if fund_level == '极低' or iv_rel == '弱信号':
        # 极低资金 或 弱信号 IV → 都降级
        if iv_rel == '弱信号' and fund_level == '极低':
            return '忽略噪音'
        return '弱确认（降级）' if fund_level != '极低' else '忽略噪音'

    # 高 / 中 / 低 资金 × 强 / 中 / 弱 IV
    # 映射表（高/中/低, 强/中/弱）
    table = {
        ('高', '强信号'): '强确认',     # 信号置信度极高，坚定执行
        ('高', '中等'):   '确认',         # 信号可靠，维持原始判定
        ('高', '弱信号'): '弱确认',       # 资金大量涌入但 IV 未明显变化（可能是卖权收租），方向参考，仓位减半
        ('中', '强信号'): '确认',
        ('中', '中等'):   '弱确认',
        ('中', '弱信号'): '弱确认（降级）',
        ('低', '强信号'): '弱确认（降级）',
        ('低', '中等'):   '弱确认（降级）',
        ('低', '弱信号'): '忽略噪音',
    }
    return table.get((fund_level, iv_rel), '无修正')


def _cv_apply_rule_contradictory(fund_level, iv_rel):
    """子规则 2：方向矛盾时，大资金方主导（非简单观望）

    飞书附录 表"子规则 2" 9 行映射
    """
    if fund_level == '极低' or iv_rel == '弱信号':
        if fund_level == '极低' and iv_rel == '弱信号':
            return '忽略噪音'
        return '无修正'

    table = {
        ('高', '强信号'): '强确认',         # 大资金方完全主导
        ('高', '中等'):   '确认',           # 大资金方明显占优
        ('高', '弱信号'): '弱确认',
        ('中', '强信号'): '弱确认',
        ('中', '中等'):   '弱确认（降级）',
        ('中', '弱信号'): '忽略噪音',
        ('低', '强信号'): '弱确认（降级）',
        ('低', '中等'):   '无修正',
        ('低', '弱信号'): '忽略噪音',
    }
    return table.get((fund_level, iv_rel), '无修正')


def _cv_apply_rule_pcr_flat(skew_dir, iv_rel):
    """子规则 3：PCR 平稳 + Skew 变化 → IV 变化可能是噪音

    飞书附录 表"子规则 3" 3 行映射
    """
    if iv_rel == '强信号':
        return '弱确认'         # IV 变化大但 PCR 无验证，可能是做市商报价调整或 Theta decay
    elif iv_rel == '中等':
        return '无修正'         # IV 变化未达"显著"，不纳入交叉验证
    else:
        return '忽略噪音'


def cross_validate_funding(cv_inputs):
    """主入口：综合判定函数

    输入: cv_inputs = _build_cross_validation_inputs 的输出
    输出: dict {
        'call': {'verdict': '强确认/...', 'rationale': '...', 'subrule': 1/2/3/4},
        'put':  { 同上 },
        'consistency': 'consistent' / 'contradictory' / 'pcr_flat',
        'pcr_direction': 'up/down/flat',
        'skew_direction': 'deepen/flatten/flat',
    }
    """
    if not cv_inputs or not cv_inputs.get('available'):
        return {
            'call': {'verdict': '无修正', 'rationale': 'cross_validation 不可用', 'subrule': 4},
            'put':  {'verdict': '无修正', 'rationale': 'cross_validation 不可用', 'subrule': 4},
            'consistency': 'unavailable',
        }

    pcr_dir = cv_inputs['pcr']['direction']
    skew_dir = cv_inputs['skew']['direction']
    fund_call = cv_inputs['fund_activity']['Call']['level']
    fund_put  = cv_inputs['fund_activity']['Put']['level']
    iv_call = cv_inputs['iv_reliability']['Call']
    iv_put  = cv_inputs['iv_reliability']['Put']

    # 一致性判定：PCR↑ + Skew加深 都看空 / PCR↓ + Skew减轻 都看多 → 一致
    # 业务映射：
    #   PCR↑ → 看空方向（Put 资金涌入）
    #   Skew加深 → 看空方向（Put 端溢价上升）
    #   PCR↓ → 看多方向
    #   Skew减轻 → 看多方向
    if pcr_dir == 'flat' or skew_dir == 'flat':
        consistency = 'pcr_flat'  # 子规则 3 / 4 适用
    elif (pcr_dir == 'up' and skew_dir == 'deepen') or (pcr_dir == 'down' and skew_dir == 'flatten'):
        consistency = 'consistent'  # 同向
    else:
        consistency = 'contradictory'  # 反向

    result = {
        'call': {},
        'put': {},
        'consistency': consistency,
        'pcr_direction': pcr_dir,
        'skew_direction': skew_dir,
    }

    for side, fund_lv, iv_rel in [('call', fund_call, iv_call), ('put', fund_put, iv_put)]:
        if consistency == 'consistent':
            verdict = _cv_apply_rule_consistent(fund_lv, iv_rel)
            subrule = 1
            rationale = f'子规则1（方向一致）: 资金[{fund_lv}] × IV[{iv_rel}]'
        elif consistency == 'contradictory':
            verdict = _cv_apply_rule_contradictory(fund_lv, iv_rel)
            subrule = 2
            rationale = f'子规则2（方向矛盾大资金方主导）: 资金[{fund_lv}] × IV[{iv_rel}]'
        else:  # pcr_flat
            if iv_rel == '强信号':
                verdict = _cv_apply_rule_pcr_flat(skew_dir, iv_rel)
                subrule = 3
                rationale = f'子规则3（PCR平稳+Skew变化）: Skew[{skew_dir}] + IV[{iv_rel}]'
            else:
                verdict = '无修正'
                subrule = 4
                rationale = f'子规则4（无法判定）: PCR平稳 + IV变化<0.5pp'

        result[side] = {
            'verdict': verdict,
            'rationale': rationale,
            'subrule': subrule,
        }

    return result


def compute_weighted_nature(strike_rows, futures_price):
    """主入口: 输入 T 表 strike_rows + F, 输出 strike_role + weighted_pct

    Returns:
        dict 或 None (输入异常时返回 None, 调用方走 fallback).
        {
          'Call': {'strike_role': [...], 'weighted_pct': {...}, 'label': '...', 'main_nat': '...', 'main_pct': ...},
          'Put':  {...same...},
          'data_quality': {'threshold_version': 'v2.11.85a', 'oi_threshold': 1000, ...},
          'generated_at': ISO timestamp,
        }
    """
    if not strike_rows or not futures_price or float(futures_price) <= 0:
        return None
    try:
        F = float(futures_price)
        result = {'generated_at': __import__('datetime').datetime.now().isoformat(timespec='seconds'),
                  'data_quality': {
                      'threshold_version': 'v2.11.85a',
                      'oi_threshold': MIN_OI,
                      'iv_threshold_pct': MIN_IV_PCT,
                      'iv_threshold_pp': IV_THRESH_PP,
                      'decay_constant': DECAY,
                  }}

        for side in ('Call', 'Put'):
            side_d = _compute_side(strike_rows, F, side)
            if not side_d:
                result[side] = {'strike_role': [], 'weighted_pct': {}, 'label': '无达标 strike', 'main_nat': None, 'main_pct': 0}
                continue
            rows = side_d['rows']
            scores = side_d['scores']
            total_w = side_d['total_w']

            sorted_scores = sorted(scores.items(), key=lambda x: -x[1])
            main_nat = sorted_scores[0][0]
            main_pct = sorted_scores[0][1] / total_w * 100 if total_w > 0 else 0
            second_max = sorted_scores[1][1] / total_w * 100 if len(sorted_scores) > 1 and total_w > 0 else 0

            # final label (飞书 §规则 1-4)
            if main_pct > PCT_STRONG:
                verdict = f'★强信号★: {main_nat} {main_pct:.1f}% > 60%'
                label = f'{main_nat}_strong'
            elif main_pct > PCT_MID:
                verdict = f'中强度主导: {main_nat} {main_pct:.1f}% 40-60%'
                label = f'{main_nat}_mid'
            elif all(s / total_w < 0.30 for _, s in sorted_scores):
                verdict = f'无主导力量 (最大 < 30%)'
                label = 'mixed_neutral'
            else:
                # 进入规则 3: 混合中性区分
                verdict = f'混合中性 (最大 {main_pct:.1f}% < 40%, 第二 {second_max:.1f}% > 25%)'
                label = 'mixed_neutral'

            # strike_role 输出 (按 weight 降序)
            strike_role = []
            for r in sorted(rows, key=lambda x: -x['weight']):
                strike_role.append({
                    'strike': r['strike'],
                    'side': side,
                    'nature': r['nature'],
                    'moneyness': r['moneyness'],
                    'oi_pct': round(r['oi_pct'], 2),
                    'iv_pp': round(r['iv_pp'], 2),
                    'oi_chg': round(r['oi_chg_abs'], 1),
                    'impact': round(r['impact'], 4),
                    'contribution': round(r['contribution'], 4),
                    'weight': round(r['weight'], 4),
                })

            # weighted_pct = {nature: pct%}
            weighted_pct = {n: round(s / total_w * 100, 2) for n, s in scores.items()} if total_w > 0 else {}

            result[side] = {
                'strike_role': strike_role,
                'weighted_pct': weighted_pct,
                'label': label,
                'verdict': verdict,
                'main_nat': main_nat,
                'main_pct': round(main_pct, 2),
                'direction': _to_dir(scores, side),
            }

        return result
    except Exception as e:
        logger.warning('[compute_weighted_nature] 异常, 返回 None: %s', e)
        return None


# 自检
if __name__ == '__main__':
    import json
    import urllib.request

    cur = json.loads(urllib.request.urlopen(
        'http://127.0.0.1:8424/api/options/chain?main_only=true', timeout=10
    ).read())
    sr = cur.get('strike_rows') or []
    F = float(cur.get('underlying_price') or 0)
    result = compute_weighted_nature(sr, F)
    if not result:
        print('FAIL: 返回 None')
    else:
        import json as _json
        print(_json.dumps(result, ensure_ascii=False, indent=2)[:3500])

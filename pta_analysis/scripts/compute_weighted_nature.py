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
import os
from typing import Any, Dict, Tuple

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

# ============================================================
# v2.11.85f: 子规则 2b 新资金方向分层 —— NAT_DIR + nature 分类
# 飞书 §2.3.1 单合约性质判定，方向词按 NAT_MAP（Call/Put 端方向相反）
# close_push 方向说明:
#   OI↓ IV↑ → 平仓者预期反向 → Call close_push = 平 Call 多头 → 预期标的不涨/微跌
#   NAT_MAP 给: Call close_push → '看多' (反向逻辑) / Put close_push → '看空'
# ============================================================
NAT_DIR_CALL = {
    'spec_buy_directional': '看多', 'spec_buy_lotto': '偏多',
    'hedge_buy': '偏空',           # Call 端产业买 Call = 锁定卖出价 → 看空标的
    'close_push': '看多',          # Call 端 close_push = 平 Call 多头 → 反向看多
    'hedge_sell': '中性', 'double_exit': '中性', 'supply_overhang': '中性',
    'mixed_neutral': '中性', 'passive_close': '中性', 'noise_close': '中性',
    'noise_open': '中性', 'theta_decay': '中性', 'quote_adjust': '中性',
    'static': '中性', 'hedge_rolling': '中性',
}
NAT_DIR_PUT = {
    'spec_buy_directional': '看空', 'spec_buy_lotto': '偏空',
    'hedge_buy': '偏多',           # Put 端产业买 Put = 锁定买入价/套保 → 看多标的
    'close_push': '看空',          # Put 端 close_push = 平 Put 空头 → 反向看空
    'hedge_sell': '中性', 'double_exit': '中性', 'supply_overhang': '中性',
    'mixed_neutral': '中性', 'passive_close': '中性', 'noise_close': '中性',
    'noise_open': '中性', 'theta_decay': '中性', 'quote_adjust': '中性',
    'static': '中性', 'hedge_rolling': '中性',
}

# nature 分类（按 OI 净变化是否代表新增方向性观点）
NEW_FUND_NATURES = {'spec_buy_directional', 'spec_buy_lotto', 'hedge_buy'}
# hedge_sell = 卖权收租（新开仓但中性，归中性新开仓）
NEUTRAL_NEW_NATURES = {'hedge_sell'}
# 存量调整（OI↓ 但 close_push 仍带方向，double_exit 是中性撤退）
STOCK_ADJ_NATURES = {'close_push', 'double_exit'}
# v2.11.85h: passive_close 是被动平仓（OI↓ IV—），无方向性, 不算存量调整也不算噪音
PASSIVE_NATURES = {'passive_close'}
# 噪音（不计入方向判定, 不计入 dominant_nature）
NOISE_NATURES = {'noise_open', 'noise_close', 'quote_adjust',
                 'theta_decay', 'supply_overhang', 'static', 'hedge_rolling'}

# 新资金 vs 存量 主导阈值（飞书 §2.3.2 子规则 2b 拍板）
NEW_FUND_DOMINANCE_RATIO = 1.5  # |新资金| > |存量| × 1.5 → 新资金主导


def _calc_fund_flow_split(strike_role_list, side):
    """v2.11.85f: 按 strike_role 计算该端的新资金 vs 存量调整拆分（按 NAT_DIR 方向加权）

    输入: strike_role_list = weighted[side]['strike_role']
          side = 'Call' / 'Put'
    输出: {
        'new_fund_net_long': int,      # 新资金 NAT_DIR='看多'/'偏多' 的 OI 净
        'new_fund_net_short': int,     # 新资金 NAT_DIR='看空'/'偏空' 的 OI 净
        'new_fund_net_neutral': int,   # 新资金中性 (hedge_sell) 的 OI 净
        'stock_adj_net_long': int,     # 存量 NAT_DIR='看多'/'偏多' 的 OI 净
        'stock_adj_net_short': int,    # 存量 NAT_DIR='看空'/'偏空' 的 OI 净
        'oi_total_chg': int,           # 净 OI 变化（用于对照）
        'dominant_nature': str,        # abs(oi_chg) 最大的 nature（含噪音）
        'new_fund_dominant_nature': str,  # 新资金中 abs(oi_chg) 最大的 nature
    }
    """
    nat_dir_map = NAT_DIR_CALL if side == 'Call' else NAT_DIR_PUT

    new_long = new_short = new_neutral = 0
    stock_long = stock_short = 0
    oi_total = 0.0
    nature_oi = {}            # nature → abs(oi_chg) 累计（找 dominant_nature 用, 仅 fallback）
    nature_weight = {}        # nature → weight (impact × contribution) 累计（业务口径, 优先用）
    new_fund_nature_weight = {}  # 仅新资金 nature → weight 加权

    for s in (strike_role_list or []):
        nat = s.get('nature')
        # ⚠️ 前置 A 已确认: strike_role 里 OI 绝对变化字段 = 'oi_chg'
        try:
            oi_chg = float(s.get('oi_chg') or 0)
        except (TypeError, ValueError):
            continue
        try:
            weight_v = float(s.get('weight') or 0)
        except (TypeError, ValueError):
            weight_v = 0.0

        oi_total += oi_chg
        # v2.11.85h 修订: dominant_nature 用 weight (impact × contribution) 加权
        #          业务口径与 _compute_side L333 scores 一致 (那里累加的是 r['weight'])
        #          排除噪音和被动平仓
        if nat not in NOISE_NATURES and nat not in PASSIVE_NATURES:
            nature_oi[nat] = nature_oi.get(nat, 0) + abs(oi_chg)
            nature_weight[nat] = nature_weight.get(nat, 0) + abs(weight_v)
        direction = nat_dir_map.get(nat, '中性')

        if nat in NEW_FUND_NATURES:
            if direction in ('看多', '偏多'):
                new_long += oi_chg
            elif direction in ('看空', '偏空'):
                new_short += oi_chg
            else:
                new_neutral += oi_chg
            new_fund_nature_weight[nat] = new_fund_nature_weight.get(nat, 0) + abs(weight_v)
        elif nat in NEUTRAL_NEW_NATURES:
            new_neutral += oi_chg
            new_fund_nature_weight[nat] = new_fund_nature_weight.get(nat, 0) + abs(weight_v)
        elif nat in STOCK_ADJ_NATURES:
            if direction in ('看多', '偏多'):
                stock_long += oi_chg
            elif direction in ('看空', '偏空'):
                stock_short += oi_chg
            # stock 中性不计入 stock_long/short
        elif nat in PASSIVE_NATURES:
            pass  # 被动平仓无方向, 不计入 stock/long/short, 不计入 nature_weight
        # NOISE_NATURES 不计入 (包括 nature_weight)

    # v2.11.85h: dominant_nature 按 weight (impact × contribution) 加权排序
    #          业务口径与 _compute_side L333 scores 一致
    #          fallback 到 abs(oi_chg) (仅在 weight 全为 0 时)
    if nature_weight and any(v > 0 for v in nature_weight.values()):
        dominant_nature = max(nature_weight, key=nature_weight.get)
    else:
        dominant_nature = max(nature_oi, key=nature_oi.get) if nature_oi else 'unknown'
    # new_fund_dominant 也用 weight 加权
    if new_fund_nature_weight and any(v > 0 for v in new_fund_nature_weight.values()):
        new_fund_dominant = max(new_fund_nature_weight, key=new_fund_nature_weight.get)
    elif new_fund_nature_oi:
        new_fund_dominant = max(new_fund_nature_oi, key=new_fund_nature_oi.get)
    else:
        new_fund_dominant = 'unknown'

    return {
        'new_fund_net_long': round(new_long),
        'new_fund_net_short': round(new_short),
        'new_fund_net_neutral': round(new_neutral),
        'stock_adj_net_long': round(stock_long),
        'stock_adj_net_short': round(stock_short),
        'oi_total_chg': round(oi_total),
        'dominant_nature': dominant_nature,
        'new_fund_dominant_nature': new_fund_dominant,
    }
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

    v2.11.85f: 子规则 2（矛盾场景）追加新资金方向分层
      - 新资金 vs 存量调整 NAT_DIR 方向加权（不是单纯 OI 符号）
      - 仅当新资金主导（|新| > |存量| × 1.5）时给 verdict_direction
      - 存量主导时 verdict_direction=None（让原 9 行表结论主导）
      - 综合两端 new_fund_direction (看空/看多/多空博弈/None)

    输入: cv_inputs = _build_cross_validation_inputs 的输出
    输出: dict {
        'call': {'verdict': ..., 'rationale': ..., 'subrule': 1/2/3/4,
                 'verdict_direction': 看空/看多/None (v2.11.85f 新增),
                 'fund_flow_verdict': 新资金主导/存量调整主导/资金僵持 (v2.11.85f 新增),
                 'new_fund_net_long/short/neutral': int,
                 'stock_adj_net_long/short': int,
                 'new_fund_dominant_nature': str,
                 'dominant_nature': str},
        'put':  { 同上 },
        'consistency': 'consistent' / 'contradictory' / 'pcr_flat',
        'pcr_direction': 'up/down/flat',
        'skew_direction': 'deepen/flatten/flat',
        'new_fund_direction': 看空/看多/多空博弈/None (v2.11.85f 新增, 仅 contradictory 时计算),
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

    # v2.11.85f: 子规则 2b 仅在 contradictory 时启用判定
    # 但 v2.11.85h 修订: consistent 场景也透传 fund_flow 字段供前端展示
    fund_flow = cv_inputs.get('fund_flow', {}) or {}

    for side, fund_lv, iv_rel in [('call', fund_call, iv_call), ('put', fund_put, iv_put)]:
        if consistency == 'consistent':
            verdict = _cv_apply_rule_consistent(fund_lv, iv_rel)
            subrule = 1
            rationale = f'子规则1（方向一致）: 资金[{fund_lv}] × IV[{iv_rel}]'
        elif consistency == 'contradictory':
            verdict = _cv_apply_rule_contradictory(fund_lv, iv_rel)
            subrule = 2
            rationale = f'子规则2（方向矛盾大资金方主导）: 资金[{fund_lv}] × IV[{iv_rel}]'

            # ============================================================
            # v2.11.85f: 子规则 2b 新资金方向分层
            # 仅当本端 fund_flow 数据存在时计算
            # ============================================================
            ff = fund_flow.get(side.capitalize(), {})
            new_long  = ff.get('new_fund_net_long', 0)
            new_short = ff.get('new_fund_net_short', 0)
            new_neutral = ff.get('new_fund_net_neutral', 0)
            stock_long = ff.get('stock_adj_net_long', 0)
            stock_short = ff.get('stock_adj_net_short', 0)
            new_dom = ff.get('new_fund_dominant_nature', 'unknown')
            dominant = ff.get('dominant_nature', 'unknown')

            abs_new = abs(new_long) + abs(new_short) + abs(new_neutral)
            abs_stock = abs(stock_long) + abs(stock_short)

            # 新资金 vs 存量 主导判定
            if abs_new > abs_stock * NEW_FUND_DOMINANCE_RATIO:
                flow_verdict = '新资金主导'
            elif abs_stock > abs_new * NEW_FUND_DOMINANCE_RATIO:
                flow_verdict = '存量调整主导'
            else:
                flow_verdict = '资金僵持'

            # 方向判定: 仅当新资金主导时给方向
            if flow_verdict == '新资金主导':
                if new_long > abs(new_short):
                    direction = '看多'
                elif abs(new_short) > new_long:
                    direction = '看空'
                else:
                    direction = None  # 新资金内部多空均衡
            else:
                direction = None  # 存量主导/僵持 → 不给方向,让 9 行表结论主导

            # v2.11.85h+ (A 拍板): rationale 删 `新主导[{new_dom}]` 段
            #   理由: strike 详情已列出每个 nature, rationale 重复展示"新资金最大项"冗余且易误读为方向主导
            #   资金流判定本身 (fund_flow_verdict) 已说清资金方向, 不再附新主导 nature
            #   改写 flow_verdict → "资金流:{verdict}(不参与方向)" 让"不参与方向"显式可读
            if flow_verdict == '新资金主导':
                flow_label = f'资金流:{flow_verdict}'
            else:
                flow_label = f'资金流:{flow_verdict}(不参与方向)'
            rationale += (
                f' | 新资金[L:{new_long:+.0f}/S:{new_short:+.0f}/N:{new_neutral:+.0f}] '
                f'存量[L:{stock_long:+.0f}/S:{stock_short:+.0f}] '
                f'{flow_label}'
            )

            result[side] = {
                'verdict': verdict,
                'rationale': rationale,
                'subrule': subrule,
                # v2.11.85f 新增字段
                'verdict_direction': direction,
                'fund_flow_verdict': flow_verdict,
                'new_fund_net_long': new_long,
                'new_fund_net_short': new_short,
                'new_fund_net_neutral': new_neutral,
                'stock_adj_net_long': stock_long,
                'stock_adj_net_short': stock_short,
                'new_fund_dominant_nature': new_dom,
                'dominant_nature': dominant,
            }
            continue  # 子规则 2 已在上面赋值 result[side], 跳过下面的 else 分支

        else:  # pcr_flat
            if iv_rel == '强信号':
                verdict = _cv_apply_rule_pcr_flat(skew_dir, iv_rel)
                subrule = 3
                rationale = f'子规则3（PCR平稳+Skew变化）: Skew[{skew_dir}] + IV[{iv_rel}]'
            else:
                verdict = '无修正'
                subrule = 4
                rationale = f'子规则4（无法判定）: PCR平稳 + IV变化<0.5pp'

        # 子规则 1/3/4 不变, 但 v2.11.85f 透传 fund_flow 字段供前端展示
        side_data = {
            'verdict': verdict,
            'rationale': rationale,
            'subrule': subrule,
        }
        # v2.11.85f: 即使非 contradictory, 也透传 fund_flow 字段（如果有）
        if fund_flow:
            ff = fund_flow.get(side.capitalize(), {})
            new_long_v  = ff.get('new_fund_net_long', 0)
            new_short_v = ff.get('new_fund_net_short', 0)
            new_neutral_v = ff.get('new_fund_net_neutral', 0)
            stock_long_v = ff.get('stock_adj_net_long', 0)
            stock_short_v = ff.get('stock_adj_net_short', 0)
            abs_new_v = abs(new_long_v) + abs(new_short_v) + abs(new_neutral_v)
            abs_stock_v = abs(stock_long_v) + abs(stock_short_v)
            # v2.11.85h: consistent 也给 verdict_direction（按新资金主导判定）
            if abs_new_v > abs_stock_v * NEW_FUND_DOMINANCE_RATIO:
                flow_verdict_v = '新资金主导'
                if new_long_v > abs(new_short_v):
                    direction_v = '看多'
                elif abs(new_short_v) > new_long_v:
                    direction_v = '看空'
                else:
                    direction_v = None
            elif abs_stock_v > abs_new_v * NEW_FUND_DOMINANCE_RATIO:
                flow_verdict_v = '存量调整主导'
                direction_v = None
            else:
                flow_verdict_v = '资金僵持'
                direction_v = None
            side_data['fund_flow_verdict'] = flow_verdict_v
            side_data['new_fund_net_long'] = ff.get('new_fund_net_long', 0)
            side_data['new_fund_net_short'] = ff.get('new_fund_net_short', 0)
            side_data['new_fund_net_neutral'] = ff.get('new_fund_net_neutral', 0)
            side_data['stock_adj_net_long'] = ff.get('stock_adj_net_long', 0)
            side_data['stock_adj_net_short'] = ff.get('stock_adj_net_short', 0)
            side_data['new_fund_dominant_nature'] = ff.get('new_fund_dominant_nature', 'unknown')
            side_data['dominant_nature'] = ff.get('dominant_nature', 'unknown')
            side_data['verdict_direction'] = direction_v  # v2.11.85h: consistent 也给方向
        result[side] = side_data

    # ============================================================
    # v2.11.85f: 综合两端 new_fund_direction（仅 contradictory 时有意义）
    # ============================================================
    if consistency == 'contradictory':
        ff_c = fund_flow.get('Call', {})
        ff_p = fund_flow.get('Put', {})
        c_long = ff_c.get('new_fund_net_long', 0)
        c_short = ff_c.get('new_fund_net_short', 0)
        p_long = ff_p.get('new_fund_net_long', 0)
        p_short = ff_p.get('new_fund_net_short', 0)
        abs_c_new = abs(c_long) + abs(c_short) + abs(ff_c.get('new_fund_net_neutral', 0))
        abs_p_new = abs(p_long) + abs(p_short) + abs(ff_p.get('new_fund_net_neutral', 0))
        abs_c_stock = abs(ff_c.get('stock_adj_net_long', 0)) + abs(ff_c.get('stock_adj_net_short', 0))
        abs_p_stock = abs(ff_p.get('stock_adj_net_long', 0)) + abs(ff_p.get('stock_adj_net_short', 0))
        c_new_dom = abs_c_new > abs_c_stock * NEW_FUND_DOMINANCE_RATIO
        p_new_dom = abs_p_new > abs_p_stock * NEW_FUND_DOMINANCE_RATIO

        # 标的看多力 = Call 多 - Put 多(反向)
        # 标的看空力 = Put 空 - Call 空(反向)
        bull_force = c_long - p_long
        bear_force = p_short - c_short

        if c_new_dom and p_new_dom:
            # 两端都新资金主导 → 比较力量
            if bear_force > bull_force and bear_force > 0:
                result['new_fund_direction'] = '看空'
            elif bull_force > bear_force and bull_force > 0:
                result['new_fund_direction'] = '看多'
            else:
                result['new_fund_direction'] = '多空博弈'
        elif c_new_dom and not p_new_dom:
            # 只有 Call 新资金主导
            if c_long > abs(c_short):
                result['new_fund_direction'] = '看多'
            elif abs(c_short) > c_long:
                result['new_fund_direction'] = '看空'
            else:
                result['new_fund_direction'] = None
        elif p_new_dom and not c_new_dom:
            # 只有 Put 新资金主导
            if p_short > abs(p_long):
                result['new_fund_direction'] = '看空'
            elif abs(p_long) > p_short:
                result['new_fund_direction'] = '看多'
            else:
                result['new_fund_direction'] = None
        else:
            # 两端存量主导或僵持 → 不给方向
            result['new_fund_direction'] = None
    else:
        result['new_fund_direction'] = None

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


# ============================================================
# v2.11.85e: 资金意图层综合结论 + PCR×Skew 交叉验证
# 严格按飞书 §2.3.1 第三层 Put端与Call端合成信号矩阵 + §2.3.2 附录交叉验证框架
# ============================================================

# 飞书 §2.3.1 14 行表的方向枚举（5 档）
DIRECTION_5 = ('看空', '偏空', '中性', '偏多', '看多')

# v2.11.85e: 把 _to_dir 输出（业务语义丰富）映射到飞书 5 档
DIR_BUSINESS_TO_5 = {
    '看多':       '看多',
    '偏多(弱)':   '偏多',
    '偏多(防御)': '偏多',
    '看空':       '看空',
    '偏空(弱)':   '偏空',
    '偏空(防御)': '偏空',
    '中性':       '中性',
    'unknown':    '中性',
}


def _to_dir_5(scores_or_dir: dict, side: str = None) -> str:
    """v2.11.85e: _to_dir 输出 → 飞书 5 档方向（看空/偏空/中性/偏多/看多）

    输入可以是:
      - scores dict (weighted_pct 形式) + side ('Call'/'Put') → 自动调 _to_dir
      - 已经计算好的 _to_dir 字符串 ('看多'/'偏多(弱)'/...)
    """
    if isinstance(scores_or_dir, str):
        return DIR_BUSINESS_TO_5.get(scores_or_dir, '中性')
    if isinstance(scores_or_dir, dict):
        return DIR_BUSINESS_TO_5.get(_to_dir(scores_or_dir, side or 'Call'), '中性')
    return '中性'


def synthesize_funding_signal(call_main_nat: str, put_main_nat: str,
                              pcr_now: float = 0, pcr_prev: float = 0,
                              strike_modifier: str = '') -> Dict[str, Any]:
    """v2.11.85e: 资金意图层综合结论（严格按飞书 §2.3.1 第三层合成信号矩阵）

    输入:
      call_main_nat: Call 端加权判定主信号 (spec_buy_directional, hedge_sell 等)
      put_main_nat:  Put 端加权判定主信号
      pcr_now: 当前 PCR
      pcr_prev: 前次 PCR (用于恐慌出清 / 乐观消退 早返)
      strike_modifier: strike 级别修正项（v2.11.63d，慢牛/慢熊）

    输出:
      {
        'signal_label': str,     # 业务标签（飞书 14 行表）
        'signal_strength': str,  # 强/中/中弱/弱/极弱(观望)
        'signal_direction': str, # 综合方向（看多/看空/中性/矛盾）
        'p_dir': str,             # Put 端业务方向
        'c_dir': str,             # Call 端业务方向
        'source': str,            # 飞书协议引用
      }

    调用 judge_state.label_standardize 完成查表（§2.3.1 第三层）
    """
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location('judge_state',
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'judge_state.py'))
    _js = _ilu.module_from_spec(_spec)
    # v2.11.85e: judge_state L67 import generate_daily_report 依赖 requests 模块,
    # 缺 requests 时跳过其副作用但仍暴露 label_standardize
    try:
        _spec.loader.exec_module(_js)
    except (ImportError, ModuleNotFoundError):
        # 缺 requests 时: 把 label_standardize + PCR 常量复制出来本地调用
        import re as _re
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'judge_state.py')) as _f:
            _src = _f.read()
        # 提取 PCR_* 常量定义行
        for line in _src.split('\n'):
            if _re.match(r'^(PCR_FEAR_LOW|PCR_FEAR_HIGH|PCR_NEUTRAL_LOW|PCR_NEUTRAL_HIGH)\s*=', line):
                exec(line, _js.__dict__)
        # 提取 label_standardize 函数（整个 def 块）
        m = _re.search(r'^def label_standardize.*?(?=^def |\Z)', _src, _re.MULTILINE | _re.DOTALL)
        if m:
            exec(m.group(0), _js.__dict__)
    label, strength = _js.label_standardize(
        put_nature=put_main_nat,
        call_nature=call_main_nat,
        strike_modifier=strike_modifier,
        pcr_now=pcr_now,
        pcr_prev=pcr_prev,
    )
    # 综合方向从 label 推断（用于交叉验证的子规则方向一致性判定）
    if '看空' in label and '看多' not in label:
        sig_dir = '看空'
    elif '看多' in label and '看空' not in label:
        sig_dir = '看多'
    elif '分歧' in label or '矛盾' in label:
        sig_dir = '矛盾'
    else:  # 中性 / 无方向 / 箱体震荡
        sig_dir = '中性'
    # v2.11.85f: judge_state.L891/912 的 PUT_DIR/CALL_DIR 是 label_standardize 函数内局部常量,
    # _js 模块级访问不到,这里本地复制一份 5 档方向映射
    _PUT_DIR_LOCAL = {
        'spec_buy': '看空', 'spec_buy_directional': '看空', 'close_push': '看空',
        'spec_buy_lotto': '偏空',
        'hedge_buy': '偏多',
        'hedge_sell': '中性', 'double_exit': '中性', 'supply_overhang': '中性',
        'mixed_neutral': '中性', 'passive_close': '中性', 'noise_close': '中性',
        'noise_open': '中性', 'theta_decay': '中性', 'quote_adjust': '中性',
        'static': '中性', 'hedge_rolling': '中性',
    }
    _CALL_DIR_LOCAL = {
        'spec_buy': '看多', 'spec_buy_directional': '看多', 'close_push': '看多',
        'spec_buy_lotto': '偏多',
        'hedge_buy': '偏空',
        'hedge_sell': '中性', 'double_exit': '中性', 'supply_overhang': '中性',
        'mixed_neutral': '中性', 'passive_close': '中性', 'noise_close': '中性',
        'noise_open': '中性', 'theta_decay': '中性', 'quote_adjust': '中性',
        'static': '中性', 'hedge_rolling': '中性',
    }
    return {
        'signal_label': label,
        'signal_strength': strength,
        'signal_direction': sig_dir,
        'p_dir': _PUT_DIR_LOCAL.get(put_main_nat, '中性'),
        'c_dir': _CALL_DIR_LOCAL.get(call_main_nat, '中性'),
        'source': '飞书 §2.3.1 Put端与Call端合成信号矩阵 (v2.11.85f)',
    }


def _iv_change_bucket(iv_change_pp: float) -> str:
    """v2.11.85e: IV 变化幅度分档（飞书附录第二步 Skew变化可靠性系数）

    <0.5pp: 弱信号
    0.5-1.5pp: 中等信号
    >1.5pp: 强信号
    """
    a = abs(iv_change_pp or 0)
    if a < 0.5:
        return '弱信号'
    elif a < 1.5:
        return '中等'
    else:
        return '强信号'


def _fund_activity_bucket(abs_oi_chg: float) -> str:
    """v2.11.85e: 资金活跃度分档（飞书附录第一步）

    <2000: 极低
    2000-5000: 低
    5000-15000: 中
    >15000: 高
    """
    a = abs(abs_oi_chg or 0)
    if a < 2000:
        return '极低'
    elif a < 5000:
        return '低'
    elif a < 15000:
        return '中'
    else:
        return '高'


def cross_validate_synthesized_signal(synth_label: str, synth_direction: str,
                                       pcr_dir: str, skew_dir: str,
                                       fund_call_abs: float, fund_put_abs: float,
                                       iv_call_chg: float, iv_put_chg: float,
                                       skew_delta_pp: float = 0) -> Dict[str, Any]:
    """v2.11.85e: 按飞书 §2.3.2 附录交叉验证框架验证资金意图综合结论

    流程: 三步走 + 一个前置 + 4 个子规则
      Step 1: 资金活跃度分档 (max(call, put))
      Step 2: Skew 变化可靠性 (|Skew delta_pp|)
      前置: 方向一致性 (synth_direction vs PCR+Skew 方向)
      子规则 1: 方向一致 → fund × IV 评级
      子规则 2: 方向矛盾 → fund × IV 评级 (大资金方主导)
      子规则 3: PCR 平稳 + Skew 有方向 → IV 评级
      子规则 4: PCR 平稳 + IV 弱 → 无修正

    输入:
      synth_label: 飞书 §2.3.1 合成信号标签 (e.g. "多空分歧(极端)")
      synth_direction: 综合方向 ('看多'/'看空'/'中性'/'矛盾')
      pcr_dir: 'up'/'down'/'flat'
      skew_dir: 'deepen'/'flatten'/'flat'
      fund_call_abs: Call 端总 |ΔOI| (手)
      fund_put_abs: Put 端总 |ΔOI| (手)
      iv_call_chg: Call IV 变化 (pp)
      iv_put_chg: Put IV 变化 (pp)

    输出:
      {
        'verdict': str,           # '强确认'/'确认'/'弱确认'/'弱确认(降级)'/'无修正'/'忽略噪音'
        'subrule': 1/2/3/4,
        'rationale': str,         # 飞书附录引用
        'consistency': str,       # 'consistent'/'contradictory'/'pcr_flat'
        'fund_bucket': str,       # '极低'/'低'/'中'/'高'
        'iv_bucket': str,         # '弱信号'/'中等'/'强信号'
        'source': str,
      }
    """
    # Step 1: 资金活跃度（取两端较大者 = 大资金方）
    fund_bucket_call = _fund_activity_bucket(fund_call_abs)
    fund_bucket_put = _fund_activity_bucket(fund_put_abs)
    # 整体资金活跃度: 取 max(call, put) 的绝对 OI 变化分档
    fund_abs = max(fund_call_abs or 0, fund_put_abs or 0)
    fund_bucket = _fund_activity_bucket(fund_abs)

    # Step 2: Skew 变化可靠性（用 |Skew delta| 绝对值）
    # 优先用传入的 skew_delta_pp，否则从 call/put IV 变化估算
    if skew_delta_pp:
        iv_pp_for_bucket = skew_delta_pp
    else:
        # 估算: Skew = put_iv - call_iv, delta = (put_iv_now - put_iv_prev) - (call_iv_now - call_iv_prev)
        iv_pp_for_bucket = (iv_put_chg or 0) - (iv_call_chg or 0)
    iv_bucket = _iv_change_bucket(iv_pp_for_bucket)

    # 前置: 方向一致性（合成信号方向 vs PCR+Skew 方向）
    # PCR 方向: up=看空(>0.01), down=看多(<-0.01), flat=平稳
    # Skew 方向: deepen=看空(delta>+0.3pp), flatten=看多(delta<-0.3pp), flat=平稳
    # 合成信号方向: 看多 / 看空 / 中性 / 矛盾(分裂)

    # 子规则 3/4 的前置: PCR 平稳
    if pcr_dir == 'flat':
        consistency = 'pcr_flat'
    else:
        # 合成信号 vs PCR+Skew 方向一致性
        pcr_skew_dir = '看空' if pcr_dir == 'up' else '看多'
        if synth_direction == '看多' and pcr_skew_dir == '看多':
            consistency = 'consistent'
        elif synth_direction == '看空' and pcr_skew_dir == '看空':
            consistency = 'consistent'
        elif synth_direction in ('中性', '矛盾'):
            # 中性/矛盾的合成信号 vs 明确 PCR+Skew 方向 → 矛盾
            consistency = 'contradictory'
        elif synth_direction != pcr_skew_dir:
            consistency = 'contradictory'
        else:
            consistency = 'contradictory'  # 兜底

    # 注意: PCR 平稳时子规则 3/4 应用（不论合成信号方向如何）

    # 子规则
    if consistency == 'consistent':
        # 子规则 1: 方向一致
        if fund_bucket == '极低' and iv_bucket == '弱信号':
            verdict = '忽略噪音'
            rationale = f'子规则1: 低资金+弱IV=忽略噪音（fund={fund_bucket}, iv={iv_bucket}）'
        elif fund_bucket == '极低':
            verdict = '弱确认（降级）'
            rationale = f'子规则1: 极低资金降级（fund={fund_bucket}, iv={iv_bucket}）'
        elif iv_bucket == '弱信号':
            # 高/中资金 + 弱 IV → 弱确认
            if fund_bucket == '高':
                verdict = '弱确认'
                rationale = f'子规则1: 高资金+弱IV=弱确认（卖权收租可能）'
            else:
                verdict = '弱确认（降级）'
                rationale = f'子规则1: 中资金+弱IV=弱确认降级'
        else:
            table_s1 = {
                ('高', '强信号'):   '强确认',
                ('高', '中等'):     '确认',
                ('中', '强信号'):   '确认',
                ('中', '中等'):     '弱确认',
                ('中', '弱信号'):   '弱确认（降级）',
                ('低', '强信号'):   '弱确认（降级）',
                ('低', '中等'):     '弱确认（降级）',
                ('低', '弱信号'):   '忽略噪音',
            }
            verdict = table_s1.get((fund_bucket, iv_bucket), '无修正')
            rationale = f'子规则1: 方向一致 fund={fund_bucket} × iv={iv_bucket}'
        return {
            'verdict': verdict, 'subrule': 1, 'rationale': rationale,
            'consistency': consistency, 'fund_bucket': fund_bucket, 'iv_bucket': iv_bucket,
            'source': '飞书 §2.3.2 附录交叉验证 (v2.11.85e)',
        }
    elif consistency == 'contradictory':
        # 子规则 2: 方向矛盾 - 大资金方主导
        if fund_bucket == '极低' and iv_bucket == '弱信号':
            verdict = '忽略噪音'
            rationale = f'子规则2: 矛盾+极低资金+弱IV=忽略噪音'
        elif fund_bucket == '极低':
            verdict = '无修正'
            rationale = f'子规则2: 矛盾+极低资金=无修正'
        elif iv_bucket == '弱信号':
            if fund_bucket == '高':
                verdict = '弱确认'
                rationale = f'子规则2: 矛盾+高资金+弱IV=弱确认（大资金涌入但IV未变）'
            else:
                verdict = '忽略噪音'
                rationale = f'子规则2: 矛盾+中资金+弱IV=忽略噪音'
        else:
            table_s2 = {
                ('高', '强信号'):   '强确认',
                ('高', '中等'):     '确认',
                ('高', '弱信号'):   '弱确认',
                ('中', '强信号'):   '弱确认',
                ('中', '中等'):     '弱确认（降级）',
                ('中', '弱信号'):   '忽略噪音',
                ('低', '强信号'):   '弱确认（降级）',
                ('低', '中等'):     '无修正',
                ('低', '弱信号'):   '忽略噪音',
            }
            verdict = table_s2.get((fund_bucket, iv_bucket), '无修正')
            rationale = f'子规则2: 方向矛盾 fund={fund_bucket} × iv={iv_bucket}（大资金方主导）'
        return {
            'verdict': verdict, 'subrule': 2, 'rationale': rationale,
            'consistency': consistency, 'fund_bucket': fund_bucket, 'iv_bucket': iv_bucket,
            'source': '飞书 §2.3.2 附录交叉验证 (v2.11.85e)',
        }
    else:
        # consistency == 'pcr_flat' → 子规则 3 / 4
        if iv_bucket == '强信号':
            verdict = '弱确认'
            rationale = f'子规则3: PCR平稳+Skew有方向+强IV=弱确认（可能是做市商调整）'
            return {
                'verdict': verdict, 'subrule': 3, 'rationale': rationale,
                'consistency': consistency, 'fund_bucket': fund_bucket, 'iv_bucket': iv_bucket,
                'source': '飞书 §2.3.2 附录交叉验证 (v2.11.85e)',
            }
        elif iv_bucket == '中等':
            verdict = '无修正'
            rationale = f'子规则3/4: PCR平稳+中IV=无修正'
            return {
                'verdict': verdict, 'subrule': 3, 'rationale': rationale,
                'consistency': consistency, 'fund_bucket': fund_bucket, 'iv_bucket': iv_bucket,
                'source': '飞书 §2.3.2 附录交叉验证 (v2.11.85e)',
            }
        else:
            verdict = '无修正'
            rationale = f'子规则4: PCR平稳+弱IV=无修正'
            return {
                'verdict': verdict, 'subrule': 4, 'rationale': rationale,
                'consistency': consistency, 'fund_bucket': fund_bucket, 'iv_bucket': iv_bucket,
                'source': '飞书 §2.3.2 附录交叉验证 (v2.11.85e)',
            }


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

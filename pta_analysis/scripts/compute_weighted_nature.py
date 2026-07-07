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
    """单端 (Call/Put) 达标 strike + 综合权重 + SCORE_性质"""
    if not strike_rows or futures_price <= 0:
        return None
    oi_fld = f'{side.lower()}_oi'
    oi_chg_fld = f'{side.lower()}_oi_change'  # %
    iv_fld = f'{side.lower()}_iv'
    iv_chg_fld = f'{side.lower()}_iv_change'  # pp

    rows = []
    for r in strike_rows:
        try:
            oi_cur = float(r.get(oi_fld) or 0)
            iv_cur = float(r.get(iv_fld) or 0)
            if oi_cur < MIN_OI or iv_cur < MIN_IV_PCT:
                continue
            s = int(r['strike'])
            oi_pct = float(r.get(oi_chg_fld) or 0)  # T 表字段: %
            iv_pp = float(r.get(iv_chg_fld) or 0)   # T 表字段: pp
            if iv_pp is None:
                continue

            # 还原 prev_oi 用于算 |ΔOI| 绝对量 (分母 Contribution 用)
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

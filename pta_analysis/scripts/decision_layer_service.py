#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA 决策层独立调度服务（v2.11.77b）

目的：把 judge_state.py 的四维决策（PAIN 结构 / GEX 机制 / 资金意图 / 情绪确认）
从 generate_report() 解耦，独立 daemon 线程每 15 分钟跑一次，
落盘 data/fundamental/decision_layer_cache.json，前端通过 /api/decision_layer 读取。

为什么独立（vs 接到 15min 研报刷新里）：
1. judge_state 跑一次 ~200ms，会拖慢研报刷新（用户感知）
2. 解耦后能独立监控、独立报警、独立手动触发
3. 与 pta-tqsdk-watchdog-v21173 / pta-web-cache-periodic-refresh 一致的模式

缓存路径：data/fundamental/decision_layer_cache.json
调度频率：15 分钟（与研报面板对齐）
对齐策略：启动后 sleep 到下一个整 15 分边界，避免启动打满
"""

import os
import sys
import json
import time
import threading
import logging
from datetime import datetime
from typing import Optional, Dict, Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

# 与 web_app_integrated.py 保持一致的缓存目录
FUNDAMENTAL_DIR = os.path.join(PROJECT_ROOT, 'data', 'fundamental')
CACHE_PATH = os.path.join(FUNDAMENTAL_DIR, 'decision_layer_cache.json')

# 调度参数
SCHEDULE_INTERVAL_MINUTES = 15
REFRESH_TIMEOUT_SEC = 30  # judge_state 自身超时上限
LOG_TAG = '[decision_layer_service]'

# 模块级状态（线程安全靠 GIL 单进程 + 短临界区）
_state_lock = threading.Lock()
_in_progress = False
_service_started = False  # start() 幂等

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
)
_logger = logging.getLogger(__name__)


# ============================================================
# judge_state 调用：复用现有 importlib 加载模式（scripts/judge_state.py:62-66）
# ============================================================
def _load_judge_state_module():
    """加载 scripts/judge_state.py 模块（importlib 模式，复用 web_app 已有模式）"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'judge_state',
        os.path.join(SCRIPT_DIR, 'judge_state.py')
    )
    if spec is None or spec.loader is None:
        raise RuntimeError('judge_state.py 路径解析失败')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ============================================================
# v2.11.85d: PCR + Skew 交叉验证数据契约层（飞书 §2.3.2 附录）
# ============================================================
def _build_cross_validation_inputs(chain_data, alert_data, gex, weighted):
    """从 T 表 + alert_data + gex 提取 PCR 驱动因素 + Skew 驱动因素 + 资金活跃度

    输出 dict 结构: see SKILL.md pta-decision-layer-service-85d-cross-validation
    """
    strike_rows = (chain_data or {}).get('strike_rows') or []
    if not strike_rows:
        return {'available': False, 'note': 'strike_rows 为空'}

    from scripts.compute_weighted_nature import (
        _calc_fund_activity, _classify_iv_reliability
    )

    # ---------- PCR 驱动因素 ----------
    rows_ad = (alert_data or {}).get('rows', []) or []
    call_oi_now = sum((r.get('oi_call') or 0) for r in rows_ad)
    put_oi_now  = sum((r.get('oi_put')  or 0) for r in rows_ad)
    call_oi_prev = sum((r.get('oi_call_prev') or 0) for r in rows_ad)
    put_oi_prev  = sum((r.get('oi_put_prev')  or 0) for r in rows_ad)
    pcr_now  = (put_oi_now / call_oi_now) if call_oi_now else 0
    pcr_prev = (put_oi_prev / call_oi_prev) if call_oi_prev else 0
    pcr_delta = pcr_now - pcr_prev

    if pcr_delta > 0.01:
        pcr_direction = 'up'
    elif pcr_delta < -0.01:
        pcr_direction = 'down'
    else:
        pcr_direction = 'flat'

    call_oi_chg = call_oi_now - call_oi_prev
    put_oi_chg = put_oi_now - put_oi_prev
    put_up = put_oi_chg > 0
    call_dn = call_oi_chg < 0
    if pcr_direction == 'up' and put_up and call_dn:
        pcr_drive = 'both'
    elif pcr_direction == 'up' and put_up:
        pcr_drive = 'put_oi_up'
    elif pcr_direction == 'up' and call_dn:
        pcr_drive = 'call_oi_down'
    elif pcr_direction == 'down' and put_oi_chg < 0 and call_oi_chg > 0:
        pcr_drive = 'both'
    elif pcr_direction == 'down' and put_oi_chg < 0:
        pcr_drive = 'put_oi_down'
    elif pcr_direction == 'down' and call_oi_chg > 0:
        pcr_drive = 'call_oi_up'
    else:
        pcr_drive = 'flat'

    # ---------- Skew 变化（v2.11.85d 修订：ATM ±5 档简单平均口径）----------
    # 旧口径: 全档 OI 加权平均 IV → 受深度虚值档 OI 拉偏
    # 新口径: ATM ±5 档（11 档）Call/Put 简单平均 IV → 覆盖完整轻度虚实值区
    #   - ±3 档是 7 档（1.72%-5.17% moneyness），太窄
    #   - ±5 档是 11 档（1.72%-8.62% moneyness），覆盖 OTM/ITM_slight 全段
    #   - 最大 8.62% < 10% OTM_deep 边界，不会引入深度虚值（spec_buy_lotto 噪音）
    #   - 5300-5400 含产业买保深度 ITM；6200-6300 含产业卖权收租虚值区
    # 业务映射:
    #   skew_delta = (Put_avg - Call_avg)_now - (Put_avg - Call_avg)_prev
    #   正值 > +0.3pp → Skew 加深（Put 端相对变贵 → 强化 Put 端看空）
    #   负值 < -0.3pp → Skew 减轻（Call 端相对变贵 → 强化 Call 端看多）
    #   |delta| ≤ 0.3pp → Skew flat
    # 注: 数据源是 alert_data.rows[].iv_call/iv_put，prev 用 alert_data.rows[].iv_call_prev（前日 15:00 收盘）
    #     维持前日基准 → 日内多次 refresh 相对同一基准，delta 反映日内动态

    # 数据源: alert_data.atm_strike + alert_data.rows[].iv_call/iv_put/iv_call_prev/iv_put_prev
    # 注: chain_data.strike_rows 里的 call_iv 和 put_iv 是同一个值（SVI 拟合后的 avg IV），
    #     算不出真实 Skew。必须用 alert_data.rows 里分开的 iv_call / iv_put。
    atm_strike = (alert_data or {}).get('atm_strike') or 0
    curve = []
    for r in rows_ad:
        sv = r.get('strike')
        if sv is None:
            continue
        curve.append({
            'strike': sv,
            'call_iv':      r.get('iv_call'),
            'put_iv':       r.get('iv_put'),
            'call_iv_prev': r.get('iv_call_prev'),
            'put_iv_prev':  r.get('iv_put_prev'),
        })

    # 找 ATM 位置
    if atm_strike and curve:
        strikes_list = [c['strike'] for c in curve if c.get('strike') is not None]
        if atm_strike in strikes_list:
            atm_idx = strikes_list.index(atm_strike)
            neighbor = curve[max(0, atm_idx-5):atm_idx+6]  # ATM ±5 档（11 档）
        else:
            # ATM 不在 curve 里 → 取最接近的
            closest = min(strikes_list, key=lambda s: abs(s - atm_strike))
            atm_idx = strikes_list.index(closest)
            neighbor = curve[max(0, atm_idx-5):atm_idx+6]
    else:
        # 没 ATM 信息 → 取 curve 中间 11 档
        n = len(curve)
        if n >= 11:
            neighbor = curve[n//2-5:n//2+6]
        else:
            neighbor = curve

    # 计算简单平均（仅用有值的 strike）
    c_iv_now_list  = [c.get('call_iv')      for c in neighbor if c.get('call_iv')      is not None]
    p_iv_now_list  = [c.get('put_iv')       for c in neighbor if c.get('put_iv')       is not None]
    c_iv_prev_list = [c.get('call_iv_prev') for c in neighbor if c.get('call_iv_prev') is not None]
    p_iv_prev_list = [c.get('put_iv_prev')  for c in neighbor if c.get('put_iv_prev')  is not None]

    def _safe_mean(lst):
        return sum(lst) / len(lst) if lst else 0

    # 注：call_iv / put_iv 是百分比数字（如 28.79 = 28.79%），直接相减就是 pp 变化
    #     不需要 *100（那会把 28.79 变成 2879%）
    call_iv_now_avg  = _safe_mean(c_iv_now_list)
    put_iv_now_avg   = _safe_mean(p_iv_now_list)
    call_iv_prev_avg = _safe_mean(c_iv_prev_list)
    put_iv_prev_avg  = _safe_mean(p_iv_prev_list)

    skew_now  = put_iv_now_avg  - call_iv_now_avg
    skew_prev = put_iv_prev_avg - call_iv_prev_avg
    skew_delta_pp = skew_now - skew_prev

    # 业务映射方向 A: put_iv - call_iv 差值 = "Skew"
    SKEW_DEEPEN_THRESHOLD = 0.3  # pp（业务口径，与 IV 变化幅度 0.5/1.5pp 子规则分档对齐）
    if skew_delta_pp > SKEW_DEEPEN_THRESHOLD:
        skew_direction = 'deepen'
    elif skew_delta_pp < -SKEW_DEEPEN_THRESHOLD:
        skew_direction = 'flatten'
    else:
        skew_direction = 'flat'

    # 驱动因素分解：deepen 时是谁推动的？
    put_iv_up = (put_iv_now_avg - put_iv_prev_avg) > 0.1
    call_iv_dn = (call_iv_now_avg - call_iv_prev_avg) < -0.1
    put_iv_dn = (put_iv_now_avg - put_iv_prev_avg) < -0.1
    call_iv_up = (call_iv_now_avg - call_iv_prev_avg) > 0.1
    if skew_direction == 'deepen' and put_iv_up and call_iv_dn:
        skew_drive = 'both'
    elif skew_direction == 'deepen' and put_iv_up:
        skew_drive = 'put_iv_up'
    elif skew_direction == 'deepen' and call_iv_dn:
        skew_drive = 'call_iv_down'
    elif skew_direction == 'flatten' and put_iv_dn and call_iv_up:
        skew_drive = 'both'
    elif skew_direction == 'flatten' and put_iv_dn:
        skew_drive = 'put_iv_down'
    elif skew_direction == 'flatten' and call_iv_up:
        skew_drive = 'call_iv_up'
    else:
        skew_drive = 'flat'

    # ---------- 资金活跃度（call/put 两端）----------
    fund_call = _calc_fund_activity(strike_rows, 'Call')
    fund_put  = _calc_fund_activity(strike_rows, 'Put')

    # ---------- Skew 变化可靠性（call/put 两端，基于 ATM 邻域简单平均变化）----------
    # v2.11.85d 修订: 用 ATM ±3 档简单平均 IV 变化代替全档 OI 加权
    iv_rel_call = _classify_iv_reliability(call_iv_now_avg - call_iv_prev_avg)
    iv_rel_put  = _classify_iv_reliability(put_iv_now_avg - put_iv_prev_avg)

    return {
        'available': True,
        'threshold_version': 'v2.11.85d',
        'pcr': {
            'now': round(pcr_now, 4),
            'prev': round(pcr_prev, 4),
            'delta': round(pcr_delta, 4),
            'call_oi_now': call_oi_now,
            'put_oi_now': put_oi_now,
            'call_oi_prev': call_oi_prev,
            'put_oi_prev': put_oi_prev,
            'call_oi_chg': call_oi_chg,
            'put_oi_chg': put_oi_chg,
            'direction': pcr_direction,
            'drive': pcr_drive,
        },
        'skew': {
            'now': round(skew_now, 3),         # 当前 (Put - Call) 差值，单位 pp
            'prev': round(skew_prev, 3),        # 前次 (Put - Call) 差值，单位 pp
            'delta_pp': round(skew_delta_pp, 3),# 变化量 = now - prev
            'call_iv_now': round(call_iv_now_avg, 3),
            'put_iv_now': round(put_iv_now_avg, 3),
            'call_iv_prev': round(call_iv_prev_avg, 3),
            'put_iv_prev': round(put_iv_prev_avg, 3),
            'call_iv_chg_pp': round(call_iv_now_avg - call_iv_prev_avg, 3),
            'put_iv_chg_pp': round(put_iv_now_avg - put_iv_prev_avg, 3),
            'direction': skew_direction,        # 'deepen' / 'flatten' / 'flat'
            'drive': skew_drive,
            'method': 'atm_neighbor_simple_avg',  # v2.11.85d 修订口径
            'neighbor_window': len(neighbor),     # 邻域 strike 数（应为 7）
            'atm_strike': atm_strike,
        },
        'fund_activity': {
            'Call': fund_call,
            'Put':  fund_put,
        },
        'iv_reliability': {
            'Call': iv_rel_call,
            'Put':  iv_rel_put,
        },
    }


def _fetch_iv_smile_data() -> Dict[str, Any]:
    """复用 judge_state.py 的 fetch_iv_smile_data（避免重复实现 + 代理设置）"""
    js = _load_judge_state_module()
    return js.fetch_iv_smile_data(base_url='http://47.100.97.88', use_proxy=True)


def _build_decision_layer_payload(gex: dict, alert_data: dict, curve: dict) -> Dict[str, Any]:
    """调 judge_state 4 个 layer 函数拼装决策层 dict

    返回结构对齐前端 renderDecisionLayerBlock(d) 期望：
    {layer1, layer2, layer3, layer4, final, generated_at}

    注意函数签名（v2.11.77 judge_state.py）：
    - L2/L3/L4 都依赖 layer1（用 L1 的 shape/position/gex_dir/p_vs_flip）
    - synthesize_decision 接受 list[Dict] 不是 4 个参数
    """
    js = _load_judge_state_module()
    intraday_slots = (gex or {}).get('intraday_slots') or []

    # L1: PAIN 结构（独立，无依赖）
    l1 = js.judge_layer1_pain_structure(gex or {}, alert_data or {}, intraday_slots=intraday_slots)
    # L2: GEX 机制（依赖 L1）
    l2 = js.judge_layer2_gex(l1, intraday_slots=intraday_slots)
    # L3: 资金意图（依赖 L1）
    l3 = js.judge_layer3_funding_intent(alert_data or {}, gex or {}, l1, intraday_slots=intraday_slots)
    # L4: 情绪确认（依赖 L1）
    l4 = js.judge_layer4_emotion(curve or {}, alert_data or {}, l1, gex or {}, intraday_slots=intraday_slots)
    # final: 综合判断（接受 list）
    final = js.synthesize_decision([l1, l2, l3, l4])

    payload = {
        'layer1': l1,
        'layer2': l2,
        'layer3': l3,
        'layer4': l4,
        'final': final,
        'generated_at': datetime.now().isoformat(timespec='seconds'),
    }

    # ============================================================
    # v2.11.85a 替换: 用 compute_weighted_nature 完全替换老 _compute_nature_and_synthesis 路径
    # 老算法产出的 call_role / put_role / role_summary / standardized_label / strike_modifier /
    # data_quality (v2.11.84) 全部用 v2.11.85a 输出覆盖
    # 老算法产出的 put_nature / call_nature / nature_label / business_meaning / pcr / shape / position 保留
    # 数据源: /api/options/chain (T 表, 含 call_oi_change/iv_change 字段)
    # 前端: renderL3StrikeDetail (kline_lightweight.html) 改读 strike_role[] + weighted_verdict
    # judge_state.py narrative 增加 v2.11.85a weighted summary
    # ============================================================
    try:
        from scripts.compute_weighted_nature import compute_weighted_nature as _cwn
        import urllib.request
        with urllib.request.urlopen(
            'http://127.0.0.1:8424/api/options/chain?main_only=true', timeout=5
        ) as resp:
            chain_data = json.loads(resp.read())
        strike_rows = (chain_data or {}).get('strike_rows') or []
        F = float((chain_data or {}).get('underlying_price') or 0)
        weighted = _cwn(strike_rows, F)
        if weighted:
            # ---------- v2.11.85a: 用 strike_role[] 重算 call_role / put_role 兼容老前端 ----------
            def _rebuild_role_dict(strike_role_list):
                """从 v2.11.85a 的 strike_role[] 重算老 call_role / put_role dict 结构
                老结构: {spec_trim:[], spec_add:[], hedge_sell:[], hedge_buy:[], close_push:[], double_exit:[], role_summary, _top_n}
                """
                d = {'spec_trim': [], 'spec_add': [], 'hedge_sell': [],
                     'hedge_buy': [], 'close_push': [], 'double_exit': [], 'mixed_neutral': []}
                for s in (strike_role_list or []):
                    nat = s.get('nature', '')
                    row = {
                        'strike': s.get('strike'),
                        'side': s.get('side'),  # v2.11.85c: 加 side 字段，修复前端 7 栏目表 Call 端 strike 后缀 fallback 'P' bug
                        'nature': nat,
                        'oi_delta_pct': s.get('oi_pct'),
                        'iv_delta_pp': s.get('iv_pp'),
                        'oi_chg': s.get('oi_chg'),
                        'moneyness': s.get('moneyness'),
                        'contribution': s.get('contribution'),
                        'weight': s.get('weight'),
                    }
                    # v2.11.85a 性质映射到 v2.11.63d 老分类
                    # v2.11.85b 修复 5500P 错放: spec_buy_directional 必须显式映射
                    # 原版 NAT_MAP 漏掉这一行 → .get() fallback 到 'spec_trim'
                    #   业务语义 180° 反转（方向性投机看空 → 显示成撤退离场）
                    NAT_MAP = {
                        'hedge_sell': 'hedge_sell',
                        'hedge_buy': 'hedge_buy',
                        'spec_add': 'spec_add',
                        'spec_trim': 'spec_trim',
                        'close_push': 'close_push',
                        'double_exit': 'double_exit',
                        'passive_close': 'passive_close',
                        'noise_close': 'noise_ignore',
                        'noise_open': 'noise_ignore',
                        'quote_adjust': 'noise_ignore',
                        'theta_decay': 'noise_ignore',
                        'spec_buy_lotto': 'spec_buy_lotto',
                        'spec_buy_directional': 'spec_add',
                        'hedge_rolling': 'hedge_rolling',
                        'supply_overhang': 'supply_overhang',
                        'mixed_neutral': 'mixed_neutral',
                        'static': 'noise_ignore',
                    }
                    key = NAT_MAP.get(nat, 'noise_ignore')
                    if key not in d:
                        d[key] = []
                    d[key].append(row)
                # role_summary: 按 contribution 降序取 Top 5
                top_n = 5
                sorted_sr = sorted((strike_role_list or []), key=lambda x: -abs(x.get('contribution', 0)))
                NATURE_LABEL = {
                    'hedge_sell': '产业收租', 'hedge_buy': '产业买保',
                    'spec_add': '投机加仓', 'spec_trim': '投机撤退',
                    'close_push': '卖方平仓', 'double_exit': '双边撤退',
                    'passive_close': '被动平仓', 'noise_close': '噪声平仓',
                    'quote_adjust': '报价调整', 'spec_buy_lotto': '投机彩票',
                    'mixed_neutral': '中性',
                }
                def _fmt(r):
                    sv = r.get('strike')
                    side_letter = 'C' if r.get('side') == 'Call' else 'P'
                    nat_lbl = NATURE_LABEL.get(r.get('nature'), r.get('nature', '?'))
                    oi_pct = r.get('oi_pct')
                    iv_pp = r.get('iv_pp')
                    oi_str = f'{oi_pct:+.1f}%' if oi_pct is not None else '--'
                    iv_str = f'{iv_pp:+.2f}pp' if iv_pp is not None else '--'
                    return f'{sv}{side_letter}({nat_lbl} OI{oi_str} IV{iv_str})'
                d['role_summary'] = ' / '.join(_fmt(r) for r in sorted_sr[:top_n]) or '无显著方向分化'
                d['_top_n'] = top_n
                return d

            call_role_new = _rebuild_role_dict(weighted['Call']['strike_role'])
            put_role_new = _rebuild_role_dict(weighted['Put']['strike_role'])

            # ---------- v2.11.85a: 替换 L3 老字段（用新算法产出）----------
            payload['layer3']['call_role'] = call_role_new
            payload['layer3']['put_role'] = put_role_new
            payload['layer3']['call_role_summary'] = call_role_new['role_summary']
            payload['layer3']['put_role_summary'] = put_role_new['role_summary']
            payload['layer3']['standardized_label'] = weighted['Call']['label'] + ' / ' + weighted['Put']['label']
            payload['layer3']['standardized_intensity'] = (
                '强' if (weighted['Call']['main_pct'] > 60 or weighted['Put']['main_pct'] > 60) else
                ('中' if (weighted['Call']['main_pct'] > 40 or weighted['Put']['main_pct'] > 40) else '弱')
            )
            payload['layer3']['strike_modifier'] = (
                f'Call {weighted["Call"]["verdict"]} | Put {weighted["Put"]["verdict"]}'
            )
            payload['layer3']['data_quality'] = weighted['data_quality']
            # v2.11.85a 增量字段（前端新渲染用）
            payload['layer3']['strike_role'] = weighted['Call']['strike_role']
            payload['layer3']['put_strike_role'] = weighted['Put']['strike_role']
            payload['layer3']['weighted_pct'] = weighted['Call']['weighted_pct']
            payload['layer3']['put_weighted_pct'] = weighted['Put']['weighted_pct']
            payload['layer3']['weighted_label'] = weighted['Call']['label']
            payload['layer3']['put_weighted_label'] = weighted['Put']['label']
            payload['layer3']['weighted_verdict'] = weighted['Call']['verdict']
            payload['layer3']['put_weighted_verdict'] = weighted['Put']['verdict']
            payload['layer3']['direction'] = weighted['Call']['direction']
            payload['layer3']['put_direction'] = weighted['Put']['direction']
            payload['layer3']['weighted_version'] = 'v2.11.85a'

            # v2.11.85d: PCR + Skew 交叉验证数据契约（飞书文档 §2.3.2 附录）
            # 这些字段供 Step 2 综合判定函数消费，不影响现有 verdict 字段
            try:
                cross_val_inputs = _build_cross_validation_inputs(chain_data, alert_data, gex, weighted)
                payload['layer3']['cross_validation'] = cross_val_inputs
                # Step 2: 综合判定（4 子规则）→ 6 档置信度
                try:
                    from scripts.compute_weighted_nature import cross_validate_funding
                    cv_result = cross_validate_funding(cross_val_inputs)
                    payload['layer3']['cross_validation_verdict'] = cv_result
                except Exception as cv2_e:
                    _logger.warning('%s v2.11.85d cross_validate_funding skipped: %s', LOG_TAG, cv2_e)
                    payload['layer3']['cross_validation_verdict'] = {'error': str(cv2_e)}
            except Exception as cv_e:
                _logger.warning('%s v2.11.85d cross_validation skipped: %s', LOG_TAG, cv_e)
                payload['layer3']['cross_validation'] = {'available': False, 'note': str(cv_e)}

            _logger.info(
                '%s v2.11.85a replace OK: Call=%s (%.1f%%) Put=%s (%.1f%%)',
                LOG_TAG,
                weighted['Call']['main_nat'] or 'none',
                weighted['Call']['main_pct'],
                weighted['Put']['main_nat'] or 'none',
                weighted['Put']['main_pct'],
            )
    except Exception as e:
        # 增量挂接失败 → 老字段保留（_compute_nature_and_synthesis 已有兜底），前端仍能渲染
        _logger.warning('%s v2.11.85a replace skipped, fallback to old: %s', LOG_TAG, e)

    return payload


# ============================================================
# 缓存读写（原子写：tmp → os.replace）
# ============================================================
def _ensure_cache_dir():
    os.makedirs(FUNDAMENTAL_DIR, exist_ok=True)


def _atomic_write_json(path: str, data: dict):
    """原子写：避免 Flask 读取时拿到半截文件

    v2.11.78 加固：
    - tmp 用 PID+时间戳命名，避免多进程并发写覆盖
    - 写后立即 os.replace（POSIX 原子操作）
    - 读回 JSON 解析校验，防止磁盘满/编码问题导致写入"半成功"
    """
    import time as _t
    # tmp 用 PID + 纳秒精度时间戳 命名（毫秒精度会冲突:5 线程同 ms 调用相同）
    tmp = f"{path}.tmp.{os.getpid()}.{_t.time_ns()}"
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            try:
                os.fsync(f.fileno())  # 强刷盘，防断电丢数据
            except (OSError, AttributeError):
                pass  # 部分 fs (如 tmpfs) 不支持 fsync, 跳过
        # 写后验证:读回 JSON,确保可解析
        with open(tmp, 'r', encoding='utf-8') as f:
            json.load(f)
        os.replace(tmp, path)  # POSIX 原子 rename
    finally:
        # 任何异常时清理 tmp
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _read_cache() -> Optional[Dict[str, Any]]:
    if not os.path.exists(CACHE_PATH):
        return None
    try:
        with open(CACHE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        _logger.warning('%s 读 cache 失败: %s', LOG_TAG, e)
        return None


def _write_cache(payload: Dict[str, Any]):
    """写 cache + 附加 meta 字段（last_data_update / status）"""
    data = dict(payload)
    data['_meta'] = {
        'last_refresh_at': datetime.now().isoformat(timespec='seconds'),
        'cache_path': CACHE_PATH,
    }
    _atomic_write_json(CACHE_PATH, data)


# ============================================================
# 刷新逻辑（单次执行）
# ============================================================
def refresh_decision_layer(force: bool = False) -> Dict[str, Any]:
    """单次执行：拉 GEX / alert_data / curve → 跑 4 层 → 写 cache

    Args:
        force: True 时跳过 "距上次刷新 < 15min" 检查（手动刷新用）

    Returns:
        {'success': bool, 'decision_layer': dict|None, 'error': str|None}
    """
    global _in_progress

    with _state_lock:
        if _in_progress:
            return {'success': False, 'decision_layer': None,
                    'error': '决策层刷新已在进行中（避免并发）'}
        _in_progress = True

    try:
        # 检查 mtime：避免 15 分钟内重复跑（force=True 时跳过）
        if not force:
            cached = _read_cache()
            if cached and cached.get('_meta', {}).get('last_refresh_at'):
                try:
                    last = datetime.fromisoformat(cached['_meta']['last_refresh_at'])
                    age_sec = (datetime.now() - last).total_seconds()
                    if age_sec < SCHEDULE_INTERVAL_MINUTES * 60 - 30:  # 留 30s 余量
                        return {'success': True,
                                'decision_layer': cached.get('decision_layer'),
                                'skipped': True,
                                'reason': f'距上次刷新 {int(age_sec)}s，跳过'}
                except (ValueError, TypeError):
                    pass

        # 拉数据
        data = _fetch_iv_smile_data()
        gex = data.get('gex') or {}
        alert_data = data.get('alert_data') or {}
        curve = data.get('curve') or {}

        if not gex:
            return {'success': False, 'decision_layer': None,
                    'error': 'iv_smile/gex 返回空'}

        # 跑 4 层
        decision_layer = _build_decision_layer_payload(gex, alert_data, curve)

        # 写 cache（结构：顶层放 decision_layer + _meta，前端 API 直接透传 decision_layer 子树）
        cache_payload = {
            'decision_layer': decision_layer,
            'last_data_update': (gex.get('summary') or {}).get('last_update'),
            'futures_price': (gex.get('summary') or {}).get('futures_price'),
            'max_pain': (gex.get('summary') or {}).get('max_pain'),
        }
        _write_cache(cache_payload)

        _logger.info('%s ✅ 决策层刷新完成 @ %s', LOG_TAG, datetime.now().strftime('%H:%M:%S'))
        return {'success': True, 'decision_layer': decision_layer}

    except Exception as e:
        _logger.error('%s ❌ 决策层刷新失败: %s', LOG_TAG, e, exc_info=True)
        return {'success': False, 'decision_layer': None, 'error': str(e)}
    finally:
        with _state_lock:
            _in_progress = False


# ============================================================
# 周期调度 daemon（对齐整 15 分钟）
# ============================================================
def _periodic_scheduler():
    """对齐整 15 分钟边界，每 15 分钟跑一次刷新

    ⚠️ 致命陷阱（来自 pta-web-cache-periodic-refresh skill）：
    - while True 顶部必须 sleep 到下一个整 15 分边界
    - 不要在 while 内用 time.sleep(900) 固定 15min（会累积漂移）
    """
    now = datetime.now()
    boundary_sec = (SCHEDULE_INTERVAL_MINUTES - (now.minute % SCHEDULE_INTERVAL_MINUTES)) * 60 - now.second
    if boundary_sec <= 0:
        boundary_sec += SCHEDULE_INTERVAL_MINUTES * 60
    _logger.info('%s 周期调度启动：首次刷新在 %ds 后（整 %dmin 对齐）',
                  LOG_TAG, boundary_sec, SCHEDULE_INTERVAL_MINUTES)
    time.sleep(boundary_sec)

    while True:
        try:
            t0 = time.time()
            refresh_decision_layer(force=False)
            _logger.info('%s 周期刷新完成: %.1fs @ %s',
                         LOG_TAG, time.time() - t0, datetime.now().strftime('%H:%M:%S'))
        except Exception as e:
            _logger.error('%s 周期刷新失败: %s', LOG_TAG, e, exc_info=True)

        # 对齐下一个整 15 分边界
        now = datetime.now()
        boundary_sec = (SCHEDULE_INTERVAL_MINUTES - (now.minute % SCHEDULE_INTERVAL_MINUTES)) * 60 - now.second
        if boundary_sec <= 0:
            boundary_sec += SCHEDULE_INTERVAL_MINUTES * 60
        time.sleep(boundary_sec)


def start():
    """启动 daemon 线程（幂等：start 多次只起 1 个）

    调用入口（必须挂这两个）：
    1. if __name__ == '__main__' 直接启动场景（本文件单独调试）
    2. web_app_integrated.py 启动时（生产场景）
    """
    global _service_started
    if _service_started:
        return
    _service_started = True

    _ensure_cache_dir()
    t = threading.Thread(target=_periodic_scheduler, daemon=True, name='decision-layer-periodic')
    t.start()
    _logger.info('%s ✅ daemon 线程已启动', LOG_TAG)


def get_cache() -> Optional[Dict[str, Any]]:
    """对外 API：读 cache（线程安全，只读快照）"""
    return _read_cache()


# ============================================================
# 单独调试入口
# ============================================================
if __name__ == '__main__':
    print(f'{LOG_TAG} 单独调试模式')
    start()
    # 立即跑一次（不等待整点边界）
    result = refresh_decision_layer(force=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f'{LOG_TAG} cache 路径: {CACHE_PATH}')
    print(f'{LOG_TAG} cache 内容:')
    cached = _read_cache()
    if cached:
        print(json.dumps(cached.get('decision_layer', {}), ensure_ascii=False, indent=2))
    # 阻塞等 daemon 跑下一次（Ctrl+C 退出）
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print(f'{LOG_TAG} 退出')
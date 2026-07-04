#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA 期权决策脚本（v2.11.68）

严格按 skill `pta-options-decision-framework` v2.11.63 决策框架执行：
  1. 第一层：PAIN 结构层（形态+位置+GEX+PCR 4 维）  权重 35%
  2. 第二层：GEX 机制层（P vs Flip 位置）             权重 25%
  3. 第三层：资金意图层（性质判定+位置形态矩阵+strike 修正）权重 25%
  4. 第四层：情绪确认层（成交 PCR + ATM 隐波 + 趋势）权重 15%
  5. 四层加权叠加 + label 标准化 → 综合判断

v2.11.68 新增（动态对比机制）：
  - 整点 7 槽（10/11/14/15/21/22/23）vs 上次整点 = 1h 变化（短线方向）
  - 今日 vs 昨日 15:00 = daily_change（日间趋势）
  - 复用 skill `pta-pain-slope-indicator` 的 ±5 邻域算法（看跌/看涨阻力 + 9 象限 regime）
  - L1/L2/L3/L4 全部加 1h + daily 双轨动态对比
  - L3 B 方案：决策层只展示标准化 label + 跳段 3 链接，避免与段 3 性质判定×合成信号重复

数据源：
  - /api/iv_smile/status   → 合约 / TqSdk ready
  - /api/iv_smile/alert_data → rows（含 OI/IV/prev/vol 全档）
  - /api/iv_smile/curve    → futures_price / atm_strike / curve
  - /api/iv_smile/gex      → max_pain / net_gex / gex_flip / prev_summary
                             + intraday_slots (v2.11.68 整点历史)

调用现成函数（scripts/generate_daily_report.py）:
  - _judge_shape(call_oi, put_oi)                  → rightSteep/leftSteep/sym
  - _judge_position(futures_price, max_pain)       → aboveMP/atMP/belowMP
  - _judge_nature(oi_pct, iv_pp)                   → 6 性质 + mixed_neutral
  - _judge_nature_strike(oi_pct, iv_pp)            → strike 级别 6 性质
  - _compute_nature_and_synthesis(rows, ...)       → 完整资金意图层 + strike 修正

修复历史：
  v2.11.68:
    - 加 _get_intraday_slot_pair / _build_intraday_change / _build_daily_change 辅助函数
    - L1: 加 4 斜率字段（slope_down/up/ratio/regime）+ prev 4 字段 + 1h + daily 变化
    - L2: 加 net_gex now/prev/change + gex_flip now/prev/migration + 1h + daily 变化
    - L3: 加 1h PCR delta + detail_section_ref 标记（B 方案）
    - L4: 加 trend_1h / F_1h_ago（比 daily trend 更敏感）
  v2.11.65:
    - P0: 新增 label_standardize() 把现成函数 label 按 skill 表格标准化（多空分歧/恐慌出清升级）
    - P1: L4 接 prev_f + prev_pcr 实现"恐慌出清"判定
    - P2: L1 加 PCR 维度（持仓 + 成交）
    - P3: L1/L2 score 按 skill 高/中/弱 标准化（0.6/0.3/0）
    - P3: 清理 gex.oi_dist 冗余 fallback（rows 自带 OI 100% 覆盖）
    - 输出格式: 分层展示（每层独立 + 总结论在末尾），不是单行

使用：
  python3 scripts/judge_state.py              # 拉实时数据 + 输出
  python3 scripts/judge_state.py --json      # JSON 输出
"""

import sys, os, json, argparse
from datetime import datetime
from typing import Dict, List, Optional, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

# 引入现成判定函数（2026-07-04: 改用直接 import 替代 importlib）
# 原写法 importlib.util.spec_from_file_location('gdr', 'generate_daily_report.py')
#   + spec.loader.exec_module(gdr) 在 import 缓存满时会触发
#   'maximum recursion depth exceeded'（gdr 间接引用 judge_state 形成的循环）
# 新写法：直接 import 模块，sys.path 已经在 PROJECT_ROOT
from scripts.generate_daily_report import (
    _judge_shape,
    _judge_position,
    _compute_nature_and_synthesis,
)


# ============================================================
# 阈值常量（与 skill / 现成函数对齐）
# ============================================================
# skill 2.3.1 全档: OI 1% / IV 0.5pp
NATURE_OI_THRESHOLD = 0.01
NATURE_IV_THRESHOLD_PP = 0.5
# skill 2.3.1.d strike 级别: OI 1% / IV 0.15pp（v2.11.63e 修订）
STRIKE_OI_THRESHOLD = 0.01
STRIKE_IV_THRESHOLD_PP = 0.15
# skill 1.0 形态/位置
SHAPE_RATIO_THRESHOLD = 1.15
POSITION_BAND_PCT = 2.0
# skill 1.1/1.2 业务强度（label → score 映射）
SCORE_STRONG = 0.6    # skill "高"/"强"
SCORE_MEDIUM = 0.3    # skill "中"
SCORE_WEAK = 0.1      # skill "弱"/"略"
# skill 2.4 PCR 区间
PCR_FEAR_LOW = 0.6    # 过度乐观
PCR_NEUTRAL_LOW = 0.8
PCR_NEUTRAL_HIGH = 1.2
PCR_FEAR_HIGH = 1.5   # 恐慌
# skill 2.3.2 PCR 业务含义
PCR_BULLISH = 0.7     # 持仓 PCR 偏低（Call 多）→ 偏多
PCR_BEARISH = 1.3     # 持仓 PCR 偏高（Put 多）→ 偏空

# v2.11.68: Pain 斜率算法（复用 skill pta-pain-slope-indicator）
# ±5 邻域（500 点窗口）算 MP 两侧平均斜率
SLOPE_WINDOW = 5
# 9 象限业务阈值（按 ratio）
SLOPE_REGIME_THRESHOLDS = [
    (2.5, '强不对称'),
    (1.5, '一边主导'),
    (1.2, '略不对称'),
    (0.0, '对称'),
]
# 整点 7 槽（与 web_app_integrated.py 同步）
INTRADAY_SLOT_HOURS = {10, 11, 14, 15, 21, 22, 23}


# ============================================================
# 数据源
# ============================================================
def fetch_iv_smile_data(base_url: str = 'http://47.100.97.88', use_proxy: bool = True) -> Dict:
    import urllib.request
    proxy = 'http://127.0.0.1:7890' if use_proxy else None
    proxy_handler = urllib.request.ProxyHandler({'http': proxy, 'https': proxy}) if proxy else urllib.request.ProxyHandler()
    opener = urllib.request.build_opener(proxy_handler)
    opener.addheaders = [('User-Agent', 'judge_state.py/2.0')]

    endpoints = ['status', 'alert_data', 'curve', 'gex']
    result = {}
    for ep in endpoints:
        url = f'{base_url}/api/iv_smile/{ep}'
        try:
            with opener.open(url, timeout=10) as resp:
                result[ep] = json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            print(f'⚠️ /api/iv_smile/{ep} 拉取失败: {e}', file=sys.stderr)
            result[ep] = None
    return result


# ============================================================
# Helper: 从 alert_data.rows 算 PCR
# ============================================================
def compute_pcr_from_rows(rows: list) -> Tuple[float, float]:
    """从 rows 算成交 PCR + 持仓 PCR（按 skill 2.4 / 2.3.2 用）"""
    if not rows:
        return 0.0, 0.0
    vol_call = sum((r.get('vol_call') or 0) for r in rows)
    vol_put = sum((r.get('vol_put') or 0) for r in rows)
    pos_call = sum((r.get('oi_call') or 0) for r in rows)
    pos_put = sum((r.get('oi_put') or 0) for r in rows)
    vol_pcr = (vol_put / vol_call) if vol_call else 0
    pos_pcr = (pos_put / pos_call) if pos_call else 0
    return vol_pcr, pos_pcr


# ============================================================
# v2.11.68: Pain 斜率算法（复用 skill pta-pain-slope-indicator）
# ============================================================
def compute_pain_slope(pain_curve: list, mp_strike: float) -> Dict:
    """从 pain_curve 算 MP 两侧 ±5 邻域斜率 + 业务 regime

    Args:
        pain_curve: [{'pain': float, 'strike': float}, ...]
        mp_strike: Max Pain 行权价

    Returns:
        {
            'slope_down': 看跌阻力（Put 端）斜率,
            'slope_up':   看涨阻力（Call 端）斜率,
            'slope_ratio': max/min 比值,
            'slope_regime': '强不对称'|'一边主导'|'略不对称'|'对称'|'unknown'
        }
    """
    if not pain_curve or mp_strike is None or mp_strike <= 0:
        return {'slope_down': 0, 'slope_up': 0, 'slope_ratio': 0, 'slope_regime': 'unknown'}

    sorted_pts = sorted(pain_curve, key=lambda p: float(p['strike']))
    if len(sorted_pts) < 2:
        return {'slope_down': 0, 'slope_up': 0, 'slope_ratio': 0, 'slope_regime': 'unknown'}

    # 找 MP 索引
    mp_idx = 0
    min_dist = float('inf')
    for i, p in enumerate(sorted_pts):
        d = abs(float(p['strike']) - float(mp_strike))
        if d < min_dist:
            min_dist = d
            mp_idx = i

    def slope_one_side(side: int, window: int = SLOPE_WINDOW) -> float:
        if side < 0:
            # 左侧：MP 之前的 ±window 邻域（不含 MP）
            start = max(0, mp_idx - window)
            end = mp_idx - 1  # 排除 MP 自身
        else:
            # 右侧：MP 之后的 ±window 邻域（不含 MP）
            start = mp_idx + 1  # 排除 MP 自身
            end = min(len(sorted_pts) - 1, mp_idx + window)
        if end < start:
            return 0
        pts = sorted_pts[start:end + 1]
        if len(pts) < 2:
            return 0
        span = float(pts[-1]['strike']) - float(pts[0]['strike'])
        if span <= 0:
            return 0
        return (float(pts[-1]['pain']) - float(pts[0]['pain'])) / span

    slope_down = slope_one_side(-1)  # 看跌阻力
    slope_up   = slope_one_side(+1)  # 看涨阻力
    abs_d = abs(slope_down)
    abs_u = abs(slope_up)
    if min(abs_d, abs_u) > 0:
        ratio = max(abs_d, abs_u) / min(abs_d, abs_u)
    else:
        ratio = 0
    # 9 象限阈值查表
    regime = '对称'
    for th, label in SLOPE_REGIME_THRESHOLDS:
        if ratio >= th:
            regime = label
            break
    return {
        'slope_down': round(slope_down, 2),
        'slope_up':   round(slope_up, 2),
        'slope_ratio': round(ratio, 3),
        'slope_regime': regime,
    }


# ============================================================
# v2.11.68: 整点 / 日间动态对比辅助
# ============================================================
def _get_intraday_slot_pair(intraday_slots: Optional[list], hours: int = 1) -> Tuple[Optional[Dict], Optional[Dict]]:
    """从 intraday_slots 找当前和 N 小时前的 slot

    Returns:
        (slot_now, slot_N_hours_ago) — 任意一个为空就返回 (None, None)
    """
    if not intraday_slots or len(intraday_slots) < 2:
        return None, None
    slot_now = intraday_slots[-1]
    if not slot_now.get('ts'):
        return None, None
    try:
        now_ts = datetime.fromisoformat(slot_now['ts'])
    except (ValueError, TypeError):
        return None, None
    target_h = (now_ts.hour - hours) % 24
    target_date = now_ts.date() if now_ts.hour >= hours else now_ts.date()  # 同日兜底
    for s in intraday_slots:
        if not s.get('ts'):
            continue
        try:
            s_ts = datetime.fromisoformat(s['ts'])
        except (ValueError, TypeError):
            continue
        if s_ts.hour == target_h and s_ts.date() == target_date:
            return slot_now, s
    return slot_now, intraday_slots[0]  # fallback: 用最早一条


def _build_intraday_change(slot_old: Optional[Dict], slot_new: Optional[Dict], layer: str = 'L1') -> Optional[Dict]:
    """构造 1h 变化 dict（vs 上次整点）"""
    if not slot_old or not slot_new:
        return None
    F_old = float(slot_old.get('F') or 0)
    F_new = float(slot_new.get('F') or 0)
    mp_old = float(slot_old.get('max_pain') or 0)
    mp_new = float(slot_new.get('max_pain') or 0)
    gex_old = float(slot_old.get('net_gex') or 0)
    gex_new = float(slot_new.get('net_gex') or 0)
    flip_old = float(slot_old.get('gex_flip') or 0)
    flip_new = float(slot_new.get('gex_flip') or 0)
    sr_old = float(slot_old.get('slope_ratio') or 0)
    sr_new = float(slot_new.get('slope_ratio') or 0)
    reg_old = slot_old.get('slope_regime', '')
    reg_new = slot_new.get('slope_regime', '')

    return {
        'slot_now': slot_new.get('slot'),
        'slot_1h_ago': slot_old.get('slot'),
        'F_change': round(F_new - F_old, 1),
        'max_pain_change': round(mp_new - mp_old, 1),
        'net_gex_change': round(gex_new - gex_old, 2),
        'gex_flip_change': round(flip_new - flip_old, 1),
        'slope_ratio_change': round(sr_new - sr_old, 3),
        'slope_regime_change': (reg_old != reg_new and bool(reg_old) and bool(reg_new)),
        'layer': layer,
    }


def _build_daily_change(prev_summary: Optional[Dict], cur_summary: Optional[Dict], layer: str = 'L1') -> Optional[Dict]:
    """构造 vs 昨日 15:00 变化 dict"""
    if not prev_summary or not cur_summary:
        return None
    mp_old = float(prev_summary.get('max_pain') or 0)
    mp_new = float(cur_summary.get('max_pain') or 0)
    flip_old = float(prev_summary.get('gex_flip') or 0)
    flip_new = float(cur_summary.get('gex_flip') or 0)
    gex_old = float(prev_summary.get('net_gex') or 0)
    gex_new = float(cur_summary.get('net_gex') or 0)
    sr_old = float(prev_summary.get('slope_ratio') or 0)
    sr_new = float(cur_summary.get('slope_ratio') or 0)
    reg_old = prev_summary.get('slope_regime', '')
    reg_new = cur_summary.get('slope_regime', '')

    return {
        'max_pain_migration': round(mp_new - mp_old, 1),
        'gex_flip_migration': round(flip_new - flip_old, 1),
        'net_gex_change': round(gex_new - gex_old, 2),
        'net_gex_change_pct': round(((gex_new - gex_old) / abs(gex_old) * 100) if gex_old else 0, 2),
        'slope_ratio_change': round(sr_new - sr_old, 3),
        'slope_regime_change': (reg_old != reg_new and bool(reg_old) and bool(reg_new)),
        'slope_regime_prev': reg_old or '--',
        'slope_regime_now':  reg_new or '--',
        'layer': layer,
    }


# ============================================================
# 第一层：PAIN 结构层（35%）
# ============================================================
def judge_layer1_pain_structure(gex: Dict, alert_data: Dict,
                                intraday_slots: list = None) -> Dict:
    """第一层：PAIN 结构（4 维：形态 + 位置 + GEX + PCR）

    v2.11.68:
      - shape 计算改用 pain_curve + ±5 邻域（复用 skill pta-pain-slope-indicator）
      - 加 4 斜率字段（slope_down/up/ratio/regime）+ prev 4 字段
      - 加 intraday_change（1h 变化）和 daily_change（vs 昨日 15:00）

    评分映射（按 skill 1.1/1.2 业务语义 "高/中/弱"）：
      强多 = +0.6
      中多 = +0.3
      弱多 = +0.1
      中性 = 0
      弱空 = -0.1
      中空 = -0.3
      强空 = -0.6
    """
    summary = gex.get('summary', {}) or {}
    prev_summary = gex.get('prev_summary', {}) or {}

    max_pain = summary.get('max_pain') or 0
    futures_price = summary.get('futures_price') or 0
    gex_flip = summary.get('gex_flip') or 0
    net_gex = summary.get('net_gex') or 0

    # P0.3 fix: 从 rows 算真实 OI（不再 fallback gex.oi_dist）
    rows = (alert_data or {}).get('rows', []) or []
    call_oi = sum((r.get('oi_call') or 0) for r in rows)
    put_oi = sum((r.get('oi_put') or 0) for r in rows)

    # P0.2 fix: PCR 维度（持仓 + 成交）
    pos_pcr, vol_pcr = compute_pcr_from_rows(rows)

    # === v2.11.68: 优先用现成 _judge_shape 兜底（保留向后兼容）===
    shape_legacy = _judge_shape(call_oi, put_oi)
    # === v2.11.68: 用 pain_curve 算 slope regime 作为新的 shape ===
    pain_curve = gex.get('pain_curve') or []
    slope_info = compute_pain_slope(pain_curve, max_pain)
    slope_down_now  = slope_info['slope_down']
    slope_up_now    = slope_info['slope_up']
    slope_ratio_now = slope_info['slope_ratio']
    slope_regime_now = slope_info['slope_regime']
    # 映射 slope regime → 业务 shape（与 iv_smile.html 的 9 象限 labelMap 一致）
    if slope_regime_now in ('强不对称', '一边主导', '略不对称'):
        # 一边陡：slope_down > slope_up 视为 leftSteep（看跌阻力大）
        if abs(slope_down_now) > abs(slope_up_now):
            shape = 'leftSteep'
        else:
            shape = 'rightSteep'
    else:
        # 对称 / unknown → 兜底用现成 gdr shape
        shape = shape_legacy

    position = _judge_position(futures_price, max_pain)
    gex_dir = 'positive' if net_gex > 0 else ('negative' if net_gex < 0 else 'unknown')

    if gex_flip and futures_price:
        diff = futures_price - gex_flip
        p_vs_flip = 'above' if diff > 5 else ('below' if diff < -5 else 'at')
    else:
        p_vs_flip = 'unknown'

    # === v2.11.68: prev 4 斜率字段（从 gex.prev_summary 取）===
    slope_down_prev   = float(prev_summary.get('slope_down') or 0)
    slope_up_prev     = float(prev_summary.get('slope_up') or 0)
    slope_ratio_prev  = float(prev_summary.get('slope_ratio') or 0)
    slope_regime_prev = prev_summary.get('slope_regime') or 'unknown'

    # === v2.11.68: 1h 变化（vs 上次整点）===
    slot_now, slot_1h_ago = _get_intraday_slot_pair(intraday_slots, hours=1)
    intraday_change = _build_intraday_change(slot_1h_ago, slot_now, layer='L1')

    # === v2.11.68: daily_change（vs 昨日 15:00）===
    # 把当前 4 斜率字段临时塞到 summary 副本里给 _build_daily_change 用
    cur_for_daily = dict(summary)
    cur_for_daily['slope_down']  = slope_down_now
    cur_for_daily['slope_up']    = slope_up_now
    cur_for_daily['slope_ratio'] = slope_ratio_now
    cur_for_daily['slope_regime'] = slope_regime_now
    prev_for_daily = prev_summary  # 已经是 4 斜率字段
    daily_change = _build_daily_change(prev_for_daily, cur_for_daily, layer='L1')

    # skill 1.1/1.2 + 1.3 业务查表
    matrix_meaning = _query_pain_matrix(shape, position, gex_dir, p_vs_flip)

    # 评分（按 skill 业务强度）
    # P0.4 fix: 用标准 0.6/0.3/0.1
    score = 0
    score_detail = ''

    if shape == 'rightSteep' and position == 'belowMP':
        if gex_dir == 'negative':
            score = SCORE_WEAK
            score_detail = '空头衰竭+反弹燃料（弱多）'
        elif gex_dir == 'positive':
            score = SCORE_STRONG
            score_detail = '底部反转确立+正GEX稳定（强多）'
    elif shape == 'rightSteep' and position == 'aboveMP':
        if gex_dir == 'negative':
            score = -SCORE_MEDIUM
            score_detail = '高位急跌+负GEX加速下行（中空）'
        elif gex_dir == 'positive':
            score = SCORE_MEDIUM
            score_detail = '强多头+正GEX保护（中多）'
    elif shape == 'leftSteep' and position == 'belowMP':
        if gex_dir == 'negative':
            score = -SCORE_STRONG
            score_detail = '强空头+负GEX放大（强空）'
        elif gex_dir == 'positive':
            score = SCORE_MEDIUM
            score_detail = '恐慌出清+正GEX抑制底部（中多）'
    elif shape == 'leftSteep' and position == 'aboveMP':
        if gex_dir == 'negative':
            score = -SCORE_MEDIUM
            score_detail = '假突破后加速回归（中空）'
        elif gex_dir == 'positive':
            score = -SCORE_WEAK
            score_detail = '多空博弈+左侧埋伏（弱空）'
    elif shape == 'sym':
        score = 0
        score_detail = 'pin risk / 低波动收敛（中性）'

    # P0.2 fix: PCR 维度加成
    pcr_modifier = 0
    pcr_meaning = ''
    if pos_pcr > 0:
        if pos_pcr > PCR_BEARISH:
            pcr_modifier = -0.1
            pcr_meaning = f'持仓PCR={pos_pcr:.2f} 偏高（Put 持仓占比大）→ 略偏空'
        elif pos_pcr < PCR_BULLISH:
            pcr_modifier = +0.1
            pcr_meaning = f'持仓PCR={pos_pcr:.2f} 偏低（Call 持仓占比大）→ 略偏多'
        else:
            pcr_meaning = f'持仓PCR={pos_pcr:.2f} 平衡'

    score = max(-1, min(1, score + pcr_modifier))  # 限幅 [-1, 1]

    return {
        'layer': 1,
        'layer_name': 'PAIN 结构',
        'weight': 0.35,
        'shape': shape,
        'position': position,
        'gex_dir': gex_dir,
        'p_vs_flip': p_vs_flip,
        'max_pain': max_pain,
        'futures_price': futures_price,
        'gex_flip': gex_flip,
        'pos_pcr': pos_pcr,
        'vol_pcr': vol_pcr,
        'matrix_meaning': matrix_meaning,
        'pcr_meaning': pcr_meaning,
        'pcr_modifier': pcr_modifier,
        'score_detail': score_detail,
        'layer_score': score,
        # === v2.11.68 新增 4 斜率字段（now/prev）===
        'slope_down_now': slope_down_now,
        'slope_up_now':   slope_up_now,
        'slope_ratio_now': slope_ratio_now,
        'slope_regime_now': slope_regime_now,
        'slope_down_prev': slope_down_prev,
        'slope_up_prev':   slope_up_prev,
        'slope_ratio_prev': slope_ratio_prev,
        'slope_regime_prev': slope_regime_prev,
        # === v2.11.68 新增 1h + daily 变化 ===
        'intraday_change': intraday_change,
        'daily_change': daily_change,
        # === v2.11.68 透传 summary/prev_summary 给下游 ===
        'summary': summary,
        'prev_summary': prev_summary,
        'logic_brief': f'{shape} + {position} + GEX {gex_dir} + P vs Flip {p_vs_flip} → {score_detail}'
    }


def _query_pain_matrix(shape: str, position: str, gex_dir: str, p_vs_flip: str) -> str:
    """查 skill 1.1/1.2/1.3 矩阵返回业务含义（原文 1:1 复制）"""
    if shape == 'rightSteep' and position == 'belowMP':
        if gex_dir == 'negative':  return '空头衰竭中，反弹燃料在蓄积，负GEX延缓筑底'
        if gex_dir == 'positive':  return '底部反转确立，右侧加速器待触发，正GEX稳定反弹节奏'
    if shape == 'rightSteep' and position == 'aboveMP':
        if gex_dir == 'negative':  return '高位急跌，负GEX加速下行，一旦跌破MP则更猛烈'
        if gex_dir == 'positive':  return '强多头，上涨自我强化（右侧加速器激活），正GEX提供稳定保护'
    if shape == 'leftSteep' and position == 'belowMP':
        if gex_dir == 'negative':  return '强空头，下跌自我强化（左侧加速器激活），GEX负放大跌幅，接近情绪极值'
        if gex_dir == 'positive':  return '恐慌真实但跌幅被正GEX抑制，底部信号强，等待恐慌出清即可反转'
    if shape == 'leftSteep' and position == 'aboveMP':
        if gex_dir == 'negative':  return '假突破后加速回归，负GEX放大跌幅，一旦跌破MP下行加速'
        if gex_dir == 'positive':  return '多空激烈博弈，左侧Put OI集中（左侧加速器埋伏）一旦价格向MP回归即触发下跌加速'
    if shape == 'sym':             return 'pin risk / 低波动收敛（价格被钉在MP附近）'
    return 'unknown matrix state'


# ============================================================
# 第二层：GEX 机制层（25%）
# ============================================================
def judge_layer2_gex(layer1: Dict, intraday_slots: list = None) -> Dict:
    """第二层：GEX 机制（按 skill 2.2 GEX × P-Flip 矩阵）

    v2.11.68:
      - 加 net_gex now/prev/change + gex_flip now/prev/migration
      - 加 intraday_change（1h 变化）和 daily_change（vs 昨日 15:00）

    评分：与第一层同步（0.6/0.3/0.1）
    """
    gex_dir = layer1['gex_dir']
    p_vs_flip = layer1['p_vs_flip']
    summary = layer1.get('summary', {}) or {}
    prev_summary = layer1.get('prev_summary', {}) or {}

    # === v2.11.68: net_gex 数值 + 变化 ===
    net_gex_now  = float(summary.get('net_gex') or 0)
    net_gex_prev = float(prev_summary.get('net_gex') or 0)
    net_gex_change = net_gex_now - net_gex_prev
    net_gex_change_pct = ((net_gex_change / abs(net_gex_prev)) * 100) if net_gex_prev else 0.0

    # === v2.11.68: gex_flip 迁移 ===
    gex_flip_now  = float(summary.get('gex_flip') or 0)
    gex_flip_prev = float(prev_summary.get('gex_flip') or 0)
    gex_flip_migration = gex_flip_now - gex_flip_prev

    # === v2.11.68: 1h 变化 ===
    slot_now, slot_1h_ago = _get_intraday_slot_pair(intraday_slots, hours=1)
    intraday_change = _build_intraday_change(slot_1h_ago, slot_now, layer='L2')

    # === v2.11.68: daily_change ===
    daily_change = _build_daily_change(prev_summary, summary, layer='L2')

    if gex_dir == 'negative' and p_vs_flip == 'below':
        meaning = '负GEX + P在Flip下方 → 卖方对冲压力放大波动，下方无支撑'
        score = -SCORE_STRONG
        score_detail = '强空机制（负GEX放大下跌）'
    elif gex_dir == 'negative' and p_vs_flip == 'above':
        meaning = '负GEX + P在Flip上方 → 卖方对冲买压释放（涨幅被放大，但也有回调风险）'
        score = -SCORE_WEAK
        score_detail = '弱空机制（涨幅放大但有支撑）'
    elif gex_dir == 'negative' and p_vs_flip == 'at':
        meaning = '负GEX + P接近Flip → 波动机制即将切换（最危险拐点）'
        score = -SCORE_MEDIUM
        score_detail = '中空机制（拐点）'
    elif gex_dir == 'positive' and p_vs_flip == 'above':
        meaning = '正GEX + P在Flip上方 → 卖方净正Gamma抑制波动，托底'
        score = SCORE_MEDIUM
        score_detail = '中多机制（正GEX托底）'
    elif gex_dir == 'positive' and p_vs_flip == 'below':
        meaning = '正GEX + P在Flip下方 → 抑制减弱，下方支撑弱化'
        score = 0
        score_detail = '中性机制（抑制减弱）'
    elif gex_dir == 'positive' and p_vs_flip == 'at':
        meaning = '正GEX + P接近Flip → 即将切换到放大机制'
        score = -SCORE_WEAK
        score_detail = '弱空机制（即将切换）'
    else:
        meaning = 'unknown GEX state'
        score = 0
        score_detail = '未知状态'

    # === v2.11.68: net_gex 变化附加业务解读到 score_detail ===
    # 业务语义：负 GEX 越深 = 越恶化（卖方对冲压力越大）
    if net_gex_prev != 0 and abs(net_gex_change) > 1e5:  # 变化超过 100K
        # 双向恶化判定：变化方向与"更负/更正"对应
        if net_gex_change < 0 and net_gex_now < 0:
            # GEX 变得更负 → 恶化
            score_detail += f' | 净GEX 恶化 {net_gex_change/1e6:+.1f}M'
        elif net_gex_change > 0 and net_gex_now < 0:
            # 仍负但绝对值缩小 → 改善
            score_detail += f' | 净GEX 改善 {net_gex_change/1e6:+.1f}M'
        elif net_gex_change > 0 and net_gex_now > 0:
            # 转向正 GEX → 改善
            score_detail += f' | 净GEX 转正 {net_gex_change/1e6:+.1f}M'

    return {
        'layer': 2,
        'layer_name': 'GEX 机制',
        'weight': 0.25,
        'gex_dir': gex_dir,
        'p_vs_flip': p_vs_flip,
        'matrix_meaning': meaning,
        'score_detail': score_detail,
        'layer_score': score,
        # === v2.11.68 新增 net_gex 数值 + 变化 ===
        'net_gex_now': net_gex_now,
        'net_gex_prev': net_gex_prev,
        'net_gex_change': round(net_gex_change, 2),
        'net_gex_change_pct': round(net_gex_change_pct, 2),
        # === v2.11.68 新增 gex_flip 迁移 ===
        'gex_flip_now': gex_flip_now,
        'gex_flip_prev': gex_flip_prev,
        'gex_flip_migration': round(gex_flip_migration, 1),
        # === v2.11.68 新增 1h + daily 变化 ===
        'intraday_change': intraday_change,
        'daily_change': daily_change,
        'logic_brief': f'GEX {gex_dir} + P {p_vs_flip} Flip + 净GEX {net_gex_now/1e6:+.1f}M → {score_detail}'
    }


# ============================================================
# 第三层：资金意图层（25%）
# ============================================================
def judge_layer3_funding_intent(alert_data: Dict, gex: Dict, layer1: Dict,
                                intraday_slots: list = None) -> Dict:
    """第三层：资金意图（用现成 _compute_nature_and_synthesis）

    v2.11.68:
      - B 方案：输出 standardized_label + 1h PCR delta + detail_section_ref 标记
        （避免与段 3 性质判定×合成信号重复；前端读 detail_section_ref 跳段 3 链接）

    评分映射（PUT_DIR/CALL_DIR）:
      spec_buy 看多/看空 = ±0.5
      close_push 平仓加速 = ±0.5
      hedge_buy 套保买保 = 0（中性，软底/软顶效应）
      hedge_sell 套保卖权 = 0（中性，收租）
      double_exit 双边撤退 = 0
      mixed_neutral 混合中性 = 0
    """
    rows = (alert_data or {}).get('rows', []) or []

    # 直接用 rows 作为 iv_table_rows（不再 fallback gex.oi_dist）
    iv_table_rows = []
    for r in rows:
        iv_table_rows.append({
            'strike': r['strike'],
            'oi_call': r.get('oi_call', 0) or 0,
            'oi_put': r.get('oi_put', 0) or 0,
            'iv_call': r.get('iv_call'),
            'iv_put': r.get('iv_put'),
            'oi_call_prev': r.get('oi_call_prev', 0) or 0,
            'oi_put_prev': r.get('oi_put_prev', 0) or 0,
            'iv_call_prev': r.get('iv_call_prev'),
            'iv_put_prev': r.get('iv_put_prev'),
        })

    if not iv_table_rows:
        return {
            'layer': 3, 'layer_name': '资金意图', 'weight': 0.25,
            'available': False, 'note': 'iv_table_rows 为空',
            'layer_score': 0,
            'detail_section_ref': 'section_3',  # v2.11.68 B 方案
            'pcr_delta_1h': 0, 'slot_now': None, 'slot_1h_ago': None,
        }

    summary = gex.get('summary', {}) or {}
    prev_summary = gex.get('prev_summary', {}) or {}

    # ATM：找离 F 最近的 strike
    futures_price = summary.get('futures_price', 0) or 0
    if futures_price and iv_table_rows:
        atm_strike = min(iv_table_rows, key=lambda r: abs(r['strike'] - futures_price))['strike']
    else:
        atm_strike = 0

    # PCR 计算
    pcr_call_oi = sum((r.get('oi_call') or 0) for r in iv_table_rows)
    pcr_put_oi = sum((r.get('oi_put') or 0) for r in iv_table_rows)
    pcr_now = (pcr_put_oi / pcr_call_oi) if pcr_call_oi else 0
    pcr_prev_oi_call = sum((r.get('oi_call_prev') or 0) for r in iv_table_rows)
    pcr_prev_oi_put = sum((r.get('oi_put_prev') or 0) for r in iv_table_rows)
    pcr_prev = (pcr_prev_oi_put / pcr_prev_oi_call) if pcr_prev_oi_call else 0

    # === v2.11.68: 1h PCR delta（vs 上次整点的 PCR 槽）===
    slot_now, slot_1h_ago = _get_intraday_slot_pair(intraday_slots, hours=1)
    pcr_delta_1h = 0.0
    slot_1h_label = None
    slot_now_label = None
    if slot_now and slot_1h_ago:
        slot_now_label = slot_now.get('slot')
        slot_1h_label = slot_1h_ago.get('slot')
        # intraday_slots 里没存 pcr（只存 net_gex/mp/flip/slope*）—— 用 prev_summary 兜底
        # 真实 1h PCR delta 需要 alert_data 自身在每整点留底 —— v2.11.69 后续补
        # 当前用 pcr_delta（vs 昨日）作为兜底动态显示
        pcr_delta_1h = pcr_now - pcr_prev

    try:
        nature_result = _compute_nature_and_synthesis(
            iv_table_rows=iv_table_rows,
            atm_strike=atm_strike,
            max_pain=summary.get('max_pain', 0) or 0,
            futures_price=futures_price,
            pcr_now=pcr_now,
            pcr_call_oi=pcr_call_oi,
            pcr_put_oi=pcr_put_oi,
        )
    except Exception as e:
        return {
            'layer': 3, 'layer_name': '资金意图', 'weight': 0.25,
            'available': False, 'note': f'_compute_nature_and_synthesis 失败: {e}',
            'layer_score': 0,
            'detail_section_ref': 'section_3',  # v2.11.68 B 方案
            'pcr_delta_1h': 0, 'slot_now': None, 'slot_1h_ago': None,
        }

    put_nature = nature_result.get('put', {}).get('nature', 'unknown')
    call_nature = nature_result.get('call', {}).get('nature', 'unknown')
    synthesis = nature_result.get('synthesis', {}) or {}
    raw_label = synthesis.get('label', 'unknown')
    raw_intensity = synthesis.get('intensity', '')
    strike_modifier = synthesis.get('strike_modifier', '')

    # P0 fix: label 标准化（按 skill v2.11.63a 第三层合成信号表 + v2.11.63d 修订）
    # 关键：Put 端 hedge_sell（收租中性）+ Call 端 spec_buy（看多）= skill 示例 2 明确说"多空分歧 → 观望"
    # 但 _synthesize_signal 内部会判为"单边看多"。需要修正
    standardized_label, standardized_intensity = label_standardize(
        put_nature, call_nature, strike_modifier, pcr_now, pcr_prev
    )

    # 业务查表评分
    PUT_DIR = {
        'spec_buy': -0.5, 'close_push': -0.5,         # 看空/加速
        'hedge_buy': 0, 'hedge_sell': 0,
        'double_exit': 0, 'mixed_neutral': 0,
    }
    CALL_DIR = {
        'spec_buy': +0.5, 'close_push': +0.5,         # 看多/加速
        'hedge_buy': 0, 'hedge_sell': 0,
        'double_exit': 0, 'mixed_neutral': 0,
    }
    p_score = PUT_DIR.get(put_nature, 0)
    c_score = CALL_DIR.get(call_nature, 0)

    # strike 修正项加成
    strike_score = 0
    if strike_modifier:
        if '慢牛' in strike_modifier and '慢熊' not in strike_modifier:
            strike_score = +0.3
        elif '慢熊' in strike_modifier and '慢牛' not in strike_modifier:
            strike_score = -0.3
        # 多空分化 strike_score = 0（中性）

    layer_score = (p_score + c_score + strike_score) / 2  # 归一化到 [-0.5, +0.5]

    return {
        'layer': 3,
        'layer_name': '资金意图',
        'weight': 0.25,
        'available': True,
        'put_nature': put_nature,
        'put_nature_label': nature_result.get('put', {}).get('nature_label', ''),
        'put_business_meaning': nature_result.get('put', {}).get('business_meaning', ''),
        'call_nature': call_nature,
        'call_nature_label': nature_result.get('call', {}).get('nature_label', ''),
        'call_business_meaning': nature_result.get('call', {}).get('business_meaning', ''),
        'raw_label': raw_label,
        'raw_intensity': raw_intensity,
        'standardized_label': standardized_label,
        'standardized_intensity': standardized_intensity,
        'strike_modifier': strike_modifier,
        'pcr_now': pcr_now,
        'pcr_prev': pcr_prev,
        'pcr_delta': (pcr_now - pcr_prev) if pcr_now and pcr_prev else 0,
        'pcr_label': synthesis.get('pcr_label', ''),
        'pcr_meaning': synthesis.get('pcr_meaning', ''),
        'call_role_summary': (nature_result.get('call_role') or {}).get('role_summary', ''),
        'put_role_summary': (nature_result.get('put_role') or {}).get('role_summary', ''),
        # v2.11.68 A1 方案：透传完整 call_role/put_role dict（不只是 summary 字符串）
        # 供前端 L3 展开时渲染 24 行 strike 表格
        'call_role': nature_result.get('call_role', {}) or {},
        'put_role': nature_result.get('put_role', {}) or {},
        'data_quality': nature_result.get('data_quality'),
        'shape': nature_result.get('shape'),
        'shape_label': nature_result.get('shape_label'),
        'position': nature_result.get('position'),
        'position_label': nature_result.get('position_label'),
        'layer_score': layer_score,
        # === v2.11.68 B 方案：1h PCR delta + 跳段 3 链接标记 ===
        'pcr_delta_1h': round(pcr_delta_1h, 4),
        'slot_now': slot_now_label,
        'slot_1h_ago': slot_1h_label,
        'detail_section_ref': 'section_3',  # 段 3 性质判定×合成信号
        'logic_brief': f'Put {put_nature} + Call {call_nature} → {standardized_label}'
    }


def label_standardize(put_nature: str, call_nature: str, strike_modifier: str,
                      pcr_now: float, pcr_prev: float) -> Tuple[str, str]:
    """P0 fix: 按 skill v2.11.63a 第三层合成信号表 + v2.11.63d 修订 把现成函数 label 标准化

    skill 第三层合成信号表（line 526-532）:
      Put 性质 | Call 性质 | 合成信号        | 信号强度
      同向加强   | 同向加强   | 信号共振        | 强
      同向       | 中性      | 单边信号        | 中
      中性       | 同向      | 单边信号        | 中
      反向       | 反向      | 信号矛盾        | 观望
      一边明确   | 另一边反向 | 信号冲突        | 观望

    v2.11.63a 示例 2 关键: Put 套保卖权 + Call 投机买权 = "多空分歧 → 观望"
    （不是"单边看多"！）

    v2.11.63d 修订: 双侧中性 + strike 修正 → 中性偏慢牛/慢熊/多空分化
    """
    # 业务方向映射
    PUT_DIR = {
        'spec_buy': '看空', 'close_push': '看空',
        'hedge_buy': '中性', 'hedge_sell': '中性',
        'double_exit': '中性', 'mixed_neutral': '中性',
    }
    CALL_DIR = {
        'spec_buy': '看多', 'close_push': '看多',
        'hedge_buy': '中性', 'hedge_sell': '中性',
        'double_exit': '中性', 'mixed_neutral': '中性',
    }
    p_dir = PUT_DIR.get(put_nature, 'unknown')
    c_dir = CALL_DIR.get(call_nature, 'unknown')

    # P1 fix: PCR 恐慌出清信号（必须在双侧中性判定之前，否则被提前 return）
    # 阈值放宽：prev > 1.5 + now < 1.2 → 恐慌出清（多头）
    #         prev < 0.6 + now > 0.8 → 乐观消退（空头）
    if pcr_prev > 0 and pcr_now > 0:
        if pcr_prev > PCR_FEAR_HIGH and pcr_now < PCR_NEUTRAL_HIGH:
            return '恐慌出清中（多头）', '中'
        if pcr_prev < PCR_FEAR_LOW and pcr_now > PCR_NEUTRAL_LOW:
            return '乐观消退中（空头）', '中'

    # skill 查表
    if p_dir == '看多' and c_dir == '看多':
        return '看多共振', '强'
    if p_dir == '看空' and c_dir == '看空':
        return '看空共振', '强'
    if p_dir == '看空' and c_dir == '看多':
        return '信号矛盾', '观望'
    if p_dir == '看多' and c_dir == '看空':
        return '信号矛盾', '观望'

    # 一边中性 + 一边有方向：skill 表说"单边信号" → "中"
    # 但 skill v2.11.63a 示例 2 明确: Put 中性(hedge_sell) + Call 看多(spec_buy) = **多空分歧**
    # 这里统一用"多空分歧" 标签（比"单边看多"更精确）
    if p_dir == '中性' and c_dir in ('看多', '看空'):
        return '多空分歧（看空方不站队）', '观望'
    if c_dir == '中性' and p_dir in ('看多', '看空'):
        return '多空分歧（看多方不站队）', '观望'

    # 双侧中性
    if p_dir == '中性' and c_dir == '中性':
        if strike_modifier:
            has_bull = '慢牛' in strike_modifier
            has_bear = '慢熊' in strike_modifier
            if has_bull and has_bear:
                return '多空分化(慢牛+慢熊)', '弱'
            if has_bull:
                return '中性偏慢牛', '弱'
            if has_bear:
                return '中性偏慢熊', '弱'
        return '中性', '观望'

    return 'unknown', ''


# ============================================================
# 第四层：情绪确认层（15%）
# ============================================================
def judge_layer4_emotion(curve: Dict, alert_data: Dict, layer1: Dict, gex: Dict,
                         intraday_slots: list = None) -> Dict:
    """第四层：情绪确认（按 skill 2.4 情绪确认表 + P1 修复）

    v2.11.68: 加 trend_1h（vs 1h 前 F，比 daily trend 更敏感）

    新增:
      - 恐慌出清判定（从 prev_pcr > 1.5 回落至 < 1.0 = 多头信号）
      - 趋势用 prev_f（从 gex.prev_summary.futures_price）
    """
    rows = (alert_data or {}).get('rows', []) or []
    vol_pcr, pos_pcr = compute_pcr_from_rows(rows)

    # ATM IV（来自 curve）
    summary = curve or {}
    futures_price = summary.get('futures_price') or layer1.get('futures_price') or 0
    curve_rows = summary.get('curve', []) or []
    atm_iv_call = atm_iv_put = None
    for d in curve_rows:
        if d.get('strike') == summary.get('atm_strike'):
            atm_iv_call = d.get('raw_C') or d.get('iv_call')
            atm_iv_put = d.get('raw_P') or d.get('iv_put')
            break

    # P1 fix: prev_f + prev_pcr
    prev_summary = gex.get('prev_summary', {}) or {}
    prev_f = prev_summary.get('futures_price', 0) or 0
    cur_f = futures_price
    pcr_prev = pos_pcr_prev = 0
    # prev_pcr 从 rows 自算（oi_put_prev / oi_call_prev）
    if rows:
        prev_pos_call = sum((r.get('oi_call_prev') or 0) for r in rows)
        prev_pos_put = sum((r.get('oi_put_prev') or 0) for r in rows)
        pos_pcr_prev = (prev_pos_put / prev_pos_call) if prev_pos_call else 0
        prev_vol_call = sum((r.get('vol_call_prev') or 0) for r in rows)
        prev_vol_put = sum((r.get('vol_put_prev') or 0) for r in rows)
        pcr_prev = (prev_vol_put / prev_vol_call) if prev_vol_call else 0

    # 趋势
    if prev_f and cur_f:
        diff = cur_f - prev_f
        if diff > 5:    trend = 'up'
        elif diff < -5: trend = 'down'
        else:           trend = 'flat'
        trend_diff = diff
    else:
        trend = 'unknown'
        trend_diff = 0

    # === v2.11.68: 1h 趋势（vs 上次整点 F，比 daily trend 更敏感）===
    slot_now, slot_1h_ago = _get_intraday_slot_pair(intraday_slots, hours=1)
    F_1h_ago = float((slot_1h_ago or {}).get('F') or 0)
    if F_1h_ago and cur_f:
        diff_1h = cur_f - F_1h_ago
        if diff_1h > 5:    trend_1h = 'up'
        elif diff_1h < -5: trend_1h = 'down'
        else:              trend_1h = 'flat'
        trend_diff_1h = diff_1h
    else:
        trend_1h = 'unknown'
        trend_diff_1h = 0

    # 信号列表
    signals = []
    score = 0
    score_detail = ''

    # 1. 成交 PCR
    if vol_pcr > 0:
        if vol_pcr > PCR_FEAR_HIGH:
            signals.append(f'成交PCR={vol_pcr:.2f} 持续>1.5（恐慌未消）')
            score += -0.3
            score_detail = '恐慌情绪（强空头）'
        elif vol_pcr < PCR_FEAR_LOW:
            signals.append(f'成交PCR={vol_pcr:.2f} 持续<0.6（过度乐观）')
            score += -0.2
            score_detail = '过度乐观（弱空头）'
        elif PCR_NEUTRAL_LOW <= vol_pcr <= PCR_NEUTRAL_HIGH:
            signals.append(f'成交PCR={vol_pcr:.2f} 中性区间')
            # score 不变
        elif vol_pcr < 1.0:
            signals.append(f'成交PCR={vol_pcr:.2f} 中性偏低')
            score += +0.1
            score_detail = '略偏多'

    # 2. P1 fix: 恐慌出清判定
    if pcr_prev > 0 and vol_pcr > 0:
        if pcr_prev > PCR_FEAR_HIGH and vol_pcr < 1.0:
            signals.append(f'成交PCR 从 {pcr_prev:.2f} 回落至 {vol_pcr:.2f}（恐慌出清）→ 多头')
            score += +0.3
            if not score_detail: score_detail = '恐慌出清（多头信号）'
        elif pcr_prev < PCR_FEAR_LOW and vol_pcr > 0.8:
            signals.append(f'成交PCR 从 {pcr_prev:.2f} 上升至 {vol_pcr:.2f}（乐观消退）→ 空头')
            score += -0.2
            if not score_detail: score_detail = '乐观消退（空头信号）'

    # 3. ATM IV
    if atm_iv_call and atm_iv_put:
        avg_iv = (atm_iv_call + atm_iv_put) / 2
        signals.append(f'ATM 隐波 {avg_iv:.2f}%')

    # 4. 趋势
    if trend == 'up':
        signals.append(f'趋势↑（F {prev_f:.0f} → {cur_f:.0f}，+{trend_diff:.0f}）')
        score += +0.1
    elif trend == 'down':
        signals.append(f'趋势↓（F {prev_f:.0f} → {cur_f:.0f}，{trend_diff:.0f}）')
        score += -0.1
    elif trend == 'flat':
        signals.append('趋势→（横盘）')
    else:
        signals.append('趋势 unknown')

    # 5. v2.11.68: 1h 趋势打分加成（比 daily trend 更敏感，但不重复加分）
    if trend_1h == 'up' and trend != 'up':
        score += +0.1
        if not score_detail: score_detail = '1h趋势↑'
    elif trend_1h == 'down' and trend != 'down':
        score += -0.1
        if not score_detail: score_detail = '1h趋势↓'

    return {
        'layer': 4,
        'layer_name': '情绪确认',
        'weight': 0.15,
        'vol_pcr': vol_pcr,
        'vol_pcr_prev': pcr_prev,
        'pos_pcr': pos_pcr,
        'pos_pcr_prev': pos_pcr_prev,
        'atm_iv_call': atm_iv_call,
        'atm_iv_put': atm_iv_put,
        'trend': trend,
        'trend_diff': trend_diff,
        'prev_f': prev_f,
        'cur_f': cur_f,
        # === v2.11.68 新增 1h 趋势 ===
        'trend_1h': trend_1h,
        'trend_diff_1h': trend_diff_1h,
        'F_1h_ago': F_1h_ago,
        'signals': signals,
        'score_detail': score_detail or '中性',
        'layer_score': max(-1, min(1, score)),
        'logic_brief': ' | '.join(signals[:4]) if signals else 'no emotion signals'
    }


# ============================================================
# 四层加权叠加
# ============================================================
def synthesize_decision(layers: List[Dict]) -> Dict:
    """四层加权叠加 → 综合判断（按 skill 第三部分 + 综合判断规则表）"""
    total_score = sum(l['layer_score'] * l['weight'] for l in layers)
    total_score = round(total_score, 3)

    layer_breakdown = [
        f"{l['layer_name']}={l.get('layer_score', 0):+.2f} (权重 {l['weight']*100:.0f}%)"
        for l in layers
    ]

    # 矛盾检测
    signs = set()
    for l in layers:
        s = l.get('layer_score', 0)
        if s > 0.05: signs.add('+')
        elif s < -0.05: signs.add('-')

    # 综合判断规则
    if len(signs) > 1:
        decision = '观望（四层矛盾）'
        confidence = '低'
    elif total_score >= 0.5:
        decision = '买入'
        confidence = '高'
    elif total_score >= 0.2:
        decision = '轻仓试探'
        confidence = '中'
    elif total_score <= -0.5:
        decision = '观望或做空'
        confidence = '高'
    elif total_score <= -0.2:
        decision = '观望'
        confidence = '中'
    else:
        decision = '观望'
        confidence = '低'

    # 各层逻辑串联
    logic_chain = ' → '.join([
        f"L{l['layer']}({l['layer_name']}) [{l.get('logic_brief', '')}]"
        for l in layers
    ])

    # 总结论（按层次组织）
    summary_lines = [
        f"决策: {decision}（置信度: {confidence}）",
        f"总分: {total_score:+.3f}",
        f"逻辑链: {logic_chain}",
    ]

    return {
        'total_score': total_score,
        'decision': decision,
        'confidence': confidence,
        'layer_breakdown': layer_breakdown,
        'logic_chain': logic_chain,
        'signs': list(signs),
        'contradiction': len(signs) > 1,
        'summary_lines': summary_lines,
    }


# ============================================================
# 报告输出（分层展示 + 总结论）
# ============================================================
def format_report(result: Dict) -> str:
    """分层报告：4 层独立 + 总结论（按用户要求）"""
    L1, L2, L3, L4 = result['layer1'], result['layer2'], result['layer3'], result['layer4']
    final = result['final']

    lines = []
    lines.append('=' * 72)
    lines.append(f'📊 PTA 期权决策报告（v2.11.65）')
    lines.append(f'生成时间: {result["generated_at"]}')
    lines.append(f'合约: {result["contract"]} | 期货价: {result["futures_price"]:.0f} | ATM: {result["atm_strike"]:.0f} | MP: {result["max_pain"]:.0f}')
    if result.get('last_update'):
        lines.append(f'最后更新: {result["last_update"]} | TqSdk: {"✅ 就绪" if result.get("tqsdk_ready") else "⚠️ 未就绪"}')
    lines.append('=' * 72)
    lines.append('')

    # ---- 第一层：PAIN 结构（35%） ----
    lines.append(f'【第一层】PAIN 结构（权重 {L1["weight"]*100:.0f}%）')
    lines.append(f'  维度: 形态={L1["shape"]} | 位置={L1["position"]} | GEX={L1["gex_dir"]} | P vs Flip={L1["p_vs_flip"]}')
    lines.append(f'  业务: {L1["matrix_meaning"]}')
    lines.append(f'  PCR: {L1["pcr_meaning"]}（加成 {L1["pcr_modifier"]:+.1f}）')
    lines.append(f'  评分逻辑: {L1["score_detail"]}')
    lines.append(f'  ➜ 评分: {L1["layer_score"]:+.2f}')
    lines.append('')

    # ---- 第二层：GEX 机制（25%） ----
    lines.append(f'【第二层】GEX 机制（权重 {L2["weight"]*100:.0f}%）')
    lines.append(f'  维度: GEX={L2["gex_dir"]} | P vs Flip={L2["p_vs_flip"]}')
    lines.append(f'  业务: {L2["matrix_meaning"]}')
    lines.append(f'  评分逻辑: {L2["score_detail"]}')
    lines.append(f'  ➜ 评分: {L2["layer_score"]:+.2f}')
    lines.append('')

    # ---- 第三层：资金意图（25%） ----
    lines.append(f'【第三层】资金意图（权重 {L3["weight"]*100:.0f}%）')
    if L3.get('available'):
        lines.append(f'  Put 性质: {L3["put_nature"]} ({L3["put_nature_label"]})')
        lines.append(f'    业务: {L3["put_business_meaning"]}')
        lines.append(f'  Call 性质: {L3["call_nature"]} ({L3["call_nature_label"]})')
        lines.append(f'    业务: {L3["call_business_meaning"]}')
        lines.append(f'  原始 label: {L3["raw_label"]} ({L3["raw_intensity"]})')
        lines.append(f'  ✅ 标准化 label: {L3["standardized_label"]} ({L3["standardized_intensity"]})')
        if L3.get('strike_modifier'):
            lines.append(f'  strike 修正: {L3["strike_modifier"]}')
        if L3.get('call_role_summary'):
            lines.append(f'  Call 角色: {L3["call_role_summary"]}')
        if L3.get('put_role_summary'):
            lines.append(f'  Put 角色: {L3["put_role_summary"]}')
        lines.append(f'  PCR: now={L3["pcr_now"]:.3f} | prev={L3["pcr_prev"]:.3f} | delta={L3["pcr_delta"]:+.3f} ({L3["pcr_label"]})')
        lines.append(f'  数据质量: {L3.get("data_quality")}')
    else:
        lines.append(f'  ⚠️ {L3.get("note", "数据不可用")}')
    lines.append(f'  ➜ 评分: {L3["layer_score"]:+.2f}')
    lines.append('')

    # ---- 第四层：情绪确认（15%） ----
    lines.append(f'【第四层】情绪确认（权重 {L4["weight"]*100:.0f}%）')
    lines.append(f'  成交 PCR: now={L4["vol_pcr"]:.3f} | prev={L4["vol_pcr_prev"]:.3f}')
    lines.append(f'  持仓 PCR: now={L4["pos_pcr"]:.3f} | prev={L4["pos_pcr_prev"]:.3f}')
    if L4["atm_iv_call"]:
        lines.append(f'  ATM 隐波: Call={L4["atm_iv_call"]*100:.2f}% | Put={L4["atm_iv_put"]*100:.2f}%')
    if L4["prev_f"]:
        lines.append(f'  趋势: F {L4["prev_f"]:.0f} → {L4["cur_f"]:.0f} ({L4["trend"]}, {L4["trend_diff"]:+.0f})')
    lines.append(f'  评分逻辑: {L4["score_detail"]}')
    lines.append(f'  ➜ 评分: {L4["layer_score"]:+.2f}')
    lines.append('')

    # ---- 总结论（按用户要求：分层展示 + 总结论） ----
    lines.append('=' * 72)
    lines.append('🎯 综合判断（按权重叠加）')
    lines.append('=' * 72)
    for line in final['summary_lines']:
        lines.append(f'  {line}')
    lines.append('')
    lines.append('📋 各层贡献:')
    for bd in final['layer_breakdown']:
        lines.append(f'  {bd}')
    if final['contradiction']:
        lines.append(f'  ⚠️ 四层信号方向矛盾（{", ".join(final["signs"])}）→ 决策降级为观望')

    lines.append('')
    lines.append('=' * 72)
    return '\n'.join(lines)


# ============================================================
# Main
# ============================================================
def main():
    parser = argparse.ArgumentParser(description='PTA 期权决策脚本（v2.11.65）')
    parser.add_argument('--json', action='store_true', help='输出 JSON')
    parser.add_argument('--base-url', default='http://47.100.97.88', help='iv_smile API base URL')
    parser.add_argument('--no-proxy', action='store_true', help='不用代理（直连 127.0.0.1）')
    args = parser.parse_args()

    print('⏳ 正在拉取 iv_smile 实时数据...', file=sys.stderr)
    data = fetch_iv_smile_data(args.base_url, use_proxy=not args.no_proxy)

    status = data.get('status') or {}
    alert = data.get('alert_data') or {}
    curve = data.get('curve') or {}
    gex = data.get('gex') or {}

    if not status.get('running'):
        print('⚠️ iv_smile 服务未运行！', file=sys.stderr)
        sys.exit(1)
    if not status.get('tqsdk_ready'):
        print('⚠️ TqSdk 尚未就绪，期权数据可能为陈旧缓存', file=sys.stderr)

    contract = status.get('active_contract', '?')
    futures_price = status.get('futures_price', 0) or 0
    atm_strike = status.get('atm_strike', 0) or 0
    max_pain = status.get('max_pain', 0) or (gex.get('summary', {}) or {}).get('max_pain', 0) or 0

    # 四层判定
    L1 = judge_layer1_pain_structure(gex, alert)
    L2 = judge_layer2_gex(L1)
    L3 = judge_layer3_funding_intent(alert, gex, L1)
    L4 = judge_layer4_emotion(curve, alert, L1, gex)

    final = synthesize_decision([L1, L2, L3, L4])

    result = {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'contract': contract,
        'futures_price': futures_price,
        'atm_strike': atm_strike,
        'max_pain': max_pain,
        'last_update': status.get('last_update'),
        'tqsdk_ready': status.get('tqsdk_ready'),
        'layer1': L1,
        'layer2': L2,
        'layer3': L3,
        'layer4': L4,
        'final': final,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(format_report(result))

    return 0


if __name__ == '__main__':
    sys.exit(main())

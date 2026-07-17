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

# ============================================================
# v2.11.84 双门槛常量(飞书文档 / 实战门槛升级)
# ============================================================
# OI ≥ 1000 手:过滤掉深度虚值档的"鬼影仓位",保留真正有大资金进出的 strike
STRIKE_MIN_OI_ABS = 1000
# IV 绝对值 ≥ 5%:PTA 主力 IV 平时 20-35%, 5% 是"显著报价"门槛(<5% 多为报价缺失)
STRIKE_MIN_IV_PCT = 5.0

def _strike_meets_threshold(oi_cur: float, oi_prev: float,
                            iv_cur, iv_prev) -> bool:
    """v2.11.84 双门槛过滤 (飞书文档 2.3.1 表前置过滤层)

    用于 _is_strike_eligible 的"提前过滤":
    1. OI 当前 + 之前 **都** ≥ STRIKE_MIN_OI_ABS (1000 手)
    2. IV 当前 + 之前 都非 None 且都 ≥ STRIKE_MIN_IV_PCT (5%)

    失败者不参与 strike 级别性质判定,UI 显示 "N 个 strike 因不达标未展示"。

    Args:
        oi_cur/oi_prev: 单 strike OI 绝对值(手)
        iv_cur/iv_prev: 单 strike IV 绝对值(%, 如 0.265 表示 26.5%)

    Returns:
        bool: 是否达标
    """
    if (oi_cur or 0) < STRIKE_MIN_OI_ABS or (oi_prev or 0) < STRIKE_MIN_OI_ABS:
        return False
    if iv_cur is None or iv_prev is None:
        return False
    try:
        if float(iv_cur) < STRIKE_MIN_IV_PCT or float(iv_prev) < STRIKE_MIN_IV_PCT:
            return False
    except (TypeError, ValueError):
        return False
    return True

def _compute_strike_weight(strike: float, futures_price: float,
                           oi_change: float,
                           all_changes: List[float]) -> float:
    """v2.11.84 综合权重公式 (飞书文档附录附录)

    Wi = Impacti × Contributioni

    Impacti = e^(-0.08 × |Ki - F|)
        → 平值(GAMMA 集中区)影响力最大,深度虚值/实值趋近 0
        → 实证: 0/50/100/200/300/500 点对应 1.00/0.98/0.96/0.85/0.79/0.67

    Contributioni = |ΔOI_i| / Σ|ΔOI_j|
        → 该 strike OI 变化占该端总变化的比重
        → 用绝对值(不是净变化)避免正负相抵

    Args:
        strike: 行权价
        futures_price: 当前期货价(F)
        oi_change: 该 strike OI 净变化量
        all_changes: 同端所有达标 strike 的 OI 变化量列表

    Returns:
        float: 综合权重 0~1(实际值会 < 1)
    """
    import math
    # 因子 1: 影响力(Gamma 敏感度)
    distance = abs(float(strike) - float(futures_price))
    impact = math.exp(-0.08 * distance)
    # 因子 2: 边际贡献
    abs_total = sum(abs(float(x)) for x in all_changes)
    contribution = abs(float(oi_change)) / abs_total if abs_total > 0 else 0.0
    return impact * contribution

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

# ============================================================
# v2.11.93: 5 档 ladder (飞书原文 ±2/±1.5/±0.5/0)
# ============================================================
LADDER_5GRID = [-2.0, -1.5, -0.5, 0.0, +0.5, +1.5, +2.0]
LADDER_5GRID_LABELS = {
    -2.0: '强偏空', -1.5: '偏空', -0.5: '弱偏空', 0.0: '中性',
    +0.5: '弱偏多', +1.5: '偏多', +2.0: '强偏多',
}


def _ladder_to_5grid(score: float) -> float:
    """v2.11.93: 连续分数 → 5 档 ladder 最近邻
    业务查表 + PCR 修饰可能产生 ±2.5 漂出 ladder, 用最近邻归位
    """
    return min(LADDER_5GRID, key=lambda x: abs(x - score))


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
SLOPE_WINDOW = 5

# ============================================================
# v2.11.90: PAIN 双侧陡独立分支 (飞书附录方案 P1)
# 两侧 slope 绝对值都 > BOTH_STEEP_THRESHOLD 且比值 < both_steep_ratio_max → both_steep=True
# 业务语义: 双侧陡 = 上下阻力都大, 价格双向都"卡住", 趋势性弱
#
# v2.11.95b: both_steep_ratio_max 不再硬编码 1.15, 改用 dyn_th 联动
#   1.15 只是参考基值, 真正的阈值是"baseline + 触发条件"计算后的 dyn_th
#   一旦 dyn_th=1.05 (T<7 触发) → 对称/双侧陡 vs 偏斜的分界 = 1.05
#   一旦 dyn_th=1.08 (IV≥75% 或 OI>10万触发) → 分界 = 1.08
#   文档 L2025-2043 方案 D 案例: 比值 1.10 > 1.08 → leftSteep(略偏空)  ← 分界 1.08
#   bothSteep 跟"略不对称"档互斥:
#     - "略不对称"档: ratio >= dyn_th  → leftSteep/rightSteep
#     - bothSteep:    ratio <  dyn_th  → 真正对称
#   所以 both_steep_ratio_max = dyn_th (1.15 已被 dyn_th 替代)
# ============================================================
BOTH_STEEP_THRESHOLD = 80000  # 两侧 slope |值| 都需 > 此数 (单位: 元/点)


# ============================================================
# v2.11.87: PAIN 形态动态阈值三因子 (飞书附录 2845-2897 方案 D)
# ============================================================
DYN_THRESHOLD_IV_HIGH = 75.0      # IV ≥ 75% 分位 → 高 IV 触发阈值降至 1.08
DYN_THRESHOLD_T_LOW_DAYS = 7.0    # T < 7 天 → 临近到期触发阈值降至 1.05
DYN_THRESHOLD_OI_HIGH = 100000    # OI > 10万手 → 巨量持仓触发阈值降至 1.08
DYN_THRESHOLD_BASE = 1.15         # 默认 baseline (无触发时)
DYN_THRESHOLD_MIN_VALUE = 1.05    # 极端叠加也不能低于 1.05 (防过度优化)


def compute_dynamic_threshold(iv_percentile=None, T_days_remaining=None, oi_total_now=None) -> Dict:
    """飞书附录方案 D：IV/T/OI 三因子各自触发独立判定
       至少两个维度触发 → 取所有触发阈值中的最低值（最敏感）

    Args:
        iv_percentile:   当前 IV 在 HV 区间的分位 (波动率锥端点 /api/options/vol_cone.iv_percentile)
                         None 或 < 75 = 不触发
        T_days_remaining: 距到期剩余天数 (从 summary.days_left / T_days_remaining 取)
                         None 或 >= 7 = 不触发
        oi_total_now:    OI 总规模 (call_oi + put_oi)
                         None 或 <= 10万 = 不触发

    Returns:
        {
            'dyn_threshold': float (1.05~1.15, 最终判定的阈值),
            'triggered':     list[str] (触发的因子名称),
            'all_triggers':  dict (每个因子的触发状态+触发后阈值),
        }
    """
    candidates = [DYN_THRESHOLD_BASE]  # 起点 1.15
    all_triggers = {
        'iv_high': {'triggered': False, 'value': iv_percentile, 'post_th': 1.08},
        't_near':  {'triggered': False, 'value': T_days_remaining, 'post_th': 1.05},
        'oi_huge': {'triggered': False, 'value': oi_total_now, 'post_th': 1.08},
    }

    # IV 维度 (≥ 75 分位)
    if iv_percentile is not None and iv_percentile >= DYN_THRESHOLD_IV_HIGH:
        candidates.append(all_triggers['iv_high']['post_th'])
        all_triggers['iv_high']['triggered'] = True

    # T 维度 (< 7 天)
    if T_days_remaining is not None and 0 <= T_days_remaining < DYN_THRESHOLD_T_LOW_DAYS:
        candidates.append(all_triggers['t_near']['post_th'])
        all_triggers['t_near']['triggered'] = True

    # OI 维度 (> 10 万手)
    if oi_total_now is not None and oi_total_now > DYN_THRESHOLD_OI_HIGH:
        candidates.append(all_triggers['oi_huge']['post_th'])
        all_triggers['oi_huge']['triggered'] = True

    # 取最低（最敏感）
    dyn_th = min(candidates)
    # 但不能低于最小保底值
    dyn_th = max(dyn_th, DYN_THRESHOLD_MIN_VALUE)

    triggered_names = [k for k, v in all_triggers.items() if v['triggered']]

    return {
        'dyn_threshold': round(dyn_th, 3),
        'triggered': triggered_names,
        'all_triggers': all_triggers,
    }
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
def compute_pain_slope(pain_curve: list, mp_strike: float, dyn_th: float = None) -> Dict:
    """从 pain_curve 算 MP 两侧 ±5 邻域斜率 + 业务 regime

    Args:
        pain_curve: [{'pain': float, 'strike': float}, ...]
        mp_strike: Max Pain 行权价
        dyn_th:     v2.11.87 动态阈值（飞书附录方案 D，None 时回退固定 1.2)

    Returns:
        {
            'slope_down': 看跌阻力（Put 端）斜率,
            'slope_up':   看涨阻力（Call 端）斜率,
            'slope_ratio': max/min 比值,
            'slope_regime': '强不对称'|'一边主导'|'略不对称'|'对称'|'unknown',
            'thresholds_used': 使用的阈值表 [(2.5,...), (1.5,...), (dyn_th,...), (0,...)],
        }
    """
    if not pain_curve or mp_strike is None or mp_strike <= 0:
        return {'slope_down': 0, 'slope_up': 0, 'slope_ratio': 0, 'slope_regime': 'unknown',
                'thresholds_used': SLOPE_REGIME_THRESHOLDS}

    sorted_pts = sorted(pain_curve, key=lambda p: float(p['strike']))
    if len(sorted_pts) < 2:
        return {'slope_down': 0, 'slope_up': 0, 'slope_ratio': 0, 'slope_regime': 'unknown',
                'thresholds_used': SLOPE_REGIME_THRESHOLDS}

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

    # === v2.11.87: 动态阈值（飞书附录方案 D）===
    # 如果传了 dyn_th，用 [dyn_th, 1.5, 2.5] 替代固定 [1.2, 1.5, 2.5]
    # dyn_th 默认 None 时回退固定值（向后兼容）
    if dyn_th is not None and dyn_th > 0 and dyn_th < 1.5:
        thresholds = [(2.5, '强不对称'), (1.5, '一边主导'),
                     (dyn_th, '略不对称'), (0.0, '对称')]
        thresholds = sorted(thresholds, key=lambda x: -x[0])  # 降序排列
    else:
        thresholds = SLOPE_REGIME_THRESHOLDS

    # 9 象限阈值查表
    regime = '对称'
    for th, label in thresholds:
        if ratio >= th:
            regime = label
            break

    # === v2.11.90: 双侧陡独立判定 (P1 飞书附录方案) ===
    # 条件: 两侧 |slope| 都 > BOTH_STEEP_THRESHOLD 且比值 < both_steep_ratio_max
    # 业务语义: 上下阻力都大, 价格双向都"卡住", 趋势性弱
    #
    # v2.11.95b: both_steep_ratio_max = dyn_th (1.15 已被 dyn_th 替代, 不再硬编码)
    #   一旦 dyn_th=1.05 (T<7 触发) → 对称/双侧陡 vs 偏斜的分界 = 1.05
    #   一旦 dyn_th=1.08 (IV≥75% 或 OI>10万触发) → 分界 = 1.08
    #   dyn_th=None 时回退到 DYN_THRESHOLD_BASE=1.15 (compute_dynamic_threshold 的 baseline)
    if dyn_th is not None and dyn_th > 0:
        both_steep_ratio_max = dyn_th
    else:
        # 向后兼容: dyn_th 未传入时, 用 DYN_THRESHOLD_BASE 兜底 (跟 compute_dynamic_threshold 一致)
        both_steep_ratio_max = DYN_THRESHOLD_BASE  # 1.15
    both_steep = bool(abs_d > BOTH_STEEP_THRESHOLD
                      and abs_u > BOTH_STEEP_THRESHOLD
                      and 0 < ratio < both_steep_ratio_max)

    return {
        'slope_down': round(slope_down, 2),
        'slope_up':   round(slope_up, 2),
        'slope_ratio': round(ratio, 3),
        'slope_regime': regime,
        'both_steep': both_steep,           # v2.11.90: 双侧陡独立判定
        'thresholds_used': thresholds,
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
        # === v2.11.90 P3: 动态阈值三因子变化 (供 L2/L3/L4 联动) ===
        'iv_pct_change': round(float(slot_new.get('iv_percentile') or 0) - float(slot_old.get('iv_percentile') or 0), 1),
        'oi_total_change': int(float(slot_new.get('oi_total_now') or 0) - float(slot_old.get('oi_total_now') or 0)),
        'T_days_change': round(float(slot_new.get('T_days_remaining') or 0) - float(slot_old.get('T_days_remaining') or 0), 1),
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

    # === v2.11.87: 动态阈值三因子 (从 summary 拿 3 个字段) ===
    iv_pct = summary.get('iv_percentile')
    T_days = summary.get('T_days_remaining')
    oi_total = summary.get('oi_total_now')
    if oi_total is None:
        # 兜底: 用 call_oi + put_oi
        call_oi_sum = summary.get('total_call_oi') or 0
        put_oi_sum = summary.get('total_put_oi') or 0
        oi_total = call_oi_sum + put_oi_sum
    dyn_info = compute_dynamic_threshold(
        iv_percentile=iv_pct,
        T_days_remaining=T_days,
        oi_total_now=oi_total,
    )
    dyn_th = dyn_info['dyn_threshold']

    # === v2.11.68: 优先用现成 _judge_shape 兜底（保留向后兼容）===
    shape_legacy = _judge_shape(call_oi, put_oi)
    # === v2.11.68+87: 用 pain_curve 算 slope regime 作为新的 shape（接 dyn_th 动态阈值）===
    pain_curve = gex.get('pain_curve') or []
    slope_info = compute_pain_slope(pain_curve, max_pain, dyn_th=dyn_th)
    slope_down_now  = slope_info['slope_down']
    slope_up_now    = slope_info['slope_up']
    slope_ratio_now = slope_info['slope_ratio']
    slope_regime_now = slope_info['slope_regime']
    # v2.11.90: 双侧陡独立判定 (P1 飞书附录方案)
    both_steep_now  = slope_info.get('both_steep', False)
    # v2.11.87: 暴露 thresholds_used 给前端调试
    slope_thresholds_used = slope_info.get('thresholds_used', SLOPE_REGIME_THRESHOLDS)
    # 映射 slope regime → 业务 shape（与 iv_smile.html 的 9 象限 labelMap 一致）
    # v2.11.90 P1: 双侧陡独立分支, 优先级最高
    if both_steep_now:
        shape = 'bothSteep'
    elif slope_regime_now in ('强不对称', '一边主导', '略不对称'):
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
        # v2.11.91 P1-L2-3: 阈值改比例 (F*0.2% 替代硬编码 5 元)
        # 业务: PTA 5000-6000 区间, 0.2% ≈ 10-12 元, 比 5 元宽, 跟业务 "接近" 语义更贴
        p_vs_flip_threshold = max(5, futures_price * 0.002)
        p_vs_flip = 'above' if diff > p_vs_flip_threshold else ('below' if diff < -p_vs_flip_threshold else 'at')
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

    # v2.11.93: 业务查表直接输出 5 档量纲 (飞书原文 ±2/±1.5/±0.5/0)
    # 旧 3 档 (0.6/0.3/0.1) → 新 5 档 (2.0/1.5/0.5/0) 比例 3.33x
    # 取消中间 raw_score, 直接 5 档 (legacy_total 字段保留双轨对比)
    score = 0
    score_detail = ''

    if shape == 'rightSteep' and position == 'belowMP':
        if gex_dir == 'negative':
            score = 0.5   # 弱偏多: 空头衰竭+反弹燃料
            score_detail = '空头衰竭+反弹燃料（弱偏多）'
        elif gex_dir == 'positive':
            score = 2.0   # 强偏多: 底部反转确立+正GEX稳定
            score_detail = '底部反转确立+正GEX稳定（强偏多）'
    elif shape == 'rightSteep' and position == 'aboveMP':
        if gex_dir == 'negative':
            score = -1.5  # 偏空: 高位急跌+负GEX加速下行
            score_detail = '高位急跌+负GEX加速下行（偏空）'
        elif gex_dir == 'positive':
            score = 1.5   # 偏多: 强多头+正GEX保护
            score_detail = '强多头+正GEX保护（偏多）'
    elif shape == 'leftSteep' and position == 'belowMP':
        if gex_dir == 'negative':
            score = -2.0  # 强偏空: 强空头+负GEX放大
            score_detail = '强空头+负GEX放大（强偏空）'
        elif gex_dir == 'positive':
            score = 1.5   # 偏多: 恐慌出清+正GEX抑制底部
            score_detail = '恐慌出清+正GEX抑制底部（偏多）'
    elif shape == 'leftSteep' and position == 'aboveMP':
        if gex_dir == 'negative':
            score = -1.5  # 偏空: 假突破后加速回归
            score_detail = '假突破后加速回归（偏空）'
        elif gex_dir == 'positive':
            score = -0.5  # 弱偏空: 多空博弈+左侧埋伏
            score_detail = '多空博弈+左侧埋伏（弱偏空）'
    elif shape == 'sym':
        score = 0
        score_detail = 'pin risk / 低波动收敛（中性）'
    # v2.11.90 P1: 双侧陡独立分支 (飞书附录 1.3 矩阵第 2/3 行)
    # v2.11.93: 中性 0
    elif shape == 'bothSteep':
        if gex_dir == 'positive':
            score = 0
            score_detail = '双侧陡+正GEX中性强支撑（中性）'
        elif gex_dir == 'negative':
            score = 0
            score_detail = '双侧陡+负GEX观望等待（中性观望）'
        else:
            score = 0
            score_detail = '双侧陡+GEX未知（中性）'

    # v2.11.93: PCR 维度调整 (5 档内 ±0.5 ladder 调整, 用 vol_pcr 跟 §1.1 矩阵'成交 PCR'列一致)
    # 旧实装: pos_pcr > 1.3 → score -0.1; < 0.7 → +0.1
    # 新实装: vol_pcr > 1.2 → score -0.5 (ladder 调整, 业务确认偏空)
    #         vol_pcr < 0.8 → score +0.5 (ladder 调整, 业务确认偏多)
    pcr_modifier = 0
    pcr_meaning = ''
    if vol_pcr > 0:  # 用 vol_pcr 跟飞书原文 §1.1 矩阵'成交 PCR'列一致
        if vol_pcr > 1.2:
            pcr_modifier = -0.5
            pcr_meaning = f'成交PCR={vol_pcr:.2f} 偏高（恐慌）→ 业务确认偏空方向'
        elif vol_pcr < 0.8:
            pcr_modifier = +0.5
            pcr_meaning = f'成交PCR={vol_pcr:.2f} 偏低（过度乐观）→ 业务确认偏多方向'
        else:
            pcr_meaning = f'成交PCR={vol_pcr:.2f} 中性区间'

    # v2.11.93: 5 档 ladder 调整 (不用 max(-1,1) 限幅, 改 ladder 最近邻)
    if pcr_modifier != 0:
        score = _ladder_to_5grid(score + pcr_modifier)

    # 5 档 ladder (强/弱 + 方向)
    # 防止 score 漂出 ladder (业务查表 +0.5 修饰可能产生 ±2.5)
    score = _ladder_to_5grid(score)

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
        # === v2.11.87: 动态阈值三因子结果 (暴露给前端调试) ===
        'dyn_threshold': dyn_th,
        'dyn_triggered': dyn_info['triggered'],
        'dyn_all_triggers': dyn_info['all_triggers'],
        'slope_thresholds_used': slope_thresholds_used,
        # === v2.11.90: 双侧陡独立判定 (P1) ===
        'both_steep': both_steep_now,
        # === v2.11.90 P4: 双轨过渡标记 (1 周后用户对比主观感受再决定是否替换) ===
        'threshold_version': 'v2.11.90a',  # 新版 (both_steep 独立分支)
        'logic_brief': (f'双侧陡 (|下|={abs(slope_down_now):.0f} |上|={abs(slope_up_now):.0f} 比={slope_ratio_now:.2f}) + GEX {gex_dir} → {score_detail}'
                        if both_steep_now
                        else f'{shape} + {position} + GEX {gex_dir} + P vs Flip {p_vs_flip} → {score_detail}')
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
    # v2.11.90 P1: 双侧陡独立分支 (飞书附录 1.3 矩阵第 2/3 行)
    if shape == 'bothSteep':
        if gex_dir == 'positive':  return '双侧陡+正GEX: 上下阻力对称存在, 正GEX提供稳定锚, 趋势性弱但有底, 适合区间策略'
        if gex_dir == 'negative':  return '双侧陡+负GEX: 上下阻力对称但GEX负放大双向波动, 观望等待方向选择, 警惕假突破'
        return '双侧陡 (GEX方向未知): 上下阻力对称存在, 趋势性弱, 等待GEX信号确认'
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

    # v2.11.93: 业务查表直接 5 档量纲 (飞书原文 §2.2 GEX × P-Flip 矩阵)
    # 旧 3 档 (0.6/0.3/0.1) → 新 5 档 (2.0/1.5/0.5/0) 比例 3.33x
    if gex_dir == 'negative' and p_vs_flip == 'below':
        meaning = '负GEX + P在Flip下方 → 卖方对冲压力放大波动，下方无支撑'
        score = -2.0  # 强偏空 (旧 -SCORE_STRONG=-0.6)
        score_detail = '强空机制（负GEX放大下跌）'
    elif gex_dir == 'negative' and p_vs_flip == 'above':
        meaning = '负GEX + P在Flip上方 → 卖方对冲买压释放（涨幅被放大，但也有回调风险）'
        score = -0.5  # 弱偏空 (旧 -SCORE_WEAK=-0.1)
        score_detail = '弱空机制（涨幅放大但有支撑）'
    elif gex_dir == 'negative' and p_vs_flip == 'at':
        # v2.11.91 P1-L2-1: 负GEX + P接近Flip (即将翻正) = 放大减弱, 即将切换到正GEX抑制
        # 飞书 2.2 矩阵第 4 行: 业务含义 "即将切换到抑制机制, 拐点反向" → 偏多拐点
        # v2.11.93: 弱偏多 (旧 +SCORE_WEAK=+0.1)
        meaning = '负GEX + P接近Flip → 放大减弱，即将切换到正GEX抑制（拐点反向，中性偏多）'
        score = +0.5  # 弱偏多拐点
        score_detail = '弱多机制（负GEX即将转正，拐点有利）'
    elif gex_dir == 'positive' and p_vs_flip == 'above':
        meaning = '正GEX + P在Flip上方 → 卖方净正Gamma抑制波动，托底'
        score = +1.5  # 偏多 (旧 +SCORE_MEDIUM=+0.3)
        score_detail = '中多机制（正GEX托底）'
    elif gex_dir == 'positive' and p_vs_flip == 'below':
        meaning = '正GEX + P在Flip下方 → 抑制减弱，下方支撑弱化'
        score = 0  # 中性
        score_detail = '中性机制（抑制减弱）'
    elif gex_dir == 'positive' and p_vs_flip == 'at':
        meaning = '正GEX + P接近Flip → 即将切换到放大机制'
        score = -0.5  # 弱偏空 (旧 -SCORE_WEAK=-0.1)
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

    # === v2.11.91 P1-L2-2: GEX Flip 穿越检测 (飞书 2.2 矩阵第 5 行, 关键拐点信号) ===
    # 业务: GEX Flip 穿越 = 卖方对冲压力符号翻转 = 波动机制切换 = "最关键拐点"
    # 检测方法: 1h 内 P 从 Flip 一侧穿到另一侧 (gex_flip_migration + diff 符号变化)
    gex_flip_crossed = False
    flip_cross_direction = None  # 'neg_to_pos' / 'pos_to_neg' / None
    # L2 没有 curve 参数, futures_price 从 layer1 取
    _futures_price_for_flip = layer1.get('futures_price', 0) or 0
    if gex_flip_now and gex_flip_prev and _futures_price_for_flip:
        diff_now = _futures_price_for_flip - gex_flip_now
        # 1h 前的 P 没存, 用 gex_flip_migration 反推
        # 假设 P 没动: P_1h_ago ≈ P_now, flip_1h_ago = flip_now - flip_migration
        # diff_prev = P_1h_ago - flip_1h_ago = P_now - (flip_now - flip_migration) = diff_now + flip_migration
        if gex_flip_migration != 0:
            diff_prev = diff_now + gex_flip_migration
            # 穿越条件: diff_now 和 diff_prev 异号 + 绝对值都 < 50 (放宽, 飞书说"最关键拐点"但实战罕见)
            if diff_now * diff_prev < 0 and abs(diff_now) < 50 and abs(diff_prev) < 50:
                gex_flip_crossed = True
                flip_cross_direction = 'neg_to_pos' if diff_now > 0 else 'pos_to_neg'

    # Flip 穿越 → score 加成 + logic_brief 强调
    if gex_flip_crossed:
        score_detail += f' | ⚠️ GEX Flip 穿越 ({flip_cross_direction})'

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
        # === v2.11.91 P1-L2-2: GEX Flip 穿越检测 ===
        'gex_flip_crossed': gex_flip_crossed,
        'flip_cross_direction': flip_cross_direction,
        # === v2.11.68 新增 1h + daily 变化 ===
        'intraday_change': intraday_change,
        'daily_change': daily_change,
        'logic_brief': f'GEX {gex_dir} + P {p_vs_flip} Flip + 净GEX {net_gex_now/1e6:+.1f}M → {score_detail}'
    }


# ============================================================
# 第三层：资金意图层（25%）
# ============================================================
def judge_layer3_funding_intent(alert_data: Dict, gex: Dict, layer1: Dict,
                                intraday_slots: list = None,
                                weighted: Dict = None) -> Dict:
    """第三层：资金意图（用现成 _compute_nature_and_synthesis）

    v2.11.68:
      - B 方案：输出 standardized_label + 1h PCR delta + detail_section_ref 标记
        （避免与段 3 性质判定×合成信号重复；前端读 detail_section_ref 跳段 3 链接）

    v2.11.95c:
      - 加 weighted 参数 (v2.11.85a 加权综合结果)
      - 当 weighted 存在时, put_nature/call_nature 用 weighted['Put']['main_nat']/['Call']['main_nat']
        (加权综合主性质), 而不是 strike 级 nature
      - 目的: 让 layer_score 走加权口径, 跟 funding_signal.signal_label / direction 同源
        解决 v2.11.95b 之前的"3 套输入不一致" bug:
        - strike 级 nature: 5000P spec_buy(投机彩票) → 14 行表 → "单边偏空" → -1.5
        - 加权 main_nat:   put=hedge_buy(43%) → 14 行表 → "多空分歧" → 0
        - 之前两套并存, 量化-1.5 跟定性"防御"矛盾, 用户感知"定性和量化矛盾"
        - 现在统一走加权口径, 跟 funding_signal / cross_validation_verdict 一致

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
    # v2.11.95c: 当 weighted (v2.11.85a 加权综合) 存在时, 用 main_nat 覆盖 strike 级 nature
    # 让 14 行表查表 / L3_5GRID_TABLE / layer_score 走加权口径, 跟 funding_signal 同源
    # strike 级 nature 仍保留在 nature_label / business_meaning / role_summary (供前端展开区)
    # 注意: 改 put_nature/call_nature 不会影响 nature_label (那个是 strike 级) — 前端展开区
    #       看到的"性质"还是 strike 级, 但 layer_score / standardized_label 走加权口径
    if weighted:
        w_call_main = (weighted.get('Call') or {}).get('main_nat')
        w_put_main  = (weighted.get('Put')  or {}).get('main_nat')
        if w_call_main:
            call_nature = w_call_main
        if w_put_main:
            put_nature = w_put_main
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

    # v2.11.93: L3 5 档化 (飞书原文 14 行矩阵 → 5 档量纲 ±2/±1.5/±0.5/0)
    # 旧: (p_score + c_score + strike_score) / 2 归一化到 [-0.5, +0.5]
    # 新: 用 14 行矩阵 standardized_label → 5 档查表
    L3_5GRID_TABLE = {
        '看多共振 (强)':      +2.0,
        '看多共振':           +1.5,
        '单边偏多 (强)':      +1.5,
        '单边偏多':           +0.5,
        '箱体震荡':            0.0,
        '多空分歧':            0.0,
        '无方向':              0.0,
        '单边偏空 (弱)':      -0.5,
        '单边偏空':           -1.5,
        '看空共振':           -1.5,
        '看空共振 (强)':      -2.0,
        '恐慌出清中（多头）':  +1.5,
        '乐观消退中（空头）':  -1.5,
    }
    layer_score_5grid = L3_5GRID_TABLE.get(standardized_label, 0.0)

    # legacy 字段保留双轨对比 (v2.11.90 P4)
    legacy_layer_score = (p_score + c_score + strike_score) / 2

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
        # v2.11.93: layer_score 直接 5 档量纲 (±2/±1.5/±0.5/0)
        'layer_score': layer_score_5grid,
        # v2.11.93: legacy 字段保留双轨对比 (v2.11.90 P4)
        'legacy_layer_score': legacy_layer_score,
        'layer_score_5grid': layer_score_5grid,
        # === v2.11.68 B 方案：1h PCR delta + 跳段 3 链接标记 ===
        'pcr_delta_1h': round(pcr_delta_1h, 4),
        'slot_now': slot_now_label,
        'slot_1h_ago': slot_1h_label,
        'detail_section_ref': 'section_3',  # 段 3 性质判定×合成信号
        'logic_brief': f'Put {put_nature} + Call {call_nature} → {standardized_label}'
    }


def label_standardize(put_nature: str, call_nature: str, strike_modifier: str = '',
                      pcr_now: float = 0, pcr_prev: float = 0) -> Tuple[str, str]:
    """v2.11.85e: 严格按飞书 §2.3.1 Put端与Call端合成信号矩阵（14 行）查表

    飞书原版矩阵（line 590-654，Put 方向 × Call 方向 = 合成信号 + 信号强度）：
      看空   偏空   看空共振             强
      偏空   偏空   看空共振（弱化）     中
      看空   中性   单边偏空             中
      偏空   中性   单边偏空（弱）       中（弱）
      中性   偏空   单边偏空（防御）     中
      偏多   看多   看多共振             强
      偏多   偏多   看多共振（弱化）     中
      偏多   中性   单边偏多             中
      中性   偏多   单边偏多（防御）     中
      偏多   偏空   多空分歧             弱（观望）
      偏空   偏多   多空分歧             弱（观望）
      看空   看多   多空分歧（极端）     极弱（观望）
      看空   偏多   多空分歧             弱（观望）
      偏空   看多   多空分歧             弱（观望）
      中性   中性   无方向               极弱（观望）
      中性（套保卖权）中性（套保卖权）箱体震荡   中

    v2.11.63a/v2.11.85d 老实现只有 5 行表（看多/看空/中性 3 档方向），按飞书 14 行表
    应扩到 5 档方向：看空 / 偏空 / 中性 / 偏多 / 看多
    """
    # v2.11.85e: 业务方向映射（5 档：看空/偏空/中性/偏多/看多）
    # Put 端：spec_buy/close_push 主动看空; spec_buy_directional = spec_buy (主动看空);
    #         spec_buy_lotto 偏空弱; hedge_buy 防御偏多（软底）; hedge_sell 套保卖权中性;
    #         double_exit/supply_overhang/... 中性
    PUT_DIR = {
        'spec_buy':             '看空',
        'spec_buy_directional': '看空',
        'close_push':           '看空',
        'spec_buy_lotto':       '偏空',
        'hedge_buy':            '偏多',
        'hedge_sell':           '中性',
        'double_exit':          '中性',
        'supply_overhang':      '中性',
        'mixed_neutral':        '中性',
        'passive_close':        '中性',
        'noise_close':          '中性',
        'noise_open':           '中性',
        'theta_decay':          '中性',
        'quote_adjust':         '中性',
        'static':               '中性',
        'hedge_rolling':        '中性',
    }
    # Call 端：spec_buy/close_push 主动看多; spec_buy_directional = spec_buy (主动看多);
    #          spec_buy_lotto 偏多弱; hedge_buy 防御偏空（软顶）; hedge_sell 套保卖权中性;
    #          double_exit/supply_overhang/... 中性
    CALL_DIR = {
        'spec_buy':             '看多',
        'spec_buy_directional': '看多',
        'close_push':           '看多',
        'spec_buy_lotto':       '偏多',
        'hedge_buy':            '偏空',
        'hedge_sell':           '中性',
        'double_exit':          '中性',
        'supply_overhang':      '中性',
        'mixed_neutral':        '中性',
        'passive_close':        '中性',
        'noise_close':          '中性',
        'noise_open':           '中性',
        'theta_decay':          '中性',
        'quote_adjust':         '中性',
        'static':               '中性',
        'hedge_rolling':        '中性',
    }
    p_dir = PUT_DIR.get(put_nature, '中性')
    c_dir = CALL_DIR.get(call_nature, '中性')

    # P1 fix: PCR 恐慌出清信号（必须在常规查表之前，否则被提前 return 吞掉）
    # 阈值放宽：prev > 1.5 + now < 1.2 → 恐慌出清（多头）
    #         prev < 0.6 + now > 0.8 → 乐观消退（空头）
    if pcr_prev > 0 and pcr_now > 0:
        if pcr_prev > PCR_FEAR_HIGH and pcr_now < PCR_NEUTRAL_HIGH:
            return '恐慌出清中（多头）', '中'
        if pcr_prev < PCR_FEAR_LOW and pcr_now > PCR_NEUTRAL_LOW:
            return '乐观消退中（空头）', '中'

    # v2.11.85e: 飞书 §2.3.1 双侧套保卖权 → 箱体震荡（中）
    if put_nature == 'hedge_sell' and call_nature == 'hedge_sell':
        return '箱体震荡', '中'

    # v2.11.85e: 严格按飞书 14 行表查表（仅覆盖飞书明确列出的组合）
    table_14 = {
        ('看空', '偏空'): ('看空共振', '强'),
        ('偏空', '偏空'): ('看空共振（弱化）', '中'),
        ('看空', '中性'): ('单边偏空', '中'),
        ('偏空', '中性'): ('单边偏空（弱）', '中（弱）'),
        ('中性', '偏空'): ('单边偏空（防御）', '中'),
        ('偏多', '看多'): ('看多共振', '强'),
        ('偏多', '偏多'): ('看多共振（弱化）', '中'),
        ('偏多', '中性'): ('单边偏多', '中'),
        ('中性', '偏多'): ('单边偏多（防御）', '中'),
        ('偏多', '偏空'): ('多空分歧', '弱（观望）'),
        ('偏空', '偏多'): ('多空分歧', '弱（观望）'),
        ('看空', '看多'): ('多空分歧（极端）', '极弱（观望）'),
        ('看空', '偏多'): ('多空分歧', '弱（观望）'),
        ('偏空', '看多'): ('多空分歧', '弱（观望）'),
        ('中性', '中性'): ('无方向', '极弱（观望）'),
    }
    if (p_dir, c_dir) in table_14:
        return table_14[(p_dir, c_dir)]

    # v2.11.85e: 飞书 14 行表未覆盖的"主动+中性"组合兜底（业务上对称扩展）
    # 飞书原表只列了 (中性, 偏X) 和 (偏X, 中性) 两种"主动+中性"
    # 但实战中 (中性, 看多/看空) 也常见（产业套保卖权 + 投机主动买 Call/Put）
    # 按对称扩展兜底到最近的"单边+防御"信号:
    if p_dir == '中性' and c_dir == '看多':
        return '单边偏多（防御）', '中'
    if p_dir == '中性' and c_dir == '看空':
        return '单边偏空（防御）', '中'
    if p_dir == '看多' and c_dir == '中性':
        return '单边偏多', '中'  # 注意飞书表只有 (偏多, 中性) → 单边偏多，看多+中性兜底到同一档
    if p_dir == '看空' and c_dir == '中性':
        return '单边偏空', '中'  # 同理

    # v2.11.63d: 双侧中性 + strike 修正 → 多空分化
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
        return '无方向', '极弱（观望）'

    return 'unknown', ''


# ============================================================
# 第四层：情绪确认层（15%）
# ============================================================
def judge_layer4_emotion(curve: Dict, alert_data: Dict, layer1: Dict, gex: Dict,
                         intraday_slots: list = None, layer3: Dict = None) -> Dict:
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
    # v2.11.93: 5 子信号累加直接 5 档量纲 (旧 ±0.1/0.2/0.3 → 新 ±0.5/1.0)
    # 累加完用 _ladder_to_5grid 归到 5 档
    legacy_score = 0  # 保留双轨对比
    score_5grid_raw = 0.0  # 5 档量纲累加 (累加后 ladder 化)
    score_detail = ''  # v2.11.93 修复: 必须初始化, 避免 vol_pcr=0 + atm_iv=None 边界 UnboundLocalError

    # 1. 成交 PCR (业务定义: 飞书 §2.4)
    if vol_pcr > 0:
        if vol_pcr > PCR_FEAR_HIGH:  # > 1.5
            signals.append(f'成交PCR={vol_pcr:.2f} 持续>1.5（恐慌未消）')
            score_5grid_raw += -1.0  # 强空方向 (旧 -0.3)
            legacy_score += -0.3
            score_detail = '恐慌情绪（强空头）'
        elif vol_pcr < PCR_FEAR_LOW:  # < 0.6
            signals.append(f'成交PCR={vol_pcr:.2f} 持续<0.6（过度乐观）')
            score_5grid_raw += -0.5  # 弱空方向 (旧 -0.2)
            legacy_score += -0.2
            score_detail = '过度乐观（弱空头）'
        elif PCR_NEUTRAL_LOW <= vol_pcr <= PCR_NEUTRAL_HIGH:  # 0.8-1.2
            signals.append(f'成交PCR={vol_pcr:.2f} 中性区间')
            # score 不变
        elif vol_pcr < 1.0:  # 0.6-0.8
            signals.append(f'成交PCR={vol_pcr:.2f} 中性偏低')
            score_5grid_raw += +0.5  # 弱多方向 (旧 +0.1)
            legacy_score += +0.1
            score_detail = '略偏多'

    # 2. 恐慌出清判定
    if pcr_prev > 0 and vol_pcr > 0:
        if pcr_prev > PCR_FEAR_HIGH and vol_pcr < 1.0:
            signals.append(f'成交PCR 从 {pcr_prev:.2f} 回落至 {vol_pcr:.2f}（恐慌出清）→ 多头')
            score_5grid_raw += +1.0  # 强多方向 (旧 +0.3)
            legacy_score += +0.3
            if not score_detail: score_detail = '恐慌出清（多头信号）'
        elif pcr_prev < PCR_FEAR_LOW and vol_pcr > 0.8:
            signals.append(f'成交PCR 从 {pcr_prev:.2f} 上升至 {vol_pcr:.2f}（乐观消退）→ 空头')
            score_5grid_raw += -1.0  # 强空方向 (旧 -0.2)
            legacy_score += -0.2
            if not score_detail: score_detail = '乐观消退（空头信号）'

    # 3. ATM IV (业务定义: 飞书 §2.4)
    if atm_iv_call and atm_iv_put:
        avg_iv = (atm_iv_call + atm_iv_put) / 2
        signals.append(f'ATM 隐波 {avg_iv*100:.2f}%')
        if avg_iv > 0.30:  # 高位恐慌 (>30%)
            signals.append(f'ATM 隐波 {avg_iv*100:.1f}% 处于高位（恐慌区域）')
            score_5grid_raw += -0.5  # 弱空 (旧 -0.1)
            legacy_score += -0.1
            if not score_detail: score_detail = '高位IV恐慌（弱空）'
        elif avg_iv < 0.15:  # 低位收租 (<15%)
            signals.append(f'ATM 隐波 {avg_iv*100:.1f}% 处于低位（收租区域）')
            # 收租中性 (不强制给空分, 避免误判; cross-check L3 再调)
        else:
            signals.append(f'ATM 隐波 {avg_iv*100:.1f}% 中性区间')
    # v2.11.91 P1-L4-2: "降波也可能是套保卖权" 陷阱 cross-check L3
    if layer3 and atm_iv_call and atm_iv_put:
        avg_iv_now = (atm_iv_call + atm_iv_put) / 2
        call_main = layer3.get('call_main_nat') or layer3.get('call_nature')
        if avg_iv_now < 0.20 and call_main == 'hedge_sell':
            signals.append(f'⚠️ 降波陷阱: 隐波低位 ({avg_iv_now*100:.1f}%) + L3 Call 套保卖权集中（产业收租，非投机降波）')
            # 中性陷阱 → 不加分 (L4 业务定义 §2.4: 降波套保 = 中性陷阱)

    # 4. 趋势
    if trend == 'up':
        signals.append(f'趋势↑（F {prev_f:.0f} → {cur_f:.0f}，+{trend_diff:.0f}）')
        score_5grid_raw += +0.5  # 弱多 (旧 +0.1)
        legacy_score += +0.1
    elif trend == 'down':
        signals.append(f'趋势↓（F {prev_f:.0f} → {cur_f:.0f}，{trend_diff:.0f}）')
        score_5grid_raw += -0.5  # 弱空 (旧 -0.1)
        legacy_score += -0.1
    elif trend == 'flat':
        signals.append('趋势→（横盘）')
    else:
        signals.append('趋势 unknown')

    # 5. 1h 趋势打分加成（不重复加分）
    if trend_1h == 'up' and trend != 'up':
        score_5grid_raw += +0.5  # 弱多 (旧 +0.1)
        legacy_score += +0.1
        if not score_detail: score_detail = '1h趋势↑'
    elif trend_1h == 'down' and trend != 'down':
        score_5grid_raw += -0.5  # 弱空 (旧 -0.1)
        legacy_score += -0.1
        if not score_detail: score_detail = '1h趋势↓'

    # v2.11.93: ladder 化 5 档量纲 (飞书原文 §2.4: 偏多/中性/偏空 3 档, 但允许 ±0.5 累加)
    # L4 业务查表 3 档 (偏多/中性/偏空), 但 5 子信号累加可能产生 ±2
    # 5 档 ladder 比 3 档更精细, 跟 L1/L2/L3 统一接口
    layer_score = _ladder_to_5grid(score_5grid_raw)

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
        # v2.11.93: layer_score 直接 5 档量纲 (旧 score 累加 ±0.1 已重命名为 score_5grid_raw/legacy_score)
        'layer_score': layer_score,  # 5 档量纲 (-2/-1.5/-0.5/0/+0.5/+1.5/+2)
        'legacy_layer_score': max(-1, min(1, legacy_score)),  # v2.11.90 P4 保留
        'logic_brief': ' | '.join(signals[:4]) if signals else 'no emotion signals'
    }


# ============================================================
# 四层加权叠加
# ============================================================
# ============================================================
# v2.11.92: 飞书 5 档评分常量（强偏多+2/偏多+1.5/弱偏多+0.5/中0/弱偏空-0.5/偏空-1.5/强偏空-2）
# 旧 0.6/0.3/0.1 是 v2.11.85b 的"高/中/弱"档，量纲差 3.3 倍；飞书 5 档更精细
# ============================================================
SCORE_5GRID_STRONG_POS = 2.0    # 强偏多
SCORE_5GRID_MID_POS   = 1.5    # 偏多
SCORE_5GRID_WEAK_POS  = 0.5    # 弱偏多
SCORE_5GRID_NEUTRAL   = 0.0    # 中性
SCORE_5GRID_WEAK_NEG  = -0.5   # 弱偏空
SCORE_5GRID_MID_NEG   = -1.5   # 偏空
SCORE_5GRID_STRONG_NEG = -2.0  # 强偏空

# 信号阈值（飞书 5 档）
SCORE_THRESH_STRONG_POS = 1.2
SCORE_THRESH_WEAK_POS   = 0.6
SCORE_THRESH_WEAK_NEG   = -0.6
SCORE_THRESH_STRONG_NEG = -1.2


def _get_theta_weights(T_days_remaining: Optional[float] = None) -> Dict[str, float]:
    """v2.11.92: 飞书 θ 加权 4 档权重表

    飞书原文（"θ 加权在各层的时间表"）：
    | T | L1 | L2 | L3 | L4 |
    | T ≥ 15      | 35% | 25% | 25% | 15% |
    | 10 ≤ T < 15 | 38% | 25% | 25% | 15% |
    | 5 ≤ T < 10  | 40% | 25% | 25% | 12% |
    | T < 5       | 40% (or 45% 信号强度上调) | 25% | 20% | 8-10% |

    用户拍板：只调权重，不动内部阈值（防过度优化陷阱，跟 L1 dyn D 方案哲学一致）
    """
    if T_days_remaining is None:
        # 兜底：默认 T≥15 档
        return {'L1': 0.35, 'L2': 0.25, 'L3': 0.25, 'L4': 0.15, 'T_bucket': 'unknown'}
    if T_days_remaining >= 15:
        return {'L1': 0.35, 'L2': 0.25, 'L3': 0.25, 'L4': 0.15, 'T_bucket': 'T≥15'}
    if T_days_remaining >= 10:
        return {'L1': 0.38, 'L2': 0.25, 'L3': 0.25, 'L4': 0.15, 'T_bucket': '10≤T<15'}
    if T_days_remaining >= 5:
        return {'L1': 0.40, 'L2': 0.25, 'L3': 0.25, 'L4': 0.12, 'T_bucket': '5≤T<10'}
    # T < 5
    return {'L1': 0.45, 'L2': 0.25, 'L3': 0.20, 'L4': 0.10, 'T_bucket': 'T<5'}


def _rescore_to_5grid(raw_score: float) -> Tuple[float, str]:
    """v2.11.92: 把单层原始 score（-0.6 ~ +0.6）映射到飞书 5 档量纲（-2 ~ +2）

    飞书 5 档：强偏多+2 / 偏多+1.5 / 弱偏多+0.5 / 中0 / 弱偏空-0.5 / 偏空-1.5 / 强偏空-2
    旧实装 3 档：强+0.6 / 中+0.3 / 弱+0.1
    映射规则：按绝对值 0/0.1/0.3/0.6 比例（与原 3 档位置对齐）
      raw 0    → 飞书 0
      raw ±0.1 → 飞书 ±0.5
      raw ±0.3 → 飞书 ±1.5
      raw ±0.6 → 飞书 ±2.0
    """
    if raw_score >= 0.6:   return 2.0, '强偏多'
    if raw_score >= 0.3:   return 1.5, '偏多'
    if raw_score >= 0.05:  return 0.5, '弱偏多'
    if raw_score <= -0.6:  return -2.0, '强偏空'
    if raw_score <= -0.3:  return -1.5, '偏空'
    if raw_score <= -0.05: return -0.5, '弱偏空'
    return 0.0, '中性'


def synthesize_decision(layers: List[Dict], T_days_remaining: Optional[float] = None) -> Dict:
    """v2.11.93: 4 层直接 5 档量纲加权, 取消 _rescore_to_5grid 二次映射
    业务查表直接输出 5 档量纲 (-2/-1.5/-0.5/0/+0.5/+1.5/+2)
    legacy_total 字段保留双轨对比 (v2.11.90 P4 模式)
    """
    # === v2.11.92: θ 加权（用户拍板 = 只调权重）===
    weights = _get_theta_weights(T_days_remaining)
    layer_weight_map = {1: weights['L1'], 2: weights['L2'], 3: weights['L3'], 4: weights['L4']}

    # === v2.11.93: 4 层 layer_score 已经是 5 档量纲, 直接加权 ===
    layer_5grid = []
    for l in layers:
        score5 = l.get('layer_score', 0)  # 4 层直接输出 5 档
        w = layer_weight_map.get(l.get('layer', 0), l.get('weight', 0.25))
        layer_5grid.append({
            'layer': l.get('layer'),
            'layer_name': l.get('layer_name', ''),
            'score_5grid': score5,
            'score_label': LADDER_5GRID_LABELS.get(score5, '中性'),
            'weight': round(w, 3),
            'contribution': round(score5 * w, 3),
        })
    rescore_total = round(sum(d['contribution'] for d in layer_5grid), 3)

    # === v2.11.92: 5 档信号阈值（飞书原文）===
    if rescore_total >= SCORE_THRESH_STRONG_POS:
        signal_label = '强多共振'
        decision_v1 = '买入/加仓'
        confidence = '极高'
    elif rescore_total >= SCORE_THRESH_WEAK_POS:
        signal_label = '弱多'
        decision_v1 = '轻仓试探'
        confidence = '中'
    elif rescore_total <= SCORE_THRESH_STRONG_NEG:
        signal_label = '强空共振'
        decision_v1 = '卖出/加仓'
        confidence = '极高'
    elif rescore_total <= SCORE_THRESH_WEAK_NEG:
        signal_label = '弱空'
        decision_v1 = '轻仓做空'
        confidence = '中'
    else:
        signal_label = '信号矛盾/无信号'
        decision_v1 = '观望'
        confidence = '低'

    # v2.11.93+: 取消 legacy_total 双轨对比 (L1/L2 旧 0.6/0.3/0.1 旧法对照与 5 档量纲不一致, 已去除)
    legacy_total = rescore_total  # 字段保留供前端兼容, 实际值 = 5 档总分

    # 矛盾检测（5 档量纲下）
    signs = set()
    for d in layer_5grid:
        if d['score_5grid'] > 0.5: signs.add('+')
        elif d['score_5grid'] < -0.5: signs.add('-')

    layer_breakdown = [
        f"{d['layer_name']}={d['score_5grid']:+.1f} ({d['score_label']}, 权重 {d['weight']*100:.0f}%)"
        for d in layer_5grid
    ]

    # 各层逻辑串联
    logic_chain = ' → '.join([
        f"L{l.get('layer', '?')}({l.get('layer_name', '')}) [{l.get('logic_brief', '')}]"
        for l in layers
    ])

    # 总结论（按层次组织）
    summary_lines = [
        f"决策(评分): {decision_v1}（置信度: {confidence}）",
        f"信号强度: {signal_label}",
        f"总分(5档): {rescore_total:+.3f}",
        f"θ 加权档: {weights['T_bucket']} (L1={weights['L1']*100:.0f}% L2={weights['L2']*100:.0f}% L3={weights['L3']*100:.0f}% L4={weights['L4']*100:.0f}%)",
        f"逻辑链: {logic_chain}",
    ]

    return {
        # === 路线 1: 评分路线（v2.11.93: 直接 5 档加权, 取消 5 档映射）===
        'final_score': rescore_total,
        'final_signal': signal_label,
        'decision_v1': decision_v1,
        'theta_weights': weights,
        'layer_5grid': layer_5grid,           # v2.11.93 替代 rescore_details
        # === 向后兼容（保留 1 周双轨对比）===
        'total_score': legacy_total,            # 旧 3 档量纲加权
        'decision': decision_v1,
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
    """分层报告：4 层独立 + 总结论（按用户要求）

    v2.11.85b 兼容: contract/atm_strike/tqsdk_ready/last_update 缺省时用 .get 兜底
    允许从 decision_layer_cache.json 直接构造 result 调用（不需要外部 gex/alert_data）
    """
    L1 = result.get('layer1', {})
    L2 = result.get('layer2', {})
    L3 = result.get('layer3', {})
    L4 = result.get('layer4', {})
    final = result.get('final', {})
    contract = result.get('contract', '-')
    futures_price = result.get('futures_price', 0) or 0
    atm_strike = result.get('atm_strike', 0) or 0
    max_pain = result.get('max_pain', 0) or 0
    generated_at = result.get('generated_at', '-')
    last_update = result.get('last_update', '')
    tqsdk_ready = result.get('tqsdk_ready')

    lines = []
    lines.append('=' * 72)
    lines.append('📊 PTA 期权四维决策报告（v2.11.85b）')
    lines.append(f'生成时间: {generated_at}')
    lines.append(f'合约: {contract} | 期货价: {futures_price:.0f} | ATM: {atm_strike:.0f} | MP: {max_pain:.0f}')
    if last_update:
        ready_str = '✅ 就绪' if tqsdk_ready else ('⚠️ 未就绪' if tqsdk_ready is False else '-')
        lines.append(f'最后更新: {last_update} | TqSdk: {ready_str}')
    lines.append('=' * 72)
    lines.append('')

    # ---- 第一层：PAIN 结构（35%） ----
    lines.append(f'【第一层】PAIN 结构（权重 {L1.get("weight",0)*100:.0f}%）')
    if L1:
        lines.append(f'  维度: 形态={L1.get("shape","-")} | 位置={L1.get("position","-")} | GEX={L1.get("gex_dir","-")} | P vs Flip={L1.get("p_vs_flip","-")}')
        if L1.get('matrix_meaning'):
            lines.append(f'  业务: {L1["matrix_meaning"]}')
        if L1.get('pcr_meaning'):
            lines.append(f'  PCR: {L1["pcr_meaning"]}（加成 {L1.get("pcr_modifier",0):+.1f}）')
        if L1.get('score_detail'):
            lines.append(f'  评分逻辑: {L1["score_detail"]}')
        lines.append(f'  ➜ 评分: {L1.get("layer_score",0):+.2f}')
    else:
        lines.append('  ⚠️ 数据不可用')
    lines.append('')

    # ---- 第二层：GEX 机制（25%） ----
    lines.append(f'【第二层】GEX 机制（权重 {L2.get("weight",0)*100:.0f}%）')
    if L2:
        lines.append(f'  维度: GEX={L2.get("gex_dir","-")} | P vs Flip={L2.get("p_vs_flip","-")}')
        if L2.get('matrix_meaning'):
            lines.append(f'  业务: {L2["matrix_meaning"]}')
        if L2.get('score_detail'):
            lines.append(f'  评分逻辑: {L2["score_detail"]}')
        lines.append(f'  ➜ 评分: {L2.get("layer_score",0):+.2f}')
    else:
        lines.append('  ⚠️ 数据不可用')
    lines.append('')

    # ---- 第三层：资金意图（25%） ----
    lines.append(f'【第三层】资金意图（权重 {L3.get("weight",0)*100:.0f}%）')
    if L3.get('available'):
        lines.append(f'  Put 性质: {L3.get("put_nature","-")} ({L3.get("put_nature_label","")})')
        if L3.get('put_business_meaning'):
            lines.append(f'    业务: {L3["put_business_meaning"]}')
        lines.append(f'  Call 性质: {L3.get("call_nature","-")} ({L3.get("call_nature_label","")})')
        if L3.get('call_business_meaning'):
            lines.append(f'    业务: {L3["call_business_meaning"]}')
        if L3.get('raw_label'):
            lines.append(f'  原始 label: {L3["raw_label"]} ({L3.get("raw_intensity","")})')
        if L3.get('standardized_label'):
            lines.append(f'  ✅ 标准化 label: {L3["standardized_label"]} ({L3.get("standardized_intensity","")})')
        if L3.get('strike_modifier'):
            lines.append(f'  strike 修正: {L3["strike_modifier"]}')
        if L3.get('call_role_summary'):
            lines.append(f'  Call 角色: {L3["call_role_summary"]}')
        if L3.get('put_role_summary'):
            lines.append(f'  Put 角色: {L3["put_role_summary"]}')
        # v2.11.85a: 加权判定明细
        if L3.get('weighted_version') == 'v2.11.85a':
            lines.append(f'  ⚖️ v2.11.85a 加权: Call {L3.get("weighted_label","-")} | Put {L3.get("put_weighted_label","-")}')
            if L3.get('weighted_verdict'):
                lines.append(f'    Call verdict: {L3["weighted_verdict"]}')
            if L3.get('put_weighted_verdict'):
                lines.append(f'    Put verdict: {L3["put_weighted_verdict"]}')
            if L3.get('direction'):
                lines.append(f'    Call 方向: {L3["direction"]}')
            if L3.get('put_direction'):
                lines.append(f'    Put 方向: {L3["put_direction"]}')
        if L3.get('pcr_now') is not None:
            lines.append(f'  PCR: now={L3["pcr_now"]:.3f} | prev={L3.get("pcr_prev",0):.3f} | delta={L3.get("pcr_delta",0):+.3f} ({L3.get("pcr_label","")})')
        dq = L3.get('data_quality') or {}
        if dq:
            dq_ver = dq.get('threshold_version', '?')
            dq_str = f'  数据质量({dq_ver}): confidence={dq.get("confidence","-")}, OI≥{dq.get("oi_threshold","-")}, IV≥{dq.get("iv_threshold_pct") or dq.get("iv_threshold_pp")}-门槛, eligible_call={dq.get("eligible_call","-")}/{dq.get("total_strikes","-")}'
            lines.append(dq_str)
    else:
        lines.append(f'  ⚠️ {L3.get("note", "数据不可用")}')
    lines.append(f'  ➜ 评分: {L3.get("layer_score",0):+.2f}')
    lines.append('')

    # ---- 第四层：情绪确认（15%） ----
    lines.append(f'【第四层】情绪确认（权重 {L4.get("weight",0)*100:.0f}%）')
    if L4:
        if L4.get('vol_pcr') is not None:
            lines.append(f'  成交 PCR: now={L4["vol_pcr"]:.3f} | prev={L4.get("vol_pcr_prev",0):.3f}')
        if L4.get('pos_pcr') is not None:
            lines.append(f'  持仓 PCR: now={L4["pos_pcr"]:.3f} | prev={L4.get("pos_pcr_prev",0):.3f}')
        if L4.get('atm_iv_call'):
            lines.append(f'  ATM 隐波: Call={L4["atm_iv_call"]*100:.2f}% | Put={L4.get("atm_iv_put",0)*100:.2f}%')
        if L4.get('prev_f'):
            lines.append(f'  趋势: F {L4["prev_f"]:.0f} → {L4.get("cur_f",0):.0f} ({L4.get("trend","")}, {L4.get("trend_diff",0):+.0f})')
        if L4.get('score_detail'):
            lines.append(f'  评分逻辑: {L4["score_detail"]}')
        lines.append(f'  ➜ 评分: {L4.get("layer_score",0):+.2f}')
    else:
        lines.append('  ⚠️ 数据不可用')
    lines.append('')

    # ---- 总结论（按用户要求：分层展示 + 总结论） ----
    lines.append('=' * 72)
    lines.append('🎯 综合判断（按权重叠加）')
    lines.append('=' * 72)
    if final.get('summary_lines'):
        for line in final['summary_lines']:
            lines.append(f'  {line}')
    else:
        lines.append(f'  决策: {final.get("decision","-")} | 总分: {final.get("total_score",0):+.3f} | 置信度: {final.get("confidence","-")}')
    lines.append('')
    if final.get('layer_breakdown'):
        lines.append('📋 各层贡献:')
        for bd in final['layer_breakdown']:
            lines.append(f'  {bd}')
    if final.get('contradiction'):
        lines.append(f'  ⚠️ 四层信号方向矛盾（{", ".join(final.get("signs", []))}）→ 决策降级为观望')

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

    # v2.11.92: 传 T_days_remaining 给 synthesize_decision 触发 θ 加权
    _T_days = (gex.get('summary', {}) or {}).get('T_days_remaining')
    final = synthesize_decision([L1, L2, L3, L4], T_days_remaining=_T_days)

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

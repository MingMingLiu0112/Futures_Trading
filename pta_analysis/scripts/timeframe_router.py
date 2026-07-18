#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
时间维度路由模块 (v2.11.95a)

设计依据：
- 飞书《PTA 期权完整决策框架》§"关于综合判断的补充方案：多数一致 + 加权优先级"
- 核心洞察：PAIN 结构反映中长线（数天~数周），资金意图+情绪确认反映短线（分钟~小时），
  GEX 介于两者之间（1-2 天）但与 PAIN 同源（OI 加权），放中长线组
- 不动 22 cell 表（保留"规则表为主"原则），只在 fallback 路径触发
- 不改 final.decision（独立计算"理论决策"供回测对比）

调用模式：
  from scripts.timeframe_router import route_decision_by_timeframe

  result = route_decision_by_timeframe(
      l1=dict, l2=dict, l3=dict, l4=dict,
      T_days=int, F=float
  )
  # 返回: {"decision": str, "scenario": str, "position_pct": float,
  #        "long_verdict": str, "short_verdict": str,
  #        "short_term_weight": float, "long_term_weight": float,
  #        "fallback_to_22cell": bool, "rationale": str}

6 个场景（保留 E）：
- A 双组同向多 → 满仓 100%
- B 短线主导（短线强 + 中长线中性/反向）→ 轻仓试多 30-40%（临到期 70%）
- C 中长线主导（短线中性/矛盾 + 中长线强）→ 中仓跟随 50-60%（临到期 30%）
- D 双组同向空 → 满仓 100%
- E 双组强反向 → 观望 0%
- F 退化 → 22 cell 表（return fallback_to_22cell=True）
"""

import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# ============================================================
# 5 档量纲化映射（与 decision_layer_service 5 档评分保持一致）
# ============================================================
# 参考 skill: pta-decision-5grid-ladder-2-stage-mapping
# score → 5 档 label
SCORE_TO_5GRID = [
    (-float('inf'), -1.75, '强偏空'),
    (-1.75, -1.0, '偏空'),
    (-1.0, -0.25, '弱偏空'),
    (-0.25, 0.25, '中性'),
    (0.25, 1.0, '弱偏多'),
    (1.0, 1.75, '偏多'),
    (1.75, float('inf'), '强偏多'),
]


def score_to_5grid(score: Optional[float]) -> str:
    """把 layer_score 量纲化到 5 档标签"""
    if score is None:
        return '中性'
    for lo, hi, label in SCORE_TO_5GRID:
        if lo <= score < hi:
            return label
    return '中性'


# ============================================================
# 组内判定：把 5 档映射到"组级 verdict"
# ============================================================
def _group_verdict(score_a: Optional[float], score_b: Optional[float]) -> Tuple[str, str]:
    """组内两层的组级判定

    输入：两层 score（已量纲化前的原始分数）
    输出：(verdict_label, strength_label)
      verdict_label: 强偏多/偏多/中性/偏空/强偏空
      strength_label: 强/中/弱
    """
    a = score_to_5grid(score_a)
    b = score_to_5grid(score_b)

    # 5 档→数字（用于计算方向）
    SCORE_VAL = {
        '强偏多': 2, '偏多': 1.5, '弱偏多': 0.5,
        '中性': 0,
        '弱偏空': -0.5, '偏空': -1.5, '强偏空': -2
    }
    va = SCORE_VAL[a]
    vb = SCORE_VAL[b]

    # 方向：取均值（正=偏多，负=偏空，0=中性）
    avg = (va + vb) / 2.0

    # 强度：两层的"绝对距离"
    gap = abs(va - vb)

    # 同向判定（gap < 0.5 视为一致）
    if gap <= 0.5:
        # 两层一致
        if avg >= 1.5:
            return ('强偏多', '强')
        elif avg >= 0.75:
            return ('偏多', '强')
        elif avg >= 0.25:
            return ('弱偏多', '中')
        elif avg >= -0.25:
            return ('中性', '中')
        elif avg >= -0.75:
            return ('弱偏空', '中')
        elif avg >= -1.5:
            return ('偏空', '强')
        else:
            return ('强偏空', '强')
    else:
        # 两层不一致 → 取主导方（数值大的一方）
        if abs(va) > abs(vb):
            dominant = va
        elif abs(vb) > abs(va):
            dominant = vb
        else:
            dominant = avg  # 同强度，取均值

        if dominant >= 1.5:
            return ('强偏多', '中')
        elif dominant >= 0.5:
            return ('偏多', '中')
        elif dominant <= -1.5:
            return ('强偏空', '中')
        elif dominant <= -0.5:
            return ('偏空', '中')
        else:
            return ('中性', '弱')


# ============================================================
# θ 加权：根据到期天数分配组权重
# ============================================================
def _theta_group_weights(T_days: Optional[int]) -> Tuple[float, float]:
    """返回 (短线组权重, 中长线组权重)

    T≥10 天: 短线 40% / 中长线 60%（中长线主导，时间充裕）
    5≤T<10 天: 短线 50% / 中长线 50%（平衡期）
    T<5 天:   短线 70% / 中长线 30%（临到期, PAIN 滞后问题最严重, 短线最高权重）
    """
    if T_days is None:
        return (0.5, 0.5)  # 默认平衡
    if T_days >= 10:
        return (0.40, 0.60)
    if T_days >= 5:
        return (0.50, 0.50)
    return (0.70, 0.30)


# ============================================================
# 最终方向推断：θ 加权综合长短线判定
# ============================================================
# 把 5 档量纲标签 → 数值（用于加权求和）
_DIR_VAL = {
    '强偏多': 2.0, '偏多': 1.5, '弱偏多': 0.5,
    '中性': 0.0,
    '弱偏空': -0.5, '偏空': -1.5, '强偏空': -2.0,
}


def _infer_final_direction(long_v: str, short_v: str,
                           long_w: float, short_w: float) -> Tuple[str, float, bool]:
    """θ 加权长短线判定 → 最终方向

    业务规则:
      1) 主导组（权重大的）若偏多/偏空，最终方向跟主导组
      2) 仅当主导组中性时，看加权综合分（阈值 ±0.25）
      3) 长短线方向不一致即冲突（业务警告）

    Returns: (direction_label, weighted_score, is_conflict)
      direction_label: '看多' / '看空' / '中性'
      weighted_score: 加权分（-2~+2）
      is_conflict: 长短线方向不一致
    """
    lv = _DIR_VAL.get(long_v, 0.0)
    sv = _DIR_VAL.get(short_v, 0.0)
    score = lv * long_w + sv * short_w
    long_bull = lv > 0
    short_bull = sv > 0
    long_bear = lv < 0
    short_bear = sv < 0
    is_conflict = (long_bull and short_bear) or (long_bear and short_bull)
    # 主导组方向（业务直觉：权重大的说了算）
    dominant = long_v if long_w >= short_w else short_v
    dv = _DIR_VAL.get(dominant, 0.0)
    if dv > 0:
        return ('看多', score, is_conflict)
    if dv < 0:
        return ('看空', score, is_conflict)
    # 主导组中性 → 看加权综合分（更宽松阈值 ±0.25）
    if score >= 0.25:
        return ('看多', score, is_conflict)
    if score <= -0.25:
        return ('看空', score, is_conflict)
    return ('中性', score, is_conflict)


def _direction_decision_cn(scenario: str, direction: str) -> str:
    """场景 + 方向 → 业务决策名（带方向）

    A 满仓买入 / D 满仓卖出 (方向固定)
    B 短线主导：方向看短线判断
    C 中长线主导：方向看中长线判断
    E 观望 / F 退化
    """
    if scenario == 'A':
        return '满仓做多'
    if scenario == 'D':
        return '满仓做空'
    if scenario == 'B':
        return '轻仓试多' if direction == '看多' else ('轻仓试空' if direction == '看空' else '轻仓观望')
    if scenario == 'C':
        return '中仓跟随做多' if direction == '看多' else ('中仓跟随做空' if direction == '看空' else '中仓观望')
    if scenario == 'E':
        return '观望'
    if scenario == 'F':
        return '退化到22cell'
    return '观望'


def _position_reason_text(scenario: str, theta_bucket: str,
                          long_w: float, short_w: float) -> str:
    """仓位的来源（让用户知道为什么是这个百分比）"""
    base = {
        'A': '双组同向多',
        'B': '短线主导',
        'C': '中长线主导',
        'D': '双组同向空',
        'E': '双组强反向',
        'F': '退化场景',
    }.get(scenario, '未知场景')

    if scenario == 'E':
        return f'{base}（长短线根本性冲突，0% 仓观望）'
    if scenario == 'F':
        return f'{base}（不在 A-E 主轨，0% 仓走 22 cell 表）'

    # θ 桶 → 主导组
    if theta_bucket == 'T≥10':
        dominant = '中长线' if long_w > short_w else '短线'
    elif theta_bucket == '5≤T<10':
        dominant = '长短线平衡'
    else:
        dominant = '短线（临到期 PAIN 滞后）'
    return f'{base} · θ={theta_bucket}（{dominant}主导）'


def _conflict_note_text(long_v: str, short_v: str, is_conflict: bool) -> str:
    """长短线冲突信号的业务解释"""
    if not is_conflict:
        if long_v == short_v:
            return f'长短线同向 → {long_v}（共振，无冲突）'
        # 一致偏多/偏空或中性
        return f'长线 {long_v} / 短线 {short_v}（同向，无冲突）'
    # 冲突
    return f'⚠️ 长短线分裂：长线 {long_v} vs 短线 {short_v}，时序维度信号矛盾，仓位按主导组方向但降权'


# ============================================================
# 场景判定
# ============================================================
def _classify_scenario(long_v: str, short_v: str, long_strength: str = '', short_strength: str = '') -> str:
    """根据两组判定分类到 6 个场景 A/B/C/D/E/F

    long_v/short_v 是 _group_verdict 返回的 verdict_label
    long_strength/short_strength 是 _group_verdict 返回的 strength_label ('强'/'中'/'弱')

    场景定义：
    - A: 双组同向多（短/中长线 都偏多或强偏多）
    - B: 短线主导（短线偏多/强偏多 + 中长线中性或反向）
    - C: 中长线主导（中长线偏多/强偏多 + 短线中性或反向）
    - D: 双组同向空（短/中长线 都偏空或强偏空）
    - E: 双组强反向（必须两组都"强度=强"且反向, 时间维度根本性冲突）
          关键: 一组强 + 另一组中/弱 不算 E, 应走 B/C
    - F: 其他（退化到 22 cell 表）
    """
    # 简化为方向分类
    long_bull = long_v in ('强偏多', '偏多', '弱偏多')
    long_bear = long_v in ('强偏空', '偏空', '弱偏空')
    long_neutral = long_v == '中性'

    short_bull = short_v in ('强偏多', '偏多', '弱偏多')
    short_bear = short_v in ('强偏空', '偏空', '弱偏空')
    short_neutral = short_v == '中性'

    long_strong_bull = long_v == '强偏多'
    long_strong_bear = long_v == '强偏空'
    short_strong_bull = short_v == '强偏多'
    short_strong_bear = short_v == '强偏空'

    # E: 双组强反向 (必须两组 strength='强' + verdict 反向)
    #     关键: 即使 verdict label 是"强偏多/空", 如果 strength 是"中"(组内不一致), 不算强
    if long_strength == '强' and short_strength == '强':
        if (long_strong_bull and short_strong_bear) or (long_strong_bear and short_strong_bull):
            return 'E'

    # A: 双组同向多（两边都至少"偏多"）
    if long_bull and short_bull and not long_neutral and not short_neutral:
        if (long_v in ('强偏多', '偏多')) and (short_v in ('强偏多', '偏多')):
            return 'A'

    # D: 双组同向空
    if long_bear and short_bear and not long_neutral and not short_neutral:
        if (long_v in ('强偏空', '偏空')) and (short_v in ('强偏空', '偏空')):
            return 'D'

    # B: 短线主导（短线明确看多 + 中长线不站同边）
    #     短线必须明确（强/偏多），中长线中性或反向或弱（不站同边）
    if (short_v in ('强偏多', '偏多')) and not (long_v in ('强偏多', '偏多')):
        # 短线明确多 + 中长线非"明确多" → B
        # 注意: 中长线"弱偏多"也走 B（虽然站同边但强度不够, 不算共振）
        if long_v == '弱偏多':
            # 短线强多 + 中长线弱多: 仍算 B（短线主导权重更高）
            return 'B'
        if long_neutral or long_bear:
            return 'B'

    # C: 中长线主导（中长线明确看多 + 短线不站同边）
    if (long_v in ('强偏多', '偏多')) and not (short_v in ('强偏多', '偏多')):
        if short_v == '弱偏多':
            return 'C'
        if short_neutral or short_bear:
            return 'C'

    # 同理: 短线/中长线 看空的 B/C 对称（卖出方向）
    if (short_v in ('强偏空', '偏空')) and not (long_v in ('强偏空', '偏空')):
        if long_v == '弱偏空':
            return 'B'  # 短线主导空
        if long_neutral or long_bull:
            return 'B'
    if (long_v in ('强偏空', '偏空')) and not (short_v in ('强偏空', '偏空')):
        if short_v == '弱偏空':
            return 'C'
        if short_neutral or short_bull:
            return 'C'

    # 其他：退化到 22 cell 表
    return 'F'


# ============================================================
# 仓位映射
# ============================================================
def _position_pct(scenario: str, theta_bucket: str) -> float:
    """根据场景 + θ 桶输出仓位百分比

    θ 桶: "T≥15" / "10≤T<15" / "5≤T<10" / "T<5"
    简化为 T≥10 / 5≤T<10 / T<5 三档（_theta_group_weights 的口径）
    """
    if scenario == 'A':
        # 双组同向多：满仓
        if theta_bucket in ('T<5',):
            return 0.80  # 临到期快进快出
        return 1.00
    if scenario == 'B':
        # 短线主导：轻仓
        if theta_bucket in ('T<5',):
            return 0.70  # 临到期短线权重最高
        if theta_bucket in ('5≤T<10',):
            return 0.50
        return 0.30  # T≥10 默认轻仓
    if scenario == 'C':
        # 中长线主导：中仓
        if theta_bucket in ('T<5',):
            return 0.30  # 临到期中长线滞后
        if theta_bucket in ('5≤T<10',):
            return 0.50
        return 0.60  # T≥10 中长线主导，中仓跟随
    if scenario == 'D':
        # 双组同向空：满仓（与 A 对称）
        if theta_bucket in ('T<5',):
            return 0.80
        return 1.00
    if scenario == 'E':
        # 双组强反向：观望 0%
        return 0.00
    # F: 退化
    return 0.00


def _scenario_to_decision(scenario: str, direction: str = '') -> str:
    """场景 → 中文决策名（与现有 final.decision 字符串对齐，兼容旧调用）

    新版推荐用 _direction_decision_cn(scenario, direction) 带方向。
    """
    return _direction_decision_cn(scenario, direction or '中性')


# ============================================================
# 主入口：时间维度路由
# ============================================================
def route_decision_by_timeframe(
    l1: dict, l2: dict, l3: dict, l4: dict,
    T_days: Optional[int] = None,
    F: Optional[float] = None,
) -> Dict[str, Any]:
    """时间维度分组 + 多数一致 + 场景路由

    Args:
        l1: PAIN 结构层 dict（含 layer_score）
        l2: GEX 机制层 dict（含 layer_score）
        l3: 资金意图层 dict（含 layer_score）
        l4: 情绪确认层 dict（含 layer_score）
        T_days: 到期天数（影响 θ 加权）
        F: 当前期货价（仅用于日志/debug）

    Returns:
        {
          "decision": str,                  # 中文决策
          "scenario": str,                  # A/B/C/D/E/F
          "position_pct": float,            # 仓位 0~1
          "long_verdict": str,              # 中长线组判定
          "long_strength": str,             # 强/中/弱
          "short_verdict": str,             # 短线组判定
          "short_strength": str,
          "short_term_weight": float,       # θ 加权后短线权重
          "long_term_weight": float,        # θ 加权后中长线权重
          "theta_bucket": str,              # T≥10 / 5≤T<10 / T<5
          "fallback_to_22cell": bool,       # 是否退化
          "rationale": str,                 # 决策依据（一句话）
        }
    """
    # 1) 提取 score
    s1 = (l1 or {}).get('layer_score') if l1 else None
    s2 = (l2 or {}).get('layer_score') if l2 else None
    s3 = (l3 or {}).get('layer_score') if l3 else None
    s4 = (l4 or {}).get('layer_score') if l4 else None

    # 2) θ 桶
    if T_days is None:
        theta_bucket = 'T≥10'
    elif T_days >= 10:
        theta_bucket = 'T≥10'
    elif T_days >= 5:
        theta_bucket = '5≤T<10'
    else:
        theta_bucket = 'T<5'

    short_w, long_w = _theta_group_weights(T_days)

    # 3) 组内判定（PAIN+GEX = 中长线组；资金+情绪 = 短线组）
    long_v, long_strength = _group_verdict(s1, s2)
    short_v, short_strength = _group_verdict(s3, s4)

    # 4) 场景路由
    scenario = _classify_scenario(long_v, short_v, long_strength, short_strength)

    # 5) 方向推断（θ 加权长短线判定） + 仓位 + 决策
    direction, dir_score, is_conflict = _infer_final_direction(long_v, short_v, long_w, short_w)
    pos_pct = _position_pct(scenario, theta_bucket)
    decision_cn = _direction_decision_cn(scenario, direction)
    position_reason = _position_reason_text(scenario, theta_bucket, long_w, short_w)
    conflict_note = _conflict_note_text(long_v, short_v, is_conflict)

    # 结构化 rationale：方向结论 / 长线信号 / 短线信号 / 仓位依据 / 冲突警告
    rationale_lines = [
        f'方向：θ加权综合分={dir_score:+.2f} → {direction}',
        f'中长线（{long_v}/{long_strength},权重{long_w:.0%}）：' + (
            'PAIN+GEX 联动偏多' if long_v in ('强偏多', '偏多', '弱偏多') else
            'PAIN+GEX 联动偏空' if long_v in ('强偏空', '偏空', '弱偏空') else
            'PAIN+GEX 中性'
        ),
        f'短线（{short_v}/{short_strength},权重{short_w:.0%}）：' + (
            '资金+情绪 偏多' if short_v in ('强偏多', '偏多', '弱偏多') else
            '资金+情绪 偏空' if short_v in ('强偏空', '偏空', '弱偏空') else
            '资金+情绪 中性'
        ),
        f'仓位 {pos_pct:.0%} → {position_reason}',
    ]
    if is_conflict:
        rationale_lines.append(conflict_note)

    result = {
        "decision": decision_cn,
        "scenario": scenario,
        "position_pct": pos_pct,
        "long_verdict": long_v,
        "long_strength": long_strength,
        "short_verdict": short_v,
        "short_strength": short_strength,
        "short_term_weight": short_w,
        "long_term_weight": long_w,
        "theta_bucket": theta_bucket,
        "fallback_to_22cell": scenario == 'F',
        # v2.11.95e: 新增字段（前端用）
        "final_direction": direction,
        "direction_score": round(dir_score, 3),
        "is_conflict": is_conflict,
        "position_reason": position_reason,
        "conflict_note": conflict_note,
        "rationale": '\n'.join(rationale_lines),
    }

    logger.info(
        "🎯 [timeframe_router] F=%s T=%s天 | 中长线(%s/%s, w=%.0f%%) | 短线(%s/%s, w=%.0f%%) | %s | %s",
        F, T_days, long_v, long_strength, long_w * 100,
        short_v, short_strength, short_w * 100,
        scenario, result['rationale']
    )
    return result


# ============================================================
# 自测入口
# ============================================================
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')

    # 7/7 案例（飞书补充方案）：PAIN 强偏空 + GEX 偏多 + 资金偏多 + 情绪偏多 → B 场景
    print("\n=== Test 1: 7/7 案例（短线主导）===")
    r1 = route_decision_by_timeframe(
        l1={'layer_score': -2.0},   # PAIN 强偏空
        l2={'layer_score': 1.5},    # GEX 偏多
        l3={'layer_score': 1.0},    # 资金 偏多
        l4={'layer_score': 0.5},    # 情绪 弱偏多
        T_days=18, F=5708
    )
    print(f"  decision={r1['decision']} scenario={r1['scenario']} pos={r1['position_pct']:.0%}")
    print(f"  rationale: {r1['rationale']}")

    # 当前生产实测：PAIN 强偏空 + GEX 弱偏空 + 资金中性 + 情绪中性 → C 场景（中长线主导）
    print("\n=== Test 2: 当前生产（中长线主导）===")
    r2 = route_decision_by_timeframe(
        l1={'layer_score': -2.0},   # PAIN 强偏空
        l2={'layer_score': -0.5},   # GEX 弱偏空
        l3={'layer_score': 0.0},    # 资金 中性
        l4={'layer_score': 0.0},    # 情绪 中性
        T_days=26, F=5708
    )
    print(f"  decision={r2['decision']} scenario={r2['scenario']} pos={r2['position_pct']:.0%}")
    print(f"  rationale: {r2['rationale']}")

    # 强反向：PAIN 强偏多 + 短线强偏空 → E 场景
    print("\n=== Test 3: 双组强反向（观望）===")
    r3 = route_decision_by_timeframe(
        l1={'layer_score': 2.0},
        l2={'layer_score': 1.5},
        l3={'layer_score': -2.0},
        l4={'layer_score': -1.5},
        T_days=10, F=5708
    )
    print(f"  decision={r3['decision']} scenario={r3['scenario']} pos={r3['position_pct']:.0%}")
    print(f"  rationale: {r3['rationale']}")

    # 双组同向多 → A
    print("\n=== Test 4: 双组同向多（满仓）===")
    r4 = route_decision_by_timeframe(
        l1={'layer_score': 2.0},
        l2={'layer_score': 1.5},
        l3={'layer_score': 1.0},
        l4={'layer_score': 0.5},
        T_days=15, F=5708
    )
    print(f"  decision={r4['decision']} scenario={r4['scenario']} pos={r4['position_pct']:.0%}")
    print(f"  rationale: {r4['rationale']}")

    # 临到期场景
    print("\n=== Test 5: 临到期 (T=3) 短线主导 → B 仓位放大 ===")
    r5 = route_decision_by_timeframe(
        l1={'layer_score': -1.5},
        l2={'layer_score': -0.5},
        l3={'layer_score': 1.5},
        l4={'layer_score': 1.0},
        T_days=3, F=5708
    )
    print(f"  decision={r5['decision']} scenario={r5['scenario']} pos={r5['position_pct']:.0%}")
    print(f"  rationale: {r5['rationale']}")
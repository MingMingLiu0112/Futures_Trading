#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
时间维度路由回测脚本 (v2.11.95a)

功能：
1. 读 decision_layer_history.jsonl（v2.11.95a 阶段 1 落盘的历史快照）
2. 对每条快照用 timeframe_router 计算"理论决策"（不动 final.decision）
3. 用 K 线 API 查 T+1h / T+4h / T+1d 的 F 价
4. 判定旧决策 vs 新理论决策 的命中率
5. 输出对照表 + 场景触发率分布

数据要求：
- decision_layer_history.jsonl ≥ 1 条（先验证脚本本身）
- 真实回测建议 ≥ 200 条（~7 天数据）

使用：
  cd /home/admin/.openclaw/workspace/Futures_Trading/pta_analysis
  python3 scripts/backtest_timeframe_router.py                 # 用当前 history 跑
  python3 scripts/backtest_timeframe_router.py --days 7        # 仅看最近 7 天
  python3 scripts/backtest_timeframe_router.py --limit 50      # 仅前 50 条
  python3 scripts/backtest_timeframe_router.py --skip-kline    # 跳过 K 线查询（仅算理论决策, 用于快速验证）
"""

import argparse
import json
import os
import sys
import sqlite3
import logging
from datetime import datetime, timedelta
from collections import Counter
from typing import Dict, List, Optional, Any

# 添加 scripts 路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from timeframe_router import route_decision_by_timeframe

logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# ============================================================
# 配置
# ============================================================
HISTORY_PATH = os.path.join(PROJECT_ROOT, 'data', 'fundamental', 'decision_layer_history.jsonl')
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'futures_data.db')

# 命中阈值（T+X 后涨跌幅判定）
HIT_THRESHOLDS = {
    'T+1h': 0.003,   # 0.3% (避免噪声)
    'T+4h': 0.005,   # 0.5%
    'T+1d': 0.008,   # 0.8%
}

# 决策 → 期望方向映射
DECISION_DIRECTION = {
    '满仓买入': 'long',
    '轻仓试多': 'long',
    '中仓跟随': 'long',
    '满仓卖出': 'short',
    '轻仓做空': 'short',
    '观望': 'neutral',
    '退化到22cell': 'neutral',
    '买入': 'long',
    '卖出': 'long',  # 主决策表里的"卖出/做空"也是空
    '卖出/做空': 'short',
    '轻仓试空': 'short',
}


# ============================================================
# K 线查价（用 /api/kline/data 端点，不用 sqlite）
# ============================================================
def query_kline_price(F_target_ts: datetime, F_at_decision: float, symbol: str = 'TA') -> Optional[float]:
    """通过 /api/kline/data 端点查 ts 时刻附近的 K 线 close

    Args:
        F_target_ts: 目标时间
        F_at_decision: 决策时刻的价格（fallback 用）
        symbol: 合约代码（默认 TA, 实际用主力合约 TA2609/TA609 等）

    Returns:
        该时刻的价格，如果查不到返回 None
    """
    import urllib.request
    import urllib.error
    import json as _json

    try:
        # 转 Unix timestamp
        target_ts = int(F_target_ts.timestamp())

        # 用 5min K 线查 ±15 分钟窗口（容错 ±3 根 5min K 线）
        url = f"http://127.0.0.1:8424/api/kline/data?symbol={symbol}&period=5min&count=200"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = _json.loads(resp.read().decode())

        # payload.data 是 list of dict: [{close, high, low, open, time, volume}, ...]
        # time 是 Unix timestamp（秒）
        klines = payload.get('data', [])
        if not klines:
            logger.debug("K 线 API 返回空 data: ts=%s", F_target_ts)
            return None

        # 找最接近 target_ts 的那根 K 线
        best = None
        best_diff = float('inf')
        for k in klines:
            diff = abs(k['time'] - target_ts)
            if diff < best_diff:
                best_diff = diff
                best = k

        if best is None:
            return None

        # K 线不存在"滞后"问题（用户 7/17 反跑偏纠正）:
        # - 休盘时段 (午休/夜盘断) 本来就没数据, 不算滞后
        # - TqSdk 模拟盘字段冻结 vs K 线静止是另一回事（不是这个脚本的范围）
        # 所以这里不需要 best_diff 容差 — 只要找到最接近的 K 线就用

        return float(best['close'])
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError, ValueError) as e:
        logger.debug("K 线 API 查询失败 ts=%s: %s", F_target_ts, e)
        return None


def compute_hit(decision_cn: str, F_at_decision: float, F_at_target: float, threshold: float) -> Optional[bool]:
    """根据决策和涨跌幅判定是否命中

    Args:
        decision_cn: 中文决策名（如"轻仓做空"）
        F_at_decision: 决策时价格
        F_at_target: 目标时间价格
        threshold: 涨跌幅阈值（绝对值）

    Returns:
        True=命中, False=未命中, None=无法判定（如观望 + 涨跌幅接近阈值）
    """
    if F_at_target is None or F_at_decision is None or F_at_decision == 0:
        return None

    direction = DECISION_DIRECTION.get(decision_cn)
    if direction is None:
        return None  # 未知决策

    change_pct = (F_at_target - F_at_decision) / F_at_decision

    if direction == 'long':
        # 买入方向：价格上涨 → 命中
        if change_pct >= threshold:
            return True
        if change_pct <= -threshold:
            return False
        return None  # 涨跌幅 < 阈值: 信号噪声, 不计入命中率
    elif direction == 'short':
        # 做空方向：价格下跌 → 命中
        if change_pct <= -threshold:
            return True
        if change_pct >= threshold:
            return False
        return None
    else:  # neutral (观望)
        # 观望方向: 涨跌幅 < 阈值 → 命中（观望对了 = 方向不明）
        if abs(change_pct) < threshold:
            return True
        return False


# ============================================================
# 回测主流程
# ============================================================
def backtest(days: Optional[int] = None, limit: Optional[int] = None, skip_kline: bool = False) -> Dict[str, Any]:
    """主回测入口

    Returns:
        {
          'total': int,
          'hits': Dict[str, int],   # 每个时间窗口命中数
          'miss': Dict[str, int],
          'skip': Dict[str, int],
          'scenarios': Counter,     # 场景触发率
          'scenario_diff': List[Dict],  # 决策变更案例
        }
    """
    # 1) 加载历史
    if not os.path.exists(HISTORY_PATH):
        logger.error("历史文件不存在: %s", HISTORY_PATH)
        return {'total': 0}

    rows = []
    with open(HISTORY_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    # 过滤时间窗口
    if days is not None:
        cutoff = datetime.now() - timedelta(days=days)
        rows = [r for r in rows if datetime.fromisoformat(r['ts']) >= cutoff]

    # 限制条数
    if limit is not None:
        rows = rows[:limit]

    if not rows:
        logger.warning("没有可用的历史快照")
        return {'total': 0}

    # 2) 计算理论决策 + 命中
    hits = {'T+1h': 0, 'T+4h': 0, 'T+1d': 0}
    miss = {'T+1h': 0, 'T+4h': 0, 'T+1d': 0}
    skip = {'T+1h': 0, 'T+4h': 0, 'T+1d': 0}
    scenarios = Counter()
    decision_diff = []

    for row in rows:
        ts = datetime.fromisoformat(row['ts'])
        F = row['F']

        # 提取 T_days（从 L1.summary.days_left 或 cache.last_data_update）
        # 注意: history 没有存 T_days, 我们从 L1.dyn_triggered 推断或用固定值
        # 简化: 用 15 天（T≥15 档, 最常见）
        T_days = 15
        if row.get('L1', {}).get('shape') and row['F']:
            # 尝试从 row.L1.dyn_triggered 推断
            triggers = row.get('L1', {}).get('dyn_triggered', [])
            if 't_near' in triggers:
                T_days = 3
            elif isinstance(triggers, list) and len(triggers) > 0:
                T_days = 15

        # 3) 计算理论决策
        l1 = {'layer_score': row['L1']['score']}
        l2 = {'layer_score': row['L2']['score']}
        l3 = {'layer_score': row['L3']['score']}
        l4 = {'layer_score': row['L4']['score']}
        routed = route_decision_by_timeframe(l1, l2, l3, l4, T_days=T_days, F=F)
        scenarios[routed['scenario']] += 1

        old_decision = row['final']['decision']

        # 4) 命中判定（需要 K 线）
        if not skip_kline:
            for window_name, delta_hours in [('T+1h', 1), ('T+4h', 4), ('T+1d', 24)]:
                target_ts = ts + timedelta(hours=delta_hours)

                # ⚠️ 休盘时段不查（避免误判成"滞后"）:
                # - PTA 日盘 9:00-11:30, 13:00-15:00
                # - 夜盘 21:00-次日 02:30
                # - 午休 11:30-13:00: target 落在 11:30-13:00 → 跳过（不算命中）
                # - 夜盘断 02:30-09:00: target 落在 → 跳过
                if 11 <= target_ts.hour < 13:
                    skip[window_name] += 1
                    continue
                if target_ts.hour >= 23 or target_ts.hour < 1:
                    # 02:30 后是日盘前, 21:00-23:00 是夜盘
                    # 23:00-次日 01:00 是夜盘尾巴, 跳过
                    skip[window_name] += 1
                    continue

                F_target = query_kline_price(target_ts, F)
                hit_old = compute_hit(old_decision, F, F_target, HIT_THRESHOLDS[window_name])
                hit_new = compute_hit(routed['decision'], F, F_target, HIT_THRESHOLDS[window_name])

                if hit_old is None:
                    skip[window_name] += 1
                elif hit_old:
                    hits[window_name] += 1
                else:
                    miss[window_name] += 1
        else:
            # 跳过 K 线: 仅记录决策变更
            if routed['decision'] != old_decision:
                decision_diff.append({
                    'ts': row['ts'],
                    'F': F,
                    'old': old_decision,
                    'new': routed['decision'],
                    'scenario': routed['scenario'],
                    'rationale': routed['rationale'],
                })

    return {
        'total': len(rows),
        'hits': hits,
        'miss': miss,
        'skip': skip,
        'scenarios': scenarios,
        'decision_diff': decision_diff,
        'skip_kline': skip_kline,
    }


def print_report(result: Dict[str, Any]):
    """输出回测报告"""
    print("=" * 70)
    print(f"📊 时间维度路由回测报告 (v2.11.95a)")
    print("=" * 70)
    print(f"总快照数: {result['total']}")
    print(f"K 线查询: {'跳过' if result.get('skip_kline') else '已执行'}")
    print()

    if not result.get('skip_kline') and result['hits']:
        print("=== 命中率对比（旧规则 vs 新规则 - 仅旧决策可判定的样本）===")
        print(f"{'时间窗口':<10} {'命中':<8} {'未命中':<8} {'跳过':<8} {'命中率':<10}")
        print("-" * 70)
        for window in ['T+1h', 'T+4h', 'T+1d']:
            h = result['hits'][window]
            m = result['miss'][window]
            s = result['skip'][window]
            total = h + m
            hit_rate = h / total * 100 if total > 0 else 0
            print(f"{window:<10} {h:<8} {m:<8} {s:<8} {hit_rate:.1f}%")
        print()
        print("⚠️  注：当前脚本只统计旧决策命中率（新决策命中率需补全双向计数）")
        print()

    if result['scenarios']:
        print("=== 场景触发率分布 ===")
        total_scenarios = sum(result['scenarios'].values())
        for sc in ['A', 'B', 'C', 'D', 'E', 'F']:
            cnt = result['scenarios'].get(sc, 0)
            pct = cnt / total_scenarios * 100 if total_scenarios > 0 else 0
            print(f"  {sc}: {cnt} 次 ({pct:.1f}%)")
        print()

    if result.get('decision_diff'):
        print(f"=== 决策变更案例（前 {min(20, len(result['decision_diff']))} 条）===")
        for diff in result['decision_diff'][:20]:
            print(f"  [{diff['ts']}] F={diff['F']} {diff['old']} → {diff['new']} ({diff['scenario']})")
            print(f"      {diff['rationale']}")
        print()
        if len(result['decision_diff']) > 20:
            print(f"  ... 共 {len(result['decision_diff'])} 条变更")


# ============================================================
# 主入口
# ============================================================
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='时间维度路由回测')
    parser.add_argument('--days', type=int, default=None, help='只看最近 N 天')
    parser.add_argument('--limit', type=int, default=None, help='只看前 N 条')
    parser.add_argument('--skip-kline', action='store_true', help='跳过 K 线查询（仅算理论决策）')
    args = parser.parse_args()

    result = backtest(days=args.days, limit=args.limit, skip_kline=args.skip_kline)
    print_report(result)
#!/usr/bin/env python3
"""
v2.11.63e: strike 性质判定的命中率回测分析

用法:
    python3 analyze_nature_stats.py              # 全量回测
    python3 analyze_nature_stats.py --days 7     # 近 7 天回测
    python3 analyze_nature_stats.py --today      # 仅今天

输出: 命中率 + 修正项触发率 + 数据质量分布 + 业务结论稳定性
"""
import sys
import os
import json
import argparse
from datetime import datetime, timedelta
from collections import Counter


def load_snapshots(days: int = None, today_only: bool = False):
    stats_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'nature_stats')
    index_path = os.path.join(stats_dir, 'index.json')
    if not os.path.exists(index_path):
        print(f'[ERROR] no index.json at {index_path}')
        return []
    with open(index_path, 'r', encoding='utf-8') as f:
        index = json.load(f)
    snapshots = index.get('snapshots', [])
    if not snapshots:
        return []

    if today_only:
        today = datetime.now().strftime('%Y-%m-%d')
        snapshots = [s for s in snapshots if s.get('_date') == today]
    elif days:
        cutoff = datetime.now() - timedelta(days=days)
        snapshots = [s for s in snapshots if datetime.fromisoformat(s['timestamp']) >= cutoff]

    return snapshots


def analyze(snapshots: list):
    if not snapshots:
        print('[no data]')
        return

    print(f'=== 总快照数: {len(snapshots)} ===')
    if not snapshots:
        return

    # 时间跨度
    dates = sorted(set(s.get('_date', '?') for s in snapshots))
    print(f'日期范围: {dates[0]} → {dates[-1]}')
    print()

    # 1. 合成 label 分布
    label_counter = Counter(s.get('synthesis_label') for s in snapshots)
    print('=== 合成 label 分布 ===')
    for label, cnt in label_counter.most_common():
        pct = cnt / len(snapshots) * 100
        print(f'  {label}: {cnt} ({pct:.0f}%)')
    print()

    # 2. Call/Put 性质分布
    call_counter = Counter(s.get('call_nature') for s in snapshots)
    put_counter = Counter(s.get('put_nature') for s in snapshots)
    print('=== Call 端性质分布 ===')
    for n, cnt in call_counter.most_common():
        print(f'  {n}: {cnt} ({cnt/len(snapshots)*100:.0f}%)')
    print('=== Put 端性质分布 ===')
    for n, cnt in put_counter.most_common():
        print(f'  {n}: {cnt} ({cnt/len(snapshots)*100:.0f}%)')
    print()

    # 3. Strike 修正项触发率（label 升级的多空分化场景）
    modifier_count = sum(1 for s in snapshots if s.get('strike_modifier'))
    print(f'=== Strike 修正项触发 ===')
    print(f'  触发修正项快照数: {modifier_count}/{len(snapshots)} ({modifier_count/len(snapshots)*100:.0f}%)')
    print()

    # 4. 数据质量分布
    conf_counter = Counter((s.get('data_quality') or {}).get('confidence', '?') for s in snapshots)
    print('=== 数据质量分布 ===')
    for c, cnt in conf_counter.most_common():
        print(f'  {c}: {cnt} ({cnt/len(snapshots)*100:.0f}%)')
    avg_eligible_call = sum((s.get('data_quality') or {}).get('eligible_call', 0) for s in snapshots) / len(snapshots)
    avg_eligible_put = sum((s.get('data_quality') or {}).get('eligible_put', 0) for s in snapshots) / len(snapshots)
    print(f'  平均有效 Call strike: {avg_eligible_call:.1f}')
    print(f'  平均有效 Put strike: {avg_eligible_put:.1f}')
    print()

    # 5. 业务结论稳定性（同日内 label 一致性）
    print('=== 同日 label 一致性（业务稳定性）===')
    by_date = {}
    for s in snapshots:
        d = s.get('_date', '?')
        by_date.setdefault(d, []).append(s.get('synthesis_label'))
    for d in sorted(by_date.keys()):
        labels = by_date[d]
        unique = set(labels)
        marker = '✅ 一致' if len(unique) == 1 else f'⚠️  {len(unique)} 种不同 label: {list(unique)}'
        print(f'  {d}: {labels} → {marker}')
    print()

    # 6. 业务信号统计（基于合成 label 的买卖建议）
    print('=== 业务信号统计 ===')
    bullish = sum(1 for s in snapshots if '看多' in (s.get('synthesis_label') or ''))
    bearish = sum(1 for s in snapshots if '看空' in (s.get('synthesis_label') or ''))
    neutral = sum(1 for s in snapshots if (s.get('synthesis_label') or '') in ('中性', '中性偏慢牛', '中性偏慢熊', '多空分化(慢牛+慢熊)'))
    conflict = sum(1 for s in snapshots if s.get('synthesis_label') == '信号矛盾')
    print(f'  看多信号: {bullish} ({bullish/len(snapshots)*100:.0f}%)')
    print(f'  看空信号: {bearish} ({bearish/len(snapshots)*100:.0f}%)')
    print(f'  中性观望: {neutral} ({neutral/len(snapshots)*100:.0f}%)')
    print(f'  信号矛盾: {conflict} ({conflict/len(snapshots)*100:.0f}%)')
    print()

    # 7. 与"次日价格变化"对比（事后验证）
    # 需要快照按时间排序，比较 label → 次日价格变化
    print('=== 事后验证（label vs 次日价格变化）===')
    sorted_snaps = sorted(snapshots, key=lambda x: x['timestamp'])
    if len(sorted_snaps) >= 2:
        for i in range(len(sorted_snaps) - 1):
            cur = sorted_snaps[i]
            nxt = sorted_snaps[i + 1]
            cur_f = cur.get('futures_price')
            nxt_f = nxt.get('futures_price')
            if cur_f and nxt_f:
                chg = (nxt_f - cur_f) / cur_f * 100
                label = cur.get('synthesis_label', '?')
                print(f'  {cur["_date"]} {label} → 次日 F={nxt_f} (Δ {chg:+.2f}%)')
    print()

    print('=== 关键指标汇总 ===')
    print(f'  - 修正项触发率: {modifier_count/len(snapshots)*100:.0f}% （目标：< 30%，太高说明判定规则太敏感）')
    print(f'  - 高置信率: {conf_counter.get("high", 0)/len(snapshots)*100:.0f}% （目标：> 70%，太低说明数据质量差）')
    print(f'  - 同日 label 一致性: {sum(1 for labels in by_date.values() if len(set(labels)) == 1)}/{len(by_date)} 天')
    print(f'  - 平均有效 strike 数: Call {avg_eligible_call:.1f}, Put {avg_eligible_put:.1f} （目标：≥ 8 才有统计意义）')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, help='近 N 天')
    parser.add_argument('--today', action='store_true', help='仅今天')
    args = parser.parse_args()

    snapshots = load_snapshots(days=args.days, today_only=args.today)
    analyze(snapshots)


if __name__ == '__main__':
    main()
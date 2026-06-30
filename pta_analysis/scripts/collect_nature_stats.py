#!/usr/bin/env python3
"""
v2.11.63e: 收集 strike 级别性质判定的历史快照，做实战统计验证

用法:
    python3 collect_nature_stats.py --once       # 单次快照
    python3 collect_nature_stats.py --schedule   # 每天 15:00 收盘后跑一次（用 cron 触发）

输出:
    data/nature_stats/snapshot_YYYY-MM-DD_HHMMSS.json
    data/nature_stats/index.json (按日期索引，便于回测)
"""
import sys
import os
import json
import argparse
from datetime import datetime, timedelta

# 强制使用项目 Python 环境
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import generate_daily_report as g


def collect_snapshot(note: str = '') -> dict:
    """收集一次当前所有 strike 级别判定结果 + 元数据"""
    # 重置模块缓存（避免循环引用）
    for mod in list(sys.modules):
        if 'generate_daily_report' in mod:
            del sys.modules[mod]
    import generate_daily_report as g

    # 直接 fetch alert_data
    import urllib.request
    req = urllib.request.Request('http://47.100.97.88/api/iv_smile/alert_data')
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read())
    except Exception as e:
        return {'error': f'fetch alert_data failed: {e}'}

    rows = d.get('rows', [])
    if not rows:
        return {'error': 'no rows'}

    # 算性质判定
    ns = g._compute_nature_and_synthesis(
        iv_table_rows=rows,
        atm_strike=d.get('atm_strike'),
        max_pain=d.get('max_pain'),
        futures_price=d.get('futures_price'),
        pcr_now=None, pcr_call_oi=None, pcr_put_oi=None,
    )

    snapshot = {
        'timestamp': datetime.now().isoformat(),
        'note': note,
        'futures_price': d.get('futures_price'),
        'atm_strike': d.get('atm_strike'),
        'max_pain': d.get('max_pain'),
        'baseline_label': d.get('baseline_label'),
        'last_update': d.get('last_update'),
        # 顶层判定
        'call_nature': ns.get('call', {}).get('nature'),
        'put_nature': ns.get('put', {}).get('nature'),
        'synthesis_label': ns.get('synthesis', {}).get('label'),
        'synthesis_intensity': ns.get('synthesis', {}).get('intensity'),
        'strike_modifier': ns.get('synthesis', {}).get('strike_modifier'),
        'shape': ns.get('shape'),
        'position': ns.get('position'),
        # 数据质量
        'data_quality': ns.get('data_quality'),
        # 完整 bucket（用于事后分析）
        'call_buckets': {k: v for k, v in ns.get('call_role', {}).items() if isinstance(v, list)},
        'put_buckets': {k: v for k, v in ns.get('put_role', {}).items() if isinstance(v, list)},
        # OI/IV 全档汇总
        'put_oi_pct': ns.get('put', {}).get('oi_delta_pct'),
        'call_oi_pct': ns.get('call', {}).get('oi_delta_pct'),
        'put_iv_pp': ns.get('put', {}).get('iv_delta_pp'),
        'call_iv_pp': ns.get('call', {}).get('iv_delta_pp'),
    }

    return snapshot


def save_snapshot(snapshot: dict):
    """保存快照到 data/nature_stats/"""
    stats_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'nature_stats')
    os.makedirs(stats_dir, exist_ok=True)

    ts = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    snap_path = os.path.join(stats_dir, f'snapshot_{ts}.json')
    with open(snap_path, 'w', encoding='utf-8') as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    print(f'[saved] {snap_path}')

    # 更新 index.json（按日期聚合）
    index_path = os.path.join(stats_dir, 'index.json')
    if os.path.exists(index_path):
        with open(index_path, 'r', encoding='utf-8') as f:
            index = json.load(f)
    else:
        index = {'snapshots': []}

    # 按日期分组（一日多次快照也保留）
    date_str = ts[:10]
    snapshot['_snapshot_file'] = os.path.basename(snap_path)
    snapshot['_date'] = date_str
    index['snapshots'].append(snapshot)

    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print(f'[updated] {index_path} (total {len(index["snapshots"])} snapshots)')


def print_summary(snapshot: dict):
    """打印快照摘要"""
    if snapshot.get('error'):
        print(f'[ERROR] {snapshot["error"]}')
        return

    dq = snapshot.get('data_quality') or {}
    print(f'[{snapshot["timestamp"]}] F={snapshot.get("futures_price")} MP={snapshot.get("max_pain")}')
    print(f'  形态={snapshot.get("shape")} 位置={snapshot.get("position")}')
    print(f'  Call={snapshot.get("call_nature")} Put={snapshot.get("put_nature")}')
    print(f'  合成: {snapshot.get("synthesis_label")} ({snapshot.get("synthesis_intensity")})')
    print(f'  Strike 修正: {snapshot.get("strike_modifier") or "(无)"}')
    print(f'  数据质量: {dq.get("confidence", "?")} (Call {dq.get("eligible_call", 0)}/{dq.get("total_strikes", 0)} Put {dq.get("eligible_put", 0)}/{dq.get("total_strikes", 0)})')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true', help='单次快照')
    parser.add_argument('--schedule', action='store_true', help='每天 15:05 收盘后跑一次')
    parser.add_argument('--note', default='', help='备注（如"6/30 早盘"/"测试"）')
    args = parser.parse_args()

    if args.once or args.schedule:
        snapshot = collect_snapshot(note=args.note)
        print_summary(snapshot)
        save_snapshot(snapshot)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
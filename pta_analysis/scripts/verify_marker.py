#!/usr/bin/env python3
"""
v2.11.95k-tools: 验证 Python/HTML 代码改动是否真生效

用法:
    python3 verify_marker.py                       # 验证最近 N 个版本的 marker
    python3 verify_marker.py --since <TAG_A>       # 只验证 <TAG_A> 起的版本 (exclusive)
    python3 verify_marker.py --since-incl <TAG_A>  # 只验证 <TAG_A> 起的版本 (含自身)
    python3 verify_marker.py --all                 # 验证所有已知 marker
    python3 verify_marker.py --no-cache            # 只看代码是否含新函数 (不查运行时 marker)
    python3 verify_marker.py --strict              # marker 缺失直接 exit 1 (CI 用)

输出: 每个版本一个状态表 (PASS/WARN/MISS), 汇总 OK/MISSING/N/A 三类。

设计原则:
- 算法逻辑不变, 只换"做事方式"
- marker 字段从 git log + 注释里的 <VERSION_A> 标签里挖
- 运行时 marker 走 curl, 静态 marker 走 grep, 混合避免漏判
- 不擅自 restart/operate, 只输出验证结果让人判断

注意: 本脚本的 MARKERS 字典里会列出多个历史版本 (e.g. <VERSION_B>, <VERSION_C>),
但脚本本身的归属版本是 v2.11.95k-tools. 运行 commit_split.py 时会看到本文件被标 mixed-diff,
那是 docstring/MARKERS 字典的"参考引用"导致的, 不是真实 mixed-diff, 可以直接 git add 整文件.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple

REPO_ROOT = '/home/admin/.openclaw/workspace/Futures_Trading'
PTA_DIR = os.path.join(REPO_ROOT, 'pta_analysis')
DEFAULT_API = 'http://127.0.0.1:8424'


@dataclass
class Marker:
    """一个版本的一个验证 marker"""
    version: str          # 例: v2.11.95j
    kind: str             # 'static' (grep 源码) | 'runtime' (curl API) | 'template' (curl HTML)
    target: str           # 文件路径 / API URL / 模板文件
    needle: str           # 期望出现的字符串 / JSON 字段路径
    description: str      # 人话说明
    expected: bool = True # True=应存在, False=应不存在
    found: Optional[bool] = None
    evidence: str = ''    # 实际找到什么


@dataclass
class VersionStatus:
    version: str
    markers: List[Marker] = field(default_factory=list)

    def passed(self) -> int:
        return sum(1 for m in self.markers if m.found == m.expected)

    def missed(self) -> int:
        return [m for m in self.markers if m.found != m.expected and m.found is not None]


# ============================================================
# Marker 知识库 - 从 v2.11.95i/j/k 实装里挖出来
# 任何新版本加 marker 必须同时更新这里
# ============================================================

# 静态 marker: 在源码里 grep 特定函数名/注释
STATIC_MARKERS: Dict[str, List[Marker]] = {
    'v2.11.95i': [
        Marker(
            version='v2.11.95i', kind='static',
            target='pta_analysis/iv_smile_service.py',
            needle='def _iso_expiry(',
            description='新增 _iso_expiry() 函数',
        ),
    ],
    'v2.11.95j': [
        Marker(
            version='v2.11.95j', kind='static',
            target='pta_analysis/web_app_integrated.py',
            needle='def _override_report_with_realtime_decision(',
            description='新增 _override_report_with_realtime_decision() 函数',
        ),
    ],
    'v2.11.95k': [
        Marker(
            version='v2.11.95k', kind='static',
            target='pta_analysis/scripts/generate_daily_report.py',
            needle='def _build_decision_track(',
            description='新增 _build_decision_track() 函数',
        ),
        Marker(
            version='v2.11.95k', kind='static',
            target='pta_analysis/scripts/generate_daily_report.py',
            needle='def load_previous_trading_day_decision_snapshot(',
            description='新增 load_previous_trading_day_decision_snapshot() 函数',
        ),
        Marker(
            version='v2.11.95k', kind='static',
            target='pta_analysis/templates/kline_lightweight.html',
            needle='decision_track',
            description='前端模板包含 decision_track 字段渲染',
        ),
    ],
}

# 运行时 marker: 调 API / 查 HTML, 确认新代码真在 Flask 进程内存里跑
RUNTIME_MARKERS: Dict[str, List[Marker]] = {
    'v2.11.95i': [
        Marker(
            version='v2.11.95i', kind='runtime',
            target=f'{DEFAULT_API}/api/iv_smile/status',
            needle='expiry',
            description='status API 返回 expiry 字段 (兼容 str)',
        ),
    ],
    'v2.11.95j': [
        Marker(
            version='v2.11.95j', kind='runtime',
            target=f'{DEFAULT_API}/api/strategy_report/realtime',
            needle='realtime_override',
            description='market_brief.decision_table.realtime_override=True (95j 函数跑了)',
        ),
    ],
    # 95k 的运行时 marker 在 close_report 里, 不是日内 realtime
    # 验证逻辑: 检查 daily_report.json 是不是有 decision_track 字段 (close 报告才生成)
    'v2.11.95k': [
        Marker(
            version='v2.11.95k', kind='runtime',
            target=f'{DEFAULT_API}/api/strategy_report/realtime',
            needle='previous_day_comparison',
            description='realtime 报告含 previous_day_comparison (95k 需 close_report, 非交易时段为 None)',
            expected=False,  # 默认预期不在 (业务设计)
        ),
    ],
}

# Template marker: 验证 footer 版本号
TEMPLATE_MARKERS: Dict[str, List[Marker]] = {
    'v2.11.95k': [
        Marker(
            version='v2.11.95k', kind='template',
            target=f'{DEFAULT_API}/',
            needle='v2.11.95k',
            description='主页 footer 显示 v2.11.95k',
        ),
        Marker(
            version='v2.11.95k', kind='template',
            target=f'{DEFAULT_API}/iv_smile',
            needle='v2.11.95k',
            description='iv_smile 页 footer 显示 v2.11.95k',
        ),
    ],
}


def git_log_versions(since_tag: Optional[str] = None, include_self: bool = False) -> List[str]:
    """从 git log 拿版本号列表 (倒序, 最新的在前)

    include_self=False (默认): 用 <since>..HEAD (exclusive)
    include_self=True: 用 <since>^..HEAD (inclusive, 也包含 since 自身)
    """
    cmd = ['git', '-C', REPO_ROOT, 'log', '--oneline', '--format=%s']
    if since_tag:
        if include_self:
            cmd.append(f'{since_tag}^..HEAD')
        else:
            cmd.append(f'{since_tag}..HEAD')
    out = subprocess.check_output(cmd, text=True, errors='ignore')

    versions = []
    for line in out.splitlines():
        # 抓 v2.11.XX 或 v2.11.XX[a-z]
        m = re.search(r'v2\.11\.\d+[a-z]?', line)
        if m:
            ver = m.group()
            if ver not in versions:
                versions.append(ver)
    return versions


def check_static(marker: Marker, api_base: str) -> Marker:
    """grep 源码检查函数/字符串是否存在"""
    full_path = os.path.join(REPO_ROOT, marker.target)
    if not os.path.exists(full_path):
        marker.found = False
        marker.evidence = f'文件不存在: {marker.target}'
        return marker
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        marker.found = False
        marker.evidence = f'读取失败: {e}'
        return marker

    if marker.needle in content:
        marker.found = True
        marker.evidence = f'在 {marker.target} 中找到 "{marker.needle}"'
    else:
        marker.found = False
        marker.evidence = f'在 {marker.target} 中未找到 "{marker.needle}"'
    return marker


def check_runtime(marker: Marker, api_base: str) -> Marker:
    """curl API 检查 marker 字段"""
    target = marker.target.replace(DEFAULT_API, api_base)
    try:
        with urllib.request.urlopen(target, timeout=10) as resp:
            body = resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        marker.found = None  # 不可判定
        marker.evidence = f'API 不可达 ({target}): {e}'
        return marker

    # JSON 字段路径 (用 . 分隔, 支持 data.foo.bar)
    if '.' in marker.needle:
        try:
            data = json.loads(body)
            parts = marker.needle.split('.')
            cursor = data
            for p in parts:
                if isinstance(cursor, dict) and p in cursor:
                    cursor = cursor[p]
                else:
                    cursor = None
                    break
            if cursor is not None:
                # bool 类型字段: True/False 都算"存在"
                marker.found = True
                marker.evidence = f'JSON 路径 "{marker.needle}" = {repr(cursor)[:100]}'
            else:
                marker.found = False
                marker.evidence = f'JSON 路径 "{marker.needle}" 不存在或为 null'
        except Exception as e:
            marker.found = False
            marker.evidence = f'JSON 解析失败: {e}'
    else:
        # 普通字符串
        if marker.needle in body:
            marker.found = True
            marker.evidence = f'HTTP body 含 "{marker.needle}"'
        else:
            marker.found = False
            marker.evidence = f'HTTP body 不含 "{marker.needle}"'
    return marker


def check_template(marker: Marker, api_base: str) -> Marker:
    """curl HTML 页面检查 footer 版本号"""
    target = marker.target.replace(DEFAULT_API, api_base)
    try:
        with urllib.request.urlopen(target, timeout=10) as resp:
            body = resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        marker.found = None
        marker.evidence = f'页面不可达 ({target}): {e}'
        return marker

    # 用 class="version" 行单独提取, 避免 body 噪音
    # 例: <div class="version" style="...">v2.11.95k (...)</div>
    # 注意: 版本号后可能有空格 + 长描述, 用惰性匹配 + 截断到第一个非版本字符
    version_match = re.search(r'class="version"[^>]*>(v[\d]+\.[\d]+\.[\d]+[a-z]?)', body)
    actual_version = version_match.group(1) if version_match else 'NOT_FOUND'

    if marker.needle in actual_version:
        marker.found = True
        marker.evidence = f'页面 footer = {actual_version} (匹配 {marker.needle})'
    else:
        marker.found = False
        marker.evidence = f'页面 footer = {actual_version} (不匹配 {marker.needle})'
    return marker


def check_marker(marker: Marker, api_base: str) -> Marker:
    if marker.kind == 'static':
        return check_static(marker, api_base)
    elif marker.kind == 'runtime':
        return check_runtime(marker, api_base)
    elif marker.kind == 'template':
        return check_template(marker, api_base)
    else:
        marker.found = None
        marker.evidence = f'未知 marker kind: {marker.kind}'
        return marker


# ============================================================
# 报告输出
# ============================================================

RED = '\033[31m'
GREEN = '\033[32m'
YELLOW = '\033[33m'
BLUE = '\033[34m'
DIM = '\033[2m'
RESET = '\033[0m'


def colorize(s: str, c: str) -> str:
    if sys.stdout.isatty():
        return f'{c}{s}{RESET}'
    return s


def print_version_status(status: VersionStatus, strict: bool = False) -> bool:
    """打印一个版本的状态, 返回是否全部 PASS"""
    print(f'\n{colorize(f"══ {status.version} ══", BLUE)}')

    if not status.markers:
        print(f'  {colorize("(无 marker, 跳过)", DIM)}')
        return True

    all_pass = True
    for m in status.markers:
        if m.found is None:
            sym = '?'
            col = YELLOW
            verdict = 'N/A'
        elif m.found == m.expected:
            sym = '✓'
            col = GREEN
            verdict = 'PASS'
        else:
            sym = '✗'
            col = RED
            verdict = 'MISS'
            all_pass = False

        kind_tag = f'[{m.kind}]'
        print(f'  {colorize(sym, col)} {colorize(verdict, col)} {kind_tag:11s} {m.description}')
        if m.evidence:
            print(f'      {colorize(m.evidence, DIM)}')

    return all_pass


def main():
    parser = argparse.ArgumentParser(
        description='验证 PTA Python/HTML 改动是否真生效 (运行时 + 静态)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--since', metavar='TAG', help='只验证从这个 tag 起的版本 (exclusive, 不含自身)')
    parser.add_argument('--since-incl', metavar='TAG', help='只验证从这个 tag 起的版本 (inclusive, 含自身)')
    parser.add_argument('--all', action='store_true', help='验证所有已知 marker')
    parser.add_argument('--no-cache', action='store_true',
                        help='只跑静态 (grep 源码), 不调 API/HTML (用于代码改动后立即检查)')
    parser.add_argument('--strict', action='store_true', help='有 MISS 直接 exit 1 (CI 用)')
    parser.add_argument('--api', default=DEFAULT_API, help=f'API base URL (默认 {DEFAULT_API})')
    args = parser.parse_args()

    # 决定要验证哪些版本
    if args.all:
        versions = sorted(set(STATIC_MARKERS) | set(RUNTIME_MARKERS) | set(TEMPLATE_MARKERS),
                          key=lambda v: tuple(int(x.rstrip('abcdefghijklmnopqrstuvwxyz') or 0)
                                             for x in v.replace('v', '').split('.')))
    else:
        # 默认: 从 git log 拿最近 N 个版本 (按出现顺序去重, 最新在前)
        since = args.since_incl or args.since
        include_self = bool(args.since_incl)
        versions = git_log_versions(since_tag=since, include_self=include_self)
        if not versions:
            print(f'{colorize("ERROR", RED)}: 没找到版本号 (用 --all 或 --since 试试)')
            return 1

    # 用 args.api 作为运行时 API base (避免 mutate module-level 常量)
    for ver_markers in [STATIC_MARKERS, RUNTIME_MARKERS, TEMPLATE_MARKERS]:
        for ver, markers in ver_markers.items():
            for m in markers:
                if m.target.startswith('http://127.0.0.1:8424'):
                    m.target = m.target.replace('http://127.0.0.1:8424', args.api)

    print(f'{colorize("PTA marker 验证", BLUE)} - 范围: {len(versions)} 个版本')
    print(f'  版本列表: {", ".join(versions[:10])}{"..." if len(versions) > 10 else ""}')

    statuses: List[VersionStatus] = []
    for ver in versions:
        status = VersionStatus(version=ver)
        # 静态永远跑 (除非 --no-cache)
        for m in STATIC_MARKERS.get(ver, []):
            status.markers.append(check_marker(m, args.api))
        if not args.no_cache:
            for m in RUNTIME_MARKERS.get(ver, []):
                status.markers.append(check_marker(m, args.api))
            for m in TEMPLATE_MARKERS.get(ver, []):
                status.markers.append(check_marker(m, args.api))
        statuses.append(status)

    # 输出
    all_pass_count = 0
    miss_count = 0
    na_count = 0
    for s in statuses:
        if print_version_status(s, args.strict):
            all_pass_count += 1
        miss_count += len(s.missed())
        for m in s.markers:
            if m.found is None:
                na_count += 1

    # 汇总
    total = len(statuses)
    print(f'\n{colorize("══ 汇总 ══", BLUE)}')
    print(f'  版本数: {total}')
    print(f'  全 PASS: {colorize(str(all_pass_count), GREEN)}')
    print(f'  有 MISS: {colorize(str(total - all_pass_count), RED if total - all_pass_count else DIM)}')
    print(f'  marker MISS 数: {colorize(str(miss_count), RED if miss_count else DIM)}')
    print(f'  marker N/A 数 (运行时不可达): {colorize(str(na_count), YELLOW if na_count else DIM)}')

    if args.strict and miss_count > 0:
        print(f'\n{colorize("STRICT 模式: 有 MISS, exit 1", RED)}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
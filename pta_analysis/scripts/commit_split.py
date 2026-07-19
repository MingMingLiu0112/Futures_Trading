#!/usr/bin/env python3
"""
v2.11.95k-tools: 把 disk 上的 mixed-diff 按子版本标签自动分组

用法:
    python3 commit_split.py                  # 只输出建议, 不执行
    python3 commit_split.py --apply          # 自动 git add + commit (会弹确认)
    python3 commit_split.py --tag            # 自动 git tag (在每个 commit 后)
    python3 commit_split.py --dry            # 输出 git 命令, 不执行 (供脚本调用)

背景:
    当 PTA/Futures_Trading 一次迭代产生 "多个有独立追溯价值的子版本" (e.g. v2.11.95i/j/k),
    改动在 disk 上是 mixed-diff 混在同一文件的不同 hunk. 直接 git add file.py = 失去 a/b/c 追溯.

这个脚本做的事:
1. 扫所有 disk 上的改动文件 (git diff --name-only)
2. 在每个文件的 +/- 行里 grep v2.11.X[a-z] 标签
3. 按文件归到子版本 dict: { '95i': [files], '95j': [files], ... }
4. 检测 mixed-diff: 同一文件有多个版本标签 -> warn (必须按 hunk 拆)
5. 排除 cache/snapshot/data/runtime 文件 (防止污染 commit/tag)
6. 输出建议的 git add 序列 + commit message 模板

设计原则:
- 算法逻辑不变, 只换"做事方式" (用户 2026-07-19)
- 默认 --dry, 不擅自执行任何 git 写操作
- 排除清单 hardcode (PTA 数据目录约定), 防止 git add -A 全包带脏数据
"""

import argparse
import os
import re
import subprocess
import sys
from collections import defaultdict
from typing import Dict, List, Set, Tuple, Optional

REPO_ROOT = '/home/admin/.openclaw/workspace/Futures_Trading'
# 允许 v2.11.95[a-z] (业务子版本) 和 v2.11.95[a-z]-tools (工具子版本)
VERSION_RE = re.compile(r'v2\.11\.\d+[a-z]?(?:-[a-z]+)?')

# 数据/缓存/snapshot 排除清单 (不进 commit/tag, 跟 pta-mixed-diff-multi-commit-split skill 一致)
EXCLUDE_PATTERNS = [
    # data/ 目录下全部
    'pta_analysis/data/',
    # 临时文件
    '__pycache__',
    '.pyc',
    '.bak',
    '.swp',
    '.swo',
    # 备份目录
    '.backup_',
    # 运行时日志
    'web_app_error.log',
    'web_app.log',
    'web_app_new.log',
    'iv_smile.log',
    'option_fetch.log',
    # 调试输出
    '/tmp/',
]

# 文件扩展名白名单 (只处理代码文件)
CODE_EXTENSIONS = {'.py', '.html', '.js', '.css', '.json', '.yaml', '.yml', '.md', '.sh'}


# ============================================================
# 颜色输出
# ============================================================

RED = '\033[31m'
GREEN = '\033[32m'
YELLOW = '\033[33m'
BLUE = '\033[34m'
CYAN = '\033[36m'
DIM = '\033[2m'
BOLD = '\033[1m'
RESET = '\033[0m'


def colorize(s: str, c: str) -> str:
    if sys.stdout.isatty():
        return f'{c}{s}{RESET}'
    return s


# ============================================================
# Git 操作
# ============================================================

def git_diff_name_only() -> List[str]:
    """返回所有 disk 上改动的文件 (相对仓库根)"""
    out = subprocess.check_output(
        ['git', '-C', REPO_ROOT, 'diff', '--name-only'],
        text=True, errors='ignore'
    )
    files = [l.strip() for l in out.splitlines() if l.strip()]
    return files


def git_untracked_files() -> List[str]:
    """返回 untracked 文件 (相对仓库根)"""
    out = subprocess.check_output(
        ['git', '-C', REPO_ROOT, 'ls-files', '--others', '--exclude-standard'],
        text=True, errors='ignore'
    )
    files = [l.strip() for l in out.splitlines() if l.strip()]
    return files


def git_diff_for_file(rel_path: str) -> List[str]:
    """返回某文件的 + 行 (新增)"""
    out = subprocess.check_output(
        ['git', '-C', REPO_ROOT, 'diff', '--', rel_path],
        text=True, errors='ignore'
    )
    added_lines = []
    for line in out.splitlines():
        if line.startswith('+') and not line.startswith('+++'):
            added_lines.append(line[1:])  # 去掉前导 +
    return added_lines


def is_excluded(rel_path: str) -> bool:
    """是否在排除清单 (cache/data/snapshot/runtime)"""
    return any(pat in rel_path for pat in EXCLUDE_PATTERNS)


def is_code_file(rel_path: str) -> bool:
    """是否是代码文件"""
    _, ext = os.path.splitext(rel_path)
    return ext in CODE_EXTENSIONS


# ============================================================
# 核心分析: 把每个文件归到子版本
# ============================================================


class FileVersionGroup:
    """一个文件 + 它归属的子版本 (可能多个 = mixed-diff)"""

    def __init__(self, rel_path: str):
        self.rel_path = rel_path
        self.versions: List[str] = []  # 顺序: 在 diff 里出现顺序
        self.excluded: bool = is_excluded(rel_path)
        self.is_code: bool = is_code_file(rel_path)

    def add_version(self, ver: str):
        if ver not in self.versions:
            self.versions.append(ver)

    @property
    def is_mixed(self) -> bool:
        return len(self.versions) > 1

    @property
    def primary_version(self) -> Optional[str]:
        """mixed-diff 时返回第一个出现的版本 (作为 fallback 归属)"""
        return self.versions[0] if self.versions else None

    def __repr__(self):
        tags = '/'.join(self.versions) if self.versions else '(no tag)'
        excl = ' [EXCLUDED]' if self.excluded else ''
        return f'{self.rel_path} -> {tags}{excl}'


def analyze_file(rel_path: str) -> FileVersionGroup:
    """扫一个文件的所有新增行, 找 v2.11.X[a-z] 标签

    处理两类文件:
    - git tracked 且 disk 有改动: 用 git diff 取 + 行
    - untracked (新文件): 直接读整个文件 (因为没"旧版"对照)
    """
    group = FileVersionGroup(rel_path)
    try:
        # 先判断是否 tracked
        r = subprocess.run(
            ['git', '-C', REPO_ROOT, 'ls-files', '--error-unmatch', '--', rel_path],
            capture_output=True, text=True
        )
        is_tracked = (r.returncode == 0)

        if is_tracked:
            added_lines = git_diff_for_file(rel_path)
        else:
            # untracked: 直接读整个文件
            full = os.path.join(REPO_ROOT, rel_path)
            if os.path.exists(full):
                with open(full, 'r', encoding='utf-8', errors='ignore') as f:
                    added_lines = f.read().splitlines()
            else:
                added_lines = []
    except subprocess.CalledProcessError:
        return group

    for line in added_lines:
        for m in VERSION_RE.finditer(line):
            group.add_version(m.group())

    return group


def analyze_all() -> Dict[str, List[FileVersionGroup]]:
    """扫所有改动文件, 按归属子版本分组

    返回: { 'v2.11.95i': [FileVersionGroup, ...], 'v2.11.95j': [...], ... }
    """
    modified = git_diff_name_only()
    untracked = git_untracked_files()
    all_changed = sorted(set(modified) | set(untracked))

    # file -> group
    file_groups: Dict[str, FileVersionGroup] = {}
    for f in all_changed:
        group = analyze_file(f)
        file_groups[f] = group

    # 按子版本归类 (排除清单也归, 但单独标记)
    version_to_files: Dict[str, List[FileVersionGroup]] = defaultdict(list)
    unknown_files: List[FileVersionGroup] = []
    excluded_files: List[FileVersionGroup] = []

    for f, g in file_groups.items():
        if g.excluded:
            excluded_files.append(g)
            continue
        if not g.versions:
            unknown_files.append(g)
            continue
        # 归到每个它出现的子版本 (mixed-diff 时会出现在多个组)
        for v in g.versions:
            version_to_files[v].append(g)

    # unknown 也加进结果, 方便报告
    if unknown_files:
        version_to_files['__unknown__'] = unknown_files
    if excluded_files:
        version_to_files['__excluded__'] = excluded_files

    return dict(version_to_files), file_groups


# ============================================================
# 输出
# ============================================================

def print_banner(s: str):
    print(f'\n{colorize(s, BOLD + BLUE)}')
    print(colorize('=' * len(s), BLUE))


def print_group_summary(version_to_files: Dict[str, List[FileVersionGroup]],
                        file_groups: Dict[str, FileVersionGroup]):
    print_banner('PTA commit_split 分析结果')

    total_changed = len(file_groups)
    print(f'  改动文件总数: {total_changed}')
    print(f'  按归属归类版本数: {len([k for k in version_to_files if not k.startswith("__")])}')

    # mixed-diff warn
    mixed = [g for g in file_groups.values() if g.is_mixed and not g.excluded]
    if mixed:
        print(f'\n  {colorize("⚠️  mixed-diff 警告", YELLOW)}: {len(mixed)} 个文件含多个版本标签')
        for g in mixed:
            print(f'    {colorize(g.rel_path, YELLOW)} -> {"/".join(g.versions)}')
        print(f'    {colorize("(必须按 hunk 拆, 不能简单 git add)", DIM)}')

    # unknown 文件
    unknowns = version_to_files.get('__unknown__', [])
    if unknowns:
        print(f'\n  {colorize("❓ 未标注版本的文件", YELLOW)}: {len(unknowns)} 个')
        for g in unknowns[:10]:
            print(f'    {colorize(g.rel_path, DIM)}')
        if len(unknowns) > 10:
            print(f'    {colorize(f"... 还有 {len(unknowns) - 10} 个", DIM)}')

    # excluded 文件
    excluded = version_to_files.get('__excluded__', [])
    if excluded:
        print(f'\n  {colorize("🚫 排除文件 (不进 commit/tag)", DIM)}: {len(excluded)} 个')
        for g in excluded[:5]:
            print(f'    {colorize(g.rel_path, DIM)}')
        if len(excluded) > 5:
            print(f'    {colorize(f"... 还有 {len(excluded) - 5} 个", DIM)}')


def print_suggested_commands(version_to_files: Dict[str, List[FileVersionGroup]],
                              file_groups: Dict[str, FileVersionGroup]):
    """输出建议的 git add + commit + tag 序列"""
    print_banner('建议的 git 命令序列')

    versions = sorted([v for v in version_to_files if not v.startswith('__')])
    if not versions:
        print(f'  {colorize("(没有需要 commit 的版本, disk 干净或全是 cache)", DIM)}')
        return

    # 收集所有 mixed-diff 文件 (在"建议"段统一提醒, 不用每个版本都重复)
    mixed_files = [g for g in file_groups.values() if g.is_mixed and not g.excluded]
    mixed_paths = set(g.rel_path for g in mixed_files)

    for v in versions:
        groups = version_to_files[v]
        clean_groups = [g for g in groups if not g.is_mixed]
        if not clean_groups:
            continue

        # 如果 v 是 mixed_files 里出现的主版本, 仍然 add (用户确认后)
        # 简化: 全部按 clean add 处理
        print(f'\n  {colorize(f"[{v}]", CYAN)} -> {len(clean_groups)} 个文件')
        # git add
        add_files = [g.rel_path for g in clean_groups]
        add_cmd = 'git add ' + ' '.join(f'-- {f}' for f in add_files)
        print(f'    {colorize(add_cmd, DIM)}')
        # 准备 commit message 路径 (避免 f-string 嵌套 + quote 冲突)
        ver_no_dot = v.replace('.', '')
        msg_path = f'/tmp/commit_msg_{ver_no_dot}.md'
        tag_msg_path = f'/tmp/tag_msg_{ver_no_dot}.md'
        # commit
        print(f'    {colorize("# 然后编辑 commit message:", DIM)} {v}: <一句话总结>')
        print(f'    {colorize(f"git commit -F {msg_path}", DIM)}')
        # tag
        print(f'    {colorize("# 打 tag (用 commit SHA, 不要裸 tag):", DIM)}')
        print(f'    {colorize("#   SHA=$(git rev-list -n 1 HEAD)", DIM)}')
        print(f'    {colorize(f"git tag -a {v} <SHA> -F {tag_msg_path}", DIM)}')

    # mixed-diff 特别提醒
    if mixed_files:
        print(f'\n{colorize("── mixed-diff 文件需要人工决定 ──", YELLOW)}')
        for g in mixed_files:
            primary = g.versions[0] if g.versions else '?'
            ref_count = max(0, len(g.versions) - 1)
            print(f'  {colorize(g.rel_path, YELLOW)} -> 主版本: {primary} (其余 {ref_count} 个为参考引用)')
            # 避免 f-string 嵌套反斜杠, 用变量先拼
            suggest_cmd = f'git add -- {g.rel_path} && git commit -m "{primary}: <说明>"'
            print(f'    {colorize(suggest_cmd, DIM)}')


def print_commit_message_template(version_to_files: Dict[str, List[FileVersionGroup]]):
    """输出 commit message 模板"""
    print_banner('commit message 模板 (复制到 /tmp/commit_msg_XXX.md)')

    versions = sorted([v for v in version_to_files if not v.startswith('__')])
    for v in versions:
        groups = version_to_files[v]
        clean_groups = [g for g in groups if not g.is_mixed]
        file_list = '\n'.join(f'  - {g.rel_path}: <一句话描述改动>' for g in clean_groups)
        template = f"""\
{v}: <一句话标题 (动名词 + 范围)>

根因: <一段话描述为什么改>

修复: <一段话描述怎么改>

F1 {file_list if clean_groups else '<no file>'}

不动: 业务判定逻辑 / cache 写入逻辑 / 数据格式。
"""
        print(f'\n{colorize(f"── {v} ──", CYAN)}')
        print(template)


# ============================================================
# 执行 (--apply 模式)
# ============================================================

def apply_split(version_to_files: Dict[str, List[FileVersionGroup]]):
    """实际执行 git add + commit (会问确认)"""
    versions = sorted([v for v in version_to_files if not v.startswith('__')])
    if not versions:
        print(f'{colorize("(没有需要 commit 的内容)", DIM)}')
        return 0

    print_banner('准备执行 (会问 y/N 确认)')
    for v in versions:
        groups = version_to_files[v]
        clean_groups = [g for g in groups if not g.is_mixed]
        if not clean_groups:
            print(f'  {colorize(f"[{v}] 跳过 (mixed-diff)", YELLOW)}')
            continue
        print(f'  {colorize(f"[{v}]", CYAN)}: {len(clean_groups)} 文件')

    print()
    resp = input(f'{colorize("确认执行? (y/N): ", BOLD)}').strip().lower()
    if resp != 'y':
        print(f'{colorize("取消", DIM)}')
        return 0

    # 逐版本 add + commit
    for v in versions:
        groups = version_to_files[v]
        clean_groups = [g for g in groups if not g.is_mixed]
        if not clean_groups:
            continue

        # git add
        for g in clean_groups:
            subprocess.run(['git', '-C', REPO_ROOT, 'add', '--', g.rel_path], check=True)

        # 准备 commit message (如果 /tmp 不存在, 用一个占位)
        ver_no_dot = v.replace('.', '')
        msg_path = f'/tmp/commit_msg_{ver_no_dot}.md'
        if not os.path.exists(msg_path):
            print(f'  {colorize(f"⚠ {msg_path} 不存在, 用占位 message", YELLOW)}')
            with open(msg_path, 'w') as f:
                f.write(f'{v}: <请补充 commit message>\n')

        r = subprocess.run(['git', '-C', REPO_ROOT, 'commit', '-F', msg_path])
        if r.returncode != 0:
            print(f'  {colorize(f"❌ {v} commit 失败 (rc={r.returncode})", RED)}')
            return r.returncode

        print(f'  {colorize(f"✓ {v} commit 完成", GREEN)}')

    return 0


# ============================================================
# 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='把 disk 上的 mixed-diff 按子版本标签自动分组',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--apply', action='store_true', help='自动 git add + commit (会问确认)')
    parser.add_argument('--dry', action='store_true', help='只输出 git 命令, 不执行')
    parser.add_argument('--msg-only', action='store_true', help='只输出 commit message 模板')
    args = parser.parse_args()

    # 1) 扫 disk
    version_to_files, file_groups = analyze_all()

    # 2) 输出汇总
    print_group_summary(version_to_files, file_groups)

    # 3) 输出建议
    if args.msg_only:
        print_commit_message_template(version_to_files)
    else:
        print_suggested_commands(version_to_files, file_groups)

    # 4) 执行 (仅 --apply)
    if args.apply and not args.dry:
        return apply_split(version_to_files)

    return 0


if __name__ == '__main__':
    sys.exit(main())
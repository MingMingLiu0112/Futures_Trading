#!/usr/bin/env bash
set -euo pipefail

# PTA Flask 日志兜底保护：超过阈值自动截断，避免系统盘被刷爆。
# 注意：使用 truncate 而不是 rm，避免进程仍持有 deleted inode 导致空间不释放。

MAX_BYTES=${MAX_BYTES:-524288000}  # 500 MiB
STATE_LOG=${STATE_LOG:-/tmp/pta_log_truncate_guard.log}

logs=(
  "/home/admin/.openclaw/workspace/Futures_Trading/pta_analysis/web_app.log"
  "/tmp/flask_pta.log"
)

for log in "${logs[@]}"; do
  [[ -f "$log" ]] || continue
  size=$(stat -c '%s' "$log" 2>/dev/null || echo 0)
  if [[ "$size" =~ ^[0-9]+$ ]] && (( size > MAX_BYTES )); then
    printf '%s truncate %s size=%s max=%s\n' "$(date '+%F %T')" "$log" "$size" "$MAX_BYTES" >> "$STATE_LOG"
    : > "$log"
  fi
done

#!/usr/bin/env bash
set -euo pipefail

# PTA Flask 内存兜底保护：RSS 超阈值时重启，避免小内存机器被吃满。
# 默认阈值 1.2GiB，可通过 MAX_RSS_KB 覆盖。

APP_DIR="/home/admin/.openclaw/workspace/Futures_Trading/pta_analysis"
PYTHON_BIN="/home/admin/.pyenv/versions/3.11.9/bin/python3"
PATTERN="^${PYTHON_BIN} web_app_integrated.py$"
MAX_RSS_KB=${MAX_RSS_KB:-1258291}
LOG=${LOG:-/tmp/pta_memory_guard.log}

pids=$(pgrep -f "$PATTERN" || true)
if [[ -z "$pids" ]]; then
  printf '%s app not running, starting\n' "$(date '+%F %T')" >> "$LOG"
  cd "$APP_DIR"
  PYTHONPATH="${PYTHONPATH:-/home/admin/.pyenv/versions/3.11.9/lib/python3.11/site-packages}" \
    nohup "$PYTHON_BIN" web_app_integrated.py > web_app.log 2> web_app_error.log &
  exit 0
fi

# 防止手工/守护重复拉起：多进程时只保留最新一个。
count=$(printf '%s\n' "$pids" | wc -l)
if (( count > 1 )); then
  newest=$(printf '%s\n' "$pids" | sort -n | tail -1)
  printf '%s multiple app processes: %s; keep %s\n' "$(date '+%F %T')" "$pids" "$newest" >> "$LOG"
  for old_pid in $pids; do
    [[ "$old_pid" == "$newest" ]] && continue
    kill "$old_pid" 2>/dev/null || true
  done
  sleep 3
  pids="$newest"
fi

pid=$(printf '%s\n' "$pids" | head -1)
rss=$(ps -o rss= -p "$pid" | awk '{print $1+0}')
if (( rss > MAX_RSS_KB )); then
  printf '%s rss=%sKB > %sKB, restarting pid=%s\n' "$(date '+%F %T')" "$rss" "$MAX_RSS_KB" "$pid" >> "$LOG"
  kill "$pid" || true
  sleep 3
  if kill -0 "$pid" 2>/dev/null; then
    kill -9 "$pid" || true
    sleep 1
  fi
  cd "$APP_DIR"
  : > web_app.log
  : > web_app_error.log
  PYTHONPATH="${PYTHONPATH:-/home/admin/.pyenv/versions/3.11.9/lib/python3.11/site-packages}" \
    nohup "$PYTHON_BIN" web_app_integrated.py > web_app.log 2> web_app_error.log &
fi

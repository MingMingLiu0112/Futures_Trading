#!/bin/bash
# 2026-07-04 修订：绝对路径 + 显式 PYTHONPATH（修复 systemd 启动时的 ModuleNotFoundError）
# - python 用绝对路径 /home/admin/.pyenv/versions/3.11.9/bin/python3，避免 shim 跳到 3.11.15
# - 显式 export PYTHONPATH，让 systemd 子进程也能找到 flask/tqsdk/akshare
set -e

cd /home/admin/.openclaw/workspace/Futures_Trading/pta_analysis

# ===== 1. 强制杀掉所有老进程（避免 pkill -f 匹配到当前shell/调用命令导致自杀）=====
python3 - <<'PYKILL'
import os, signal, subprocess, time
me = os.getpid()
out = subprocess.check_output(['ps', '-eo', 'pid,args'], text=True)
patterns = ('web_app_integrated.py', 'iv_smile_service')
for line in out.splitlines():
    parts = line.strip().split(None, 1)
    if len(parts) != 2:
        continue
    pid_s, args = parts
    try:
        pid = int(pid_s)
    except ValueError:
        continue
    if pid == me:
        continue
    if any(p in args for p in patterns) and 'python' in args:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
time.sleep(2)
PYKILL

# ===== 2. 加载 .env + 显式 PYTHONPATH =====
export $(cat .env | grep -v '^#' | xargs)
export PYTHONPATH=/home/admin/.pyenv/versions/3.11.9/lib/python3.11/site-packages

# ===== 3. 先停 systemd 服务（避免双实例占端口冲突） =====
if systemctl is-active --quiet web-app-pta.service 2>/dev/null; then
    echo "Stopping systemd web-app-pta.service first..."
    sudo systemctl stop web-app-pta.service 2>/dev/null || systemctl stop web-app-pta.service 2>/dev/null || true
    sleep 2
fi

# ===== 4. 用绝对路径启动服务 =====
nohup /home/admin/.pyenv/versions/3.11.9/bin/python3 web_app_integrated.py >> /tmp/flask.log 2>&1 &
NEW_PID=$!
echo "Started PID: $NEW_PID"
echo "PYTHONPATH=$PYTHONPATH"

# ===== 5. 验证启动 =====
sleep 8
if ps -p $NEW_PID > /dev/null 2>&1; then
    HTTP=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://127.0.0.1:8424/api/strategy_report/realtime 2>/dev/null || echo "000")
    if [ "$HTTP" = "200" ]; then
        echo "Service running. HTTP=$HTTP"
    else
        echo "WARN: Service started but HTTP=$HTTP (Flask may not be fully ready)"
    fi
else
    echo "ERROR: Process died immediately"
    tail -20 /tmp/flask.log
    exit 1
fi
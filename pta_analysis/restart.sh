#!/bin/bash
cd /home/admin/.openclaw/workspace/Futures_Trading/pta_analysis

# 强制杀掉所有老进程（避免 pkill -f 匹配到当前shell/调用命令导致自杀）
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

# 加载环境变量
export $(cat .env | grep -v '^#' | xargs)

# 启动服务
nohup python3 web_app_integrated.py >> /tmp/flask.log 2>&1 &
echo "Started PID: $!"
sleep 5
echo "Service running."

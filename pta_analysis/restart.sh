#!/bin/bash
# 重启脚本 - 彻底杀掉所有进程后再启动

cd /home/admin/.openclaw/workspace/Futures_Trading/pta_analysis

# 彻底杀掉所有 web_app_integrated.py 进程（包括子进程）
pkill -9 -f "web_app_integrated.py" 2>/dev/null

# 等待进程完全退出
sleep 2

# 确认已清理
if ps aux | grep -v grep | grep "web_app_integrated.py" > /dev/null; then
    echo "[WARN] 还有残留进程，强制重试..."
    pkill -9 -f "web_app_integrated.py" 2>/dev/null
    sleep 2
fi

echo "[$(date)] 启动新服务..."
nohup python3 web_app_integrated.py > /tmp/pta_web.log 2>&1 &
sleep 3

PID=$(ps aux | grep -v grep | grep "web_app_integrated.py" | awk '{print $2}' | head -1)
echo "[$(date)] 服务已启动 PID=$PID"
tail -5 /tmp/pta_web.log

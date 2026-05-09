#!/bin/bash
# 重启脚本 - 彻底杀掉所有进程后再启动

cd /home/admin/.openclaw/workspace/Futures_Trading/pta_analysis

echo "[$(date)] 1. 杀掉旧进程..."
pkill -9 -f "web_app_integrated.py" 2>/dev/null
sleep 2

# 检查是否还有残留（包括 fork 的子进程）
remaining=$(ps aux | grep -v grep | grep "web_app_integrated.py" | awk '{print $2}')
if [ -n "$remaining" ]; then
    echo "[WARN] 仍有残留进程: $remaining，再次杀掉..."
    for pid in $remaining; do
        pkill -9 -P $pid 2>/dev/null  # 杀掉该进程的子进程
    done
    pkill -9 -f "web_app_integrated.py" 2>/dev/null
    sleep 2
fi

# 清理可能的僵死进程
pkill -9 -f "tqsdk" 2>/dev/null
pkill -9 -f "_demo.py" 2>/dev/null

echo "[$(date)] 2. 确认端口已释放..."
if netstat -tlnp 2>/dev/null | grep ":8424 "; then
    echo "[ERROR] 端口8424仍被占用!"
    netstat -tlnp 2>/dev/null | grep ":8424 "
    exit 1
fi
echo "  端口8424已释放 ✓"

echo "[$(date)] 3. 启动新服务..."
nohup python3 web_app_integrated.py > /tmp/pta_web.log 2>&1 &
sleep 5

PID=$(ps aux | grep -v grep | grep "web_app_integrated.py" | awk '{print $2}' | head -1)
if [ -z "$PID" ]; then
    echo "[ERROR] 服务启动失败!"
    tail -20 /tmp/pta_web.log
    exit 1
fi

echo "[$(date)] ✓ 服务已启动 PID=$PID"
echo ""
echo "=== 最近日志 ==="
tail -10 /tmp/pta_web.log

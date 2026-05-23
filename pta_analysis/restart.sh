#!/bin/bash
cd /home/admin/.openclaw/workspace/Futures_Trading/pta_analysis

# 强制杀掉所有老进程
pkill -9 -f web_app_integrated 2>/dev/null
pkill -9 -f "iv_smile_service" 2>/dev/null
sleep 2

# 加载环境变量
export $(cat .env | grep -v '^#' | xargs)

# 启动服务
nohup python3 web_app_integrated.py >> /tmp/flask.log 2>&1 &
echo "Started PID: $!"
sleep 5
echo "Service running."

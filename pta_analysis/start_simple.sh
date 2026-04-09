#!/bin/bash
cd /home/admin/.openclaw/workspace/codeman/pta_analysis

# 清理旧进程
pkill -f "python3 web_app.py" 2>/dev/null || true
sleep 2

# 检查端口占用
for port in 8422 8423; do
  fuser -k $port/tcp 2>/dev/null || true
done

# 启动应用
echo "启动PTA分析平台..."
python3 web_app.py
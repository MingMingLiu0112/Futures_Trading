#!/bin/bash
# PTA分析平台启动脚本

WORKSPACE="/home/admin/.openclaw/workspace/codeman/pta_analysis"
cd "$WORKSPACE"

echo "========================================="
echo "PTA期货分析平台启动"
echo "========================================="

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到python3"
    exit 1
fi

# 检查依赖
echo "检查Python依赖..."
python3 -c "import flask, akshare, pandas, numpy" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "安装依赖..."
    pip install flask akshare pandas numpy -i https://pypi.tuna.tsinghua.edu.cn/simple
fi

# 检查缠论图表
if [ -f "charts/chan_bi_xd.png" ]; then
    echo "找到缠论图表: charts/chan_bi_xd.png"
    mkdir -p static
    cp charts/chan_bi_xd.png static/
else
    echo "警告: 未找到缠论图表"
fi

# 检查端口占用
PORT=8421
if netstat -tln | grep ":$PORT " > /dev/null; then
    echo "端口 $PORT 已被占用，尝试停止现有进程..."
    PID=$(lsof -ti:$PORT)
    if [ ! -z "$PID" ]; then
        kill -9 $PID
        sleep 2
    fi
fi

# 启动应用
echo "启动PTA分析平台..."
echo "访问地址: http://$(hostname -I | awk '{print $1}'):$PORT"
echo "          http://47.100.97.88:$PORT"
echo ""
echo "按 Ctrl+C 停止服务"

python3 web_app.py
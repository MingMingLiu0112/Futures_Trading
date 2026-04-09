#!/bin/bash
# 启动多品种期货分析平台

cd "$(dirname "$0")"

echo "================================================================"
echo "多品种期货分析平台启动脚本"
echo "================================================================"

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到python3，请先安装Python3"
    exit 1
fi

# 检查依赖
echo "检查Python依赖..."
pip3 install fastapi uvicorn jinja2 akshare pandas --quiet

# 启动服务
echo "启动多品种期货分析平台..."
echo "服务地址: http://0.0.0.0:8001"
echo "按 Ctrl+C 停止服务"
echo "================================================================"

python3 multi_variety_main.py
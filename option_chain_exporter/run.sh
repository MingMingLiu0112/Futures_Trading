#!/bin/bash

# 期权链数据Excel导出系统启动脚本

echo "启动期权链数据Excel导出系统..."

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "错误: Python3未安装"
    exit 1
fi

# 检查依赖
echo "检查Python依赖..."
pip3 install -r requirements.txt

# 创建必要的目录
mkdir -p exports
mkdir -p uploads

# 启动Flask应用
echo "启动Flask应用..."
echo "访问地址: http://localhost:5000"
echo "API接口:"
echo "  - GET /api/export/sample    # 导出示例数据Excel"
echo "  - GET /api/data/sample      # 获取示例数据JSON"
echo "  - GET /api/health           # 健康检查"

python3 main.py
#!/bin/bash

# IV曲线组件启动脚本

echo "🚀 启动隐含波动率曲线组件..."

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "❌ 未找到Python3，请先安装Python3"
    exit 1
fi

# 检查依赖
echo "📦 检查Python依赖..."
pip install -r requirements.txt

# 启动后端API
echo "🔧 启动后端API服务..."
python3 api.py &

# 获取进程ID
API_PID=$!

# 等待API启动
sleep 2

# 检查API是否运行
if curl -s http://localhost:5000/api/iv/current > /dev/null; then
    echo "✅ 后端API启动成功 (PID: $API_PID)"
    echo "🌐 访问地址: http://localhost:5000"
    echo ""
    echo "📊 可用API端点:"
    echo "  • 当前IV曲线: http://localhost:5000/api/iv/current?symbol=TA"
    echo "  • 前日IV曲线: http://localhost:5000/api/iv/previous?symbol=TA"
    echo "  • 曲线分析: http://localhost:5000/api/iv/analyze?symbol=TA"
    echo "  • 历史数据: http://localhost:5000/api/iv/history?symbol=TA&days=7"
    echo ""
    echo "🛑 停止服务: kill $API_PID"
else
    echo "❌ 后端API启动失败"
    kill $API_PID 2>/dev/null
    exit 1
fi

# 保持脚本运行
echo ""
echo "📝 按Ctrl+C停止服务"
wait $API_PID
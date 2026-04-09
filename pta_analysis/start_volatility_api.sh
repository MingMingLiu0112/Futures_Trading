#!/bin/bash
# 启动波动锥API服务

WORKSPACE="/home/admin/.openclaw/workspace/codeman/pta_analysis"
cd "$WORKSPACE"

echo "================================================"
echo "启动PTA期货波动锥API服务"
echo "工作目录: $WORKSPACE"
echo "================================================"

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到python3"
    exit 1
fi

# 检查必要的Python包
echo "检查Python依赖..."
REQUIRED_PACKAGES=("flask" "pandas" "numpy" "matplotlib" "scipy" "flask-cors")
for package in "${REQUIRED_PACKAGES[@]}"; do
    if ! python3 -c "import $package" &> /dev/null; then
        echo "安装缺失的包: $package"
        pip3 install "$package"
    fi
done

# 创建必要的目录
mkdir -p static
mkdir -p logs

# 停止已运行的进程
echo "检查已运行的进程..."
PID_FILE="volatility_api.pid"
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "停止旧进程 (PID: $OLD_PID)..."
        kill "$OLD_PID"
        sleep 2
    fi
    rm -f "$PID_FILE"
fi

# 启动API服务
echo "启动波动锥API服务..."
nohup python3 volatility_api.py > logs/volatility_api.log 2>&1 &
API_PID=$!
echo $API_PID > "$PID_FILE"

echo "API服务已启动 (PID: $API_PID)"
echo "日志文件: logs/volatility_api.log"
echo ""
echo "API端点:"
echo "  - 主页: http://localhost:5001/"
echo "  - 波动锥数据: http://localhost:5001/api/volatility/cone"
echo "  - IV百分位: http://localhost:5001/api/volatility/iv-percentile"
echo "  - 交易信号: http://localhost:5001/api/volatility/signals"
echo "  - 综合分析: http://localhost:5001/api/volatility/summary"
echo ""
echo "按 Ctrl+C 停止服务"
echo "================================================"

# 等待进程
wait $API_PID

# 清理
rm -f "$PID_FILE"
echo "服务已停止"
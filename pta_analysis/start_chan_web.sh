#!/bin/bash
# 启动缠论Web界面

set -e

echo "=========================================="
echo "  缠论Web界面启动脚本"
echo "=========================================="

# 检查Python环境
echo "检查Python环境..."
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到python3，请先安装Python 3"
    exit 1
fi

python_version=$(python3 --version | awk '{print $2}')
echo "✓ Python版本: $python_version"

# 检查依赖
echo -e "\n检查Python依赖..."
required_packages=("flask" "pandas" "numpy")

for package in "${required_packages[@]}"; do
    if python3 -c "import $package" 2>/dev/null; then
        echo "✓ $package 已安装"
    else
        echo "⚠ $package 未安装，尝试安装..."
        pip3 install $package
    fi
done

# 检查数据目录
echo -e "\n检查数据文件..."
data_file="data/ta509_daily.csv"
if [ -f "$data_file" ]; then
    echo "✓ 找到数据文件: $data_file"
    line_count=$(wc -l < "$data_file")
    echo "  数据行数: $line_count"
else
    echo "⚠ 未找到数据文件 $data_file"
    echo "  将使用模拟数据进行演示"
    
    # 创建示例数据目录
    mkdir -p data
    echo "创建示例数据文件..."
    cat > "$data_file" << EOF
datetime,open,high,low,close,volume
2024-04-01 09:00:00,6900.00,6920.00,6880.00,6910.00,10000
2024-04-01 09:01:00,6910.00,6930.00,6890.00,6920.00,12000
2024-04-01 09:02:00,6920.00,6940.00,6900.00,6930.00,11000
2024-04-01 09:03:00,6930.00,6950.00,6910.00,6940.00,13000
2024-04-01 09:04:00,6940.00,6960.00,6920.00,6950.00,14000
2024-04-01 09:05:00,6950.00,6970.00,6930.00,6960.00,15000
2024-04-01 09:06:00,6960.00,6980.00,6940.00,6970.00,16000
2024-04-01 09:07:00,6970.00,6990.00,6950.00,6980.00,17000
2024-04-01 09:08:00,6980.00,7000.00,6960.00,6990.00,18000
2024-04-01 09:09:00,6990.00,7010.00,6970.00,7000.00,19000
EOF
    echo "✓ 已创建示例数据文件"
fi

# 检查静态文件
echo -e "\n检查静态文件..."
static_files=("static/style.css" "static/chan_chart.js" "static/favicon.ico")
for file in "${static_files[@]}"; do
    if [ -f "$file" ]; then
        echo "✓ $file 存在"
    else
        echo "⚠ $file 不存在，请确保已创建"
    fi
done

# 检查模板文件
echo -e "\n检查模板文件..."
if [ -f "templates/chan_web.html" ]; then
    echo "✓ templates/chan_web.html 存在"
else
    echo "错误: 未找到模板文件 templates/chan_web.html"
    exit 1
fi

# 检查Python模块
echo -e "\n检查Python模块..."
python_modules=("web_app.py" "chan_advanced.py")
for module in "${python_modules[@]}"; do
    if [ -f "$module" ]; then
        echo "✓ $module 存在"
    else
        echo "错误: 未找到模块 $module"
        exit 1
    fi
done

# 启动Flask应用
echo -e "\n=========================================="
echo "  启动Flask应用..."
echo "=========================================="
echo ""
echo "访问地址:"
echo "  - 缠论Web界面: http://localhost:5000/chan_web"
echo "  - API接口:     http://localhost:5000/api/chan_advanced"
echo ""
echo "按 Ctrl+C 停止服务"
echo ""

# 设置环境变量
export FLASK_APP=web_app.py
export FLASK_ENV=development

# 启动Flask
python3 web_app.py

echo -e "\nFlask应用已停止"
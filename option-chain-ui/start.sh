#!/bin/bash

# PTA期权链T型显示组件启动脚本

set -e

echo "========================================="
echo "PTA期权链T型显示组件"
echo "========================================="

# 检查Node.js版本
NODE_VERSION=$(node --version | cut -d'v' -f2 | cut -d'.' -f1)
if [ "$NODE_VERSION" -lt 18 ]; then
    echo "错误: 需要Node.js 18或更高版本"
    echo "当前版本: $(node --version)"
    exit 1
fi

# 检查npm
if ! command -v npm &> /dev/null; then
    echo "错误: npm未安装"
    exit 1
fi

# 显示菜单
show_menu() {
    echo ""
    echo "请选择操作:"
    echo "1. 安装依赖并启动开发服务器"
    echo "2. 构建生产版本"
    echo "3. 启动API模拟服务器"
    echo "4. 转换PTA平台数据"
    echo "5. 查看集成指南"
    echo "6. 退出"
    echo ""
    read -p "请输入选择 (1-6): " choice
}

# 安装依赖并启动开发服务器
start_dev() {
    echo "正在安装依赖..."
    npm install
    
    echo "启动开发服务器..."
    echo "前端应用将在 http://localhost:3000 启动"
    echo "按 Ctrl+C 停止服务器"
    echo ""
    
    npm start
}

# 构建生产版本
build_prod() {
    echo "正在构建生产版本..."
    npm run build
    
    echo ""
    echo "构建完成！"
    echo "构建文件位于: dist/"
    echo "可以将此目录部署到Web服务器"
    echo ""
    
    # 显示部署说明
    echo "部署说明:"
    echo "1. 将dist目录复制到Web服务器"
    echo "2. 配置Nginx/Apache指向此目录"
    echo "3. 确保API端点可访问"
    echo ""
}

# 启动API模拟服务器
start_api() {
    echo "启动API模拟服务器..."
    echo "API服务器将在 http://localhost:8000 启动"
    echo "可用端点:"
    echo "  GET /api/options/chain      - 期权链数据"
    echo "  GET /api/options/stats      - 市场统计"
    echo "  GET /api/health             - 健康检查"
    echo ""
    echo "按 Ctrl+C 停止服务器"
    echo ""
    
    python3 api_server.py
}

# 转换PTA平台数据
convert_data() {
    echo "PTA平台数据转换工具"
    echo ""
    
    if [ ! -f "data_converter.py" ]; then
        echo "错误: data_converter.py 不存在"
        return 1
    fi
    
    python3 data_converter.py
}

# 查看集成指南
show_guide() {
    echo "集成指南摘要:"
    echo ""
    echo "1. 独立部署 (推荐)"
    echo "   - 构建: npm run build"
    echo "   - 复制dist目录到PTA平台"
    echo "   - 使用iframe嵌入"
    echo ""
    echo "2. 组件嵌入"
    echo "   - 复制组件代码到PTA项目"
    echo "   - 安装依赖: npm install react react-dom recharts"
    echo "   - 导入并使用组件"
    echo ""
    echo "3. 数据集成"
    echo "   - 创建API端点返回期权数据"
    echo "   - 数据格式参考 types/index.ts"
    echo "   - 使用data_converter.py转换现有数据"
    echo ""
    echo "详细指南请查看 INTEGRATION_GUIDE.md"
    echo ""
    
    read -p "是否打开完整指南? (y/n): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        if command -v less &> /dev/null; then
            less INTEGRATION_GUIDE.md
        else
            cat INTEGRATION_GUIDE.md | head -100
            echo "... (更多内容请查看文件)"
        fi
    fi
}

# 主循环
while true; do
    show_menu
    
    case $choice in
        1)
            start_dev
            break
            ;;
        2)
            build_prod
            break
            ;;
        3)
            start_api
            break
            ;;
        4)
            convert_data
            ;;
        5)
            show_guide
            ;;
        6)
            echo "退出"
            exit 0
            ;;
        *)
            echo "无效选择，请重试"
            ;;
    esac
done
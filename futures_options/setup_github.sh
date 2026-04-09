#!/bin/bash
# GitHub 仓库创建和配置脚本
# 运行此脚本前需要先安装 gh CLI 并登录 GitHub

set -e

echo "============================================"
echo "🚀 期货期权分析 - GitHub 仓库配置"
echo "============================================"

# 1. 检查 gh CLI
if ! command -v gh &> /dev/null; then
    echo "❌ gh CLI 未安装"
    echo "请先安装: https://cli.github.com/"
    echo "或者手动在 GitHub 网页上创建仓库"
    exit 1
fi

# 2. 检查 GitHub 登录状态
echo ""
echo "📋 检查 GitHub 登录状态..."
if ! gh auth status &> /dev/null; then
    echo "❌ 未登录 GitHub"
    echo "请运行: gh auth login"
    exit 1
fi

REPO_NAME="futures-options-analysis"

# 3. 创建 GitHub 仓库
echo ""
echo "📦 创建 GitHub 仓库: $REPO_NAME"
gh repo create "$REPO_NAME" --public --source=. --push --description "基于隐含波动率的期货期权分析工具"

# 4. 添加 Secrets
echo ""
echo "🔐 配置 GitHub Secrets..."

# 飞书 Webhook
read -p "请输入飞书 Webhook URL (直接回车使用默认值): " webhook
webhook=${webhook:-"https://open.feishu.cn/open-apis/bot/v2/hook/8148922b-04f5-469f-994e-ae3e17d6b256"}
gh secret set FEISHU_WEBHOOK --body "$webhook"

# 5. 添加 Repository Variables
echo ""
echo "⚙️ 配置 Repository Variables..."
gh variable set PYTHON_VERSION --body "3.11"

# 6. 触发首次 workflow
echo ""
echo "🎯 触发首次 workflow..."
gh workflow run analysis.yml --repo="$GITHUB_USER/$REPO_NAME" || true

echo ""
echo "============================================"
echo "✅ 配置完成!"
echo "============================================"
echo ""
echo "📝 后续操作:"
echo "1. 访问 https://github.com/$GITHUB_USER/$REPO_NAME 查看仓库"
echo "2. 查看 Actions 页面: https://github.com/$GITHUB_USER/$REPO_NAME/actions"
echo "3. 修改 main.py 中的品种配置"
echo ""

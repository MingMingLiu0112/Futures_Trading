#!/bin/bash
# ============================================================
# Docker 构建脚本 - 配置国内镜像加速
# ============================================================

set -e

echo "=========================================="
echo "  PTA Analysis Docker 构建"
echo "=========================================="

# 配置 Docker 国内镜像加速
configure_docker_mirror() {
    echo "[1/4] 配置 Docker 国内镜像加速..."

    DOCKER_CONF="/etc/docker/daemon.json"
    DOCKER_CONF_DIR=$(dirname "$DOCKER_CONF")

    sudo mkdir -p "$DOCKER_CONF_DIR"

    # 写入镜像配置
    sudo tee "$DOCKER_CONF" > /dev/null << 'EOF'
{
  "registry-mirrors": [
    "https://docker.mirrors.ustc.edu.cn",
    "https://hub-mirror.c.163.com",
    "https://mirror.baidubce.com"
  ],
  "dns": ["8.8.8.8", "114.114.114.114"],
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
EOF

    echo "  镜像配置已写入 $DOCKER_CONF"
}

# 重启 Docker
restart_docker() {
    echo "[2/4] 重启 Docker 服务..."
    if command -v systemctl &> /dev/null; then
        sudo systemctl restart docker
        echo "  Docker 已重启 (systemctl)"
    elif command -v service &> /dev/null; then
        sudo service docker restart
        echo "  Docker 已重启 (service)"
    else
        echo "  无法重启 Docker，请手动重启"
    fi
    sleep 3
}

# 测试镜像连接
test_mirror() {
    echo "[3/4] 测试 Docker 镜像连接..."
    if docker pull python:3.11-slim-bookworm --quiet 2>&1 | grep -q "i/o timeout\|connection refused\|EOF"; then
        echo "  ⚠️ 镜像加速可能未生效，尝试备用方案..."
        return 1
    fi
    echo "  ✅ 镜像拉取测试通过"
    return 0
}

# 构建镜像
build_image() {
    echo "[4/4] 构建 PTA Analysis 镜像..."
    docker build -t pta-analysis:latest \
        --platform linux/amd64 \
        -f Dockerfile \
        .
    echo "  ✅ 镜像构建完成: pta-analysis:latest"
}

# 主流程
configure_docker_mirror
restart_docker

if ! test_mirror; then
    echo ""
    echo "⚠️  Docker Hub 连接有问题，尝试直接构建..."
    echo "   如果构建卡住，请手动配置 VPN 或代理"
fi

build_image

echo ""
echo "=========================================="
echo "  ✅ Docker 构建完成!"
echo "=========================================="
echo ""
echo "下一步:"
echo "  1. docker-compose up -d     # 启动服务"
echo "  2. docker-compose logs -f  # 查看日志"
echo "  3. curl http://localhost:8000/health  # 健康检查"
echo ""

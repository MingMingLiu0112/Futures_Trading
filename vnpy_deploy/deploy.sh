#!/bin/bash
# vnpy_web部署脚本
# 目标：vnpy.mingmingliu.cn

set -e

DEPLOY_DIR="/home/admin/.openclaw/vnpy_deploy"
DOMAIN="vnpy.mingmingliu.cn"
EMAIL="admin@mingmingliu.cn"

echo "=========================================="
echo "vnpy_web 部署脚本"
echo "目标域名: $DOMAIN"
echo "=========================================="

# 检查Docker
echo "[1/6] 检查Docker环境..."
if ! command -v docker &> /dev/null; then
    echo "Docker未安装，正在安装..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
    echo "Docker安装完成"
else
    echo "Docker已安装: $(docker --version)"
fi

# 检查docker-compose
if ! command -v docker-compose &> /dev/null; then
    echo "安装docker-compose..."
    curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
fi
echo "docker-compose: $(docker-compose --version)"

# 创建目录
mkdir -p $DEPLOY_DIR/ssl $DEPLOY_DIR/nginx

# 申请SSL证书
echo "[2/6] 申请SSL证书..."
if [ ! -f "$DEPLOY_DIR/ssl/fullchain.pem" ]; then
    # 安装certbot
    if ! command -v certbot &> /dev/null; then
        echo "安装certbot..."
        apt-get update && apt-get install -y certbot
    fi
    
    # 临时停止nginx（如果运行）
    docker stop vnpy_nginx 2>/dev/null || true
    
    # 申请证书
    certbot certonly --standalone -d $DOMAIN --non-interactive --agree-tos -m $EMAIL
    
    # 复制证书
    cp /etc/letsencrypt/live/$DOMAIN/fullchain.pem $DEPLOY_DIR/ssl/
    cp /etc/letsencrypt/live/$DOMAIN/privkey.pem $DEPLOY_DIR/ssl/
    echo "SSL证书申请完成"
else
    echo "SSL证书已存在，跳过"
fi

# 复制配置文件
echo "[3/6] 配置文件..."
cp /home/admin/.openclaw/vnpy_deploy/docker-compose.yml $DEPLOY_DIR/
cp /home/admin/.openclaw/vnpy_deploy/nginx/nginx.conf $DEPLOY_DIR/nginx/
echo "配置文件就绪"

# 拉取镜像
echo "[4/6] 拉取vnpy_web镜像..."
cd $DEPLOY_DIR
docker-compose pull

# 启动服务
echo "[5/6] 启动服务..."
docker-compose down 2>/dev/null || true
docker-compose up -d

# 等待启动
echo "[6/6] 验证服务状态..."
sleep 10

# 检查容器状态
docker ps | grep vnpy

# 检查nginx日志
echo ""
echo "=========================================="
echo "部署完成！"
echo "=========================================="
echo "访问地址: https://$DOMAIN"
echo ""
echo "容器状态:"
docker ps --filter "name=vnpy" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

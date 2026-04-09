#!/bin/bash
# PTA平台部署脚本 - 直接使用podman（无需docker-compose）
set -e

# 镜像
BACKEND_IMG="pta-backend:latest"
FRONTEND_IMG="pta-frontend:latest"
REDIS_IMG="redis:7-alpine"

start() {
    echo "[1/3] 启动Redis (:6379)..."
    podman run -d --name pta-redis \
        --network host \
        --restart unless-stopped \
        -v pta-redis-data:/data \
        $REDIS_IMG redis-server --appendonly yes
    echo "  Redis启动完成"

    echo "[2/3] 启动后端 (:5000)..."
    podman run -d --name pta-backend \
        --network host \
        --restart unless-stopped \
        -e REDIS_HOST=localhost \
        -e REDIS_PORT=6379 \
        -e VNPY_RPC_HOST=localhost \
        -e VNPY_RPC_PORT=2014 \
        -v /home/admin/pta-platform/data:/app/data \
        $BACKEND_IMG
    echo "  后端启动完成"

    echo "[3/3] 启动前端 (:8090)..."
    podman run -d --name pta-frontend \
        --network host \
        --restart unless-stopped \
        -p 8090:80 \
        $FRONTEND_IMG
    echo "  前端启动完成"

    sleep 3
    status
}

stop() {
    echo "[停止] 删除容器..."
    podman rm -f pta-frontend pta-backend pta-redis 2>/dev/null || true
    echo "[完成]"
}

restart() { stop; sleep 2; start; }

status() {
    echo "=== 容器状态 ==="
    podman ps -a --format "table {{.Names}}\t{{.Status}}" | grep -E 'pta|redis' || echo "(无PTA容器运行)"
    echo ""
    echo "=== 端口监听 ==="
    ss -tlnp 2>/dev/null | grep -E '5000|6379|8090' || netstat -tlnp 2>/dev/null | grep -E '5000|6379|8090'
    echo ""
    echo "=== 访问地址 ==="
    echo "  前端: http://47.100.97.88:8090"
    echo "  后端: http://47.100.97.88:5000"
}

logs() {
    echo "=== pta-backend ===" && podman logs --tail=20 pta-backend
    echo "=== pta-frontend ===" && podman logs --tail=20 pta-frontend
    echo "=== pta-redis ===" && podman logs --tail=10 pta-redis
}

case "$1" in
    start) start ;;
    stop) stop ;;
    restart) restart ;;
    status) status ;;
    logs) logs ;;
    *) echo "用法: $0 start|stop|restart|status|logs" ;;
esac

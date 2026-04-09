#!/bin/bash
set -e

echo "[启动] PTA后端服务"
echo "[启动] Python版本: $(python3 --version)"
echo "[启动] 工作目录: $(pwd)"

# 等待Redis就绪
echo "[Redis] 等待连接..."
for i in $(seq 1 10); do
    if redis-cli -h ${REDIS_HOST:-localhost} -p ${REDIS_PORT:-6379} ping > /dev/null 2>&1; then
        echo "[Redis] 连接成功"
        break
    fi
    echo "[Redis] 等待... ($i/10)"
    sleep 2
done

# 启动gunicorn
echo "[启动] Gunicorn监听 :5000"
exec gunicorn \
    --bind 0.0.0.0:5000 \
    --workers 2 \
    --threads 4 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    'app:create_app()'

#!/bin/bash
set -e

echo "=========================================="
echo "  PTA Analysis Docker 启动"
echo "=========================================="

# 初始化 MySQL 数据库 (首次启动)
if [ ! -d "/var/lib/mysql/mysql" ]; then
    echo "[MySQL] 初始化数据库..."
    mysql_install_db --user=mysql --datadir=/var/lib/mysql > /dev/null 2>&1
fi

# 创建 PTA 数据库和用户
mysql_ready() {
    mysqladmin ping -u root --silent 2>/dev/null
}

echo "[MySQL] 等待 MySQL 启动..."
for i in $(seq 1 30); do
    if mysql_ready; then
        echo "[MySQL] 已就绪"
        break
    fi
    sleep 1
done

# 创建数据库
mysql -u root << 'EOSQL'
CREATE DATABASE IF NOT EXISTS pta_analysis CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS vnpy CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 创建应用用户
CREATE USER IF NOT EXISTS 'pta'@'localhost' IDENTIFIED BY 'pta_pass_2025';
GRANT ALL PRIVILEGES ON pta_analysis.* TO 'pta'@'localhost';
GRANT ALL PRIVILEGES ON vnpy.* TO 'pta'@'localhost';
FLUSH PRIVILEGES;
EOSQL

echo "[MySQL] 数据库初始化完成"

# 创建数据目录
mkdir -p /app/data /app/logs /app/cache

# 设置定时任务
echo "*/10 * * * * cd /app && python health_check.py >> /var/log/supervisor/health.log 2>&1" >> /etc/cron.d/pta-cron
echo "0 */2 * * * cd /app && python collector/pta_collector.py >> /var/log/supervisor/collector.log 2>&1" >> /etc/cron.d/pta-cron
chmod 644 /etc/cron.d/pta-cron
crontab /etc/cron.d/pta-cron

echo "[Cron] 定时任务已配置"

# 启动 supervisord (管理所有进程)
echo "[Supervisor] 启动所有服务..."
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf

# ============================================================
# PTA Analysis Docker 环境 - 单一容器包含所有服务
# ============================================================
# 包含: Python3.11 + vnpy + MySQL(MariaDB) + Redis + FastAPI
# 架构: supervisord 管理多进程
# ============================================================

FROM python:3.11-slim-bookworm

# 设置环境变量
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    # 基础工具
    curl wget git vim cron rsyslog logrotate tzdata \
    # 数据库
    mariadb-server mariadb-client \
    # Redis
    redis-server \
    # 字体(matplotlib)
    fonts-noto-cjk \
    # 编译工具(TA-Lib等)
    build-essential gcc g++ \
    # 杂项
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# 设置时区
RUN ln -snf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo 'Asia/Shanghai' > /etc/timezone

# 创建工作目录
WORKDIR /app

# ===================== Python 依赖 =====================
# 先安装 TA-Lib (需要编译)
COPY requirements_pip.txt /tmp/requirements_pip.txt

# 安装 Python 包 (分阶段避免超时)
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# 核心数据/分析包
RUN pip install --no-cache-dir \
    numpy==1.26.4 \
    pandas==2.2.3 \
    scipy==1.14.1 \
    matplotlib==3.9.3 \
    requests==2.32.3 \
    python-dotenv==1.0.1 \
    akshare==1.15.1 \
    tqsdk==3.24.20250627 \
    vnpy==4.3.0 \
    TA-Lib==0.6.8 \
    sqlalchemy==2.0.36 \
    pymysql==1.1.1 \
    redis==5.2.1 \
    fastapi==0.135.3 \
    uvicorn==0.34.0 \
    python-multipart==0.0.20 \
    pydantic==2.10.5 \
    pydantic-settings==2.7.1 \
    apscheduler==3.11.0 \
    schedule==1.2.2

# 中文显示
RUN fc-cache -f -v > /dev/null 2>&1 || true

# ===================== 配置 MySQL =====================
# 初始化 MySQL 数据目录
RUN mkdir -p /var/run/mysqld /var/lib/mysql \
    && chown -R mysql:mysql /var/run/mysqld /var/lib/mysql

# MySQL 配置 (低内存容器优化)
RUN cat > /etc/mysql/my.cnf << 'EOF'
[mysqld]
user            = mysql
datadir         = /var/lib/mysql
socket          = /var/run/mysqld/mysqld.sock
port            = 3306
bind-address    = 127.0.0.1
pid-file        = /var/run/mysqld/mysqld.pid

# 性能(容器级)
innodb_buffer_pool_size     = 128M
innodb_log_file_size        = 32M
max_connections             = 50
query_cache_size            = 0
table_open_cache            = 64

# 字符集
character-set-server        = utf8mb4
collation-server            = utf8mb4_unicode_ci

# 跳过域名解析(加速)
skip-name-resolve

[client]
port    = 3306
socket  = /var/run/mysqld/mysqld.sock
default-character-set       = utf8mb4

[mysql]
default-character-set       = utf8mb4
EOF

# ===================== 配置 Redis =====================
RUN cat > /etc/redis/redis.conf << 'EOF'
daemonize no
port 6379
bind 127.0.0.1
protected-mode yes
timeout 0
loglevel notice

# 持久化(容器环境用 AOF)
appendonly yes
appendfilename "appendonly.aof"
appendfsync everysec

# 内存
maxmemory 256mb
maxmemory-policy allkeys-lru

# 低内存优化
save ""
EOF

# ===================== 项目文件 =====================
COPY . /app/

# ===================== supervisord 管理多进程 =====================
RUN apt-get update && apt-get install -y --no-install-recommends supervisor \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /var/log/supervisor /var/log/mysql /var/log/redis

# supervisord 配置
RUN cat > /etc/supervisor/conf.d/supervisord.conf << 'EOF'
[supervisord]
nodaemon=true
logfile=/var/log/supervisor/supervisord.log
pidfile=/var/run/supervisord.pid
childlogdir=/var/log/supervisor
loglevel=info

[program:mysql]
command=/usr/bin/mysqld_safe --datadir=/var/lib/mysql --user=mysql
stdout_logfile=/var/log/mysql/mysql.log
stderr_logfile=/var/log/mysql/mysql.err
autorestart=true
priority=10
startsecs=5

[program:redis]
command=redis-server /etc/redis/redis.conf
stdout_logfile=/var/log/redis/redis.log
stderr_logfile=/var/log/redis/redis.err
autorestart=true
priority=20

[program:api]
command=uvicorn main:app --host 0.0.0.0 --port 8000 --log-level info
directory=/app
stdout_logfile=/var/log/supervisor/api.log
stderr_logfile=/var/log/supervisor/api.err
autorestart=true
priority=30

[program:cron]
command=/usr/sbin/cron -f -l 2
stdout_logfile=/var/log/supervisor/cron.log
stderr_logfile=/var/log/supervisor/cron.err
autorestart=true
priority=40
EOF

# ===================== 启动脚本 =====================
RUN chmod +x /app/entrypoint.sh

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python /app/health_check.py || exit 1

EXPOSE 3306 6379 8000

ENTRYPOINT ["/app/entrypoint.sh"]

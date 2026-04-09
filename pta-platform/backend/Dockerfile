FROM python:3.10-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    redis-tools \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/log/nginx && mkdir -p /run/nginx || true

# 复制依赖列表
COPY requirements.txt .

# 安装Python依赖（使用国内镜像）
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r requirements.txt

# 复制应用代码
COPY app/ /app/app/
COPY chan_py/ /app/chan_py/
COPY run.sh /app/run.sh
RUN chmod +x /app/run.sh

# 创建数据目录
RUN mkdir -p /app/data

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5000/api/health || exit 1

CMD ["/app/run.sh"]

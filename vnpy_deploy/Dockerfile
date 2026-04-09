FROM python:3.11-slim

WORKDIR /app

# 安装依赖
RUN pip install fastapi uvicorn pandas numpy akshare

# 复制应用
COPY app.py .

# 复制数据目录
COPY data/ /data/

# 暴露端口
EXPOSE 5000

# 运行
CMD ["python", "app.py"]

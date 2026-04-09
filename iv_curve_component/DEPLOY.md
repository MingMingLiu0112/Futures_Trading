# 部署指南

## 🚀 快速部署

### 1. 本地开发环境

```bash
# 克隆或复制文件
cd iv_curve_component

# 安装依赖
pip install -r requirements.txt

# 启动服务
python api.py

# 在浏览器中打开
open http://localhost:5000
```

### 2. 使用启动脚本

```bash
chmod +x start.sh
./start.sh
```

## ☁️ 云服务器部署

### 1. 准备服务器

```bash
# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装Python和pip
sudo apt install python3 python3-pip python3-venv -y

# 安装Node.js（可选，用于构建）
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install nodejs -y
```

### 2. 部署应用

```bash
# 创建应用目录
sudo mkdir -p /opt/iv-curve
sudo chown $USER:$USER /opt/iv-curve

# 复制文件
cp -r iv_curve_component/* /opt/iv-curve/
cd /opt/iv-curve

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 3. 配置系统服务

创建systemd服务文件 `/etc/systemd/system/iv-curve.service`：

```ini
[Unit]
Description=IV Curve API Service
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/iv-curve
Environment="PATH=/opt/iv-curve/venv/bin"
ExecStart=/opt/iv-curve/venv/bin/python api.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启用并启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable iv-curve
sudo systemctl start iv-curve
sudo systemctl status iv-curve
```

### 4. 配置Nginx反向代理

安装Nginx：

```bash
sudo apt install nginx -y
```

创建Nginx配置 `/etc/nginx/sites-available/iv-curve`：

```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket支持
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    
    # 静态文件缓存
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

启用配置：

```bash
sudo ln -s /etc/nginx/sites-available/iv-curve /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 5. 配置SSL（可选）

使用Certbot获取SSL证书：

```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d your-domain.com
```

## 🐳 Docker部署

### 1. 创建Dockerfile

```dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["python", "api.py"]
```

### 2. 构建和运行

```bash
# 构建镜像
docker build -t iv-curve .

# 运行容器
docker run -d \
  --name iv-curve \
  -p 5000:5000 \
  -v $(pwd)/data:/app/data \
  iv-curve

# 查看日志
docker logs -f iv-curve
```

### 3. Docker Compose

创建 `docker-compose.yml`：

```yaml
version: '3.8'

services:
  iv-curve:
    build: .
    ports:
      - "5000:5000"
    volumes:
      - ./data:/app/data
    environment:
      - FLASK_ENV=production
      - PYTHONUNBUFFERED=1
    restart: unless-stopped
```

运行：

```bash
docker-compose up -d
```

## 🔧 环境配置

### 生产环境变量

创建 `.env` 文件：

```bash
FLASK_ENV=production
SECRET_KEY=your-secret-key-here
API_RATE_LIMIT=100/hour
CACHE_TYPE=simple
```

### 数据库配置（如果需要）

```python
# 在api.py中添加
import os
from flask_sqlalchemy import SQLAlchemy

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///iv_data.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
```

## 📊 监控和日志

### 日志配置

```python
import logging
from logging.handlers import RotatingFileHandler

# 在api.py中添加
handler = RotatingFileHandler('iv_curve.log', maxBytes=10000, backupCount=3)
handler.setLevel(logging.INFO)
app.logger.addHandler(handler)
```

### 健康检查端点

```python
@app.route('/health')
def health_check():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0'
    })
```

## 🔒 安全配置

### 1. 防火墙

```bash
# 只开放必要端口
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

### 2. 限制API访问

```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["100 per hour"]
)

@app.route('/api/iv/current')
@limiter.limit("10 per minute")
def get_current_iv():
    # ...
```

### 3. CORS配置

```python
from flask_cors import CORS

# 只允许特定域名
CORS(app, resources={
    r"/api/*": {
        "origins": ["https://your-domain.com", "http://localhost:*"]
    }
})
```

## 📈 性能优化

### 1. 启用Gzip压缩

在Nginx配置中添加：

```nginx
gzip on;
gzip_vary on;
gzip_min_length 1024;
gzip_types text/plain text/css text/xml text/javascript application/javascript application/xml+rss application/json;
```

### 2. 静态文件CDN

将静态文件托管到CDN：

```html
<!-- 修改index.html中的CDN链接 -->
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
```

### 3. 缓存策略

```python
from flask_caching import Cache

cache = Cache(app, config={'CACHE_TYPE': 'simple'})

@app.route('/api/iv/current')
@cache.cached(timeout=60)  # 缓存60秒
def get_current_iv():
    # ...
```

## 🔄 更新部署

### 1. 手动更新

```bash
cd /opt/iv-curve
git pull origin main  # 或复制新文件
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart iv-curve
```

### 2. 使用部署脚本

创建 `deploy.sh`：

```bash
#!/bin/bash
set -e

cd /opt/iv-curve

echo "拉取最新代码..."
git pull origin main

echo "安装依赖..."
source venv/bin/activate
pip install -r requirements.txt

echo "重启服务..."
sudo systemctl restart iv-curve

echo "部署完成！"
```

## 🐛 故障排除

### 常见问题

1. **端口被占用**
   ```bash
   sudo lsof -i :5000
   sudo kill -9 <PID>
   ```

2. **权限问题**
   ```bash
   sudo chown -R www-data:www-data /opt/iv-curve
   sudo chmod -R 755 /opt/iv-curve
   ```

3. **依赖问题**
   ```bash
   # 重新创建虚拟环境
   rm -rf venv
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

4. **服务无法启动**
   ```bash
   sudo journalctl -u iv-curve -f
   ```

### 调试模式

```bash
# 临时启用调试
FLASK_ENV=development python api.py
```

## 📞 支持

- 查看日志：`sudo journalctl -u iv-curve -f`
- 检查状态：`sudo systemctl status iv-curve`
- 重启服务：`sudo systemctl restart iv-curve`
- 查看网络：`sudo netstat -tulpn | grep :5000`

---

**部署成功！** 🎉

访问你的应用：http://your-domain.com 或 http://localhost:5000
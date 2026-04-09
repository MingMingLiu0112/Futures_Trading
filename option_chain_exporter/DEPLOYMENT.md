# 部署指南

## 部署方式

### 1. 直接运行（开发环境）
```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
python main.py
# 或
./run.sh
```

### 2. 使用Docker
```bash
# 构建镜像
docker build -t option-chain-exporter .

# 运行容器
docker run -d \
  -p 5000:5000 \
  -v $(pwd)/exports:/app/exports \
  -v $(pwd)/uploads:/app/uploads \
  --name option-chain-exporter \
  option-chain-exporter
```

### 3. 使用Docker Compose
```bash
# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

### 4. 生产环境部署（使用gunicorn）
```bash
# 安装gunicorn
pip install gunicorn

# 启动服务
gunicorn -w 4 -b 0.0.0.0:5000 --access-logfile - --error-logfile - main:app
```

## 环境变量配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| FLASK_ENV | development | Flask环境（development/production） |
| PYTHONUNBUFFERED | 1 | Python输出无缓冲 |
| EXPORT_FOLDER | exports | Excel导出目录 |
| UPLOAD_FOLDER | uploads | 文件上传目录 |

## Nginx反向代理配置

```nginx
server {
    listen 80;
    server_name option-chain.yourdomain.com;
    
    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    # 静态文件缓存
    location /exports/ {
        alias /path/to/exports/;
        expires 7d;
        add_header Cache-Control "public";
    }
}
```

## 系统服务配置（Systemd）

创建服务文件 `/etc/systemd/system/option-chain-exporter.service`：

```ini
[Unit]
Description=Option Chain Exporter Service
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/option-chain-exporter
Environment="PYTHONUNBUFFERED=1"
Environment="FLASK_ENV=production"
ExecStart=/usr/bin/gunicorn -w 4 -b 0.0.0.0:5000 --access-logfile - --error-logfile - main:app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启用并启动服务：
```bash
sudo systemctl daemon-reload
sudo systemctl enable option-chain-exporter
sudo systemctl start option-chain-exporter
sudo systemctl status option-chain-exporter
```

## 监控和日志

### 日志位置
- **直接运行**: 控制台输出
- **Docker**: `docker logs option-chain-exporter`
- **Systemd**: `journalctl -u option-chain-exporter -f`

### 健康检查
```bash
# 检查服务状态
curl http://localhost:5000/api/health
```

### 监控指标
- 服务响应时间
- 导出文件数量
- 内存和CPU使用率
- 错误率

## 备份策略

### 重要数据
1. **导出文件**: `exports/` 目录
2. **上传文件**: `uploads/` 目录
3. **配置文件**: 应用配置文件

### 备份脚本示例
```bash
#!/bin/bash
# backup.sh

BACKUP_DIR="/backup/option-chain-exporter"
DATE=$(date +%Y%m%d_%H%M%S)

# 创建备份目录
mkdir -p $BACKUP_DIR/$DATE

# 备份数据
cp -r exports $BACKUP_DIR/$DATE/
cp -r uploads $BACKUP_DIR/$DATE/

# 备份配置
cp main.py $BACKUP_DIR/$DATE/
cp requirements.txt $BACKUP_DIR/$DATE/

# 压缩备份
tar -czf $BACKUP_DIR/option-chain-backup-$DATE.tar.gz -C $BACKUP_DIR/$DATE .

# 清理旧备份（保留最近7天）
find $BACKUP_DIR -name "*.tar.gz" -mtime +7 -delete

echo "备份完成: $BACKUP_DIR/option-chain-backup-$DATE.tar.gz"
```

## 安全建议

1. **启用HTTPS**: 使用Let's Encrypt获取SSL证书
2. **访问控制**: 配置防火墙，限制访问IP
3. **文件上传限制**: 配置最大文件大小和类型检查
4. **定期更新**: 保持依赖包最新版本
5. **日志审计**: 定期检查访问日志

## 故障排除

### 常见问题

1. **端口占用**
   ```bash
   # 检查端口占用
   sudo netstat -tlnp | grep :5000
   
   # 停止占用进程
   sudo kill <PID>
   ```

2. **依赖安装失败**
   ```bash
   # 更新pip
   pip install --upgrade pip
   
   # 使用国内镜像
   pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
   ```

3. **权限问题**
   ```bash
   # 设置目录权限
   chmod 755 exports uploads
   chown -R www-data:www-data exports uploads
   ```

4. **内存不足**
   ```bash
   # 查看内存使用
   free -h
   
   # 调整gunicorn worker数量
   gunicorn -w 2 -b 0.0.0.0:5000 main:app
   ```

### 联系支持
如有问题，请检查日志文件或联系系统管理员。
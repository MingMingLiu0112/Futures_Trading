# PTA Analysis Docker 环境

## 概述

全合一 Docker 容器，包含：
- **Python 3.11** - 主运行环境
- **vnpy 4.3.0** - 量化交易框架
- **TQSdk** - 天勤量化（免费实时行情）
- **MySQL (MariaDB)** - 数据存储
- **Redis** - 缓存层
- **FastAPI** - REST API 服务
- **AKShare** - 数据源

## 架构

```
┌─────────────────────────────────────┐
│           pta-analysis              │
│         (单一容器)                   │
│                                     │
│  ┌─────────┬─────────┬──────────┐  │
│  │  MySQL  │  Redis  │  FastAPI │  │
│  │  3306   │  6379   │   8000   │  │
│  └─────────┴─────────┴──────────┘  │
│                                     │
│  Supervisor 管理所有进程             │
└─────────────────────────────────────┘
```

## 快速开始

### 1. 配置国内镜像加速（避免 Docker Hub 超时）

```bash
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json > /dev/null << 'EOF'
{
  "registry-mirrors": [
    "https://docker.mirrors.ustc.edu.cn",
    "https://hub-mirror.c.163.com"
  ]
}
EOF
sudo systemctl restart docker
```

### 2. 构建镜像

```bash
cd /home/admin/.openclaw/workspace/codeman/pta_analysis
chmod +x build_docker.sh
./build_docker.sh
```

或直接：

```bash
docker build -t pta-analysis:latest --platform linux/amd64 -f Dockerfile .
```

### 3. 启动服务

```bash
docker-compose up -d
```

### 4. 查看服务状态

```bash
docker-compose ps
docker-compose logs -f
```

### 5. 健康检查

```bash
curl http://localhost:8000/health
```

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 服务健康检查 |
| `/api/pta/quote` | GET | PTA期货实时行情 |
| `/api/pta/option` | GET | PTA期权链数据 |
| `/api/pta/iv` | GET | IV曲面与PCR |
| `/api/pta/cost` | GET | PTA成本计算 |
| `/api/pta/signal` | GET | 综合信号 |
| `/api/brent` | GET | 布伦特原油价格 |
| `/api/macro/news` | GET | 宏观新闻摘要 |

## 定时任务

- `/health_check.py` - 每10分钟执行健康检查
- `collector/pta_collector.py` - 每2小时采集数据

## 数据持久化

```yaml
volumes:
  pta_data:/app/data      # 策略数据
  pta_logs:/app/logs      # 日志文件
  pta_cache:/app/cache    # 缓存
  pta_mysql:/var/lib/mysql # 数据库
```

## 清理

```bash
docker-compose down -v   # 停止并删除数据卷
docker rmi pta-analysis   # 删除镜像
```

## 常见问题

### Q: Docker Hub 连接超时
A: 配置国内镜像加速器，见上面的快速开始第1步。

### Q: TA-Lib 安装失败
A: Dockerfile 中已包含 build-essential，TA-Lib Python包会自动编译。

### Q: vnpy CTP 接口需要什么
A: CTP接口需要完整的CTP开发库（来自期货公司），免费测试可用 SimNow 账户。

### Q: 如何使用 TQSdk
A: TQSdk 已包含在镜像中，无需额外配置，可直接使用：
```python
from tqsdk import TqApi
api = TqApi()
quote = api.get_quote("CZCE.TA")
```

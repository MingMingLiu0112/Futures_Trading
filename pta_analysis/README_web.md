# PTA期货分析平台 - Web版本

## 🚀 功能概述

已成功部署完整的PTA期货分析平台，主页面位于：**http://47.100.97.88/**

## 📊 核心功能

### 1. 主页面 (http://47.100.97.88/)
- **PTA期货价格**：实时行情显示
- **交易信号**：三维度分析（宏观+技术+期权）
- **成本分析**：布伦特原油→PX→PTA成本链
- **缠论分析**：笔、线段、中枢技术分析
- **期权数据**：PCR、合约列表
- **宏观新闻**：实时财经新闻

### 2. 二级页面
- **缠论分析**：http://47.100.97.88/chan/
- **历史数据**：http://47.100.97.88/history
- **宏观分析**：http://47.100.97.88/macro

### 3. API接口
- `GET /api/quote` - PTA实时行情
- `GET /api/signal` - 交易信号
- `GET /api/cost` - 成本分析
- `GET /api/options` - 期权数据
- `GET /api/chan` - 缠论分析
- `GET /api/news` - 宏观新闻
- `GET /api/history` - 历史信号

## 🛠️ 技术架构

### 后端
- **框架**：Flask (Python)
- **数据源**：akshare API
- **数据库**：SQLite (缓存历史数据)
- **端口**：8422

### 前端
- **框架**：Bootstrap 5 + Font Awesome
- **响应式**：支持移动端访问
- **自动刷新**：每60秒自动更新数据

### 部署
- **Web服务器**：Nginx (端口80)
- **反向代理**：Nginx → Flask (8422)
- **静态文件**：Nginx直接服务
- **兼容性**：保留原有 `/chan/` 路径

## ✅ 已解决问题

1. **✅ 主页面访问**：http://47.100.97.88/ 正常显示
2. **✅ 所有功能集成**：价格、信号、成本、缠论、期权、新闻
3. **✅ 二级页面**：/chan/, /history/, /macro/ 均可访问
4. **✅ API接口**：所有API返回正常JSON数据
5. **✅ 静态文件**：缠论图表可正常显示
6. **✅ 响应式设计**：适配手机和电脑浏览器

## 🔧 维护命令

### 启动应用
```bash
cd /home/admin/.openclaw/workspace/codeman/pta_analysis
python3 web_app.py
```

### 检查状态
```bash
# 检查Flask应用
curl http://127.0.0.1:8422/

# 检查Nginx配置
sudo nginx -t
sudo systemctl status nginx

# 查看日志
sudo tail -f /var/log/nginx/error.log
```

### 重启服务
```bash
# 重启Flask
pkill -f "python3 web_app.py"
cd /home/admin/.openclaw/workspace/codeman/pta_analysis && python3 web_app.py &

# 重启Nginx
sudo systemctl reload nginx
```

## 📱 页面预览

### 主页面包含：
1. **顶部标题栏**：PTA期货分析平台
2. **第一行**：价格卡片 + 信号卡片 + 成本卡片
3. **第二行**：缠论分析 + 期权数据
4. **第三行**：宏观新闻速递
5. **功能按钮**：缠论分析、API接口、历史数据、宏观分析
6. **右下角**：刷新按钮（每60秒自动刷新）

### 响应式特性：
- 电脑端：3列布局
- 平板端：2列布局  
- 手机端：1列布局

## 🎯 下一步优化

1. **数据缓存**：减少akshare API调用频率
2. **图表优化**：更多可视化图表
3. **用户交互**：添加筛选和对比功能
4. **报警功能**：价格突破预警
5. **移动应用**：考虑PWA支持

## 📞 技术支持

如有问题，请检查：
1. Flask应用是否运行：`ps aux | grep web_app.py`
2. Nginx是否运行：`sudo systemctl status nginx`
3. 端口是否开放：`netstat -tln | grep :8422`
4. 错误日志：`sudo tail -f /var/log/nginx/error.log`
# 多品种期货分析平台

## 概述

这是一个支持一键更换不同期货品种的分析平台，能够自动选择主力合约和最近月期权合约。平台提供了品种配置管理、合约自动切换逻辑和现代化的界面组件。

## 功能特性

### 1. 多品种支持
- 支持8个主要期货品种：PTA、甲醇、白糖、棉花、铜、铝、锌、镍
- 一键切换品种，界面实时更新
- 每个品种有独立的配置（颜色、图标、合约规格等）

### 2. 合约自动选择
- **主力合约自动识别**：根据成交量自动选择主力合约
- **期权合约自动选择**：自动选择最近月期权合约
- **实时行情获取**：从akshare获取实时行情数据

### 3. 现代化界面
- 响应式设计，支持移动端和桌面端
- 直观的品种选择卡片
- 实时价格显示和涨跌幅计算
- 合约信息展示
- 自动刷新（每30秒）

### 4. RESTful API
- 完整的API接口，支持程序化访问
- 品种切换、数据获取、配置管理
- 健康检查接口

## 快速开始

### 1. 启动服务
```bash
cd /home/admin/.openclaw/workspace/codeman/pta_analysis
./start_multi_variety.sh
```

或者直接运行：
```bash
python3 multi_variety_main.py
```

### 2. 访问界面
打开浏览器访问：http://localhost:8001

### 3. 使用界面
1. **选择品种**：点击品种卡片切换当前分析的品种
2. **查看数据**：查看实时价格、涨跌幅、成交量等信息
3. **刷新数据**：点击右下角刷新按钮或等待自动刷新
4. **查看合约**：查看主力合约和期权合约信息

## API接口

### 基础信息
- `GET /health` - 健康检查
- `GET /api/config` - 获取平台配置
- `GET /api/variety/current` - 获取当前品种
- `GET /api/variety/list` - 获取品种列表

### 品种操作
- `POST /api/variety/switch/{variety_code}` - 切换品种
- `GET /api/variety/{variety_code}/data` - 获取品种数据
- `GET /api/variety/{variety_code}/options` - 获取期权数据
- `GET /api/variety/{variety_code}/signal` - 获取交易信号
- `GET /api/variety/{variety_code}/history` - 获取历史数据

## 配置文件

### 品种配置 (variety_config.json)
平台会自动创建配置文件，包含以下信息：
```json
{
  "current_variety": "PTA",
  "varieties": {
    "PTA": {
      "name": "精对苯二甲酸",
      "exchange": "CZCE",
      "futures_symbol": "TA",
      "options_symbol": "TA",
      "unit": "元/吨",
      "contract_size": 5,
      "tick_size": 2,
      "margin_rate": 0.08,
      "description": "PTA期货，郑州商品交易所",
      "enabled": true,
      "color": "#3498db",
      "icon": "fas fa-flask"
    },
    // ... 其他品种配置
  }
}
```

### 添加新品种
可以通过编辑`variety_config.py`文件或通过API添加新品种。

## 技术架构

### 后端技术栈
- **FastAPI**：高性能Web框架
- **akshare**：金融数据接口
- **SQLite**：轻量级数据库
- **Jinja2**：模板引擎

### 前端技术栈
- **Bootstrap 5**：响应式CSS框架
- **Font Awesome**：图标库
- **原生JavaScript**：交互逻辑

### 数据流
1. 用户访问界面 → 2. 加载品种配置 → 3. 获取实时行情 → 4. 显示数据 → 5. 用户交互 → 6. 更新数据

## 开发指南

### 项目结构
```
pta_analysis/
├── multi_variety_main.py      # 主程序
├── variety_config.py          # 品种配置管理
├── templates/
│   └── multi_variety.html     # 主界面模板
├── test_multi_variety.py      # 测试脚本
├── test_pta_only.py           # PTA测试脚本
├── start_multi_variety.sh     # 启动脚本
└── MULTI_VARIETY_README.md    # 本文档
```

### 添加新品种
1. 在`variety_config.py`的`default_config`中添加新品种配置
2. 确保有正确的`akshare_symbol_map`映射
3. 重启服务

### 扩展功能
- **技术分析**：集成缠论分析模块
- **基本面分析**：添加产业数据和分析
- **期权分析**：完善期权数据和分析
- **报警功能**：价格预警和信号通知
- **数据导出**：导出历史数据到CSV/Excel

## 注意事项

### 数据源限制
- akshare API可能有频率限制
- 部分品种的实时数据可能不可用
- 期权数据依赖于交易所提供

### 性能优化
- 使用缓存减少API调用
- 数据库索引优化查询性能
- 前端资源压缩和CDN

### 错误处理
- 网络错误自动重试
- 数据缺失时显示友好提示
- 日志记录便于调试

## 故障排除

### 常见问题
1. **服务无法启动**：检查端口是否被占用，修改端口号
2. **数据获取失败**：检查网络连接和akshare API状态
3. **界面显示异常**：清除浏览器缓存或检查控制台错误

### 日志查看
服务启动时会显示日志信息，包括：
- 数据库初始化状态
- API调用结果
- 错误信息

## 未来规划

### 短期目标
- [ ] 完善技术分析模块
- [ ] 添加基本面数据
- [ ] 优化移动端体验
- [ ] 添加数据图表

### 长期目标
- [ ] 集成机器学习模型
- [ ] 添加回测功能
- [ ] 支持自定义策略
- [ ] 多用户支持

## 贡献指南

欢迎提交Issue和Pull Request来改进这个项目。

## 许可证

本项目仅供学习和研究使用，投资有风险，入市需谨慎。
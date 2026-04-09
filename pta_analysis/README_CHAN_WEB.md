# 缠论Web界面集成

## 功能概述

本模块实现了缠论算法的完整Web界面和API集成，包括：

1. **缠论分析Web页面** - 完整的缠论可视化界面
2. **缠论数据API接口** - 提供JSON格式的缠论分析数据
3. **实时缠论信号推送** - WebSocket实时更新
4. **缠论可视化图表** - 基于Chart.js的交互式图表
5. **与现有K线图集成** - 与PTA分析平台无缝集成

## 技术栈

- **前端**: Bootstrap 5, Chart.js, JavaScript (ES6+)
- **后端**: Flask (Python)
- **缠论算法**: 自定义实现（笔、线段、中枢、分型识别）
- **实时通信**: WebSocket (计划中)

## 文件结构

```
pta_analysis/
├── web_app.py                 # 主Flask应用（已更新）
├── chan_advanced.py           # 高级缠论分析模块
├── templates/
│   └── chan_web.html          # 缠论Web页面模板
├── static/
│   ├── style.css              # 自定义样式
│   ├── chan_chart.js          # 缠论图表渲染器
│   └── favicon.ico            # 网站图标
└── README_CHAN_WEB.md         # 本文件
```

## API接口

### 1. 高级缠论分析
```
GET /api/chan_advanced
参数:
  - symbol: 品种代码 (默认: TA)
  - period: 时间周期 (默认: 1d, 可选: 3d, 1w, 1m)

返回: 完整的缠论分析结果，包括笔、线段、中枢、分型等
```

### 2. 缠论信号
```
GET /api/chan_signals
返回: 实时缠论交易信号
```

### 3. 笔列表
```
GET /api/chan_bi
返回: 笔的详细列表
```

### 4. 线段列表
```
GET /api/chan_xd
返回: 线段的详细列表
```

### 5. 中枢列表
```
GET /api/chan_zhongshu
返回: 中枢的详细列表
```

## Web页面

### 缠论分析页面
```
访问: /chan_web
功能: 完整的缠论可视化分析界面
```

## 运行方法

### 1. 启动Flask应用
```bash
cd pta_analysis
python web_app.py
```

### 2. 访问Web界面
- 缠论分析页面: http://localhost:5000/chan_web
- API接口: http://localhost:5000/api/chan_advanced

### 3. 在容器中运行
```bash
# 进入vnpy容器
podman exec -it vnpy-beta bash

# 在容器中启动
cd /app/pta_analysis
python web_app.py
```

## 功能特性

### 1. 图表功能
- 交互式K线图表
- 笔、线段、中枢、分型可视化
- 显示/隐藏控制
- 时间周期切换

### 2. 实时功能
- 实时信号显示
- WebSocket连接状态
- 自动数据刷新

### 3. 分析功能
- 趋势分析
- 中枢分析
- 操作建议
- 风险等级评估

### 4. 响应式设计
- 支持桌面和移动设备
- Bootstrap 5响应式布局
- 触摸友好的界面

## 缠论算法

### 核心概念
1. **分型**: 顶分型和底分型识别
2. **笔**: 相邻分型之间的价格走势
3. **线段**: 至少3笔构成的趋势段
4. **中枢**: 至少3个重叠线段构成的盘整区域

### 算法流程
1. K线包含关系处理
2. 分型识别
3. 笔的构建
4. 线段的构建
5. 中枢的识别
6. 趋势分析和信号生成

## 配置选项

### 时间周期
- 1d: 今日数据
- 3d: 近3日数据
- 1w: 近1周数据
- 1m: 近1月数据

### 显示控制
- 显示/隐藏笔
- 显示/隐藏线段
- 显示/隐藏中枢
- 显示/隐藏分型

## 开发说明

### 添加新功能
1. 在 `chan_advanced.py` 中添加算法逻辑
2. 在 `web_app.py` 中添加API路由
3. 在 `chan_web.html` 中添加前端界面
4. 在 `chan_chart.js` 中添加图表渲染逻辑

### 数据源
当前使用模拟数据，实际部署时需要：
1. 连接到真实行情数据源
2. 实现数据缓存机制
3. 添加数据库支持

### 性能优化
- 图表数据分页加载
- WebSocket连接池
- 数据缓存
- 异步处理

## 故障排除

### 常见问题
1. **图表不显示**: 检查Chart.js是否正确加载
2. **数据为空**: 检查数据源连接
3. **API错误**: 查看Flask日志
4. **样式问题**: 检查CSS文件路径

### 日志查看
```bash
# 查看Flask日志
tail -f pta_analysis/flask.log

# 查看错误日志
grep ERROR pta_analysis/flask.log
```

## 下一步计划

### 短期目标
1. 实现真实数据源连接
2. 完善WebSocket实时推送
3. 添加更多技术指标

### 长期目标
1. 多品种支持
2. 多时间周期分析
3. 机器学习信号预测
4. 移动端应用

## 贡献指南

欢迎提交Issue和Pull Request来改进本项目。

## 许可证

MIT License
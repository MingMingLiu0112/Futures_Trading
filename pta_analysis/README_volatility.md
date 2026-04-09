# PTA期货波动锥与隐波百分位分析系统

## 概述

本系统提供PTA期货的历史波动锥分析和期权隐含波动率(IV)百分位计算功能，帮助交易者理解市场波动率特征并生成交易策略建议。

## 功能特性

### 1. 历史波动锥分析
- 多时间窗口历史波动率计算（5, 10, 20, 30, 60, 90, 120, 250天）
- 波动率分布统计（均值、中位数、最小值、最大值、分位数）
- 可视化波动锥图表展示

### 2. 隐含波动率百分位分析
- 当前IV值获取（ATM期权）
- 历史IV百分位计算（基于250天历史数据）
- IV分布可视化

### 3. 交易策略建议
- 基于波动锥的波动率交易信号
- 基于IV百分位的期权交易建议
- 置信度评级（高/中/低）

### 4. 数据可视化
- 交互式波动锥图表
- IV分布直方图
- 实时数据更新

## 系统架构

```
pta_analysis/
├── volatility_cone.py      # 核心计算模块
├── volatility_api.py       # Flask API服务
├── templates/
│   └── volatility_index.html  # 前端界面
├── static/                 # 静态文件（图表、JSON数据）
├── data/                   # 数据文件
├── start_volatility_api.sh # 启动脚本
└── test_api.py            # API测试脚本
```

## 快速开始

### 1. 安装依赖
```bash
cd pta_analysis
pip3 install flask pandas numpy matplotlib scipy flask-cors
```

### 2. 启动API服务
```bash
# 方式1：直接运行
python3 volatility_api.py

# 方式2：使用启动脚本
./start_volatility_api.sh
```

服务将在 http://localhost:5001 启动

### 3. 访问Web界面
打开浏览器访问：http://localhost:5001

### 4. 运行分析（命令行）
```bash
python3 volatility_cone.py
```

## API接口

### 数据接口
- `GET /api/volatility/cone` - 获取波动锥数据
- `GET /api/volatility/iv-percentile` - 获取IV百分位数据
- `GET /api/volatility/signals` - 获取交易信号
- `GET /api/volatility/summary` - 获取综合分析摘要

### 图表接口
- `GET /api/volatility/chart/cone` - 获取波动锥图表（PNG）
- `GET /api/volatility/chart/iv-distribution` - 获取IV分布图表（PNG）

### 管理接口
- `POST /api/volatility/refresh` - 刷新缓存

## 数据说明

### 输入数据
1. **PTA期货数据**：`data/pta_1day.csv` 或 `data/pta_1min.csv`
   - 需要包含价格数据（close列）
   - 时间列可以是`datetime`或`date`

2. **期权IV数据**：`data/ta_iv_1min.csv`等
   - 由`scripts/compute_iv.py`生成
   - 包含隐含波动率计算

### 输出数据
1. **JSON分析结果**：`static/volatility_analysis.json`
2. **图表文件**：`static/volatility_cone.png`, `static/iv_percentile.png`
3. **缓存数据**：内存缓存（5分钟TTL）

## 交易策略逻辑

### 波动锥策略
- **短期波动率偏高**（短期>长期×1.2）：考虑卖出期权或做空波动率
- **短期波动率偏低**（短期<长期×0.8）：考虑买入期权或做多波动率

### IV百分位策略
- **IV≤25%**（历史低位）：适合买入期权（做多波动率）
- **IV≥75%**（历史高位）：适合卖出期权（做空波动率）
- **25%<IV<75%**（正常范围）：中性策略或方向性交易

## 配置参数

### 时间窗口配置（volatility_cone.py）
```python
WINDOWS = [5, 10, 20, 30, 60, 90, 120, 250]  # 天
```

### 颜色配置
```python
COLORS = {
    'cone': '#3498db',      # 波动锥
    'current': '#e74c3c',   # 当前值
    'percentile': '#2ecc71', # 百分位
    'median': '#f39c12',    # 中位数
    'q1_q3': '#95a5a6'      # 分位数区域
}
```

### API配置（volatility_api.py）
```python
app.run(
    host='0.0.0.0',
    port=5001,              # 服务端口
    debug=True,             # 调试模式
    threaded=True           # 多线程
)
```

## 使用示例

### Python调用示例
```python
import requests
import json

# 获取波动锥数据
response = requests.get('http://localhost:5001/api/volatility/cone')
data = response.json()

if data['success']:
    for item in data['data']:
        print(f"{item['window']}天窗口: {item['current']:.1f}%")
```

### 命令行测试
```bash
# 测试所有API端点
python3 test_api.py

# 运行完整分析
python3 volatility_cone.py
```

## 监控与维护

### 日志文件
- API服务日志：`logs/volatility_api.log`
- 进程PID文件：`volatility_api.pid`

### 数据更新
1. 期货数据：每日更新`data/pta_1day.csv`
2. 期权数据：运行`scripts/compute_iv.py`更新IV数据
3. 分析缓存：自动5分钟刷新，或手动调用`/api/volatility/refresh`

### 性能优化
- 数据缓存：5分钟TTL
- 图表预生成：减少实时计算
- 增量更新：仅处理新数据

## 故障排除

### 常见问题
1. **数据加载失败**
   - 检查数据文件路径和格式
   - 确认列名正确（date/datetime, close）

2. **API服务无法启动**
   - 检查端口5001是否被占用
   - 确认Python依赖已安装
   - 查看日志文件`logs/volatility_api.log`

3. **图表生成失败**
   - 检查matplotlib后端配置
   - 确认有写入`static/`目录的权限

4. **IV计算异常**
   - 检查期权数据完整性
   - 确认`compute_iv.py`已正确运行

### 调试模式
```bash
# 启用详细日志
export FLASK_DEBUG=1
python3 volatility_api.py
```

## 扩展开发

### 添加新指标
1. 在`volatility_cone.py`中添加计算函数
2. 在API中注册新端点
3. 更新前端显示

### 集成到现有系统
1. 将API服务部署到生产环境
2. 使用Nginx反向代理
3. 添加身份验证和速率限制

### 数据源扩展
1. 支持其他期货品种
2. 添加实时数据接口
3. 集成数据库存储

## 版本历史

### v1.0.0 (2024-04-08)
- 初始版本发布
- 基础波动锥和IV百分位功能
- Flask API和Web界面
- 交易策略建议

## 联系方式

如有问题或建议，请联系系统维护人员。

---

**注意**：本系统提供的交易建议仅供参考，不构成投资建议。实际交易请谨慎决策。
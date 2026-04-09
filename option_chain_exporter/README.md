# 期权链数据Excel导出系统

基于Python Flask + pandas的期权链数据Excel导出系统，支持完整期权链数据、PCR数据、希腊字母、历史数据导出。

## 功能特性

- ✅ **完整期权链数据导出**：包含看涨/看跌期权详细数据
- ✅ **PCR数据分析**：Put-Call Ratio数据计算与导出
- ✅ **希腊字母汇总**：Delta, Gamma, Theta, Vega, Rho等希腊字母分析
- ✅ **历史数据趋势**：30天历史数据导出
- ✅ **波动率曲面**：IV曲面数据导出
- ✅ **多Sheet Excel**：6个独立Sheet的Excel文件
- ✅ **格式化优化**：专业的Excel格式和样式

## 系统架构

```
option_chain_exporter/
├── main.py              # 主Flask应用
├── requirements.txt     # Python依赖
├── run.sh              # 启动脚本
├── README.md           # 说明文档
├── exports/            # 导出的Excel文件
└── uploads/            # 上传文件目录
```

## 快速开始

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 启动服务
```bash
./run.sh
# 或
python main.py
```

### 3. 访问Web界面
打开浏览器访问：http://localhost:5000

## API接口

### 获取示例数据
```bash
GET /api/data/sample
```
返回JSON格式的示例期权链数据。

### 导出Excel文件
```bash
GET /api/export/sample
```
下载包含示例数据的Excel文件。

### 健康检查
```bash
GET /api/health
```
返回系统状态信息。

## Excel文件结构

导出的Excel文件包含6个Sheet：

1. **基础信息** - 标的资产基本信息
2. **期权链数据** - 完整的期权链数据（看涨/看跌）
3. **PCR数据** - Put-Call Ratio分析数据
4. **历史数据** - 30天历史趋势数据
5. **希腊字母汇总** - 希腊字母统计分析
6. **波动率曲面** - 隐含波动率曲面数据

## 数据字段说明

### 期权链数据字段
- `symbol`: 期权代码
- `type`: 类型（call/put）
- `strike`: 行权价
- `expiry`: 到期日
- `last_price`: 最新价
- `bid/ask`: 买一/卖一价
- `volume`: 成交量
- `open_interest`: 未平仓合约
- `implied_volatility`: 隐含波动率
- `delta/gamma/theta/vega/rho`: 希腊字母
- `moneyness`: 虚实程度（ITM/ATM/OTM）

### PCR数据字段
- `expiry`: 到期日
- `pcr_volume`: 成交量PCR
- `pcr_open_interest`: 持仓量PCR
- `total_volume`: 总成交量
- `total_open_interest`: 总持仓量
- `avg_iv_call/avg_iv_put`: 平均隐含波动率
- `iv_skew`: 波动率偏度

## 扩展开发

### 添加自定义数据源
修改`main.py`中的`_generate_sample_data()`方法，替换为真实数据源。

### 添加新的Sheet
在`export_to_excel()`方法中添加新的Sheet导出逻辑。

### 自定义格式化
使用`openpyxl`库进行更复杂的Excel格式化。

## 依赖说明

- **Flask**: Web框架
- **pandas**: 数据处理和Excel导出
- **numpy**: 数值计算
- **openpyxl**: Excel文件操作
- **Werkzeug**: WSGI工具库

## 部署建议

### 生产环境部署
```bash
# 使用gunicorn部署
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 main:app
```

### Docker部署
```dockerfile
FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

## 许可证

MIT License
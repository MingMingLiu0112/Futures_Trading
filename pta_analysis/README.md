# PTA量化分析工程

## 工程结构

```
pta_analysis/
├── backtest/          # 回测脚本
│   ├── backtest_multi_v2.py    # 多周期联动策略（最新）
│   ├── backtest_final.py       # 日线策略
│   └── ...
├── charts/            # 缠论绘图
│   ├── draw_chan_v6.py
│   └── ...
├── data/              # K线数据
│   ├── pta_1min.csv          # 1分钟K线（8000根）
│   ├── pta_5min.csv          # 5分钟K线（8000根）
│   ├── pta_15min.csv         # 15分钟K线（8000根）
│   ├── pta_30min.csv         # 30分钟K线（8000根）
│   ├── pta_60min.csv         # 60分钟K线（8000根）
│   └── pta_1day.csv          # 日K线（2488根）
├── scripts/            # 定时脚本
├── docs/               # 文档
├── strategies/         # 策略模块（待整理）
└── reports/           # 报告（待整理）
```

## 数据来源

- **天勤量化TqSdk**：使用快期账户连接
- 账户：`mingmingliu`
- 合约：PTA主连（KQ.m@CZCE.TA）

## 策略框架

基于futures-trading skill的三维度框架：

1. **技术面**：MACD + RSI + MA均线
2. **多周期**：30分钟确认趋势 → 5分钟找买卖点
3. **仓位管理**：以损定量，单笔最大亏损2%

## 使用说明

### 安装依赖

```bash
pip install tqsdk akshare pandas numpy
```

### 获取数据

```python
from tqsdk import TqApi, TqAuth, TqKq

api = TqApi(TqKq(), auth=TqAuth('mingmingliu', 'Liuzhaoning2025'))
klines = api.get_kline_serial('KQ.m@CZCE.TA', 86400, data_length=8000)
```

### 运行回测

```bash
python backtest/backtest_multi_v2.py
```

## 最新回测结果

- 周期：2025-10-13 ~ 2026-04-03
- 交易次数：59次
- 胜率：59.3%
- 收益：-28.2%（需优化）

## TODO

- [ ] 优化策略参数
- [ ] 加入期权数据验证
- [ ] 实现缠论完整逻辑
- [ ] 添加实时监控功能

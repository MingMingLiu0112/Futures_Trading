# 📊 期货期权综合分析系统

基于隐含波动率(IV)的期货开仓信号分析工具，结合期权市场信号提升期货交易胜率。

## 🎯 核心功能

- **IV Rank 分析**: 当前IV在历史区间的位置
- **IV Skew 检测**: 看跌/看涨期权IV差值，辅助判断市场情绪
- **基差+IV共振**: 结合升贴水结构和波动率信号
- **技术面辅助**: 均线、MACD、RSI、布林带
- **飞书推送**: 分析结果自动推送到飞书群

## 📁 项目结构

```
futures_options/
├── analyzer.py          # 分析引擎
├── main.py              # 主入口
├── requirements.txt     # 依赖
├── signals/             # 信号计算
│   └── volatility.py    # 波动率信号
├── data/                # 数据获取
│   └── futures_data.py  # 期货数据
├── push/                # 推送模块
│   └── feishu.py        # 飞书推送
└── utils/               # 工具函数
    └── indicators.py    # 技术指标
```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置飞书 Webhook

```bash
export FEISHU_WEBHOOK="https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
```

或在项目根目录创建 `.env` 文件：

```
FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
```

### 3. 运行分析

```bash
python main.py
```

## ⚙️ GitHub Actions 部署

### 1. Fork 项目到 GitHub

### 2. 添加 Secrets

在 GitHub 仓库 Settings → Secrets 添加：
- `FEISHU_WEBHOOK`: 飞书机器人 Webhook URL

### 3. 自动运行

- 每天 08:00、15:00、21:00 自动分析（北京时间）
- 支持手动触发（workflow_dispatch）

## 📊 信号说明

| 信号 | 含义 | 操作 |
|------|------|------|
| IV Rank < 20% | IV极低，波动即将放大 | 卖期权+顺趋势开仓 |
| IV Rank > 80% | IV极高，注意风险 | 买期权对冲 |
| Skew > 0 | 市场买看跌保护 | 偏空信号 |
| Skew < 0 | 市场买看涨博涨 | 偏多信号 |
| 贴水 + IV高 | 现货紧张 | 多期货胜率高 |
| 升水 + IV低 | 产业套保 | 空期货胜率高 |

## 🔧 自定义品种

编辑 `main.py` 中的 `TARGET_SYMBOLS`：

```python
TARGET_SYMBOLS = ["CU", "AU", "AG", "RU", "SC"]  # 铜、黄金、白银、橡胶、原油
```

## ⚠️ 免责声明

本工具仅供参考，不构成投资建议。期权和期货交易有风险，请谨慎操作。

## 📝 License

MIT

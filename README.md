# PTA 期货交易分析平台

> 集缠论分析、期权分析、K线图表、波动率研究于一体的期货实盘交易辅助工具

## 🏗️ 项目架构

```
pta_trading/
├── pta_analysis/          # ⭐ 主项目：PTA期货分析平台
│   ├── web_app_integrated.py  # Flask主应用（端口8424）
│   ├── chan_analyzer.py       # 缠论多级别递归算法
│   ├── chan_simple.py         # 缠论简化版
│   ├── chan_wrapper.py        # 数据源封装
│   ├── volatility_cone.py     # 波动率锥
│   ├── macro_news.py          # 宏观新闻
│   ├── templates/             # HTML模板
│   ├── static/                 # 静态资源
│   ├── data/                  # SQLite数据库
│   ├── scripts/               # 运维脚本
│   └── chan_analysis/         # 缠论引擎
│
├── futures_options/         # 期货期权分析工具
├── iv_curve_component/      # 隐含波动率曲线组件
├── option_chain_exporter/   # 期权链数据导出工具
├── option-chain-ui/         # 期权链前端界面（React）
└── chan_learn/             # 缠论学习资料
```

## 🚀 快速部署

```bash
# 安装依赖
pip install -r pta_analysis/requirements.txt

# 启动主服务
cd pta_analysis
python web_app_integrated.py

# 访问
open http://47.100.97.88/kline
```

## 📊 主要功能

| 功能 | 说明 | 状态 |
|------|------|------|
| K线图表 | ECharts蜡烛图 + MACD + KDJ | ✅ 运行中 |
| 缠论分析 | 笔 / 线段 / 中枢 / 买卖点 | ✅ 运行中 |
| 波动率锥 | 历史波动率分布 | ✅ 运行中 |
| 期权链 | T型期权链界面 | ✅ 运行中 |
| 宏观新闻 | 期货相关新闻聚合 | ✅ 运行中 |
| 天勤实时 | TqSDK + Redis（需安装Redis） | 🔜 待启用 |

## 📦 依赖

```
Flask >= 2.3
akshare >= 1.13
pandas >= 2.0
numpy >= 1.24
scipy >= 1.10
matplotlib >= 3.7
requests >= 2.28
python-dotenv >= 1.0
```

## 🌐 线上地址

- **K线图**: http://47.100.97.88/kline
- **API接口**: http://47.100.97.88/api/kline, /api/chan

## 📝 项目结构说明

- `pta_analysis/` — 主项目，线上运行
- `futures_options/` — 期货期权分析脚本集
- `iv_curve_component/` — IV曲线可视化组件
- `option_chain_exporter/` — 期权链Excel导出
- `option-chain-ui/` — 前端期权链界面（React）
- `chan_learn/` — 缠论学习资料

## ⚠️ 注意

- OpenClaw 工作空间配置文件（AGENTS.md / SOUL.md / USER.md / HEARTBEAT.md 等）在 `codeman/` 目录，不在本仓库
- `futures_options/` 有独立 git 历史，作为子模块保留

# backtest/ 状态说明

**最后更新**: 2026-07-19 (v2.11.95m)

## 状态: STABLE LEGACY (不是 deprecated)

这个目录是**回测框架**, **仍是 web_app_integrated.py 的运行依赖**, 不要删除.

### 当前活跃引用 (2026-07-19 验证)

```
pta_analysis/web_app_integrated.py:
  - L56:  from backtest.strategy_import_api import register_strategy_import_routes
  - L59:  from backtest.backtest_engine import BacktestEngine
  - L3036: from backtest import GridOptimizer, ParameterGrid, run_backtest_for_optimization
  - L3105: from backtest import StrategyComparator
  - L3133: from backtest import BacktestExporter

pta_analysis/main.py:
  - L16:  from backtest import BacktestEngine

pta_analysis/api_service.py:
  - L18:  from backtest import BacktestEngine

pta_analysis/cli.py:
  - args.backtest -> TradingSystem().run_backtest() -> backtest.BacktestEngine
```

**结论**: 5 个 import 路径, 删 backtest/ 会直接 502 整个 PTA 服务.

### 为什么看起来像"被遗忘"

- 18 个 .py 文件最后修改 = **2026-05-09 ~ 05-11** (70+ 天前)
- 最近 7 天的 git commit 里 backtest/ 文件 0 改动
- **但代码稳定 + 仍被引用**, 不是 deprecated, 是 **stable**

### 跟 PTA 主决策框架的关系

- PTA 主页研报的 4 维决策 (PAIN/GEX/资金意图/情绪) **不依赖** backtest/
- backtest/ 用于独立的回测入口 (CLI `python cli.py --backtest <strategy>` + web 路由 `/api/backtest/*`)
- 两条业务线**并行但互不干扰**

### 新功能应该放哪

- **4 维决策相关** → `pta_analysis/scripts/judge_state.py` 或 `scripts/decision_layer_service.py`
- **新回测策略** → `pta_analysis/backtest/strategy/<新文件>.py` (沿用现有结构)
- **新数据源** → `pta_analysis/backtest/lab/` (data lab) 或 `pta_analysis/scripts/`

**不要新建** 平行于 backtest/ 的新回测框架 (会分裂), 而是补到现有框架里.

### user_strategies/ 目录 (2026-07-18 创建, 当前空)

```
backtest/user_strategies/   # 7/18 创建, 未跟踪 git
```

- 创建目的: 用户/agent 实验用, 放 user 自定义策略
- 当前状态: **空目录**
- 处理: **保留不动** (git 不跟踪空目录, 但本地存在)
- 如果未来需要正式 user strategies 模式: 加 `user_strategies/__init__.py` 标记 package + 在 `strategy_import_api.py` 加路由

### 历史 commit 信息

| 时间 | commit | 说明 |
|---|---|---|
| 2026-05-09 ~ 05-11 | (多次) | backtest/ 框架 v1 上线 (native_engine / backtest_engine / optimizer / walkforward / strategy_base 等) |
| 2026-05-25 | (无 commit) | `__pycache__` 自动生成 (Python 缓存, 不进 commit) |
| 2026-07-18 | (无 commit) | `user_strategies/` 目录创建 (本地, 未 git add) |
| 2026-07-19 | v2.11.95m (本 commit) | 加 STATUS.md (本文档), 标记 stable legacy |

### 反跑偏警示 (为什么写这个文件)

写这个 STATUS.md 的目的是**防止未来有人 (1) 看到 backtest/ 70+ 天没动, 当成死代码归档到 `_legacy/`; (2) 或者写代码时不知道 backtest/ 还有人在用, 重复造轮子**.

跟 `scripts/_legacy/` (8 个真死脚本) 不同, backtest/ **还在被 web_app_integrated.py 主动 import**, 归档或删除会立即导致生产环境崩溃.

---

如果你正在读这个文件, 想确认 backtest/ 是否还在用:

```bash
cd pta_analysis
grep -rln "from backtest\|import backtest" --include="*.py" | grep -v __pycache__
# 期望: web_app_integrated.py / main.py / api_service.py / cli.py (4 个文件)
```

如果输出 0 行, 那 backtest/ 才真的可以归档 (那时再走 `_legacy/` 流程).
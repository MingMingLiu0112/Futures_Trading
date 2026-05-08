# PTA 回测平台设计方案

> 基于现有 `web_app_integrated.py` + `strategies/pta_option_strategy.py` + `backtest/` 模块，构建一套完整的在线回测系统。

---

## 一、项目现状

### 已有资产

| 类别 | 路径 | 说明 |
|------|------|------|
| 回测脚本（独立） | `backtest/backtest_*.py` | 12个版本，用pandas计算，print输出 |
| 策略模块 | `strategies/pta_option_strategy.py` | dataclass策略框架，含杀期权/期权墙/PCR/共振信号 |
| 策略API | `strategies/strategy_api.py` | Flask API，完整分析接口 |
| 历史K线 | `data/pta_1day.csv` 等 | CSV格式，多周期（1min/5min/15min/30min/60min/1day） |
| 实时数据 | `realtime/tqsdk_realtime.py` | TqSdk天勤实时行情 |
| 缠论核心 | `core/chan_algorithm.py` | 笔/段/中枢/级别计算 |

### 差距分析

- 所有回测脚本是**独立Python文件**，无法通过Web页面触发
- 结果只能`print`，没有可视化图表
- 没有仓位管理/资金曲线/回撤分析
- 没有参数优化/参数扫描功能
- 没有绩效归因（盈利来源/胜率/盈亏比/持仓时间）

---

## 二、系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                      前端 (HTML/JS)                         │
│   回测页面: kline_lightweight.html + backtest_panel.html    │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP / SSE (长轮询)
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    Flask API 层                              │
│   /api/backtest/run        启动回测任务                      │
│   /api/backtest/status     查询进度                          │
│   /api/backtest/cancel     取消任务                          │
│   /api/backtest/result     获取结果                          │
│   /api/backtest/equity_curve 资金曲线数据                    │
│   /api/backtest/trades     交易明细                          │
└──────────────────────────┬──────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
┌──────────────────────────┐  ┌──────────────────────────────┐
│   历史数据存储            │  │   回测引擎 (BacktestEngine)  │
│   data/kline/            │  │   strategies/                │
│   data/option/           │  │   core/chan_algorithm.py     │
│   data/daily/            │  │   strategies/pta_option_*.py │
│   data/fundamental/       │  │                              │
└──────────────────────────┘  └──────────────────────────────┘
```

---

## 三、数据层设计

### 3.1 历史K线数据存储

**目标格式：** Parquet 列式存储（压缩率高，读取快）

```
data/kline/
├── czce.ta_1min.parquet
├── czce.ta_5min.parquet
├── czce.ta_15min.parquet
├── czce.ta_30min.parquet
├── czce.ta_60min.parquet
├── czce.ta_1day.parquet
├── czce.ma_1day.parquet      # MA品种
└── czce.rm_1day.parquet      # 醇类关联
```

**Parquet Schema：**

```python
{
    "symbol": "CZCE.TA509",      # 合约代码
    "datetime": "2024-01-03T09:00:00",  # UTC+8时间
    "open": 5800.0,
    "high": 5850.0,
    "low": 5790.0,
    "close": 5830.0,
    "volume": 125000,
    "open_interest": 850000,
    "preclose": 5780.0,         # 前收（用于计算涨跌）
}
```

**数据来源：**
- 现有 CSV → 一次性转为 Parquet（`tools/migrate_kline_to_parquet.py`）
- 增量更新：每日收盘后 TqSdk 自动追加（`realtime/tqsdk_realtime.py` 已实现）

### 3.2 期权历史数据

```
data/option/
├── czce.ta_option_202501.pq
├── czce.ta_option_202502.pq
└── ...
```

**Schema：**

```python
{
    "trade_date": "2025-01-15",
    "expiry": "20250128",        # 到期日
    "strike": 5800,
    "option_type": "C",           # C=P_CALL, P=PUT
    "close": 185.0,
    "iv": 0.22,
    "delta": 0.55,
    "gamma": 0.002,
    "theta": -8.5,
    "vega": 0.35,
    "open_interest": 12500,
    "volume": 3800,
    "underlying": 5812.0,
}
```

### 3.3 宏观/基本面数据

```
data/fundamental/
├── brent_daily.csv
├── px_daily.csv
├── inventory_weekly.csv
└── pta_social_inventory.csv
```

---

## 四、回测引擎设计

### 4.1 核心类结构

```
backtest/
├── __init__.py
├── engine.py              # BacktestEngine 主引擎
├── data_loader.py         # 数据加载（Parquet + CSV）
├── position.py            # 持仓与资金管理
├── risk_manager.py        # 风险管理（止损/止盈/仓位）
├── performance.py          # 绩效指标计算
├── serializers.py          # 结果序列化（JSON输出）
├── strategies/
│   ├── __init__.py
│   ├── macd_cross.py      # MACD金叉死叉策略
│   ├── chan_macd_resonance.py  # 缠论+MACD共振策略
│   ├── option_kill_stage.py    # 杀期权阶段策略
│   ├── option_wall.py     # 期权墙突破策略
│   └── combined.py        # 综合多信号策略
└── migrators/
    └── csv_to_parquet.py  # CSV迁移工具
```

### 4.2 BacktestEngine 主引擎

```python
class BacktestEngine:
    """
    PTA回测引擎
    - 事件驱动，逐K线推进
    - 支持多信号组合
    - 完整资金管理
    - 绩效归因
    """

    def __init__(
        self,
        symbol: str,            # 'CZCE.TA509'
        period: str,             # '1day', '60min', ...
        start_date: str,         # '2024-01-01'
        end_date: str,           # '2025-12-31'
        initial_capital: float,  # 100000.0
        commission_rate: float,  # 0.0003 (万三)
        slippage: float,        # 滑点（跳）
    ):

    def set_data(self, kline_df: pd.DataFrame):
        """注入K线数据"""

    def add_signal(self, signal_fn: callable):
        """注册信号函数，接收OHLCV，返回 signal: 1(多)/-1(空)/0(无)"""

    def run(self) -> BacktestResult:
        """执行回测，返回结果"""

    def get_equity_curve(self) -> pd.DataFrame:
        """资金曲线（日频）"""

    def get_trades(self) -> List[Trade]:
        """交易明细"""
```

### 4.3 信号函数接口

```python
# 策略注册示例
def my_signal(df: pd.DataFrame, i: int) -> int:
    """
    df: 当前K线 DataFrame（含指标列）
    i: 当前索引
    return: 1(做多信号) / -1(做空信号) / 0(无信号)
    """
    if i < 30:
        return 0

    # MACD金叉 + 价格站上MA10
    if df['macd_golden'].iloc[i] and df['close'].iloc[i] > df['ma10'].iloc[i]:
        return 1  # 做多

    # MACD死叉
    if df['macd_dead'].iloc[i]:
        return -1  # 做空

    return 0

engine.add_signal(my_signal)
```

### 4.4 支持的策略模板

| 策略名称 | 文件 | 核心逻辑 |
|---------|------|---------|
| MACD金叉死叉 | `strategies/macd_cross.py` | DIF>DEA 金叉做多，死叉做空/平 |
| 缠论+MACD共振 | `strategies/chan_macd_resonance.py` | 缠论一买/二买 + MACD底背离共振 |
| 杀期权阶段 | `strategies/option_kill_stage.py` | 临近到期+杀期权价区识别，反向操作 |
| 期权墙突破 | `strategies/option_wall.py` | 价格突破PUT墙（支撑）或CALL墙（阻力）|
| 多信号综合 | `strategies/combined.py` | MACD + 缠论 + 基本面 + 期权PCR 综合评分 |

---

## 五、风险管理设计

```python
class RiskManager:
    """
    风险管理规则（可配置开关）
    """

    def __init__(self):
        self.max_position_size = 10       # 最大持仓手数
        self.max_loss_per_trade = 0.02    # 单笔最大亏损（资金比例）
        self.stop_loss_ratio = 0.02       # 止损比例
        self.take_profit_ratio = 0.05     # 止盈比例
        self.max_drawdown = 0.10          # 最大回撤上限（触发强制平仓）

    def check_entry(self, capital: float, price: float, direction: int) -> int:
        """计算实际开仓手数"""

    def should_stop_loss(self, entry_price, current_price, direction, unrealized_pnl, capital) -> bool:
        """判断是否触发止损"""

    def should_take_profit(self, entry_price, current_price, direction, unrealized_pnl, capital) -> bool:
        """判断是否触发止盈"""

    def should_force_close(self, current_drawdown: float) -> bool:
        """判断是否触发最大回撤强制平仓"""
```

---

## 六、绩效指标

```python
@dataclass
class PerformanceMetrics:
    # 收益类
    total_return: float           # 总收益率
    annual_return: float          # 年化收益率
    sharpe_ratio: float           # 夏普比率
    calmar_ratio: float           # 卡玛比率（年化收益/最大回撤）

    # 风险类
    max_drawdown: float           # 最大回撤
    max_drawdown_duration: int    # 最大回撤持续天数
    max_consecutive_loss: int     # 最大连续亏损次数
    volatility: float             # 年化波动率

    # 交易类
    total_trades: int            # 总交易次数
    win_rate: float              # 胜率
    avg_win: float               # 平均盈利
    avg_loss: float              # 平均亏损
    profit_loss_ratio: float     # 盈亏比
    avg_holding_days: float      # 平均持仓天数

    # 持仓分析
    long_holding_days: float     # 多头累计持仓天数
    short_holding_days: float    # 空头累计持仓天数
    total_trading_days: int      # 总交易天数

    # 月度统计
    monthly_returns: Dict[str, float]  # {YYYY-MM: return}


@dataclass
class Trade:
    trade_id: int
    direction: str              # 'long' / 'short'
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    lots: int
    commission: float
    slippage_cost: float
    pnl: float                  # 净盈亏
    pnl_pct: float              # 盈亏比例
    holding_days: int
    exit_reason: str            # 'stop_loss' / 'take_profit' / 'signal' / 'force_close'
    equity_at_entry: float      # 入场时资金
```

---

## 七、API 设计

### 7.1 启动回测

```
POST /api/backtest/run
Content-Type: application/json

{
    "strategy": "macd_cross",           // 策略名称
    "symbol": "CZCE.TA509",             // 合约代码
    "period": "1day",                   // 周期
    "start_date": "2024-01-01",
    "end_date": "2025-05-01",
    "initial_capital": 100000,
    "params": {                          // 策略参数
        "fast_period": 12,
        "slow_period": 26,
        "signal_period": 9,
        "stop_loss": 0.02,
        "take_profit": 0.05,
        "ma_period": 10
    },
    "risk": {
        "max_position": 10,
        "commission_rate": 0.0003,
        "slippage": 1
    }
}

Response:
{
    "success": true,
    "task_id": "bt_20250507_001",
    "status": "running",
    "message": "回测任务已启动"
}
```

### 7.2 查询进度（SSE）

```
GET /api/backtest/status?task_id=bt_20250507_001

Response (SSE stream):
event: progress
data: {"progress": 45, "current_date": "2024-08-15", "trades_count": 12}

event: complete
data: {"progress": 100, "task_id": "bt_20250507_001"}

event: result
data: {"success": true, "result_id": "bt_20250507_001"}
```

### 7.3 获取结果

```
GET /api/backtest/result?task_id=bt_20250507_001

Response:
{
    "success": true,
    "summary": {
        "total_return": 0.283,
        "annual_return": 0.142,
        "sharpe_ratio": 1.85,
        "max_drawdown": 0.082,
        "win_rate": 0.58,
        "total_trades": 34,
        "profit_loss_ratio": 1.92
    },
    "equity_curve_url": "/api/backtest/equity_curve?task_id=bt_20250507_001",
    "trades_url": "/api/backtest/trades?task_id=bt_20250507_001"
}
```

### 7.4 资金曲线

```
GET /api/backtest/equity_curve?task_id=bt_20250507_001

Response:
{
    "dates": ["2024-01-02", "2024-01-03", ...],
    "equity": [100000, 101200, 100800, ...],
    "drawdown": [0, -0.008, -0.012, ...],
    "benchmark": [100000, 100500, 100200, ...]  # 同周期买入持有基准
}
```

### 7.5 交易明细

```
GET /api/backtest/trades?task_id=bt_20250507_001

Response:
{
    "trades": [
        {
            "trade_id": 1,
            "direction": "long",
            "entry_date": "2024-03-12",
            "entry_price": 5850,
            "exit_date": "2024-03-19",
            "exit_price": 5940,
            "lots": 3,
            "pnl": 2700,
            "pnl_pct": 0.0154,
            "exit_reason": "take_profit",
            "holding_days": 5
        },
        ...
    ]
}
```

---

## 八、前端页面设计

### 8.1 页面路径

- 独立页面：`templates/backtest.html`
- 或作为 `kline_lightweight.html` 的一个 Tab（推荐整合到现有页面）

### 8.2 页面布局

```
┌────────────────────────────────────────────────────────────────┐
│  📊 回测平台                                                    │
├──────────────────────┬─────────────────────────────────────────┤
│                      │                                         │
│  【策略参数】         │   【资金曲线 + Benchmark】               │
│                      │   (ECharts 折线图)                       │
│  ● 选择策略:         │                                         │
│    ○ MACD金叉死叉    │   ─────────────────────────────────     │
│    ○ 缠论+MACD共振   │                                         │
│    ○ 杀期权阶段      │                                         │
│    ○ 期权墙突破      │   【绩效概览面板】                        │
│    ○ 多信号综合      │   总收益 | 年化 | 夏普 | 最大回撤          │
│                      │   胜率 | 盈亏比 | 交易次数 | 持仓时间       │
│  ● 交易品种: PTA509  │                                         │
│                      │   ─────────────────────────────────     │
│  ● 周期: [日线 ▼]    │                                         │
│                      │   【K线图表 + 交易标记】                   │
│  【技术指标参数】     │   (K线 + 入场/出场/止损/止盈标记)          │
│  MACD快速: [12]      │                                         │
│  MACD慢速: [26]      │                                         │
│  信号周期: [9]       │   ─────────────────────────────────     │
│  MA周期: [10]        │                                         │
│                      │   【MACD副图 + 入场信号标注】              │
│  【风控参数】         │                                         │
│  初始资金: [100000]  │   ─────────────────────────────────     │
│  止损比例: [2%]      │                                         │
│  止盈比例: [5%]      │   【交易明细表】                          │
│  手续费: [0.03%]     │   序号 | 方向 | 入场日 | 出场日 | 盈亏    │
│  滑点: [1]           │   ...                                    │
│                      │                                         │
│  【回测区间】         │                                         │
│  开始: [2024-01-01]  │                                         │
│  结束: [2025-05-01]  │                                         │
│                      │                                         │
│  [▶ 开始回测]        │                                         │
│                      │                                         │
└──────────────────────┴─────────────────────────────────────────┘
```

### 8.3 K线图表 — 交易标记叠加

在现有 `kline_lightweight.html` 的 LightweightCharts 上叠加：

```javascript
// 回测入场标记
trades.forEach(trade => {
    if (trade.direction === 'long') {
        mainChart.addLine({
            time: trade.entry_date,
            color: '#26a69a',
            lineStyle: LightweightCharts.LineStyle.Dashed,
            shape: 'arrowUp',
            text: `多 ${trade.entry_price}`,
        });
    }
});

// 止损/止盈水平线
addLineMarker(trade.stop_loss_price, '#ef5350', 'SL');
addLineMarker(trade.take_profit_price, '#ffd700', 'TP');
```

### 8.4 资金曲线组件

```javascript
// 使用 ECharts
const equityChart = echarts.init(document.getElementById('equityChart'));

const option = {
    title: { text: '资金曲线 vs 买入持有基准', textStyle: { color: '#ccc' } },
    tooltip: { trigger: 'axis' },
    legend: {
        data: ['策略资金', '买入持有'],
        textStyle: { color: '#888' }
    },
    xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: '#444' } },
        axisLabel: { color: '#888' }
    },
    yAxis: {
        type: 'value',
        axisLine: { lineStyle: { color: '#444' } },
        splitLine: { lineStyle: { color: '#333' } },
        axisLabel: { color: '#888', formatter: v => (v/10000).toFixed(0)+'万' }
    },
    series: [
        {
            name: '策略资金',
            type: 'line',
            data: equity,
            smooth: true,
            lineStyle: { color: '#26a69a', width: 2 },
            areaStyle: { color: 'rgba(38,166,155,0.1)' }
        },
        {
            name: '买入持有',
            type: 'line',
            data: benchmark,
            smooth: true,
            lineStyle: { color: '#ef5350', width: 1, type: 'dashed' }
        }
    ]
};
```

### 8.5 绩效指标面板

```html
<div class="perf-grid">
    <div class="perf-card highlight">
        <div class="perf-label">总收益率</div>
        <div class="perf-value up">+28.3%</div>
    </div>
    <div class="perf-card">
        <div class="perf-label">年化收益率</div>
        <div class="perf-value up">+14.2%</div>
    </div>
    <div class="perf-card">
        <div class="perf-label">夏普比率</div>
        <div class="perf-value">1.85</div>
    </div>
    <div class="perf-card warning">
        <div class="perf-label">最大回撤</div>
        <div class="perf-value down">-8.2%</div>
    </div>
    <div class="perf-card">
        <div class="perf-label">胜率</div>
        <div class="perf-value">58%</div>
    </div>
    <div class="perf-card">
        <div class="perf-label">盈亏比</div>
        <div class="perf-value">1.92</div>
    </div>
    <div class="perf-card">
        <div class="perf-label">总交易次数</div>
        <div class="perf-value">34</div>
    </div>
    <div class="perf-card">
        <div class="perf-label">平均持仓</div>
        <div class="perf-value">4.2天</div>
    </div>
</div>
```

---

## 九、数据获取方案

### 9.1 数据来源总览

| 数据类型 | 来源 | 说明 |
|---------|------|------|
| K线历史 | TqSdk `get_kline_serial` | 免费，实时，支持日/分钟/Tick |
| CSV历史 | `data/pta_1day.csv` 等 | 现有历史，已积累多年 |
| 实时行情 | TqSdk | 已实现于 `realtime/tqsdk_realtime.py` |
| 期权链 | 郑商所TP1952接口 | 已实现于 `strategies/pta_option_strategy.py` |
| 宏观数据 | akshare | 原油/石脑油/PX现货/库存 |

### 9.2 CSV → Parquet 迁移脚本

```python
# tools/migrate_kline_to_parquet.py
import pandas as pd
from pathlib import Path

def migrate_all():
    base = Path("data")
    for csv_file in base.glob("pta_*min.csv"):
        df = pd.read_csv(csv_file)
        # 标准化列名
        df = df.rename(columns={
            'date': 'datetime',
            ' CZCE.TA': 'close',  # 示例，按实际调整
        })
        # 补全必要字段
        df['symbol'] = 'CZCE.TA509'
        df['preclose'] = df['close'].shift(1).fillna(df['close'])
        # 转为Parquet
        out = csv_file.with_suffix('.parquet')
        df.to_parquet(out, compression='zstd')
        print(f"Migrated: {csv_file} -> {out}")

    # 增量追加（新数据追加到已有Parquet）
    def append_klines(parquet_path: str, new_rows: pd.DataFrame):
        existing = pd.read_parquet(parquet_path)
        combined = pd.concat([existing, new_rows]).drop_duplicates(subset=['datetime','symbol'])
        combined.to_parquet(parquet_path, compression='zstd')
```

### 9.3 每日定时数据更新

利用现有 `restart.sh` 同体系的 cron job，在每日 **16:00（收盘后）** 自动执行：

```bash
# crontab -e
0 16 * * 1-5 cd /home/admin/.openclaw/workspace/Futures_Trading/pta_analysis && python tools/migrate_kline_to_parquet.py --append >> logs/data_update.log 2>&1
```

---

## 十、与现有代码的集成

### 10.1 复用 `strategies/pta_option_strategy.py`

```python
# backtest/strategies/combined.py
from strategies.pta_option_strategy import (
    MarketRegime, KillOptionStageDetector, OptionWallDetector,
    PCRMonitor, ResonanceSignalGenerator
)

class CombinedSignal:
    """综合多信号评分策略"""

    def __init__(self, params: dict):
        self.kill_detector = KillOptionStageDetector(params.get('kill_days', 7))
        self.pcr_monitor = PCRMonitor()
        self.wall_detector = OptionWallDetector()

    def score(self, row) -> int:
        """
        综合评分：返回 -2~+2
        -2: 强烈做空
        -1: 偏空
         0: 中性
        +1: 偏多
        +2: 强烈做多
        """
        score = 0

        # PCR信号
        if self.pcr_monitor.is_bullish():
            score += 1
        elif self.pcr_monitor.is_bearish():
            score -= 1

        # 期权墙信号
        if self.wall_detector.has_ceil_wall_broken(row.price):
            score += 1

        return score
```

### 10.2 复用 `core/chan_algorithm.py`

```python
# backtest/strategies/chan_macd_resonance.py
from core.chan_algorithm import ChanAlgorithm

class ChanMacdResonance:
    """
    缠论 + MACD 共振策略
    买入信号：一买（底背离）+ MACD金叉
    卖出信号：一卖（顶背离）+ MACD死叉
    """

    def __init__(self, config: dict):
        self.chan = ChanAlgorithm(...)
        self.macd_fast = config.get('fast', 12)
        self.macd_slow = config.get('slow', 26)

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        # 计算MACD
        df['diff'] = ...
        df['dea'] = ...

        # 计算缠论笔（逐K线更新）
        self.chan.load_data(df)
        bi_signals = self.chan.compute_bi()

        # 背离检测
        df['bullish_divergence'] = self._detect_divergence(df, bi_signals, 'low')
        df['bearish_divergence'] = self._detect_divergence(df, bi_signals, 'high')

        return df

    def signal(self, row) -> int:
        if row['bullish_divergence'] and row['macd_golden']:
            return 1
        if row['bearish_divergence'] and row['macd_dead']:
            return -1
        return 0
```

### 10.3 新增 Flask API 端点

```python
# web_app_integrated.py 新增

@app.route('/api/backtest/run', methods=['POST'])
def api_backtest_run():
    from backtest.engine import BacktestEngine
    from backtest.strategies import get_strategy_by_name

    data = request.get_json()
    task_id = f"bt_{dt.now().strftime('%Y%m%d_%H%M%S')}"

    # 参数校验
    required = ['strategy', 'symbol', 'period', 'start_date', 'end_date']
    for field in required:
        if field not in data:
            return jsonify({'success': False, 'error': f'missing: {field}'}), 400

    # 注册任务（异步执行）
    task = {
        'task_id': task_id,
        'status': 'pending',
        'params': data,
        'result': None,
        'progress': 0,
        'created_at': dt.now().isoformat(),
    }
    BACKTEST_TASKS[task_id] = task

    # 异步执行回测（不阻塞HTTP响应）
    def _run():
        try:
            engine = BacktestEngine(
                symbol=data['symbol'],
                period=data['period'],
                start_date=data['start_date'],
                end_date=data['end_date'],
                initial_capital=data.get('initial_capital', 100000),
                commission_rate=data.get('commission_rate', 0.0003),
                slippage=data.get('slippage', 1),
            )
            engine.set_data(load_parquet(data['symbol'], data['period']))
            strategy_fn = get_strategy_by_name(data['strategy'])
            engine.add_signal(strategy_fn(data.get('params', {})))
            result = engine.run()
            task['result'] = result.to_dict()
            task['status'] = 'complete'
        except Exception as e:
            task['error'] = str(e)
            task['status'] = 'error'
        task['progress'] = 100

    threading.Thread(target=_run, daemon=True).start()

    return jsonify({
        'success': True,
        'task_id': task_id,
        'status': 'running',
        'message': '回测任务已启动'
    })


@app.route('/api/backtest/status')
def api_backtest_status():
    task_id = request.args.get('task_id')
    task = BACKTEST_TASKS.get(task_id)
    if not task:
        return jsonify({'success': False, 'error': 'task not found'}), 404
    return jsonify({
        'success': True,
        'task_id': task_id,
        'status': task['status'],
        'progress': task.get('progress', 0),
        'error': task.get('error'),
    })


@app.route('/api/backtest/result')
def api_backtest_result():
    task_id = request.args.get('task_id')
    task = BACKTEST_TASKS.get(task_id)
    if not task:
        return jsonify({'success': False, 'error': 'task not found'}), 404
    if task['status'] != 'complete':
        return jsonify({'success': False, 'status': task['status'], 'error': 'not ready'}), 202
    return jsonify({'success': True, **task['result']})


@app.route('/api/backtest/equity_curve')
def api_backtest_equity():
    task_id = request.args.get('task_id')
    task = BACKTEST_TASKS.get(task_id)
    if not task or task['status'] != 'complete':
        return jsonify({'success': False, 'error': 'task not found'}), 404
    equity = task['result'].get('equity_curve', {})
    return jsonify({'success': True, **equity})


@app.route('/api/backtest/trades')
def api_backtest_trades():
    task_id = request.args.get('task_id')
    task = BACKTEST_TASKS.get(task_id)
    if not task or task['status'] != 'complete':
        return jsonify({'success': False, 'error': 'task not found'}), 404
    return jsonify({'success': True, 'trades': task['result'].get('trades', [])})


# 任务存储（内存dict，重启后丢失；生产环境建议用Redis）
BACKTEST_TASKS: Dict[str, dict] = {}
```

---

## 十一、实现路线图

### Phase 1：基础设施（1~2天）

- [ ] 创建 `backtest/` 目录结构
- [ ] 实现 `engine.py` 核心引擎
- [ ] 实现 `data_loader.py`（Parquet + CSV）
- [ ] 实现 `performance.py` 绩效计算
- [ ] 将历史CSV迁移为Parquet格式

### Phase 2：基础策略（1~2天）

- [ ] 实现 `strategies/macd_cross.py`（MACD金叉死叉）
- [ ] 实现 `strategies/chan_macd_resonance.py`（缠论+MACD共振）
- [ ] 集成 `core/chan_algorithm.py` 笔/段/中枢

### Phase 3：API层（1天）

- [ ] Flask API：`/api/backtest/run|status|result|equity_curve|trades`
- [ ] 异步任务管理（threading）
- [ ] 内存任务存储（未来迁移到Redis）

### Phase 4：前端页面（1~2天）

- [ ] `templates/backtest.html` 独立页面
- [ ] 参数配置表单
- [ ] ECharts 资金曲线
- [ ] LightweightCharts 叠加交易标记
- [ ] 绩效指标面板
- [ ] 交易明细表格

### Phase 5：高级功能（2~3天）

- [ ] 参数优化（参数扫描暴力遍历）
- [ ] 多周期对比（同一策略在日线/60min下对比）
- [ ] 敏感性分析（改变止损比例对夏普的影响）
- [ ] 期权策略回测（价差策略、备兑策略）
- [ ] 邮件/飞书通知回测完成

---

## 十二、关键设计决策

### 决策 1：为什么不直接用 Backtrader/Vnpy 回测框架？

| 对比项 | Backtrader/Vnpy | 自研引擎（本方案） |
|-------|----------------|----------------|
| 集成难度 | 高，需改造适配现有缠论/期权模块 | 低，直接复用 `core/` 和 `strategies/` |
| 数据格式 | 需转换为框架格式 | 直接使用 Parquet 原生存储 |
| 实时/历史统一 | 割裂 | 共享同一数据源 |
| 定制能力 | 需学习框架内部 | 完全可控 |

**结论：** 自研引擎初期开发成本略高，但长期可维护性、数据一致性和功能扩展性远优于强依赖第三方框架。

### 决策 2：为什么用 Parquet 而不是继续用 CSV？

- Parquet 压缩率约 **10:1**（CTA数据压缩后 1GB → 100MB）
- 列式查询只需读取需要的列，读取速度快 **5~10倍**
- 支持 schema 验证，避免数据损坏
- Python（Pandas）/ Spark / DuckDB 多引擎共用

### 决策 3：为什么不支持 Tick 级回测？

- PTA 期货 Tick 数据量：每天约 **200万行**，全年 **5亿行**
- Tick 级回测需要：
  - 毫秒级撮合引擎（当前是日/分钟级）
  - 订单簿模拟（当前没有）
  - 存储成本 10倍以上
- 建议：**分钟级回测足够**，Tick 信号用于盘后分析

---

## 十三、文件清单

```
pta_analysis/
├── backtest/
│   ├── __init__.py
│   ├── engine.py              ← 核心引擎（新增）
│   ├── data_loader.py          ← 数据加载（新增）
│   ├── position.py             ← 仓位资金管理（新增）
│   ├── risk_manager.py         ← 风险管理（新增）
│   ├── performance.py          ← 绩效计算（新增）
│   ├── serializers.py          ← JSON序列化（新增）
│   └── strategies/
│       ├── __init__.py
│       ├── macd_cross.py       ← 策略1（新增）
│       ├── chan_macd_resonance.py ← 策略2（新增）
│       ├── option_kill_stage.py   ← 策略3（新增）
│       ├── option_wall.py        ← 策略4（新增）
│       └── combined.py          ← 综合策略（新增）
├── data/
│   ├── kline/                  ← Parquet 历史数据（新增目录）
│   └── option/                 ← 期权历史数据（新增目录）
├── tools/
│   └── migrate_kline_to_parquet.py  ← CSV迁移工具（新增）
├── templates/
│   └── backtest.html           ← 回测页面（新增）
├── web_app_integrated.py       ← 新增5个API端点（修改）
└── docs/
    └── BACKTEST_DESIGN.md      ← 本文档
```

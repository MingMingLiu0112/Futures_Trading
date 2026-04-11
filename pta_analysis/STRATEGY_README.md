# PTA期货期权一体化策略模块

## 概述

本模块集成了**杀期权阶段识别**、**期权墙识别**、**PCR指标计算**、**缠论与期权共振信号**四大功能，为PTA期货交易提供量化分析支持。

---

## 核心功能

### 1. 杀期权阶段识别

**判断逻辑：**
1. 临近到期（通常为近月期权到期前约7天）
2. 期权墙明确（地板/天花板有明显的梯度性密集持仓）

**数据结构：**
```python
@dataclass
class KillOptionStage:
    is_active: bool       # 是否处于杀期权阶段
    near_expiry: bool     # 是否临近到期
    expiry_date: str      # 最近的到期日
    days_to_expiry: int   # 距离到期天数
    wall_clarity: float   # 期权墙清晰度 (0-1)
    confidence: float     # 判断置信度 (0-1)
```

---

### 2. 期权墙识别

**识别规则（需同时满足）：**
1. **绝对量门槛**：单档行权价持仓量 ≥ 10000手
2. **密集度判断**：`持仓量[K] / ((持仓量[K-1] + 持仓量[K+1]) / 2)) ≥ 1.5`

**数据结构：**
```python
@dataclass
class OptionWall:
    strike: int           # 行权价
    option_type: str     # 'C' (认购) or 'P' (认沽)
    oi: int              # 持仓量
    density_ratio: float # 密集度比率
    is_wall: bool         # 是否为有效期权墙
```

---

### 3. PCR指标计算

**PCR (Put/Call Ratio) 指标体系：**

| 指标 | 计算 | 阈值 |
|------|------|------|
| 持仓PCR | 认沽总持仓 / 认购总持仓 | >1偏空，<0.8偏多 |
| 成交PCR | 认沽总成交 / 认购总成交 | 短期资金情绪 |

**信号判断：**
- PCR > 1.5: 强烈偏空
- PCR > 1.0: 偏空
- PCR < 0.6: 强烈偏多
- PCR < 0.8: 偏多
- 其他: 中性

---

### 4. 缠论与期权共振信号

**交易规则速记：**

| 规则 | 条件 | 操作 |
|------|------|------|
| **规则A：右偏背景做空** | 隐波明显右偏 + 涨至期权墙阻力位 + 顶背离 | 轻仓试错 |
| **规则B：左偏背景做多** | 隐波明显左偏 + 跌至期权墙支撑位 + 底背离 | 轻仓试错 |
| **规则C：顺势增强** | PCR维持适中 + 隐波温和上升 | 可正常仓位 |

**数据结构：**
```python
@dataclass
class ResonanceSignal:
    direction: SignalDirection  # 交易方向
    confidence: float         # 置信度 (0-1)
    regime: MarketRegime      # 市场状态
    共振依据: List[str]       # 共振依据列表
    risk_level: str          # 风险等级 (高/中/低)
    action: str              # 操作建议
```

---

## 市场状态与权重分配

| 市场状态 | 描述 | 操作建议 |
|---------|------|---------|
| **宏观平静期（默认）** | 无重大宏观事件冲击 | 严格按技术信号+期权执行 |
| **杀期权阶段** | 近月期权到期前约1周 + 期权墙明确 | 技术信号 = 期权墙，共振执行 |
| **宏观驱动期** | 重大事件/数据形成系统性冲击 | 可持仓级别提升，容忍回调 |

---

## 使用方法

### 方法一：直接使用Python模块

```python
from pta_option_strategy import (
    PTAOptionStrategy,
    get_pta_option_data,
    get_pta_expiry_dates
)
from chan_core_wrapper import get_chan_result

# 初始化策略
strategy = PTAOptionStrategy(fp=7000)

# 获取数据
trade_date = '20250411'
option_df = get_pta_option_data(trade_date)
chan_result = get_chan_result(period='5min')
expiry_dates = get_pta_expiry_dates(months=2)

# 执行分析
result = strategy.get_full_analysis(option_df, chan_result, expiry_dates)

# 生成报告
report = strategy.generate_report(result)
print(report)
```

### 方法二：使用Flask API

```bash
# 完整分析
curl "http://47.100.97.88:8425/api/strategy/full_analysis?trade_date=20250411"

# 获取格式化报告
curl "http://47.100.97.88:8425/api/strategy/report?trade_date=20250411"

# 杀期权阶段识别
curl "http://47.100.97.88:8425/api/strategy/kill_option_stage?trade_date=20250411"

# 期权墙识别
curl "http://47.100.97.88:8425/api/strategy/option_walls?trade_date=20250411&fp=7000"

# PCR指标计算
curl "http://47.100.97.88:8425/api/strategy/pcr?trade_date=20250411"

# IV曲线分析
curl "http://47.100.97.88:8425/api/strategy/iv_skew?trade_date=20250411&fp=7000"

# 共振信号
curl "http://47.100.97.88:8425/api/strategy/resonance?trade_date=20250411"
```

---

## API响应示例

### 完整分析响应 (full_analysis)

```json
{
  "success": true,
  "timestamp": "2026-04-11 12:30:00",
  "regime": "杀期权阶段",
  "option_structure": {
    "pcr": 0.85,
    "pcr_label": "偏多",
    "iv_skew": "左偏",
    "gradient_ratio": 1.5,
    "floor_oi": 50000,
    "ceil_oi": 35000,
    "floor_walls": [
      {"strike": 6800, "oi": 15000, "density_ratio": 1.8, "iv": 18.5},
      {"strike": 6900, "oi": 12000, "density_ratio": 1.6, "iv": 17.2}
    ],
    "ceil_walls": [
      {"strike": 7200, "oi": 18000, "density_ratio": 2.1, "iv": 16.8},
      {"strike": 7300, "oi": 10000, "density_ratio": 1.5, "iv": 15.5}
    ],
    "score": 2,
    "label": "偏多"
  },
  "kill_option_stage": {
    "is_active": true,
    "near_expiry": true,
    "expiry_date": "20250415",
    "days_to_expiry": 4,
    "wall_clarity": 0.85,
    "confidence": 0.9
  },
  "resonance_signal": {
    "direction": "做多",
    "confidence": 0.75,
    "regime": "杀期权阶段",
    "共振依据": ["缠论做多信号", "期权偏多信号", "杀期权阶段(置信度强化)"],
    "risk_level": "高",
    "action": "轻仓试错，止损: 0.5%，方向: 做多"
  },
  "chan_signal": {
    "direction": "做多",
    "confidence": 0.8,
    "price": 7050,
    "type": "2buy"
  },
  "current_price": 7060
}
```

---

## 文件清单

| 文件 | 说明 |
|------|------|
| `pta_option_strategy.py` | 核心策略模块 |
| `strategy_api.py` | Flask HTTP API |
| `chan_core_wrapper.py` | 缠论分析封装 |

---

## 启动API服务

```bash
cd /home/admin/.openclaw/workspace/Futures_Trading/pta_analysis
python strategy_api.py
```

API服务将在 `http://0.0.0.0:8425` 启动。

---

## 注意事项

1. **数据依赖**：需要通过akshare获取PTA期权数据
2. **到期日处理**：实际到期日应从交易所日历获取，这里使用简化近似
3. **策略定位**：本工具用于数据分析辅助决策，不构成投资建议
4. **风险控制**：杀期权阶段必须严格止损

---

## 免责声明

本模块仅供学习和研究使用，不构成任何投资建议。期货交易有风险，投资需谨慎。

# v2.11.95a 时间维度路由 MVP 跟踪笔记

**启动日期**: 2026-07-17
**状态**: 代码 3 阶段完成，实战观察中
**用户决策**: "先观察一段时间，把后续任务记下，不要忘记跟进"

## 已完成（用户拍板"按你的意见办"）

### 阶段 1: 决策层历史落盘
- 改动文件: `scripts/decision_layer_service.py`
- 新增函数: `_build_history_row()` + `_append_history()`
- 落盘路径: `data/fundamental/decision_layer_history.jsonl`
- 触发: 每次 `refresh_decision_layer()` 成功后 append
- 数据格式: jsonl, 每条 ~2.3KB, 含 4 层 score/label + final 决策 + ts + F
- 重启确认: PID 461367 (Jul 17 12:26 启动), history 已从 1 行增长到 2 行

### 阶段 3: timeframe_router.py
- 文件: `scripts/timeframe_router.py` (17.7KB)
- 6 场景路由 A/B/C/D/E/F
- E 场景必须 `(long_strength=='强' AND short_strength=='强' AND 反向)` 才判观望
- 5 个 test case 全过:
  - 7/7 案例 → B 30% (短线主导)
  - 当前生产 → C 60% (中长线主导)
  - 强反向 → E 0%
  - 同向多 → A 100%
  - 临到期短线主导 → B 70%

### 阶段 2: backtest_timeframe_router.py
- 文件: `scripts/backtest_timeframe_router.py` (13.5KB)
- 功能: 读 history → 算理论决策 → K 线查 T+1h/T+4h/T+1d 价 → 命中率对比
- K 线 API: `/api/kline/data?symbol=TA&period=5min`
- **用户反跑偏纠正**: K 线不存在滞后, 末根停在 11:25 是因为午休 (11:30-13:00)。已修正
- 休盘时段处理:
  - 午休 11-13 点: skip
  - 夜盘尾巴 23-01 点: skip

## 反跑偏点（待用户拍板）

### D 场景激进仓位问题
**现象**: 单条快照 GEX 从 -0.5 变到 -2.0 + 资金从 0 变 -2.0 时, 路由从"轻仓 50%" 跳到"满仓 100%"
**风险**: 短时噪声被放大成满仓信号
**3 个选项**:
- A: 直接接受（逻辑自洽, 双组同向空 = 满仓）
- B: 仓位平滑（confidence="中"时降级到 80%, "高"才 100%）
- C: 先看 ≥50 条数据再判断（D 场景触发率 >5% 需 B 平滑, <1% 噪声可忽略）

**用户拍板**: 先观察一段时间（选项 C）

## 剩余任务清单（按优先级）

### 必须做的（观察期）
1. **等 ≥50 条快照** (约 12.5h, daemon 15min 触发一次)
   - 触发时刻: 12:45, 13:00, 13:15, ... 累积到 50 条
   - 当前: 2 条
2. **检查 history 文件增长是否正常** (每天应涨 ~30 条 = ~70KB)
3. **观察 D 场景触发率** (重点: 是否 >5%)

### 阶段 4: 自动诊断报告（等数据足够后做）
- 扩展 backtest 输出: 命中率对比 + 场景触发率分布 + 决策变更案例表格
- 触发条件: history ≥50 条后
- 工作量: ~100 行 (基于现有 backtest 框架)

### D 场景激进仓位评估（用回测数据）
- 跑 backtime 后看 D 场景触发率
- >5%: 必须 B 选项平滑
- <1%: 噪声忽略, 不处理
- 1-5%: 用户拍板

### 阶段 5: 上线门（最后做）
- 触发条件: 命中率 +5% 且用户拍板
- 实装: `timeframe_router_enabled` 配置开关 (默认 false)
- 改动: `decision_layer_service.py` 的 final.decision 计算处, 加 router fallback
- 工作量: ~30 行

## 关键文件路径

```
scripts/timeframe_router.py                    # 路由模块 (17.7KB)
scripts/backtest_timeframe_router.py           # 回测脚本 (13.5KB)
scripts/decision_layer_service.py              # + 阶段 1 的 _build_history_row / _append_history
data/fundamental/decision_layer_history.jsonl  # 历史快照 (当前 2 行)
notes/2026-07-17-timeframe-router-mvp.md       # 本笔记
```

## 关键回测口径

- 命中阈值: T+1h 0.3% / T+4h 0.5% / T+1d 0.8%
- K 线 API: `/api/kline/data?symbol=TA&period=5min`
- 决策方向映射: 满仓买入/轻仓试多/中仓跟随=long, 满仓卖出/轻仓做空/轻仓试空=short, 观望/退化=neutral

## 跟进节奏（建议）

- **7/17-7/18**: 观察 history 增长 (无需操作)
- **7/18 上午**: history 应该有 ~50 条, 跑一次完整 backtest
- **7/18-7/19**: 看 D 场景触发率 + 命中率对比, 用户拍板 B 选项
- **7/19-7/20**: 实装 B 选项 (如需要) + 阶段 4 自动诊断报告
- **7/20+**: 阶段 5 上线门评估

## 反跑偏教训（本次）

1. **不要凭印象编造外部服务假设**: 我说"K 线滞后 1 小时" 实际是午休, 被用户当场纠正
2. **3 锚点实证**: API + 落盘 + 进程, 都对才能算"完成"
3. **休盘时段处理**: K 线 API 不查休盘时段, 不能用滞后容差掩盖
4. **激进仓位问题**: D 场景 100% 仓可能是设计正确也可能是噪声, 不能凭 1-2 条快照就下结论
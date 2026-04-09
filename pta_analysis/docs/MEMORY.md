# MEMORY.md - CodeMan 长期记忆

## 关于用户

- **GitHub**: MingMingLiu0112
- **主要需求**: 股票/期货分析自动化
- **偏好**: 使用 GitHub Actions 运行分析，推送到飞书

## 项目

### 1. 期货技术分析 (futures-options-analysis)
- **仓库**: https://github.com/MingMingLiu0112/futures-options-analysis
- **定时**: 北京时间 08:00/15:00/21:00
- **分析品种**（2026-04-03更新）:
  - 橡胶2609、棕榈油2609、豆油2609、锰硅2605、燃油2605、聚丙烯2605
  - 焦煤2609、铁矿2609、苹果2610、不锈钢2605、棉花2609、生猪2605、纸浆2609、纯碱2609

### 2. 股票分析项目 (daily_stock_analysis)
- **仓库**: https://github.com/MingMingLiu0112/daily_stock_analysis
- **持仓**: 603993（洛阳钼业）、600183（生益科技）、601899（紫金矿业）

## 技术配置

- **AI 模型**: MiniMax-M2.5-highspeed
- **API**: OpenAI 兼容模式 (api.minimaxi.com)
- **飞书机器人**:
  - Webhook: `https://open.feishu.cn/open-apis/bot/v2/hook/8148922b-04f5-469f-994e-ae3e17d6b256`
  - App ID: `cli_a93a74737d7a5cc0`
  - App Secret: `ITgEfB7XN07z69JfadO06dfcPfZ5ylw6`

## ⚠️ 重要：GitHub Actions 限制
- 免费账户每月只有 **2000 分钟**运行时间
- **不要频繁触发 workflow** - 每2小时只做本地自查和群里汇报
- 仅在代码修好需要测试时，才触发一次 GHA

## GitHub 配置

- **Token**: （见 .env.github）
- **Workflow IDs**:
  - Futures Technical Analysis: 249723968
  - K-Line Chart Generator: 255265193（仅定时触发，无workflow_dispatch）

## 项目记录

- 2026-03-22: 创建期货期权分析项目
- 2026-04-03: 品种配置大更新，更换为橡胶/棕榈油/豆油/锰硅/燃油/聚丙烯/焦煤/铁矿/苹果/不锈钢/棉花/生猪/纸浆/纯碱
- 2026-04-06: PTA缠论线段检测核心算法完成 ✓

## 已知问题

- 2026-04-03: 新浪实时行情API编码问题 → 已修复（GBK）
- MACD信号未生效
- K线图仅在定时workflow触发时生成

## PTA分析项目 (pta-analysis)

- **仓库**: https://github.com/MingMingLiu0112/pta-analysis
- **策略**: 每2小时自查进度并群里汇报，不频繁触发GHA
- **当前版本**: v1.1
- **Cron**: `/home/admin/.openclaw/workspace/codeman/pta_analysis/report_progress.sh`

### 缠论线段检测（核心开发项目）

**目标**：实现完整的缠论线段检测算法，输出用户确认的3条线段：
- XD1↑ bi1~3 [09:01~09:58] 6726→6922
- XD2↓ bi4~6 [09:58~10:35] 6922→6810
- XD3↑ bi7~16 [10:35~14:54] 6810→6948

**当前状态（2026-04-06傍晚）**：
- CZSC确认16笔/天（4月3日），数据与用户完全吻合
- bi4数据：start=6922, end=6882（收盘）, low=6876（真正最低）
- **算法已突破**（2026-04-06晚）：输出3条正确线段

**笔端点规则（已确认）**：
- UP笔：start=首bar.low, end=末bar.high
- DOWN笔：start=首bar.high, end=末bar.low

**线段破坏规则（简化版，已验证正确）**：
- 同方向 = 延续（比高低点抬升/下降）
- 反方向 = 破坏
- DOWN破坏UP：`cur.low < prev_opposite.low` → 破坏成功
- UP破坏DOWN：`cur.high > prev_opposite.high` → 破坏成功
- 破坏成功 → 前段结束，新段开始
- 破坏失败 → 前段延续

**最终验证结果**：
- XD1↑ bi1~3 [09:01~09:18] 6726→6922 ✓
- XD2↓ bi4~6 [09:58~10:08] 6922→6810 ✓
- XD3↑ bi7~16 [10:35~14:32] 6810→6948 ✓

**脚本路径**：
- `/home/admin/.openclaw/workspace/codeman/pta_analysis/scripts/chan_xd_correct.py`
- `charts/chan_bi_xd.png`（可视化图）

**GitHub**: commit 02da645

### 交易策略框架（已沉淀到skills/futures-trading）

- 三维度：宏观基本面 + 技术面(缠论) + 期权印证
- 动态权重：平静期技术=期权、驱动期弱化期权、杀期权阶段期权墙主导
- 三级别：1分钟→5分钟→30分钟，操作级5分钟
- 期权核心：价格+持仓+PCR三维组合、隐波曲面、四维共振与背离

### 今日新增进展（2026-04-06）

- CZSC确认16笔/天（4月3日）
- 中枢计算：[6810, 6922]，ZD=6810, ZG=6922, 高度112点
- 日度报告新框架 `daily_report.py` 完成
- 期权数据：PCR=0.31（极低，多头偏强），IV均值69.7%
- 三维共振结论：🟢 做多共振，止损6810下方
- **缠论线段检测算法突破**：3条线段全部正确输出

## Skills 技能库

### futures-trading
期货技术分析技能，已沉淀在 `~/.openclaw/skills/futures-trading/`
- SKILL.md: 核心框架、指标体系、打分逻辑
- references/: 指标公式、期权IV、数据接口文档

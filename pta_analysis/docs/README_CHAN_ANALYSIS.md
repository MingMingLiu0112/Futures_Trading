# 缠论中枢识别与买卖点判断系统

## 概述

本系统实现了缠论算法的核心功能，包括：
1. **中枢识别算法** - 根据线段重叠部分识别中枢
2. **中枢级别判断** - 支持1分钟、5分钟、30分钟等多级别分析
3. **买卖点识别** - 一、二、三类买卖点检测
4. **背驰判断** - 趋势背驰检测
5. **交易信号生成** - 完整的交易信号生成系统

## 系统架构

### 模块组成

1. **chan_analysis_system.py** - 核心缠论分析系统
   - 笔检测
   - 线段检测
   - 基础分析功能

2. **chan_zhongshu_detector.py** - 中枢识别器
   - 线段重叠分析
   - 中枢参数计算
   - 买卖点检测

3. **chan_trading_system.py** - 交易信号生成系统
   - 多时间框架分析
   - 信号综合
   - 交易计划生成

4. **chan_integration_module.py** - 集成模块
   - 各模块整合
   - 统一接口
   - 结果汇总

## 安装与使用

### 依赖安装

```bash
pip install pandas numpy
```

### 快速开始

```python
from chan_integration_module import ChanIntegrationSystem
import pandas as pd

# 创建系统
config = {
    'main_timeframe': '30min',
    'analyze_timeframes': ['1min', '5min', '30min'],
    'min_segments_for_zhongshu': 3
}
system = ChanIntegrationSystem(config)

# 准备K线数据
klines_dict = {
    '1min': pd.DataFrame(...),  # 1分钟K线
    '5min': pd.DataFrame(...),  # 5分钟K线
    '30min': pd.DataFrame(...)  # 30分钟K线
}

# 执行分析
results = system.multi_timeframe_analysis(klines_dict)

# 查看交易计划
trading_plan = results['trading_plan']
print(f"交易建议: {trading_plan['recommendation']}")

# 保存结果
system.save_results('analysis_results.json')
```

## 数据结构

### K线数据格式

```python
klines = pd.DataFrame({
    'datetime': pd.DatetimeIndex,  # 时间戳
    'open': float,                 # 开盘价
    'high': float,                 # 最高价
    'low': float,                  # 最低价
    'close': float,                # 收盘价
    'volume': float                # 成交量
})
```

### 分析结果结构

```json
{
  "multi_timeframe_results": {
    "1min": {
      "bis_count": 25,
      "segments_count": 8,
      "zhongshus_count": 2,
      "signals_count": 3
    },
    "5min": {
      "bis_count": 15,
      "segments_count": 5,
      "zhongshus_count": 1,
      "signals_count": 2
    }
  },
  "combined_signals": [
    {
      "type": "first_buy",
      "price": 5123.45,
      "confidence": 0.78,
      "confirming_timeframes": ["5min", "30min"],
      "description": "第一类买点：下降趋势背驰"
    }
  ],
  "trading_plan": {
    "status": "ready",
    "plan": [
      {
        "action": "BUY",
        "entry_price": 5123.45,
        "stop_loss": 5021.78,
        "take_profit": 5277.15,
        "confidence": 0.78
      }
    ]
  }
}
```

## 核心算法

### 1. 笔检测算法

基于顶底分型识别：
- 顶分型：中间K线高点最高，低点也最高
- 底分型：中间K线低点最低，高点也最低
- 笔条件：至少5根K线，分型类型不同

### 2. 线段检测算法

基于笔的方向序列：
- 线段由至少3笔组成
- 连续同方向笔构成线段
- 方向变化标志线段结束

### 3. 中枢识别算法

基于线段重叠：
- 取连续3段或以上线段
- 计算重叠区间：`[max(线段低点), min(线段高点)]`
- 重叠条件：`max_low < min_high`

### 4. 买卖点判断

**第一类买卖点**：
- 趋势背驰点
- 上升趋势背驰 → 第一类卖点
- 下降趋势背驰 → 第一类买点

**第二类买卖点**：
- 第一类买卖点后的回抽确认
- 回抽不创新低/新高

**第三类买卖点**：
- 离开中枢后回抽不回到中枢内
- 中枢破坏确认

### 5. 背驰判断

力度比较算法：
```python
# 计算线段力度
strength = abs(线段价格变化) / 线段时间长度

# 背驰条件
if 后段力度 < 前段力度 * 0.7:
    return True  # 背驰
```

## 多时间框架分析

系统支持多时间框架协同分析：

1. **小级别验证**：1分钟、5分钟框架验证信号
2. **主级别决策**：30分钟框架主要决策
3. **大级别确认**：1小时、4小时框架趋势确认

### 信号综合规则

- 多个时间框架确认 → 置信度提升
- 主时间框架信号 → 权重更高
- 背驰信号 → 优先级提升

## 交易信号生成

### 信号类型

1. **BUY信号**：第一类、第二类、第三类买点
2. **SELL信号**：第一类、第二类、第三类卖点

### 风险管理

自动计算：
- 止损位：入场价 ±2%
- 止盈位：入场价 ±3%
- 风险收益比：≥1.5

### 置信度分级

- 高置信度 (≥0.8)：多时间框架确认 + 背驰
- 中置信度 (0.6-0.8)：主时间框架信号
- 低置信度 (<0.6)：单时间框架信号

## 集成到现有平台

### 1. 作为独立模块

```python
# 导入系统
from chan_integration_module import ChanIntegrationSystem

# 初始化
system = ChanIntegrationSystem()

# 分析数据
results = system.process_klines(klines, '30min')

# 获取信号
signals = results['signals']
```

### 2. 与现有缠论算法整合

```python
# 使用现有笔和线段检测
from existing_chan_module import detect_bis, detect_segments

# 获取笔和线段
bis = detect_bis(klines)
segments = detect_segments(bis)

# 使用本系统进行中枢识别和买卖点判断
from chan_zhongshu_detector import ZhongShuDetector

detector = ZhongShuDetector('30min')
zhongshus = detector.detect_zhongshu_from_segments(segments)
points = detector.detect_buy_sell_points()
```

### 3. 实时分析集成

```python
class RealTimeChanAnalyzer:
    def __init__(self):
        self.system = ChanIntegrationSystem()
        self.buffer = []
    
    def on_new_bar(self, bar):
        """处理新K线"""
        self.buffer.append(bar)
        
        if len(self.buffer) >= 100:  # 积累足够数据
            klines = pd.DataFrame(self.buffer)
            results = self.system.process_klines(klines, '1min')
            
            # 生成实时信号
            signals = results.get('signals', [])
            for signal in signals:
                self.emit_signal(signal)
```

## 性能优化

### 数据处理

1. **批量处理**：积累足够K线后批量分析
2. **增量更新**：只分析新数据，复用已有结果
3. **缓存机制**：缓存笔、线段识别结果

### 算法优化

1. **向量化计算**：使用NumPy进行批量计算
2. **提前终止**：满足条件后提前结束扫描
3. **近似算法**：对历史数据使用近似算法

## 测试与验证

### 单元测试

```bash
# 测试核心算法
python -m pytest test_chan_analysis.py

# 测试集成系统
python -m pytest test_integration.py
```

### 回测验证

```python
# 使用历史数据回测
backtest_results = backtest_chan_signals(
    historical_data,
    chan_system,
    initial_capital=100000
)

print(f"总收益: {backtest_results['total_return']:.2%}")
print(f"胜率: {backtest_results['win_rate']:.2%}")
```

## 配置选项

### 系统配置

```python
config = {
    # 时间框架
    'main_timeframe': '30min',
    'analyze_timeframes': ['1min', '5min', '30min', '1h'],
    
    # 算法参数
    'min_segments_for_zhongshu': 3,
    'divergence_threshold': 0.7,
    'confidence_threshold': 0.6,
    
    # 交易参数
    'stop_loss_percent': 0.02,
    'take_profit_percent': 0.03,
    'min_risk_reward_ratio': 1.5
}
```

### 自定义扩展

```python
# 自定义笔检测算法
class CustomBiDetector:
    def detect(self, klines):
        # 实现自定义算法
        pass

# 集成到系统
system.analysis_system.bi_detector = CustomBiDetector()
```

## 故障排除

### 常见问题

1. **无信号生成**
   - 检查K线数据质量
   - 调整算法参数
   - 增加分析时间框架

2. **信号置信度过低**
   - 等待更多时间框架确认
   - 检查背驰条件
   - 验证中枢识别结果

3. **性能问题**
   - 减少分析时间框架数量
   - 增加批量处理大小
   - 启用缓存机制

### 调试模式

```python
# 启用调试输出
system = ChanIntegrationSystem(config)
system.config['debug'] = True

# 查看详细日志
results = system.process_klines(klines, '30min')
print(json.dumps(results, indent=2))
```

## 贡献与扩展

### 添加新功能

1. **新买卖点类型**：扩展`BuySellPointType`枚举
2. **新背驰算法**：实现`_check_divergence`方法
3. **新时间框架**：添加`TimeFrame`枚举值

### 性能改进

1. **算法优化**：改进笔和线段检测算法
2. **并行计算**：多时间框架并行分析
3. **GPU加速**：使用CUDA加速计算

## 许可证

本项目采用MIT许可证。详见LICENSE文件。

## 联系方式

如有问题或建议，请通过以下方式联系：
- GitHub Issues: [项目地址]
- Email: [联系邮箱]

---

**注意**：本系统为缠论分析工具，不构成投资建议。实际交易请谨慎决策，控制风险。
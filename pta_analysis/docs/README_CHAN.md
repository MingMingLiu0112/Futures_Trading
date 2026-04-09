# 缠论算法实现

基于缠论108课标准定义的完整笔划分和线段检测算法。

## 功能特性

1. **包含关系处理** - 正确处理K线包含关系（高高原则、低低原则）
2. **分型识别** - 准确识别顶分型和底分型
3. **笔划分算法** - 支持标准笔和小笔划分
4. **线段检测** - 实现线段破坏规则和线段延伸
5. **可视化输出** - 生成专业的分析图表
6. **完整测试** - 包含多种市场走势的测试用例

## 文件结构

```
.
├── chan_final_implementation.py  # 最终实现（核心算法）
├── chan_complete_test.py         # 完整测试套件
├── chan_xd_correct.py            # 基础实现
├── chan_xd_enhanced.py           # 增强版实现
├── README_CHAN.md                # 本文档
└── 生成的图表文件:
    ├── chan_final_up_trend.png     # 上升趋势分析
    ├── chan_final_down_trend.png   # 下降趋势分析
    ├── chan_final_sideways.png     # 横盘震荡分析
    ├── chan_final_complex.png      # 复杂走势分析
    ├── chan_test_up_trend.png      # 测试：上升趋势
    ├── chan_test_down_trend.png    # 测试：下降趋势
    ├── chan_test_sideways.png      # 测试：横盘震荡
    └── chan_test_complex.png       # 测试：复杂走势
```

## 核心算法类

### ChanTheoryAnalyzer

缠论分析器，提供完整的分析功能：

```python
from chan_final_implementation import ChanTheoryAnalyzer

# 创建分析器
analyzer = ChanTheoryAnalyzer(
    min_k_bars=4,        # 笔的最小K线数量
    min_price_range=30.0 # 小笔的最小价格幅度
)

# 执行分析（klines为包含OHLC数据的DataFrame）
results = analyzer.analyze(klines)

# 获取统计信息
stats = analyzer.get_statistics()
print(f"笔数量: {stats['stroke_count']}")
print(f"线段数量: {stats['segment_count']}")

# 获取趋势分析
trend = analyzer.get_trend_analysis()
print(f"当前趋势: {trend['trend_status']}")
```

### ChanVisualizer

可视化器，生成分析图表：

```python
from chan_final_implementation import ChanVisualizer

# 可视化分析结果
ChanVisualizer.visualize(
    analyzer, 
    output_path='my_analysis.png',
    title='我的缠论分析'
)
```

## 使用示例

### 示例1：基本使用

```python
import pandas as pd
from chan_final_implementation import ChanTheoryAnalyzer, ChanVisualizer

# 1. 准备数据（需要包含open, high, low, close列）
klines = pd.DataFrame({
    'open': [...],
    'high': [...],
    'low': [...],
    'close': [...]
})

# 2. 创建分析器并执行分析
analyzer = ChanTheoryAnalyzer()
results = analyzer.analyze(klines)

# 3. 查看结果
print(f"找到 {len(analyzer.strokes)} 笔")
print(f"找到 {len(analyzer.segments)} 个线段")

# 4. 可视化
ChanVisualizer.visualize(analyzer, 'analysis_result.png')
```

### 示例2：使用测试数据

```python
from chan_final_implementation import DataGenerator

# 生成测试数据
data = DataGenerator.generate_trend_data('up_trend', n_bars=200)

# 分析
analyzer = ChanTheoryAnalyzer()
analyzer.analyze(data)

# 可视化
ChanVisualizer.visualize(analyzer, 'test_up_trend.png', '上升趋势分析')
```

## 算法原理

### 1. 包含关系处理

- **上升趋势包含**：取高高原则（max(high), max(low)）
- **下降趋势包含**：取低低原则（min(high), min(low)）
- **趋势判断**：当前K线low > 前一根low为上升，否则为下降

### 2. 分型识别

- **顶分型**：中间K线的high和low都高于左右两根K线
- **底分型**：中间K线的high和low都低于左右两根K线
- **过滤**：排除相邻分型，确保分型之间至少有一根独立K线

### 3. 笔划分

- **标准笔**：相邻顶底分型，间隔至少4根K线
- **小笔**：间隔不足4根但价格幅度超过阈值
- **笔方向**：底分型→顶分型=上升笔，顶分型→底分型=下降笔

### 4. 线段检测

- **线段构成**：至少由3笔构成
- **上行线段**：底-顶-底（低点抬高，高点抬高）
- **下行线段**：顶-底-顶（高点降低，低点降低）
- **线段延伸**：同方向笔不断创新高/新低
- **线段破坏**：反方向笔突破前一线段极值

## 测试结果

已通过以下测试场景：

1. **上升趋势测试** ✓
   - 笔数量：16笔（8上行，8下行）
   - 线段数量：2段（2上行）
   - 平均线段幅度：74.7点

2. **下降趋势测试** ✓
   - 笔数量：12笔（6上行，6下行）
   - 线段数量：2段（2下行）
   - 平均线段幅度：68.8点

3. **横盘震荡测试** ✓
   - 笔数量：10笔（5上行，5下行）
   - 线段数量：1段（1上行）
   - 平均线段幅度：18.8点

4. **复杂走势测试** ✓
   - 笔数量：12笔（6上行，6下行）
   - 线段数量：1段（1上行）
   - 平均线段幅度：73.0点

## 输出示例

分析结果包含：

1. **分型列表**：每个分型的类型、位置和价格
2. **笔列表**：每笔的方向、起止位置、价格和是否为小笔
3. **线段列表**：每个线段的方向、起止位置、价格和包含的笔索引
4. **统计信息**：各类数量统计和平均值
5. **趋势分析**：当前趋势状态和强度

## 可视化说明

生成的图表包含：

1. **主图**：K线 + 分型标记 + 笔连线 + 线段连线
2. **副图**：收盘价走势 + 线段转折点标记
3. **图例**：清晰的颜色编码说明
4. **网格**：便于价格和位置参考

## 参数调整

可根据不同市场调整参数：

```python
# 期货市场（波动较大）
analyzer_futures = ChanTheoryAnalyzer(
    min_k_bars=4,        # 标准笔要求4根K线
    min_price_range=50.0 # 小笔要求50点幅度
)

# 股票市场（波动较小）
analyzer_stock = ChanTheoryAnalyzer(
    min_k_bars=5,        # 标准笔要求5根K线
    min_price_range=0.05 # 小笔要求5%幅度（相对价格）
)
```

## 注意事项

1. **数据质量**：确保输入数据包含完整的OHLC信息
2. **时间周期**：算法适用于任何时间周期的K线数据
3. **参数优化**：根据具体市场特性调整参数
4. **线段复杂性**：复杂走势可能需要人工复核线段划分

## 扩展建议

1. **实时分析**：结合实时数据流进行连续分析
2. **多周期分析**：同时分析多个时间周期的缠论结构
3. **交易信号**：基于线段破坏生成交易信号
4. **回测系统**：集成到量化回测框架中

## 许可证

本项目代码可自由使用、修改和分发。
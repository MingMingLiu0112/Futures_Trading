# 隐含波动率曲线（IV Curve）可视化组件

一个功能完整的隐含波动率曲线分析工具，支持双曲线对比、曲线移动分析和动画可视化。

## 📋 功能特性

### 1. 双曲线对比
- **前日收盘 vs 实时曲线**：对比不同时间点的IV曲线
- **多品种支持**：PTA、铜、黄金、白银、橡胶、原油等
- **多到期月份**：当月、次月、季度、半年合约

### 2. 曲线移动分析
- **垂直移动**：整体IV水平变化分析
- **水平移动**：微笑曲线中心移动分析
- **扭曲分析**：曲线两端变化不一致分析
- **微笑变化**：IV偏度变化分析

### 3. 可视化功能
- **交互式图表**：使用Chart.js实现
- **动画效果**：曲线过渡动画
- **实时更新**：支持实时数据刷新
- **导出功能**：图表导出为PNG格式

### 4. 市场情绪分析
- 基于曲线移动自动判断市场情绪
- 提供交易建议和风险提示
- 可视化信号指示器

## 🚀 快速开始

### 1. 安装依赖

```bash
cd iv_curve_component
pip install -r requirements.txt
```

### 2. 启动后端API

```bash
python api.py
```

后端将在 `http://localhost:5000` 启动。

### 3. 打开前端页面

在浏览器中打开 `index.html`，或通过后端服务访问 `http://localhost:5000`

## 📁 项目结构

```
iv_curve_component/
├── index.html              # 前端主页面
├── iv-curve.js            # 前端JavaScript逻辑
├── api.py                 # 后端Flask API服务
├── requirements.txt       # Python依赖
├── README.md             # 说明文档
└── assets/               # 静态资源（可选）
```

## 🔧 配置选项

### 前端控制面板
- **品种选择**：支持6个期货品种
- **到期月份**：4种不同到期时间
- **时间范围**：1-30天历史数据
- **行权价范围**：80%-120%
- **显示选项**：控制曲线显示/隐藏

### 动画控制
- **播放/暂停**：控制动画播放
- **速度调节**：1-10倍速
- **重置**：回到初始状态

## 📊 数据分析指标

### 1. IV Rank & Percentile
- 当前IV在历史区间的位置
- 超过历史数据的百分比

### 2. IV Skew
- 看跌/看涨期权IV差值
- 市场情绪判断（偏多/偏空/中性）

### 3. 曲线移动指标
- **垂直移动值**：整体IV水平变化
- **水平移动值**：微笑中心偏移
- **扭曲度**：曲线两端变化差异
- **ATM IV变化**：平值期权IV变化

### 4. 市场情绪
- 基于多个指标的综合判断
- 提供交易方向建议

## 🔌 API接口

### 获取当前IV曲线
```
GET /api/iv/current?symbol=TA&expiry=current
```

### 获取前日IV曲线
```
GET /api/iv/previous?symbol=TA&expiry=current
```

### 获取历史数据
```
GET /api/iv/history?symbol=TA&expiry=current&days=7
```

### 分析曲线移动
```
GET /api/iv/analyze?symbol=TA&expiry=current
```

### 获取动画帧数据
```
GET /api/iv/animation?symbol=TA&expiry=current&frames=10
```

## 🎨 技术栈

### 前端
- **Chart.js**：数据可视化
- **Vanilla JavaScript**：核心逻辑
- **CSS3**：现代响应式设计
- **HTML5**：语义化标记

### 后端
- **Flask**：轻量级Web框架
- **Flask-CORS**：跨域支持
- **NumPy**：数值计算
- **Pandas**：数据处理

## 📱 响应式设计

- **桌面端**：完整功能，双栏布局
- **平板端**：自适应布局
- **移动端**：单栏布局，触摸优化

## 🔄 集成方式

### 1. 独立部署
```bash
# 启动服务
python api.py

# 访问页面
open http://localhost:5000
```

### 2. 嵌入现有项目
```html
<!-- 嵌入iframe -->
<iframe src="http://your-server/iv-curve" width="100%" height="600px"></iframe>

<!-- 或直接引入组件 -->
<script src="iv-curve.js"></script>
<div id="iv-curve-container"></div>
```

### 3. API集成
```javascript
// 获取IV数据
fetch('http://your-server/api/iv/current?symbol=TA')
  .then(response => response.json())
  .then(data => {
    // 处理数据
    console.log(data);
  });
```

## 🧪 测试数据

组件包含完整的模拟数据生成器，支持：
- 不同品种的IV特性模拟
- 时间序列数据生成
- 市场情绪模拟
- 随机波动注入

## 📈 使用场景

### 1. 期权交易分析
- 识别IV异常点
- 判断市场情绪
- 寻找交易机会

### 2. 风险管理
- 监控IV变化
- 预警异常波动
- 评估持仓风险

### 3. 策略研究
- 回测IV策略
- 分析曲线形态
- 研究市场规律

### 4. 教育培训
- 可视化IV概念
- 演示曲线移动
- 教学工具

## 🔒 安全注意事项

1. **生产环境**：建议添加身份验证
2. **API限流**：防止滥用
3. **数据验证**：验证输入参数
4. **错误处理**：友好的错误提示

## 🐛 故障排除

### 常见问题

1. **图表不显示**
   - 检查Chart.js是否加载
   - 查看浏览器控制台错误
   - 验证数据格式

2. **API连接失败**
   - 检查后端服务是否运行
   - 验证端口是否被占用
   - 检查防火墙设置

3. **动画卡顿**
   - 减少动画帧数
   - 优化数据量
   - 检查浏览器性能

### 调试模式

```javascript
// 启用调试日志
localStorage.setItem('ivCurveDebug', 'true');
```

## 📄 许可证

MIT License

## 🤝 贡献指南

1. Fork项目
2. 创建功能分支
3. 提交更改
4. 推送到分支
5. 创建Pull Request

## 📞 支持

如有问题或建议，请提交Issue或联系维护者。

---

**祝您交易顺利！** 🚀
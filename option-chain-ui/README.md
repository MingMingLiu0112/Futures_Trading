# PTA期权链T型显示组件

基于React + TypeScript开发的期权链T型显示组件，专为PTA期货分析平台设计。

## 功能特点

### 📊 核心显示字段（简化版）
1. **价格** - 当前期权价格及涨跌幅
2. **持仓量变化%** - 反映资金流向和市场情绪
3. **成交量变化%** - 反映短期交易活跃度
4. **隐波绝对值变化** - 反映市场波动预期变化
5. **希腊字母当前值** - Delta, Gamma, Theta, Vega, Rho

### 🎯 T型布局
- 左侧：看涨期权 (Calls)
- 右侧：看跌期权 (Puts)
- 中间：平值期权高亮显示

### ⚙️ 可配置功能
- 字段显示/隐藏控制
- 多种排序方式（行权价、成交量、持仓量、隐波）
- 最大显示数量控制
- 自动刷新开关
- 颜色主题选择

## 项目结构

```
option-chain-ui/
├── src/
│   ├── components/
│   │   ├── OptionChain.tsx    # 主T型显示组件
│   │   ├── OptionRow.tsx      # 单个期权行组件
│   │   └── MarketStats.tsx    # 市场统计组件
│   ├── types/
│   │   └── index.ts          # TypeScript类型定义
│   ├── App.tsx               # 主应用组件
│   ├── main.tsx              # 应用入口
│   └── index.css             # 样式文件
├── public/
├── index.html                # HTML模板
├── package.json
├── tsconfig.json
└── vite.config.ts
```

## 快速开始

### 1. 安装依赖
```bash
cd option-chain-ui
npm install
```

### 2. 开发模式运行
```bash
npm start
```
访问 http://localhost:3000

### 3. 生产构建
```bash
npm run build
```

## 与PTA分析平台集成

### 方法一：作为独立页面集成
1. 将构建后的文件复制到PTA平台静态目录
2. 在平台导航中添加链接
3. 配置后端API数据源

### 方法二：作为组件嵌入现有页面
1. 复制组件文件到现有项目
2. 安装所需依赖（React, TypeScript, Recharts）
3. 导入并使用组件：

```typescript
import OptionChain from './components/OptionChain';
import { OptionData } from './types';

// 从API获取数据
const fetchOptionData = async (): Promise<OptionData[]> => {
  const response = await fetch('/api/options/chain');
  return response.json();
};

// 在页面中使用
<OptionChain 
  data={optionData}
  config={{
    maxDisplay: 10,
    highlightATM: true,
    showFields: {
      price: true,
      oiChangePercent: true,
      volumeChangePercent: true,
      ivChangeAbs: true,
      greeks: true
    }
  }}
  onOptionClick={(option) => {
    console.log('Selected option:', option);
    // 显示详情或执行其他操作
  }}
/>
```

### 方法三：通过iframe嵌入
```html
<iframe 
  src="/option-chain/index.html" 
  width="100%" 
  height="800px"
  frameborder="0"
  scrolling="no"
></iframe>
```

## 数据接口

组件期望的数据格式：

```typescript
interface OptionData {
  contractCode: string;      // 合约代码，如 TA605C4050
  strikePrice: number;       // 行权价
  optionType: 'C' | 'P';     // 期权类型：C=看涨，P=看跌
  price: number;            // 当前价格
  priceChangePercent: number; // 价格变化百分比
  oiChangePercent: number;  // 持仓量变化百分比
  volumeChangePercent: number; // 成交量变化百分比
  ivChangeAbs: number;      // 隐含波动率绝对值变化
  greeks: {
    delta: number;          // Delta值
    gamma: number;          // Gamma值
    theta: number;          // Theta值
    vega: number;           // Vega值
    rho: number;            // Rho值
  };
  underlyingPrice: number;  // 标的物价格
  isATM: boolean;           // 是否为平值期权
}
```

## 与现有PTA平台数据对接

### 1. 数据转换
现有PTA平台的期权数据格式需要转换为组件所需格式：

```python
# Python数据转换示例
def convert_to_component_format(option_row):
    """将PTA平台数据转换为组件格式"""
    return {
        'contractCode': option_row['合约代码'],
        'strikePrice': option_row['行权价'],
        'optionType': 'C' if 'C' in option_row['合约代码'] else 'P',
        'price': option_row['最新价'],
        'priceChangePercent': option_row['涨跌幅'],
        'oiChangePercent': option_row['持仓量变化率'],
        'volumeChangePercent': option_row['成交量变化率'],
        'ivChangeAbs': abs(option_row['隐波变化']),
        'greeks': {
            'delta': option_row['delta'],
            'gamma': option_row['gamma'],
            'theta': option_row['theta'],
            'vega': option_row['vega'],
            'rho': option_row['rho']
        },
        'underlyingPrice': option_row['标的物价格'],
        'isATM': option_row['行权价'] == option_row['平值行权价']
    }
```

### 2. API端点
建议创建专用API端点：

```python
# Flask示例
@app.route('/api/options/chain')
def get_option_chain():
    """获取期权链数据"""
    # 从数据库或实时数据源获取
    raw_data = fetch_option_data()
    
    # 转换为组件格式
    formatted_data = [convert_to_component_format(row) for row in raw_data]
    
    # 计算市场统计
    stats = calculate_market_stats(raw_data)
    
    return jsonify({
        'options': formatted_data,
        'stats': stats,
        'updateTime': datetime.now().isoformat()
    })
```

## 样式定制

### 颜色主题
组件支持三种颜色主题：
- `green-red`：绿色看涨/红色看跌（默认）
- `blue-orange`：蓝色看涨/橙色看跌
- `monochrome`：单色主题

### 自定义样式
可以通过CSS变量覆盖默认样式：

```css
:root {
  --primary-color: #2c3e50;
  --secondary-color: #3498db;
  --call-color: #27ae60;    /* 看涨期权颜色 */
  --put-color: #e74c3c;     /* 看跌期权颜色 */
  --neutral-color: #f39c12;
}
```

## 性能优化

### 1. 虚拟滚动
对于大量期权数据，建议实现虚拟滚动：

```typescript
import { FixedSizeList as List } from 'react-window';

// 在OptionChain组件中使用虚拟列表
<List
  height={600}
  itemCount={options.length}
  itemSize={120}
  width="100%"
>
  {({ index, style }) => (
    <div style={style}>
      <OptionRow option={options[index]} />
    </div>
  )}
</List>
```

### 2. 数据缓存
实现数据缓存减少API调用：

```typescript
const useOptionData = () => {
  const [data, setData] = useState<OptionData[]>([]);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  
  const fetchData = useCallback(async () => {
    // 检查缓存
    if (lastUpdate && Date.now() - lastUpdate.getTime() < 30000) {
      return; // 30秒内不重复获取
    }
    
    const response = await fetch('/api/options/chain');
    const newData = await response.json();
    
    setData(newData);
    setLastUpdate(new Date());
  }, [lastUpdate]);
  
  return { data, fetchData };
};
```

## 部署到生产环境

### 1. 构建优化
```bash
# 生产构建
npm run build

# 分析包大小
npm run build -- --analyze
```

### 2. Nginx配置
```nginx
server {
    listen 80;
    server_name options.yourdomain.com;
    
    root /var/www/option-chain-ui/dist;
    index index.html;
    
    # 启用gzip压缩
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml;
    
    # 缓存静态资源
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
    
    # API代理
    location /api/ {
        proxy_pass http://localhost:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    
    # SPA路由支持
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

## 故障排除

### 常见问题

1. **数据不显示**
   - 检查API端点是否可访问
   - 验证数据格式是否符合要求
   - 查看浏览器控制台错误信息

2. **样式错乱**
   - 检查CSS冲突
   - 确保Bootstrap和Font Awesome正确加载
   - 验证自定义CSS变量

3. **性能问题**
   - 启用虚拟滚动处理大量数据
   - 实现数据缓存
   - 优化API响应时间

### 调试工具
- 使用React Developer Tools检查组件状态
- 使用浏览器Network面板监控API请求
- 使用Performance面板分析渲染性能

## 后续开发计划

1. **实时数据推送** - WebSocket支持
2. **高级筛选** - 按希腊字母范围筛选
3. **图表集成** - 期权价格曲线、隐波曲面
4. **策略分析** - 期权策略构建器
5. **移动端优化** - 响应式设计增强

## 许可证

MIT License
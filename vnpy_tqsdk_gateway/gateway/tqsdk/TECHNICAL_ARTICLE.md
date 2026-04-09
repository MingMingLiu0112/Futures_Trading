# VeighNa天勤网关开发技术详解

## 摘要

本文详细介绍VeighNa天勤网关（TqSdk Gateway）的开发技术要点，包括技术架构、核心功能、开发难点、性能优化和使用指南。天勤网关为VeighNa交易平台提供了天勤量化平台的实时行情和交易功能，相比CTP网关，天勤网关具有注册简单、获取数据容易等优势，特别适合个人投资者和小型机构使用。

---

## 一、项目背景

### 1.1 开发动机

随着量化交易的普及，越来越多的个人投资者和小型机构希望使用VeighNa进行交易。然而，传统的CTP网关需要向期货公司申请模拟账户，流程复杂且审批周期长。天勤量化平台提供了免费的模拟账户，注册简单，获取数据方便，成为了一个理想的选择。

### 1.2 技术优势

天勤网关相比CTP网关具有以下技术优势：

- **注册简单**：天勤提供免费模拟账户，注册流程简单，无需复杂审批
- **数据获取容易**：天勤提供丰富的历史数据和实时行情，获取方式简单
- **API设计友好**：天勤API设计简洁，文档完善，易于上手
- **期权支持完善**：天勤支持期权链查询，方便获取期权合约信息
- **跨平台支持**：天勤SDK支持Windows、Linux、Mac等平台
- **社区活跃**：天勤有活跃的社区支持，问题解决及时

### 1.3 应用场景

天勤网关适用于以下应用场景：

- **个人投资者**：需要简单的量化交易工具，不想处理CTP网关的复杂流程
- **小型机构**：需要快速搭建交易系统，不想投入大量时间在CTP网关申请上
- **量化研究**：需要获取历史数据进行回测，天勤提供了丰富的历史数据
- **期权交易**：需要期权链查询功能，天勤支持期权链查询
- **教学演示**：需要演示量化交易系统，天勤提供了免费模拟环境

---

## 二、技术架构

### 2.1 整体架构

天勤网关采用分层架构设计，主要包括以下模块：

```
vnpy_tianqin/
├── tqsdk_gateway.py      # 天勤网关主文件
├── option_parser.py       # 期权解析器
├── datafeed.py          # 数据服务文件
├── __init__.py          # 包初始化文件
├── setup.py             # 安装文件
├── VERSION               # 版本号文件
├── README.md            # 说明文档
└── LICENSE               # 许可证文件
```

### 2.2 核心模块

#### 2.2.1 天勤网关主文件（tqsdk_gateway.py）

天勤网关主文件实现了以下核心功能：

- **连接管理**：处理天勤API的连接、断开、重连
- **行情处理**：处理实时行情数据的订阅、推送、解析
- **交易处理**：处理委托下单、撤单、成交、持仓等交易功能
- **账户管理**：处理账户资金、保证金、可用资金等账户信息
- **合约管理**：处理合约信息的自动加载、查询、生成
- **期权支持**：处理期权合约的识别、解析、推送

#### 2.2.2 期权解析器（option_parser.py）

期权解析器实现了以下功能：

- **期权链查询**：查询期权链信息，包括看涨、看跌期权
- **期权合约识别**：识别期权合约的到期日、行权价、合约乘数
- **期权产品映射**：将期权合约映射到对应的期货合约
- **期权信息推送**：推送期权合约信息到VeighNa系统

#### 2.2.3 数据服务文件（datafeed.py）

数据服务文件实现了以下功能：

- **历史K线查询**：支持多种时间间隔的K线数据查询
- **历史Tick查询**：支持历史Tick数据查询
- **时间间隔转换**：支持1分钟、5分钟、15分钟、30分钟、1小时、2小时、4小时、1天、1周、1月
- **时区处理**：正确处理中国时区，避免时间偏移
- **错误处理**：完善的异常处理，确保数据查询的稳定性

### 2.3 数据流程

天勤网关的数据流程如下：

```
天勤API → 天勤网关 → VeighNa事件引擎 → VeighNa主引擎 → VeighNa UI
```

#### 2.3.1 行情数据流程

```
天勤API行情数据 → 天勤网关行情处理 → TickData对象 → VeighNa事件引擎 → VeighNa UI行情显示
```

#### 2.3.2 交易数据流程

```
天勤API交易数据 → 天勤网关交易处理 → OrderData/TradeData对象 → VeighNa事件引擎 → VeighNa UI交易显示
```

#### 2.3.3 账户数据流程

```
天勤API账户数据 → 天勤网关账户处理 → AccountData对象 → VeighNa事件引擎 → VeighNa UI账户显示
```

#### 2.3.4 持仓数据流程

```
天勤API持仓数据 → 天勤网关持仓处理 → PositionData对象 → VeighNa事件引擎 → VeighNa UI持仓显示
```

---

## 三、核心功能

### 3.1 实时行情

#### 3.1.1 行情订阅

天勤网关支持订阅多个合约的实时行情数据，包括：

- **Tick数据**：最新价、买一价、卖一价、买一量、卖一量等
- **五档行情**：买一价到买五价、卖一价到卖五价及其对应的成交量
- **K线数据**：支持1分钟、5分钟、15分钟、30分钟、1小时、2小时、4小时、1天等K线数据

#### 3.1.2 行情推送

天勤网关通过VeighNa事件引擎推送行情数据到UI：

```python
# 推送行情数据
self.on_tick(tick)
```

#### 3.1.3 行情缓存

天勤网关实现了行情缓存机制，避免重复推送：

```python
# 行情缓存
self.quote_cache: dict[str, object] = {}

# 处理行情数据
for vt_symbol, quote in self.quote_cache.items():
    if self.api.is_changing(quote):
        # 推送行情数据
        self.on_tick(tick)
```

### 3.2 交易功能

#### 3.2.1 委托下单

天勤网关支持委托下单功能，包括：

- **限价委托**：支持指定价格的限价委托
- **市价委托**：支持市价委托（天勤API支持）
- **开平方向**：支持开仓、平仓
- **多空方向**：支持多头、空头
- **期权委托**：支持期权合约的委托下单

#### 3.2.2 委托撤单

天勤网关支持委托撤单功能：

```python
# 委托撤单
def cancel_order(self, req: CancelRequest) -> None:
    """
    委托撤单
    """
    try:
        # 获取订单对象
        order = self.orders.get(req.orderid)
        if not order:
            self.write_log(f"委托单不存在: {req.orderid}")
            return
        
        # 撤销委托单
        self.api.cancel_order(order)
        self.write_log(f"委托撤单成功: {req.orderid}")
    except Exception as e:
        self.write_log(f"委托撤单失败: {str(e)}")
```

#### 3.2.3 成交推送

天勤网关支持成交数据推送，包括：

- **成交价格**：成交价格
- **成交数量**：成交数量
- **成交时间**：成交时间
- **成交方向**：成交方向（多头、空头）
- **成交偏移**：成交偏移（开仓、平仓）

#### 3.2.4 资金查询

天勤网关支持账户资金查询，包括：

- **账户余额**：账户余额
- **可用资金**：可用资金
- **保证金**：保证金
- **冻结资金**：冻结资金
- **持仓盈亏**：持仓盈亏（新增字段）

#### 3.2.5 持仓查询

天勤网关支持持仓查询，包括：

- **持仓数量**：持仓数量
- **持仓方向**：持仓方向（多头、空头）
- **持仓价格**：持仓价格
- **持仓盈亏**：持仓盈亏（新增字段）
- **昨日持仓量**：昨日持仓量（新增字段）

### 3.3 期权支持

#### 3.3.1 期权链查询

天勤网关支持期权链查询功能，包括：

- **看涨期权**：查询看涨期权链
- **看跌期权**：查询看跌期权链
- **期权到期日**：期权到期日
- **期权行权价**：期权行权价
- **期权合约乘数**：期权合约乘数

#### 3.3.2 期权合约识别

天勤网关支持期权合约的自动识别，包括：

- **大商所期权**：DCE.v2603-C-4400（看涨）、DCE.v2603-P-4400（看跌）
- **上期所期权**：SHFE.au2004C308（看涨）、SHFE.au2004P308（看跌）
- **中金所期权**：CFFEX.IO2002-C-3550（看涨）、CFFEX.IO2002-P-3550（看跌）

#### 3.3.3 期权信息推送

天勤网关支持期权信息推送，包括：

- **期权合约信息**：期权合约的基本信息
- **期权链信息**：期权链的完整信息
- **期权产品映射**：期权合约到期货合约的映射

### 3.4 合约管理

#### 3.4.1 自动加载合约

天勤网关支持自动加载合约配置，包括：

- **期货合约**：自动加载期货合约信息
- **期权合约**：自动加载期权合约信息
- **合约乘数**：自动设置合约乘数
- **最小变动价位**：自动设置最小变动价位
- **交易单位**：自动设置交易单位

#### 3.4.2 从JSON文件加载

天勤网关支持从JSON文件加载合约配置：

```json
{
    "symbol": "v2605",
    "exchange": "DCE",
    "name": "PVC期货",
    "size": 5,
    "price_tick": 5,
    "min_volume": 1
}
```

#### 3.4.3 自动生成合约配置

天勤网关支持自动生成合约配置文件，包括：

- **查询所有合约**：查询天勤API中的所有可用合约
- **识别交易所**：自动识别交易所（CFFEX、SHFE、DCE、CZCE、INE）
- **识别品种**：自动识别品种（期货、期权）
- **生成配置文件**：自动生成tqsdk_contracts.json配置文件

### 3.5 数据服务

#### 3.5.1 历史K线查询

天勤网关支持历史K线数据查询，包括：

- **多种时间间隔**：1分钟、5分钟、15分钟、30分钟、1小时、2小时、4小时、1天、1周、1月
- **时间范围查询**：支持指定时间范围查询
- **合约查询**：支持单个合约或多个合约查询
- **数据转换**：将天勤API返回的数据转换为VeighNa的BarData对象

#### 3.5.2 历史Tick查询

天勤网关支持历史Tick数据查询，包括：

- **时间范围查询**：支持指定时间范围查询
- **合约查询**：支持单个合约或多个合约查询
- **数据转换**：将天勤API返回的数据转换为VeighNa的TickData对象

#### 3.5.3 时区处理

天勤网关正确处理中国时区，避免时间偏移：

```python
# 时区处理
CHINA_TZ = ZoneInfo("Asia/Shanghai")

# 转换时间
datetime_value = datetime.fromtimestamp(tp.datetime/1_000_000_000, tz=CHINA_TZ)
```

---

## 四、开发难点和解决方案

### 4.1 开发难点

#### 4.1.1 事件循环关闭问题

**问题描述**：

天勤API使用异步事件循环，在关闭连接时，如果事件循环中还有任务在等待执行，会抛出`RuntimeError: Event loop is closed`错误。

**解决方案**：

修改关闭顺序，先停止线程，再关闭API连接：

```python
def close(self) -> None:
    """
    关闭天勤网关连接
    """
    try:
        self.running = False
        
        # 先等待线程结束
        if self.thread:
            self.thread.join(timeout=10)
        
        # 再关闭API连接
        if self.api:
            self.api.close()
            self.api = None
        
        self.write_log("天勤网关连接已关闭")
    except Exception as e:
        self.write_log(f"关闭天勤网关失败: {str(e)}")
```

#### 4.1.2 委托状态转换问题

**问题描述**：

天勤API的委托状态和VeighNa的委托状态不一致，需要进行状态转换。

**解决方案**：

实现完整的状态转换逻辑：

```python
# 转换订单状态
if order.status == "ALIVE":
    if order.volume_orign == order.volume_left:
        status = Status.NOTTRADED
    else:
        status = Status.PARTTRADED
elif order.status == "FINISHED":
    if order.volume_orign == order.volume_left:
        status = Status.CANCELLED
    else:
        status = Status.ALLTRADED
elif order.status == "ALIVE" and order.volume_left == 0:
    status = Status.ALLTRADED
else:
    status = Status.NOTTRADED
```

#### 4.1.3 成交数量计算问题

**问题描述**：

天勤API的成交数量计算方式不正确，需要从成交记录中获取实际成交数量。

**解决方案**：

从成交记录中获取实际成交数量：

```python
# 从成交记录中获取实际成交数量
traded = 0
if hasattr(order, "trade_records"):
    for trade in order.trade_records.values():
        traded += trade.volume

# 创建订单数据对象
order_data = OrderData(
    symbol=symbol,
    exchange=exchange,
    orderid=tq_order_id,
    type=OrderType.LIMIT,
    direction=direction,
    offset=offset,
    price=order.limit_price,
    volume=order.volume_orign,
    traded=traded,  # 从成交记录中获取
    status=status,
    datetime=datetime.now(),
    reference="ManualTrading",
    gateway_name=self.gateway_name
)
```

#### 4.1.4 期权合约识别问题

**问题描述**：

天勤API的期权合约格式不统一，需要根据交易所和品种进行识别。

**解决方案**：

实现完整的期权合约识别逻辑：

```python
# 识别期权合约
def is_option_contract(symbol: str, exchange: Exchange) -> bool:
    """
    识别期权合约
    """
    # 大商所期权
    if exchange == Exchange.DCE:
        return "-" in symbol and ("C" in symbol or "P" in symbol)
    
    # 上期所期权
    elif exchange == Exchange.SHFE:
        return "C" in symbol or "P" in symbol
    
    # 中金所期权
    elif exchange == Exchange.CFFEX:
        return "IO" in symbol
    
    # 郑商所期权
    elif exchange == Exchange.CZCE:
        return "-" in symbol and ("C" in symbol or "P" in symbol)
    
    # 能源中心
    elif exchange == Exchange.INE:
        return "-" in symbol and ("C" in symbol or "P" in symbol)
    
    return False
```

#### 4.1.5 时间间隔转换问题

**问题描述**：

天勤API按照秒来计算时间间隔，需要将VeighNa的时间间隔转换为秒数。

**解决方案**：

实现完整的时间间隔转换字典：

```python
# 时间间隔转换
INTERVAL_VT2TQ: dict[Interval, int] = {
    Interval.MINUTE: 60,
    Interval.MINUTE_5: 300,
    Interval.MINUTE_15: 900,
    Interval.MINUTE_30: 1800,
    Interval.HOUR: 60 * 60,
    Interval.HOUR_2: 60 * 60 * 2,
    Interval.HOUR_4: 60 * 60 * 4,
    Interval.DAILY: 60 * 60 * 24,
    Interval.WEEKLY: 60 * 60 * 24 * 7,
    Interval.MONTHLY: 60 * 60 * 24 * 30
}
```

#### 4.1.6 时区处理问题

**问题描述**：

天勤API返回的时间戳是纳秒级，需要正确转换为datetime对象，并设置正确的时区。

**解决方案**：

正确处理时区转换：

```python
# 时区处理
CHINA_TZ = ZoneInfo("Asia/Shanghai")

# 转换时间
datetime_value = datetime.fromtimestamp(tp.datetime/1_000_000_000, tz=CHINA_TZ)
```

### 4.2 解决方案总结

| 开发难点 | 解决方案 | 技术要点 |
|---------|---------|---------|
| 事件循环关闭问题 | 修改关闭顺序 | 先停止线程，再关闭API连接 |
| 委托状态转换问题 | 实现完整的状态转换逻辑 | 支持所有委托状态 |
| 成交数量计算问题 | 从成交记录中获取实际成交数量 | 确保成交数量准确 |
| 期权合约识别问题 | 实现完整的期权合约识别逻辑 | 支持所有交易所期权 |
| 时间间隔转换问题 | 实现完整的时间间隔转换字典 | 支持所有时间间隔 |
| 时区处理问题 | 正确处理时区转换 | 避免时间偏移 |

---

## 五、性能优化

### 5.1 行情缓存

天勤网关实现了行情缓存机制，避免重复推送：

```python
# 行情缓存
self.quote_cache: dict[str, object] = {}

# 处理行情数据
for vt_symbol, quote in self.quote_cache.items():
    if self.api.is_changing(quote):
        # 推送行情数据
        self.on_tick(tick)
```

### 5.2 异步处理

天勤网关使用异步处理机制，提高性能：

```python
# 异步处理
def _run(self) -> None:
    """
    异步处理函数
    """
    while self.running:
        try:
            # 等待天勤API更新
            self.api.wait_update()
            
            # 处理账户数据
            self.process_account_data()
            
            # 处理持仓数据
            self.process_position_data()
            
            # 处理委托数据
            self.process_order_data()
            
            # 处理成交数据
            self.process_trade_data()
            
            # 处理行情数据
            self.process_quote_data()
        except Exception as e:
            self.write_log(f"处理数据错误: {str(e)}")
```

### 5.3 连接池

天勤网关支持连接池，提高并发性能：

```python
# 连接池
self.api_pool: list[TqApi] = []

# 创建连接
api = TqApi(auth="快期模拟,123456")
self.api_pool.append(api)
```

### 5.4 数据压缩

天勤网关支持数据压缩，减少网络传输量：

```python
# 数据压缩
import gzip

# 压缩数据
compressed_data = gzip.compress(data)
```

### 5.5 性能优化总结

| 优化技术 | 优化效果 | 技术要点 |
|---------|---------|---------|
| 行情缓存 | 避免重复推送 | 使用dict缓存行情数据 |
| 异步处理 | 提高并发性能 | 使用异步处理机制 |
| 连接池 | 提高并发性能 | 使用连接池管理连接 |
| 数据压缩 | 减少网络传输量 | 使用gzip压缩数据 |

---

## 六、使用指南

### 6.1 安装指南

#### 6.1.1 安装包

使用pip安装天勤网关：

```bash
pip install vnpy_tianqin
```

#### 6.1.2 开发模式安装

使用开发模式安装，方便开发调试：

```bash
cd vnpy/gateway/tqsdk
pip install -e .
```

#### 6.1.3 生产模式安装

使用生产模式安装，适合生产环境：

```bash
cd vnpy/gateway/tqsdk
python setup.py install
```

### 6.2 配置指南

#### 6.2.1 连接配置

在VeighNaTrader中连接天勤网关：

```python
from vnpy.gateway.tqsdk import TqSdkGateway

# 创建网关实例
gateway = TqSdkGateway()

# 连接网关
gateway.connect({
    "快期账号": "your_username",
    "快期密码": "your_password",
    "账户类型": "模拟账户"
})
```

#### 6.2.2 数据服务配置

在VeighNa的配置文件中设置数据服务：

```python
# vnpy/setting.py
SETTINGS["datafeed.name"] = "tianqin"
```

#### 6.2.3 合约配置

自动生成合约配置：

```bash
python vnpy/gateway/tqsdk/generate_contracts.py
```

### 6.3 使用指南

#### 6.3.1 实时行情

订阅实时行情：

```python
# 订阅行情
main_engine.subscribe(quote, symbol, exchange)
```

#### 6.3.2 交易功能

委托下单：

```python
# 委托下单
req = OrderRequest(
    symbol="v2605",
    exchange=Exchange.DCE,
    direction=Direction.LONG,
    offset=Offset.OPEN,
    type=OrderType.LIMIT,
    volume=1,
    price=4890.0,
    reference="ManualTrading"
)

main_engine.send_order(req, "TQSDK")
```

委托撤单：

```python
# 委托撤单
req = CancelRequest(
    orderid="vt_orderid",
    symbol="v2605",
    exchange=Exchange.DCE
)

main_engine.cancel_order(req, "TQSDK")
```

#### 6.3.3 数据查询

查询历史K线数据：

```python
# 查询历史K线数据
req = HistoryRequest(
    symbol="v2605",
    exchange=Exchange.DCE,
    interval=Interval.MINUTE,
    start=datetime(2026, 1, 1),
    end=datetime(2026, 1, 31)
)

datafeed = get_datafeed()
bars = datafeed.query_bar_history(req)
```

查询历史Tick数据：

```python
# 查询历史Tick数据
req = HistoryRequest(
    symbol="v2605",
    exchange=Exchange.DCE,
    start=datetime(2026, 1, 1),
    end=datetime(2026, 1, 31)
)

datafeed = get_datafeed()
ticks = datafeed.query_tick_history(req)
```

### 6.4 注意事项

#### 6.4.1 账户安全

- 请妥善保管天勤账号和密码
- 不要在代码中硬编码账号密码
- 建议使用配置文件或环境变量

#### 6.4.2 API权限

- 确保账号有查询合约的权限
- 模拟账户和实盘账户的权限可能不同

#### 6.4.3 网络连接

- 确保网络连接正常
- 建议使用稳定的网络环境

#### 6.4.4 合约配置

- 生成合约配置前，建议备份原有的 `tqsdk_contracts.json`
- 生成新文件后，需要重启天勤网关才能生效

#### 6.4.5 期权交易

- 期权交易风险较高，请谨慎操作
- 确保了解期权交易的基本原理
- 建议先使用模拟账户测试

#### 6.4.6 性能优化

- 避免订阅过多合约，影响性能
- 合理设置行情订阅频率
- 及时清理不必要的行情订阅

---

## 七、技术支持

### 7.1 官方文档

- 天勤SDK官方文档：https://doc.shinnytech.com/tqsdk/latest/
- 天勤SDK示例代码：https://github.com/shinnytech/tqsdk

### 7.2 技术支持

- 天勤技术支持：support@shinnytech.com
- VeighNa技术支持：vnpy@veighna.com

### 7.3 社区支持

- VeighNa社区：https://www.vnpy.com/
- VeighNa论坛：https://www.vnpy.com/forum/

---

## 八、总结

天勤网关为VeighNa交易平台提供了天勤量化平台的实时行情和交易功能，相比CTP网关，天勤网关具有注册简单、获取数据容易等优势，特别适合个人投资者和小型机构使用。

### 核心优势

1. **注册简单**：天勤提供免费模拟账户，注册流程简单，无需复杂审批
2. **数据获取容易**：天勤提供丰富的历史数据和实时行情，获取方式简单
3. **API设计友好**：天勤API设计简洁，文档完善，易于上手
4. **期权支持完善**：天勤支持期权链查询，方便获取期权合约信息
5. **跨平台支持**：天勤SDK支持Windows、Linux、Mac等平台
6. **社区活跃**：天勤有活跃的社区支持，问题解决及时

### 技术特点

1. **分层架构**：采用分层架构设计，模块职责清晰
2. **异步处理**：使用异步处理机制，提高性能
3. **行情缓存**：实现行情缓存机制，避免重复推送
4. **期权支持**：支持期权合约识别、解析、推送
5. **数据服务**：支持历史K线和Tick数据查询
6. **性能优化**：使用连接池、数据压缩等技术优化性能

### 适用场景

1. **个人投资者**：需要简单的量化交易工具
2. **小型机构**：需要快速搭建交易系统
3. **量化研究**：需要获取历史数据进行回测
4. **期权交易**：需要期权链查询功能
5. **教学演示**：需要演示量化交易系统

天勤网关是一个功能完善、性能优良、易于使用的量化交易网关，特别适合个人投资者和小型机构使用。通过本文的介绍，相信读者已经对天勤网关的技术架构、核心功能、开发难点、性能优化和使用指南有了全面的了解，能够更好地使用天勤网关进行量化交易。

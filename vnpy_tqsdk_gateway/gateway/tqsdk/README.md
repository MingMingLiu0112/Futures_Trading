# TqSdk Gateway for VeighNa

天勤网关（TqSdk Gateway）是VeighNa交易平台的官方数据接口之一，支持天勤量化平台的实时行情和交易功能。

## 功能特性

### 1. 实时行情
- 支持订阅多个合约的实时行情数据
- 支持Tick数据推送
- 支持五档行情数据
- 支持K线数据订阅

### 2. 交易功能
- 支持委托下单
- 支持委托撤单
- 支持查询资金
- 支持查询持仓
- 支持成交数据推送

### 3. 期权支持
- 支持期权合约识别
- 支持期权信息解析
- 支持期权产品名称映射
- 支持期权链自动生成

### 4. 合约管理
- 支持自动加载合约配置
- 支持从JSON文件加载合约
- 支持期货和期权合约
- 支持自动生成合约配置文件

### 5. 账户类型
- 支持模拟账户（TqKq）
- 支持快期实盘（TqAccount）
- 支持期货实盘（TqAccount + 期货公司账号）

## 安装方法

### 方法1：使用pip安装（推荐）

```bash
cd vnpy/gateway/tqsdk
pip install -e .
```

### 方法2：使用setup.py安装

```bash
cd vnpy/gateway/tqsdk
python setup.py install
```

### 方法3：手动安装

将 `vnpy/gateway/tqsdk` 目录复制到VeighNa的安装目录：

```bash
# Windows
xcopy /E /I /Y vnpy\gateway\tqsdk C:\Python312\Lib\site-packages\vnpy\gateway\tqsdk

# Linux/Mac
cp -r vnpy/gateway/tqsdk /usr/local/lib/python3.12/site-packages/vnpy/gateway/tqsdk
```

## 使用方法

### 1. 在VeighNaTrader中连接

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

### 2. 配置选项

天勤网关支持以下配置选项：

| 配置项 | 说明 | 默认值 |
|---------|------|---------|
| `auto_load` | 自动加载合约 | `True` |
| `contracts_file` | 合约配置文件 | `tqsdk_contracts.json` |
| `账户类型` | 账户类型 | `["模拟账户", "快期实盘"]` |
| `快期账号` | 快期账号 | `""` |
| `快期密码` | 快期密码 | `""` |
| `模拟账号编号` | 模拟账号编号 | `0` |
| `交易服务器地址` | 交易服务器地址 | `""` |
| `期货公司` | 期货公司 | `""` |
| `期货账号` | 期货账号 | `""` |
| `期货密码` | 期货密码 | `""` |

### 3. 合约配置

天勤网关支持从JSON文件加载合约配置，合约配置文件格式如下：

#### 期货合约

```json
{
    "symbol": "v2603",
    "exchange": "DCE",
    "name": "PVC期货",
    "size": 5,
    "price_tick": 5,
    "min_volume": 1
}
```

#### 期权合约

```json
{
    "symbol": "v2603-C-4400",
    "exchange": "DCE",
    "name": "PVC期权看涨",
    "size": 5,
    "price_tick": 5,
    "min_volume": 1
}
```

### 4. 自动生成合约

天勤网关提供了自动生成合约配置的工具：

```bash
python vnpy/gateway/tqsdk/generate_contracts.py --account <天勤账号> --password <天勤密码>
```

该工具会：
1. 从天勤API查询所有可用合约
2. 自动识别交易所和品种
3. 生成期货合约配置
4. 生成期权合约配置
5. 保存到 `tqsdk_contracts.json` 文件

### 5. 支持的交易所

- CFFEX（中国金融期货交易所）
- SHFE（上海期货交易所）
- DCE（大连商品交易所）
- CZCE（郑州商品交易所）
- INE（上海国际能源交易中心）

### 6. 支持的品种

#### 期货品种

- IF（沪深300期货）
- IH（上证50期货）
- IM（中证1000期货）
- cu（铜期货）
- au（黄金期货）
- rb（螺纹钢期货）
- m（豆粕期货）
- y（豆油期货）
- c（玉米期货）
- SR（白糖期货）
- CF（棉花期货）
- v（PVC期货）

#### 期权品种

- PVC期权（v2603-C-4400）
- 豆粕期权（m2605-C-3000）
- 豆油期权（y2605-C-8000）
- 玉米期权（c2605-C-2200）
- 白糖期权（SR605-C-6000）
- 棉花期权（CF605-C-11000）

### 7. 期权合约格式

天勤网关支持天勤SDK标准格式的期权合约：

#### 大商所（DCE）

```
DCE.v2603-C-4400  - PVC期权看涨
DCE.v2603-P-4400  - PVC期权看跌
```

#### 上期所（SHFE）

```
SHFE.au2004C308  - 黄金期权看涨
SHFE.au2004P308  - 黄金期权看跌
```

#### 中金所（CFFEX）

```
CFFEX.IO2002-C-3550  - 沪深300股指期权看涨
CFFEX.IO2002-P-3550  - 沪深300股指期权看跌
```

## 注意事项

### 1. 账户安全

- 请妥善保管天勤账号和密码
- 不要在代码中硬编码账号密码
- 建议使用配置文件或环境变量

### 2. API权限

- 确保账号有查询合约的权限
- 模拟账户和实盘账户的权限可能不同

### 3. 网络连接

- 确保网络连接正常
- 建议使用稳定的网络环境

### 4. 合约配置

- 生成合约配置前，建议备份原有的 `tqsdk_contracts.json`
- 生成新文件后，需要重启天勤网关才能生效

### 5. 期权交易

- 期权交易风险较高，请谨慎操作
- 确保了解期权交易的基本原理
- 建议先使用模拟账户测试

### 6. 性能优化

- 避免订阅过多合约，影响性能
- 合理设置行情订阅频率
- 及时清理不必要的行情订阅

## 技术支持

### 1. 官方文档

- 天勤SDK官方文档：https://doc.shinnytech.com/tqsdk/latest/
- 天勤SDK示例代码：https://github.com/shinnytech/tqsdk

### 2. 技术支持

- 天勤技术支持：support@shinnytech.com
- VeighNa技术支持：vnpy@veighna.com

### 3. 社区支持

- VeighNa社区：https://www.vnpy.com/
- VeighNa论坛：https://www.vnpy.com/forum/

## 更新日志

### 3.8.6.0（2026-01-23）

- 支持天勤API自动查询合约
- 支持期货和期权合约自动生成
- 支持期权合约识别和解析
- 添加持仓盈亏信息（pnl字段）
- 添加昨日持仓量（yd_volume字段）
- 添加委托信息调试日志
- 添加成交信息调试日志
- 添加datetime和reference字段到委托信息
- 完善setup.py安装文件
- 添加README文档

## 许可证

MIT License

## 作者

VeighNa Team

## 联系方式

- 官方网站：https://www.vnpy.com/
- 技术支持：vnpy@veighna.com
- 社区论坛：https://www.vnpy.com/forum/

# 天勤网关期权支持实现指南

## 概述

本文档说明如何为天勤网关添加期权支持，使其能够为期权模块（OptionMaster、OptionStrategy）提供必要的期权合约信息。

## 功能需求

期权模块需要网关提供以下期权相关字段：

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `option_portfolio` | str | 期权产品代码 | "IO", "HO", "MO", "CU_O" |
| `option_underlying` | str | 标的物合约代码 | "IF2605", "cu2605" |
| `option_type` | OptionType | 期权类型 | CALL/PUT |
| `option_strike` | float | 行权价 | 4500.0, 60000.0 |
| `option_expiry` | Datetime | 到期日 | 2026-05-15 |
| `option_index` | str | 期权索引 | "4500", "60000" |

## 实现方案

### 1. 期权合约命名规则

不同交易所的期权合约命名规则不同：

#### 中金所（CFFEX）- 股指期权
```
格式: IO2605-C-4500
- IO: 沪深300股指期权
- HO: 上证50股指期权
- MO: 中证1000股指期权
- 2605: 2026年5月到期
- C/P: 看涨/看跌
- 4500: 行权价
```

#### 上期所（SHFE）- 商品期权
```
格式: cu2605C60000
- cu: 标的物代码
- 2605: 2026年5月到期
- C/P: 看涨/看跌
- 60000: 行权价
```

#### 大商所（DCE）- 商品期权
```
格式: m2605C3000
- m: 标的物代码
- 2605: 2026年5月到期
- C/P: 看涨/看跌
- 3000: 行权价
```

#### 郑商所（CZCE）- 商品期权
```
格式: SR605C6000
- SR: 标的物代码
- 605: 2026年5月到期（年份省略20）
- C/P: 看涨/看跌
- 6000: 行权价
```

### 2. 核心实现

#### 2.1 期权解析器

已创建 `option_parser.py` 模块，提供以下功能：

- `OptionContractParser.is_option_contract()` - 判断是否为期权合约
- `OptionContractParser.parse_option_info()` - 解析期权合约信息
- `OptionContractParser.create_option_contract()` - 创建期权合约对象

#### 2.2 网关集成

在 `tqsdk_gateway.py` 中：

1. 导入期权解析器：
```python
from .option_parser import OptionContractParser
```

2. 修改 `load_contracts()` 方法，支持期权合约解析：
```python
if OptionContractParser.is_option_contract(symbol, exchange):
    contract = OptionContractParser.create_option_contract(
        symbol=symbol,
        exchange=exchange,
        name=name,
        size=size,
        pricetick=pricetick,
        min_volume=min_volume,
        gateway_name=self.gateway_name
    )
    if contract:
        self.contracts[vt_symbol] = contract
        self.on_contract(contract)
        option_count += 1
```

### 3. 配置文件示例

在 `tqsdk_contracts.json` 中添加期权合约：

```json
{
    "symbol": "IO2605-C-4500",
    "exchange": "CFFEX",
    "name": "沪深300股指期权看涨",
    "size": 100,
    "price_tick": 0.1,
    "min_volume": 1
},
{
    "symbol": "cu2605C60000",
    "exchange": "SHFE",
    "name": "铜期权看涨",
    "size": 5,
    "price_tick": 1,
    "min_volume": 1
},
{
    "symbol": "m2605C3000",
    "exchange": "DCE",
    "name": "豆粕期权看涨",
    "size": 10,
    "price_tick": 0.5,
    "min_volume": 1
},
{
    "symbol": "SR605C6000",
    "exchange": "CZCE",
    "name": "白糖期权看涨",
    "size": 10,
    "price_tick": 1,
    "min_volume": 1
}
```

## 使用示例

### 1. 启动天勤网关

```python
from vnpy.event import EventEngine
from vnpy.trader.engine import MainEngine
from vnpy.gateway.tqsdk import TqSdkGateway

event_engine = EventEngine()
main_engine = MainEngine(event_engine)

gateway = main_engine.add_gateway(TqSdkGateway)

setting = {
    "auto_load": True,
    "contracts_file": "tqsdk_contracts.json",
    "账户类型": "模拟账户",
    "模拟账号编号": 123456
}

gateway.connect(setting)
```

### 2. 查询期权合约

```python
from vnpy.trader.constant import Product

all_contracts = main_engine.get_all_contracts()
option_contracts = [c for c in all_contracts if c.product == Product.OPTION]

for contract in option_contracts:
    print(f"期权合约: {contract.vt_symbol}")
    print(f"  产品: {contract.option_portfolio}")
    print(f"  标的: {contract.option_underlying}")
    print(f"  类型: {contract.option_type}")
    print(f"  行权价: {contract.option_strike}")
    print(f"  到期日: {contract.option_expiry}")
    print()
```

### 3. 期权模块集成

期权模块会自动监听 `EVENT_CONTRACT` 事件，获取期权合约信息：

```python
from vnpy.trader.event import EVENT_CONTRACT

def on_contract(event):
    contract = event.data
    if contract.product == Product.OPTION:
        print(f"收到期权合约: {contract.vt_symbol}")
        print(f"  期权产品: {contract.option_portfolio}")
        print(f"  标的物: {contract.option_underlying}")
        print(f"  行权价: {contract.option_strike}")

main_engine.event_engine.register(EVENT_CONTRACT, on_contract)
```

## 期权模块与网关交互流程

```
┌─────────────────┐
│   期权模块      │
│ (OptionMaster/  │
│ OptionStrategy) │
└────────┬────────┘
         │
         │ 1. 启动模块
         ▼
┌─────────────────┐
│   MainEngine    │
└────────┬────────┘
         │
         │ 2. connect() - 连接天勤网关
         ▼
┌─────────────────┐
│ TqSdkGateway   │
└────────┬────────┘
         │
         │ 3. load_contracts() - 加载合约
         │    - 识别期权合约
         │    - 解析期权字段
         │    - 创建ContractData对象
         ▼
┌─────────────────┐
│  ContractData   │
│  (含期权字段)   │
└────────┬────────┘
         │
         │ 4. on_contract() - 推送合约事件
         ▼
┌─────────────────┐
│  EventEngine    │
│  EVENT_CONTRACT │
└────────┬────────┘
         │
         │ 5. 期权模块接收事件
         ▼
┌─────────────────┐
│   期权模块      │
│  - 构建期权组合  │
│  - 构建期权链    │
│  - 订阅期权行情  │
└────────┬────────┘
         │
         │ 6. subscribe() - 订阅行情
         ▼
┌─────────────────┐
│ TqSdkGateway   │
└────────┬────────┘
         │
         │ 7. 推送Tick数据
         ▼
┌─────────────────┐
│  EventEngine    │
│  EVENT_TICK     │
└────────┬────────┘
         │
         │ 8. 期权模块接收行情
         ▼
┌─────────────────┐
│   期权模块      │
│  - 定价计算     │
│  - 交易决策     │
└────────┬────────┘
         │
         │ 9. send_order() - 发送委托
         ▼
┌─────────────────┐
│ TqSdkGateway   │
│  执行交易       │
└─────────────────┘
```

## 测试验证

### 1. 验证期权合约加载

```python
from vnpy.trader.constant import Product

all_contracts = main_engine.get_all_contracts()
option_contracts = [c for c in all_contracts if c.product == Product.OPTION]

print(f"共加载 {len(option_contracts)} 个期权合约")

for contract in option_contracts:
    assert contract.option_portfolio is not None
    assert contract.option_underlying is not None
    assert contract.option_type is not None
    assert contract.option_strike is not None
    assert contract.option_expiry is not None
    print(f"✓ {contract.vt_symbol} - {contract.option_portfolio}")
```

### 2. 验证期权字段完整性

```python
from vnpy.trader.constant import OptionType

contract = main_engine.get_contract("IO2605-C-4500.CFFEX")

assert contract.option_portfolio == "IO"
assert contract.option_underlying == "IF2605"
assert contract.option_type == OptionType.CALL
assert contract.option_strike == 4500.0
assert contract.option_expiry.year == 2026
assert contract.option_expiry.month == 5
assert contract.option_index == "4500"

print("✓ 期权字段验证通过")
```

## 注意事项

1. **合约配置文件**：确保 `tqsdk_contracts.json` 中包含所有需要的期权合约

2. **期权产品代码**：
   - 股指期权：IO, HO, MO
   - 商品期权：标的物代码 + "_O"（如 CU_O, M_O）

3. **到期日处理**：当前实现使用固定的到期日（每月15日），实际应用中可能需要从交易所获取准确的到期日

4. **期权类型判断**：根据合约代码中的 C/P 判断看涨/看跌

5. **行权价解析**：注意不同交易所的行权价格式（整数/小数）

## 扩展功能

### 1. 动态获取期权合约

可以通过天勤API动态获取期权合约列表：

```python
def load_option_contracts_from_tqsdk(self):
    if not self.api:
        return
    
    symbols = self.api.get_all_symbols()
    for symbol in symbols:
        exchange_str, contract_symbol = symbol.split(".")
        exchange = Exchange(exchange_str)
        
        if OptionContractParser.is_option_contract(contract_symbol, exchange):
            quote = self.api.get_quote(symbol)
            contract_info = {
                "symbol": contract_symbol,
                "exchange": exchange_str,
                "name": quote.instrument_name,
                "size": quote.volume_multiple,
                "price_tick": quote.price_tick,
                "min_volume": 1
            }
            
            contract = OptionContractParser.create_option_contract(
                **contract_info,
                gateway_name=self.gateway_name
            )
            if contract:
                self.contracts[contract.vt_symbol] = contract
                self.on_contract(contract)
```

### 2. 支持ETF期权

扩展解析器以支持ETF期权：

```python
@staticmethod
def parse_etf_option(symbol: str, exchange: Exchange) -> Dict:
    """
    解析ETF期权合约
    
    格式: 510050P5M2600
    - 510050: ETF代码
    - P: 看跌
    - 5M: 2026年5月
    - 2600: 行权价
    """
    pattern = r"^(\d{6})([CP])(\d{1,2}M)(\d{4})$"
    match = re.match(pattern, symbol)
    
    if not match:
        return {}
    
    etf_code, cp_type, month_code, strike = match.groups()
    
    option_type = OptionType.CALL if cp_type == "C" else OptionType.PUT
    option_strike = float(strike)
    
    year = int("20" + month_code[:-1])
    month = int(month_code[-1])
    option_expiry = datetime(year, month, 15)
    
    portfolio_code = f"{etf_code}_O"
    
    return {
        "option_type": option_type,
        "option_strike": option_strike,
        "option_underlying": etf_code,
        "option_portfolio": portfolio_code,
        "option_expiry": option_expiry,
        "option_index": str(option_strike)
    }
```

## 总结

通过以上实现，天勤网关现在可以：

1. ✅ 识别和解析期权合约
2. ✅ 提供完整的期权字段信息
3. ✅ 支持多个交易所的期权合约
4. ✅ 与期权模块无缝集成
5. ✅ 支持期权行情订阅和交易

期权模块可以基于这些信息构建期权组合和期权链，实现完整的期权交易功能。

# 天勤数据下载工具

一个功能完整的天勤数据下载工具，支持命令行调用、公共函数调用和图形界面操作，可下载各类周期数据并导入到VNPY数据库。

## 功能特性

- ✅ 支持下载tick数据和各类K线数据（1分钟、5分钟、1小时、日线等）
- ✅ 支持通过命令行、公共函数和图形界面三种方式使用
- ✅ 支持保存为CSV文件
- ✅ 支持导入到VNPY数据库
- ✅ 支持批量下载多个合约
- ✅ 支持断点续传（追加模式）
- ✅ 支持复权计算
- ✅ 提供进度显示
- ✅ 完整的日志输出

## 安装依赖

### 基础依赖
```bash
pip install tqsdk
```

### 图形界面依赖（可选）
```bash
pip install pyqt6
```

## 文件说明

- `tq_data_downloader.py`: 核心下载逻辑，提供公共函数接口
- `tq_data_downloader_gui.py`: 图形界面实现
- `example_download.py`: 使用示例脚本

## 使用方法

### 1. 命令行方式

**基本语法**：
```bash
python tq_data_downloader.py --symbol <合约代码> --start <开始时间> --end <结束时间> --interval <周期> --output <输出文件>
```

**参数说明**：
- `--account`: 天勤账号（可选）
- `--password`: 天勤密码（可选）
- `--symbol`: 合约代码，如 `SHFE.cu2305`（必填）
- `--start`: 起始时间，格式：`YYYY-MM-DD HH:MM:SS` 或 `YYYY-MM-DD`（必填）
- `--end`: 结束时间，格式：`YYYY-MM-DD HH:MM:SS` 或 `YYYY-MM-DD`（必填）
- `--interval`: 数据周期，可选值：`tick`、`1m`、`5m`、`15m`、`30m`、`1h`、`2h`、`4h`、`d`（必填）
- `--output`: 输出CSV文件名（必填）
- `--mode`: 写入模式，`w` 为覆盖，`a` 为追加（默认：`w`）
- `--import`: 是否导入到VNPY数据库（可选）
- `--vnpy-symbol`: VNPY合约代码，如 `cu2305`（导入时必填）
- `--exchange`: 交易所，如 `SHFE`（导入时必填）

**示例**：
```bash
# 下载铜2305合约的1分钟数据
python tq_data_downloader.py --symbol SHFE.cu2305 --start 2023-01-01 --end 2023-01-10 --interval 1m --output cu2305_1min.csv

# 下载铜2305合约的tick数据并导入到数据库
python tq_data_downloader.py --symbol SHFE.cu2305 --start 2023-01-01 09:00:00 --end 2023-01-01 15:00:00 --interval tick --output cu2305_tick.csv --import --vnpy-symbol cu2305 --exchange SHFE
```

### 2. 公共函数调用

**示例代码**：
```python
from datetime import date
from tq_data_downloader import download_tq_data, import_tq_data_to_vnpy

# 下载数据
success = download_tq_data(
    symbol_list="SHFE.cu2305",
    dur_sec=60,  # 1分钟线
    start_dt=date(2023, 1, 1),
    end_dt=date(2023, 1, 10),
    csv_file_name="cu2305_1min.csv"
)

# 导入到数据库
if success:
    import_tq_data_to_vnpy(
        csv_file_path="cu2305_1min.csv",
        symbol="cu2305",
        exchange="SHFE",
        interval="1m"
    )
```

**函数说明**：

#### `download_tq_data()`
```python
def download_tq_data(
    symbol_list: Union[str, List[str]],
    dur_sec: int,
    start_dt: Union[date, datetime],
    end_dt: Union[date, datetime],
    csv_file_name: str,
    account: str = "",
    password: str = "",
    write_mode: str = 'w',
    adj_type: str = None
) -> bool:
    """
    下载天勤数据到CSV文件
    
    Args:
        symbol_list: 合约代码列表
        dur_sec: 数据周期（秒），0为tick数据
        start_dt: 起始时间
        end_dt: 结束时间
        csv_file_name: 输出文件名
        account: 天勤账号（可选）
        password: 天勤密码（可选）
        write_mode: 写入模式，'w'为覆盖，'a'为追加
        adj_type: 复权类型，'F'前复权，'B'后复权，None不复权
        
    Returns:
        是否下载成功
    """
```

#### `import_tq_data_to_vnpy()`
```python
def import_tq_data_to_vnpy(
    csv_file_path: str,
    symbol: str,
    exchange: str,
    interval: str = None
) -> bool:
    """
    导入天勤数据到VNPY数据库
    
    Args:
        csv_file_path: CSV文件路径
        symbol: VNPY合约代码，如"cu2305"
        exchange: 交易所，如"SHFE"
        interval: K线周期，如"1m"、"1h"、"d"（tick数据不需要）
        
    Returns:
        是否导入成功
    """
```

### 3. 图形界面方式

**启动图形界面**：
```bash
python tq_data_downloader_gui.py
```

**使用步骤**：
1. 输入天勤账号和密码（可选）
2. 输入合约代码，选择交易所和数据周期
3. 设置起始时间和结束时间
4. 选择保存路径和写入模式
5. （可选）勾选"导入到VNPY数据库"，并输入VNPY合约代码
6. 点击"开始下载"按钮
7. 查看进度条和日志输出

## 数据格式

### CSV文件格式

#### Tick数据
```
datetime,symbol,exchange,last_price,last_volume,volume,turnover,open_interest,open_price,high_price,low_price,pre_close,upper_limit,lower_limit,bid_price1,bid_volume1,ask_price1,ask_volume1,bid_price2,bid_volume2,ask_price2,ask_volume2,bid_price3,bid_volume3,ask_price3,ask_volume3,bid_price4,bid_volume4,ask_price4,ask_volume4,bid_price5,bid_volume5,ask_price5,ask_volume5
2023-01-01 09:00:00.000000,SHFE.cu2305,SHFE,68000,1,100,6800000,10000,68000,68000,68000,68000,71400,64600,67990,10,68000,5,67980,20,68010,3,67970,30,68020,2,67960,40,68030,1,67950,50,68040,5
```

#### K线数据
```
datetime,symbol,exchange,open,high,low,close,volume,turnover,open_interest
2023-01-01 09:00:00,SHFE.cu2305,SHFE,68000,68100,67900,68050,1000,68050000,10000
```

## VNPY数据库映射

### TickData映射
| CSV字段 | VNPY TickData字段 |
|---------|-------------------|
| datetime | datetime |
| last_price | last_price |
| volume | volume |
| turnover | turnover |
| open_interest | open_interest |
| open | open_price |
| high | high_price |
| low | low_price |
| pre_close | pre_close |
| upper_limit | limit_up |
| lower_limit | limit_down |
| bid_price1 | bid_price_1 |
| bid_volume1 | bid_volume_1 |
| ask_price1 | ask_price_1 |
| ask_volume1 | ask_volume_1 |
| ... | ... |

### BarData映射
| CSV字段 | VNPY BarData字段 |
|---------|-------------------|
| datetime | datetime |
| open | open_price |
| high | high_price |
| low | low_price |
| close | close_price |
| volume | volume |
| turnover | turnover |
| open_interest | open_interest |

## 注意事项

1. **天勤账号**：部分数据可能需要登录天勤账号才能下载
2. **网络连接**：确保网络连接稳定，下载过程中不要中断
3. **数据周期**：
   - `tick`: 0秒
   - `1m`: 60秒
   - `5m`: 300秒
   - `15m`: 900秒
   - `30m`: 1800秒
   - `1h`: 3600秒
   - `2h`: 7200秒
   - `4h`: 14400秒
   - `d`: 86400秒
4. **导入数据库**：确保VNPY数据库已正确配置
5. **合约代码格式**：使用天勤格式，如 `SHFE.cu2305`
6. **写入模式**：
   - `w`: 覆盖原有文件
   - `a`: 追加到原有文件末尾

## 示例脚本

查看 `example_download.py` 文件，了解如何使用公共函数进行数据下载和导入。

## 常见问题

### Q: 为什么下载速度很慢？
A: 天勤API有流量限制，建议合理设置下载范围，避免一次性下载大量数据。

### Q: 为什么下载失败？
A: 请检查：
- 合约代码格式是否正确
- 时间范围是否合理
- 网络连接是否正常
- 天勤账号密码是否正确（如果使用了登录）

### Q: 为什么导入数据库失败？
A: 请检查：
- CSV文件格式是否正确
- VNPY数据库是否已配置
- 合约代码和交易所是否匹配
- 周期设置是否正确

## 更新日志

### v1.0.0
- 初始版本
- 支持命令行、公共函数和图形界面三种使用方式
- 支持下载tick和K线数据
- 支持保存为CSV文件
- 支持导入到VNPY数据库

## 许可证

MIT

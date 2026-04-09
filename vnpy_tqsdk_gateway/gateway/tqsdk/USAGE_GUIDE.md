# VNPY TQ SDK 网关使用指南

## 概述

本指南将说明如何在安装修改后的 VNPY TQ SDK 网关（vnpy_tianqin）后，正确配置和使用它，确保 VNPY 能够正确加载并使用我们的改进功能。

## 安装准备

### 卸载原有包（可选）

如果您之前安装过 `vnpy_tqsdk` 或旧版本的 `vnpy_tianqin`，建议先卸载：

```bash
pip uninstall vnpy_tqsdk vnpy_tianqin
```

### 安装新版本

使用以下命令安装我们修改后的包：

```bash
# 通过本地文件安装
pip install dist/vnpy_tianqin-3.8.6.0-py3-none-any.whl

# 或通过 PyPI 安装（如果已发布）
pip install vnpy_tianqin
```

## 配置使用

### 1. 配置 vt_setting.json

在 VNPY 安装目录或运行目录下，确保 `vt_setting.json` 文件包含以下配置：

```json
{
    "datafeed.name": "tianqin",
    "datafeed.username": "your-tqsdk-username",
    "datafeed.password": "your-tqsdk-password",
    "database.timezone": "Asia/Shanghai",
    "database.name": "sqlite",
    "database.database": "database.db"
}
```

**关键配置说明**：
- `datafeed.name`: 设置为 `tianqin` 或 `tqsdk`（我们的包支持这两种配置）
- `datafeed.username`: 您的 TQ SDK 用户名
- `datafeed.password`: 您的 TQ SDK 密码

### 2. 在 VeighNa Trader 中添加网关

如果您使用 VeighNa Trader GUI，可以在 `Vnpy_Trader.py` 中添加网关：

```python
from vnpy.gateway.tqsdk import TqSdkGateway

# 在 main 函数中添加
main_engine.add_gateway(TqSdkGateway)
```

### 3. 验证是否正确加载

可以使用以下脚本来验证是否正确加载了我们修改后的包：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from vnpy.trader.setting import SETTINGS
from vnpy.trader.datafeed import get_datafeed

# 设置配置
SETTINGS["datafeed.name"] = "tianqin"

# 获取数据服务
print("=== 验证数据服务加载 ===")
datafeed = get_datafeed()
print(f"数据服务类型: {type(datafeed).__name__}")
print(f"数据服务模块: {datafeed.__module__}")

# 测试我们的改进功能
if hasattr(datafeed, 'is_valid_price'):
    test_result = datafeed.is_valid_price("100")
    print(f"✓ is_valid_price('100') = {test_result} (支持字符串输入)")
    
    test_result = datafeed.is_valid_price(None)
    print(f"✓ is_valid_price(None) = {test_result} (正确处理None值)")
    
    print("✅ 成功加载我们修改后的TQ SDK数据服务！")
else:
    print("❌ 未能加载我们修改后的TQ SDK数据服务！")
```

保存为 `verify_datafeed.py` 并运行：

```bash
python verify_datafeed.py
```

## 功能使用

### 1. 数据下载

在 VeighNa Trader 中：
1. 打开 "数据管理" 模块
2. 选择合约和时间范围
3. 点击 "下载" 按钮
4. 系统会自动使用我们修改后的 TQ SDK 数据服务下载数据

### 2. CTA 回测

在 VeighNa Trader 中：
1. 打开 "CTA 回测" 模块
2. 选择策略和合约
3. 设置回测参数
4. 点击 "开始回测"
5. 系统会自动使用我们修改后的 TQ SDK 数据服务获取历史数据

### 3. 实盘交易

在 VeighNa Trader 中：
1. 连接 TQ SDK 网关
2. 登录您的账号
3. 开始正常的交易操作

## 注意事项

### 1. 关于 vnpy_tqsdk 和 vnpy_tianqin

- **vnpy_tqsdk**：这是旧版本的包名，已不再维护
- **vnpy_tianqin**：这是新版本的包名，包含我们的所有改进
- 我们的包支持 `datafeed.name` 配置为 `tianqin` 或 `tqsdk`，确保向后兼容

### 2. 不需要修改 get_datafeed() 函数

我们的包已经内置了对 `get_datafeed()` 函数的支持，不需要修改 VNPY 核心代码。当 `datafeed.name` 配置为 `tianqin` 或 `tqsdk` 时，系统会自动加载我们的包。

### 3. 确保包已正确安装

可以使用以下命令检查包的安装情况：

```bash
pip show vnpy_tianqin
```

输出应该包含：
- **Name**: vnpy_tianqin
- **Version**: 3.8.6.0（或您安装的版本）
- **Location**: 显示安装路径

### 4. 常见问题排查

**问题**：系统未能加载我们的改进功能

**解决方案**：
1. 检查 `vt_setting.json` 中的 `datafeed.name` 配置是否正确
2. 检查包是否已正确安装：`pip show vnpy_tianqin`
3. 尝试卸载并重新安装包
4. 检查是否有其他版本的包冲突：`pip list | grep vnpy`

**问题**：数据下载或回测时出现错误

**解决方案**：
1. 检查 TQ SDK 用户名和密码是否正确
2. 检查网络连接是否正常
3. 查看日志文件，了解具体错误信息
4. 确保 TQ SDK 账号具有相应的权限

## 验证改进功能

我们的包包含以下改进功能，可以通过以下方式验证：

### 1. 测试 is_valid_price 方法

该方法现在支持字符串输入和正确处理 None 值：

```python
from vnpy.trader.datafeed import get_datafeed

datafeed = get_datafeed()

# 测试字符串输入
result1 = datafeed.is_valid_price("100")
print(f"is_valid_price('100') = {result1} (应为 True)")

# 测试 None 值
result2 = datafeed.is_valid_price(None)
print(f"is_valid_price(None) = {result2} (应为 False)")
```

### 2. 测试数据服务初始化

```python
from vnpy.trader.datafeed import get_datafeed

datafeed = get_datafeed()
result = datafeed.init(print)
print(f"数据服务初始化结果: {result}")
```

## 结论

通过正确的配置和安装，我们的修改后的 VNPY TQ SDK 网关（vnpy_tianqin）可以被 VNPY 正确加载和使用，无需修改 VNPY 核心代码。它包含了我们对数据服务的改进，能够更好地处理实际数据中的各种情况，避免数据下载和回测过程中的错误。

如果您遇到任何问题，可以参考本指南的排查步骤，或联系我们获取支持。

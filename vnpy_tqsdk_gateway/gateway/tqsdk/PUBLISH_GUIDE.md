# VNPY TQ SDK 网关发布指南

## 概述

本指南将说明如何将修改后的 VNPY TQ SDK 网关作为一个安装包发布出去，让其他用户可以正常安装到系统目录。

## 包信息

- **包名称**：vnpy_tianqin
- **当前版本**：3.8.6.0
- **主要功能**：TQ SDK 网关，支持期货、期权交易，以及数据服务

## 准备工作

1. **确保所有修改已完成**
   - 检查 `datafeed.py` 文件，确保我们的修改已正确实现
   - 测试功能是否正常工作

2. **更新版本号（可选）**
   - 编辑 `VERSION` 文件，更新版本号（如：3.8.7.0）
   - 版本号格式：主版本号.次版本号.修订号.构建号

3. **安装构建依赖**
   ```bash
   pip install setuptools wheel twine
   ```

## 构建安装包

1. **进入网关目录**
   ```bash
   cd vnpy/gateway/tqsdk
   ```

2. **构建源码包和二进制包**
   ```bash
   python setup.py sdist bdist_wheel
   ```

3. **检查构建结果**
   - 构建成功后，会在 `dist` 目录下生成两个文件：
     - `vnpy_tianqin-3.8.6.0.tar.gz`（源码包）
     - `vnpy_tianqin-3.8.6.0-py3-none-any.whl`（二进制包）

## 发布到 PyPI

1. **注册 PyPI 账号**
   - 访问 https://pypi.org/ 注册账号
   - 或使用已有的账号

2. **配置 PyPI 认证**
   - 创建 `~/.pypirc` 文件，添加以下内容：
     ```ini
     [pypi]
     username = __token__
     password = your-api-token
     ```
   - 或使用 `twine upload` 命令时手动输入账号密码

3. **上传包到 PyPI**
   ```bash
   twine upload dist/*
   ```

## 安装和使用

### 安装方式

1. **通过 PyPI 安装**
   ```bash
   pip install vnpy_tianqin
   ```

2. **通过本地文件安装**
   ```bash
   pip install dist/vnpy_tianqin-3.8.6.0-py3-none-any.whl
   ```

### 使用方式

1. **配置数据服务**
   - 在 `vt_setting.json` 中添加以下配置：
     ```json
     {
         "datafeed.name": "tianqin",
         "datafeed.username": "your-tqsdk-username",
         "datafeed.password": "your-tqsdk-password"
     }
     ```

2. **在代码中使用**
   ```python
   from vnpy.trader.datafeed import get_datafeed
   
   # 获取数据服务实例（会自动使用我们修改过的TQ SDK数据服务）
   datafeed = get_datafeed()
   ```

3. **在 VeighNa Trader 中使用**
   - 启动 VeighNa Trader
   - 在 "系统设置" 中配置数据服务
   - 在 "CTA 回测" 或 "数据下载" 中使用

## 注意事项

1. **兼容性**
   - 确保包的依赖版本正确
   - 支持 Python 3.7+ 版本

2. **测试**
   - 在发布前，确保在不同环境下测试功能
   - 测试数据下载、回测等核心功能

3. **文档**
   - 保持文档的更新，包括使用说明和技术文章
   - 记录重要的修改和新增功能

4. **版本控制**
   - 使用 Git 进行版本控制，记录所有修改
   - 发布前确保代码已提交到仓库

## 常见问题

### Q: 如何更新已发布的包？
A: 更新 VERSION 文件，重新构建并上传即可。PyPI 会自动处理版本更新。

### Q: 如何安装特定版本的包？
A: 使用 `pip install vnpy_tianqin==3.8.6.0` 安装特定版本。

### Q: 如何卸载已安装的包？
A: 使用 `pip uninstall vnpy_tianqin` 卸载。

### Q: 如何查看已安装的包信息？
A: 使用 `pip show vnpy_tianqin` 查看。

## 结论

通过以上步骤，您可以将修改后的 VNPY TQ SDK 网关作为一个安装包发布出去，让其他用户可以正常安装到系统目录。这样，用户就可以直接使用我们改进后的功能，而不需要手动修改代码。

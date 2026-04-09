# PTA数据采集器 - Windows安装指南

## 环境要求
- Windows 10/11
- Python 3.12（已安装）

## 第一步：安装依赖

打开命令提示符（Win+R → 输入cmd → 回车），依次输入以下命令：

```bash
pip install akshare requests -U
```

## 第二步：创建配置.env文件

在 `pta_collector.py` 同目录下创建一个 `config.env` 文件，内容如下：

```env
GITHUB_TOKEN=你的GitHub_TOKEN
FEISHU_WEBHOOK=你的飞书Webhook地址
```

> GitHub Token 在 GitHub Settings → Developer settings → Personal access tokens 生成，需要repo权限。

## 第三步：获取Git Bash（用于推送数据到GitHub）

下载地址：https://git-scm.com/download/win

安装时一路点"Next"即可。

## 第四步：配置GitHub访问

在命令提示符里输入：

```bash
git config --global user.name "你的GitHub用户名"
git config --global user.email "你的GitHub邮箱"
```

## 第五步：克隆数据仓库

```bash
cd %USERPROFILE%
git clone https://github.com/MingMingLiu0112/pta-data.git
cd pta-data
mkdir data
git add .
git commit -m "init"
git push -u origin main
```

> 注意：如果仓库不存在，先在GitHub上手动创建空的 `pta-data` 私有仓库

## 第六步：放入采集脚本

把 `pta_collector.py` 和 `config.env` 复制到 `pta-data` 目录下。

## 第七步：运行采集脚本

```bash
cd %USERPROFILE%\pta-data
python pta_collector.py
```

看到 "采集完成" 即成功。

## 第八步：设置每日定时任务

1. 打开命令提示符，输入：
```bash
taskschd.msc
```

2. 右侧点"创建基本任务"

3. 名称填"PTA数据采集（早盘）"，触发器选"每日"，时间填"10:30"

4. 操作选"启动程序"，程序填：
```
C:\Users\你的用户名\AppData\Local\Programs\Python\Python312\python.exe
```

5. 参数填：
```
C:\Users\你的用户名\pta-data\pta_collector.py
```

6. 同样方法创建午盘（14:00）和夜盘（21:30）

## 数据说明

采集的数据包含：
- PTA期货行情（收盘价、成交量）
- PX现货价格
- 布伦特原油价格
- PTA成本区间计算
- 期权合约信息（如果东财T链可达）

数据保存在本地 `data/YYYYMMDD/` 目录，并推送到GitHub仓库。

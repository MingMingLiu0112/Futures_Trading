# 🚀 快速上手指南

## 方式一：使用 GitHub 网页（推荐新手）

### 步骤 1: 创建 GitHub 仓库

1. 访问 https://github.com/new
2. 仓库名称: `futures-options-analysis`
3. 选择 Public 或 Private
4. **不要**勾选 "Add a README file"（我们已经有代码了）
5. 点击 "Create repository"

### 步骤 2: 推送代码

在终端运行以下命令（把 `YOUR_USERNAME` 换成你的 GitHub 用户名）:

```bash
cd /home/admin/.openclaw/workspace/codeman/futures_options

# 添加远程仓库
git remote add origin https://github.com/YOUR_USERNAME/futures-options-analysis.git

# 推送代码
git push -u origin master
```

### 步骤 3: 配置 Secrets

1. 进入仓库 → Settings → Secrets and variables → Actions
2. 点击 "New repository secret"
3. 添加:
   - **Name**: `FEISHU_WEBHOOK`
   - **Secret**: `https://open.feishu.cn/open-apis/bot/v2/hook/8148922b-04f5-469f-994e-ae3e17d6b256`

### 步骤 4: 手动触发测试

1. 进入仓库 → Actions 页面
2. 点击 "Futures Options Analysis" workflow
3. 点击 "Run workflow" → "Run workflow"

---

## 方式二：使用 gh CLI

### 安装 gh CLI

```bash
# Linux
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt update && sudo apt install gh
```

### 登录 GitHub

```bash
gh auth login
```

### 运行设置脚本

```bash
cd /home/admin/.openclaw/workspace/codeman/futures_options
chmod +x setup_github.sh
./setup_github.sh
```

---

## 配置完成后的操作

### 修改分析的品种

编辑 `main.py` 中的 `TARGET_SYMBOLS`:

```python
TARGET_SYMBOLS = ["CU", "AU", "AG", "RU", "SC"]
```

常见品种代码:
- `CU` - 铜
- `AU` - 黄金
- `AG` - 白银
- `RU` - 橡胶
- `SC` - 原油
- `I` - 铁矿石
- `M` - 豆粕

### 查看分析结果

- GitHub Actions: 仓库 → Actions
- 飞书群: 每天 08:00, 15:00, 21:00 自动推送

---

## ⚠️ 注意事项

1. **期权数据**: 当前使用模拟IV数据，实际使用时需要接入真实期权数据源
2. **基差数据**: 需要配置现货数据源才能获取真实基差
3. **风险提示**: 本工具仅供参考，不构成投资建议

---

需要帮助？随时问我！

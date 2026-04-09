# 项目打包指南

## 📦 打包选项

### 选项1：完整包（推荐）
包含所有文件，开箱即用。

### 选项2：最小包
仅包含运行必需文件。

### 选项3：Docker镜像
容器化打包。

## 📁 完整包内容

### 必需文件
```
iv_curve_component.zip
├── index.html              # 主页面
├── iv-curve.js            # 核心逻辑
├── api.py                 # 后端API
├── requirements.txt       # Python依赖
├── start.sh              # 启动脚本
└── README.md             # 使用说明
```

### 文档文件（可选）
```
├── DEPLOY.md             # 部署指南
├── DEMO.md               # 演示脚本
├── SUMMARY.md            # 项目总结
├── PROJECT_STRUCTURE.md  # 结构说明
├── PACKAGE.md            # 本文档
├── test.html             # 测试页面
└── demo_data.json        # 示例数据
```

## 🔧 打包脚本

### 创建完整包
```bash
#!/bin/bash
# package.sh

PACKAGE_NAME="iv_curve_component"
VERSION="1.0.0"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

echo "📦 打包IV曲线组件 v${VERSION}..."

# 创建临时目录
TEMP_DIR="/tmp/${PACKAGE_NAME}_${TIMESTAMP}"
mkdir -p "${TEMP_DIR}"

# 复制必需文件
cp index.html "${TEMP_DIR}/"
cp iv-curve.js "${TEMP_DIR}/"
cp api.py "${TEMP_DIR}/"
cp requirements.txt "${TEMP_DIR}/"
cp start.sh "${TEMP_DIR}/"
cp README.md "${TEMP_DIR}/"

# 复制文档文件（可选）
cp DEPLOY.md "${TEMP_DIR}/" 2>/dev/null || true
cp DEMO.md "${TEMP_DIR}/" 2>/dev/null || true
cp SUMMARY.md "${TEMP_DIR}/" 2>/dev/null || true

# 创建版本文件
echo "version: ${VERSION}" > "${TEMP_DIR}/VERSION"
echo "build_date: ${TIMESTAMP}" >> "${TEMP_DIR}/VERSION"
echo "files:" >> "${TEMP_DIR}/VERSION"
find "${TEMP_DIR}" -type f -name "*.html" -o -name "*.js" -o -name "*.py" -o -name "*.md" -o -name "*.sh" -o -name "*.txt" | sort | while read file; do
    filename=$(basename "$file")
    size=$(stat -c%s "$file")
    echo "  - ${filename}: ${size} bytes" >> "${TEMP_DIR}/VERSION"
done

# 打包
cd /tmp
zip -r "${PACKAGE_NAME}_v${VERSION}_${TIMESTAMP}.zip" "${PACKAGE_NAME}_${TIMESTAMP}/"

# 计算哈希值
MD5=$(md5sum "${PACKAGE_NAME}_v${VERSION}_${TIMESTAMP}.zip" | cut -d' ' -f1)
SHA256=$(sha256sum "${PACKAGE_NAME}_v${VERSION}_${TIMESTAMP}.zip" | cut -d' ' -f1)

echo "📊 打包完成:"
echo "  文件: ${PACKAGE_NAME}_v${VERSION}_${TIMESTAMP}.zip"
echo "  大小: $(du -h "${PACKAGE_NAME}_v${VERSION}_${TIMESTAMP}.zip" | cut -f1)"
echo "  MD5: ${MD5}"
echo "  SHA256: ${SHA256}"

# 清理临时文件
rm -rf "${TEMP_DIR}"

echo "✅ 打包完成！"
```

### 创建最小包
```bash
#!/bin/bash
# package_minimal.sh

PACKAGE_NAME="iv_curve_component_minimal"
VERSION="1.0.0"

echo "📦 打包最小化IV曲线组件..."

# 必需文件列表
ESSENTIAL_FILES=(
    "index.html"
    "iv-curve.js"
    "api.py"
    "requirements.txt"
    "start.sh"
    "README.md"
)

# 检查文件是否存在
for file in "${ESSENTIAL_FILES[@]}"; do
    if [ ! -f "$file" ]; then
        echo "❌ 文件缺失: $file"
        exit 1
    fi
done

# 创建ZIP包
zip "${PACKAGE_NAME}_v${VERSION}.zip" "${ESSENTIAL_FILES[@]}"

echo "✅ 最小包创建完成: ${PACKAGE_NAME}_v${VERSION}.zip"
```

## 🐳 Docker镜像打包

### Dockerfile
```dockerfile
# Dockerfile
FROM python:3.9-slim

LABEL maintainer="your-email@example.com"
LABEL version="1.0.0"
LABEL description="IV Curve Visualization Component"

WORKDIR /app

# 复制必需文件
COPY index.html .
COPY iv-curve.js .
COPY api.py .
COPY requirements.txt .
COPY start.sh .

# 设置权限
RUN chmod +x start.sh

# 安装依赖
RUN pip install --no-cache-dir -r requirements.txt

# 创建非root用户
RUN useradd -m -u 1000 ivuser && chown -R ivuser:ivuser /app
USER ivuser

# 暴露端口
EXPOSE 5000

# 健康检查
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/api/iv/current || exit 1

# 启动命令
CMD ["python", "api.py"]
```

### 构建镜像
```bash
# 构建Docker镜像
docker build -t iv-curve:1.0.0 .

# 标记为latest
docker tag iv-curve:1.0.0 iv-curve:latest

# 保存为tar文件
docker save iv-curve:1.0.0 -o iv-curve-1.0.0.tar

# 压缩
gzip iv-curve-1.0.0.tar
```

## 📋 发布清单

### 版本1.0.0发布清单
- [ ] 代码审查完成
- [ ] 功能测试通过
- [ ] 性能测试通过
- [ ] 安全扫描通过
- [ ] 文档更新完成
- [ ] 打包文件生成
- [ ] 哈希值计算
- [ ] 发布说明编写

### 发布文件
```
releases/v1.0.0/
├── iv_curve_component_v1.0.0.zip      # 完整包
├── iv_curve_component_minimal_v1.0.0.zip  # 最小包
├── iv-curve-1.0.0.tar.gz              # Docker镜像
├── CHANGELOG.md                       # 变更日志
├── RELEASE_NOTES.md                   # 发布说明
└── checksums.txt                      # 哈希值文件
```

## 📝 发布说明模板

```markdown
# IV曲线组件 v1.0.0 发布说明

## 🎉 新版本发布

### 版本信息
- **版本号**: 1.0.0
- **发布日期**: 2024-04-08
- **状态**: 稳定版

### 下载链接
- 完整包: [iv_curve_component_v1.0.0.zip](链接)
- 最小包: [iv_curve_component_minimal_v1.0.0.zip](链接)
- Docker镜像: [iv-curve-1.0.0.tar.gz](链接)

### 哈希值验证
```
文件: iv_curve_component_v1.0.0.zip
MD5: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SHA256: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

文件: iv_curve_component_minimal_v1.0.0.zip
MD5: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SHA256: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

## 🚀 新功能

### 核心功能
1. **双曲线对比** - 前日收盘 vs 实时曲线
2. **曲线移动分析** - 垂直/水平/扭曲分析
3. **动画可视化** - 平滑过渡动画
4. **市场情绪分析** - 自动判断市场情绪

### 技术特性
1. **响应式设计** - 多设备支持
2. **实时更新** - 动态数据加载
3. **API集成** - RESTful接口
4. **导出功能** - 图表导出

## 📊 系统要求

### 最低要求
- Python 3.8+
- 现代浏览器（Chrome 90+/Firefox 88+）
- 1GB RAM
- 100MB磁盘空间

### 推荐配置
- Python 3.9+
- Chrome 100+
- 2GB RAM
- 500MB磁盘空间

## 🔧 安装指南

### 快速安装
```bash
# 下载并解压
unzip iv_curve_component_v1.0.0.zip
cd iv_curve_component

# 启动服务
./start.sh
```

### Docker安装
```bash
# 加载镜像
docker load -i iv-curve-1.0.0.tar.gz

# 运行容器
docker run -d -p 5000:5000 --name iv-curve iv-curve:1.0.0
```

## 📖 使用说明

详细使用说明请参考 [README.md](README.md)

## 🐛 已知问题

1. 在极慢的网络环境下，动画可能卡顿
2. 某些移动设备浏览器可能不支持所有CSS特性
3. API响应时间可能受服务器负载影响

## 🔄 升级说明

### 从旧版本升级
1. 备份现有配置和数据
2. 停止旧版本服务
3. 安装新版本
4. 恢复配置和数据
5. 启动新服务

### 配置变更
- 无破坏性变更
- 向后兼容
- 新增配置可选

## 🤝 技术支持

### 获取帮助
- 文档: [README.md](README.md)
- 问题: [GitHub Issues](链接)
- 邮件: support@example.com

### 社区支持
- 论坛: [社区论坛](链接)
- Discord: [Discord频道](链接)
- 微信群: [微信群二维码](链接)

## 📄 许可证

本项目采用 MIT 许可证。详见 [LICENSE](LICENSE) 文件。

## 🙏 致谢

感谢所有贡献者和用户的支持！

---

**祝您使用愉快！** 🚀
```

## 🔒 安全发布流程

### 1. 代码审计
```bash
# 安全扫描
bandit -r . -f json -o security_scan.json

# 依赖漏洞检查
safety check -r requirements.txt

# 代码质量检查
pylint api.py
```

### 2. 构建验证
```bash
# 验证打包文件
unzip -t iv_curve_component_v1.0.0.zip

# 验证Docker镜像
docker run --rm iv-curve:1.0.0 python -c "import flask; print('OK')"

# 验证启动脚本
./start.sh --test
```

### 3. 发布签名
```bash
# 生成签名
gpg --detach-sign --armor iv_curve_component_v1.0.0.zip

# 验证签名
gpg --verify iv_curve_component_v1.0.0.zip.asc
```

## 📈 版本管理

### 版本号规则
- **主版本号**：不兼容的API修改
- **次版本号**：向下兼容的功能性新增
- **修订号**：向下兼容的问题修正

### 分支策略
- `main`：稳定版
- `develop`：开发版
- `feature/*`：功能分支
- `release/*`：发布分支
- `hotfix/*`：热修复分支

### 标签管理
```bash
# 创建标签
git tag -a v1.0.0 -m "Release v1.0.0"

# 推送标签
git push origin v1.0.0
```

## 🚢 部署流程

### 开发环境
```bash
# 开发分支
git checkout develop
./start.sh --dev
```

### 测试环境
```bash
# 测试分支
git checkout release/v1.0.0
./start.sh --test
```

### 生产环境
```bash
# 稳定版本
git checkout v1.0.0
./start.sh --prod
```

## 📊 质量指标

### 代码质量
- 测试覆盖率: > 80%
- 代码重复率: < 5%
- 复杂度: < 10 (McCabe)
- 文档覆盖率: > 90%

### 性能指标
- API响应时间: < 100ms
- 页面加载时间: < 2s
- 内存使用: < 200MB
- 并发用户: > 100

### 安全指标
- 漏洞数量: 0
- 依赖漏洞: 0
- 权限配置: 最小权限原则
- 日志记录: 完整审计

## 🔄 更新策略

### 定期更新
- 每月: 安全更新
- 每季度: 功能更新
- 每年: 大版本更新

### 紧急更新
- 安全漏洞: 24小时内
- 严重错误: 48小时内
- 功能问题: 一周内

### 兼容性保证
- API向后兼容至少2个版本
- 数据格式向后兼容
- 配置向前兼容

---

**打包完成，准备发布！** 🎉
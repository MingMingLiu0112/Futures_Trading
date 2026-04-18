# 合并趋势线属性面板到 kline_lightweight.html

> **目标：** 将 `drawing_test.html` 的绘图属性面板（右键菜单+属性设置+多周期可见性）合并到 `kline_lightweight.html`

---

## 当前状态

- **kline_lightweight.html**（主线）：简单绘图工具条，周期切换时重绘线条，无属性面板
- **drawing_test.html**（测试分支）：完整右键菜单、属性面板（颜色/线宽/周期/价格区间）、多周期可见性过滤

---

## 合并范围

### 1. CSS 样式（~80行）
**文件：** `pta_analysis/templates/kline_lightweight.html`

在 `</style>` 前添加（大约 line 253 附近）：

```css
/* 右键菜单 */
.context-menu {
    position: fixed;
    background: #2a2a3e;
    border: 1px solid #444;
    border-radius: 6px;
    padding: 4px 0;
    min-width: 160px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.4);
    z-index: 1000;
    display: none;
}
.context-menu.show { display: block; }
.context-menu-item {
    padding: 8px 14px;
    cursor: pointer;
    font-size: 13px;
    color: #ddd;
}
.context-menu-item:hover { background: #3a3a5e; }
.context-menu-item.danger { color: #ff6b6b; }
.context-menu-item.danger:hover { background: rgba(255,107,107,0.15); }
.context-menu-separator { height: 1px; background: #444; margin: 4px 0; }

/* 属性面板 */
.props-panel {
    position: fixed;
    top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    background: #252538;
    border: 1px solid #444;
    border-radius: 10px;
    padding: 20px 24px;
    min-width: 320px;
    max-width: 400px;
    z-index: 1001;
    display: none;
    box-shadow: 0 8px 32px rgba(0,0,0,0.5);
}
.props-panel.show { display: block; }
.props-panel h3 { color: #FF9800; margin-bottom: 16px; font-size: 15px; border-bottom: 1px solid #444; padding-bottom: 10px; }
.props-panel .prop-row { display: flex; align-items: center; margin-bottom: 12px; gap: 10px; }
.props-panel .prop-label { color: #aaa; font-size: 13px; min-width: 80px; }
.props-panel .prop-value { flex: 1; }
.props-panel input[type="checkbox"] { width: 16px; height: 16px; cursor: pointer; }
.props-panel input[type="number"] { background: #333; color: #ddd; border: 1px solid #555; border-radius: 4px; padding: 4px 8px; width: 80px; font-size: 13px; }
.props-panel .prop-hint { color: #666; font-size: 11px; margin-top: 4px; }
.props-panel .btn-row { display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px; border-top: 1px solid #444; padding-top: 14px; }
.props-panel button { padding: 6px 16px; border-radius: 4px; border: none; cursor: pointer; font-size: 13px; }
.props-panel .btn-ok { background: #FF9800; color: #fff; }
.props-panel .btn-cancel { background: #444; color: #ddd; }
.props-panel .btn-apply { background: #4CAF50; color: #fff; }

/* 覆盖层遮罩 */
.overlay {
    position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.5);
    z-index: 1000;
    display: none;
}
.overlay.show { display: block; }

/* 周期标签 */
.period-tags { display: flex; gap: 6px; flex-wrap: wrap; }
.period-tag {
    padding: 3px 10px; border-radius: 4px; font-size: 12px;
    background: #333; color: #888; cursor: pointer; border: 1px solid #444;
    transition: all 0.15s;
}
.period-tag.active { background: #FF9800; color: #fff; border-color: #FF9800; }
```

### 2. HTML 模板（约70行）
**文件：** `pta_analysis/templates/kline_lightweight.html`

#### 2.1 右键菜单 HTML
在 `</body>` 前、`</html>` 后添加：

```html
<!-- 右键菜单 -->
<div class="context-menu" id="contextMenu" onmousedown="event.stopPropagation();">
    <div class="context-menu-item" onclick="ctxDeleteDrawing()">🗑 删除此图形</div>
    <div class="context-menu-item" onclick="ctxShowProps()">⚙ 属性设置</div>
</div>

<!-- 属性面板 -->
<div class="overlay" id="propsOverlay"></div>
<div class="props-panel" id="propsPanel">
    <h3 id="propsTitle">📐 图形属性</h3>
    <div id="propsContent">
        <div class="prop-row">
            <span class="prop-label">类型</span>
            <span class="prop-value" id="propType" style="color:#FF9800;"></span>
        </div>
        <div class="prop-row">
            <span class="prop-label">ID</span>
            <span class="prop-value" id="propId" style="color:#888;font-size:12px;"></span>
        </div>
        <div class="prop-row" style="align-items:flex-start;">
            <span class="prop-label">跨越周期</span>
            <div class="prop-value">
                <div class="period-tags" id="propCycles">
                    <span class="period-tag" data-period="1min" onclick="toggleCycleTag(this)">1min</span>
                    <span class="period-tag" data-period="5min" onclick="toggleCycleTag(this)">5min</span>
                    <span class="period-tag" data-period="15min" onclick="toggleCycleTag(this)">15min</span>
                    <span class="period-tag" data-period="60min" onclick="toggleCycleTag(this)">60min</span>
                </div>
                <div class="prop-hint">勾选后图形将在对应周期图表上同时显示</div>
            </div>
        </div>
        <div class="prop-row">
            <span class="prop-label">颜色</span>
            <div class="prop-value">
                <button class="tool-btn draw-color-btn" data-color="#FFD700" onclick="setPropColor('#FFD700')" style="background:#FFD700;color:#000;">&nbsp;</button>
                <button class="tool-btn draw-color-btn" data-color="#FFFFFF" onclick="setPropColor('#FFFFFF')" style="background:#fff;color:#000;">&nbsp;</button>
                <button class="tool-btn draw-color-btn" data-color="#4CAF50" onclick="setPropColor('#4CAF50')" style="background:#4CAF50;color:#fff;">&nbsp;</button>
                <button class="tool-btn draw-color-btn" data-color="#2196F3" onclick="setPropColor('#2196F3')" style="background:#2196F3;color:#fff;">&nbsp;</button>
                <input type="color" id="propColorPicker" onchange="setPropColor(this.value)" style="background:#333;border:1px solid #555;border-radius:4px;width:30px;height:24px;cursor:pointer;">
            </div>
        </div>
        <div class="prop-row">
            <span class="prop-label">线宽</span>
            <div class="prop-value">
                <select id="propLineWidth">
                    <option value="1">细</option>
                    <option value="2">中</option>
                    <option value="3">粗</option>
                </select>
            </div>
        </div>
    </div>
    <div class="btn-row">
        <button class="btn-ok" onclick="event.stopPropagation();applyProps();closePropsPanel();">确定</button>
        <button class="btn-cancel" onclick="event.stopPropagation();closePropsPanel()">取消</button>
    </div>
</div>
```

#### 2.2 修改 drawings 数据结构
**位置：** `kline_lightweight.html` 中 `drawings` 数组的每条记录

绘图创建时（finishDrawing 函数），增加两个字段：
```javascript
// 在创建 series 后，给 drawings.push(...) 加上：
cycles: [currentPeriod],  // 当前周期数组
priceMin: null,            // 价格区间下限（null表示不限制）
priceMax: null,            // 价格区间上限
```

#### 2.3 修改跨周期恢复逻辑
**位置：** `period change` 事件中 `restoreDrawings` 函数

在 `savedDrawings.forEach` 循环中，给每个新建的 series 对象补充 `cycles` 和 `priceMin/priceMax` 字段（从 savedDrawings 读取）。

---

### 3. JavaScript 函数（约200行）

#### 3.1 新增全局变量
```javascript
let ctxTargetId = null;        // 右键目标图形ID
let currentPeriod = '1min';    // 当前周期（从DOM读取）
```

#### 3.2 新增右键菜单事件绑定
在 `initChart()` 或 `mousemove` 事件附近添加：

```javascript
// 右键菜单
document.getElementById('main-chart').addEventListener('contextmenu', (e) => {
    e.preventDefault();
    const rect = document.getElementById('main-chart').getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const clickedDrawing = findDrawingAtPoint(x, y);
    if (clickedDrawing) {
        ctxTargetId = clickedDrawing.id;
        showContextMenu(e.clientX, e.clientY);
    }
});

// 点击空白处关闭菜单/属性面板
document.addEventListener('click', (e) => {
    if (!e.target.closest('.context-menu') && !e.target.closest('.props-panel')) {
        closeContextMenu();
        closePropsPanel();
    }
});

// ESC关闭
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
        closeContextMenu();
        closePropsPanel();
    }
});
```

#### 3.3 新增辅助函数

**findDrawingAtPoint(x, y)** - 在 `findDrawingAtPoint` 已存在于 kline_lightweight.html，检查并补充 `cycles.includes(currentPeriod)` 的过滤逻辑。

**showContextMenu / closeContextMenu** - 显示/关闭右键菜单

**ctxDeleteDrawing** - 右键删除
```javascript
function ctxDeleteDrawing() {
    if (ctxTargetId === null) return;
    const idx = drawings.findIndex(d => d.id === ctxTargetId);
    if (idx !== -1) {
        drawings[idx].series?.setData([]);
        drawings.splice(idx, 1);
    }
    closeContextMenu();
    renderDrawingsForPeriod();
}
```

**ctxShowProps / openPropsPanel / closePropsPanel** - 打开/关闭属性面板

**toggleCycleTag** - 切换周期标签选中状态

**setPropColor** - 设置属性面板颜色

**applyProps** - 应用属性修改
```javascript
function applyProps() {
    const id = window._currentPropsId;
    const d = drawings.find(d => d.id === id);
    if (!d) return;

    // 周期
    d.cycles = Array.from(document.querySelectorAll('#propCycles .period-tag.active'))
        .map(t => t.dataset.period);
    if (d.cycles.length === 0) d.cycles = [currentPeriod];

    // 颜色
    d.color = document.getElementById('propColorPicker').value;
    d.lineWidth = parseInt(document.getElementById('propLineWidth').value);

    // 应用到 series
    d.series?.applyOptions({ color: d.color, lineWidth: d.lineWidth });

    renderDrawingsForPeriod();
}
```

#### 3.4 修改 existing 函数

**findDrawingAtPoint(x, y)** - 在遍历 drawings 时加入 `if (!d.cycles.includes(currentPeriod)) return;` 过滤

**finishDrawing** - 在创建 drawings.push 时增加 `cycles: [currentPeriod], priceMin: null, priceMax: null`

**deselectAll** - 改为调用 `renderDrawingsForPeriod()` 而非清空

**selectDrawingById** - 选中后调用 `renderDrawingsForPeriod()`

#### 3.5 新增多周期渲染函数

**renderDrawingsForPeriod()** - 遍历 drawings，根据 `cycles` 过滤可见性，调用 `restoreDrawingData(d)` 或 `d.series.setData([])`
```javascript
function renderDrawingsForPeriod() {
    drawings.forEach(d => {
        if (!d.cycles.includes(currentPeriod)) {
            d.series?.setData([]);
            return;
        }
        restoreDrawingData(d);
    });
}
```

**restoreDrawingData(d)** - 恢复图形数据到 series（从现有跨周期恢复逻辑提取）

---

## 执行步骤

### Step 1: 添加 CSS（~80行）
在 `kline_lightweight.html` 的 `</style>` 标签前插入 CSS 块

### Step 2: 添加 HTML 模板（~70行）
在 `</body>` 前添加右键菜单和属性面板 HTML

### Step 3: 修改 drawings 数据结构
在 `finishDrawing()` 中 `drawings.push(...)` 增加 `cycles` 和 `priceMin/priceMax` 字段

### Step 4: 修改跨周期恢复
在 `restoreDrawings` 的 `savedDrawings.forEach` 中，给每个新建对象补充 `cycles: [period], priceMin: null, priceMax: null`

### Step 5: 添加右键菜单事件
在 initChart 末尾或 DOMContentLoaded 添加 contextmenu 和 click/ESC 监听

### Step 6: 添加属性面板函数
添加 `openPropsPanel, closePropsPanel, toggleCycleTag, setPropColor, applyProps, ctxDeleteDrawing, ctxShowProps` 等函数

### Step 7: 修改 findDrawingAtPoint
加入 `cycles.includes(currentPeriod)` 过滤

### Step 8: 添加 renderDrawingsForPeriod
新增函数，基于 cycles 过滤渲染

### Step 9: 修改 deselectAll 和 selectDrawingById
选中和取消选中时调用 `renderDrawingsForPeriod()`

### Step 10: 测试
1. Ctrl+F5 刷新
2. 画一条趋势线
3. 右键 → 属性设置
4. 勾选 5min、15min
5. 切换周期，观察线条是否按周期显示/隐藏
6. 检查控制台无报错

---

## 注意事项

1. **drawing_test.html 仍保留** — 独立测试页面，不删除
2. **周期获取** — `currentPeriod` 从 `document.getElementById('period').value` 读取
3. **现有跨周期逻辑保留** — `restoreDrawings` 函数逻辑不变，只补充字段
4. **不修改 kline 数据加载逻辑** — 只修改 drawings 相关

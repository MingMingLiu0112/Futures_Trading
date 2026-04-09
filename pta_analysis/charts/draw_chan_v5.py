"""PTA缠论分析 - 合并K线版（正确）"""
import akshare as ak, pandas as pd, warnings, matplotlib
warnings.filterwarnings('ignore')
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ── 数据 ──
df = ak.futures_zh_minute_sina(symbol='TA0', period='1')
df['datetime'] = pd.to_datetime(df['datetime'])
df = df.sort_values('datetime').tail(250).reset_index(drop=True)
df = df.reset_index(drop=True)
print(f"数据: {df['datetime'].iloc[0].strftime('%H:%M')} ~ {df['datetime'].iloc[-1].strftime('%H:%M')}  {len(df)}根K线")

# ── 包含关系处理 ──
def merge_bars(rows):
    result = []
    i = 0
    while i < len(rows):
        if not result:
            result.append(rows[i]); i += 1; continue
        h1, l1, c1 = result[-1]
        h2, l2, c2 = rows[i]
        if (h2 <= h1 and l2 >= l1) or (h2 >= h1 and l2 <= l1):
            if c2 >= c1:
                result[-1] = (max(h1,h2), max(l1,l2), c2)
            else:
                result[-1] = (min(h1,h2), min(l1,l2), c2)
            i += 1
        else:
            result.append(rows[i]); i += 1
    return result

# ── 分型识别 ──
def find_fx(bars):
    n = len(bars); fx = []
    for i in range(1, n-1):
        h0, l0, c0 = bars[i-1]
        h1, l1, c1 = bars[i]
        h2, l2, c2 = bars[i+1]
        if h1 > h0 and h1 > h2 and l1 > l0 and l1 > l2:
            if c0 < l1 or c2 < l1: fx.append(('D', i, h1))
        elif h1 < h0 and h1 < h2 and l1 < l0 and l1 < l2:
            if c0 > h1 or c2 > h1: fx.append(('G', i, l1))
    return fx

# ── 笔构建 ──
MIN_RANGE = 40

def build_bi(fx):
    if len(fx) < 2: return []
    result = []; i = 0
    while i < len(fx) - 1:
        t0, pos0, p0 = fx[i]
        if not result:
            direction = 'up' if t0 == 'G' else 'dn'
        else:
            direction = 'dn' if result[-1][0] == 'up' else 'up'
        target = 'D' if direction == 'up' else 'G'
        pole = None
        for b in reversed(result):
            if b[0] == direction:
                pole = b[4] if direction == 'up' else b[3]
                break
        j = i + 1; found = False
        while j < len(fx):
            t1, pos1, p1 = fx[j]
            if t1 != target: j += 1; continue
            gap = pos1 - pos0
            rng = p1 - p0 if direction == 'up' else p0 - p1
            if gap >= 4:
                result.append((direction, pos0, pos1, p0, p1, False))
                i = j + 1; found = True; break
            elif gap < 5 and pole is not None:
                can = (direction == 'up' and p1 > pole and rng >= MIN_RANGE) or \
                      (direction == 'dn' and p1 < pole and rng >= MIN_RANGE)
                if can:
                    result.append((direction, pos0, pos1, p0, p1, True))
                    i = j + 1; found = True; break
            if pole is not None:
                if direction == 'up' and p1 > pole: pole = p1
                elif direction == 'dn' and p1 < pole: pole = p1
            j += 1
        if not found: i += 1
    return result

# ── 主程序 ──
raw_rows = list(zip(df['high'], df['low'], df['close']))
merged = merge_bars(raw_rows)
fx = find_fx(merged)
bi = build_bi(fx)
print(f"原始{len(raw_rows)}根 → 合并{len(merged)}根 → 分型{len(fx)}个 → 笔{len(bi)}个")
for b in bi:
    d = '↑' if b[0]=='up' else '↓'
    sm = '[小]' if b[5] else ''
    print(f"  {d} {b[3]:.0f}→{b[4]:.0f} 幅度{abs(b[4]-b[3]):.0f}点 {sm}")

# ── 画图（合并K线） ──
plt.style.use('dark_background')
fig, ax = plt.subplots(figsize=(18, 8))

# 合并K线
for i, (h, l, c) in enumerate(merged):
    color = '#e54d4d' if c >= 6900 else '#4da64d'
    ax.plot([i, i], [l, h], color=color, linewidth=1.0)
    ax.add_patch(mpatches.Rectangle((i-0.4, l), 0.8, h-l, facecolor=color, edgecolor=color, linewidth=0.5))

# 笔（位置直接在合并K线坐标上）
for b in bi:
    d, sp, ep, pp0, pp1, small = b
    color = '#ff6b35' if d == 'up' else '#35a7ff'
    lw = 1.2 if small else 2.5
    ax.plot([sp, ep], [pp0, pp1], color=color, linewidth=lw, alpha=0.9)

# 分型
for t, pos, price in fx:
    color = '#ffff00' if t == 'D' else '#00ffcc'
    ax.scatter(pos, price, color=color, s=30, zorder=5)

ax.set_title(f"PTA 1分钟 缠论笔(v5合并K线) {df['datetime'].iloc[0].strftime('%H:%M')}~{df['datetime'].iloc[-1].strftime('%H:%M')}  笔:{len(bi)}", color='white', fontsize=13)
ax.set_xlabel('合并K线序号')
ax.set_ylabel('价格')
ax.grid(True, alpha=0.2)
ax.legend(handles=[
    mpatches.Patch(color='#ff6b35', label='上行笔'),
    mpatches.Patch(color='#35a7ff', label='下行笔'),
    mpatches.Patch(color='#ffff00', label='顶分型'),
    mpatches.Patch(color='#00ffcc', label='底分型'),
], loc='upper left')
plt.tight_layout()
plt.savefig('/home/admin/.openclaw/workspace/codeman/pta_analysis/chan_chart.png', dpi=120, bbox_inches='tight')
print(f"图片已保存")

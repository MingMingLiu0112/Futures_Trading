"""PTA缠论 - 参考russellchan92实现版"""
import akshare as ak, pandas as pd, warnings, matplotlib
warnings.filterwarnings('ignore')
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

df = ak.futures_zh_minute_sina(symbol='TA0', period='1')
df['datetime'] = pd.to_datetime(df['datetime'])
df = df.sort_values('datetime').tail(200).reset_index(drop=True)
df = df.reset_index(drop=True)
print(f"数据: {df['datetime'].iloc[0].strftime('%H:%M')} ~ {df['datetime'].iloc[-1].strftime('%H:%M')}  {len(df)}根")

# ── 包含关系处理（追踪位置） ──
def merge_bars_with_pos(df):
    """
    处理包含关系，同时记录每个merged bar对应的raw位置
    返回: merged_bars, pos_map
    pos_map[i] = merged bar i 在raw中的起始位置
    pos_end_map[i] = merged bar i 在raw中的结束位置
    """
    rows = list(zip(df['high'], df['low'], df['close']))
    result = []  # [(high, low, close, raw_start_pos)]
    i = 0
    while i < len(rows):
        h, l, c = rows[i]
        if not result:
            result.append((h, l, c, i))
            i += 1
            continue
        h1, l1, c1, start_pos = result[-1]
        if (h <= h1 and l >= l1) or (h >= h1 and l <= l1):
            if c >= c1:
                result[-1] = (max(h1,h), max(l1,l), c, start_pos)
            else:
                result[-1] = (min(h1,h), min(l1,l), c, start_pos)
            i += 1
        else:
            result.append((h, l, c, i))
            i += 1
    merged = [(r[0], r[1], r[2]) for r in result]
    pos_map = [r[3] for r in result]
    # 每个merged bar的结束位置 = 下一个merged bar的起始位置 - 1
    pos_end_map = []
    for i in range(len(result)):
        if i < len(result) - 1:
            pos_end_map.append(result[i+1][3] - 1)
        else:
            pos_end_map.append(len(df) - 1)  # 最后一个bar到raw最后
    return merged, pos_map, pos_end_map

# ── 分型识别（只验证右侧） ──
def find_fx(bars, pos_end_map):
    """
    顶分型：中间K线高低都最高，且左或右侧K线收盘在中间K线最低下方
    底分型：中间K线高低都最低，且左或右侧K线收盘在中间K线最高上方
    位置用raw K线条数（pos_end_map[i] = merged bar i在raw中的结束位置）
    """
    n = len(bars)
    fx = []
    for i in range(1, n-1):
        h0, l0, c0 = bars[i-1]
        h1, l1, c1 = bars[i]
        h2, l2, c2 = bars[i+1]
        # 顶分型
        if h1 > h0 and h1 > h2 and l1 > l0 and l1 > l2:
            if c0 < l1 or c2 < l1:
                raw_pos = pos_end_map[i]  # 用merged bar结束位置作为分型在raw中的位置
                fx.append(('D', raw_pos, h1, l1))
        # 底分型
        elif h1 < h0 and h1 < h2 and l1 < l0 and l1 < l2:
            if c0 > h1 or c2 > h1:
                raw_pos = pos_end_map[i]
                fx.append(('G', raw_pos, h1, l1))
    return fx

# ── 笔构建 ──
MIN_RANGE = 40

def build_bi(fx):
    """
    规则：
    1. 第一笔方向由第一个有效分型决定（底分型→向上，顶分型→向下）
    2. 方向交替找下一分型成笔
    3. gap>=5根无包含K线 → 成笔
    4. gap<5：突破同方向前极（上一笔终点那根K线的位置） → 小笔
    """
    if len(fx) < 2:
        return []

    result = []
    i = 0
    while i < len(fx) - 1:
        t0, pos0, h0, l0 = fx[i]
        # 第一笔方向由分型决定
        if not result:
            direction = 'up' if t0 == 'G' else 'dn'
        else:
            direction = 'dn' if result[-1][0] == 'up' else 'up'

        target = 'D' if direction == 'up' else 'G'

        # 同方向前极：上一笔终点那根K线在本笔方向上的极值位置
        prev_pole = None
        for b in reversed(result):
            if b[0] == direction:
                prev_pole = b[2]  # b[2] = 上一笔终点在merged中的位置
                break

        j = i + 1
        found = False
        while j < len(fx):
            t1, pos1, h1, l1 = fx[j]
            if t1 != target:
                j += 1; continue

            gap = pos1 - pos0

            if gap >= 4:
                # 成一笔
                result.append((direction, pos0, pos1, h0, l0, False))
                i = j + 1; found = True; break
            elif gap < 5 and prev_pole is not None:
                can_save = (direction == 'up' and pos1 > prev_pole) or \
                           (direction == 'dn' and pos1 < prev_pole)
                if can_save:
                    result.append((direction, pos0, pos1, h0, l0, True))
                    i = j + 1; found = True; break

            j += 1

        if not found:
            i += 1

    return result

# ── 主程序 ──
rows = list(zip(df['high'], df['low'], df['close']))
merged = merge_bars(rows)
fx = find_fx(merged)
bi = build_bi(fx)

print(f"原始{len(rows)}根 → 合并{len(merged)}根 → 分型{len(fx)}个 → 笔{len(bi)}个")
for b in bi:
    d = '↑' if b[0]=='up' else '↓'
    sm = '[小]' if b[7] else ''
    print(f"  {d} pos{b[1]}→{b[2]} 价{b[3]:.0f}→{b[4]:.0f} {sm}")

# ── 画图 ──
plt.style.use('dark_background')
fig, ax = plt.subplots(figsize=(18, 8))

for i, (h, l, c) in enumerate(merged):
    color = '#e54d4d' if c >= 6900 else '#4da64d'
    ax.plot([i, i], [l, h], color=color, linewidth=1.0)
    ax.add_patch(mpatches.Rectangle((i-0.4, l), 0.8, h-l, facecolor=color, edgecolor=color, linewidth=0.5))

for b in bi:
    d, sp, ep, hp, lp, pole_h, pole_l, small = b
    color = '#ff6b35' if d == 'up' else '#35a7ff'
    lw = 1.2 if small else 2.5
    ax.plot([sp, ep], [hp, lp], color=color, linewidth=lw, alpha=0.9)

for f in fx:
    t, pos, h, l = f
    color = '#ffff00' if t == 'D' else '#00ffcc'
    ax.scatter(pos, h if t == 'D' else l, color=color, s=30, zorder=5)

ax.set_title(f"PTA 1分钟 缠论笔(v6) {df['datetime'].iloc[0].strftime('%H:%M')}~{df['datetime'].iloc[-1].strftime('%H:%M')}  笔:{len(bi)}", color='white', fontsize=13)
ax.set_xlabel('合并K线序号')
ax.set_ylabel('价格')
ax.grid(True, alpha=0.2)
ax.legend(handles=[
    mpatches.Patch(color='#ff6b35', label='上行笔'),
    mpatches.Patch(color='#35a7ff', label='下行笔'),
], loc='upper left')
plt.tight_layout()
plt.savefig('/home/admin/.openclaw/workspace/codeman/pta_analysis/chan_chart.png', dpi=120, bbox_inches='tight')
print(f"图片已保存")

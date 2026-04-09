"""缠论笔构建v3 - 最终修正版"""
import akshare as ak, pandas as pd, warnings, matplotlib
warnings.filterwarnings('ignore')
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ── 数据 ──
df = ak.futures_zh_minute_sina(symbol='TA0', period='1')
df['datetime'] = pd.to_datetime(df['datetime'])
df = df.sort_values('datetime').tail(200).reset_index(drop=True)

# ── 包含关系处理 ──
def process_baohan(klines_df):
    rows = klines_df[['high', 'low']].values.tolist()
    result = []
    i = 0
    while i < len(rows):
        if len(result) == 0:
            result.append(rows[i]); i += 1; continue
        h1, l1 = result[-1]; h2, l2 = rows[i]
        if not ((h2 <= h1 and l2 >= l1) or (h2 >= h1 and l2 <= l1)):
            result.append(rows[i]); i += 1; continue
        if l2 > l1:
            result[-1] = (max(h1,h2), max(l1,l2))
        else:
            result[-1] = (min(h1,h2), min(l1,l2))
        i += 1
    return result

# ── 分型识别 ──
def find_fenxing(klist):
    n = len(klist); fen = []
    for i in range(1, n-1):
        hp, lp = klist[i-1]; hc, lc = klist[i]; hn, ln = klist[i+1]
        if hc > hp and hc > hn and lc > lp and lc > ln:
            fen.append(('D', i, hc))
        elif hc < hp and hc < hn and lc < lp and lc < ln:
            fen.append(('G', i, lc))
    return fen

# ── 修正版笔构建 ──
MIN_RANGE = 40  # 40点阈值

def build_bi_v3(fen_list):
    """
    规则：
    1. 第一要件（主）：相邻底+顶（或顶+底），间隔>=4根K线 → 直接成一笔
    2. 第二要件（例外）：gap<4 + 突破同方向前极 + 幅度>=阈值 → 小笔
    3. 第三要件（否定）：gap<4 + 不突破前极 → 不是一笔，从下一个分型继续找（方向不变）
    """
    if len(fen_list) < 2:
        return []

    result = []
    i = 0

    while i < len(fen_list) - 1:
        t_start, idx_start, price_start = fen_list[i]
        direction = 'up' if t_start == 'G' else 'dn'
        target_type = 'D' if direction == 'up' else 'G'

        # 同方向前极点的极值
        def get_prev_pole(dir):
            for b in reversed(result):
                if b[0] == dir:
                    return b[4] if dir == 'up' else b[3]
            return None

        prev_pole = get_prev_pole(direction)
        j = i + 1
        found = False

        while j < len(fen_list):
            t_check, idx_check, price_check = fen_list[j]
            if t_check != target_type:
                j += 1
                continue

            gap = idx_check - idx_start

            if gap >= 4:
                # 要件一：直接成一笔
                result.append((direction, idx_start, idx_check, price_start, price_check, False))
                i = idx_check
                found = True
                break
            else:
                # 要件二/三：检查能否救
                rng = price_check - price_start if direction == 'up' else price_start - price_check
                can_save = False
                if prev_pole is not None:
                    if direction == 'up' and price_check > prev_pole and rng >= MIN_RANGE:
                        can_save = True
                    elif direction == 'dn' and price_check < prev_pole and rng >= MIN_RANGE:
                        can_save = True

                if can_save:
                    # 要件二：成小笔
                    result.append((direction, idx_start, idx_check, price_start, price_check, True))
                    i = idx_check
                    found = True
                    break
                else:
                    # 要件三：否定，不成一笔，prev_pole更新，继续找
                    if prev_pole is not None:
                        if direction == 'up' and price_check > prev_pole:
                            prev_pole = price_check
                        elif direction == 'dn' and price_check < prev_pole:
                            prev_pole = price_check
                    j += 1
                    continue

        if not found:
            i += 1

    return result

# ── 主程序 ──
proc = process_baohan(df)
fen = find_fenxing(proc)
bi_list = build_bi_v3(fen)

print(f"数据: {df['datetime'].iloc[0]} ~ {df['datetime'].iloc[-1]}")
print(f"原始K线: {len(df)}根 | 处理后: {len(proc)}根 | 分型: {len(fen)}个 | 笔: {len(bi_list)}个")
print(f"笔阈值: {MIN_RANGE}点")
print()
for bi in bi_list:
    d = '↑' if bi[0]=='up' else '↓'
    sm = '[小]' if bi[5] else '    '
    print(f"  {d} {bi[3]:.0f}→{bi[4]:.0f} 幅度{abs(bi[4]-bi[3]):.0f}点 {sm}")

# ── 画图 ──
plt.style.use('dark_background')
fig, ax = plt.subplots(figsize=(18, 8))

for idx, row in df.iterrows():
    color = '#e54d4d' if row['close'] >= row['open'] else '#4da64d'
    ax.plot([idx, idx], [row['low'], row['high']], color=color, linewidth=0.8)
    body_bottom = min(row['open'], row['close'])
    body_top = max(row['open'], row['close'])
    ax.add_patch(mpatches.Rectangle((idx-0.4, body_bottom), 0.8, body_top-body_bottom,
                                    facecolor=color, edgecolor=color, linewidth=0.5))

for bi in bi_list:
    d, s, e, ps, pe, small = bi
    color = '#ff6b35' if d == 'up' else '#35a7ff'
    lw = 1.2 if small else 2.5
    ax.plot([s, e], [ps, pe], color=color, linewidth=lw, alpha=0.9)

for f in fen:
    t, idx, price = f
    color = '#ffff00' if t == 'D' else '#00ffcc'
    ax.scatter(idx, price, color=color, s=25, zorder=5)

ax.set_title(f"PTA 1分钟K线+缠论笔(v3修正版)  {df['datetime'].iloc[0].strftime('%Y-%m-%d %H:%M')} ~ {df['datetime'].iloc[-1].strftime('%H:%M')}", color='white', fontsize=13)
ax.set_xlabel('K线序号', color='white')
ax.set_ylabel('价格', color='white')
ax.grid(True, alpha=0.2)
up_patch = mpatches.Patch(color='#ff6b35', label='上行笔')
dn_patch = mpatches.Patch(color='#35a7ff', label='下行笔')
ax.legend(handles=[up_patch, dn_patch], loc='upper left')

plt.tight_layout()
plt.savefig('/home/admin/.openclaw/workspace/codeman/pta_analysis/chan_chart_v3.png', dpi=120, bbox_inches='tight')
print(f"\n图片已保存 chan_chart_v3.png")

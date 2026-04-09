"""缠论笔构建最终版 + 画图"""
import akshare as ak, pandas as pd, warnings, matplotlib
warnings.filterwarnings('ignore')
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

df = ak.futures_zh_minute_sina(symbol='TA0', period='1')
df['datetime'] = pd.to_datetime(df['datetime'])
df = df.sort_values('datetime').tail(200).reset_index(drop=True)

def process_baohan(klines_df):
    rows = klines_df[['high', 'low', 'close']].values.tolist()
    result = []
    i = 0
    while i < len(rows):
        if len(result) == 0:
            result.append(rows[i]); i += 1; continue
        h1, l1, c1 = result[-1]; h2, l2, c2 = rows[i]
        if not ((h2 <= h1 and l2 >= l1) or (h2 >= h1 and l2 <= l1)):
            result.append(rows[i]); i += 1; continue
        if l2 > l1:
            result[-1] = (max(h1,h2), max(l1,l2), c2)
        else:
            result[-1] = (min(h1,h2), min(l1,l2), c2)
        i += 1
    return result

def find_fenxing(klist, left=1, right=1):
    n = len(klist); fen = []
    for i in range(left, n - right):
        hp, lp = klist[i-left][:2]; hc, lc = klist[i][:2]; hn, ln = klist[i+right][:2]
        if hc > hp and hc > hn and lc > lp and lc > ln:
            if any(klist[i+j][2] < lc for j in range(-left, right+1) if j != 0):
                fen.append(('D', i, hc))
        elif hc < hp and hc < hn and lc < lp and lc < ln:
            if any(klist[i+j][2] > hc for j in range(-left, right+1) if j != 0):
                fen.append(('G', i, lc))
    return fen

MIN_RANGE = 40
proc = process_baohan(df)
fen = find_fenxing(proc)

result = []
i = 0
while i < len(fen) - 1:
    t_start, idx_start, price_start = fen[i]
    if not result:
        direction = 'up' if t_start == 'G' else 'dn'
    else:
        direction = 'dn' if result[-1][0] == 'up' else 'up'
    target_type = 'D' if direction == 'up' else 'G'
    prev_pole = None
    for b in reversed(result):
        if b[0] == direction:
            prev_pole = b[4] if direction == 'up' else b[3]
            break
    j = i + 1; found = False
    while j < len(fen):
        t_check, idx_check, price_check = fen[j]
        if t_check != target_type:
            j += 1; continue
        gap = idx_check - idx_start
        rng = price_check - price_start if direction == 'up' else price_start - price_check
        if gap >= 4:
            result.append((direction, idx_start, idx_check, price_start, price_check, False))
            i = j + 1; found = True; break
        elif gap < 4 and prev_pole is not None:
            can_save = (direction == 'up' and price_check > prev_pole and rng >= MIN_RANGE) or \
                       (direction == 'dn' and price_check < prev_pole and rng >= MIN_RANGE)
            if can_save:
                result.append((direction, idx_start, idx_check, price_start, price_check, True))
                i = j + 1; found = True; break
        if prev_pole is not None:
            if direction == 'up' and price_check > prev_pole:
                prev_pole = price_check
            elif direction == 'dn' and price_check < prev_pole:
                prev_pole = price_check
        j += 1
    if not found:
        i += 1

print(f"数据: {df['datetime'].iloc[0]} ~ {df['datetime'].iloc[-1]}")
print(f"K线{len(df)}根 → 处理后{len(proc)}根 → 分型{len(fen)}个 → 笔{len(result)}个")
print()
for bi in result:
    d = '↑' if bi[0]=='up' else '↓'
    sm = '[小]' if bi[5] else ''
    print(f"  {d} {bi[3]:.0f}→{bi[4]:.0f} 幅度{abs(bi[4]-bi[3]):.0f}点 {sm}")

plt.style.use('dark_background')
fig, ax = plt.subplots(figsize=(18, 8))

# 用处理后的K线画蜡烛图（合并后的K线才是缠论处理的对象）
proc_df = pd.DataFrame(proc, columns=['high', 'low', 'close'])
proc_df['open'] = proc_df['close']  # 合并K线开盘价用收盘代替（简化）

for idx in range(len(proc_df)):
    row = proc_df.iloc[idx]
    color = '#e54d4d' if row['close'] >= row['open'] else '#4da64d'
    ax.plot([idx, idx], [row['low'], row['high']], color=color, linewidth=1.0)
    body_bottom = min(row['open'], row['close'])
    body_top = max(row['open'], row['close'])
    ax.add_patch(mpatches.Rectangle((idx-0.4, body_bottom), 0.8, body_top-body_bottom,
                                    facecolor=color, edgecolor=color, linewidth=0.5))

for bi in result:
    d, s, e, ps, pe, small = bi
    color = '#ff6b35' if d == 'up' else '#35a7ff'
    lw = 1.2 if small else 2.5
    ax.plot([s, e], [ps, pe], color=color, linewidth=lw, alpha=0.9)

for f in fen:
    t, idx_fen, price = f
    color = '#ffff00' if t == 'D' else '#00ffcc'
    ax.scatter(idx_fen, price, color=color, s=30, zorder=5)
ax.set_title(f"PTA 1分钟K线+缠论笔(修正版)  {df['datetime'].iloc[0].strftime('%Y-%m-%d %H:%M')} ~ {df['datetime'].iloc[-1].strftime('%H:%M')}  笔:{len(result)}", color='white', fontsize=13)
ax.set_xlabel('K线序号', color='white')
ax.set_ylabel('价格', color='white')
ax.grid(True, alpha=0.2)
up_patch = mpatches.Patch(color='#ff6b35', label='上行笔')
dn_patch = mpatches.Patch(color='#35a7ff', label='下行笔')
ax.legend(handles=[up_patch, dn_patch], loc='upper left')
plt.tight_layout()
plt.savefig('/home/admin/.openclaw/workspace/codeman/pta_analysis/chan_chart.png', dpi=120, bbox_inches='tight')
print(f"\n图片已保存 chan_chart.png")

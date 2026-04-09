"""缠论笔图 - 位置对齐版"""
import akshare as ak, pandas as pd, warnings, matplotlib
warnings.filterwarnings('ignore')
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ── 数据 ──
df = ak.futures_zh_minute_sina(symbol='TA0', period='1')
df['datetime'] = pd.to_datetime(df['datetime'])
df = df.sort_values('datetime').tail(200).reset_index(drop=True)
df = df.reset_index(drop=True)  # 0起索引

# ── 包含关系处理 ──
def process_baohan(df):
    """处理包含关系，返回[(raw_idx, high, low, close)]"""
    rows = df[['high', 'low', 'close']].values.tolist()
    result = []
    i = 0
    while i < len(rows):
        if len(result) == 0:
            result.append((i, rows[i][0], rows[i][1], rows[i][2]))
            i += 1; continue
        h1, l1 = result[-1][1], result[-1][2]
        h2, l2 = rows[i][0], rows[i][1]
        if not ((h2 <= h1 and l2 >= l1) or (h2 >= h1 and l2 <= l1)):
            result.append((i, rows[i][0], rows[i][1], rows[i][2]))
            i += 1; continue
        if l2 > l1:
            result[-1] = (result[-1][0], max(h1,h2), max(l1,l2), rows[i][2])
        else:
            result[-1] = (result[-1][0], min(h1,h2), min(l1,l2), rows[i][2])
        i += 1
    return result  # [(raw_idx, high, low, close), ...]

# ── 分型识别 ──
def find_fenxing(proc):
    """proc: [(raw_idx, high, low, close), ...]"""
    n = len(proc)
    fen = []
    for i in range(1, n-1):
        hp, lp = proc[i-1][1], proc[i-1][2]
        hc, lc = proc[i][1], proc[i][2]
        hn, ln = proc[i+1][1], proc[i+1][2]
        # 顶分型
        if hc > hp and hc > hn and lc > lp and lc > ln:
            if any(proc[i+j][3] < lc for j in [-1, 1] if 0 <= i+j < n):
                fen.append(('D', proc[i][0], hc))
        # 底分型
        elif hc < hp and hc < hn and lc < lp and lc < ln:
            if any(proc[i+j][3] > hc for j in [-1, 1] if 0 <= i+j < n):
                fen.append(('G', proc[i][0], lc))
    return fen  # [(type, raw_idx, price), ...]

# ── 笔构建 ──
MIN_RANGE = 40
def build_bi(fen):
    if len(fen) < 2: return []
    result = []; i = 0
    while i < len(fen) - 1:
        t_start, raw_start, p_start = fen[i]
        direction = 'up' if t_start == 'G' else 'dn'
        target = 'D' if direction == 'up' else 'G'
        prev_pole = None
        for b in reversed(result):
            if b[0] == direction:
                prev_pole = b[4] if direction == 'up' else b[3]
                break
        j = i + 1; found = False
        while j < len(fen):
            t2, raw2, p2 = fen[j]
            if t2 != target: j += 1; continue
            gap = raw2 - raw_start
            rng = p2 - p_start if direction == 'up' else p_start - p2
            if gap >= 4:
                result.append((direction, raw_start, raw2, p_start, p2, False))
                i = j + 1; found = True; break
            elif gap < 4 and prev_pole is not None:
                can = (direction == 'up' and p2 > prev_pole and rng >= MIN_RANGE) or \
                      (direction == 'dn' and p2 < prev_pole and rng >= MIN_RANGE)
                if can:
                    result.append((direction, raw_start, raw2, p_start, p2, True))
                    i = j + 1; found = True; break
            if prev_pole is not None:
                if direction == 'up' and p2 > prev_pole: prev_pole = p2
                elif direction == 'dn' and p2 < prev_pole: prev_pole = p2
            j += 1
        if not found: i += 1
    return result  # [(方向, raw_start, raw_end, p_start, p_end, is_small), ...]

# ── 主程序 ──
proc = process_baohan(df)
fen = find_fenxing(proc)
bi_list = build_bi(fen)

print(f"原始{df.shape[0]}根 → 处理后{len(proc)}根 → 分型{len(fen)}个 → 笔{len(bi_list)}个")
for bi in bi_list:
    d = '↑' if bi[0]=='up' else '↓'
    sm = '[小]' if bi[5] else ''
    print(f"  {d} {bi[3]:.0f}→{bi[4]:.0f} 幅度{abs(bi[4]-bi[3]):.0f}点 {sm}")

# ── 画图 ──
plt.style.use('dark_background')
fig, ax = plt.subplots(figsize=(18, 8))

# 建立raw_idx → proc_position的映射
raw_to_proc_pos = {ri: p for p, (ri, *_) in enumerate(proc)}

# 画K线（processed bar）
for pos, (raw_idx, high, low, close) in enumerate(proc):
    color = '#e54d4d' if close >= 6800 else '#4da64d'
    ax.plot([pos, pos], [low, high], color=color, linewidth=1.0)
    ax.add_patch(mpatches.Rectangle((pos-0.4, low), 0.8, high-low,
                                    facecolor=color, edgecolor=color, linewidth=0.5))

# 画笔（用proc位置）
for bi in bi_list:
    d, rs, re, ps, pe, small = bi
    sp = raw_to_proc_pos.get(rs, 0)
    ep = raw_to_proc_pos.get(re, 0)
    color = '#ff6b35' if d == 'up' else '#35a7ff'
    lw = 1.2 if small else 2.5
    ax.plot([sp, ep], [ps, pe], color=color, linewidth=lw, alpha=0.9)

# 画分型（用proc位置）
for f in fen:
    t, raw_idx, price = f
    pos = raw_to_proc_pos.get(raw_idx, raw_idx)
    color = '#ffff00' if t == 'D' else '#00ffcc'
    ax.scatter(pos, price, color=color, s=30, zorder=5)

ax.set_title(f"PTA 1分钟 缠论笔 {df['datetime'].iloc[0].strftime('%m-%d %H:%M')}~{df['datetime'].iloc[-1].strftime('%H:%M')}  笔:{len(bi_list)}", color='white', fontsize=13)
ax.set_xlabel('处理后K线位置', color='white')
ax.set_ylabel('价格', color='white')
ax.grid(True, alpha=0.2)
ax.legend(handles=[
    mpatches.Patch(color='#ff6b35', label='上行笔'),
    mpatches.Patch(color='#35a7ff', label='下行笔'),
    mpatches.Patch(color='#ffff00', label='顶分型'),
    mpatches.Patch(color='#00ffcc', label='底分型'),
], loc='upper left')
plt.tight_layout()
plt.savefig('/home/admin/.openclaw/workspace/codeman/pta_analysis/chan_chart.png', dpi=120, bbox_inches='tight')
print(f"\n图片已保存")

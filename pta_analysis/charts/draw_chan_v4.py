"""缠论笔 - 修正包含关系处理版"""
import akshare as ak, pandas as pd, warnings, matplotlib
warnings.filterwarnings('ignore')
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ── 数据 ──
df = ak.futures_zh_minute_sina(symbol='TA0', period='1')
df['datetime'] = pd.to_datetime(df['datetime'])
df = df.sort_values('datetime').tail(200).reset_index(drop=True)
df = df.reset_index(drop=True)

# ── 包含关系处理（修正版：比较result[-1]而非rows[i]） ──
def process_baohan(df):
    """
    上升趋势（当前low>前low）：高高原则 max(high) + max(low)
    下降趋势（当前high<前high）：低低原则 min(high) + min(low)
    """
    rows = df[['high', 'low', 'close']].values.tolist()
    result = []  # [(raw_pos, high, low, close), ...]
    i = 0
    while i < len(rows):
        raw_pos = i
        h2, l2, c2 = rows[i]

        if not result:
            result.append((raw_pos, h2, l2, c2))
            i += 1
            continue

        h1, l1 = result[-1][1], result[-1][2]

        # 判断包含：当前K在前一K范围内，或前一K在当前K范围内
        contained = (h2 <= h1 and l2 >= l1) or (h2 >= h1 and l2 <= l1)

        if not contained:
            result.append((raw_pos, h2, l2, c2))
            i += 1
            continue

        # 包含：用result[-1]的趋势方向判断（不是rows[i]）
        # 趋势：前一合并K线是升还是降？
        prev_close = result[-1][3]
        curr_close = c2
        if curr_close >= prev_close:
            # 升趋势 → 高高原则
            new_h = max(h1, h2)
            new_l = max(l1, l2)
        else:
            # 降趋势 → 低低原则
            new_h = min(h1, h2)
            new_l = min(l1, l2)

        result[-1] = (result[-1][0], new_h, new_l, curr_close)
        i += 1

    return result  # [(raw_pos, high, low, close), ...]

# ── 分型识别 ──
def find_fenxing(proc):
    """
    proc: [(raw_pos, high, low, close), ...]
    顶分型：中间K线高、低都分别高于左右两根，且停顿验证（收盘跌破中间K线最低）
    底分型：中间K线高、低都分别低于左右两根，且停顿验证（收盘涨过中间K线最高）
    """
    n = len(proc)
    fen = []
    for i in range(1, n - 1):
        hp, lp = proc[i-1][1], proc[i-1][2]
        hc, lc = proc[i][1], proc[i][2]
        hn, ln = proc[i+1][1], proc[i+1][2]

        # 顶分型
        if hc > hp and hc > hn and lc > lp and lc > ln:
            # 停顿验证：左或右有收盘 < 中间最低点
            if (proc[i-1][3] < lc) or (proc[i+1][3] < lc):
                fen.append(('D', proc[i][0], hc))

        # 底分型
        elif hc < hp and hc < hn and lc < lp and lc < ln:
            # 停顿验证：左或右有收盘 > 中间最高点
            if (proc[i-1][3] > hc) or (proc[i+1][3] > hc):
                fen.append(('G', proc[i][0], lc))

    return fen  # [(type, raw_pos, price), ...]

# ── 笔构建 ──
MIN_RANGE = 40

def build_bi(fen):
    """
    方向交替：上笔后找下笔，下笔后找上笔
    要件一：gap>=4根K线 → 成笔
    要件二：gap<4 + 突破同方向前极 + 幅度>=阈值 → 小笔
    """
    if len(fen) < 2:
        return []

    result = []
    i = 0
    while i < len(fen) - 1:
        t_start, raw_start, p_start = fen[i]

        # 方向交替
        if not result:
            direction = 'up' if t_start == 'G' else 'dn'
        else:
            direction = 'dn' if result[-1][0] == 'up' else 'up'

        target = 'D' if direction == 'up' else 'G'

        # 同方向前极点
        prev_pole = None
        for b in reversed(result):
            if b[0] == direction:
                prev_pole = b[4] if direction == 'up' else b[3]
                break

        j = i + 1
        found = False
        while j < len(fen):
            t2, raw2, p2 = fen[j]
            if t2 != target:
                j += 1; continue

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

            # 更新前极
            if prev_pole is not None:
                if direction == 'up' and p2 > prev_pole:
                    prev_pole = p2
                elif direction == 'dn' and p2 < prev_pole:
                    prev_pole = p2
            j += 1

        if not found:
            i += 1

    return result

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

raw_to_proc = {ri: p for p, (ri, *_) in enumerate(proc)}

for pos, (raw_pos, high, low, close) in enumerate(proc):
    color = '#e54d4d' if close >= 6800 else '#4da64d'
    ax.plot([pos, pos], [low, high], color=color, linewidth=1.0)
    ax.add_patch(mpatches.Rectangle((pos-0.4, low), 0.8, high-low,
                                    facecolor=color, edgecolor=color, linewidth=0.5))

for bi in bi_list:
    d, rs, re, ps, pe, small = bi
    sp = raw_to_proc.get(rs, 0)
    ep = raw_to_proc.get(re, 0)
    color = '#ff6b35' if d == 'up' else '#35a7ff'
    lw = 1.2 if small else 2.5
    ax.plot([sp, ep], [ps, pe], color=color, linewidth=lw, alpha=0.9)

for f in fen:
    t, raw_pos, price = f
    pos = raw_to_proc.get(raw_pos, raw_pos)
    color = '#ffff00' if t == 'D' else '#00ffcc'
    ax.scatter(pos, price, color=color, s=30, zorder=5)

ax.set_title(f"PTA 1分钟 缠论笔(v4修正) {df['datetime'].iloc[0].strftime('%m-%d %H:%M')}~{df['datetime'].iloc[-1].strftime('%H:%M')}  笔:{len(bi_list)}", color='white', fontsize=13)
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
print(f"图片已保存")

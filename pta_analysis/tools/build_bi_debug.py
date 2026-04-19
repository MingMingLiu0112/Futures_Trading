"""缠论笔构建 - 调试版（无重用bug）"""
import akshare as ak, pandas as pd, warnings
warnings.filterwarnings('ignore')

df = ak.futures_zh_minute_sina(symbol='TA0', period='1')
df['datetime'] = pd.to_datetime(df['datetime'])
df = df.sort_values('datetime').tail(200).reset_index(drop=True)

def process_baohan(klines_df):
    """处理包含关系，返回[(high, low, close), ...]"""
    rows = klines_df[['high', 'low', 'close']].values.tolist()
    result = []
    i = 0
    while i < len(rows):
        if len(result) == 0:
            result.append(rows[i]); i += 1; continue
        h1, l1, c1 = result[-1]
        h2, l2, c2 = rows[i]
        if not ((h2 <= h1 and l2 >= l1) or (h2 >= h1 and l2 <= l1)):
            result.append(rows[i]); i += 1; continue
        if l2 > l1:
            result[-1] = (max(h1,h2), max(l1,l2), c2)
        else:
            result[-1] = (min(h1,h2), min(l1,l2), c2)
        i += 1
    return result

def find_fenxing(klist, left=1, right=1):
    """
    识别分型（顶底分型停顿验证）
    顶分型：中间K线最高+最低都高于左右两根，且至少一根相邻K线收盘跌破中间K线最低点
    底分型：中间K线最高+最低都低于左右两根，且至少一根相邻K线收盘涨过中间K线最高点
    klist: [(high, low, close), ...]
    """
    n = len(klist)
    fen = []

    for i in range(left, n - right):
        hp, lp, cp = klist[i-left]
        hc, lc, cc = klist[i]
        hn, ln, cn = klist[i+right]

        # 顶分型几何条件
        if hc > hp and hc > hn and lc > lp and lc > ln:
            # 停顿验证：左侧或右侧至少一根K线收盘 < 中间K线最低点
            valid = False
            for offset in range(-left, right + 1):
                if offset == 0:
                    continue
                test_close = klist[i + offset][2]  # close
                if test_close < lc:
                    valid = True
                    break
            if valid:
                fen.append(('D', i, hc))

        # 底分型几何条件
        elif hc < hp and hc < hn and lc < lp and lc < ln:
            # 停顿验证：左侧或右侧至少一根K线收盘 > 中间K线最高点
            valid = False
            for offset in range(-left, right + 1):
                if offset == 0:
                    continue
                test_close = klist[i + offset][2]  # close
                if test_close > hc:
                    valid = True
                    break
            if valid:
                fen.append(('G', i, lc))

    return fen

MIN_RANGE = 40
proc = process_baohan(df)
fen = find_fenxing(proc)

# 核心算法：不用i=j复用端点，而是跳过端点后的下一个fen
result = []
i = 0
while i < len(fen) - 1:
    t_start, idx_start, price_start = fen[i]
    direction = 'up' if t_start == 'G' else 'dn'
    target_type = 'D' if direction == 'up' else 'G'
    
    # 同方向前极点
    prev_pole = None
    for b in reversed(result):
        if b[0] == direction:
            prev_pole = b[4] if direction == 'up' else b[3]
            break
    
    j = i + 1
    found = False
    while j < len(fen):
        t_check, idx_check, price_check = fen[j]
        if t_check != target_type:
            j += 1; continue
        gap = idx_check - idx_start
        rng = price_check - price_start if direction == 'up' else price_start - price_check
        
        if gap >= 4:
            result.append((direction, idx_start, idx_check, price_start, price_check, False))
            i = j + 1  # 跳到端点后的下一个fen，不重用端点
            found = True; break
        elif prev_pole is not None:
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
print(f"K线{len(df)}根 处理后{len(proc)}根 分型{len(fen)}个 笔{len(result)}个")
print()
for bi in result:
    d = '↑' if bi[0]=='up' else '↓'
    sm = '[小]' if bi[5] else '    '
    print(f"  {d} {bi[3]:.0f}→{bi[4]:.0f} 幅度{abs(bi[4]-bi[3]):.0f}点 {sm}")

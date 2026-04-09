"""缠论模块：包含关系处理 + 顶底分型识别"""
import pandas as pd
import numpy as np
import akshare as ak
import warnings

warnings.filterwarnings('ignore')

# ─────────────────────────────────────────
# 数据获取
# ─────────────────────────────────────────

def get_raw_klines():
    """获取1分钟原始K线"""
    df = ak.futures_zh_minute_sina(symbol='TA0', period='1')
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.sort_values('datetime').reset_index(drop=True)
    # 只取最近200根K线
    return df.tail(200).reset_index(drop=True)

# ─────────────────────────────────────────
# 第一步：包含关系处理
# ─────────────────────────────────────────

def process_baohan(klines):
    """
    处理K线包含关系
    上升包含：取高高原则 max(high) + max(low)
    下降包含：取低低原则 min(high) + min(low)
    返回处理后的K线列表 [(high, low), ...]
    """
    k = klines[['high', 'low']].values.tolist()
    result = []

    i = 0
    while i < len(k):
        if len(result) == 0:
            result.append(k[i])
            i += 1
            continue

        h1, l1 = result[-1]
        h2, l2 = k[i]

        # 判断是否存在包含关系
        # 包含：h2在[h1,l1]内部 或 l2在[h1,l1]内部（同向内外）
        hasContain = (h2 <= h1 and l2 >= l1) or (h2 >= h1 and l2 <= l1)

        if not hasContain:
            result.append(k[i])
            i += 1
            continue

        # 确认方向：看前一根处理后K线与当前K线的高低关系
        # 如果前一根收盘 >= 前一根开盘 → 上升趋势
        prev_idx = len(klines) - len(result)
        # 用result里最后一根对应的原始K线判断
        if len(result) >= 2:
            # 取result中倒数第二根和倒数第一根的收盘价判断趋势
            # 需要知道原始K线的开闭口
            # 简化：用result中最后一根的原始对应关系
            pass

        # 判断趋势：用result中最后一根的high/low
        # 上升趋势：前一k的高点<当前k的高点
        # 下降趋势：前一k的高点>当前k的高点
        if h1 < h2:
            # 上升中包含 → 高高原则
            new_h = max(h1, h2)
            new_l = max(l1, l2)
        else:
            # 下降中包含 → 低低原则
            new_h = min(h1, h2)
            new_l = min(l1, l2)

        result[-1] = (new_h, new_l)
        i += 1

    return result

def process_baohan_v2(klines_df):
    """
    处理K线包含关系（只用最高价最低价）
    上升趋势（最低价抬升）：当前low > 前一low → 高高原则 max(high) + max(low)
    下降趋势（最高价下降）：当前high < 前一high → 低低原则 min(high) + min(low)
    """
    rows = klines_df[['high', 'low']].values.tolist()
    result = []

    i = 0
    while i < len(rows):
        if len(result) == 0:
            result.append(rows[i])
            i += 1
            continue

        h1, l1 = result[-1]
        h2, l2 = rows[i]

        # 判断包含关系：h2在[h1,l1]内部 或 l2在[h1,l1]内部
        hasContain = (h2 <= h1 and l2 >= l1) or (h2 >= h1 and l2 <= l1)

        if not hasContain:
            result.append(rows[i])
            i += 1
            continue

        # 判断趋势：最低价抬升=上升，最高价下降=下降
        # 用 result 最后一根 与 当前K线 比较
        if l2 > l1:
            # 上升趋势 → 高高原则
            new_h = max(h1, h2)
            new_l = max(l1, l2)
        else:
            # 下降趋势 → 低低原则
            new_h = min(h1, h2)
            new_l = min(l1, l2)

        result[-1] = (new_h, new_l)
        i += 1

    return result

# ─────────────────────────────────────────
# 第二步：顶底分型识别
# ─────────────────────────────────────────

def find_fenxing(klist):
    """
    识别顶分型和底分型
    顶分型：连续三根K线，中间K线的最高价和最低价都分别高于左右两根
    底分型：连续三根K线，中间K线的最高价和最低价都分别低于左右两根
    返回分型列表 [(type, index, high/low), ...]
    """
    n = len(klist)
    fen = []

    for i in range(1, n - 1):
        h_prev, l_prev = klist[i - 1]
        h_curr, l_curr = klist[i]
        h_next, l_next = klist[i + 1]

        # 顶分型
        if h_curr > h_prev and h_curr > h_next and l_curr > l_prev and l_curr > l_next:
            fen.append(('D', i, h_curr))
        # 底分型
        elif h_curr < h_prev and h_curr < h_next and l_curr < l_prev and l_curr < l_next:
            fen.append(('G', i, l_curr))

    return fen


def get_daily_atr(n=14):
    """计算PTA日线ATR（昨日收盘价为基准，固定阈值）"""
    df = ak.futures_zh_daily_sina(symbol='TA0')
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').tail(60).reset_index(drop=True)
    if len(df) < n + 1:
        return 200.0  # 数据不足返回默认值
    tr1 = df['high'] - df['low']
    tr2 = abs(df['high'] - df['close'].shift(1))
    tr3 = abs(df['low'] - df['close'].shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(n).mean().iloc[-1]
    if pd.isna(atr):
        return 200.0
    return round(float(atr), 0)


def build_bi(fen_list, klist=None, atr_threshold_pct=0.30):
    """
    从分型列表构建笔
    规则：
    - 底分型 + 顶分型 = 上行笔（up）
    - 顶分型 + 底分型 = 下行笔（dn）
    - 标准笔：分型间至少4根K线
    - 小笔：不足4根K线但价格幅度>=日ATR×atr_threshold_pct（默认30%）
    返回笔列表 [(方向, 起点索引, 终点索引, 起点价, 终点价, 是否小笔), ...]
    """
    if len(fen_list) < 2:
        return []

    # 计算ATR阈值
    atr = get_daily_atr()
    min_range = atr * atr_threshold_pct  # 默认30%日ATR

    result = []
    i = 0

    while i < len(fen_list) - 1:
        t_start, idx_start, price_start = fen_list[i]

        direction = 'up' if t_start == 'G' else 'dn'
        target_type = 'D' if direction == 'up' else 'G'

        j = i + 1
        while j < len(fen_list):
            t_check, idx_check, price_check = fen_list[j]

            if t_check == target_type:
                gap = idx_check - idx_start
                # 计算实际幅度（含跳空）
                if direction == 'up':
                    rng = price_check - price_start
                else:
                    rng = price_start - price_check

                if gap >= 4:
                    # 标准笔：幅度也需达到ATR阈值（否则标记为小笔）
                    is_small = (rng < min_range)
                    result.append((direction, idx_start, idx_check, price_start, price_check, is_small))
                    i = j
                    break
                elif gap < 4 and rng >= min_range:
                    # 小笔：不足4根但幅度达标
                    result.append((direction, idx_start, idx_check, price_start, price_check, True))
                    i = j
                    break
                else:
                    # 幅度也不够，继续穿过找下一个
                    j += 1
                    continue
            else:
                j += 1
                continue
        else:
            i += 1

    return result

# ─────────────────────────────────────────
# 测试
# ─────────────────────────────────────────

if __name__ == '__main__':
    print('获取1分钟K线...')
    raw = get_raw_klines()
    print(f'原始K线: {len(raw)} 根')
    print('前10根:')
    for i, r in raw.head(10).iterrows():
        print(f'  {r["datetime"]}  H={r["high"]} L={r["low"]} O={r["open"]} C={r["close"]}')

    print('\n处理包含关系...')
    proc = process_baohan_v2(raw)
    print(f'处理后K线: {len(proc)} 根')
    print('前10根:')
    for i, r in enumerate(proc[:10]):
        print(f'  {i}: H={r[0]} L={r[1]}')

    print('\n识别分型...')
    fen = find_fenxing(proc)
    print(f'找到 {len(fen)} 个分型')
    for f in fen[:20]:
        print(f'  {"顶分型" if f[0]=="D" else "底分型"} 位置={f[1]} 价位={f[2]}')

    print('\n计算ATR阈值...')
    atr = get_daily_atr()
    min_range = atr * 0.10
    print(f'日ATR={atr}点  笔最小幅度阈值=ATR×30%={min_range:.0f}点')

    print('\n构建笔...')
    bi_list = build_bi(fen)
    print(f'找到 {len(bi_list)} 笔')
    for bi in bi_list[:20]:
        direction = '↑上行' if bi[0] == 'up' else '↓下行'
        small = ' [小笔]' if bi[5] else ''
        print(f'  {direction} 位置{bi[1]}→{bi[2]}  价{bi[3]}→{bi[4]}  幅度{abs(bi[4]-bi[3]):.0f}点{small}')

# ─────────────────────────────────────────
# 线段构建
# ─────────────────────────────────────────

def build_duan(bi_list):
    """
    从笔序列构建线段
    规则：
    - 至少连续三笔构成一线段
    - 上行线段：上下上，第二笔低点>第一笔低点，第三笔高点>第二笔高点
    - 下行线段：下上下，第二笔高点<第一笔高点，第三笔低点<第二笔低点
    - 线段延伸：只要后续同向笔不断创新高/新低，线段就不断延伸
    - 线段破坏（正常破坏）：上行笔不再新高 或 下行笔不再新低
    返回线段列表 [(方向, 起点笔索引, 终点笔索引, 起点价, 终点价), ...]
    """
    if len(bi_list) < 3:
        return []

    duan_list = []
    i = 0

    while i <= len(bi_list) - 3:
        b1 = bi_list[i]
        b2 = bi_list[i + 1]
        b3 = bi_list[i + 2]

        d1, s1_idx, e1_idx, p1_start, p1_end, *rest1 = b1
        d2, s2_idx, e2_idx, p2_start, p2_end, *rest2 = b2
        d3, s3_idx, e3_idx, p3_start, p3_end, *rest3 = b3

        # 三笔方向检查
        dirs = [d1, d2, d3]

        if dirs == ['up', 'dn', 'up']:
            # 上行线段
            # 第二笔低点 > 第一笔低点，第三笔高点 > 第二笔高点
            if p2_end > p1_end and p3_end > p2_end:
                # 找到上行线段起点
                duan_list.append(('up', s1_idx, e3_idx, p1_start, p3_end))
                i += 1  # 线段起点移动
                continue

        elif dirs == ['dn', 'up', 'dn']:
            # 下行线段
            if p2_end < p1_end and p3_end < p2_end:
                duan_list.append(('dn', s1_idx, e3_idx, p1_start, p3_end))
                i += 1
                continue

        i += 1

    return duan_list


def build_zs_from_bi(bi_list):
    """
    从笔序列构建中枢（简化笔中枢）
    规则：三笔有重叠区间 → 形成中枢
    中枢上轨ZG = 三笔中最低的高点
    中枢下轨ZD = 三笔中最高的低点
    返回中枢列表 [{type, zs_lo(ZD), zs_hi(ZG), b1/b2/b3}, ...]
    """
    if len(bi_list) < 3:
        return []

    zs_list = []
    for i in range(len(bi_list) - 2):
        b1 = bi_list[i]
        b2 = bi_list[i + 1]
        b3 = bi_list[i + 2]

        d1, _, _, p1_start, p1_end, *_ = b1
        d2, _, _, p2_start, p2_end, *_ = b2
        d3, _, _, p3_start, p3_end, *_ = b3

        # 三笔同向
        if not (d1 == d2 == d3):
            continue

        if d1 == 'up':
            # 上行笔的高点
            highs = [p1_end, p2_end, p3_end]
            ZG = min(highs)
            # ZG = 三笔最低的高点，ZD = 三笔最高的低点
            ZD = max(lows)
            if ZG > ZD:  # 重叠成中枢
                zs_list.append({
                    'type': 'up',
                    'zs_lo': ZD,  # 下轨
                    'zs_hi': ZG,  # 上轨
                    'b1': b1, 'b2': b2, 'b3': b3
                })
        else:
            # 下行笔的低点
            highs = [p1_start, p2_start, p3_start]
            lows = [p1_end, p2_end, p3_end]
            ZG = min(highs)
            ZD = max(lows)
            if ZG > ZD:
                zs_list.append({
                    'type': 'dn',
                    'zs_lo': ZD,
                    'zs_hi': ZG,
                    'b1': b1, 'b2': b2, 'b3': b3
                })

    return zs_list


# ─────────────────────────────────────────
# 文字报告
# ─────────────────────────────────────────

def report_full():
    """完整缠论文字报告"""
    print('获取数据...')
    raw = get_raw_klines()
    print(f'原始K线: {len(raw)} 根')

    proc = process_baohan_v2(raw)
    print(f'处理后K线: {len(proc)} 根')

    fen = find_fenxing(proc)
    print(f'分型: {len(fen)} 个')

    atr = get_daily_atr()
    min_range = atr * 0.10
    print(f'日ATR={atr}  小笔阈值={min_range:.0f}')

    bi_list = build_bi(fen)
    print(f'笔: {len(bi_list)} 笔')

    duan_list = build_duan(bi_list)
    print(f'线段: {len(duan_list)} 段')

    zs_list = build_zs_from_bi(bi_list)
    print(f'中枢: {len(zs_list)} 个')

    print('\n=== 笔 ===')
    for bi in bi_list:
        d = '↑' if bi[0] == 'up' else '↓'
        small = '[小]' if bi[5] else ''
        print(f'  {d} {bi[3]:.0f}→{bi[4]:.0f} {abs(bi[4]-bi[3]):.0f}点{small}')

    print('\n=== 线段 ===')
    for duan in duan_list:
        d = '↑' if duan[0] == 'up' else '↓'
        print(f'  {d} {duan[3]:.0f}→{duan[4]:.0f} ({duan[1]}→{duan[2]})')

    print('\n=== 中枢 ===')
    for zs in zs_list[-5:]:
        print(f'  中枢[{int(zs["zs_lo"])}~{int(zs["zs_hi"])}] 幅度{int(zs["zs_hi"]-zs["zs_lo"])}点')


if __name__ == '__main__':
    report_full()

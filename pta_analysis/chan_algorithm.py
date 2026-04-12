#!/usr/bin/env python3
"""
缠论算法 - 笔延续版本
带有笔延续逻辑的完整缠论实现
"""

from typing import List, Dict, Any, Tuple, Optional
import pandas as pd


# ==================== 数据结构 ====================

class KL:
    """K线对象"""
    def __init__(self, idx: int, time: str, open: float, high: float, low: float, close: float, volume: float):
        self.idx = idx
        self.time = time
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume


class Bi:
    """笔"""
    def __init__(self, idx: int, dir: str, begin_idx: int, end_idx: int, begin_price: float, end_price: float, level: int = 1):
        self.idx = idx
        self.dir = dir
        self.begin_idx = begin_idx
        self.end_idx = end_idx
        self.begin_price = begin_price
        self.end_price = end_price
        self.level = level


# ==================== 包含关系处理 ====================

def merge_include(kls: List[KL]) -> List[KL]:
    """处理包含关系
    
    上升趋势：高高原则（取高点更高、低点更高）
    下降趋势：低低原则（取高点更低、低点更低）
    """
    if len(kls) < 3:
        return kls.copy()
    
    result = [kls[0], kls[1]]
    
    for i in range(2, len(kls)):
        current = kls[i]
        prev = result[-1]
        prev_prev = result[-2]
        
        # 判断是否存在包含关系
        has_containment = (current.high <= prev.high and current.low >= prev.low) or \
                          (current.high >= prev.high and current.low <= prev.low)
        
        if not has_containment:
            result.append(current)
            continue
        
        # 判断趋势：比较prev和prev_prev的低点
        is_up_trend = prev.low > prev_prev.low
        
        if is_up_trend:
            new_high = max(prev.high, current.high)
            new_low = max(prev.low, current.low)
        else:
            new_high = min(prev.high, current.high)
            new_low = min(prev.low, current.low)
        
        merged = KL(
            idx=prev.idx,
            time=prev.time,
            open=prev.open,
            high=new_high,
            low=new_low,
            close=current.close,
            volume=prev.volume + current.volume
        )
        result[-1] = merged
    
    return result


# ==================== 分型识别 ====================

def find_fenxing(kls: List[KL], min_gap: int = 1) -> List[Tuple[int, str, float]]:
    """识别分型
    
    顶分型：中间K线高点最高、低点也最高
    底分型：中间K线高点最低、低点也最低
    """
    if len(kls) < 3:
        return []
    
    fenxing = []
    i = 1
    
    while i < len(kls) - 1:
        left = kls[i - 1]
        mid = kls[i]
        right = kls[i + 1]
        
        # 顶分型
        if mid.high > left.high and mid.high > right.high and \
           mid.low > left.low and mid.low > right.low:
            fenxing.append((mid.idx, 'top', mid.high))
            i += 2
            continue
        
        # 底分型
        if mid.high < left.high and mid.high < right.high and \
           mid.low < left.low and mid.low < right.low:
            fenxing.append((mid.idx, 'bottom', mid.low))
            i += 2
            continue
        
        i += 1
    
    # 同向分型合并：保留幅度更大的
    if len(fenxing) > 1:
        merged = [fenxing[0]]
        for fx in fenxing[1:]:
            last = merged[-1]
            if last[1] == fx[1]:  # 同向
                if last[1] == 'top':
                    if last[2] >= fx[2]:
                        pass  # last更高，保持
                    else:
                        merged[-1] = fx  # fx更高，替换
                else:  # bottom
                    if last[2] <= fx[2]:
                        pass  # last更低，保持
                    else:
                        merged[-1] = fx
            else:
                merged.append(fx)
        fenxing = merged
    
    return fenxing


# ==================== 笔构建（带延续逻辑） ====================

def build_bi_extended(kls: List[KL], fenxing: List[Tuple[int, str, float]],
                      min_k: int = 4, small_bi_points: int = 30) -> List[Bi]:
    """构建笔 - 带延续逻辑
    
    延续规则：
    - 上行笔：起点与终点之间可以有更高的高点，但不能有更低的低点
    - 下行笔：起点与终点之间可以有更低的低点，但不能有更高的高点
    - 回调不足4根且没破起点，继续看是否有符合条件的新顶点
    """
    if len(fenxing) < 2:
        return []
    
    kls_dict = {kl.idx: kl for kl in kls}
    bis = []
    bi_idx = 0
    i = 0
    
    while i < len(fenxing) - 1:
        fx1 = fenxing[i]
        idx1, type1, price1 = fx1
        
        # 确定方向
        if type1 == 'bottom':
            direction = 'up'
            start_price = kls_dict[idx1].low if kls_dict.get(idx1) else price1
        else:
            direction = 'down'
            start_price = kls_dict[idx1].high if kls_dict.get(idx1) else price1
        
        # 找终点
        result = find_bi_end(kls, fenxing, kls_dict, i, direction, start_price, min_k)
        
        if result:
            end_idx, end_price, end_fenxing_type = result
            
            if end_idx != idx1:
                bi = Bi(
                    idx=bi_idx,
                    dir=direction,
                    begin_idx=idx1,
                    end_idx=end_idx,
                    begin_price=start_price,
                    end_price=end_price,
                    level=1
                )
                bis.append(bi)
                bi_idx += 1
                
                # 移动到终点分型的下一个
                for j in range(i + 1, len(fenxing)):
                    if fenxing[j][0] == end_idx:
                        i = j + 1
                        break
                else:
                    i += 1
            else:
                i += 1
        else:
            i += 1
    
    return bis


def find_bi_end(kls: List[KL], fenxing: List[Tuple[int, str, float]],
                kls_dict: Dict[int, KL], start_fenxing_idx: int,
                direction: str, start_price: float, min_k: int) -> Optional[Tuple[int, float, str]]:
    """找到笔的终点
    
    返回: (end_idx, end_price, end_fenxing_type) 或 None
    """
    i = start_fenxing_idx + 1
    
    # 记录上一个有效分型的信息
    last_valid_idx = fenxing[start_fenxing_idx][0]
    last_valid_price = start_price
    
    while i < len(fenxing):
        idx_i, type_i, price_i = fenxing[i]
        
        if direction == 'up':
            if type_i == 'top':
                # 遇到顶，更高则延续
                if price_i > last_valid_price:
                    last_valid_idx = idx_i
                    last_valid_price = price_i
                # 不更高的顶也继续看后面
                i += 1
            else:  # bottom
                if price_i < start_price:
                    # 破了起点，结束
                    return (idx_i, price_i, 'bottom')
                else:
                    # 没破起点，先检查后面是否有更高顶
                    has_higher_top = False
                    for j in range(i + 1, len(fenxing)):
                        if fenxing[j][1] == 'top' and fenxing[j][2] > last_valid_price:
                            has_higher_top = True
                            break
                    
                    if has_higher_top:
                        # 有更高顶，延续
                        i += 1
                    else:
                        # 没有更高顶，检查间隔
                        gap = abs(idx_i - fenxing[start_fenxing_idx][0])
                        if gap >= min_k:
                            return (last_valid_idx, last_valid_price, 'top')
                        else:
                            last_valid_idx = idx_i
                            last_valid_price = price_i
                            i += 1
        else:  # down
            if type_i == 'bottom':
                if price_i < last_valid_price:
                    last_valid_idx = idx_i
                    last_valid_price = price_i
                i += 1
            else:  # top
                if price_i > start_price:
                    return (idx_i, price_i, 'top')
                else:
                    # 检查后面是否有更低底
                    has_lower_bottom = False
                    for j in range(i + 1, len(fenxing)):
                        if fenxing[j][1] == 'bottom' and fenxing[j][2] < last_valid_price:
                            has_lower_bottom = True
                            break
                    
                    if has_lower_bottom:
                        i += 1
                    else:
                        gap = abs(idx_i - fenxing[start_fenxing_idx][0])
                        if gap >= min_k:
                            return (last_valid_idx, last_valid_price, 'bottom')
                        else:
                            last_valid_idx = idx_i
                            last_valid_price = price_i
                            i += 1
    
    # 到末尾，返回最后的有效位置
    if last_valid_idx != fenxing[start_fenxing_idx][0]:
        return (last_valid_idx, last_valid_price, 'top' if direction == 'up' else 'bottom')
    
    return None


# ==================== 兼容旧接口 ====================

def build_bi(kls: List[KL], fenxing: List[Tuple[int, str, float]],
             min_k: int = 4, small_bi_points: int = 30) -> List[Bi]:
    """兼容旧接口：使用带延续逻辑的版本"""
    return build_bi_extended(kls, fenxing, min_k, small_bi_points)


# ==================== 测试 ====================

if __name__ == "__main__":
    import akshare as ak
    
    df = ak.futures_zh_minute_sina(symbol='TA0', period='1')
    df = df.sort_values('datetime').reset_index(drop=True)
    
    mask = (df['datetime'] >= '2026-04-10 09:00:00') & (df['datetime'] <= '2026-04-10 15:00:00')
    segment = df[mask].reset_index(drop=True)
    
    def to_kls(dataframe):
        return [KL(
            idx=i,
            time=str(row['datetime']),
            open=row['open'],
            high=row['high'],
            low=row['low'],
            close=row['close'],
            volume=row.get('volume', 0)
        ) for i, row in dataframe.iterrows()]
    
    kls = to_kls(segment)
    mkls = merge_include(kls)
    fxs = find_fenxing(mkls)
    bis = build_bi(mkls, fxs, min_k=4, small_bi_points=30)
    
    print(f'分型: {len(fxs)}')
    print(f'笔: {len(bis)}')
    
    for b in bis:
        t1 = segment.iloc[b.begin_idx]['datetime'] if b.begin_idx < len(segment) else None
        t2 = segment.iloc[b.end_idx]['datetime'] if b.end_idx < len(segment) else None
        if t1 and t2:
            print(f'  {b.dir}, {str(t1)[-8:]}->{str(t2)[-8:]}, {b.begin_price:.0f}->{b.end_price:.0f}')

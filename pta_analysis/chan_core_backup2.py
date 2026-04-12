"""
chan_core.py - 缠论核心算法（严格按照缠论108课标准）
author: OpenClaw Agent
"""

from __future__ import annotations
import warnings
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any
import numpy as np

# 尝试导入matplotlib用于可视化
try:
    import matplotlib.pyplot as plt
    import matplotlib.patches as patches
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    warnings.warn("matplotlib not available, visualization disabled")

# ==================== 数据结构 ====================

@dataclass
class KL:
    """K线数据结构（含MACD）"""
    idx: int           # 全局索引
    time: str          # 时间字符串
    open: float        # 开盘价
    high: float        # 最高价
    low: float         # 最低价
    close: float       # 收盘价
    volume: float      # 成交量
    # MACD指标（计算后填充）
    dif: float = 0.0
    dea: float = 0.0
    macd: float = 0.0  # 柱 = (dif - dea) * 2


class Bi:
    """笔数据结构（增强版）
    
    新增功能：
    - is_sure: 虚实线段标记（True=确定线段，False=待确认虚笔）
    - sure_end: 确认结束位置列表（用于虚笔回退确认）
    - MACD指标族: Cal_MACD_area/peak/slope/amp 等多种背驰算法
    """
    
    def __init__(self, idx: int, dir: str, begin_idx: int, end_idx: int,
                 begin_price: float, end_price: float, level: int = 1,
                 is_sure: bool = True):
        self.idx = idx
        self.dir = dir
        self.begin_idx = begin_idx
        self.end_idx = end_idx
        self.begin_price = begin_price
        self.end_price = end_price
        self.level = level
        self._is_sure = is_sure
        self._sure_end: list = []  # 确认结束位置列表
        
        # 父线段引用
        self.parent_seg_idx: int = -1
    
    @property
    def is_sure(self) -> bool:
        """是否为确定笔（True）还是待确认虚笔（False）"""
        return self._is_sure
    
    @property
    def sure_end(self) -> list:
        """确认结束位置列表"""
        return self._sure_end
    
    def update_virtual_end(self, new_end_idx: int, new_end_price: float):
        """更新虚笔结束位置（当市场发展导致笔尚未最终确认）
        
        Args:
            new_end_idx: 新的结束K线索引
            new_end_price: 新的结束价格
        """
        # 保存当前确认结束位置
        self._sure_end.append((self.end_idx, self.end_price))
        # 更新为新的虚结束位置
        self.end_idx = new_end_idx
        self.end_price = new_end_price
        self._is_sure = False
    
    def restore_from_virtual_end(self, sure_end_idx: int, sure_end_price: float):
        """从虚笔恢复到确认状态
        
        Args:
            sure_end_idx: 确认的结束K线索引
            sure_end_price: 确认的结束价格
        """
        self._is_sure = True
        self.end_idx = sure_end_idx
        self.end_price = sure_end_price
        self._sure_end = []
    
    def append_sure_end(self, end_idx: int, end_price: float):
        """追加确认结束位置"""
        self._sure_end.append((end_idx, end_price))
    
    @property
    def is_up(self) -> bool:
        return self.dir == 'up'
    
    @property
    def is_down(self) -> bool:
        return self.dir == 'down'
    
    def get_begin_val(self) -> float:
        """获取笔起点值（UP笔=low, DOWN笔=high）"""
        return self.begin_price if self.is_up else self.begin_price
    
    def get_end_val(self) -> float:
        """获取笔终点值（UP笔=high, DOWN笔=low）"""
        return self.end_price if self.is_up else self.end_price
    
    def amp(self) -> float:
        """计算笔的价格幅度"""
        return abs(self.end_price - self.begin_price)
    
    def get_klc_cnt(self) -> int:
        """计算笔包含的K线数量"""
        return abs(self.end_idx - self.begin_idx) + 1
    
    # ==================== MACD指标族 ====================
    # 参考 chan_py_external/Math/MACD.py 和 Bi.py 中的实现
    
    def Cal_MACD_area(self, kls: List['KL']) -> float:
        """计算MACD面积（整段）
        
        MACD面积 = 笔区间内所有同向MACD柱的绝对值之和
        背驰判断：离开中枢的笔MACD面积 < 进入中枢的笔面积
        
        Args:
            kls: K线列表（含MACD指标）
            
        Returns:
            MACD面积值
        """
        idx_start = min(self.begin_idx, self.end_idx)
        idx_end = max(self.begin_idx, self.end_idx)
        
        area = 1e-7  # 避免除零
        for kl in kls:
            if idx_start <= kl.idx <= idx_end:
                if self.is_up and kl.macd > 0:
                    area += kl.macd
                elif self.is_down and kl.macd < 0:
                    area += abs(kl.macd)
        return area
    
    def Cal_MACD_half(self, kls: List['KL'], is_reverse: bool = False) -> float:
        """计算MACD半面积（前半段或后半段）
        
        Args:
            kls: K线列表（含MACD指标）
            is_reverse: False=前半段（从起点到峰值），True=后半段（从终点回溯到峰值）
            
        Returns:
            MACD半面积值
        """
        idx_start = min(self.begin_idx, self.end_idx)
        idx_end = max(self.begin_idx, self.end_idx)
        kl_range = [kl for kl in kls if idx_start <= kl.idx <= idx_end]
        
        if not kl_range:
            return 1e-7
        
        area = 1e-7
        
        if is_reverse:
            # 后半段：从终点往回找同向MACD
            begin_klu = kl_range[-1]  # 终点
            peak_macd = begin_klu.macd
            for kl in reversed(kl_range):
                if kl.macd * peak_macd > 0:  # 同向
                    area += abs(kl.macd)
                else:
                    break
        else:
            # 前半段：从起点往峰值找同向MACD
            begin_klu = kl_range[0]  # 起点
            peak_macd = begin_klu.macd
            for kl in kl_range:
                if kl.macd * peak_macd > 0:  # 同向
                    area += abs(kl.macd)
                else:
                    break
        
        return area
    
    def Cal_MACD_peak(self, kls: List['KL']) -> float:
        """计算MACD峰值（绝对值最大）
        
        Args:
            kls: K线列表（含MACD指标）
            
        Returns:
            MACD峰值（绝对值）
        """
        idx_start = min(self.begin_idx, self.end_idx)
        idx_end = max(self.begin_idx, self.end_idx)
        
        peak = 1e-7
        for kl in kls:
            if idx_start <= kl.idx <= idx_end:
                abs_macd = abs(kl.macd)
                if abs_macd > peak:
                    if self.is_up and kl.macd > 0:
                        peak = abs_macd
                    elif self.is_down and kl.macd < 0:
                        peak = abs_macd
        return peak
    
    def Cal_MACD_diff(self, kls: List['KL']) -> float:
        """计算MACD差值（红绿柱最大值-最小值）
        
        Args:
            kls: K线列表（含MACD指标）
            
        Returns:
            MACD差值（_max - _min）
        """
        idx_start = min(self.begin_idx, self.end_idx)
        idx_end = max(self.begin_idx, self.end_idx)
        
        macd_values = []
        for kl in kls:
            if idx_start <= kl.idx <= idx_end:
                if self.is_up and kl.macd > 0:
                    macd_values.append(kl.macd)
                elif self.is_down and kl.macd < 0:
                    macd_values.append(kl.macd)
        
        if not macd_values:
            return 0.0
        
        return max(macd_values) - min(macd_values)
    
    def Cal_MACD_slope(self, kls: List['KL']) -> float:
        """计算MACD斜率（基于价格变化）
        
        斜率 = (end_price - begin_price) / begin_price / k线数量
        
        Args:
            kls: K线列表
            
        Returns:
            MACD斜率值
        """
        kl_count = max(1, self.get_klc_cnt())
        if self.is_up:
            return (self.end_price - self.begin_price) / self.begin_price / kl_count
        else:
            return (self.begin_price - self.end_price) / self.begin_price / kl_count
    
    def Cal_MACD_amp(self, kls: List['KL']) -> float:
        """计算MACD振幅比率
        
        UP笔: (end_high - begin_low) / begin_low
        DOWN笔: (begin_high - end_low) / begin_high
        
        Args:
            kls: K线列表
            
        Returns:
            振幅比率
        """
        begin_klu = None
        end_klu = None
        for kl in kls:
            if kl.idx == self.begin_idx:
                begin_klu = kl
            elif kl.idx == self.end_idx:
                end_klu = kl
        
        if self.is_down:
            if begin_klu and end_klu:
                return (begin_klu.high - end_klu.low) / begin_klu.high
            return self.amp() / self.begin_price
        else:
            if begin_klu and end_klu:
                return (end_klu.high - begin_klu.low) / begin_klu.low
            return self.amp() / self.begin_price
    
    def cal_macd_metric(self, kls: List['KL'], macd_algo: str = 'area') -> float:
        """计算MACD指标（根据算法类型）
        
        Args:
            kls: K线列表（含MACD指标）
            macd_algo: 算法类型 ('area', 'peak', 'slope', 'amp', 'diff', 'half')
            
        Returns:
            对应的MACD指标值
        """
        algo_map = {
            'area': self.Cal_MACD_area,
            'peak': self.Cal_MACD_peak,
            'slope': self.Cal_MACD_slope,
            'amp': self.Cal_MACD_amp,
            'diff': self.Cal_MACD_diff,
            'half': self.Cal_MACD_half,
        }
        func = algo_map.get(macd_algo, self.Cal_MACD_area)
        if macd_algo == 'half':
            return func(kls, is_reverse=False)
        return func(kls)


@dataclass
class Seg:
    """线段数据结构"""
    idx: int           # 线段编号
    dir: str           # 'up' 或 'down'
    begin_idx: int     # 起始笔索引
    end_idx: int       # 结束笔索引
    begin_price: float  # 起始价格
    end_price: float    # 结束价格
    level: int = 1     # 级别


@dataclass
class ZS:
    """中枢数据结构"""
    idx: int           # 中枢编号
    low: float         # 中枢区间最低价
    high: float        # 中枢区间最高价
    begin_idx: int     # 起始线段索引
    end_idx: int       # 结束线段索引
    level: int = 1     # 级别


@dataclass
class BSPoint:
    """买卖点数据结构"""
    idx: int           # 买点编号
    type: str          # '1buy'/'2buy'/'3buy'/'1sell'/'2sell'/'3sell'
    direction: str     # 'long' 或 'short'
    price: float       # 价格
    bi_idx: int        # 关联的笔索引
    reason: str = ""   # 原因说明


# ==================== 辅助函数 ====================

def calculate_macd(kls: List[KL], fast: int = 12, slow: int = 26, signal: int = 9) -> List[KL]:
    """计算MACD指标（基于收盘价）
    
    Args:
        kls: KL列表
        fast: 快线周期
        slow: 慢线周期
        signal: 信号线周期
        
    Returns:
        KL列表，每项填充 dif/dea/macd
    """
    if len(kls) < slow:
        return kls
    
    closes = np.array([kl.close for kl in kls], dtype=float)
    
    # EMA
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    
    dif = ema_fast - ema_slow
    dea = _ema(dif, signal)
    macd = (dif - dea) * 2  # 柱状图
    
    for i, kl in enumerate(kls):
        kl.dif = float(dif[i])
        kl.dea = float(dea[i])
        kl.macd = float(macd[i])
    
    return kls


def _ema(values: np.ndarray, period: int) -> np.ndarray:
    """计算指数移动平均线"""
    ema = np.zeros_like(values)
    alpha = 2.0 / (period + 1)
    ema[0] = values[0]
    for i in range(1, len(values)):
        ema[i] = alpha * values[i] + (1 - alpha) * ema[i - 1]
    return ema


def kl_to_kls(df) -> List[KL]:
    """DataFrame转换为KL列表
    
    Args:
        df: 包含 open/high/low/close/time/vol 的DataFrame
        
    Returns:
        List[KL]对象（含MACD）
    """
    kls = []
    for i, row in df.iterrows():
        kl = KL(
            idx=i,
            time=str(row.get('time', row.get('datetime', i))),
            open=float(row['open']),
            high=float(row['high']),
            low=float(row['low']),
            close=float(row['close']),
            volume=float(row.get('volume', 0))
        )
        kls.append(kl)
    
    # 计算MACD
    kls = calculate_macd(kls)
    return kls


# ==================== 第一步：包含关系处理 ====================

def merge_include(kls: List[KL]) -> List[KL]:
    """处理K线包含关系
    
    严格按照缠论108课标准：
    - 上升趋势包含：取高高原则 (max(high), max(low))
    - 下降趋势包含：取低低原则 (min(high), min(low))
    - 趋势判断：处理后K线的收盘 vs 开盘，或者 low抬升/下降
    
    重要：合并后重新建立顺序索引(0,1,2...)，不再使用原始idx
    idx用于最终结果的K线定位（分型/笔的begin_idx/end_idx都是指原始K线索引）
    
    Args:
        kls: 原始K线列表
        
    Returns:
        处理后的K线列表
    """
    if len(kls) < 3:
        return [KL(idx=i, time=kl.time, open=kl.open, high=kl.high,
                    low=kl.low, close=kl.close, volume=kl.volume)
                for i, kl in enumerate(kls)]
    
    result: List[KL] = []
    new_idx = 0  # 新的顺序索引
    
    i = 0
    while i < len(kls):
        if len(result) < 2:
            result.append(KL(
                idx=kls[i].idx,  # 保留原始idx用于回溯
                time=kls[i].time,
                open=kls[i].open,
                high=kls[i].high,
                low=kls[i].low,
                close=kls[i].close,
                volume=kls[i].volume
            ))
            i += 1
            new_idx += 1
            continue
        
        prev = result[-1]
        curr = kls[i]
        
        # 判断是否有包含关系
        has_include = (curr.high <= prev.high and curr.low >= prev.low) or \
                      (curr.high >= prev.high and curr.low <= prev.low)
        
        if not has_include:
            result.append(KL(
                idx=kls[i].idx,
                time=kls[i].time,
                open=kls[i].open,
                high=kls[i].high,
                low=kls[i].low,
                close=kls[i].close,
                volume=kls[i].volume
            ))
            i += 1
            new_idx += 1
            continue
        
        # 存在包含关系，根据趋势处理
        if len(result) >= 2:
            p1 = result[-2]
            # 上升趋势：低点不断抬高 → p1.low < prev.low
            # 下降趋势：高不断降低 → p1.high > prev.high
            if p1.low < prev.low:  # 上升趋势
                new_high = max(prev.high, curr.high)
                new_low = max(prev.low, curr.low)
            else:  # 下降趋势
                new_high = min(prev.high, curr.high)
                new_low = min(prev.low, curr.low)
        else:
            if curr.close >= prev.close:
                new_high = max(prev.high, curr.high)
                new_low = max(prev.low, curr.low)
            else:
                new_high = min(prev.high, curr.high)
                new_low = min(prev.low, curr.low)
        
        # 更新前一根K线（保留原始idx，用于后续定位）
        result[-1] = KL(
            idx=prev.idx,
            time=prev.time,
            open=prev.open,
            high=new_high,
            low=new_low,
            close=curr.close,
            volume=prev.volume + curr.volume
        )
        i += 1
    
    return result


# ==================== 第二步：分型识别 ====================

def find_fenxing(kls: List[KL], min_gap: int = 1) -> List[Tuple[int, str, float]]:
    """识别分型（顶分型和底分型）
    
    严格按照缠论108课标准：
    - 顶分型：中间K线高点最高、低点也最高
    - 底分型：中间K线高点最低、低点也最低
    - 相邻分型必须间隔至少min_gap根K线
    
    注意：返回的idx是KL对象在原始数据中的索引（不是列表位置）
    
    Args:
        kls: 处理后的K线列表
        min_gap: 相邻分型最小间隔K线数
        
    Returns:
        List[Tuple[original_idx, 'top'/'bottom', price]]
    """
    if len(kls) < 3:
        return []
    
    fenxing: List[Tuple[int, str, float]] = []
    i = 1  # 从第二根开始
    
    while i < len(kls) - 1:
        left = kls[i - 1]
        mid = kls[i]
        right = kls[i + 1]
        
        # 顶分型：中间K线高点最高、低点也最高
        if mid.high > left.high and mid.high > right.high and \
           mid.low > left.low and mid.low > right.low:
            fenxing.append((mid.idx, 'top', mid.high))
            i += 2  # 跳过分型本身
            continue
        
        # 底分型：中间K线高点最低、低点也最低
        if mid.high < left.high and mid.high < right.high and \
           mid.low < left.low and mid.low < right.low:
            fenxing.append((mid.idx, 'bottom', mid.low))
            i += 2
            continue
        
        i += 1
    
    # 过滤间隔太近的分型（使用原始idx差值）
    if min_gap > 0 and len(fenxing) > 1:
        filtered = [fenxing[0]]
        for fx in fenxing[1:]:
            if fx[0] - filtered[-1][0] >= min_gap:
                filtered.append(fx)
        fenxing = filtered
    
    return fenxing


# ==================== 第三步：笔构建 ====================

def build_bi(kls: List[KL], fenxing: List[Tuple[int, str, float]],
             min_k: int = 4, small_bi_points: int = 30) -> List[Bi]:
    """构建笔
    
    严格按照缠论108课标准：
    - 标准笔：顶底分型间隔 >= 4根K线
    - 小笔：间隔<4根但价格幅度 >= small_bi_points点
    - 顶分型后底分型 = 向下笔，底分型后顶分型 = 向上笔
    
    注意：fenxing中的idx是原始K线索引，kls列表是合并后的（但保留了原始idx）
    
    Args:
        kls: 处理后的K线列表（保留原始idx）
        fenxing: 分型列表
        min_k: 标准笔最小K线数
        small_bi_points: 小笔最小价格幅度
        
    Returns:
        List[Bi]笔列表
    """
    if len(fenxing) < 2:
        return []
    
    # 建立原始idx -> KL的映射
    kls_dict: Dict[int, KL] = {kl.idx: kl for kl in kls}
    bis: List[Bi] = []
    bi_idx = 0
    
    i = 0
    while i < len(fenxing) - 1:
        fx1 = fenxing[i]
        fx2 = fenxing[i + 1]
        
        idx1, type1, price1 = fx1
        idx2, type2, price2 = fx2
        
        # 必须顶底交替
        if type1 == type2:
            i += 1
            continue
        
        # 计算间隔K线数（使用原始idx差值）
        gap = abs(idx2 - idx1) - 1
        
        # 判断是否为有效笔
        if gap < min_k:
            # 小笔判断：价格幅度
            gap_points = abs(price2 - price1)
            if gap_points < small_bi_points:
                i += 1
                continue
        
        # 确定笔的方向
        # UP笔：start=底.low，end=顶.high（向上价格运动）
        # DOWN笔：start=顶.high，end=底.low（向下价格运动）
        if type1 == 'top':  # 顶分型后底分型 = 向下笔
            direction = 'down'
            start_k = kls_dict.get(idx1)
            end_k = kls_dict.get(idx2)
            if start_k and end_k:
                start_price = start_k.high   # 顶的high作为起点
                end_price = end_k.low        # 底的low作为终点
            else:
                i += 1
                continue
        else:  # 底分型后顶分型 = 向上笔
            direction = 'up'
            start_k = kls_dict.get(idx1)
            end_k = kls_dict.get(idx2)
            if start_k and end_k:
                start_price = start_k.low    # 底的low作为起点
                end_price = end_k.high       # 顶的high作为终点
            else:
                i += 1
                continue
        
        bi = Bi(
            idx=bi_idx,
            dir=direction,
            begin_idx=idx1,
            end_idx=idx2,
            begin_price=start_price,
            end_price=end_price,
            level=1
        )
        bis.append(bi)
        bi_idx += 1
        i += 1
    
    return bis


# ==================== 第四步：线段检测（严格特征序列算法） ====================

def _get_bi_low(bi: Bi) -> float:
    return min(bi.begin_price, bi.end_price)

def _get_bi_high(bi: Bi) -> float:
    return max(bi.begin_price, bi.end_price)


class FeatureSequence:
    """简化版特征序列 - 用于严格线段破坏检测
    
    缠论标准（特征序列分型破坏）：
    - UP线段的特征序列 = DOWN笔序列
    - DOWN线段的特征序列 = UP笔序列
    - 特征序列分型：3个元素形成顶/底分型
    - 线段破坏：反向笔的分型有效穿越前一线段的高低点
    
    简化处理：不合并特征序列元素，每个反向笔作为一个独立元素
    """
    
    def __init__(self, seg_dir: str):
        self.seg_dir = seg_dir  # 线段方向 'up' or 'down'
        # 特征序列方向 = 线段方向的反向
        self.eigen_dir = 'down' if seg_dir == 'up' else 'up'
        # 三个特征序列元素: (bi, low, high)
        self.elements: List[Tuple[Bi, float, float]] = []
        # 累积的特征序列笔列表（按顺序）
        self.bi_list: List[Bi] = []
    
    def add_bi(self, bi: Bi) -> bool:
        """添加笔到特征序列
        
        Args:
            bi: 要添加的笔
            
        Returns:
            bool: 是否形成特征序列分型（3个元素齐备且形成有效分型）
        """
        # 只接受反向笔
        if bi.dir != self.eigen_dir:
            return False
        
        self.bi_list.append(bi)
        
        # 计算该笔的高低
        low = min(bi.begin_price, bi.end_price)
        high = max(bi.begin_price, bi.end_price)
        
        if len(self.elements) == 0:
            # 第1元素：直接添加
            self.elements.append((bi, low, high))
            return False
        
        elif len(self.elements) == 1:
            # 第2元素：直接添加（不合并）
            self.elements.append((bi, low, high))
            return False
        
        elif len(self.elements) == 2:
            # 第3元素：直接添加
            self.elements.append((bi, low, high))
            # 检查是否形成有效分型
            return self._check_fractal()
        
        else:
            # 4个以上元素时滑动后添加
            return False
    
    def _check_fractal(self) -> bool:
        """检查特征序列是否形成有效分型
        
        对于UP线段（特征序列是DOWN笔）：
        - 有效底分型：第2元素的low < 第1元素的low 且 第2元素的low < 第3元素的low
        
        对于DOWN线段（特征序列是UP笔）：
        - 有效顶分型：第2元素的high > 第1元素的high 且 第2元素的high > 第3元素的high
        """
        if len(self.elements) < 3:
            return False
        
        e0_bi, e0_low, e0_high = self.elements[0]
        e1_bi, e1_low, e1_high = self.elements[1]
        e2_bi, e2_low, e2_high = self.elements[2]
        
        if self.seg_dir == 'up':
            # UP线段需要底分型：e1是三个中最低的
            return e1_low < e0_low and e1_low < e2_low
        else:
            # DOWN线段需要顶分型：e1是三个中最高的
            return e1_high > e0_high and e1_high > e2_high
    
    def check_break(self) -> Tuple[bool, int, int]:
        """检查线段是否被破坏
        
        严格缠论规则：
        - 3个特征序列元素形成有效分型
        - 对于UP线段：第3元素low < 第2元素low 且 后续笔确认
        - 对于DOWN线段：第3元素high > 第2元素high 且 后续笔确认
        
        Returns:
            Tuple(是否破坏, 破坏笔索引, 确认笔索引)
        """
        if len(self.elements) < 3:
            return False, -1, -1
        
        e0_bi, e0_low, e0_high = self.elements[0]
        e1_bi, e1_low, e1_high = self.elements[1]
        e2_bi, e2_low, e2_high = self.elements[2]
        
        # e2是最后一个添加的笔
        e2_bi_idx = e2_bi.idx
        
        if self.seg_dir == 'up':
            # UP线段被破坏：
            # 条件1：e2.low < e1.low（跌破）
            # 条件2：后续两个UP笔确认，第二个UP笔高点 > e1.high
            if e2_low < e1_low:
                # 检查后续确认
                # 找到e2之后的第一笔（应该是UP笔）
                e2_pos = len(self.bi_list) - 1
                if e2_pos + 2 < len(self.bi_list):
                    after_e2 = self.bi_list[e2_pos + 1:e2_pos + 3]
                    if after_e2[0].dir == 'up' and after_e2[1].dir == 'up':
                        if after_e2[1].end_price > e1_high:
                            return True, e2_bi_idx, after_e2[1].idx
                # 即使没有后续确认，跌破e1.low也算破坏
                return True, e2_bi_idx, -1
        
        else:
            # DOWN线段被破坏：
            # 条件1：e2.high > e1.high（突破）
            # 条件2：后续两个DOWN笔确认，第二个DOWN笔低点 < e1.low
            if e2_high > e1_high:
                e2_pos = len(self.bi_list) - 1
                if e2_pos + 2 < len(self.bi_list):
                    after_e2 = self.bi_list[e2_pos + 1:e2_pos + 3]
                    if after_e2[0].dir == 'down' and after_e2[1].dir == 'down':
                        if after_e2[1].end_price < e1_low:
                            return True, e2_bi_idx, after_e2[1].idx
                return True, e2_bi_idx, -1
        
        return False, -1, -1
    
    def slide(self) -> bool:
        """滑动特征序列窗口
        - 将第2元素作为新的第1元素
        - 将第3元素（如果有）作为新的第2元素
        - 清空第3元素位置
        - 返回是否滑动成功
        """
        if len(self.elements) < 2:
            return False
        
        if len(self.elements) >= 3:
            # 有3个元素：滑动后剩2个
            self.elements = [self.elements[1], self.elements[2]]
            # 滑动bi_list：移除第1个bi
            self.bi_list = self.bi_list[1:]
        else:
            # 只有2个元素：滑动后剩1个
            self.elements = [self.elements[1]]
            self.bi_list = self.bi_list[1:]
        
        return True


def check_seg_broken_strict(bi_list: List[Bi], start_i: int, seg_dir: str) -> Tuple[bool, int, int, FeatureSequence]:
    """严格检查线段是否破坏（特征序列分型破坏算法）
    
    使用滑动窗口算法：
    1. 收集反向笔形成特征序列
    2. 当形成3元素分型时检查是否破坏
    3. 如果没有破坏，滑动窗口继续
    
    Args:
        bi_list: 笔列表
        start_i: 线段起始笔索引（确定线段方向的第1笔）
        seg_dir: 线段方向 ('up' or 'down')
        
    Returns:
        Tuple(是否破坏, 破坏笔索引, 确认笔索引, 特征序列对象)
    """
    n = len(bi_list)
    if start_i >= n - 2:
        return False, -1, -1, None
    
    fs = FeatureSequence(seg_dir)
    
    # 从第2笔开始处理
    i = start_i + 1
    max_iterations = n * 2  # 防止无限循环
    iterations = 0
    
    while i < n and iterations < max_iterations:
        iterations += 1
        bi = bi_list[i]
        
        # 添加反向笔到特征序列
        if fs.add_bi(bi):
            # 形成了3元素分型，检查是否破坏
            is_broken, broken_bi_idx, confirm_bi_idx = fs.check_break()
            if is_broken:
                return True, broken_bi_idx, confirm_bi_idx, fs
            
            # 没有破坏，滑动窗口继续
            fs.slide()
        
        i += 1
    
    # 遍历完所有笔也没有破坏
    return False, -1, -1, fs


def _extend_seg(bi_list: List[Bi], start_i: int) -> Tuple[Seg, int, int]:
    """通用线段延伸函数（状态机）
    
    缠论标准：
    - 线段至少需要3笔
    - UP段被破坏：DOWN笔.low < 前一UP笔.low
    - DOWN段被破坏：UP笔.high > 前一DOWN笔.high
    
    Returns:
        Tuple(线段, 笔计数, 下一搜索位置)
    """
    n = len(bi_list)
    if start_i >= n - 2:
        return Seg(idx=-1, dir='up', begin_idx=-1, end_idx=-1, begin_price=0, end_price=0, level=1), 0, n
    
    seg_dir = bi_list[start_i].dir
    first_bi = bi_list[start_i]
    
    # 用于追踪当前线段范围
    if seg_dir == 'up':
        # UP线段：追踪高点
        seg_high = first_bi.end_price
        seg_low = first_bi.begin_price  # 破坏参考：跌破此低则破坏
        ref_low = first_bi.begin_price  # 用于判断破坏的前一本UP笔低点
    else:
        # DOWN线段：追踪低点
        seg_low = first_bi.end_price
        seg_high = first_bi.begin_price  # 破坏参考：突破此高则破坏
        ref_high = first_bi.begin_price  # 用于判断破坏的前一本DOWN笔高点
    
    seg_end_i = start_i
    stroke_count = 1
    i = start_i + 1
    
    while i < n:
        curr_bi = bi_list[i]
        
        if curr_bi.dir == seg_dir:
            # 同向笔：必须创新高（UP）或新低（DOWN）才算延伸
            if seg_dir == 'up' and curr_bi.end_price > seg_high:
                seg_high = curr_bi.end_price
                seg_low = curr_bi.begin_price  # 更新破坏参考点
                ref_low = curr_bi.begin_price
                seg_end_i = i
                stroke_count += 1
                i += 1
                continue
            elif seg_dir == 'down' and curr_bi.end_price < seg_low:
                seg_low = curr_bi.end_price
                seg_high = curr_bi.begin_price  # 更新破坏参考点
                ref_high = curr_bi.begin_price
                seg_end_i = i
                stroke_count += 1
                i += 1
                continue
            else:
                # 没创新高/新低，继续看后续笔（不加入线段）
                i += 1
                continue
        else:
            # 反向笔：检查是否破坏
            if seg_dir == 'up':
                # DOWN笔破坏：curr_bi.low < ref_low（跌破前一本UP笔低点）
                if curr_bi.begin_price < ref_low:
                    # 破坏！包含此反向笔
                    seg_end_i = i
                    stroke_count += 1
                    # 延伸结束，返回 (seg, count, i+1)
                    end_bi = bi_list[seg_end_i]
                    seg = Seg(
                        idx=first_bi.idx, dir='up',
                        begin_idx=first_bi.begin_idx, end_idx=end_bi.end_idx,
                        begin_price=first_bi.begin_price, end_price=end_bi.end_price,
                        level=1
                    )
                    return seg, stroke_count, i + 1
                else:
                    # 未破坏：作为第2笔，看第3笔是否能创新高
                    seg_end_i = i
                    stroke_count += 1
                    # 找第3笔（必须是同向且创新高/新低）
                    j = i + 1
                    while j < n:
                        next_bi = bi_list[j]
                        if next_bi.dir == seg_dir:
                            if seg_dir == 'up' and next_bi.end_price > seg_high:
                                seg_high = next_bi.end_price
                                ref_low = next_bi.begin_price
                                seg_end_i = j
                                stroke_count += 1
                                j += 1
                                break
                            elif seg_dir == 'down' and next_bi.end_price < seg_low:
                                seg_low = next_bi.end_price
                                ref_high = next_bi.begin_price
                                seg_end_i = j
                                stroke_count += 1
                                j += 1
                                break
                            else:
                                j += 1
                                continue
                        else:
                            # 又是反向笔：跳过，继续
                            j += 1
                            continue
                    if stroke_count >= 3:
                        end_bi = bi_list[seg_end_i]
                        seg = Seg(
                            idx=first_bi.idx, dir=seg_dir,
                            begin_idx=first_bi.begin_idx, end_idx=end_bi.end_idx,
                            begin_price=first_bi.begin_price, end_price=end_bi.end_price,
                            level=1
                        )
                        return seg, stroke_count, j
                    else:
                        # 笔数不足3，放弃此起点
                        stroke_count = 0
                        break
            else:
                # DOWN线段被UP笔破坏
                if curr_bi.begin_price > ref_high:
                    seg_end_i = i
                    stroke_count += 1
                    end_bi = bi_list[seg_end_i]
                    seg = Seg(
                        idx=first_bi.idx, dir='down',
                        begin_idx=first_bi.begin_idx, end_idx=end_bi.end_idx,
                        begin_price=first_bi.begin_price, end_price=end_bi.end_price,
                        level=1
                    )
                    return seg, stroke_count, i + 1
                else:
                    seg_end_i = i
                    stroke_count += 1
                    j = i + 1
                    while j < n:
                        next_bi = bi_list[j]
                        if next_bi.dir == seg_dir:
                            if seg_dir == 'down' and next_bi.end_price < seg_low:
                                seg_low = next_bi.end_price
                                ref_high = next_bi.begin_price
                                seg_end_i = j
                                stroke_count += 1
                                j += 1
                                break
                            else:
                                j += 1
                                continue
                        else:
                            j += 1
                            continue
                    if stroke_count >= 3:
                        end_bi = bi_list[seg_end_i]
                        seg = Seg(
                            idx=first_bi.idx, dir=seg_dir,
                            begin_idx=first_bi.begin_idx, end_idx=end_bi.end_idx,
                            begin_price=first_bi.begin_price, end_price=end_bi.end_price,
                            level=1
                        )
                        return seg, stroke_count, j
                    else:
                        stroke_count = 0
                        break
    
    # 线段无效（笔数不足）
    return Seg(idx=-1, dir=seg_dir, begin_idx=-1, end_idx=-1, begin_price=0, end_price=0, level=1), 0, start_i + 1


def build_seg(bi_list: List[Bi]) -> List[Seg]:
    """构建线段 - 严格特征序列分型破坏算法
    
    严格按照缠论108课标准：
    - 线段至少由3笔构成
    - UP线段被破坏：特征序列底分型 + 3rd元素跌破确认点
    - DOWN线段被破坏：特征序列顶分型 + 3rd元素突破确认点
    
    算法流程：
    1. 以第1笔确定线段方向
    2. 收集反向笔构成特征序列
    3. 当特征序列形成有效分型且破坏成立时，线段结束
    """
    if len(bi_list) < 3:
        return []
    
    segs: List[Seg] = []
    seg_idx = 0
    i = 0
    n = len(bi_list)
    
    while i <= n - 3:
        # 以bi_list[i]作为线段起点
        first_bi = bi_list[i]
        seg_dir = first_bi.dir
        
        # 使用严格算法检查破坏
        is_broken, broken_bi_idx, confirm_bi_idx, fs = check_seg_broken_strict(bi_list, i, seg_dir)
        
        if is_broken and broken_bi_idx >= 0:
            # 找到破坏点之前的最后一笔（应该与seg_dir同向）
            # 特征序列至少要有3个元素，对应至少3笔
            if len(fs.bi_list) >= 3:
                # 线段结束于特征序列第3元素对应的原始笔
                # 找到broken_bi_idx对应的笔索引
                end_bi = None
                for bi in bi_list:
                    if bi.idx == broken_bi_idx:
                        end_bi = bi
                        break
                
                if end_bi is None:
                    # fallback: 使用特征序列最后一笔
                    end_bi = fs.bi_list[-1]
                
                # 创建线段
                seg = Seg(
                    idx=seg_idx,
                    dir=seg_dir,
                    begin_idx=first_bi.begin_idx,
                    end_idx=end_bi.end_idx,
                    begin_price=first_bi.begin_price,
                    end_price=end_bi.end_price,
                    level=1
                )
                segs.append(seg)
                seg_idx += 1
                
                # 从破坏点继续搜索（找破坏笔之后的第一笔作为新起点）
                # 找到broken_bi_idx在bi_list中的位置
                broken_pos = -1
                for idx, bi in enumerate(bi_list):
                    if bi.idx == broken_bi_idx:
                        broken_pos = idx
                        break
                
                if broken_pos >= 0:
                    i = broken_pos + 1
                else:
                    i += 1
            else:
                # 特征序列不足3笔，尝试下一个起点
                i += 1
        else:
            # 没有检测到破坏（可能是数据结束或特征序列未形成）
            # 使用原有简化逻辑作为fallback
            seg, stroke_count, next_i = _extend_seg(bi_list, i)
            if stroke_count >= 3 and seg.idx >= 0:
                seg.idx = seg_idx
                seg_idx += 1
                segs.append(seg)
                i = next_i
            else:
                i += 1
    
    return segs


# ==================== 第五步：中枢构建 ====================

def _zs_overlap(zs1: ZS, zs2: ZS) -> bool:
    """检查两个中枢是否重叠（允许边界相等）"""
    return max(zs1.low, zs2.low) <= min(zs1.high, zs2.high)


def build_zs(segs: List[Seg]) -> List[ZS]:
    """构建中枢 + 合并相邻重叠中枢
    
    严格按照缠论108课标准：
    - 三段重叠 = 中枢
    - 中枢区间：[max(各段低点), min(各段高点)]
    - 相邻中枢如果有重叠，合并为一个（借鉴chan_py_external）
    
    Args:
        segs: 线段列表
        
    Returns:
        List[ZS]中枢列表
    """
    if len(segs) < 3:
        return []
    
    # 第一遍：构建所有原始中枢
    raw_zss: List[ZS] = []
    zs_idx = 0
    
    i = 0
    while i <= len(segs) - 3:
        s1, s2, s3 = segs[i], segs[i + 1], segs[i + 2]
        
        # 每个线段对应的实际高低点
        # UP线段: begin_price=低点(底), end_price=高点(顶)
        # DOWN线段: begin_price=高点(顶), end_price=低点(底)
        # ZS需要: low=最低价, high=最高价
        if s1.dir == 'up':
            l1, h1 = s1.begin_price, s1.end_price  # low=起点, high=终点
        else:
            l1, h1 = s1.end_price, s1.begin_price  # low=终点, high=起点
        
        if s2.dir == 'up':
            l2, h2 = s2.begin_price, s2.end_price
        else:
            l2, h2 = s2.end_price, s2.begin_price
        
        if s3.dir == 'up':
            l3, h3 = s3.begin_price, s3.end_price
        else:
            l3, h3 = s3.end_price, s3.begin_price
        
        max_low = max(l1, l2, l3)
        min_high = min(h1, h2, h3)
        
        if max_low < min_high:
            zs = ZS(
                idx=zs_idx,
                low=max_low,
                high=min_high,
                begin_idx=s1.begin_idx,
                end_idx=s3.end_idx,
                level=1
            )
            raw_zss.append(zs)
            zs_idx += 1
        i += 2
    
    # 第二遍：合并相邻重叠的中枢
    if not raw_zss:
        return []
    
    merged: List[ZS] = [raw_zss[0]]
    for zs in raw_zss[1:]:
        last = merged[-1]
        if _zs_overlap(last, zs):
            # 合并：新区间 = union
            merged[-1] = ZS(
                idx=last.idx,
                low=min(last.low, zs.low),
                high=max(last.high, zs.high),
                begin_idx=last.begin_idx,
                end_idx=zs.end_idx,
                level=last.level
            )
        else:
            merged.append(zs)
    
    # 重新编号
    for idx, zs in enumerate(merged):
        zs.idx = idx
    
    return merged


# ==================== 第六步：背驰判断（MACD版） ====================

def _bi_amplitude(bi: Bi) -> float:
    """计算笔的价格幅度（绝对值）"""
    return abs(bi.end_price - bi.begin_price)


def _get_bi_macd_area(bi: Bi, kls: List[KL], is_reverse: bool = False) -> float:
    """计算笔的MACD面积
    
    MACD面积 = 笔区间内所有同向MACD柱的绝对值之和
    背驰：离开中枢的笔的MACD面积 < 进入中枢的笔的面积
    """
    begin_kl = kls[bi.begin_idx] if bi.begin_idx < len(kls) else None
    end_kl = kls[bi.end_idx] if bi.end_idx < len(kls) else None
    
    if begin_kl is None or end_kl is None:
        return abs(bi.end_price - bi.begin_price)
    
    idx_start = min(begin_kl.idx, end_kl.idx)
    idx_end = max(begin_kl.idx, end_kl.idx)
    
    area = 0.0
    for i in range(idx_start, min(idx_end + 1, len(kls))):
        kl = kls[i]
        if bi.dir == 'up' and kl.macd > 0:
            area += kl.macd
        elif bi.dir == 'down' and kl.macd < 0:
            area += abs(kl.macd)
    
    return area + 1e-7


def _find_fx_in_range(kls: List[KL], idx_start: int, idx_end: int, fx_type: str) -> Optional[Tuple[int, str, float]]:
    """在指定K线索引范围内查找指定类型的分型
    
    允许分型出现在范围的边缘（边界K线可以作为分型的左或右邻K线）
    这样当分型在笔的终点时，仍能被检测到。
    
    Args:
        kls: K线列表（合并处理后的）
        idx_start: 起始K线索引（原始idx）
        idx_end: 结束K线索引（原始idx）
        fx_type: 'bottom' 或 'top'
        
    Returns:
        Tuple(kl_idx, fx_type, price) 或 None
    """
    # 在 kls 中找到 idx_start 到 idx_end 范围内的K线
    # kls 中的每个 KL 的 idx 是原始索引
    seg_kls = [kl for kl in kls if idx_start <= kl.idx <= idx_end]
    
    if len(seg_kls) < 3:
        return None
    
    # 方法：在全局K线列表中搜索，以分型中间K线为基准
    # 只要分型的中间K线在范围内，就认为分型在范围内
    # 注意：分型的左右邻K线可以在范围外
    
    # 首先建立 idx -> KL 的映射
    kl_dict: Dict[int, KL] = {kl.idx: kl for kl in kls}
    
    # 在 idx_start 到 idx_end 范围内找分型（中间K线在范围内）
    for i in range(idx_start, idx_end + 1):
        kl = kl_dict.get(i)
        if kl is None:
            continue
        
        # 找左右邻K线（可能在范围外，但必须在 kls 中）
        left_idx = i - 1
        right_idx = i + 1
        left_kl = kl_dict.get(left_idx)
        right_kl = kl_dict.get(right_idx)
        
        if left_kl is None or right_kl is None:
            continue
        
        if fx_type == 'bottom':
            if kl.high < left_kl.high and kl.high < right_kl.high and \
               kl.low < left_kl.low and kl.low < right_kl.low:
                return (kl.idx, 'bottom', kl.low)
        else:  # 'top'
            if kl.high > left_kl.high and kl.high > right_kl.high and \
               kl.low > left_kl.low and kl.low > right_kl.low:
                return (kl.idx, 'top', kl.high)
    
    return None


def _has_bottom_fx_in_bi(bi: Bi, kls: List[KL]) -> bool:
    """检查笔的K线范围内是否存在底分型
    
    Args:
        bi: 笔对象
        kls: K线列表
        
    Returns:
        True if 底分型 exists in bi's range
    """
    idx_start = min(bi.begin_idx, bi.end_idx)
    idx_end = max(bi.begin_idx, bi.end_idx)
    return _find_fx_in_range(kls, idx_start, idx_end, 'bottom') is not None


def _has_top_fx_in_bi(bi: Bi, kls: List[KL]) -> bool:
    """检查笔的K线范围内是否存在顶分型"""
    idx_start = min(bi.begin_idx, bi.end_idx)
    idx_end = max(bi.begin_idx, bi.end_idx)
    return _find_fx_in_range(kls, idx_start, idx_end, 'top') is not None


def check_beichi(bi_in: Bi, bi_out: Bi, kls: List[KL],
                  method: str = 'macd') -> Tuple[bool, float]:
    """检查背驰（MACD版）
    
    Args:
        bi_in: 进入中枢的笔
        bi_out: 离开中枢的笔
        kls: K线列表（含MACD）
        method: 'macd'(面积) / 'peak'(峰值) / 'slope'(斜率) / 'price'(价格幅度)
        
    Returns:
        Tuple(是否背驰, 背驰比率)
    """
    if method == 'macd':
        in_metric = _get_bi_macd_area(bi_in, kls, is_reverse=False)
        out_metric = _get_bi_macd_area(bi_out, kls, is_reverse=True)
    elif method == 'peak':
        idx_start = min(bi_in.begin_idx, bi_in.end_idx)
        idx_end = max(bi_in.begin_idx, bi_in.end_idx)
        macd_values = [abs(kls[i].macd) for i in range(idx_start, min(idx_end + 1, len(kls))) if kls]
        in_peak = max(macd_values) if macd_values else 1e-7
        idx_start = min(bi_out.begin_idx, bi_out.end_idx)
        idx_end = max(bi_out.begin_idx, bi_out.end_idx)
        macd_values = [abs(kls[i].macd) for i in range(idx_start, min(idx_end + 1, len(kls))) if kls]
        out_peak = max(macd_values) if macd_values else 1e-7
        in_metric = in_peak
        out_metric = out_peak
    elif method == 'slope':
        in_metric = abs(bi_in.end_price - bi_in.begin_price) / max(1, abs(bi_in.end_idx - bi_in.begin_idx))
        out_metric = abs(bi_out.end_price - bi_out.begin_price) / max(1, abs(bi_out.end_idx - bi_out.begin_idx))
    else:  # price
        in_metric = abs(bi_in.end_price - bi_in.begin_price)
        out_metric = abs(bi_out.end_price - bi_out.begin_price)
    
    if in_metric == 0:
        return False, 0.0
    
    ratio = out_metric / in_metric
    # 背驰：离开段力度 < 进入段力度 * 0.8
    return ratio < 0.8, ratio


# ==================== 第七步：买卖点（严格买卖点标准） ====================

# ==================== 严格买卖点配置参数（增强版）====================
# 参考 chan_py_external/BuySellPoint/BSPointConfig.py

class BSPointConfig:
    """买卖点配置类（支持独立配置多空方向）
    
    新增参数：
    - divergence_rate: 背驰比率阈值（离开段/进入段 < 此值才算背驰）
    - max_bs2_rate: 2买回落比率上限（回落幅度/突破幅度 <= 此值）
    - macd_algo: MACD算法类型 ('area', 'peak', 'slope', 'amp', 'diff', 'half')
    """
    
    def __init__(self, **kwargs):
        # 背驰判断：离开段指标 < divergence_rate * 进入段指标 才算背驰
        # 注意：使用 None 表示无穷大（不限制），避免 JSON 序列化问题
        self.divergence_rate = kwargs.get('divergence_rate', None)
        
        # 2买回落比率：回落幅度/突破幅度 <= max_bs2_rate
        self.max_bs2_rate = kwargs.get('max_bs2_rate', 0.9999)
        
        # MACD算法类型
        self.macd_algo = kwargs.get('macd_algo', 'area')
        
        # 原有参数
        self.max_bs2_retrace_rate = kwargs.get('max_bs2_retrace_rate', 1.0)
        self.min_bs3_break_ratio = kwargs.get('min_bs3_break_ratio', 0.3)
        self.bs3_price_margin = kwargs.get('bs3_price_margin', 0.002)
        self.beichi_threshold = kwargs.get('beichi_threshold', 0.8)
        self.max_3buy_count = kwargs.get('max_3buy_count', 3)
        self.max_3sell_count = kwargs.get('max_3sell_count', 3)
        
        # 验证
        assert self.max_bs2_rate <= 1.0, "max_bs2_rate must be <= 1"
    
    def __repr__(self):
        return (f"BSPointConfig(divergence_rate={self.divergence_rate}, "
                f"max_bs2_rate={self.max_bs2_rate}, macd_algo={self.macd_algo})")


# 全局默认配置（向后兼容）
BSPointConfigDefault = {
    'divergence_rate': None,  # 背驰比率阈值（None=无穷大=不使用）
    'max_bs2_rate': 0.9999,           # 2买回落比率上限
    'macd_algo': 'area',               # MACD算法
    'max_bs2_retrace_rate': 1.0,
    'min_bs3_break_ratio': 0.3,
    'bs3_price_margin': 0.002,
    'beichi_threshold': 0.8,
    'max_3buy_count': 3,
    'max_3sell_count': 3,
}


def find_bs_points(bis: List[Bi], zss: List[ZS], kls: List[KL],
                   config=None) -> List[BSPoint]:
    """寻找买卖点 - 严格标准（增强版）
    
    严格条件：
    - 1买：下跌背驰（MACD面积衰竭）+ 创新低后反弹
    - 2买：一买后，UP笔回落不破一买 + 回落形成底分型 + 回落幅度合理
    - 3买：突破中枢 + 突破幅度足够 + 回落形成底分型 + 回落不破中枢高点
    
    新增参数（通过config传入）：
    - divergence_rate: 背驰比率阈值（离开段/进入段 < 此值才算背驰）
    - max_bs2_rate: 2买回落比率上限（回落幅度/突破幅度 <= 此值）
    - macd_algo: MACD算法类型 ('area', 'peak', 'slope', 'amp', 'diff', 'half')
    
    卖点反之
    """
    # 处理config参数（兼容旧版dict和新版BSPointConfig）
    if config is None:
        config = BSPointConfig(**BSPointConfigDefault)
    elif isinstance(config, dict):
        # 合并默认配置和传入配置
        merged_config = {**BSPointConfigDefault, **config}
        config = BSPointConfig(**merged_config)
    
    # 确保config是BSPointConfig对象
    if not isinstance(config, BSPointConfig):
        config = BSPointConfig(**BSPointConfigDefault)
    
    if len(bis) < 5 or not zss:
        return []
    
    bs_points: List[BSPoint] = []
    bs_idx = 0
    kls_dict = {kl.idx: kl for kl in kls}
    
    # 获取最近的中枢
    recent_zs = zss[-1]
    zs_low, zs_high = recent_zs.low, recent_zs.high
    zs_begin_bi_idx = recent_zs.begin_idx
    zs_end_bi_idx = recent_zs.end_idx
    zs_range = zs_high - zs_low
    
    # 找进入中枢的笔和离开中枢的笔
    in_bi = None
    out_bi = None
    for i, b in enumerate(bis):
        if b.begin_idx >= zs_begin_bi_idx and b.end_idx <= zs_end_bi_idx:
            if in_bi is None:
                in_bi = b
            out_bi = b  # 最后一笔在区间内
    
    if in_bi is None or out_bi is None:
        return []
    
    # ==================== 买点 ====================
    
    # -------- 1买：下跌背驰（严格化）--------
    # 条件：
    # 1. 连续下跌（创新低）
    # 2. 下跌段本身有底分型（衰竭信号）
    # 3. 后续UP笔MACD背驰（离开段 < 进入段）
    for i in range(1, len(bis) - 2):
        prev_bi = bis[i - 1]
        curr_bi = bis[i]
        next_bi = bis[i + 1]
        
        if curr_bi.dir == 'down' and next_bi.dir == 'up':
            curr_low = min(curr_bi.begin_price, curr_bi.end_price)
            prev_low = min(prev_bi.begin_price, prev_bi.end_price)
            
            # 条件1：创新低
            if curr_low >= prev_low:
                continue
            
            # 条件2：下跌段形成底分型（至少内部有反弹迹象）
            # 检查前一UP笔是否有顶分型（说明进入段有内部结构）
            has_in_structure = prev_bi.dir == 'up' and _has_top_fx_in_bi(prev_bi, kls)
            
            # 条件3：MACD背驰判断：next_bi(离开段) vs curr_bi(进入段)
            # 使用config中的macd_algo
            is_beichi, ratio = check_beichi(curr_bi, next_bi, kls, method=config.macd_algo)
            
            # 1买确认：创新低 + MACD背驰（使用config中的divergence_rate）
            # divergence_rate为None表示无穷大（即不限制）
            if is_beichi and (config.divergence_rate is None or ratio < config.divergence_rate):
                curr_kl = kls_dict.get(next_bi.end_idx)
                if curr_kl:
                    reason_parts = [f"MACD背驰(比率={ratio:.2f}, 算法={config.macd_algo})"]
                    if has_in_structure:
                        reason_parts.append("进入段有顶分型")
                    bs_points.append(BSPoint(
                        idx=bs_idx, type='1buy', direction='long',
                        price=curr_kl.low, bi_idx=next_bi.idx,
                        reason="; ".join(reason_parts)
                    ))
                    bs_idx += 1
                    break
    
    # -------- 2买：严格化 --------
    # 严格条件（参考 chan_py_external BSPointList.treat_bsp2）:
    # 1. 回落段必须是向下笔
    # 2. 回落段的低点不能跌破一买的位置（一买K线区间内）
    # 3. 回落段必须形成底分型（用 _has_bottom_fx_in_bi 验证）
    # 4. 回落幅度/突破幅度 <= max_bs2_rate（不能回落太深）
    if bs_points and bs_points[0].type == '1buy':
        first_buy = bs_points[0]
        first_bi_obj = bis[first_buy.bi_idx]
        first_buy_price = min(first_bi_obj.begin_price, first_bi_obj.end_price)
        first_buy_low = first_buy_price  # 一买的实际低点
        
        for i in range(first_buy.bi_idx + 1, len(bis) - 1):
            bi = bis[i]
            next_bi = bis[i + 1]
            
            # UP笔后DOWN笔（回落）
            if bi.dir != 'up' or next_bi.dir != 'down':
                continue
            
            break_bi = bi          # 突破笔（一买后的上涨）
            retr_bi = next_bi      # 回落笔
            
            next_low = min(retr_bi.begin_price, retr_bi.end_price)
            break_amp = _bi_amplitude(break_bi)  # 突破幅度
            retr_amp = _bi_amplitude(retr_bi)    # 回落幅度
            
            # 条件1：回落不破一买（允许0.2%误差）
            if next_low < first_buy_low * (1 - config.bs3_price_margin):
                continue
            
            # 条件2：回落段必须形成底分型（严格验证）
            if not _has_bottom_fx_in_bi(retr_bi, kls):
                continue
            
            # 条件3：回落幅度/突破幅度 <= max_bs2_rate
            # 使用config中的max_bs2_rate代替max_bs2_retrace_rate
            if break_amp <= 0:
                continue
            retrace_rate = retr_amp / break_amp
            if retrace_rate > config.max_bs2_rate:
                continue
            
            # 条件4：回落后的下一笔应该是UP（确认回落结束）
            if i + 2 < len(bis) and bis[i + 2].dir == 'up':
                curr_kl = kls_dict.get(retr_bi.end_idx)
                if curr_kl:
                    bs_points.append(BSPoint(
                        idx=bs_idx, type='2buy', direction='long',
                        price=curr_kl.low, bi_idx=retr_bi.idx,
                        reason=f"回落不破一买(回落率={retrace_rate:.2f}, max_bs2_rate={config.max_bs2_rate:.2f})"
                    ))
                    bs_idx += 1
                    break
    
    # -------- 3买：严格化 --------
    # 严格条件（参考 chan_py_external bsp3_back2zs）:
    # 1. 向上笔高点突破中枢高点（必须是真正突破）
    # 2. 突破幅度/中枢区间 >= min_bs3_break_ratio（不能勉强突破）
    # 3. 回落段必须是向下笔
    # 4. 回落段的低点不能有效跌破中枢高点（允许微小误差）
    # 5. 回落段必须形成底分型（验证回落有效性）
    break_count = 0
    for i in range(len(bis) - 1):
        if break_count >= config.max_3buy_count:
            break
        bi = bis[i]
        next_bi = bis[i + 1]
        
        if bi.dir != 'up' or next_bi.dir != 'down':
            continue
        
        bi_high = max(bi.begin_price, bi.end_price)
        next_low = min(next_bi.begin_price, next_bi.end_price)
        
        # 条件1：向上笔高点必须突破中枢高点
        if bi_high <= zs_high:
            continue
        
        # 条件2：突破幅度必须足够大（至少中枢区间的30%）
        break_range = bi_high - zs_high
        if zs_range > 0 and break_range < zs_range * config.min_bs3_break_ratio:
            continue
        
        # 条件3：回落不破中枢高点（允许0.2%误差）
        if next_low < zs_high * (1 - config.bs3_price_margin):
            continue
        
        # 条件4：回落段必须形成底分型（严格验证）
        if not _has_bottom_fx_in_bi(next_bi, kls):
            continue
        
        # 条件5：回落后的下一笔应该是UP
        if i + 2 < len(bis) and bis[i + 2].dir == 'up':
            curr_kl = kls_dict.get(next_bi.end_idx)
            if curr_kl:
                bs_points.append(BSPoint(
                    idx=bs_idx, type='3buy', direction='long',
                    price=curr_kl.low, bi_idx=next_bi.idx,
                    reason=f"突破({break_range:.0f}点)回落不破中枢"
                ))
                bs_idx += 1
                break_count += 1
    
    # ==================== 卖点（对称严格化） ====================
    
    # -------- 1卖：上涨背驰 --------
    for i in range(1, len(bis) - 2):
        prev_bi = bis[i - 1]
        curr_bi = bis[i]
        next_bi = bis[i + 1]
        
        if curr_bi.dir == 'up' and next_bi.dir == 'down':
            curr_high = max(curr_bi.begin_price, curr_bi.end_price)
            prev_high = max(prev_bi.begin_price, prev_bi.end_price)
            
            # 创新高
            if curr_high <= prev_high:
                continue
            
            # 检查进入段是否有底分型结构
            has_in_structure = prev_bi.dir == 'down' and _has_bottom_fx_in_bi(prev_bi, kls)
            
            # MACD背驰判断
            is_beichi, ratio = check_beichi(curr_bi, next_bi, kls, method=config.macd_algo)
            if is_beichi and (config.divergence_rate is None or ratio < config.divergence_rate):
                curr_kl = kls_dict.get(next_bi.end_idx)
                if curr_kl:
                    reason_parts = [f"MACD背驰(比率={ratio:.2f}, 算法={config.macd_algo})"]
                    if has_in_structure:
                        reason_parts.append("进入段有底分型")
                    bs_points.append(BSPoint(
                        idx=bs_idx, type='1sell', direction='short',
                        price=curr_kl.high, bi_idx=next_bi.idx,
                        reason="; ".join(reason_parts)
                    ))
                    bs_idx += 1
                    break
    
    # -------- 2卖：严格化 --------
    if any(p.type == '1sell' for p in bs_points):
        first_sell = next((p for p in bs_points if p.type == '1sell'), None)
        if first_sell:
            first_bi_obj = bis[first_sell.bi_idx]
            first_sell_price = max(first_bi_obj.begin_price, first_bi_obj.end_price)
            
            for i in range(first_sell.bi_idx + 1, len(bis) - 1):
                bi = bis[i]
                next_bi = bis[i + 1]
                
                if bi.dir != 'down' or next_bi.dir != 'up':
                    continue
                
                break_bi = bi        # 突破笔（一卖后的下跌）
                retr_bi = next_bi   # 反弹笔
                
                next_high = max(retr_bi.begin_price, retr_bi.end_price)
                break_amp = _bi_amplitude(break_bi)
                retr_amp = _bi_amplitude(retr_bi)
                
                # 条件1：反弹不破一卖（允许0.2%误差）
                if next_high > first_sell_price * (1 + config.bs3_price_margin):
                    continue
                
                # 条件2：反弹段必须形成顶分型
                if not _has_top_fx_in_bi(retr_bi, kls):
                    continue
                
                # 条件3：反弹幅度/突破幅度 <= max_bs2_rate
                if break_amp <= 0:
                    continue
                retrace_rate = retr_amp / break_amp
                if retrace_rate > config.max_bs2_rate:
                    continue
                
                # 条件4：反弹后下一笔是DOWN
                if i + 2 < len(bis) and bis[i + 2].dir == 'down':
                    curr_kl = kls_dict.get(retr_bi.end_idx)
                    if curr_kl:
                        bs_points.append(BSPoint(
                            idx=bs_idx, type='2sell', direction='short',
                            price=curr_kl.high, bi_idx=retr_bi.idx,
                            reason=f"反弹不破一卖(反弹率={retrace_rate:.2f})"
                        ))
                        bs_idx += 1
                        break
    
    # -------- 3卖：严格化 --------
    break_count_sell = 0
    price_margin = config.bs3_price_margin
    for i in range(len(bis) - 1):
        if break_count_sell >= config.max_3sell_count:
            break
        bi = bis[i]
        next_bi = bis[i + 1]
        
        if bi.dir != 'down' or next_bi.dir != 'up':
            continue
        
        bi_low = min(bi.begin_price, bi.end_price)
        next_high = max(next_bi.begin_price, next_bi.end_price)
        
        # 条件1：向下笔低点跌破中枢低点
        if bi_low >= zs_low:
            continue
        
        # 条件2：跌破幅度必须足够大
        break_range = zs_low - bi_low
        if zs_range > 0 and break_range < zs_range * config.min_bs3_break_ratio:
            continue
        
        # 条件3：反弹不破中枢低点
        if next_high > zs_low * (1 + price_margin):
            continue
        
        # 条件4：反弹段必须形成顶分型
        if not _has_top_fx_in_bi(next_bi, kls):
            continue
        
        # 条件5：反弹后下一笔是DOWN
        if i + 2 < len(bis) and bis[i + 2].dir == 'down':
            curr_kl = kls_dict.get(next_bi.end_idx)
            if curr_kl:
                bs_points.append(BSPoint(
                    idx=bs_idx, type='3sell', direction='short',
                    price=curr_kl.high, bi_idx=next_bi.idx,
                    reason=f"跌破({break_range:.0f}点)反弹不破中枢"
                ))
                bs_idx += 1
                break_count_sell += 1
    
    return bs_points


# ==================== 主分析函数 ====================

def analyze_chan(df, min_k: int = 4, small_bi_points: int = 30) -> Dict[str, Any]:
    """完整的缠论分析流程
    
    Args:
        df: 包含K线数据的DataFrame
        min_k: 标准笔最小K线数
        small_bi_points: 小笔最小价格幅度
        
    Returns:
        包含所有分析结果的字典
    """
    print("=" * 60)
    print("缠论核心算法分析")
    print("=" * 60)
    
    # Step 1: 转换为KL列表
    print("\n[Step 1] 转换K线数据...")
    kls = kl_to_kls(df)
    print(f"  原始K线数量: {len(kls)}")
    
    # Step 2: 处理包含关系
    print("\n[Step 2] 处理K线包含关系...")
    kls_merged = merge_include(kls)
    print(f"  处理后K线数量: {len(kls_merged)}")
    print(f"  合并数量: {len(kls) - len(kls_merged)}")
    
    # Step 3: 识别分型
    print("\n[Step 3] 识别分型...")
    fenxing = find_fenxing(kls_merged, min_gap=1)
    print(f"  识别到分型数量: {len(fenxing)}")
    top_count = sum(1 for fx in fenxing if fx[1] == 'top')
    bottom_count = sum(1 for fx in fenxing if fx[1] == 'bottom')
    print(f"    顶分型: {top_count}")
    print(f"    底分型: {bottom_count}")
    
    # Step 4: 构建笔
    print("\n[Step 4] 构建笔...")
    bis = build_bi(kls_merged, fenxing, min_k=min_k, small_bi_points=small_bi_points)
    print(f"  构建笔数量: {len(bis)}")
    up_bi_count = sum(1 for b in bis if b.dir == 'up')
    down_bi_count = sum(1 for b in bis if b.dir == 'down')
    print(f"    向上笔: {up_bi_count}")
    print(f"    向下笔: {down_bi_count}")
    
    # Step 5: 构建线段
    print("\n[Step 5] 构建线段...")
    segs = build_seg(bis)
    print(f"  构建线段数量: {len(segs)}")
    
    # Step 6: 构建中枢
    print("\n[Step 6] 构建中枢...")
    zss = build_zs(segs)
    print(f"  构建中枢数量: {len(zss)}")
    for zs in zss:
        print(f"    中枢{zs.idx}: [{zs.low:.2f}, {zs.high:.2f}]")
    
    # Step 7: 识别买卖点
    print("\n[Step 7] 识别买卖点...")
    bs_points = find_bs_points(bis, zss, kls_merged)
    print(f"  买卖点数量: {len(bs_points)}")
    for bp in bs_points:
        print(f"    {bp.type}: 价格={bp.price:.2f}, 原因={bp.reason}")
    
    print("\n" + "=" * 60)
    
    return {
        'kls': kls,
        'kls_merged': kls_merged,
        'fenxing': fenxing,
        'bis': bis,
        'segs': segs,
        'zss': zss,
        'bs_points': bs_points
    }


# ==================== 可视化函数 ====================

def plot_chan_chart(result: Dict[str, Any], output_path: str = None,
                    title: str = "缠论分析"):
    """绘制缠论分析图表
    
    Args:
        result: analyze_chan返回的结果字典
        output_path: 输出文件路径
        title: 图表标题
    """
    if not HAS_MATPLOTLIB:
        print("matplotlib不可用，跳过绘图")
        return
    
    kls = result['kls_merged']
    bis = result['bis']
    segs = result['segs']
    zss = result['zss']
    bs_points = result['bs_points']
    
    if len(kls) == 0:
        print("无K线数据可绘制")
        return
    
    # 创建图表
    fig, ax = plt.subplots(figsize=(20, 10))
    
    # 提取价格数据
    times = list(range(len(kls)))
    opens = [kl.open for kl in kls]
    highs = [kl.high for kl in kls]
    lows = [kl.low for kl in kls]
    closes = [kl.close for kl in kls]
    
    # 绘制K线蜡烛图
    for i, kl in enumerate(kls):
        color = 'red' if kl.close >= kl.open else 'green'
        # 绘制上下影线
        ax.plot([i, i], [kl.low, kl.high], color=color, linewidth=0.8)
        # 绘制实体
        body_bottom = min(kl.open, kl.close)
        body_top = max(kl.open, kl.close)
        height = max(body_top - body_bottom, 0.1)
        rect = patches.Rectangle((i - 0.3, body_bottom), 0.6, height,
                                   linewidth=0.5, edgecolor=color, facecolor=color)
        ax.add_patch(rect)
    
    # 绘制笔
    for bi in bis:
        # 找到对应的x位置
        begin_x = None
        end_x = None
        for j, kl in enumerate(kls):
            if kl.idx == bi.begin_idx:
                begin_x = j
            if kl.idx == bi.end_idx:
                end_x = j
            if begin_x and end_x:
                break
        
        if begin_x is None or end_x is None:
            continue
        
        color = 'orange' if bi.dir == 'up' else 'blue'
        linewidth = 2.0
        ax.plot([begin_x, end_x], [bi.begin_price, bi.end_price],
                color=color, linewidth=linewidth, alpha=0.8)
    
    # 绘制线段
    for seg in segs:
        begin_x = None
        end_x = None
        for j, kl in enumerate(kls):
            if kl.idx == seg.begin_idx:
                begin_x = j
            if kl.idx == seg.end_idx:
                end_x = j
            if begin_x and end_x:
                break
        
        if begin_x is None or end_x is None:
            continue
        
        color = 'magenta' if seg.dir == 'up' else 'cyan'
        linewidth = 3.0
        ax.plot([begin_x, end_x], [seg.begin_price, seg.end_price],
                color=color, linewidth=linewidth, alpha=1.0)
    
    # 绘制分型
    for fx_idx, fx_type, fx_price in result['fenxing']:
        for j, kl in enumerate(kls):
            if kl.idx == fx_idx:
                x = j
                break
        else:
            continue
        
        if fx_type == 'top':
            marker = '^'
            color = 'red'
        else:
            marker = 'v'
            color = 'green'
        ax.scatter(x, fx_price, marker=marker, color=color, s=100, zorder=5)
    
    # 绘制中枢
    for zs in zss:
        # 找到对应的x位置
        begin_x = None
        end_x = None
        for j, kl in enumerate(kls):
            if kl.idx == zs.begin_idx:
                begin_x = j
            if kl.idx == zs.end_idx:
                end_x = j
            if begin_x and end_x:
                break
        
        if begin_x is None or end_x is None:
            continue
        
        width = end_x - begin_x + 1
        height = zs.high - zs.low
        rect = patches.Rectangle((begin_x - 0.5, zs.low), width, height,
                                   linewidth=1, edgecolor='gray', facecolor='yellow',
                                   alpha=0.3)
        ax.add_patch(rect)
    
    # 绘制买卖点
    for bp in bs_points:
        # 找到对应的x位置
        for j, kl in enumerate(kls):
            if kl.idx == bis[bp.bi_idx].end_idx if bp.bi_idx < len(bis) else False:
                x = j
                break
        else:
            continue
        
        if 'buy' in bp.type:
            marker = '*'
            color = 'red'
        else:
            marker = '*'
            color = 'green'
        ax.scatter(x, bp.price, marker=marker, color=color, s=300, zorder=10)
    
    # 设置图表属性
    ax.set_xlim(-1, len(kls))
    price_min = min(kl.low for kl in kls)
    price_max = max(kl.high for kl in kls)
    ax.set_ylim(price_min - 10, price_max + 10)
    ax.set_title(title, fontsize=16)
    ax.set_xlabel('K线索引')
    ax.set_ylabel('价格')
    ax.grid(True, alpha=0.3)
    
    # 添加图例
    legend_elements = [
        patches.Patch(facecolor='red', label='K线（涨）'),
        patches.Patch(facecolor='green', label='K线（跌）'),
        plt.Line2D([0], [0], color='orange', linewidth=2, label='向上笔'),
        plt.Line2D([0], [0], color='blue', linewidth=2, label='向下笔'),
        plt.Line2D([0], [0], color='magenta', linewidth=3, label='向上线段'),
        plt.Line2D([0], [0], color='cyan', linewidth=3, label='向下线段'),
        plt.Line2D([0], [0], marker='^', color='w', markerfacecolor='red',
                   markersize=10, label='顶分型'),
        plt.Line2D([0], [0], marker='v', color='w', markerfacecolor='green',
                   markersize=10, label='底分型'),
    ]
    ax.legend(handles=legend_elements, loc='upper left', fontsize=8)
    
    plt.tight_layout()
    
    if output_path:
        plt.savefig(output_path, dpi=100, bbox_inches='tight')
        print(f"\n图表已保存到: {output_path}")
    
    plt.close()


# ==================== 多级别K线递归支持 ====================

def aggregate_klines_fixed(kls: List[KL], level: int) -> List[KL]:
    """将低级别K线按固定周期聚合成高级别K线
    
    级别对应：
    - level=1: 原始K线（返回副本）
    - level=2: 3合1（每3根K线合并为1根）
    - level=3: 5合1（每5根K线合并为1根）
    - level=4: 笔合并（基于笔区间聚合）
    
    Args:
        kls: 低级别K线列表
        level: 聚合级别
        
    Returns:
        高级别K线列表
    """
    if level <= 1 or len(kls) < level:
        return [KL(
            idx=kl.idx, time=kl.time, open=kl.open, high=kl.high,
            low=kl.low, close=kl.close, volume=kl.volume,
            dif=kl.dif, dea=kl.dea, macd=kl.macd
        ) for kl in kls]
    
    # 固定周期聚合
    factor = {2: 3, 3: 5, 4: 7}.get(level, 5)
    parent_kls: List[KL] = []
    
    for i in range(0, len(kls), factor):
        segment = kls[i:i + factor]
        if not segment:
            continue
        
        # 聚合规则
        parent_kl = KL(
            idx=len(parent_kls),
            time=segment[-1].time,
            open=segment[0].open,
            high=max(k.high for k in segment),
            low=min(k.low for k in segment),
            close=segment[-1].close,
            volume=sum(k.volume for k in segment),
            dif=segment[-1].dif,
            dea=segment[-1].dea,
            macd=segment[-1].macd
        )
        parent_kls.append(parent_kl)
    
    # 重新计算MACD（基于聚合后的收盘价）
    parent_kls = calculate_macd(parent_kls)
    return parent_kls


def aggregate_by_bi(kls: List[KL], bis: List[Bi]) -> List[KL]:
    """基于笔区间聚合K线 - 更准确的缠论方式
    
    每笔对应一段K线，将这段K线聚合成一根高级K线：
    - high = 这段K线的最高价
    - low = 这段K线的最低价
    - open = 这段第一根K线的开盘
    - close = 这段最后一根K线的收盘
    - volume = 这段K线的总成交量
    - time = 这段最后一根K线的时间
    
    Args:
        kls: 低级别K线列表
        bis: 笔列表（用于确定K线区间）
        
    Returns:
        高级别K线列表
    """
    if not bis or not kls:
        return []
    
    parent_kls: List[KL] = []
    for bi in bis:
        begin_idx = bi.begin_idx
        end_idx = bi.end_idx
        
        # 确保索引有效
        if begin_idx < 0 or end_idx < 0:
            continue
        if begin_idx >= len(kls) or end_idx >= len(kls):
            # 尝试用kls的位置找
            begin_pos = next((i for i, k in enumerate(kls) if k.idx == begin_idx), -1)
            end_pos = next((i for i, k in enumerate(kls) if k.idx == end_idx), -1)
            if begin_pos < 0 or end_pos < 0:
                continue
            segment = kls[begin_pos:end_pos + 1]
        else:
            segment = kls[begin_idx:end_idx + 1]
        
        if not segment:
            continue
        
        parent_kl = KL(
            idx=len(parent_kls),
            time=segment[-1].time,
            open=segment[0].open,
            high=max(k.high for k in segment),
            low=min(k.low for k in segment),
            close=segment[-1].close,
            volume=sum(k.volume for k in segment),
            dif=segment[-1].dif,
            dea=segment[-1].dea,
            macd=segment[-1].macd
        )
        parent_kls.append(parent_kl)
    
    # 重新计算MACD
    if parent_kls:
        parent_kls = calculate_macd(parent_kls)
    return parent_kls


def _build_level_kls(kls: List[KL], level: int, bis: List[Bi] = None) -> List[KL]:
    """根据级别构建对应的K线列表
    
    Args:
        kls: 原始K线列表（level=1）
        level: 目标级别
        bis: 可选的笔列表（用于bi-based聚合）
        
    Returns:
        对应级别的K线列表
    """
    if level <= 1:
        return kls
    
    if level == 4 and bis:
        # 笔合并方式
        return aggregate_by_bi(kls, bis)
    else:
        # 固定周期聚合
        return aggregate_klines_fixed(kls, level)


def analyze_level(kls: List[KL], level: int = 1, 
                   min_k: int = 4, small_bi_points: int = 30,
                   bis_input: List[Bi] = None) -> Dict[str, Any]:
    """对单个级别进行完整的缠论分析
    
    Args:
        kls: K线列表
        level: 级别 (1=原始, 2=3合1, 3=5合1, 4=笔合并)
        min_k: 标准笔最小K线数
        small_bi_points: 小笔最小价格幅度
        bis_input: 可选，输入的笔列表（用于基于笔的聚合）
        
    Returns:
        该级别的分析结果字典
    """
    if len(kls) < 3:
        return {
            'level': level,
            'kls': kls,
            'kls_merged': kls,
            'fenxing': [],
            'bis': [],
            'segs': [],
            'zss': [],
            'bs_points': []
        }
    
    # 处理包含关系
    kls_merged = merge_include(kls)
    
    # 识别分型
    fenxing = find_fenxing(kls_merged, min_gap=1)
    
    # 构建笔
    bis = build_bi(kls_merged, fenxing, min_k=min_k, small_bi_points=small_bi_points)
    
    # 构建线段
    segs = build_seg(bis)
    
    # 构建中枢
    zss = build_zs(segs)
    
    # 识别买卖点
    bs_points = find_bs_points(bis, zss, kls_merged)
    
    return {
        'level': level,
        'kls': kls,
        'kls_merged': kls_merged,
        'fenxing': fenxing,
        'bis': bis,
        'segs': segs,
        'zss': zss,
        'bs_points': bs_points
    }


def multi_level_analysis(df, max_level: int = 4,
                          min_k: int = 4, small_bi_points: int = 30) -> Dict[int, Dict[str, Any]]:
    """多级别缠论分析
    
    从低级别K线聚合出高级别K线，形成父-子关系，逐级分析。
    
    Args:
        df: 原始K线DataFrame
        max_level: 最大级别数 (1=原始, 2=3合1, 3=5合1, 4=笔合并)
        min_k: 标准笔最小K线数
        small_bi_points: 小笔最小价格幅度
        
    Returns:
        dict: {level: {'kls': [...], 'bis': [...], 'segs': [...], 'zss': [...], 'bs_points': [...]}}
        level=1 是原始分析结果，level=2/3/4 是聚合后的分析结果
    """
    print("=" * 60)
    print(f"多级别缠论分析 (最大级别: {max_level})")
    print("=" * 60)
    
    # Step 1: 转换为KL列表（原始级别）
    print(f"\n[Level 1] 转换K线数据...")
    kls = kl_to_kls(df)
    print(f"  原始K线数量: {len(kls)}")
    
    # Level 1 分析（基准）
    result_l1 = analyze_level(kls, level=1, min_k=min_k, small_bi_points=small_bi_points)
    results = {1: result_l1}
    
    # 逐级向上分析
    for level in range(2, max_level + 1):
        print(f"\n[Level {level}] 聚合K线并分析...")
        
        # 获取上一级别的K线或笔列表
        prev_result = results[level - 1]
        
        if level == 4:
            # 级别4：使用笔合并方式
            prev_kls = prev_result.get('kls', kls)  # 使用原始K线
            prev_bis = prev_result.get('bis', [])
            level_kls = _build_level_kls(prev_kls, level, bis_input=prev_bis)
        else:
            # 级别2/3：使用固定周期聚合
            level_kls = aggregate_klines_fixed(prev_result['kls'], level)
        
        kls_count = len(level_kls)
        print(f"  聚合后K线数量: {kls_count}")
        
        if kls_count < 5:
            print(f"  K线数量不足，跳过级别{level}")
            continue
        
        # 分析该级别
        result = analyze_level(level_kls, level=level, min_k=min_k, small_bi_points=small_bi_points)
        results[level] = result
        
        # 打印该级别统计
        print(f"  笔数量: {len(result['bis'])}")
        print(f"  线段数量: {len(result['segs'])}")
        print(f"  中枢数量: {len(result['zss'])}")
    
    print("\n" + "=" * 60)
    print("多级别分析完成")
    print("=" * 60)
    
    return results


def get_multi_level_summary(results: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    """获取多级别分析的汇总信息
    
    Args:
        results: multi_level_analysis 返回的结果
        
    Returns:
        汇总信息字典
    """
    summary = {
        'levels': [],
        'bi_trend': {},  # level -> 向上笔数/向下笔数
        'zs_summary': {},  # level -> 中枢区间
        'bs_signals': {}   # level -> 最新买卖点
    }
    
    for level in sorted(results.keys()):
        r = results[level]
        
        # 笔统计
        up_bis = [b for b in r['bis'] if b.dir == 'up']
        down_bis = [b for b in r['bis'] if b.dir == 'down']
        
        level_info = {
            'level': level,
            'kls_count': len(r['kls']),
            'bi_count': len(r['bis']),
            'seg_count': len(r['segs']),
            'zs_count': len(r['zss']),
            'bs_count': len(r['bs_points']),
            'up_bi_ratio': len(up_bis) / max(1, len(r['bis'])),
        }
        summary['levels'].append(level_info)
        summary['bi_trend'][level] = {'up': len(up_bis), 'down': len(down_bis)}
        
        # 中枢汇总
        if r['zss']:
            latest_zs = r['zss'][-1]
            summary['zs_summary'][level] = {
                'zs_count': len(r['zss']),
                'latest_zs': {'low': latest_zs.low, 'high': latest_zs.high}
            }
        
        # 最新买卖点
        if r['bs_points']:
            latest_bp = r['bs_points'][-1]
            summary['bs_signals'][level] = {
                'type': latest_bp.type,
                'direction': latest_bp.direction,
                'price': latest_bp.price,
                'reason': latest_bp.reason
            }
    
    return summary


# ==================== 测试代码 ====================

if __name__ == '__main__':
    print("开始缠论核心算法测试...")
    print()
    
    try:
        import akshare as ak
        print("正在获取PTA真实数据...")
        df = ak.futures_zh_minute_sina(symbol='TA0', period='1')
        df = df.tail(300)
        print(f"获取到 {len(df)} 根K线")
        print()
    except Exception as e:
        print(f"获取数据失败: {e}")
        print("使用模拟数据进行测试...")
        
        import pandas as pd
        import numpy as np
        
        np.random.seed(42)
        n = 300
        base_price = 5800
        data = []
        price = base_price
        
        for i in range(n):
            time_str = f"2024-01-01 {i % 24:02d}:{i % 60:02d}:00"
            open_p = price
            close_p = price + np.random.randn() * 20
            high_p = max(open_p, close_p) + abs(np.random.randn()) * 10
            low_p = min(open_p, close_p) - abs(np.random.randn()) * 10
            volume = np.random.randint(1000, 10000)
            
            data.append({
                'time': time_str,
                'open': open_p,
                'high': high_p,
                'low': low_p,
                'close': close_p,
                'volume': volume
            })
            price = close_p
        
        df = pd.DataFrame(data)
    
    # 运行分析
    result = analyze_chan(df, min_k=4, small_bi_points=30)
    
    # 输出验证信息
    print("\n" + "=" * 60)
    print("验证信息:")
    print("=" * 60)
    print(f"笔数量: {len(result['bis'])} (预期20-50笔)")
    print(f"线段数量: {len(result['segs'])} (预期约笔数/3)")
    print(f"中枢数量: {len(result['zss'])}")
    print(f"买卖点数量: {len(result['bs_points'])}")
    
    # 绘制图表
    output_path = "/home/admin/.openclaw/workspace/Futures_Trading/pta_analysis/charts/chan_core_test.png"
    
    import os
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    print("\n正在生成图表...")
    try:
        plot_chan_chart(result, output_path, title="PTA缠论分析")
    except Exception as e:
        print(f"图表生成失败: {e}")
    
    print("\n测试完成!")

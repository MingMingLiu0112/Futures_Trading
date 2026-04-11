#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA期货期权一体化策略模块
集成：杀期权阶段识别、期权墙识别、PCR计算、缠论与期权共振信号

核心理念：用量化工具做数据采集和计算，人来做策略选择和执行。
"""

from __future__ import annotations
import re
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from enum import Enum

import numpy as np
import pandas as pd

# ==================== 常量定义 ====================

# 期权墙识别阈值
OPTION_WALL_MIN_OI = 10000  # 单档持仓量门槛
OPTION_WALL_DENSITY_RATIO = 1.5  # 密集度比率门槛

# PCR阈值
PCR_BEARISH_THRESHOLD = 1.0  # 偏空
PCR_BULLISH_THRESHOLD = 0.8  # 偏多

# 杀期权阶段判断
KILL_OPTION_NEAR_EXPIRY_DAYS = 7  # 临近到期天数


# ==================== 枚举类 ====================

class MarketRegime(Enum):
    """市场状态枚举"""
    CALM = "宏观平静期"           # 默认状态
    KILL_OPTION = "杀期权阶段"     # 期权到期前
    MACRO_DRIVE = "宏观驱动期"     # 重大事件驱动


class SignalDirection(Enum):
    """信号方向枚举"""
    LONG = "做多"
    SHORT = "做空"
    NEUTRAL = "中性"


class PCRSignal(Enum):
    """PCR信号枚举"""
    STRONG_BULLISH = "强烈偏多"
    BULLISH = "偏多"
    NEUTRAL = "中性"
    BEARISH = "偏空"
    STRONG_BEARISH = "强烈偏空"


class IVSkew(Enum):
    """IV曲线形态枚举"""
    LEFT_SKEW = "左偏"      # put IV > call IV, 市场担忧
    RIGHT_SKEW = "右偏"     # call IV > put IV, 市场乐观
    SYMMETRIC = "对称"      # 基本平衡


# ==================== 数据结构 ====================

@dataclass
class KLine:
    """简化K线数据结构"""
    idx: int
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class OptionWall:
    """期权墙数据结构"""
    strike: int           # 行权价
    option_type: str      # 'C' or 'P'
    oi: int               # 持仓量
    vol: int              # 成交量
    iv: Optional[float]   # 隐含波动率
    position: str         # 相对位置 (ATM-xxx, ATM, ATM+xxx)
    density_ratio: float  # 密集度比率
    is_wall: bool         # 是否为有效期权墙


@dataclass
class OptionStructure:
    """期权结构数据"""
    pcr: Optional[float]           # 持仓PCR
    tcv: int                        # 认购成交量
    tpv: int                        # 认沽成交量
    floor_walls: List[OptionWall]   # 地板防线（PUT支撑）
    ceil_walls: List[OptionWall]    # 天花板防线（CALL阻力）
    total_floor_oi: int             # 地板总OI
    total_ceil_oi: int              # 天花板总OI
    gradient_ratio: Optional[float] # 梯度比率
    call_iv: Optional[float]        # 认购IV
    put_iv: Optional[float]         # 认沽IV
    iv_diff: Optional[float]        # IV差
    iv_skew: IVSkew                # IV曲线形态
    score: int                      # 综合评分
    label: str                      # 信号标签
    detail: str                     # 详细描述


@dataclass
class KillOptionStage:
    """杀期权阶段识别结果"""
    is_active: bool                 # 是否处于杀期权阶段
    near_expiry: bool               # 是否临近到期
    expiry_date: Optional[str]       # 最近的到期日
    days_to_expiry: int             # 距离到期天数
    wall_clarity: float             # 期权墙清晰度 (0-1)
    has_option_wall: bool           # 是否有明确期权墙
    confidence: float               # 判断置信度 (0-1)


@dataclass
class ChanSignal:
    """缠论信号数据结构"""
    direction: SignalDirection       # 方向
    confidence: float                # 置信度 (0-1)
    reason: str                     # 原因描述
    price: float                    # 信号价格
    bi_type: Optional[str]           # 笔类型 (1buy/2buy/3buy/1sell/2sell/3sell)
    level: str                      # 级别 (5min/15min/1hour/1day)


@dataclass
class ResonanceSignal:
    """共振信号数据结构"""
    direction: SignalDirection       # 交易方向
    confidence: float                # 置信度 (0-1)
    regime: MarketRegime             # 市场状态
    chan_signal: Optional[ChanSignal]  # 缠论信号
    option_signal: Optional[OptionStructure]  # 期权信号
    共振依据: List[str]               # 共振依据列表
    risk_level: str                 # 风险等级 (高/中/低)
    action: str                     # 操作建议


# ==================== 辅助函数 ====================

def _parse_option_code(code: str) -> Tuple[Optional[int], str]:
    """从期权代码解析行权价和类型"""
    m = re.search(r'[CP](\d+)', str(code))
    strike = int(m.group(1)) if m else None
    option_type = 'C' if 'C' in str(code) else 'P'
    return strike, option_type


def _safe_float(x, default: Optional[float] = None) -> Optional[float]:
    """安全转换为浮点数"""
    try:
        return float(x)
    except:
        return default


def _calculate_density_ratio(oi: int, oi_prev: int, oi_next: int) -> float:
    """计算密集度比率"""
    avg_adjacent = (oi_prev + oi_next) / 2
    if avg_adjacent <= 0:
        return 0.0
    return oi / avg_adjacent


# ==================== 杀期权阶段识别 ====================

class KillOptionStageDetector:
    """杀期权阶段识别器
    
    判断逻辑：
    1. 临近到期（通常为近月期权到期前约7天）
    2. 期权墙明确（地板/天花板有明显的梯度性密集持仓）
    """
    
    def __init__(self, near_expiry_days: int = KILL_OPTION_NEAR_EXPIRY_DAYS):
        self.near_expiry_days = near_expiry_days
    
    def detect(self, option_data: pd.DataFrame, expiry_dates: List[str] = None) -> KillOptionStage:
        """检测是否处于杀期权阶段
        
        Args:
            option_data: 期权数据DataFrame
            expiry_dates: 可选的到期日期列表
            
        Returns:
            KillOptionStage: 杀期权阶段识别结果
        """
        now = datetime.now()
        
        # 1. 检查是否临近到期
        near_expiry = False
        nearest_expiry = None
        days_to_expiry = 999
        
        if expiry_dates:
            for exp_date in expiry_dates:
                try:
                    exp_dt = datetime.strptime(exp_date, '%Y%m%d')
                    days = (exp_dt - now).days
                    if 0 <= days <= self.near_expiry_days:
                        near_expiry = True
                        if days < days_to_expiry:
                            days_to_expiry = days
                            nearest_expiry = exp_date
                except:
                    continue
        
        # 2. 分析期权墙清晰度
        walls = self._detect_walls(option_data)
        has_clear_wall = len(walls) >= 2  # 至少2档明确的墙
        
        # 计算墙的清晰度（基于OI梯度）
        wall_clarity = 0.0
        if walls:
            total_oi = sum(w.oi for w in walls if w.is_wall)
            max_oi = max(w.oi for w in walls if w.is_wall) if walls else 0
            if total_oi > 0:
                wall_clarity = min(1.0, max_oi / (total_oi / len(walls)))
        
        # 3. 综合判断
        is_active = near_expiry and has_clear_wall
        confidence = min(1.0, (0.4 if near_expiry else 0) + (0.6 if has_clear_wall else 0))
        
        return KillOptionStage(
            is_active=is_active,
            near_expiry=near_expiry,
            expiry_date=nearest_expiry,
            days_to_expiry=days_to_expiry,
            wall_clarity=wall_clarity,
            has_option_wall=has_clear_wall,
            confidence=confidence
        )
    
    def _detect_walls(self, df: pd.DataFrame) -> List[OptionWall]:
        """检测期权墙"""
        walls = []
        
        if df is None or df.empty:
            return walls
        
        df = df.copy()
        df['k'] = df['合约代码'].apply(lambda x: _parse_option_code(x)[0])
        df['t'] = df['合约代码'].apply(lambda x: _parse_option_code(x)[1])
        
        # 按类型分组
        for opt_type in ['C', 'P']:
            subset = df[df['t'] == opt_type].copy()
            if subset.empty:
                continue
            
            # 按行权价排序
            subset = subset.sort_values('k')
            strikes = subset['k'].values
            
            for i, row in subset.iterrows():
                strike = row['k']
                oi = int(row.get('持仓量', 0) or 0)
                
                # 获取相邻档位的OI
                idx = list(subset['k'].values).index(strike)
                oi_prev = int(subset.iloc[idx-1]['持仓量']) if idx > 0 else 0
                oi_next = int(subset.iloc[idx+1]['持仓量']) if idx < len(subset) - 1 else 0
                
                density = _calculate_density_ratio(oi, oi_prev, oi_next)
                
                walls.append(OptionWall(
                    strike=int(strike),
                    option_type=opt_type,
                    oi=oi,
                    vol=int(row.get('成交量', 0) or 0),
                    iv=_safe_float(row.get('隐含波动率')),
                    position='',
                    density_ratio=density,
                    is_wall=(oi >= OPTION_WALL_MIN_OI and density >= OPTION_WALL_DENSITY_RATIO)
                ))
        
        return walls


# ==================== 期权墙识别 ====================

class OptionWallDetector:
    """期权墙识别器
    
    识别规则（需同时满足）：
    1. 绝对量门槛：单档行权价持仓量 ≥ 10000手
    2. 密集度判断：持仓量[K] / ((持仓量[K-1] + 持仓量[K+1]) / 2)) ≥ 1.5
    """
    
    def __init__(self, min_oi: int = OPTION_WALL_MIN_OI, density_ratio: float = OPTION_WALL_DENSITY_RATIO):
        self.min_oi = min_oi
        self.density_ratio = density_ratio
    
    def detect(self, df: pd.DataFrame, fp: float = None) -> Dict[str, Any]:
        """检测期权墙
        
        Args:
            df: 期权数据DataFrame，需包含 '合约代码', '持仓量', '成交量', '隐含波动率' 列
            fp: 平价期权行权价（ATM strike）
            
        Returns:
            Dict包含:
                - floor_walls: List[OptionWall] - 地板防线（PUT支撑）
                - ceil_walls: List[OptionWall] - 天花板防线（CALL阻力）
                - all_walls: List[OptionWall] - 所有识别的墙
        """
        if df is None or df.empty:
            return {'floor_walls': [], 'ceil_walls': [], 'all_walls': []}
        
        df = df.copy()
        
        # 解析期权代码
        df['k'] = df['合约代码'].apply(lambda x: _parse_option_code(x)[0])
        df['t'] = df['合约代码'].apply(lambda x: _parse_option_code(x)[1])
        
        # 如果没有提供ATM行权价，使用成交量最大的行权价
        if fp is None:
            atm_by_vol = df.groupby('k')['成交量'].sum().idxmax()
            fp = atm_by_vol
        
        c = df[df['t'] == 'C'].copy()  # 认购
        p = df[df['t'] == 'P'].copy()  # 认沽
        
        floor_walls = self._detect_walls_for_type(p, fp, 'P', 'floor')
        ceil_walls = self._detect_walls_for_type(c, fp, 'C', 'ceil')
        
        all_walls = floor_walls + ceil_walls
        
        return {
            'floor_walls': floor_walls,
            'ceil_walls': ceil_walls,
            'all_walls': all_walls,
            'fp': fp,
            'total_floor_oi': sum(w.oi for w in floor_walls),
            'total_ceil_oi': sum(w.oi for w in ceil_walls)
        }
    
    def _detect_walls_for_type(self, df: pd.DataFrame, fp: float, opt_type: str, zone: str) -> List[OptionWall]:
        """检测某一类型的期权墙
        
        Args:
            df: 该类型的期权数据
            fp: ATM行权价
            opt_type: 'C' or 'P'
            zone: 'floor' (地板) or 'ceil' (天花板)
        """
        walls = []
        
        if df.empty:
            return walls
        
        # 过滤极深度虚值
        if zone == 'floor':  # 地板（PUT支撑）在平价下方
            df = df[df['k'] >= fp * 0.78]
        else:  # 天花板（CALL阻力）在平价上方
            df = df[df['k'] <= fp * 1.30]
        
        # 按行权价排序
        df = df.sort_values('k')
        strikes = df['k'].tolist()
        
        for idx, row in df.iterrows():
            strike = int(row['k'])
            oi = int(row.get('持仓量', 0) or 0)
            vol = int(row.get('成交量', 0) or 0)
            
            # 获取相邻档位
            strike_idx = strikes.index(strike)
            oi_prev = int(df.iloc[strike_idx - 1]['持仓量']) if strike_idx > 0 else 0
            oi_next = int(df.iloc[strike_idx + 1]['持仓量']) if strike_idx < len(df) - 1 else 0
            
            density = _calculate_density_ratio(oi, oi_prev, oi_next)
            is_wall = (oi >= self.min_oi and density >= self.density_ratio)
            
            # 计算相对位置
            dist = strike - fp
            if dist == 0:
                position = 'ATM'
            elif dist > 0:
                position = f'ATM+{dist}'
            else:
                position = f'ATM{dist}'
            
            iv = _safe_float(row.get('隐含波动率'))
            
            wall = OptionWall(
                strike=strike,
                option_type=opt_type,
                oi=oi,
                vol=vol,
                iv=iv,
                position=position,
                density_ratio=density,
                is_wall=is_wall
            )
            
            if is_wall:
                walls.append(wall)
        
        # 按OI降序排列
        walls.sort(key=lambda x: x.oi, reverse=True)
        
        return walls


# ==================== PCR指标计算 ====================

class PCRMonitor:
    """PCR指标实时计算和预警
    
    PCR (Put/Call Ratio) 指标体系：
    - 持仓PCR = 认沽总持仓 / 认购总持仓
    - 成交PCR = 认沽总成交 / 认购总成交
    """
    
    def __init__(self, pcr_bearish: float = PCR_BEARISH_THRESHOLD, 
                 pcr_bullish: float = PCR_BULLISH_THRESHOLD):
        self.pcr_bearish = pcr_bearish
        self.pcr_bullish = pcr_bullish
    
    def calculate(self, df: pd.DataFrame) -> Dict[str, Any]:
        """计算PCR指标
        
        Args:
            df: 期权数据DataFrame
            
        Returns:
            Dict包含PCR计算结果
        """
        if df is None or df.empty:
            return {
                'position_pcr': None,
                'volume_pcr': None,
                'total_call_vol': 0,
                'total_put_vol': 0,
                'total_call_oi': 0,
                'total_put_oi': 0,
                'signal': PCRSignal.NEUTRAL,
                'label': '数据不足'
            }
        
        df = df.copy()
        df['t'] = df['合约代码'].apply(lambda x: _parse_option_code(x)[1])
        
        c = df[df['t'] == 'C']  # 认购
        p = df[df['t'] == 'P']  # 认沽
        
        # 成交量PCR
        tcv = int(c['成交量(手)'].sum()) if '成交量(手)' in c.columns else int(c['成交量'].sum()) if '成交量' in c.columns else 0
        tpv = int(p['成交量(手)'].sum()) if '成交量(手)' in p.columns else int(p['成交量'].sum()) if '成交量' in p.columns else 0
        vol_pcr = round(tpv / tcv, 4) if tcv > 0 else None
        
        # 持仓PCR
        try:
            tc_oi = int(c['持仓量'].sum()) if '持仓量' in c.columns else 0
            tp_oi = int(p['持仓量'].sum()) if '持仓量' in p.columns else 0
            pos_pcr = round(tp_oi / tc_oi, 4) if tc_oi > 0 else None
        except:
            pos_pcr = None
        
        # 判断信号
        signal = self._judge_signal(pos_pcr, vol_pcr)
        
        return {
            'position_pcr': pos_pcr,
            'volume_pcr': vol_pcr,
            'total_call_vol': tcv,
            'total_put_vol': tpv,
            'total_call_oi': tc_oi,
            'total_put_oi': tp_oi,
            'signal': signal,
            'label': signal.value
        }
    
    def _judge_signal(self, pos_pcr: Optional[float], vol_pcr: Optional[float]) -> PCRSignal:
        """根据PCR判断信号"""
        pcr = pos_pcr if pos_pcr is not None else vol_pcr
        
        if pcr is None:
            return PCRSignal.NEUTRAL
        
        if pcr > self.pcr_bearish * 1.5:
            return PCRSignal.STRONG_BEARISH
        elif pcr > self.pcr_bearish:
            return PCRSignal.BEARISH
        elif pcr < self.pcr_bullish * 0.6:
            return PCRSignal.STRONG_BULLISH
        elif pcr < self.pcr_bullish:
            return PCRSignal.BULLISH
        else:
            return PCRSignal.NEUTRAL
    
    def check_alert(self, pcr: float, threshold: float, direction: str) -> bool:
        """检查是否触发预警
        
        Args:
            pcr: 当前PCR值
            threshold: 阈值
            direction: 'above' or 'below'
            
        Returns:
            bool: 是否触发预警
        """
        if pcr is None:
            return False
        
        if direction == 'above':
            return pcr > threshold
        else:
            return pcr < threshold


# ==================== IV曲线分析 ====================

class IVAnalyzer:
    """隐含波动率曲线分析
    
    IV曲线形态：
    - 左偏（put IV > call IV）：市场担忧下跌风险
    - 右偏（call IV > put IV）：市场预期上涨
    """
    
    def __init__(self, skew_threshold: float = 5.0):
        self.skew_threshold = skew_threshold  # IV差阈值%
    
    def analyze(self, df: pd.DataFrame, fp: float) -> Dict[str, Any]:
        """分析IV曲线
        
        Args:
            df: 期权数据DataFrame
            fp: ATM行权价
            
        Returns:
            Dict包含IV分析结果
        """
        if df is None or df.empty:
            return {
                'call_iv': None,
                'put_iv': None,
                'iv_diff': None,
                'skew': IVSkew.SYMMETRIC,
                'label': '数据不足'
            }
        
        df = df.copy()
        df['k'] = df['合约代码'].apply(lambda x: _parse_option_code(x)[0])
        df['t'] = df['合约代码'].apply(lambda x: _parse_option_code(x)[1])
        
        # ATM附近（±3%）的IV
        lo_iv, hi_iv = int(fp * 0.97), int(fp * 1.03)
        
        c = df[(df['t'] == 'C') & (df['k'] >= lo_iv) & (df['k'] <= hi_iv)]
        p = df[(df['t'] == 'P') & (df['k'] >= lo_iv) & (df['k'] <= hi_iv)]
        
        call_iv = round(float(c['隐含波动率'].mean()), 1) if not c.empty else None
        put_iv = round(float(p['隐含波动率'].mean()), 1) if not p.empty else None
        iv_diff = round(put_iv - call_iv, 1) if (call_iv and put_iv) else None
        
        # 判断形态
        if iv_diff is None:
            skew = IVSkew.SYMMETRIC
            label = 'IV数据不足'
        elif iv_diff > self.skew_threshold:
            skew = IVSkew.LEFT_SKEW
            label = f'左偏(put IV>{call_iv}% call IV={call_iv}%, 差={iv_diff}%)'
        elif iv_diff < -self.skew_threshold:
            skew = IVSkew.RIGHT_SKEW
            label = f'右偏(call IV>{abs(iv_diff)}% put IV={put_iv}%)'
        else:
            skew = IVSkew.SYMMETRIC
            label = f'基本对称(IV差={iv_diff}%)'
        
        return {
            'call_iv': call_iv,
            'put_iv': put_iv,
            'iv_diff': iv_diff,
            'skew': skew,
            'label': label
        }


# ==================== 期权综合分析 ====================

class OptionStructureAnalyzer:
    """期权结构综合分析器"""
    
    def __init__(self, fp: float = 7000):
        self.fp = fp
        self.wall_detector = OptionWallDetector()
        self.pcr_monitor = PCRMonitor()
        self.iv_analyzer = IVAnalyzer()
        self.kill_option_detector = KillOptionStageDetector()
    
    def analyze(self, df: pd.DataFrame, expiry_dates: List[str] = None) -> Tuple[OptionStructure, KillOptionStage]:
        """综合分析期权结构
        
        Args:
            df: 期权数据DataFrame
            expiry_dates: 到期日期列表
            
        Returns:
            Tuple[OptionStructure, KillOptionStage]: 期权结构和杀期权阶段
        """
        if df is None or df.empty:
            return self._empty_option_structure(), KillOptionStage(
                is_active=False, near_expiry=False, expiry_date=None,
                days_to_expiry=999, wall_clarity=0.0, has_option_wall=False, confidence=0.0
            )
        
        # 1. 期权墙检测
        wall_result = self.wall_detector.detect(df, self.fp)
        floor_walls = wall_result['floor_walls']
        ceil_walls = wall_result['ceil_walls']
        
        # 2. PCR计算
        pcr_result = self.pcr_monitor.calculate(df)
        
        # 3. IV分析
        iv_result = self.iv_analyzer.analyze(df, self.fp)
        
        # 4. 杀期权阶段检测
        kill_stage = self.kill_option_detector.detect(df, expiry_dates)
        
        # 5. 综合评分
        score, label = self._calculate_score(
            pcr_result, iv_result, wall_result, kill_stage
        )
        
        # 6. 计算梯度比率
        ftot = wall_result['total_floor_oi']
        ctot = wall_result['total_ceil_oi']
        gradient_ratio = round(ftot / ctot, 2) if ctot > 0 else None
        
        option_structure = OptionStructure(
            pcr=pcr_result['position_pcr'],
            tcv=pcr_result.get('total_call_vol', 0),
            tpv=pcr_result.get('total_put_vol', 0),
            floor_walls=floor_walls,
            ceil_walls=ceil_walls,
            total_floor_oi=ftot,
            total_ceil_oi=ctot,
            gradient_ratio=gradient_ratio,
            call_iv=iv_result['call_iv'],
            put_iv=iv_result['put_iv'],
            iv_diff=iv_result['iv_diff'],
            iv_skew=iv_result['skew'],
            score=score,
            label=label,
            detail=self._build_detail(pcr_result, iv_result, wall_result)
        )
        
        return option_structure, kill_stage
    
    def _calculate_score(self, pcr_result: Dict, iv_result: Dict, 
                         wall_result: Dict, kill_stage: KillOptionStage) -> Tuple[int, str]:
        """计算综合评分"""
        score = 0
        details = []
        
        # PCR评分
        pcr_signal = pcr_result['signal']
        if pcr_signal == PCRSignal.STRONG_BULLISH:
            score += 2
            details.append('PCR强烈偏多')
        elif pcr_signal == PCRSignal.BULLISH:
            score += 1
            details.append('PCR偏多')
        elif pcr_signal == PCRSignal.BEARISH:
            score -= 1
            details.append('PCR偏空')
        elif pcr_signal == PCRSignal.STRONG_BEARISH:
            score -= 2
            details.append('PCR强烈偏空')
        
        # IV形态评分
        skew = iv_result['skew']
        if skew == IVSkew.LEFT_SKEW:
            score -= 1
            details.append('IV左偏(恐慌)')
        elif skew == IVSkew.RIGHT_SKEW:
            score += 1
            details.append('IV右偏(乐观)')
        
        # 梯度比率评分
        ftot = wall_result.get('total_floor_oi', 0)
        ctot = wall_result.get('total_ceil_oi', 1)
        gr = ftot / max(ctot, 1)
        if gr > 2.0:
            score += 2
            details.append(f'地板防线极强(梯度={gr:.2f})')
        elif gr > 1.5:
            score += 1
            details.append(f'地板防线较强(梯度={gr:.2f})')
        elif gr < 0.5:
            score -= 2
            details.append(f'天花板防线极强(梯度={gr:.2f})')
        elif gr < 0.67:
            score -= 1
            details.append(f'天花板防线较强(梯度={gr:.2f})')
        
        # 杀期权阶段
        if kill_stage.is_active:
            score = int(score * 1.2)  # 杀期权阶段信号强化
            details.append('杀期权阶段')
        
        # 确定标签
        if score >= 3:
            label = '强烈偏多'
        elif score >= 1:
            label = '偏多'
        elif score <= -3:
            label = '强烈偏空'
        elif score <= -1:
            label = '偏空'
        else:
            label = '中性'
        
        return score, label
    
    def _build_detail(self, pcr_result: Dict, iv_result: Dict, wall_result: Dict) -> str:
        """构建详细描述"""
        details = []
        
        pcr = pcr_result.get('position_pcr')
        if pcr:
            details.append(f'PCR={pcr:.2f}')
        
        iv_diff = iv_result.get('iv_diff')
        if iv_diff is not None:
            details.append(f'IV差={iv_diff}%')
        
        ftot = wall_result.get('total_floor_oi', 0)
        ctot = wall_result.get('total_ceil_oi', 0)
        if ftot and ctot:
            details.append(f'地板OI={ftot} 天花板OI={ctot}')
        
        return '; '.join(details) if details else '信息不足'
    
    def _empty_option_structure(self) -> OptionStructure:
        """返回空的期权结构"""
        return OptionStructure(
            pcr=None, tcv=0, tpv=0,
            floor_walls=[], ceil_walls=[],
            total_floor_oi=0, total_ceil_oi=0,
            gradient_ratio=None,
            call_iv=None, put_iv=None, iv_diff=None,
            iv_skew=IVSkew.SYMMETRIC,
            score=0, label='无数据', detail='无数据'
        )


# ==================== 缠论与期权共振信号 ====================

class ResonanceSignalGenerator:
    """缠论买卖点与期权共振信号生成器
    
    交易规则速记：
    规则A：右偏背景做空 - 隐波明显右偏 + 涨至期权墙阻力位 + 顶背离 → 轻仓试错
    规则B：左偏背景做多 - 隐波明显左偏 + 跌至期权墙支撑位 + 底背离 → 轻仓试错
    规则C：顺势增强 - PCR维持适中 + 隐波温和上升 → 可正常仓位
    """
    
    def __init__(self, option_analyzer: OptionStructureAnalyzer):
        self.option_analyzer = option_analyzer
    
    def generate(self, chan_bs_points: List[Dict], 
                 current_price: float,
                 option_structure: OptionStructure,
                 kill_stage: KillOptionStage,
                 regime: MarketRegime = MarketRegime.CALM) -> ResonanceSignal:
        """生成共振信号
        
        Args:
            chan_bs_points: 缠论买卖点列表 (从chan_core获取)
            current_price: 当前价格
            option_structure: 期权结构分析结果
            kill_stage: 杀期权阶段识别结果
            regime: 当前市场状态
            
        Returns:
            ResonanceSignal: 共振信号
        """
        # 1. 分析缠论信号
        chan_signal = self._analyze_chan_signal(chan_bs_points, current_price)
        
        # 2. 分析期权信号
        option_direction, option_confidence = self._analyze_option_signal(option_structure)
        
        # 3. 确定方向
        if chan_signal and option_direction != SignalDirection.NEUTRAL:
            # 方向一致
            if chan_signal.direction == option_direction:
                direction = option_direction
                confidence = min(1.0, (chan_signal.confidence + option_confidence) / 2 + 0.1)
                reasons = [f'缠论{chan_signal.direction.value}', f'期权{option_direction.value}方向一致']
            else:
                direction = SignalDirection.NEUTRAL
                confidence = 0.3
                reasons = [f'缠论{chan_signal.direction.value}与期权{option_direction.value}方向矛盾']
        elif chan_signal:
            direction = chan_signal.direction
            confidence = chan_signal.confidence * 0.8
            reasons = [f'缠论{chan_signal.direction.value}信号']
        elif option_direction != SignalDirection.NEUTRAL:
            direction = option_direction
            confidence = option_confidence * 0.8
            reasons = [f'期权{option_direction.value}信号']
        else:
            direction = SignalDirection.NEUTRAL
            confidence = 0.0
            reasons = ['无明确信号']
        
        # 4. 应用杀期权阶段修正
        if kill_stage.is_active:
            confidence = min(1.0, confidence * 1.2)
            reasons.append('杀期权阶段(置信度强化)')
        
        # 5. 宏观驱动期修正
        if regime == MarketRegime.MACRO_DRIVE:
            confidence = min(1.0, confidence * 0.9)
            reasons.append('宏观驱动期(容忍回调)')
        
        # 6. 风险等级
        if kill_stage.is_active:
            risk_level = '高'
        elif confidence >= 0.7:
            risk_level = '中'
        else:
            risk_level = '低'
        
        # 7. 操作建议
        action = self._generate_action(direction, confidence, chan_signal, option_structure, kill_stage)
        
        return ResonanceSignal(
            direction=direction,
            confidence=confidence,
            regime=regime,
            chan_signal=chan_signal,
            option_signal=option_structure,
            共振依据=reasons,
            risk_level=risk_level,
            action=action
        )
    
    def _analyze_chan_signal(self, bs_points: List[Dict], current_price: float) -> Optional[ChanSignal]:
        """分析缠论信号"""
        if not bs_points:
            return None
        
        # 获取最新的买卖点
        latest = bs_points[-1] if bs_points else None
        if not latest:
            return None
        
        bs_type = latest.get('type', '')
        
        # 确定方向
        if 'buy' in bs_type.lower():
            direction = SignalDirection.LONG
        elif 'sell' in bs_type.lower():
            direction = SignalDirection.SHORT
        else:
            return None
        
        # 置信度
        if '1buy' in bs_type or '1sell' in bs_type:
            confidence = 0.8
        elif '2buy' in bs_type or '2sell' in bs_type:
            confidence = 0.7
        elif '3buy' in bs_type or '3sell' in bs_type:
            confidence = 0.6
        else:
            confidence = 0.5
        
        return ChanSignal(
            direction=direction,
            confidence=confidence,
            reason=f"缠论{bs_type}信号",
            price=latest.get('price', current_price),
            bi_type=bs_type,
            level='5min'
        )
    
    def _analyze_option_signal(self, option_structure: OptionStructure) -> Tuple[SignalDirection, float]:
        """分析期权信号"""
        direction = SignalDirection.NEUTRAL
        confidence = 0.0
        
        # 基于IV形态
        if option_structure.iv_skew == IVSkew.RIGHT_SKEW:
            # 右偏 -> 偏空
            direction = SignalDirection.SHORT
            confidence = 0.6
        elif option_structure.iv_skew == IVSkew.LEFT_SKEW:
            # 左偏 -> 偏多
            direction = SignalDirection.LONG
            confidence = 0.6
        
        # 基于PCR强化
        pcr = option_structure.pcr
        if pcr:
            if pcr > 1.0:
                if direction == SignalDirection.SHORT:
                    confidence = min(1.0, confidence + 0.2)
                else:
                    direction = SignalDirection.SHORT
                    confidence = 0.5
            elif pcr < 0.8:
                if direction == SignalDirection.LONG:
                    confidence = min(1.0, confidence + 0.2)
                else:
                    direction = SignalDirection.LONG
                    confidence = 0.5
        
        # 基于梯度比率
        gr = option_structure.gradient_ratio
        if gr:
            if gr > 2.0:  # 地板远大于天花板 -> 偏多
                if direction == SignalDirection.LONG:
                    confidence = min(1.0, confidence + 0.2)
            elif gr < 0.5:  # 天花板远大于地板 -> 偏空
                if direction == SignalDirection.SHORT:
                    confidence = min(1.0, confidence + 0.2)
        
        return direction, confidence
    
    def _generate_action(self, direction: SignalDirection, confidence: float,
                        chan_signal: Optional[ChanSignal],
                        option_structure: OptionStructure,
                        kill_stage: KillOptionStage) -> str:
        """生成操作建议"""
        if direction == SignalDirection.NEUTRAL:
            return '等待明确信号'
        
        # 仓位建议
        if confidence >= 0.8:
            position = '正常仓位'
        elif confidence >= 0.6:
            position = '轻仓试错'
        else:
            position = '极轻仓观望'
        
        # 止损建议
        if chan_signal:
            if direction == SignalDirection.LONG:
                stop_loss = f'止损参考: {chan_signal.price * 0.995:.0f}'  # 跌破信号价0.5%
            else:
                stop_loss = f'止损参考: {chan_signal.price * 1.005:.0f}'  # 涨破信号价0.5%
        else:
            stop_loss = '止损: 0.5%'
        
        # 杀期权阶段特殊处理
        if kill_stage.is_active:
            position = '轻仓' if position == '正常仓位' else position
            stop_loss = '必须严格止损'
        
        return f'{position}，{stop_loss}，方向: {direction.value}'


# ==================== 一体化策略主类 ====================

class PTAOptionStrategy:
    """PTA期权一体化策略主类
    
    整合所有分析模块，提供统一的策略接口
    """
    
    def __init__(self, fp: float = 7000):
        self.fp = fp
        self.option_analyzer = OptionStructureAnalyzer(fp=fp)
        self.resonance_generator = ResonanceSignalGenerator(self.option_analyzer)
    
    def get_full_analysis(self, option_df: pd.DataFrame, 
                          chan_result: Dict,
                          expiry_dates: List[str] = None) -> Dict[str, Any]:
        """获取完整分析结果
        
        Args:
            option_df: 期权数据DataFrame
            chan_result: 缠论分析结果 (从chan_core_wrapper.get_chan_result获取)
            expiry_dates: 期权到期日期列表
            
        Returns:
            Dict包含完整分析结果
        """
        # 1. 期权结构分析
        option_structure, kill_stage = self.option_analyzer.analyze(option_df, expiry_dates)
        
        # 2. 提取缠论买卖点
        bs_points = chan_result.get('bs_data', [])
        current_price = chan_result.get('stats', {}).get('current_price', 0)
        
        # 3. 确定市场状态
        regime = MarketRegime.CALM
        if kill_stage.is_active:
            regime = MarketRegime.KILL_OPTION
        
        # 4. 生成共振信号
        resonance_signal = self.resonance_generator.generate(
            bs_points, current_price, option_structure, kill_stage, regime
        )
        
        # 5. 构建返回结果
        return {
            'success': True,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'regime': regime.value,
            'option_structure': {
                'pcr': option_structure.pcr,
                'pcr_label': option_structure.label,
                'iv_skew': option_structure.iv_skew.value,
                'gradient_ratio': option_structure.gradient_ratio,
                'floor_oi': option_structure.total_floor_oi,
                'ceil_oi': option_structure.total_ceil_oi,
                'floor_walls': [
                    {
                        'strike': w.strike,
                        'oi': w.oi,
                        'density_ratio': round(w.density_ratio, 2),
                        'iv': w.iv
                    } for w in option_structure.floor_walls[:5]
                ],
                'ceil_walls': [
                    {
                        'strike': w.strike,
                        'oi': w.oi,
                        'density_ratio': round(w.density_ratio, 2),
                        'iv': w.iv
                    } for w in option_structure.ceil_walls[:5]
                ],
                'score': option_structure.score,
                'label': option_structure.label,
                'detail': option_structure.detail
            },
            'kill_option_stage': {
                'is_active': kill_stage.is_active,
                'near_expiry': kill_stage.near_expiry,
                'expiry_date': kill_stage.expiry_date,
                'days_to_expiry': kill_stage.days_to_expiry,
                'wall_clarity': round(kill_stage.wall_clarity, 2),
                'confidence': round(kill_stage.confidence, 2)
            },
            'resonance_signal': {
                'direction': resonance_signal.direction.value,
                'confidence': round(resonance_signal.confidence, 2),
                'regime': resonance_signal.regime.value,
                '共振依据': resonance_signal.共振依据,
                'risk_level': resonance_signal.risk_level,
                'action': resonance_signal.action
            },
            'chan_signal': {
                'direction': resonance_signal.chan_signal.direction.value if resonance_signal.chan_signal else None,
                'confidence': round(resonance_signal.chan_signal.confidence, 2) if resonance_signal.chan_signal else None,
                'price': resonance_signal.chan_signal.price if resonance_signal.chan_signal else None,
                'type': resonance_signal.chan_signal.bi_type if resonance_signal.chan_signal else None
            } if resonance_signal.chan_signal else None,
            'current_price': current_price,
            'stats': chan_result.get('stats', {})
        }
    
    def generate_report(self, analysis_result: Dict) -> str:
        """生成格式化报告
        
        Args:
            analysis_result: get_full_analysis返回的结果
            
        Returns:
            str: 格式化报告文本
        """
        lines = []
        lines.append("=" * 60)
        lines.append(f"PTA期货期权一体化分析报告")
        lines.append(f"时间: {analysis_result['timestamp']}")
        lines.append("=" * 60)
        
        # 市场状态
        regime = analysis_result['regime']
        lines.append(f"\n【市场状态】{regime}")
        
        # 杀期权阶段
        ko = analysis_result['kill_option_stage']
        if ko['is_active']:
            lines.append(f"  ⚠️ 杀期权阶段活跃")
            lines.append(f"  - 距到期: {ko['days_to_expiry']}天")
            lines.append(f"  - 到期日: {ko['expiry_date']}")
            lines.append(f"  - 墙清晰度: {ko['wall_clarity']:.0%}")
        else:
            lines.append(f"  ✅ 正常运行状态")
        
        # 期权结构
        opt = analysis_result['option_structure']
        lines.append(f"\n【期权结构】")
        lines.append(f"  PCR: {opt['pcr']:.2f} ({opt['pcr_label']})" if opt['pcr'] else "  PCR: N/A")
        lines.append(f"  IV形态: {opt['iv_skew']}")
        lines.append(f"  梯度比率: {opt['gradient_ratio']:.2f}" if opt['gradient_ratio'] else "  梯度比率: N/A")
        lines.append(f"  综合评分: {opt['score']} ({opt['label']})")
        
        lines.append(f"\n  地板防线(OI={opt['floor_oi']}):")
        for w in opt['floor_walls'][:3]:
            lines.append(f"    P{int(w['strike'])}: OI={w['oi']} 密度={w['density_ratio']:.1f}")
        
        lines.append(f"  天花板防线(OI={opt['ceil_oi']}):")
        for w in opt['ceil_walls'][:3]:
            lines.append(f"    C{int(w['strike'])}: OI={w['oi']} 密度={w['density_ratio']:.1f}")
        
        # 缠论信号
        chan = analysis_result.get('chan_signal')
        if chan and chan['direction']:
            lines.append(f"\n【缠论信号】")
            lines.append(f"  方向: {chan['direction']}")
            lines.append(f"  类型: {chan['type']}")
            lines.append(f"  价格: {chan['price']:.0f}")
            lines.append(f"  置信度: {chan['confidence']:.0%}")
        
        # 共振信号
        sig = analysis_result['resonance_signal']
        lines.append(f"\n【共振信号】")
        lines.append(f"  方向: {sig['direction']}")
        lines.append(f"  置信度: {sig['confidence']:.0%}")
        lines.append(f"  风险等级: {sig['risk_level']}")
        lines.append(f"  共振依据: {' | '.join(sig['共振依据'])}")
        lines.append(f"  操作建议: {sig['action']}")
        
        lines.append("\n" + "=" * 60)
        return "\n".join(lines)


# ==================== 数据获取辅助 ====================

def get_pta_option_data(trade_date: str = None) -> pd.DataFrame:
    """获取PTA期权数据
    
    Args:
        trade_date: 交易日期，格式YYYYMMDD，默认今日
        
    Returns:
        DataFrame: 期权数据
    """
    import akshare as ak
    
    if trade_date is None:
        trade_date = datetime.now().strftime('%Y%m%d')
    
    try:
        df = ak.option_hist_czce(symbol='PTA期权', trade_date=trade_date)
        return df
    except Exception as e:
        warnings.warn(f"获取期权数据失败: {e}")
        return pd.DataFrame()


def get_pta_expiry_dates(months: int = 2) -> List[str]:
    """获取PTA期权到期日期
    
    Args:
        months: 往前看的月数
        
    Returns:
        List[str]: 到期日期列表 (格式YYYYMMDD)
    """
    from datetime import datetime
    import pandas as pd
    
    # PTA期权通常为标的期货交割月前一个月的第5个工作日
    # 这里简化处理，返回最近几个月的周五
    dates = []
    now = datetime.now()
    
    for i in range(months):
        # 简单近似：每月末周五
        target = now + pd.DateOffset(months=i)
        # 简化处理，实际应查交易所日历
        expiry = target.replace(day=min(28, target.day))
        dates.append(expiry.strftime('%Y%m%d'))
    
    return dates


# ==================== 主入口 ====================

if __name__ == '__main__':
    print("PTA期货期权一体化策略模块")
    print("=" * 60)
    
    # 示例用法
    strategy = PTAOptionStrategy(fp=7000)
    
    # 获取期权数据
    trade_date = datetime.now().strftime('%Y%m%d')
    print(f"\n获取 {trade_date} 的PTA期权数据...")
    option_df = get_pta_option_data(trade_date)
    
    if option_df.empty:
        print("期权数据获取失败，使用模拟数据演示...")
        # 演示用模拟数据
        option_df = pd.DataFrame()
    
    # 获取缠论分析结果
    print("\n获取缠论分析结果...")
    from chan_core_wrapper import get_chan_result
    chan_result = get_chan_result(period='5min')
    
    # 执行完整分析
    print("\n执行一体化分析...")
    result = strategy.get_full_analysis(option_df, chan_result)
    
    # 生成报告
    report = strategy.generate_report(result)
    print("\n" + report)

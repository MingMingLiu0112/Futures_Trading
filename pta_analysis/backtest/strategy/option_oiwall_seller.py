


#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
期权墙卖方收租策略 v4.3
=======================
核心逻辑：
  - 识别期权墙（OI密集区）
  - 在墙附近卖期权收权利金
  - 保护腿：卖CALL买PUT（方向同向），卖PUT买PUT（更下方）

开仓约束：
  - CALL墙：S上方 <= 5档
  - PUT墙：S下方 1~8档（太远OTM不做）
  - IV >= 15%
  - OI >= 2000, 密度 >= 1.5
  - 最大持仓4组

风控：
  - 卖权浮亏 > 保证金5% → 止损
  - 卖权实值 + 临近期权(≤5天) → 止损
  - 升波突破(IV+15%) + 方向不利 → 止损
  - 到期OTM → 持有收割

移仓/反手：
  - 突破行权价 + IV续升 + 墙移 → 移仓到新墙
  - 反向强墙出现 + IV降 → 反手

数据范围: 20220104 ~ 20240514
"""

import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'option_history.db')


# ==================== 数据结构 ====================

@dataclass
class OIWall:
    strike: float
    side: str           # 'call' / 'put' / 'both'
    total_oi: float
    density: float
    iv: float


@dataclass
class OptionPosition:
    trade_id: int
    trade_date: str
    expiry: str
    strike: float
    option_type: str    # 'C' or 'P'
    direction: str       # 'sell' or 'buy'
    open_price: float
    volume: int
    iv_at_open: float
    margin_used: float
    wall_strike: float   # 挂住该仓的墙行权价


@dataclass
class TradeResult:
    trade_id: int
    open_date: str
    close_date: str
    expiry: str
    strike: float
    option_type: str
    direction: str
    open_price: float
    close_price: float
    volume: int
    pnl: float
    pnl_pct: float
    hold_days: int
    exit_reason: str


# ==================== 数据加载 ====================

class OptionDataLoader:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._all_data: Optional[pd.DataFrame] = None
    
    def get_trade_dates(self, start: str, end: str) -> List[str]:
        cur = self.conn.cursor()
        cur.execute('SELECT DISTINCT trade_date FROM option_daily WHERE trade_date >= ? AND trade_date <= ? ORDER BY trade_date',
                    (start, end))
        return [r[0] for r in cur.fetchall()]
    
    def _preload_data(self, trade_dates: List[str]):
        if self._all_data is not None:
            return
        ph = ','.join(['?' for _ in trade_dates])
        self._all_data = pd.read_sql(f'''
            SELECT trade_date, symbol, underlying, expiry, strike, option_type,
                   close, settle, volume, oi, oi_change, iv, delta, pre_settle
            FROM option_daily WHERE trade_date IN ({ph})
            ORDER BY trade_date, expiry, strike, option_type
        ''', self.conn, params=(*trade_dates,))
        self._all_data['trade_date'] = self._all_data['trade_date'].astype(str)
        self._all_data['expiry'] = self._all_data['expiry'].astype(str)
        self._all_data['strike'] = self._all_data['strike'].astype(float)
    
    def load_ttype(self, trade_date: str, expiry: str = None) -> pd.DataFrame:
        if self._all_data is None:
            return pd.DataFrame()
        df = self._all_data[self._all_data['trade_date'] == trade_date]
        if expiry:
            df = df[df['expiry'] == expiry]
        return df
    
    def get_iv_rank(self, trade_date: str, expiry: str, current_iv: float) -> float:
        if self._all_data is None:
            return 0.5
        ivs = self._all_data[
            (self._all_data['trade_date'] <= trade_date) &
            (self._all_data['expiry'].astype(str) == expiry) &
            (self._all_data['iv'] > 0)
        ]['iv'].dropna().tail(60).tolist()
        if not ivs or current_iv <= 0:
            return 0.5
        return min(sum(1 for iv in ivs if iv <= current_iv) / len(ivs), 1.0)
    
    def get_near_expiry(self, trade_date: str) -> List[str]:
        cur = self.conn.cursor()
        cur.execute('''
            SELECT DISTINCT expiry FROM option_daily
            WHERE trade_date = ? AND expiry >= ?
            ORDER BY expiry LIMIT 2
        ''', (trade_date, trade_date[:6]))
        return [r[0] for r in cur.fetchall()]
    
    def close(self):
        self.conn.close()


# ==================== 期权墙识别 ====================

class OIWallDetector:
    def __init__(self, loader: OptionDataLoader):
        self.loader = loader
        self._precomputed: Optional[pd.DataFrame] = None
    
    def preload(self, trade_dates: List[str], oi_min: float = 2000.0, density_min: float = 1.5):
        if self._precomputed is not None:
            return
        self.oi_min = oi_min
        self.density_min = density_min
        self.loader._preload_data(trade_dates)
        self._precompute_walls(trade_dates)
    
    def _precompute_walls(self, trade_dates: List[str]):
        all_data = self.loader._all_data[
            self.loader._all_data['trade_date'].isin(trade_dates)
        ].copy()
        
        oi_agg = all_data.groupby(['trade_date', 'expiry', 'strike']).agg({
            'oi': 'sum', 'iv': 'mean', 'volume': 'sum', 'oi_change': 'sum'
        }).reset_index()
        
        for opt_type, col in [('C', 'call_oi'), ('P', 'put_oi')]:
            tmp = all_data[all_data['option_type'] == opt_type].groupby(
                ['trade_date', 'expiry', 'strike'])['oi'].sum().reset_index()
            tmp.columns = ['trade_date', 'expiry', 'strike', col]
            oi_agg = oi_agg.merge(tmp, on=['trade_date', 'expiry', 'strike'], how='left')
            oi_agg[col] = oi_agg[col].fillna(0)
        
        oi_agg = oi_agg.sort_values(['expiry', 'strike'])
        
        for w in [-1, 1]:
            oi_agg[f'shift{w}'] = oi_agg.groupby(['trade_date', 'expiry'])['oi'].shift(w)
        oi_agg['neighbor_avg'] = oi_agg[['shift-1', 'shift1']].mean(axis=1).replace(0, np.nan)
        oi_agg['density'] = oi_agg['oi'] / oi_agg['neighbor_avg']
        oi_agg['density'] = oi_agg['density'].fillna(0)
        oi_agg['is_wall'] = (oi_agg['density'] > self.density_min) & (oi_agg['oi'] > self.oi_min)
        
        def calc_side(row):
            c, p, t = row['call_oi'], row['put_oi'], row['oi']
            if t <= 0:
                return 'both'
            diff = abs(c - p) / t
            if diff < 0.3:
                return 'both'
            return 'call' if c > p else 'put'
        
        oi_agg['side'] = oi_agg.apply(calc_side, axis=1)
        self._precomputed = oi_agg.copy()
    
    def detect_walls(self, trade_date: str, expiry: str) -> List[OIWall]:
        if self._precomputed is None:
            return []
        df = self._precomputed[
            (self._precomputed['trade_date'] == trade_date) &
            (self._precomputed['expiry'] == expiry)
        ]
        if df.empty:
            return []
        walls = []
        for _, row in df[df['is_wall']].iterrows():
            walls.append(OIWall(
                strike=row['strike'],
                side=row['side'],
                total_oi=row['oi'],
                density=row['density'] if row['density'] else 0,
                iv=row['iv'] or 0,
            ))
        walls.sort(key=lambda w: (w.density, w.total_oi), reverse=True)
        return walls


# ==================== 策略核心 ====================

class OptionOIWallSellerV4:
    def __init__(
        self,
        db_path: str = DB_PATH,
        iv_min: float = 15.0,
        call_wall_distance_max: int = 5,   # CALL墙：S上方 <= N档
        put_wall_distance_max: int = 8,     # PUT墙：S下方 <= N档
        put_wall_distance_min: int = 1,     # PUT墙：S下方 >= N档（避免太近OTM）
        oi_min: float = 3000.0,
        density_min: float = 1.5,
        stop_loss_margin_pct: float = 0.05, # 卖权浮亏超保证金5%止损
        max_positions: int = 4,              # 最大持仓组数
        full_ratio: float = 0.50,
        half_ratio: float = 0.25,
        oi_full_threshold: int = 8000,
        commission: float = 10.0,
        multiplier: float = 10.0,
    ):
        self.db_path = db_path
        self.loader = OptionDataLoader(db_path)
        self.wall_detector = OIWallDetector(self.loader)
        self.iv_min = iv_min
        self.call_wall_distance_max = call_wall_distance_max
        self.put_wall_distance_max = put_wall_distance_max
        self.put_wall_distance_min = put_wall_distance_min
        self.oi_min = oi_min
        self.density_min = density_min
        self.stop_loss_margin_pct = stop_loss_margin_pct
        self.max_positions = max_positions
        self.full_ratio = full_ratio
        self.half_ratio = half_ratio
        self.oi_full_threshold = oi_full_threshold
        self.commission = commission
        self.multiplier = multiplier
        self.positions: List[OptionPosition] = []
        self.closed_trades: List[TradeResult] = []
        self.equity_curve: List[Dict] = []
        self._trade_id_counter = 0
        self._wall_approached: Dict[str, int] = {}
        self._cooldown: Dict[str, str] = {}
        self._cooldown_days = 5
        self._pre_equity = 0
        # ====== 新增参数（S1/S2/S3/S4/S5）======
        self.max_dd_stop_pct = 0.10       # S2: 全局回撤止损阈值（默认10%）
        self.buyer_profit_pct = 1.30       # S3: 买方止盈（默认130%）
        self.buyer_stop_loss_pct = 0.50    # S3: 买方止损（默认50%）
        self.buyer_time_stop_days = 5      # S3: 买方时间止损天数
        self.buyer_time_profit_pct = 1.15  # S3: 买方时间止盈
        self.density_weighted = False     # S4: 是否启用密度加权
        self.iv_entry_filter = None       # S5: IV择时入场（None=不禁用，0=IV上升不开仓）
        self.iv_rank_filter = 1.0         # S1: IV Rank上限（1.0=不过滤）
        self._prev_iv: Dict[str, Dict] = {}  # S5: 追踪每日IV变化
    
    def _parse_date(self, d: str) -> datetime:
        if len(d) == 6:
            d += '01'
        return datetime.strptime(d, '%Y%m%d')
    
    def _date_diff(self, d1: str, d2: str) -> int:
        try:
            return (self._parse_date(d2) - self._parse_date(d1)).days
        except:
            return 0
    
    def _estimate_S(self, trade_date: str, expiry: str) -> float:
        df = self.loader.load_ttype(trade_date, expiry)
        active = df[df['close'] > 0]
        if active.empty:
            return df['strike'].median() if not df.empty else 0
        return active['strike'].median()
    
    def _iv_thresholds(self, current_iv: float) -> Dict[str, float]:
        """
        返回IV变化阈值（基于当前ATM IV判断波动环境）。
        高波：阈值宽松（噪音<3%）
        低波：阈值严格（噪音<1.5%）
        """
        if current_iv >= 30:
            return {'noise': 3.0, 'significant': 6.0, 'extreme': 999}
        elif current_iv >= 20:
            return {'noise': 2.0, 'significant': 4.0, 'extreme': 999}
        else:
            return {'noise': 1.5, 'significant': 3.0, 'extreme': 999}

    def _oi_thresholds(self, oi: float) -> Dict[str, float]:
        """
        返回持仓量变化阈值（基于当前OI量级）。
        大OI：阈值宽松；小OI：阈值严格。
        """
        if oi >= 10000:
            return {'noise': 5.0, 'sigLow': 10.0, 'extreme': 999}
        elif oi >= 3000:
            return {'noise': 7.0, 'sigLow': 15.0, 'extreme': 999}
        else:
            return {'noise': 10.0, 'sigLow': 25.0, 'extreme': 999}

    def _is_iv_significant_rise(self, iv_change_pct: float, current_iv: float) -> bool:
        """IV变化是否达到显著升波（> significant阈值才算）"""
        th = self._iv_thresholds(current_iv)
        return iv_change_pct >= th['significant']

    def _is_iv_significant_drop(self, iv_change_pct: float, current_iv: float) -> bool:
        """IV变化是否达到显著降波（< -significant阈值才算）"""
        th = self._iv_thresholds(current_iv)
        return iv_change_pct <= -th['significant']
    
    def _get_iv_rank(self, trade_date: str, expiry: str, current_iv: float) -> float:
        """返回IV在近60天历史上的百分位（0~1）"""
        return self.loader.get_iv_rank(trade_date, expiry, current_iv)
    
    def _margin(self, strike: float, option_price: float) -> float:
        base = strike * 0.02 * self.multiplier + option_price * self.multiplier
        cap = strike * 0.15 * self.multiplier
        return min(base, cap)
    
    def _position_size(self, price: float, strike: float, is_full: bool, equity: float, existing_margin: float, density: float = 1.5) -> Tuple[int, float, float]:
        margin_per = self._margin(strike, price)
        target = equity * (self.full_ratio if is_full else self.half_ratio)
        remaining = target - existing_margin
        if remaining <= margin_per:
            return 0, 0, 0
        vol = max(1, int(remaining / margin_per))
        # S4: 密度加权，density=1.5→1.0x, density=3.0→1.45x, 限制0.7~1.5
        if self.density_weighted and density > 1.5:
            density_w = 1.0 + (density - 1.5) * 0.3
            density_w = max(0.7, min(1.5, density_w))
            vol = max(1, min(20, int(vol * density_w)))
        else:
            vol = min(vol, 20)
        margin = margin_per * vol
        premium = price * self.multiplier * vol - self.commission
        return vol, margin, premium
    
    def _find_walls_for_entry(
        self, trade_date: str, expiry: str, df: pd.DataFrame, S: float,
        all_walls: List[OIWall]
    ) -> List[Dict]:
        results = []
        
        for wall in all_walls[:8]:
            wk = f"{expiry}_{wall.strike}"
            
            # 冷却期
            cd = self._cooldown.get(wk, '')
            if cd and self._date_diff(cd, trade_date) < self._cooldown_days:
                continue
            
            # IV门槛
            if wall.iv < self.iv_min:
                continue

            # ====== S1: IV Rank过滤 ======
            if self.iv_rank_filter < 1.0:
                iv_rank = self._get_iv_rank(trade_date, expiry, wall.iv)
                if iv_rank >= self.iv_rank_filter:
                    continue

            # 方向 + 档位约束
            distance = (wall.strike - S) / 100  # 正=S上方，负=S下方
            
            if wall.side == 'call':
                if distance <= 0 or distance > self.call_wall_distance_max:
                    continue
                opt_type = 'C'
            elif wall.side == 'put':
                if distance >= 0:
                    continue
                if abs(distance) < self.put_wall_distance_min or abs(distance) > self.put_wall_distance_max:
                    continue
                opt_type = 'P'
            elif wall.side == 'both':
                if wall.strike > S:
                    if distance > self.call_wall_distance_max:
                        continue
                    opt_type = 'C'
                elif wall.strike < S:
                    if abs(distance) < self.put_wall_distance_min or abs(distance) > self.put_wall_distance_max:
                        continue
                    opt_type = 'P'
                else:
                    continue
            else:
                continue

            # ====== S5: IV择时入场 ======
            if self.iv_entry_filter is not None and hasattr(wall, '_iv_chg'):
                if wall._iv_chg > self.iv_entry_filter:
                    continue

            # 价格检查
            opt_df = df[(df['expiry'] == expiry) & (df['strike'] == wall.strike) & (df['option_type'] == opt_type)]
            if opt_df.empty:
                continue
            row = opt_df.iloc[0]
            price = row['close']
            if price < 5 or price >= 300:
                continue
            
            # 短线博弈仓：卖墙 + 买反向期权形成价差保护
            # 卖CALL（上方墙）→ 买更深虚值PUT（博弈S跌→PUT涨）
            # 卖PUT（下方墙）→ 买更高行权价CALL（博弈S大涨→CALL涨补偿卖PUT损失）
            # 选腿标准：更深虚值、价格低、IV适中（赔率导向）
            if opt_type == 'C':
                prot_opt_type = 'P'
                # 卖CALL的博弈腿：买更深虚值PUT（卖墙-2~4档）
                prot_candidates = [
                    (wall.strike - 200, 'OTM2'),
                    (wall.strike - 300, 'OTM3'),
                    (wall.strike - 400, 'OTM4'),
                ]
            else:
                # 卖PUT的博弈腿：买更高行权价CALL（卖墙+1~3档，博弈S大涨）
                # 这是牛市价差（Bull Call Spread）：卖PUT收权利金 + 买CALL锁住上方上涨空间
                prot_opt_type = 'C'
                prot_candidates = [
                    (wall.strike + 100, 'OTM1'),
                    (wall.strike + 200, 'OTM2'),
                    (wall.strike + 300, 'OTM3'),
                ]

            best_prot = None
            best_score = -1
            for prot_k, label in prot_candidates:
                prot_df = df[(df['expiry'] == expiry) & (df['strike'] == prot_k) & (df['option_type'] == prot_opt_type)]
                if prot_df.empty:
                    continue
                row = prot_df.iloc[0]
                prot_price = row['close']
                prot_iv = row.get('iv') or 0
                if prot_price < 3 or prot_price >= 100:  # 价格太低没空间，太高不划算
                    continue
                # 保护腿必须是虚值
                # 买PUT（卖CALL的保护）：K < S（低于当前价）
                # 买CALL（卖PUT的保护）：K > S（高于当前价）
                if prot_opt_type == 'P' and prot_k >= S:
                    continue
                if prot_opt_type == 'C' and prot_k <= S:
                    continue
                # 评分标准（赔率导向）：价格越低分越高，虚值越高分越高，IV适中
                # 博弈仓：价格低→成本低→赔率高
                price_score = 1.5 if prot_price <= 10 else (1.2 if prot_price <= 20 else 1.0 if prot_price <= 40 else 0.6)
                # 虚值程度：越虚分越高（行权价距S越远）
                otm_pct = (S - prot_k) / S * 100
                otm_score = 1.4 if otm_pct >= 8 else (1.2 if otm_pct >= 5 else 1.0)
                # IV适中：IV太高权利金贵，太低可能没波动
                iv_score = 1.0 if 15 <= prot_iv <= 25 else (0.8 if prot_iv > 25 else 0.7)
                score = price_score * otm_score * iv_score
                if score > best_score:
                    best_score = score
                    best_prot = {'strike': prot_k, 'price': prot_price, 'iv': prot_iv}

            prot_price = best_prot['price'] if best_prot else 0
            prot_strike = best_prot['strike'] if best_prot else wall.strike - 300
            
            is_full = wall.total_oi >= self.oi_full_threshold
            approach_count = self._wall_approached.get(wk, 0)
            
            results.append({
                'wall': wall, 'opt_type': opt_type,
                'strike': wall.strike, 'price': price,
                'iv': wall.iv, 'oi': wall.total_oi,
                'distance': distance,
                'is_full': is_full, 'is_second': approach_count >= 1,
                'prot_opt_type': prot_opt_type,
                'prot_strike': prot_strike, 'prot_price': prot_price,
                'wall_key': wk,
            })
        
        return results
    
    def _check_position(
        self, trade_date: str, expiry: str, pos: OptionPosition,
        current_price: float, current_iv: float, current_oi: float,
        S: float, all_walls: List[OIWall],
    ) -> Tuple[str, Dict]:
        days_to_expiry = self._date_diff(trade_date, pos.expiry)
        iv_change_pct = (current_iv - pos.iv_at_open) / pos.iv_at_open if pos.iv_at_open > 0 else 0
        iv_th = self._iv_thresholds(current_iv)
        iv_spike = iv_change_pct >= iv_th['significant']   # 显著升波
        stop_triggered = False

        # ========== 止损 ==========
        if pos.direction == 'sell':
            # 卖权实值 + 临近期权(≤5天) → 硬止损
            is_itm = (pos.option_type == 'C' and S > pos.strike) or \
                     (pos.option_type == 'P' and S < pos.strike)
            if is_itm and days_to_expiry <= 5:
                stop_triggered = True
            # 方向不利 + 显著升波
            elif is_itm and iv_spike:
                stop_triggered = True
            # 方向有利但IV极端飙升（>10天到期且IV变化>2倍significant阈值）
            elif not is_itm and iv_change_pct >= iv_th['extreme'] and days_to_expiry <= 10:
                stop_triggered = True

            # 浮亏超保证金5%
            if not stop_triggered:
                margin_loss = abs((pos.open_price - current_price) * self.multiplier * pos.volume)
                if margin_loss > pos.margin_used * self.stop_loss_margin_pct:
                    stop_triggered = True
        else:
            # ===== 买方（短线博弈仓）止损/止盈逻辑 =====
            # 博弈方向：买PUT → 赌S跌（S跌→PUT涨）
            # 止损：S朝反方向走（即S没跌反而涨了）→ 立刻砍
            # 止盈：S朝博弈方向走 AND 降波 → 收割利润
            premium_paid = pos.open_price * self.multiplier * pos.volume
            loss = (pos.open_price - current_price) * self.multiplier * pos.volume  # 买PUT: S涨则current_price跌→loss>0

            # 计算持仓天数
            hold_days = self._date_diff(pos.trade_date, trade_date)

            if pos.option_type == 'P':
                # 买PUT = 博弈S跌
                # 止损：价格跌破开仓价×buyer_stop_loss_pct → 方向判断错误，认赔
                if current_price < pos.open_price * self.buyer_stop_loss_pct:
                    return 'stop', {'reason': 'buyer_loss_cut'}
                # 止盈：价格涨×buyer_profit_pct OR 到期降波
                if current_price >= pos.open_price * self.buyer_profit_pct:
                    return 'close', {'reason': 'buyer_tp_pct'}
                # 时间止损：持仓超过buyer_time_stop_days天且涨幅<buyer_time_profit_pct → 行情不配合，不再博弈
                if hold_days >= self.buyer_time_stop_days and current_price < pos.open_price * self.buyer_time_profit_pct:
                    return 'stop', {'reason': 'buyer_time_stop'}
                # 到期前3天+有利方向（降波或S下跌）
                iv_drop = iv_change_pct <= -iv_th['significant']
                if days_to_expiry <= 3 and (iv_drop or S < pos.strike):
                    return 'close', {'reason': 'buyer_tp_expiry'}
            else:
                # 买CALL = 博弈S涨
                if current_price < pos.open_price * self.buyer_stop_loss_pct:
                    return 'stop', {'reason': 'buyer_loss_cut'}
                if current_price >= pos.open_price * self.buyer_profit_pct:
                    return 'close', {'reason': 'buyer_tp_pct'}
                # 时间止损
                if hold_days >= self.buyer_time_stop_days and current_price < pos.open_price * self.buyer_time_profit_pct:
                    return 'stop', {'reason': 'buyer_time_stop'}

        if stop_triggered:
            return 'stop', {'iv_change_pct': iv_change_pct}

        # ========== 到期 ==========
        if days_to_expiry <= 3:
            if pos.direction == 'sell':
                is_otm = (pos.option_type == 'C' and S <= pos.strike) or \
                         (pos.option_type == 'P' and S >= pos.strike)
                if is_otm:
                    return 'close', {'reason': 'expire'}
            # 到期3日内禁止做买方
            if pos.direction == 'buy':
                return 'stop', {'reason': 'buyer_expiry_3days'}

        # ========== 反向强墙止盈（仅在高波+显著降波时有效）==========
        if days_to_expiry > 5 and pos.direction == 'sell':
            iv_drop = iv_change_pct <= -iv_th['significant']
            if iv_drop and current_iv >= 30:  # 高波环境才触发
                opp_side = 'put' if pos.option_type == 'C' else 'call'
                opp_walls = [w for w in all_walls if w.side == opp_side]
                if opp_walls:
                    strongest = max(opp_walls, key=lambda w: w.total_oi * w.density)
                    dist = abs(S - strongest.strike) / 100
                    if dist <= self.put_wall_distance_max:
                        return 'reverse', {'opp_wall': strongest}

        # ========== 突破移仓（显著升波 + 目标必须有墙）==========
        broken = (pos.option_type == 'C' and S > pos.strike) or \
                 (pos.option_type == 'P' and S < pos.strike)
        if broken and days_to_expiry > 5 and iv_spike:
            step = 100
            if pos.option_type == 'C':
                new_strike = pos.strike + step
                while new_strike <= S + step * 5:
                    wall_match = [w for w in all_walls if abs(w.strike - new_strike) < 50 and w.side in ('call', 'both')]
                    if wall_match and wall_match[0].iv >= self.iv_min:
                        return 'roll', {'new_strike': new_strike, 'wall': wall_match[0]}
                    new_strike += step
            else:
                new_strike = pos.strike - step
                while new_strike >= S - step * 5:
                    wall_match = [w for w in all_walls if abs(w.strike - new_strike) < 50 and w.side in ('put', 'both')]
                    if wall_match and wall_match[0].iv >= self.iv_min:
                        return 'roll', {'new_strike': new_strike, 'wall': wall_match[0]}
                    new_strike -= step

        return 'hold', {}
    
    def _find_roll_target(self, df: pd.DataFrame, expiry: str, pos: OptionPosition) -> Optional[Dict]:
        step = 100
        if pos.option_type == 'C':
            new_strike = pos.strike + step
        else:
            new_strike = pos.strike - step
        target_df = df[(df['expiry'] == expiry) & (df['strike'] == new_strike) & (df['option_type'] == pos.option_type)]
        if target_df.empty:
            return None
        row = target_df.iloc[0]
        if row['close'] < 5:
            return None
        return {'strike': new_strike, 'price': row['close'], 'iv': row['iv'] or 0}
    
    def run_backtest(self, start: str, end: str, initial: float = 100_000) -> pd.DataFrame:
        trade_dates = self.loader.get_trade_dates(start, end)
        print(f'回测: {start} ~ {end}, {len(trade_dates)}个交易日, 初始{initial:,.0f}')
        print(f'CALL墙距: S上方<={self.call_wall_distance_max}档 | PUT墙距: {self.put_wall_distance_min}~{self.put_wall_distance_max}档 | IV>={self.iv_min}% | OI>={self.oi_min:.0f}')
        print('-' * 70)
        
        self.wall_detector.preload(trade_dates, oi_min=self.oi_min, density_min=self.density_min)
        
        equity = initial
        self._pre_equity = equity
        self._peak_equity = initial
        self._trade_id_counter = 0
        self.positions.clear()
        self.closed_trades.clear()
        self.equity_curve.clear()
        self._wall_approached.clear()
        self._cooldown.clear()
        self._prev_iv.clear()

        for trade_date in trade_dates:
            df = self.loader.load_ttype(trade_date)
            if df.empty:
                continue
            
            expiry_list = self.loader.get_near_expiry(trade_date)
            if not expiry_list:
                continue
            near_expiry = expiry_list[0]
            expiry_df = df[df['expiry'] == near_expiry]
            S = self._estimate_S(trade_date, near_expiry)
            all_walls = self.wall_detector.detect_walls(trade_date, near_expiry)

            # ====== S5: IV择时入场 - 追踪每日IV变化 ======
            if self.iv_entry_filter is not None:
                for wall in all_walls:
                    wk = f"{near_expiry}_{wall.strike}"
                    prev = self._prev_iv.get(wk, {})
                    prev_iv = prev.get('iv', wall.iv)
                    wall._iv_chg = ((wall.iv - prev_iv) / prev_iv * 100) if prev_iv and prev_iv > 0 else 0
                    self._prev_iv[wk] = {'iv': wall.iv, 'oi': wall.total_oi}

            # ==================== 全局止损：浮亏超过总资金max_dd_stop_pct立即清仓 ====================
            peak_equity = max(self._peak_equity, equity)
            dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
            if dd >= self.max_dd_stop_pct and self.positions:
                # 清仓所有持仓
                for pos in list(self.positions):
                    p_df = expiry_df[(expiry_df['strike'] == pos.strike) & (expiry_df['option_type'] == pos.option_type)]
                    cp = p_df.iloc[0]['close'] if not p_df.empty else pos.open_price * 0.3
                    pnl = (pos.open_price - cp) * self.multiplier * pos.volume - self.commission * 2
                    equity += pnl
                    self._record_trade(pos, trade_date, cp, pnl, 'global_10pct_stop')
                    self.positions.remove(pos)
                self.equity_curve.append({'trade_date': trade_date, 'equity': equity, 'positions': 0})
                continue
            
            # ==================== 持仓管理 ====================
            # 分两阶段：先判断所有持仓的动作，再统一执行
            position_actions: List[Tuple[OptionPosition, str, Dict]] = []
            for pos in list(self.positions):
                pos_df = expiry_df[(expiry_df['strike'] == pos.strike) & (expiry_df['option_type'] == pos.option_type)]
                if pos_df.empty:
                    current_price, current_iv, current_oi = pos.open_price * 0.3, pos.iv_at_open, 0
                else:
                    r = pos_df.iloc[0]
                    current_price, current_iv = r['close'], r['iv']
                    current_oi = r['oi']
                action, meta = self._check_position(
                    trade_date, near_expiry, pos,
                    current_price, current_iv or 0, current_oi,
                    S, all_walls
                )
                position_actions.append((pos, action, meta))
            
            # 统一执行平仓（先平所有需要平的）
            for pos, action, meta in position_actions:
                if action not in ('stop', 'close', 'reverse', 'roll'):
                    continue
                pos_df = expiry_df[(expiry_df['strike'] == pos.strike) & (expiry_df['option_type'] == pos.option_type)]
                if pos_df.empty:
                    current_price = pos.open_price * 0.3
                else:
                    current_price = pos_df.iloc[0]['close']
                pnl = (pos.open_price - current_price) * self.multiplier * pos.volume - self.commission * 2
                equity += pnl
                self._record_trade(pos, trade_date, current_price, pnl, action)
                self.positions.remove(pos)  # 立即从列表移除
                if action in ('stop', 'no_roll_target', 'roll_limit'):
                    self._cooldown[f"{pos.expiry}_{pos.strike}"] = trade_date
            
            # 统一执行反向和移仓（在平仓之后，此时持仓已是最新的）
            for pos, action, meta in position_actions:
                if action == 'reverse' and len(self.positions) < self.max_positions:
                    ow = meta.get('opp_wall')
                    if ow:
                        oo = 'C' if ow.strike > S else 'P'
                        oo_df = expiry_df[(expiry_df['strike'] == ow.strike) & (expiry_df['option_type'] == oo)]
                        if not oo_df.empty and oo_df.iloc[0]['close'] > 5:
                            self._trade_id_counter += 1
                            new_pos = OptionPosition(
                                trade_id=self._trade_id_counter,
                                trade_date=trade_date, expiry=near_expiry,
                                strike=ow.strike, option_type=oo, direction='sell',
                                open_price=oo_df.iloc[0]['close'], volume=pos.volume,
                                iv_at_open=oo_df.iloc[0]['iv'] or 0,
                                margin_used=self._margin(ow.strike, oo_df.iloc[0]['close']),
                                wall_strike=ow.strike,
                            )
                            self.positions.append(new_pos)
                            equity -= self.commission
                
                elif action == 'roll' and len(self.positions) < self.max_positions:
                    new_strike = meta.get('new_strike')
                    if new_strike is None:
                        continue
                    roll_key = f'{pos.trade_id}_rolls'
                    rolls = getattr(self, '_roll_count', {})
                    roll_count = rolls.get(roll_key, 0)
                    if roll_count >= 2:
                        continue  # 已超过移仓次数（实际在上面已止损）
                    roll_df = expiry_df[(expiry_df['strike'] == new_strike) & (expiry_df['option_type'] == pos.option_type)]
                    if not roll_df.empty and roll_df.iloc[0]['close'] > 5:
                        rolls[roll_key] = roll_count + 1
                        self._roll_count = rolls
                        new_price = roll_df.iloc[0]['close']
                        new_iv = roll_df.iloc[0]['iv'] or 0
                        new_vol = min(pos.volume, 20)
                        self._trade_id_counter += 1
                        new_pos = OptionPosition(
                            trade_id=self._trade_id_counter,
                            trade_date=trade_date, expiry=near_expiry,
                            strike=new_strike, option_type=pos.option_type, direction='sell',
                            open_price=new_price, volume=new_vol,
                            iv_at_open=new_iv,
                            margin_used=self._margin(new_strike, new_price),
                            wall_strike=new_strike,
                        )
                        self.positions.append(new_pos)
                        equity -= self.commission
            
            # ==================== 开仓 ====================
            if len(self.positions) < self.max_positions:
                existing_margin = sum(p.margin_used for p in self.positions if p.direction == 'sell')
                candidates = self._find_walls_for_entry(trade_date, near_expiry, df, S, all_walls)
                
                for cand in candidates[:2]:
                    # S4: 密度加权仓位
                    vol, margin, premium = self._position_size(
                        cand['price'], cand['strike'], cand['is_full'], equity, existing_margin,
                        density=cand['wall'].density
                    )
                    if vol <= 0:
                        continue
                    
                    self._trade_id_counter += 1
                    main_pos = OptionPosition(
                        trade_id=self._trade_id_counter,
                        trade_date=trade_date, expiry=near_expiry,
                        strike=cand['strike'], option_type=cand['opt_type'], direction='sell',
                        open_price=cand['price'], volume=vol,
                        iv_at_open=cand['iv'],
                        margin_used=margin,
                        wall_strike=cand['wall'].strike,
                    )
                    self.positions.append(main_pos)
                    equity += premium
                    existing_margin += margin
                    
                    # 保护腿
                    if cand['prot_price'] > 0:
                        self._trade_id_counter += 1
                        prot_cost = cand['prot_price'] * self.multiplier * vol
                        prot_pos = OptionPosition(
                            trade_id=self._trade_id_counter,
                            trade_date=trade_date, expiry=near_expiry,
                            strike=cand['prot_strike'], option_type=cand['prot_opt_type'], direction='buy',
                            open_price=cand['prot_price'], volume=vol,
                            iv_at_open=cand['iv'],
                            margin_used=prot_cost,
                            wall_strike=cand['wall'].strike,
                        )
                        self.positions.append(prot_pos)
                        equity -= prot_cost + self.commission
                    
                    equity -= self.commission
                    self._wall_approached[cand['wall_key']] = self._wall_approached.get(cand['wall_key'], 0) + 1
            
            # 权益记录
            self.equity_curve.append({'trade_date': trade_date, 'equity': equity, 'positions': len(self.positions)})
            # 同步更新峰值权益
            if equity > self._peak_equity:
                self._peak_equity = equity
        
        # 平剩余持仓
        if self.positions and trade_dates:
            last = trade_dates[-1]
            df = self.loader.load_ttype(last)
            for pos in list(self.positions):
                p_df = df[(df['strike'] == pos.strike) & (df['option_type'] == pos.option_type)]
                cp = p_df.iloc[0]['close'] if not p_df.empty else 0
                pnl = (pos.open_price - cp) * self.multiplier * pos.volume - self.commission * 2
                equity += pnl
                self._record_trade(pos, last, cp, pnl, 'backtest_end')
            self.positions.clear()
        
        self.loader.close()
        return pd.DataFrame(self.equity_curve)
    
    def _record_trade(self, pos: OptionPosition, close_date: str, close_price: float, pnl: float, reason: str):
        days = self._date_diff(pos.trade_date, close_date)
        denom = pos.open_price * self.multiplier * pos.volume
        self.closed_trades.append(TradeResult(
            trade_id=pos.trade_id,
            open_date=pos.trade_date,
            close_date=close_date,
            expiry=pos.expiry,
            strike=pos.strike,
            option_type=pos.option_type,
            direction=pos.direction,
            open_price=pos.open_price,
            close_price=close_price,
            volume=pos.volume,
            pnl=pnl,
            pnl_pct=pnl / denom * 100 if denom > 0 else 0,
            hold_days=days,
            exit_reason=reason,
        ))
    
    def print_stats(self, initial: float = 100_000):
        if not self.closed_trades:
            print('无交易')
            return
        
        all_df = pd.DataFrame([{
            'open': t.open_date, 'close': t.close_date,
            'expiry': t.expiry, 'K': t.strike,
            'T': 'C' if t.option_type == 'C' else 'P',
            'D': '卖' if t.direction == 'sell' else '买',
            'open_px': t.open_price, 'close_px': t.close_price,
            'vol': t.volume, 'pnl': t.pnl, 'pnl%': f"{t.pnl_pct:.1f}%",
            'days': t.hold_days, 'reason': t.exit_reason,
        } for t in self.closed_trades])
        
        seller = [t for t in self.closed_trades if t.direction == 'sell']
        buyer = [t for t in self.closed_trades if t.direction == 'buy']
        s_df = pd.DataFrame(seller) if seller else pd.DataFrame()
        b_df = pd.DataFrame(buyer) if buyer else pd.DataFrame()
        
        total = all_df['pnl'].sum()
        seller_pnl = s_df['pnl'].sum() if len(s_df) else 0
        buyer_pnl = b_df['pnl'].sum() if len(b_df) else 0
        
        # 期末权益（权益曲线最后一笔 + 期末持仓按当前价格估值）
        final_equity = self.equity_curve[-1]['equity'] if self.equity_curve else initial
        # 估算期末持仓价值（如果有的话）
        final_pos_value = 0
        if self.positions and trade_dates and hasattr(self, 'positions'):
            last_td = self.equity_curve[-1]['trade_date'] if self.equity_curve else None
            if last_td:
                from option_oiwall_seller import OptionDataLoader
                loader = OptionDataLoader(self.db_path)
                df_last = loader.load_ttype(last_td)
                if not df_last.empty:
                    expiry_list = loader.get_near_expiry(last_td)
                    if expiry_list:
                        ne = expiry_list[0]
                        expiry_df = df_last[df_last['expiry'] == ne]
                        for pos in self.positions:
                            p_df = expiry_df[(expiry_df['strike'] == pos.strike) & (expiry_df['option_type'] == pos.option_type)]
                            if not p_df.empty:
                                cur_px = p_df.iloc[0]['close']
                                if pos.direction == 'sell':
                                    final_pos_value += (pos.open_price - cur_px) * self.multiplier * pos.volume
                                else:
                                    final_pos_value += (cur_px - pos.open_price) * self.multiplier * pos.volume
                loader.close()
        
        total_equity = final_equity + final_pos_value
        
        cs = all_df.sort_values('open')['pnl'].cumsum() + initial
        peak = cs.iloc[0]
        max_dd = 0
        for v in cs:
            if v > peak: peak = v
            dd = (peak - v) / peak * 100 if peak > 0 else 0
            if dd > max_dd: max_dd = dd
        
        grp = all_df.copy()
        grp['month'] = grp['open'].str[:6]
        monthly = grp.groupby('month')['pnl'].sum()
        sharpe = monthly.mean() / monthly.std() * np.sqrt(12) if monthly.std() > 0 else 0
        months = all_df['open'].str[:6].nunique()
        trades_per_month = len(all_df) / months if months > 0 else 0
        
        seller_mean = float(s_df['pnl'].mean()) if len(s_df) else 0.0
        buyer_mean = float(b_df['pnl'].mean()) if len(b_df) else 0.0
        
        print(f'''
============================================
期权墙卖方策略 v4.3 回测报告
============================================
期间: {all_df['open'].min()} ~ {all_df['close'].max()}
----------------------------------------
【收益】
  已平仓收益:   {total:,.0f}
  期末持仓估值: {final_pos_value:,.0f}
  期末总权益:   {total_equity:,.0f} ({(total_equity-initial)/initial*100:.1f}%)
  卖方收益:     {seller_pnl:,.0f}
  买方收益:     {buyer_pnl:,.0f}
  夏普:         {sharpe:.2f}
  最大回撤:     {max_dd:.1f}%
  月均交易:     {trades_per_month:.1f}笔
----------------------------------------
【卖方统计】({len(seller)}笔)
  盈利:       {len(s_df[s_df['pnl']>0]) if len(s_df) else 0}
  亏损:       {len(s_df[s_df['pnl']<=0]) if len(s_df) else 0}
  均值:       {seller_mean:.0f}
----------------------------------------
【买方统计】({len(buyer)}笔)
  盈利:       {len(b_df[b_df['pnl']>0]) if len(b_df) else 0}
  亏损:       {len(b_df[b_df['pnl']<=0]) if len(b_df) else 0}
  均值:       {buyer_mean:.0f}
----------------------------------------
【平仓原因】
{all_df['reason'].value_counts().to_string()}
''')
        print('交易明细:')
        print(all_df.to_string(index=False))


if __name__ == '__main__':
    if not os.path.exists(DB_PATH):
        print(f'数据库不存在: {DB_PATH}')
        exit(1)
    
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT MIN(trade_date), MAX(trade_date), COUNT(DISTINCT trade_date) FROM option_daily')
    min_d, max_d, n = cur.fetchone()
    conn.close()
    print(f'数据: {min_d} ~ {max_d}, {n}个交易日')
    
    s = OptionOIWallSellerV4(
        iv_min=15.0,
        call_wall_distance_max=5,
        put_wall_distance_max=8,
        put_wall_distance_min=1,
        oi_min=3000.0,
        density_min=1.5,
        stop_loss_margin_pct=0.05,
        max_positions=4,
        oi_full_threshold=8000,
    )
    
    df = s.run_backtest(min_d, max_d, initial=100_000)
    s.print_stats(initial=100_000)

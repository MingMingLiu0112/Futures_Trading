
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA期权隐波微笑曲线实时服务 v4
- TQSdk 独立线程运行（隔离事件循环）
- 动态查询 CZCE.TA 系列未到期期权，自动选取主力合约
- 等待 wait_update 确保数据到达
- Black-Scholes + Brent 反算 IV
- SABR 模型平滑拟合
- Flask API 提供数据
"""
import sys, os, time, json, warnings, atexit
from datetime import datetime, timedelta
from threading import Thread, Lock
import numpy as np

# matplotlib backend MUST be set before import
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from io import BytesIO

warnings.filterwarnings('ignore')

WORKSPACE = '/home/admin/.openclaw/workspace/Futures_Trading/pta_analysis'
sys.path.insert(0, WORKSPACE)

# ===================== 全局状态 =====================
_state = {
    'futures_price': None,
    'atm_strike': None,
    'last_update': None,
    'smile_raw': {},
    'smile_smooth': {},
    'sabr_params': None,
    'expiry': None,
    'rate': 0.02,
    'running': False,
    'lock': Lock(),
    'active_contract': None,
    'data_ready': False,   # 数据是否真正到达
}

# 缓存：连接失败时保留上一次正确值
_last_valid = {
    'futures_price': None,
    'atm_strike': None,
    'smile_raw': {},
    'smile_smooth': {},
    'sabr_params': None,
}

# 历史快照（按固定15分钟时间点存储）
# key: "HH:MM" 如 "09:00", "09:15", ... 或 'night'（昨夜盘锚点）
# value: {'smooth': {strike: iv}, 'raw': {strike: {'C': iv, 'P': iv}}, 'timestamp': str}
_interval_snapshots = {}

# ===================== 跨模块共享接口 =====================
def get_shared_futures_price():
    """供其他模块共享的实时期货价格。
    优先返回 iv_smile_service 自有的TqSdk实时价格，
    兜底返回 _last_valid 缓存值（服务重启后也能用）。
    返回 (price, source) 元组：price为float，source为 'tqsdk'/'cache'/'none'。"""
    with _state.get('lock', _dummy_lock):
        p = _state.get('futures_price') or _last_valid.get('futures_price')
    if p and p > 0:
        return float(p), 'tqsdk'
    return None, 'none'

_dummy_lock = type('DummyLock', (), {'__enter__': lambda s: s, '__exit__': lambda *a: None})()

# ===================== 持久化配置 =====================
_SNAPSHOT_DIR = os.path.join(WORKSPACE, 'data', 'iv_snapshots')
_SAVED_DATES = set()   # 记录已写入磁盘的日期，避免重复保存

def _get_snapshot_path(date_str, session='day'):
    """返回指定日期+交易时段的快照文件路径。
    session='day'   -> iv_snapshots_YYYYMMDD.json（日盘快照集合）
    session='night' -> iv_snapshots_YYYYMMDD_night.json（昨夜盘锚点）"""
    return os.path.join(_SNAPSHOT_DIR, f'iv_snapshots_{date_str}_{session}.json')

def _ensure_snapshot_dir():
    """确保快照目录存在"""
    os.makedirs(_SNAPSHOT_DIR, exist_ok=True)

def _save_night_session_snapshot():
    """
    每日夜盘收盘时（23:00前后）保存当日最后一个快照到磁盘。
    下一交易日早盘可加载作为对比锚点。
    文件命名：iv_snapshots_YYYYMMDD.json，仅保存一个最新夜盘快照。
    """
    if not _interval_snapshots:
        return
    _ensure_snapshot_dir()
    date_str = datetime.now().strftime('%Y%m%d')
    # 取当日最新的快照（最晚时间点）
    latest_key = max(_interval_snapshots.keys(),
                     default=None, key=lambda k: (int(k.replace(':', '')), k))
    if latest_key is None:
        return
    snap = _interval_snapshots[latest_key]
    payload = {
        'date': date_str,
        'interval_key': latest_key,
        'snapshot': snap,
    }
    path = _get_snapshot_path(date_str)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"[iv_smile] 📦 夜盘快照已持久化: {path} ({latest_key})")
    except Exception as e:
        print(f"[iv_smile] ⚠️ 快照持久化失败: {e}")

def _load_night_session_snapshot(date_str=None):
    """
    启动时加载上一交易日夜盘快照作为对比锚点。
    如果当前交易日已读过（_last_loaded_date == today），不重复加载。
    """
    global _interval_snapshots
    if date_str is None:
        date_str = datetime.now().strftime('%Y%m%d')
    # 尝试加载上一交易日的快照
    path = _get_snapshot_path(date_str)
    if not os.path.exists(path):
        return  # 没有历史快照
    try:
        with open(path, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        snap = payload.get('snapshot', {})
        if not snap:
            return
        # 快照interval_key保持原样（"22:45"），前端会用 prev_key 逻辑取
        _interval_snapshots.update({payload.get('interval_key', 'night'): snap})
        print(f"[iv_smile] 📂 已加载夜盘快照: {payload.get('interval_key')} (from {date_str})")
    except Exception as e:
        print(f"[iv_smile] ⚠️ 加载夜盘快照失败: {e}")

def _load_previous_night_snapshot():
    """
    启动时加载上一交易日夜盘快照作为对比锚点。
    尝试加载"昨日"快照文件（上一交易日23:00前后保存的）。
    """
    global _interval_snapshots
    # 上一交易日：减1天（绝大多数情况覆盖）
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
    path = _get_snapshot_path(yesterday)
    if not os.path.exists(path):
        return  # 没有历史快照
    try:
        with open(path, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        snap = payload.get('snapshot', {})
        if not snap:
            return
        # 用 'night' 作为key，前端 prev_key 逻辑会兜底取这个
        _interval_snapshots['night'] = snap
        print(f"[iv_smile] 📂 已加载昨夜盘快照: {payload.get('interval_key')} (from {yesterday})")
    except Exception as e:
        print(f"[iv_smile] ⚠️ 加载昨夜盘快照失败: {e}")

# 启动时尝试加载上一交易日夜盘快照
_load_previous_night_snapshot()

# ===================== 15分钟时间点辅助 =====================

def get_interval_key(dt=None):
    """返回当前时刻对应的15分钟时间点key，如 '09:00', '09:15'"""
    if dt is None:
        dt = datetime.now()
    # 向下取整到15分钟：09:07 -> 09:00, 09:16 -> 09:15
    minutes = (dt.minute // 15) * 15
    return f"{dt.hour:02d}:{minutes:02d}"

def get_prev_interval_key(dt=None):
    """返回上一个15分钟时间点key，如 '09:00' 的上一个是 '08:45'"""
    if dt is None:
        dt = datetime.now()
    minutes = (dt.minute // 15) * 15
    prev_minute = minutes - 15
    prev_hour = dt.hour
    if prev_minute < 0:
        prev_minute = 45
        prev_hour = (prev_hour - 1) % 24
    return f"{prev_hour:02d}:{prev_minute:02d}"

_tqsdk_thread = None
_tqsdk_ready = False
_option_symbols = []
_tqsdk_quotes = {}

# ===================== 动态查主力合约 =====================

_EXPIRY_CACHE = {}  # {contract_code: last_trade_date}

def get_active_ta_contract():
    """
    从交易所实时数据获取最近未到期期权合约（与期权链T型报价逻辑一致）。
    数据源: akshare option_contract_info_ctp()
    规则: 选最后交易日 > 今天 的最近月合约
    返回: (opt_prefix, expiry_date)
    """
    global _EXPIRY_CACHE
    import akshare as ak
    from datetime import datetime

    now = datetime.now()
    today_str = now.strftime('%Y-%m-%d')

    try:
        df = ak.option_contract_info_ctp()
        # 找TA期权，取唯一标的合约
        mask = df['合约名称'].str.startswith('TA', na=False)
        ta_df = df[mask][['合约名称', '最后交易日', '标的合约ID']].copy()
        # 按标的合约ID去重（同一合约多个行权价）
        ta_df = ta_df.drop_duplicates(subset=['标的合约ID'])

        # 过滤未到期
        active = ta_df[ta_df['最后交易日'] > today_str].sort_values('最后交易日')
        if active.empty:
            # 所有合约都过期了（极端情况），用最近的
            active = ta_df.sort_values('最后交易日')

        row = active.iloc[0]
        contract_id = row['标的合约ID']  # e.g. 'TA607'
        last_trade = row['最后交易日']
        _EXPIRY_CACHE = {r['标的合约ID']: r['最后交易日'] for _, r in ta_df.iterrows()}
        return contract_id, datetime.strptime(last_trade, '%Y-%m-%d')

    except Exception as e:
        # 网络失败时用缓存
        if _EXPIRY_CACHE:
            active = {k: v for k, v in _EXPIRY_CACHE.items() if v > today_str}
            if active:
                nearest = sorted(active.items(), key=lambda x: x[1])[0]
                return nearest[0], datetime.strptime(nearest[1], '%Y-%m-%d')
        # 兜底
        return 'TA607', datetime(2026, 6, 11)


# ===================== Black-Scholes =====================

def black_scholes_price(S, K, T, r, sigma, option_type='C'):
    from scipy.stats import norm
    if T <= 0 or sigma <= 0:
        return np.nan
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if option_type == 'C':
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:
        return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

def bs_iv_brent(S, K, T, r, market_price, option_type='C'):
    from scipy.optimize import brentq
    if T <= 0 or market_price <= 0 or S <= 0 or K <= 0:
        return np.nan
    intrinsic = max(S - K, 0) if option_type == 'C' else max(K - S, 0)
    if market_price < intrinsic * 0.95:
        return np.nan
    if market_price < 0.5:
        return np.nan

    def objective(sigma):
        return black_scholes_price(S, K, T, r, sigma, option_type) - market_price

    try:
        return brentq(objective, 0.01, 2.5, maxiter=200)
    except (ValueError, RuntimeError):
        return np.nan

# ===================== SABR 模型 =====================

def sabr_vol_impl(F, K, T, alpha, rho, nu, beta=1.0):
    """
    SABR Hagan 2002 approximation (fixed for large F).
    beta=1 (lognormal SABR) works well for commodity options with large F (e.g., PTA F~6400).
    Uses log-moneyness m = log(F/K) internally.
    """
    eps = 1e-10
    m = np.log(F / K)  # log-moneyness
    FK_beta = (F * K) ** (1 - beta)
    sqrt_FK_beta = np.sqrt(FK_beta + eps)

    denom = 1 + ((1 - beta) ** 2 / 24) * m ** 2 + ((1 - beta) ** 4 / 1920) * m ** 4
    term1 = alpha / (sqrt_FK_beta * denom)

    z = (nu / alpha) * sqrt_FK_beta * m
    if abs(z) < eps:
        z = eps

    sqrt_term = np.sqrt(1 - 2 * rho * z + z ** 2 + eps)
    x_z = np.log((sqrt_term + z - rho) / (1 - rho + eps))
    if abs(x_z) < eps:
        x_z = eps

    z_over_xz = z / x_z

    F_pow = max(F, eps) ** (1 - beta)
    term2 = 1 + ((1 - beta) ** 2 / 24 * alpha ** 2 / F_pow ** 2 +
                  0.25 * rho * nu * alpha / F_pow +
                  (2 - 3 * rho ** 2) / 24 * nu ** 2) * T

    # ATM: abs(m) < 0.001, limit z/x_z -> 1
    if abs(m) < 0.001:
        return term1 * term2

    return term1 * term2 * z_over_xz

def fit_sabr(K_list, IV_list, F, T):
    """
    Fit SABR parameters using Trust Reflective (trf) algorithm.
    beta=1 (lognormal SABR) fixed; fit alpha, rho, nu.
    """
    from scipy.optimize import least_squares
    K_arr = np.array(K_list, dtype=float)
    IV_arr = np.array(IV_list, dtype=float)

    valid = ~(np.isnan(IV_arr) | (IV_arr <= 0) | (IV_arr > 2.5))
    if valid.sum() < 4:
        return None

    K_v = K_arr[valid]
    IV_v = IV_arr[valid]

    atm_mask = np.abs(K_v - F) < 200
    alpha0 = IV_v[atm_mask].mean() if atm_mask.sum() > 0 else 0.20
    alpha0 = max(min(alpha0, 1.0), 0.05)

    def residuals(params):
        alpha, rho, nu = params
        if alpha <= 0 or nu <= 0 or abs(rho) >= 1:
            return np.ones(len(K_v)) * 1e6
        modeled = np.array([sabr_vol_impl(F, k, T, alpha, rho, nu, 1.0) for k in K_v])
        return IV_v - modeled

    try:
        result = least_squares(
            residuals,
            [alpha0, -0.3, 0.3],
            bounds=([0.001, -0.999, 0.001], [3.0, 0.999, 5.0]),
            method='trf',
            max_nfev=500
        )
        if result.success:
            return {
                'alpha': float(result.x[0]),
                'rho': float(result.x[1]),
                'nu': float(result.x[2]),
                'success': True
            }
    except Exception:
        pass
    return None

def smooth_smile(K_list, IV_list, F, T):
    """SABR拟合 → 重建平滑曲线"""
    sabr = fit_sabr(K_list, IV_list, F, T)
    if sabr is None:
        return {}, None

    alpha, rho, nu = sabr['alpha'], sabr['rho'], sabr['nu']
    smooth_iv = {}
    for k in sorted(K_list):
        iv = sabr_vol_impl(F, k, T, alpha, rho, nu, 1.0)
        if not np.isnan(iv) and 0 < iv < 2.5:
            smooth_iv[k] = iv

    return smooth_iv, sabr

# ===================== TQSdk 线程 =====================

def tqsdk_loop():
    """独立线程运行TQSdk事件循环"""
    global _tqsdk_ready, _tqsdk_quotes, _state, _option_symbols

    import asyncio
    from tqsdk import TqApi, TqAuth, TqKq

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        api = TqApi(TqKq(), auth=TqAuth('mingmingliu', 'Liuzhaoning2025'), loop=loop)
        print("[iv_smile] TQSdk已连接")

        # === 动态查主力合约 ===
        opt_prefix, expiry = get_active_ta_contract()
        fut_sym = f"CZCE.{opt_prefix}"

        _state['active_contract'] = opt_prefix
        _state['expiry'] = expiry
        print(f"[iv_smile] 主力合约: {opt_prefix} 到期: {expiry.date()}")

        # === 获取期货行情 ===
        fut_quote = api.get_quote(fut_sym)

        # === 生成期权列表（平值上下10档） ===
        # 先获取期货价格确定ATM
        max_wait = 20  # 最多等20次wait_update
        S = None
        for i in range(max_wait):
            api.wait_update()
            loop.run_until_complete(asyncio.sleep(0.1))
            bid = getattr(fut_quote, 'bid_price1', None)
            ask = getattr(fut_quote, 'ask_price1', None)
            if bid and ask and bid > 0:
                S = (bid + ask) / 2
                break
            last = getattr(fut_quote, 'last_price', None)
            if last and last > 0:
                S = last
                break

        if not S:
            print(f"[iv_smile] ⚠️ 期货行情未到达，使用默认值 S=6500")
            S = 6500.0

        # PTA 最小变动价位为2，取偶数
        S = round(S / 2) * 2
        atm_strike = round(S / 100) * 100
        strikes = list(range(atm_strike - 10 * 100, atm_strike + 11 * 100, 100))

        print(f"[iv_smile] S={S:.0f} ATM={atm_strike} 档位:{strikes[0]}~{strikes[-1]}")

        # === 订阅期权行情 ===
        option_quotes = {}
        option_symbols = []
        for strike in strikes:
            for opt_type in ['C', 'P']:
                sym = f'CZCE.{opt_prefix}{opt_type}{strike}'
                option_symbols.append((sym, strike, opt_type))
                option_quotes[sym] = api.get_quote(sym)

        _option_symbols = option_symbols
        print(f"[iv_smile] 订阅期权数: {len(option_symbols)}")

        # === 等待所有期权行情到达 ===
        print("[iv_smile] 等待期权行情...")
        data_ready_count = 0
        for i in range(max_wait):
            api.wait_update()
            loop.run_until_complete(asyncio.sleep(0.1))
            count = 0
            for sym, _, _ in option_symbols:
                oq = option_quotes.get(sym)
                if oq:
                    bid = getattr(oq, 'bid_price1', None)
                    if bid and bid > 0:
                        count += 1
            if count > data_ready_count:
                print(f"  wait_update {i}: {count}/{len(option_symbols)} 个期权有报价")
                data_ready_count = count
            if count >= len(option_symbols) * 0.8:  # 80%有报价就继续
                break

        _state['data_ready'] = True
        _tqsdk_ready = True
        print(f"[iv_smile] ✅ 数据就绪，{data_ready_count}/{len(option_symbols)} 个期权有有效报价")

        # === 主事件循环 ===
        counter = 0
        while _state['running']:
            try:
                api.wait_update(deadline=loop.time() + 1.0)

                # 每5秒快照一次（用于compute_once）
                counter += 1
                if counter % 5 == 0:
                    snap = {
                        'futures': {
                            'last': getattr(fut_quote, 'last_price', None),
                            'bid': getattr(fut_quote, 'bid_price1', None),
                            'ask': getattr(fut_quote, 'ask_price1', None),
                        },
                        'options': {},
                    }
                    for sym, _, _ in option_symbols:
                        oq = option_quotes.get(sym)
                        if oq:
                            snap['options'][sym] = {
                                'bid': getattr(oq, 'bid_price1', None) or 0,
                                'ask': getattr(oq, 'ask_price1', None) or 0,
                                'last': getattr(oq, 'last_price', None) or 0,
                            }
                    _tqsdk_quotes['snap'] = snap

            except Exception as e:
                if _state['running']:
                    print(f"[iv_smile] wait_update异常: {e}")
                break

        api.close()
        loop.close()
        print("[iv_smile] TQSdk线程已退出")

    except Exception as e:
        print(f"[iv_smile] TQSdk线程异常: {e}")
        import traceback; traceback.print_exc()
        _tqsdk_ready = False

# ===================== 核心计算 =====================

def calc_max_pain(opt_snap, S):
    """
    计算最大痛点行权价。
    opt_snap: {strike: {'C': oi, 'P': oi}} 或 {strike: {'C': oi_or_None, 'P': oi_or_None}}
    S: 当前期货价格（偶数化）
    返回: 最大痛点行权价（偶数），或 None
    """
    if not opt_snap:
        return None

    strikes = sorted(opt_snap.keys())
    if len(strikes) < 2:
        return None

    mp = {}
    for K in strikes:
        c_oi = opt_snap[K].get('C') or 0
        p_oi = opt_snap[K].get('P') or 0
        # 最大痛点：持有到期的总损耗最小 → 取损耗最大的K
        # Call损耗 = OI_C * max(K - S, 0)，Put损耗 = OI_P * max(S - K, 0)
        call_loss = c_oi * max(K - S, 0)
        put_loss  = p_oi * max(S - K, 0)
        mp[K] = call_loss + put_loss

    if not mp or sum(mp.values()) == 0:
        return None

    # 返回损耗最大的行权价（偶数）
    max_pain_strike = max(mp, key=lambda k: mp[k])
    # PTA tick=2，保持偶数
    return round(max_pain_strike / 2) * 2


def compute_once():
    """执行一次IV计算（每分钟实时触发）"""
    global _state

    if not _state.get('data_ready') or 'snap' not in _tqsdk_quotes:
        print("[iv_smile] 数据尚未到达")
        return False

    snap = _tqsdk_quotes.get('snap')
    if not snap:
        return False

    # 1. 实时期货价格（每分钟快照最新值）
    fut = snap.get('futures', {})
    S = None
    bid = fut.get('bid')
    ask = fut.get('ask')
    if bid and ask and bid > 0 and ask > 0:
        S = (bid + ask) / 2
    if not S:
        last = fut.get('last')
        if last and last > 0:
            S = last
    if not S or S <= 0:
        S = _last_valid.get('futures_price')
    if not S or S <= 0:
        print("[iv_smile] 无法获取期货价格")
        return False

    # PTA 最小变动价位=2，取偶数
    S = round(S / 2) * 2

    # 2. 持仓量数据 + 计算最大痛点
    opt_snap = snap.get('options', {})

    # 构建 {strike: {C/P: oi}} 结构（仅用有报价的档位）
    strike_oi = {}
    for sym, strike, opt_type in _option_symbols:
        q = opt_snap.get(sym, {})
        oi = q.get('open_interest') or q.get('oi') or 0
        if oi > 0:
            if strike not in strike_oi:
                strike_oi[strike] = {'C': 0, 'P': 0}
            strike_oi[strike][opt_type] = oi

    max_pain = calc_max_pain(strike_oi, S)
    if max_pain is None:
        # 兜底：用期货价估算
        max_pain = round(S / 100) * 100

    # 参考行权价 = 最大痛点
    ref_strike = max_pain

    # 3. 剩余期限（年）
    expiry = _state.get('expiry')
    if not expiry:
        print("[iv_smile] 到期日未设置")
        return False
    T = (expiry - datetime.now()).total_seconds() / (365.25 * 24 * 3600)
    if T <= 0:
        T = 1 / 365

    # 4. 收集IV（用买卖价中点）
    raw_iv = {}
    for sym, strike, opt_type in _option_symbols:
        q = opt_snap.get(sym)
        if not q:
            continue
        bid, ask = q.get('bid', 0), q.get('ask', 0)
        if not bid or not ask or bid <= 0 or ask <= 0:
            continue
        mid = (bid + ask) / 2
        if mid <= 0:
            continue

        iv = bs_iv_brent(S, strike, T, _state['rate'], mid, opt_type)
        if iv is not None and not np.isnan(iv):
            if strike not in raw_iv:
                raw_iv[strike] = {}
            raw_iv[strike][opt_type] = iv

    if len(raw_iv) < 3:
        print(f"[iv_smile] 有效期权太少: {len(raw_iv)}")
        return False

    # 5. SABR平滑
    K_list, IV_list = [], []
    for strike in sorted(raw_iv.keys()):
        for opt in ['C', 'P']:
            if opt in raw_iv[strike]:
                K_list.append(strike)
                IV_list.append(raw_iv[strike][opt])

    smooth_iv, sabr = smooth_smile(K_list, IV_list, S, T)

    if not smooth_iv:
        print(f"[iv_smile] SABR拟合失败，跳过")
        return False

    with _state['lock']:
        # 按固定15分钟时间点存储快照
        now = datetime.now()
        interval_key = get_interval_key(now)
        _interval_snapshots[interval_key] = {
            'smooth': {k: float(v) for k, v in smooth_iv.items()},
            'raw': {k: dict(v) for k, v in raw_iv.items()},  # 包含C和P的原始IV
            'timestamp': now.isoformat(),
            'sabr_params': sabr,
        }
        # 只保留当天9:00-15:00的快照（开盘时间段）
        # 清理旧快照（可选：按时间过滤）
        current_hour = now.hour
        if current_hour >= 9 and current_hour <= 15:
            pass  # 在交易时间段，正常保存
        else:
            # 盘后清除旧数据，只保留最新一个
            if len(_interval_snapshots) > 1:
                _interval_snapshots.clear()
                _interval_snapshots[interval_key] = {
                    'smooth': {k: float(v) for k, v in smooth_iv.items()},
                    'raw': {k: dict(v) for k, v in raw_iv.items()},
                    'timestamp': now.isoformat(),
                    'sabr_params': sabr,
                }

        # 更新缓存
        _last_valid['futures_price'] = S
        _last_valid['ref_strike'] = ref_strike
        _last_valid['max_pain'] = max_pain
        _last_valid['smile_raw'] = {k: v for k, v in raw_iv.items()}
        _last_valid['smile_smooth'] = smooth_iv
        _last_valid['sabr_params'] = sabr

        # 更新状态
        _state['futures_price'] = S
        _state['ref_strike'] = ref_strike   # 最大痛点（参考行权价）
        _state['max_pain'] = max_pain        # 最大痛点
        _state['atm_strike'] = max_pain      # 前端用atm_strike字段，统一返回最大痛点
        _state['smile_raw'] = {k: v for k, v in raw_iv.items()}
        _state['smile_smooth'] = smooth_iv
        _state['sabr_params'] = sabr
        _state['last_update'] = now.isoformat()

    sabr_str = (f"α={sabr['alpha']:.3f} ρ={sabr['rho']:.2f} ν={sabr['nu']:.2f}") if sabr else "失败"
    mp_str = f"MP={max_pain}" if max_pain else ""
    print(f"[iv_smile] ✅ S={S:.0f} {mp_str} 档位={len(raw_iv)} SABR({sabr_str})")
    return True

# ===================== 定时调度 =====================

# 调度器：记录是否已做日终快照
_saved_today = False

def start_scheduler(interval_minutes=1):
    def loop():
        global _saved_today
        print(f"[iv_smile] 调度器启动，间隔={interval_minutes}分钟")
        counter = 0
        while _state['running']:
            compute_once()
            counter += 1
            # 每天 22:45 自动保存夜盘快照
            if not _saved_today:
                now = datetime.now()
                if now.hour == 22 and now.minute >= 45:
                    _save_night_session_snapshot()
                    _saved_today = True
            # 新的一天（0点）重置标志
            elif _saved_today and datetime.now().hour == 0:
                _saved_today = False
            if counter % 5 == 0:
                print(f"[iv_smile] ⏰ 定时更新 S={_state.get('futures_price')} MP={_state.get('max_pain')}")
            for _ in range(interval_minutes * 60):
                if not _state['running']:
                    break
                time.sleep(1)
    t = Thread(target=loop, daemon=True)
    t.start()
    return t


# ===================== Flask API（可被主服务复用） =====================

def register_routes(app):
    """将 iv_smile 路由注册到主 Flask app（避免独立进程）"""
    from flask import render_template, jsonify

    @app.route('/iv_smile')
    def iv_smile_page():
        return render_template('iv_smile.html')

    @app.route('/api/iv_smile/status')
    def iv_api_status():
        with _state['lock']:
            return jsonify({
                'running': _state['running'],
                'tqsdk_ready': _tqsdk_ready,
                'data_ready': _state.get('data_ready', False),
                'futures_price': _state['futures_price'],
                'ref_strike': _state.get('ref_strike'),   # 最大痛点
                'max_pain': _state.get('max_pain'),        # 最大痛点（兼容）
                'atm_strike': _state['atm_strike'],
                'option_count': len(_state.get('smile_raw', {})),
                'last_update': _state['last_update'],
                'expiry': _state['expiry'].isoformat() if _state.get('expiry') else None,
                'rate': _state['rate'],
                'active_contract': _state.get('active_contract'),
                'option_count': len(_option_symbols),
            })

    @app.route('/api/iv_smile/curve')
    def iv_api_curve():
        # 获取当前时间对应的15分钟时间点和上一个时间点
        now = datetime.now()
        current_key = get_interval_key(now)
        prev_key = get_prev_interval_key(now)

        # 尝试获取上一个时间点的快照；如果没找到，兜底用昨夜盘快照
        with _state['lock']:
            prev_snap = _interval_snapshots.get(prev_key) or _interval_snapshots.get('night', {})
            prev_smooth = prev_snap.get('smooth', {})
            prev_raw = prev_snap.get('raw', {})
            raw = _state['smile_raw']
            smooth = _state['smile_smooth']
            sabr = _state['sabr_params']

            # 判断是否用了昨夜盘快照（作为兜底）
            using_night_fallback = (prev_key not in _interval_snapshots) and ('night' in _interval_snapshots)

        strikes = sorted(set(list(raw.keys()) + list(smooth.keys()))) if smooth else sorted(raw.keys())
        curve_data = []
        for k in strikes:
            entry = {'strike': int(k)}
            if k in raw:
                entry['raw_C'] = raw[k].get('C')
                entry['raw_P'] = raw[k].get('P')
                vals = [v for v in raw[k].values() if v and not np.isnan(v)]
                entry['raw_avg'] = float(np.mean(vals)) if vals else None
            if k in smooth:
                entry['smooth'] = smooth[k]
            # 15分钟前的平滑曲线
            if prev_key and k in prev_smooth:
                entry['smooth_prev'] = prev_smooth[k]
                entry['prev_avg'] = prev_smooth[k]
            # 15分钟前的原始Call/Put IV
            if prev_key and k in prev_raw:
                entry['raw_C_prev'] = prev_raw[k].get('C')
                entry['raw_P_prev'] = prev_raw[k].get('P')
            curve_data.append(entry)

        # 格式化prev_timestamp（更友好）
        prev_ts = prev_snap.get('timestamp', '')
        if prev_ts:
            try:
                prev_dt = datetime.fromisoformat(prev_ts)
                prev_ts_display = prev_dt.strftime('%H:%M')
            except:
                prev_ts_display = prev_ts[11:16] if len(prev_ts) > 16 else prev_ts
        else:
            prev_ts_display = None

        # 如果用了昨夜盘兜底，timestamp改为"昨收盘"
        if using_night_fallback and not prev_ts_display:
            prev_ts_display = '昨收盘'

        return jsonify({
            'futures_price': _state['futures_price'],
            'ref_strike': _state.get('ref_strike'),
            'max_pain': _state.get('max_pain'),
            'atm_strike': _state['atm_strike'],
            'last_update': _state['last_update'],
            'sabr_params': sabr,
            'curve': curve_data,
            'prev_timestamp': prev_ts_display,      # 格式: "09:30" 或 "昨收盘"
            'prev_interval_key': prev_key,          # 格式: "09:30"
            'current_interval_key': current_key,   # 格式: "09:45"
            'using_night_fallback': using_night_fallback,  # 是否用了昨夜盘兜底
        })

    @app.route('/api/iv_smile/trigger', methods=['POST'])
    def iv_api_trigger():
        success = compute_once()
        return jsonify({'success': success})

    @app.route('/api/iv_smile/chart_img')
    def iv_api_chart_img():
        """服务端渲染隐波微笑曲线图片，绕过前端JS环境问题"""
        from flask import request, jsonify
        chart_type = request.args.get('type', 'smile')
        try:
            now = datetime.now()
            prev_key = get_prev_interval_key(now)
            with _state['lock']:
                raw = _state.get('smile_raw', {})
                smooth = _state.get('smile_smooth', {})
                prev_snap = _interval_snapshots.get(prev_key, {})
                prev_smooth = prev_snap.get('smooth', {})
                atm_strike = _state.get('atm_strike')
                futures_price = _state.get('futures_price')
                sabr = _state.get('sabr_params', {})
                last_update = _state.get('last_update', '')

            plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial', 'Helvetica']
            plt.rcParams['axes.unicode_minus'] = False

            if chart_type == 'atm':
                # ATM隐波对比柱状图
                if not atm_strike or atm_strike not in smooth:
                    return b'no data', 200, {'Content-Type': 'image/png'}
                curr_iv = smooth.get(atm_strike, 0) * 100
                prev_iv = prev_smooth.get(atm_strike, 0) * 100 if prev_smooth else 0
                diff_iv = curr_iv - prev_iv if prev_smooth else 0

                fig, ax = plt.subplots(figsize=(8, 4), facecolor='#12121a')
                ax.set_facecolor('#12121a')
                x = ['ATM IV\n(prev)', 'ATM IV\n(current)']
                y = [prev_iv, curr_iv]
                colors = ['#8888ff' if prev_smooth else '#555', '#ffaa00']
                bars = ax.bar(x, y, color=colors, width=0.4, edgecolor='#2a2a4a')
                for bar, val in zip(bars, y):
                    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                           f'{val:.2f}%', ha='center', va='bottom', color='#aaa', fontsize=11)
                if prev_smooth:
                    ax.annotate('', xy=(1, curr_iv), xytext=(0, prev_iv),
                               arrowprops=dict(arrowstyle='->', color='#00ff88', lw=1.5))
                    ax.text(0.5, (curr_iv + prev_iv)/2, f'{diff_iv:+.2f}%',
                           ha='center', va='center', color='#00ff88', fontsize=10,
                           bbox=dict(boxstyle='round,pad=0.3', facecolor='#1a1a2a', edgecolor='#00ff88'))
                ax.set_ylabel('IV (%)', color='#888', fontsize=10)
                ax.set_title(f'ATM IV @ {atm_strike} | S={futures_price} | {last_update[:19]}',
                           color='#888', fontsize=10)
                ax.tick_params(colors='#666')
                ax.spines['bottom'].set_color('#2a2a4a')
                ax.spines['left'].set_color('#2a2a4a')
                ax.spines['top'].set_visible(False)
                ax.spines['right'].set_visible(False)
                ax.grid(True, axis='y', color='#1a1a2a', linestyle='--')
                ax.set_ylim(0, max(y) * 1.2 if y else 0.5)
            else:
                # 隐波微笑曲线
                strikes = sorted(set(list(raw.keys()) + list(smooth.keys())))
                fig, ax = plt.subplots(figsize=(10, 5), facecolor='#12121a')
                ax.set_facecolor('#12121a')

                call_x, call_y = [], []
                put_x, put_y = [], []
                for k in strikes:
                    if k in raw and raw[k].get('C'):
                        call_x.append(k); call_y.append(raw[k]['C'] * 100)
                    if k in raw and raw[k].get('P'):
                        put_x.append(k); put_y.append(raw[k]['P'] * 100)

                if call_x:
                    ax.scatter(call_x, call_y, color='#00d4ff', s=30, alpha=0.5, zorder=2, label='Call IV')
                if put_x:
                    ax.scatter(put_x, put_y, color='#ff6b9d', s=30, alpha=0.5, zorder=2, label='Put IV')

                xs = sorted([k for k in strikes if k in smooth])
                ys = [smooth[k] * 100 for k in xs]
                ax.plot(xs, ys, color='#ffaa00', linewidth=2.5, label='Smooth (current)', zorder=4)

                if prev_smooth:
                    xs_p = sorted([k for k in strikes if k in prev_smooth])
                    ys_p = [prev_smooth[k] * 100 for k in xs_p]
                    ax.plot(xs_p, ys_p, color='#8888ff', linewidth=2, linestyle='--', label='Smooth (15min ago)', zorder=3)

                if atm_strike:
                    ax.axvline(x=atm_strike, color='#00ff88', linestyle=':', linewidth=1, alpha=0.7)
                    ax.text(atm_strike, ax.get_ylim()[0] if ax.get_ylim()[0] > 0 else 5,
                            f' ATM={atm_strike}', color='#00ff88', fontsize=9, va='bottom')

                ax.set_xlabel('Strike', color='#888', fontsize=10)
                ax.set_ylabel('IV (%)', color='#888', fontsize=10)
                ax.tick_params(colors='#666', labelsize=9)
                ax.spines['bottom'].set_color('#2a2a4a')
                ax.spines['left'].set_color('#2a2a4a')
                ax.spines['top'].set_visible(False)
                ax.spines['right'].set_visible(False)
                ax.grid(True, color='#1a1a2a', linestyle='--', linewidth=0.5)
                ax.legend(loc='upper left', fontsize=9, facecolor='#1a1a2a', edgecolor='#2a2a4a', labelcolor='#aaa')

                sabr_str = (f"α={sabr.get('alpha',0):.3f} ρ={sabr.get('rho',0):.2f} ν={sabr.get('nu',0):.2f}"
                            if sabr else "SABR N/A")
                ax.set_title(f'PTA IV Smile | S={futures_price} | {last_update[:19]} | {sabr_str}',
                            color='#888', fontsize=10)

            buf = BytesIO()
            plt.savefig(buf, format='png', dpi=100, bbox_inches='tight',
                       facecolor='#12121a', edgecolor='none')
            buf.seek(0)
            plt.close(fig)
            return buf.getvalue(), 200, {'Content-Type': 'image/png',
                                          'Cache-Control': 'no-cache'}
        except Exception as e:
            import traceback; traceback.print_exc()
            return jsonify({'error': str(e)}), 500


# ===================== 入口 =====================

def main():
    global _state, _tqsdk_thread
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--interval', type=int, default=15)
    parser.add_argument('--port', type=int, default=5002)
    args = parser.parse_args()

    print("=" * 60)
    print("PTA期权隐波微笑曲线实时服务 v4 (动态主力合约)")
    print("=" * 60)

    _state['running'] = True
    _tqsdk_thread = Thread(target=tqsdk_loop, daemon=True)
    _tqsdk_thread.start()

    # 等待数据就绪（最多90秒）
    print("[iv_smile] 等待数据就绪...")
    for i in range(90):
        time.sleep(1)
        if _state.get('data_ready'):
            print("[iv_smile] ✅ 数据已就绪")
            break
        if i % 15 == 0 and i > 0:
            print(f"[iv_smile] 等待中... {i+1}/90秒")
    else:
        print("[iv_smile] ⚠️ 数据等待超时，继续启动（可用trigger手动触发）")

    # 首次计算
    if _state.get('data_ready'):
        print("[iv_smile] 执行首次计算...")
        compute_once()

    # 启动调度器
    scheduler_t = start_scheduler(interval_minutes=args.interval)

    # 启动Flask（独立进程模式）
    from flask import Flask
    app = Flask(__name__,
                template_folder='templates',
                static_folder='static',
                static_url_path='/static')
    register_routes(app)
    print(f"[iv_smile] 🌐 API http://0.0.0.0:{args.port}/")
    app.run(host='0.0.0.0', port=args.port, debug=False, threaded=True)

if __name__ == '__main__':
    main()


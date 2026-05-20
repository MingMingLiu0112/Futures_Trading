
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

# 历史快照（用于前后对比）
# 每个快照: {'smooth': {strike: iv}, 'raw': {strike: {C, P}}, 'timestamp': str, 'sabr_params': {...}}
_smile_history = {
    'current': None,       # 当前周期的平滑曲线
    'prev_15min': None,    # 15分钟前的快照
    'prev_timestamp': None,
}

_tqsdk_thread = None
_tqsdk_ready = False
_option_symbols = []
_tqsdk_quotes = {}

# ===================== 动态查主力合约 =====================

def get_active_ta_contract():
    """
    探测TA系列合约，返回 (opt_prefix, expiry_str)
    郑商所PTA期权月份: 1,5,9月轮转
    当前(2026年5月): 主力TA606(6月到期), 次力TA609(9月到期)
    """
    from calendar import monthrange
    now = datetime.now()
    year_digit = now.year - 2000  # 26

    # PTA期权的规则：1/5/9月
    # 当前月份往后找最近的1/5/9月
    cycle = [1, 5, 9]
    for m in sorted(cycle):
        if m > now.month:
            front_month = m
            year = now.year
            break
    else:
        front_month = cycle[0]
        year = now.year + 1

    opt_prefix = f"TA{(year_digit % 10)}{front_month:02d}"
    # 郑商所期权到期日：标的期货交割月前第二个周五
    # 简化：每月15日附近
    last_day = monthrange(year, front_month)[1]
    expiry = datetime(year, front_month, min(12, last_day))

    return opt_prefix, expiry


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

def sabr_vol_impl(F, K, T, alpha, rho, nu, c):
    """SABR近似公式 (Hagan 2002)"""
    FK = F * K
    if FK <= 0:
        return np.nan
    logFK = np.log(FK)
    sqrtFK = np.sqrt(FK)

    denom = 1 + ((1 - c) ** 2 / 24) * logFK ** 2 + ((1 - c) ** 4 / 1920) * logFK ** 4
    term1 = alpha / (FK ** ((1 - c) / 2) * denom)

    z = (nu / alpha) * sqrtFK * logFK
    eps = 1e-10
    if abs(z) < eps:
        z = eps

    sqrt_term = (1 - 2 * rho * z + z ** 2) ** 0.5
    x_z = np.log((sqrt_term + z - rho) / (1 - rho))
    if abs(x_z) < eps:
        x_z = eps

    term2 = 1 + ((1 - c) ** 2 / 24 * alpha ** 2 +
                  0.25 * rho * nu * alpha * FK +
                  (2 - 3 * rho ** 2) / 24 * nu ** 2) * T

    if abs(K - F) < 1.0:
        return alpha * (FK ** ((1 - c) / 2)) * term2

    return term1 * term2 * z / x_z

def fit_sabr(K_list, IV_list, F, T):
    """LM算法拟合SABR参数"""
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
    alpha0 = max(min(alpha0, 0.5), 0.05)

    def residuals(params):
        alpha, rho, nu, c = params
        if alpha <= 0 or nu <= 0 or abs(rho) >= 1 or c < -1 or c > 1:
            return np.ones(len(K_v)) * 1e6
        modeled = np.array([sabr_vol_impl(F, k, T, alpha, rho, nu, c) for k in K_v])
        return IV_v - modeled

    try:
        result = least_squares(
            residuals,
            [alpha0, -0.3, 0.4, 0.3],
            bounds=([0.001, -0.999, 0.001, -0.999], [2.0, 0.999, 5.0, 0.999]),
            method='lm',
            max_nfev=500
        )
        if result.success:
            return {
                'alpha': float(result.x[0]),
                'rho': float(result.x[1]),
                'nu': float(result.x[2]),
                'c': float(result.x[3]),
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

    alpha, rho, nu, c = sabr['alpha'], sabr['rho'], sabr['nu'], sabr['c']
    smooth_iv = {}
    for k in sorted(K_list):
        iv = sabr_vol_impl(F, k, T, alpha, rho, nu, c)
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

def compute_once():
    """执行一次IV计算"""
    global _state

    if not _state.get('data_ready') or 'snap' not in _tqsdk_quotes:
        print("[iv_smile] 数据尚未到达")
        return False

    snap = _tqsdk_quotes.get('snap')
    if not snap:
        return False

    # 1. 期货价格（用中价）
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
        print("[iv_smile] 无法获取期货价格")
        return False

    # 2. ATM
    atm_strike = round(S / 100) * 100

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
    opt_snap = snap.get('options', {})

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

    # 5. 构建IV序列（只取C和P都有的档位做SABR）
    K_list, IV_list = [], []
    for strike in sorted(raw_iv.keys()):
        for opt in ['C', 'P']:
            if opt in raw_iv[strike]:
                K_list.append(strike)
                IV_list.append(raw_iv[strike][opt])

    # 6. SABR平滑
    smooth_iv, sabr = smooth_smile(K_list, IV_list, S, T)

    with _state['lock']:
        # 保存历史快照（15分钟前的平滑曲线）
        if _smile_history['current'] is not None:
            _smile_history['prev_15min'] = _smile_history['current']['smooth'].copy()
            _smile_history['prev_timestamp'] = _smile_history['current']['timestamp']

        # 更新当前曲线
        current_snapshot = {
            'smooth': {k: float(v) for k, v in smooth_iv.items()},
            'timestamp': datetime.now().isoformat(),
            'sabr_params': sabr,
        }
        _smile_history['current'] = current_snapshot

        _state['futures_price'] = S
        _state['atm_strike'] = atm_strike
        _state['smile_raw'] = {k: v for k, v in raw_iv.items()}
        _state['smile_smooth'] = smooth_iv
        _state['sabr_params'] = sabr
        _state['last_update'] = datetime.now().isoformat()

    sabr_str = (f"α={sabr['alpha']:.3f} ρ={sabr['rho']:.2f} "
                f"ν={sabr['nu']:.2f} c={sabr['c']:.2f}") if sabr else "失败"
    prev_str = ""
    if _smile_history['prev_15min']:
        prev_str = f" | 前次曲线时间: {_smile_history['prev_timestamp']}"
    print(f"[iv_smile] ✅ S={S:.0f} ATM={atm_strike} "
          f"档位={len(raw_iv)} SABR({sabr_str}){prev_str}")
    return True

# ===================== 定时调度 =====================

def start_scheduler(interval_minutes=15):
    def loop():
        print(f"[iv_smile] 调度器启动，间隔={interval_minutes}分钟")
        while _state['running']:
            compute_once()
            for _ in range(interval_minutes * 60):
                if not _state['running']:
                    break
                time.sleep(1)
    t = Thread(target=loop, daemon=True)
    t.start()
    return t

# ===================== Flask API =====================

def create_app():
    from flask import Flask, jsonify
    app = Flask(__name__, template_folder='templates')

    @app.route('/api/iv_smile/status')
    def api_status():
        with _state['lock']:
            return jsonify({
                'running': _state['running'],
                'tqsdk_ready': _tqsdk_ready,
                'data_ready': _state.get('data_ready', False),
                'futures_price': _state['futures_price'],
                'atm_strike': _state['atm_strike'],
                'last_update': _state['last_update'],
                'expiry': _state['expiry'].isoformat() if _state.get('expiry') else None,
                'rate': _state['rate'],
                'active_contract': _state.get('active_contract'),
                'option_count': len(_option_symbols),
            })

    @app.route('/api/iv_smile/curve')
    def api_curve():
        with _state['lock']:
            raw = _state['smile_raw']
            smooth = _state['smile_smooth']
            sabr = _state['sabr_params']
            prev_snap = _smile_history.get('prev_15min') or {}

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
            if prev_snap and k in prev_snap.get('smooth', {}):
                entry['smooth_prev'] = prev_snap['smooth'][k]
            # 15分钟前的原始Call/Put IV
            prev_raw = prev_snap.get('raw', {})
            if k in prev_raw:
                entry['raw_C_prev'] = prev_raw[k].get('C')
                entry['raw_P_prev'] = prev_raw[k].get('P')
            curve_data.append(entry)

        return jsonify({
            'futures_price': _state['futures_price'],
            'atm_strike': _state['atm_strike'],
            'last_update': _state['last_update'],
            'sabr_params': sabr,
            'curve': curve_data,
            'prev_timestamp': _smile_history.get('prev_timestamp'),
        })

    @app.route('/api/iv_smile/trigger', methods=['POST'])
    def api_trigger():
        success = compute_once()
        return jsonify({'success': success})

    @app.route('/')
    def index():
        from flask import render_template
        return render_template('iv_smile.html')

    @app.route('/iv_compare')
    def iv_compare_page():
        from flask import render_template
        return render_template('iv_smile_compare.html')

    return app

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

    # 启动Flask
    app = create_app()
    print(f"[iv_smile] 🌐 API http://0.0.0.0:{args.port}/")
    app.run(host='0.0.0.0', port=args.port, debug=False, threaded=True)

if __name__ == '__main__':
    main()

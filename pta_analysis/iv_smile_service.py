












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
from datetime import datetime, timedelta, date
from threading import Thread, Lock
import numpy as np
import requests

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
    'svi_params': None,
    'expiry': None,
    'rate': 0.0225,
    'rate_src': 'default(2.25%)',
    'running': False,
    'lock': Lock(),
    'active_contract': None,
    'data_ready': False,   # 数据是否真正到达
    'strike_vol': {},      # {strike: {'C': volume, 'P': volume}} 期权成交量
}
# 飞书Webhook（用于IV变化报警）
_FEISHU_WEBHOOK = os.environ.get('FEISHU_WEBHOOK', '')

# 缓存：连接失败时保留上一次正确值
_last_valid = {
    'futures_price': None,
    'atm_strike': None,
    'smile_raw': {},
    'smile_smooth': {},
    'svi_params': None,
    'strike_vol': {},
}

# 历史快照（按固定15分钟时间点存储）
# key: "HH:MM" 如 "09:00", "09:15", ... 或 'night'（昨夜盘锚点）
# value: {'smooth': {strike: iv}, 'raw': {strike: {'C': iv, 'P': iv}}, 'timestamp': str}
_interval_snapshots = {}          # 内存快照: key="HH:MM" 或 "night"（仅当天数据）
_interval_loaded_from_disk = set()  # 已从磁盘加载的日期，避免重复
_prev_day_baseline = {}           # 前一交易日15:00收盘快照（启动时从磁盘加载）
                                  # {'smooth': {}, 'raw': {}, 'strike_oi': {}, 'strike_vol': {}, 'timestamp': str, 'futures_price': float}


# IV变化报警追踪（避免重复报警）
_iv_alert_sent_today = set()       # 今天已发送的报警记录: {(strike, direction), ...}
_iv_alert_last_send_time = {}      # 上次发送时间: {f"{strike}_{dir}": timestamp}
_iv_alert_last_direction = {}      # 上次报警方向: {f"{strike}": 'up'|'down', f"oi_{strike}_{side}": 'up'|'down'}
_iv_alert_dynamic_baseline = {}    # 动态基准: {strike: smooth_iv_value} — 每次IV报警触发后更新，用于捕捉盘中二次变化
_iv_alert_dynamic_raw_baseline = {}  # 兼容旧逻辑：动态raw基准
_oi_alert_dynamic_baseline = {}    # 兼容旧逻辑：OI动态基准
_iv_alert_watermarks = {}          # {"strike_side": {'trend':'up/down','extreme':float}} 报警后同向最高/最低点
_oi_alert_watermarks = {}          # {"strike_side": {'trend':'up/down','extreme':int}} 报警后同向最高/最低点

# 每日收盘基准快照（15:00 收盘时记录，作为盘中对比基准）
_close_baseline = {}               # {'smooth': {}, 'raw': {}, 'strike_oi': {}, 'strike_vol': {}, 'S': float, 'ts': str}

# ===================== IV变化报警（基于15:00收盘基准） =====================
# 阈值逻辑与主页期权链一致：按波动环境/持仓量级分档
_IV_ALERT_COOLDOWN = 900           # 飞书同一档位同一方向，至少隔15分钟再报
_IV_ALERT_THRESHOLD = 0.06         # 默认6% IV变化阈值（GET时兜底用，避免NameError）

def _get_iv_thresholds(avg_iv):
    """按平均波动率返回IV变化阈值（与主页期权链一致）
    低波 IV<20%:  noise<1.5%  显著≥1.5%  重大≥3%
    中波 20%≤IV<30%: noise<2%  显著≥2%   重大≥4%
    高波 IV≥30%:   noise<3%  显著≥3%    重大≥6%
    """
    if avg_iv >= 0.30:
        return {'noise': 0.03, 'significant': 0.03, 'extreme': 0.06}
    if avg_iv >= 0.20:
        return {'noise': 0.02, 'significant': 0.02, 'extreme': 0.04}
    return {'noise': 0.015, 'significant': 0.015, 'extreme': 0.03}

def _get_oi_thresholds(oi):
    """按持仓量返回持仓变化阈值（与主页期权链一致）
    < 3000手:    noise<10%   显著≥10%   重大≥25%
    3000-10000手: noise<7%   显著≥7%    重大≥15%
    > 10000手:  noise<5%    显著≥5%    重大≥10%
    """
    if oi >= 10000:
        return {'noise': 0.05, 'sigLow': 0.05, 'extreme': 0.10}
    if oi >= 3000:
        return {'noise': 0.07, 'sigLow': 0.07, 'extreme': 0.15}
    return {'noise': 0.10, 'sigLow': 0.10, 'extreme': 0.25}

def _record_close_baseline(smile_smooth, smile_raw, strike_oi, S, strike_vol=None):
    """记录每日15:00收盘基准快照，同时重置报警状态"""
    global _close_baseline, _iv_alert_dynamic_baseline, _iv_alert_dynamic_raw_baseline, _oi_alert_dynamic_baseline, _iv_alert_watermarks, _oi_alert_watermarks
    _close_baseline = {
        'smooth': {k: float(v) for k, v in smile_smooth.items()},
        'raw': {k: dict(v) for k, v in smile_raw.items()},
        'strike_oi': {k: dict(v) for k, v in strike_oi.items()},
        'strike_vol': {k: dict(v) for k, v in (strike_vol or {}).items()},
        'S': float(S),
        'ts': datetime.now().isoformat(),
        'contract': _state.get('active_contract'),
        'expiry': _state.get('expiry').isoformat() if _state.get('expiry') else None,
    }
    # 新基准生效，清空所有报警追踪状态
    _iv_alert_sent_today.clear()
    _iv_alert_last_send_time.clear()
    _iv_alert_last_direction.clear()
    _iv_alert_dynamic_baseline = {}
    _iv_alert_dynamic_raw_baseline = {}
    _oi_alert_dynamic_baseline = {}
    _iv_alert_watermarks = {}
    _oi_alert_watermarks = {}
    print(f"[iv_smile] 📌 收盘基准已记录: {len(smile_smooth)}档 S={S:.0f}")

def _check_iv_alert(smile_smooth, smile_raw, strike_oi, S, max_pain):
    """
    检查IV和持仓变化，触发飞书报警（对比当日15:00基准，同档位方向至少隔15分钟）。
    返回 (iv_alerts, oi_alerts) 列表。
    iv_alerts 元素: (strike, side, level, cur_val, ref_val, change, ref_type)
      ref_type: 'close' = 相对收盘基准, 'reversal' = 盘中反转（相对动态基准）
    oi_alerts 元素: (strike, side, level, cur_val, prev_val, change)
    level: 'significant' | 'major'
    """
    if not _FEISHU_WEBHOOK:
        return [], []
    if not _close_baseline.get('smooth'):
        return [], []

    now = datetime.now()
    prev_smooth = _close_baseline['smooth']
    prev_oi = _close_baseline.get('strike_oi', {})
    prev_raw = _close_baseline.get('raw', {})

    # 用ATM隐波判断波动环境（比全档位均值更准确）
    atm = _state.get('atm_strike')
    atm_iv = smile_smooth.get(atm) or smile_smooth.get(str(atm)) if atm else None
    if not atm_iv:
        vals = list(smile_smooth.values())
        atm_iv = sum(vals) / len(vals) if vals else 0
    iv_t = _get_iv_thresholds(atm_iv)

    iv_alerts = []
    oi_alerts = []

    for strike, cur_iv in smile_smooth.items():
        prev_iv = prev_smooth.get(strike)
        if prev_iv and prev_iv > 0:
            # 1) 相对收盘基准的变化
            delta_close = cur_iv - prev_iv
            abs_d_close = abs(delta_close)
            # 2) 相对动态基准的变化（捕捉盘中二次变化，如先涨6%再跌8%=14%反转）
            dyn_iv = _iv_alert_dynamic_baseline.get(strike)
            delta_dyn = (cur_iv - dyn_iv) if dyn_iv is not None else None
            abs_d_dyn = abs(delta_dyn) if delta_dyn is not None else 0
            # 取两者中更大的变化幅度
            if abs_d_dyn > abs_d_close:
                delta, abs_d, ref_iv = delta_dyn, abs_d_dyn, dyn_iv
                ref_type = 'reversal'
            else:
                delta, abs_d, ref_iv = delta_close, abs_d_close, prev_iv
                ref_type = 'close'
            if abs_d >= iv_t['significant']:
                direction = 'up' if delta > 0 else 'down'
                key = f"{strike}_{direction}"
                dir_key = f"{strike}"
                last_time = _iv_alert_last_send_time.get(key, 0)
                last_dir = _iv_alert_last_direction.get(dir_key)
                # 方向反转时重置冷却（急涨后急跌，或反之）
                direction_reversed = (last_dir is not None and last_dir != direction)
                if direction_reversed or (now.timestamp() - last_time >= _IV_ALERT_COOLDOWN):
                    level = 'major' if abs_d >= iv_t['extreme'] else 'significant'
                    iv_alerts.append((strike, 'both', level, cur_iv, ref_iv, delta, ref_type))
                    _iv_alert_last_send_time[key] = now.timestamp()
                    _iv_alert_last_direction[dir_key] = direction
                    # 触发后更新动态基准 → 下次变化从此刻开始算
                    _iv_alert_dynamic_baseline[strike] = cur_iv
                    _raw_v = smile_raw.get(strike) or smile_raw.get(int(strike)) if str(strike).isdigit() else smile_raw.get(strike)
                    if isinstance(_raw_v, dict):
                        _iv_alert_dynamic_raw_baseline[strike] = dict(_raw_v)

    # 持仓变化检测（Call/Put分别检测，含盘中反转）
    for strike, cur_ois in strike_oi.items():
        prev_ois = prev_oi.get(strike, {})
        for side, cur_oi in cur_ois.items():
            prev_oi_val = prev_ois.get(side, 0)
            if prev_oi_val <= 0:
                continue
            # 当前OI归零 = 到期清零/深虚值无人持仓，不是异动，跳过
            if cur_oi <= 0:
                continue
            # 1) 相对收盘基准
            delta_close = cur_oi - prev_oi_val
            ratio_close = delta_close / prev_oi_val
            abs_r_close = abs(ratio_close)
            # 2) 相对动态基准（捕捉盘中反转：先增仓30%再减仓20%）
            dyn_key = f"{strike}_{side}"
            dyn_oi = _oi_alert_dynamic_baseline.get(dyn_key)
            if dyn_oi is not None and dyn_oi > 0:
                delta_dyn = cur_oi - dyn_oi
                ratio_dyn = delta_dyn / dyn_oi
                abs_r_dyn = abs(ratio_dyn)
            else:
                ratio_dyn = None
                abs_r_dyn = 0
            # 取两者中更大的变化
            if abs_r_dyn > abs_r_close:
                delta_ratio, abs_d, ref_oi = ratio_dyn, abs_r_dyn, dyn_oi
                oi_ref_type = 'reversal'
            else:
                delta_ratio, abs_d, ref_oi = ratio_close, abs_r_close, prev_oi_val
                oi_ref_type = 'close'
            t = _get_oi_thresholds(ref_oi)
            if abs_d >= t['sigLow']:
                direction = 'up' if delta_ratio > 0 else 'down'
                key = f"oi_{strike}_{side}_{direction}"
                dir_key = f"oi_{strike}_{side}"
                last_time = _iv_alert_last_send_time.get(key, 0)
                last_dir = _iv_alert_last_direction.get(dir_key)
                direction_reversed = (last_dir is not None and last_dir != direction)
                if direction_reversed or (now.timestamp() - last_time >= _IV_ALERT_COOLDOWN):
                    level = 'major' if abs_d >= t['extreme'] else 'significant'
                    oi_alerts.append((strike, side, level, cur_oi, ref_oi, delta_ratio, oi_ref_type))
                    _iv_alert_last_send_time[key] = now.timestamp()
                    _iv_alert_last_direction[dir_key] = direction
                    # 触发后更新动态基准
                    _oi_alert_dynamic_baseline[dyn_key] = cur_oi

    # 发送飞书（仅当有变化时）
    if not iv_alerts and not oi_alerts:
        return iv_alerts, oi_alerts

    lines = [f"【PTA期权异动监控】{now.strftime('%H:%M')}", f"期货价: {S:.0f}  最大痛点: {max_pain}"]
    if iv_alerts:
        lines.append("━━ IV变化 ━━")
        for strike, side, level, cur_v, prv_v, chg, ref_type in iv_alerts:
            if ref_type == 'reversal':
                flag = '⚡' if level == 'major' else '🔶'
                tag = '盘中反转 '
            else:
                flag = '🔴' if level == 'major' else '🟡'
                tag = ''
            lines.append(f"{flag} {tag}{strike}档: {prv_v*100:.1f}%→{cur_v*100:.1f}% ({'+'if chg>0 else ''}{chg*100:.1f}%)")
    if oi_alerts:
        lines.append("━━ 持仓变化 ━━")
        for strike, side, level, cur_v, prv_v, chg, oi_ref_type in oi_alerts:
            if oi_ref_type == 'reversal':
                flag = '⚡' if level == 'major' else '🔶'
                tag = '盘中反转 '
            else:
                flag = '🔴' if level == 'major' else '🟡'
                tag = ''
            side_label = 'Call' if side == 'C' else 'Put'
            lines.append(f"{flag} {tag}{strike}/{side_label}: {prv_v:,}→{cur_v:,} ({'+'if chg>0 else ''}{chg*100:.1f}%)")

    text = '\n'.join(lines)
    try:
        requests.post(_FEISHU_WEBHOOK,
                      json={'msg_type': 'text', 'content': {'text': text}},
                      timeout=10)
        print(f"[iv_smile] 🚨 异动报警已发飞书: IV={len(iv_alerts)}档 OI={len(oi_alerts)}档")
    except Exception as e:
        print(f"[iv_smile] ❌ 飞书报警失败: {e}")

    return iv_alerts, oi_alerts

# ===================== 跨模块共享接口 =====================
def get_shared_futures_price():
    """供其他模块共享的实时期货价格。
    优先返回 iv_smile_service 自有的TqSdk实时价格，
    兜底返回 _last_valid 缓存值（服务重启后也能用）。
    返回 (price, source) 元组：price为float，source为 'tqsdk'/'cache'/'none'。"""
    with _state.get('lock', _dummy_lock):
        p = _state.get('futures_price')
        if p and p > 0:
            return float(p), 'tqsdk'
        p = _last_valid.get('futures_price')
    if p and p > 0:
        return float(p), 'cache'
    return None, 'none'

_dummy_lock = type('DummyLock', (), {'__enter__': lambda s: s, '__exit__': lambda *a: None})()


def _valid_price(value):
    """返回合法正价格 float；无效行情字段（None/nan/inf/0）返回 None。"""
    try:
        if value is None:
            return None
        v = float(value)
        if np.isnan(v) or np.isinf(v) or v <= 0:
            return None
        return v
    except Exception:
        return None


def _get_latest_tqsdk_futures_price():
    """从 TqSdk 最新快照取可用期货价：last > close > bid/ask 中间价。"""
    snap = _tqsdk_quotes.get('snap') or {}
    fut = snap.get('futures') or {}
    price = _valid_price(fut.get('last'))
    source = 'last'
    if price is None:
        price = _valid_price(fut.get('close'))
        source = 'close'
    if price is None:
        bid = _valid_price(fut.get('bid'))
        ask = _valid_price(fut.get('ask'))
        if bid and ask:
            price = (bid + ask) / 2
            source = 'bidask_mid'
    if price is None:
        return None, None
    return round(price / 2) * 2, source


def _set_payload_futures_price(payload, price):
    """同步校准 eod payload 内所有 current price 字段。"""
    if not price or price <= 0:
        return
    for section in ('state', 'last_valid'):
        data = payload.get(section)
        if isinstance(data, dict):
            data['futures_price'] = price
            # API/前端有些地方兼容 underlying_price 字段；若存在则保持一致
            if 'underlying_price' in data:
                data['underlying_price'] = price


def _parse_iso_dt(value):
    """宽容解析 ISO 时间字符串；失败返回 None。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except Exception:
        return None


def _payload_state_timestamp(payload_or_state):
    """取用于 current 防回退比较的时间：state.last_update 优先，其次 payload.timestamp/ts。"""
    if not isinstance(payload_or_state, dict):
        return None
    state = payload_or_state.get('state') if isinstance(payload_or_state.get('state'), dict) else payload_or_state
    return (state.get('last_update') or payload_or_state.get('timestamp')
            or payload_or_state.get('ts') or payload_or_state.get('last_update'))


def _should_restore_current(incoming_ts, source='unknown'):
    """禁止旧快照/close baseline 覆盖更新的 current _state。

    close_state/eod_state/interval snapshot 只能在其时间不早于当前 _state.last_update 时覆盖 current。
    这样 23:00 EOD current 不会被 15:00 close baseline 或旧 interval snapshot 拉回去；
    _close_baseline 仍由 close_state 单独恢复，不受影响。
    """
    current_ts = _state.get('last_update')
    cur_dt = _parse_iso_dt(current_ts)
    in_dt = _parse_iso_dt(incoming_ts)
    if cur_dt and in_dt and in_dt < cur_dt:
        print(f"[iv_smile] 🛡️ 拒绝旧状态覆盖 current: source={source} incoming={str(incoming_ts)[:19]} < current={str(current_ts)[:19]}")
        return False
    return True


def _get_latest_close_boundary_timestamp():
    """扫描今日（+ 昨日兜底）iv_snapshots_*.json 中 close_boundary=True 快照的最晚时间戳。

    用于冷启动时的 priority 判定：今日 10:15/11:30/15:00/23:00 边界
    应当优先于 eod_state.json（昨日 23:00）。让 4 个休盘点都成为 current 的候选锚点。
    """
    from datetime import timedelta
    now = datetime.now()
    today = now.strftime('%Y%m%d')
    yesterday = (now - timedelta(days=1)).strftime('%Y%m%d')
    best_ts = ''
    best_key = None
    best_date = None
    for date_str in (today, yesterday):
        path = _get_snapshot_path(date_str)
        if not os.path.exists(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
            for k, v in (payload.get('snapshots') or {}).items():
                if v.get('close_boundary') and v.get('smooth'):
                    ts = v.get('timestamp', '') or ''
                    if ts and ts > best_ts:
                        best_ts = ts
                        best_key = k
                        best_date = date_str
        except Exception:
            continue
    return best_ts, best_key, best_date


# ===================== 持久化配置 =====================
_SNAPSHOT_DIR = os.path.join(WORKSPACE, 'data', 'iv_snapshots')
_SAVED_DATES = set()   # 记录已写入磁盘的日期，避免重复保存

# PTA 收盘时间点（小盘、午盘、日盘收盘、夜盘收盘）
_PTA_CLOSE_TIMES = [(10, 15), (11, 30), (15, 0), (23, 0)]
_CLOSE_STATE_FILE = os.path.join(_SNAPSHOT_DIR, 'close_state.json')
_EOD_STATE_FILE = os.path.join(_SNAPSHOT_DIR, 'eod_state.json')  # 23:00 收盘完整状态（用于冷启动恢复 _state）
# v2.11.54+: 前次基准独立快照文件。
# 关键设计：close_state.json 是"最新一天 15:00 收盘状态"（盘中状态用），被每日 15:00 覆盖；
# prev_baseline.json 是"前次基准"（昨日 15:00），**只在 21:00 切换时被覆盖**（不在 15:00 覆盖），
# 因此冷启动永远能拿到最近一个 15:00 基准（次日 14:59 启动时 = 今日 15:00 = 昨日的"前次基准"）。
# 写入时机：21:00 夜盘开盘 _ensure_today_close_baseline_after_21() 切换时调用 _save_prev_baseline()。
_PREV_BASELINE_FILE = os.path.join(_SNAPSHOT_DIR, 'prev_baseline.json')
_eod_state_loaded = False  # 全局标记：eod_state.json 是否已加载（避免被 close_state.json 覆盖）
_close_state_saved_slots = set()  # 记录本次进程已保存的收盘时间槽，避免重复
_close_state_last_mtime = 0.0    # 上次已知的 close_state.json mtime，主循环每 60s 轮询一次，新则 reload _close_baseline
_last_close_state_check_ts = 0.0  # 独立计时器，60s 才 stat 一次文件（避免每 1s wait_update 都打磁盘）
_prev_baseline_expected_date = None  # 当前 _prev_day_baseline 加载的预期基准日（YYYYMMDD str）；用于检测节后首日 9:00 切换
_last_prev_baseline_check_ts = 0.0   # 独立计时器，60s 才 stat 一次文件

def _get_snapshot_path(date_str):
    """返回指定日期的日盘快照文件路径（包含全天所有15分钟时间点）。"""
    return os.path.join(_SNAPSHOT_DIR, f'iv_snapshots_{date_str}.json')

def _ensure_snapshot_dir():
    """确保快照目录存在"""
    os.makedirs(_SNAPSHOT_DIR, exist_ok=True)

def _save_prev_baseline(snap_15, today_str):
    """
    v2.11.54+: 21:00 夜盘切换时把今日 15:00 收盘快照写入 prev_baseline.json。
    调用时机：_ensure_today_close_baseline_after_21() 成功切换后（即 21:00 夜盘开盘后）。

    写入策略：
      - snap_15 是从 iv_snapshots_<today_str>.json['15:00'] 槽取出的数据
      - 写入 prev_baseline.json 后即代表"昨日 15:00"的副本（次日 14:59 启动时用）

    关键约束：prev_baseline.json **不被每日 15:00 收盘覆盖**，只在 21:00 切换时写入。
    这样 6/26 14:59 启动时，prev_baseline.json 还是 6/25 15:00（21:00 切换时写入的），
    不会被 6/26 15:00 收盘的 close_state.json 覆盖逻辑污染。
    """
    if not snap_15 or not snap_15.get('smooth'):
        return False
    payload = {
        'close_point': '15:00',
        'timestamp': f'{today_str}T15:00:00',  # 语义：今日 15:00 收盘
        'state': {
            'active_contract': snap_15.get('contract') or _state.get('active_contract'),
            'expiry': snap_15.get('expiry'),
            'futures_price': snap_15.get('S') or snap_15.get('futures_price'),
            'atm_strike': snap_15.get('atm_strike'),
            'max_pain': snap_15.get('max_pain'),
            'ref_strike': snap_15.get('ref_strike'),
            'smile_raw': snap_15.get('raw', {}),
            'smile_smooth': snap_15.get('smooth', {}),
            'svi_params': snap_15.get('svi_params'),
            'last_update': f'{today_str}T15:00:00',
            'strike_oi': snap_15.get('strike_oi', {}),
            'strike_vol': snap_15.get('strike_vol', {}),
        },
        'last_valid': {
            'futures_price': snap_15.get('S') or snap_15.get('futures_price'),
            'atm_strike': snap_15.get('atm_strike'),
            'max_pain': snap_15.get('max_pain'),
            'ref_strike': snap_15.get('ref_strike'),
            'smile_raw': snap_15.get('raw', {}),
            'smile_smooth': snap_15.get('smooth', {}),
            'svi_params': snap_15.get('svi_params'),
            'strike_oi': snap_15.get('strike_oi', {}),
            'strike_vol': snap_15.get('strike_vol', {}),
        },
    }
    import tempfile
    try:
        fd, tmp_path = tempfile.mkstemp(dir=_SNAPSHOT_DIR, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, _PREV_BASELINE_FILE)
            print(f"[iv_smile] 💾 prev_baseline.json 已更新为今日15:00 ({today_str}): "
                  f"smooth={len(payload['state']['smile_smooth'])}档 "
                  f"oi={len(payload['state']['strike_oi'])}档 "
                  f"S={payload['state']['futures_price']}")
            return True
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as e:
        print(f"[iv_smile] ⚠️ 写 prev_baseline.json 失败: {e}")
        return False


def _save_close_state(close_point='15:00'):
    """
    收盘快照：将当前 _state + _last_valid 完整写入 close_state.json。
    **只在 15:00 收盘时**自动调用（10:15/11:30/23:00 不再写此文件，避免污染"前次基准=15:00"语义）。
    `close_point` 字段标记语义用途，_load_close_state 加载时会校验。
    """
    _ensure_snapshot_dir()
    # 只保存可序列化的字段
    _expiry_iso = _state.get('expiry').isoformat() if _state.get('expiry') else None
    payload = {
        'close_point': close_point,           # '15:00' = 真正的日内收盘基准；其他值视为污染
        'timestamp': datetime.now().isoformat(),
        'state': {
            'active_contract': _state.get('active_contract'),
            'expiry': _expiry_iso,
            'futures_price': _state.get('futures_price'),
            'atm_strike': _state.get('atm_strike'),
            'max_pain': _state.get('max_pain'),
            'ref_strike': _state.get('ref_strike'),
            'smile_raw': _state.get('smile_raw', {}),
            'smile_smooth': _state.get('smile_smooth', {}),
            'svi_params': _state.get('svi_params'),
            'last_update': _state.get('last_update'),
            'strike_oi': _state.get('strike_oi', {}),
            'strike_vol': _state.get('strike_vol', {}),
        },
        'last_valid': {
            'futures_price': _last_valid.get('futures_price'),
            'atm_strike': _last_valid.get('atm_strike'),
            'max_pain': _last_valid.get('max_pain'),
            'ref_strike': _last_valid.get('ref_strike'),
            'smile_raw': _last_valid.get('smile_raw', {}),
            'smile_smooth': _last_valid.get('smile_smooth', {}),
            'svi_params': _last_valid.get('svi_params'),
            'strike_oi': _last_valid.get('strike_oi', {}),
            'strike_vol': _last_valid.get('strike_vol', {}),
        },
    }
    import tempfile
    try:
        fd, tmp_path = tempfile.mkstemp(dir=_SNAPSHOT_DIR, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, _CLOSE_STATE_FILE)
            print(f"[iv_smile] 💾 收盘快照已保存: S={_state.get('futures_price')} "
                  f"MP={_state.get('max_pain')} 档={len(_state.get('smile_smooth', {}))} "
                  f"ts={payload['timestamp'][:19]}")
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as e:
        print(f"[iv_smile] ⚠️ 收盘快照保存失败: {e}")


def _copy_close_state_to_interval_snapshot(hh, mm, now):
    """
    收盘边界快照：把当前最后有效状态复制到对应15分钟槽（10:15/11:30/15:00/23:00）。

    关键点：这里只复制 _state 中已计算好的 IV/SVI/OI/成交量，不重新调用 compute_once，
    因此不会破坏“休盘不重算 IV/SVI”的保护；同时补齐 11:30/15:00/23:00 这类
    交易时段右边界因为 `_is_trading_hours()` 使用 `< end` 而不会自然生成的快照。
    """
    interval_key = f"{hh:02d}:{mm:02d}"
    if interval_key in _interval_snapshots:
        return False

    smooth = _state.get('smile_smooth') or _last_valid.get('smile_smooth') or {}
    raw = _state.get('smile_raw') or _last_valid.get('smile_raw') or {}
    if not smooth:
        print(f"[iv_smile] ⚠️ 收盘边界快照跳过: {interval_key} 无smile数据")
        return False

    strike_oi = _state.get('strike_oi') or _last_valid.get('strike_oi') or {}
    strike_vol = _state.get('strike_vol') or _last_valid.get('strike_vol') or {}
    close_price = _state.get('futures_price') or _last_valid.get('futures_price')
    if hh == 23 and mm == 0:
        # 夜盘收盘边界进入休盘分支后不再 compute_once，_state 里的 last 可能停在 22:59；
        # 优先用 TqSdk 快照里的最后收盘/成交价校准 23:00 快照价格。
        latest_price, price_source = _get_latest_tqsdk_futures_price()
        if latest_price and latest_price != close_price:
            print(f"[iv_smile] 📌 23:00边界价格校准: {close_price} → {latest_price} ({price_source})")
            close_price = latest_price
            _state['futures_price'] = latest_price
            _last_valid['futures_price'] = latest_price
    _interval_snapshots[interval_key] = {
        'smooth': {k: float(v) for k, v in smooth.items()},
        'raw': {k: (dict(v) if isinstance(v, dict) else v) for k, v in raw.items()},
        'timestamp': now.isoformat(),
        'svi_params': _state.get('svi_params') or _last_valid.get('svi_params'),
        'futures_price': close_price,
        'ref_strike': _state.get('ref_strike') or _last_valid.get('ref_strike'),
        'max_pain': _state.get('max_pain') or _last_valid.get('max_pain'),
        'atm_strike': _state.get('atm_strike') or _last_valid.get('atm_strike'),
        'strike_oi': {k: dict(v) for k, v in strike_oi.items()},
        'strike_vol': {k: dict(v) for k, v in strike_vol.items()},
        'close_boundary': True,
    }
    print(f"[iv_smile] 📌 收盘边界快照已补齐: {interval_key} ({len(smooth)}档)")
    return True


def _check_and_save_close_state():
    """
    检查当前是否为 PTA 收盘时间点，是则保存收盘快照。
    每个时间槽在本进程生命周期内只保存一次。

    同时把当前最后有效状态复制到对应15分钟槽，补齐 10:15/11:30/15:00/23:00
    收盘边界快照；不重新计算 IV/SVI。
    """
    now = datetime.now()
    for hh, mm in _PTA_CLOSE_TIMES:
        slot_key = f"{now.strftime('%Y%m%d')}_{hh:02d}{mm:02d}"
        if slot_key in _close_state_saved_slots:
            continue
        target_min = hh * 60 + mm
        now_min = now.hour * 60 + now.minute
        diff = now_min - target_min
        # 只在收盘点到达后2分钟内保存，避免 14:58 这类提前写入 15:00 快照。
        # 11:30/15:00/23:00 已进入休盘分支，由调度器在 else 中调用本函数；不重算 IV/SVI。
        if 0 <= diff <= 2:
            _close_state_saved_slots.add(slot_key)
            added_boundary_snapshot = _copy_close_state_to_interval_snapshot(hh, mm, now)
            # 关键分工：
            # - 15:00 收盘 → 写 close_state.json（语义=日内收盘基准，用于冷启动恢复 _close_baseline）
            # - 23:00 收盘 → 写 eod_state.json（语义=当日最终状态，用于冷启动恢复 _state 的 OI/Vol/S/MP）
            # 10:15/11:30 只写 _interval_snapshots，不污染基准文件
            # v2.11.54+: prev_baseline.json **不在 15:00 覆盖**（保持昨日 15:00 不变，供次日 14:59 启动用），
            # 而是在 21:00 _ensure_today_close_baseline_after_21() 切换时写入今日 15:00。
            if hh == 15 and mm == 0:
                _save_close_state(close_point='15:00')
            elif hh == 23 and mm == 0:
                _save_eod_state(eod_point='23:00')
            if added_boundary_snapshot:
                _save_all_snapshots()
            break


def _json_safe(obj):
    """递归转换快照 payload 中的 datetime / numpy / lock 等不可 JSON 序列化对象。"""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if hasattr(obj, 'item'):
        try:
            return obj.item()
        except Exception:
            pass
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items() if k not in ('lock', 'running')}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    # threading.Lock 等对象直接丢弃，避免 json.dump 写半截文件
    return str(obj)


def _guard_eod_payload_schema(payload):
    """8 字段联动契约守卫：避免"只改 F 不联动 ATM/smile/max_pain"的东补西凑。

    返回 (ok, blocking_problems, warnings)
      - blocking_problems: 写盘前会硬阻断，必须修才能写
      - warnings: 不阻断但会在日志里打 WARN，便于审计
    阻断规则:
      1. 8 个关键字段必须非空 (futures_price/atm_strike/max_pain/ref_strike
         strike_oi/strike_vol/smile_raw/smile_smooth)
      2. F↔ATM 联动一致性: F 与最近 strike 偏差 > 50 (TA608 strike_step=100) 视为不一致
    警告规则:
      3. smile 档数与 OI 档数差异 (SVI 平滑可能跳过深虚值/深实值端，是已知正常现象)
    """
    state = payload.get('state') or {}
    blocking = []
    warnings = []
    # 1. 关键字段必须非空（硬阻断）
    for k in ('futures_price', 'atm_strike', 'max_pain', 'ref_strike',
              'strike_oi', 'strike_vol', 'smile_raw', 'smile_smooth'):
        v = state.get(k)
        if not v:  # None / 0 / {} / '' 都视为缺失
            blocking.append(f'字段缺失:{k}')
    # 2. 联动一致性：F 跨过 ATM 边界时 atm_strike 必须随 F 重算（硬阻断）
    F = state.get('futures_price')
    atm = state.get('atm_strike')
    if F and atm:
        if abs(float(F) - float(atm)) > 50.5:
            blocking.append(f'F↔ATM不一致(F={F}, ATM={atm})')
    # 3. smile 档数与 OI 档数差异（软告警，SVI 平滑跳过端点是已知现象）
    n_oi = len(state.get('strike_oi') or {})
    n_sm = len(state.get('smile_smooth') or {})
    n_raw = len(state.get('smile_raw') or {})
    if n_oi and n_raw and abs(n_oi - n_raw) > 1:
        warnings.append(f'smile_raw/OI 档数差>1(oi={n_oi}, raw={n_raw})')
    if n_oi and n_sm and abs(n_oi - n_sm) > 1:
        warnings.append(f'smile_smooth/OI 档数差>1(oi={n_oi}, smooth={n_sm})')
    return (len(blocking) == 0, blocking, warnings)


def _save_eod_state(eod_point='23:00'):
    """把当前 _state / _last_valid 完整写到 eod_state.json。
    用于：冷启动恢复 _state 的 OI/Vol/S/MP/ATM（盘后/夜盘时段启动后立即有数据）。

    [v2.11.41+] 写盘前先过 _guard_eod_payload_schema() 8 字段联动守卫，缺字段或 F↔ATM
    不一致时拒绝写盘并打 ERROR（不静默丢弃），避免"只改 F 不联动"的脏 EOD 污染冷启动。
    """
    try:
        # timestamp 必须是 EOD 保存时刻，不能用 _state.last_update（可能仍是 15:00 IV 更新时间）
        eod_ts = datetime.now().isoformat()
        payload = {
            'eod_point': eod_point,
            'timestamp': eod_ts,
            'state': _json_safe(dict(_state)),
            'last_valid': _json_safe(dict(_last_valid)),
        }
        # 写盘前 schema 守卫
        ok, blocking, warnings = _guard_eod_payload_schema(payload)
        if not ok:
            print(f"[iv_smile] ❌ EOD 写盘被守卫拦截，硬阻断: {blocking} | "
                  f"eod_point={eod_point} ts={eod_ts[:19]} F={payload['state'].get('futures_price')} "
                  f"ATM={payload['state'].get('atm_strike')}")
            return  # 拒绝写盘
        if warnings:
            print(f"[iv_smile] ⚠️ EOD schema 软告警: {warnings} (不阻断，但建议修复)")
        print(f"[iv_smile] ✅ EOD schema 守卫通过: 8字段齐 F={payload['state'].get('futures_price')} "
              f"ATM={payload['state'].get('atm_strike')} MP={payload['state'].get('max_pain')}")
        # 23:00 收盘后的 current 语义就是 EOD 快照；即便 IV 计算线程最后一次 last_update
        # 停在 22:59/15:00，也不能让 state.last_update 把 EOD 恢复误判成旧 current。
        if eod_point == '23:00':
            payload.setdefault('state', {})['last_update'] = eod_ts
        if eod_point == '23:00':
            latest_price, price_source = _get_latest_tqsdk_futures_price()
            fallback_price = (payload.get('state') or {}).get('futures_price') or (payload.get('last_valid') or {}).get('futures_price')
            if latest_price:
                if latest_price != fallback_price:
                    print(f"[iv_smile] 📌 EOD价格校准: {fallback_price} → {latest_price} ({price_source})")
                # [v2.11.41+] F 改变时必须联动重算 ATM（如果 F 跨过 strike 边界，旧 ATM 与新 F 不一致）
                # strike 步长从 strike_oi keys 推断（TA608 = 100）；兼容 _state 没值时从 payload 推断
                _strike_keys = sorted((_state.get('strike_oi') or {}).keys(), key=lambda x: float(x))
                if len(_strike_keys) >= 2:
                    _strike_step = round(float(_strike_keys[1]) - float(_strike_keys[0]))
                else:
                    _strike_step = 100  # 兜底
                _new_atm = min(_strike_keys, key=lambda k: abs(float(k) - latest_price)) if _strike_keys else None
                if _new_atm is not None and str(_new_atm) != str(payload.get('state', {}).get('atm_strike')):
                    print(f"[iv_smile] 📌 EOD 联动重算 ATM: {payload.get('state', {}).get('atm_strike')} → {_new_atm} (F={latest_price}, step={_strike_step})")
                    payload.setdefault('state', {})['atm_strike'] = str(_new_atm)
                    payload.setdefault('last_valid', {})['atm_strike'] = str(_new_atm)
                    _state['atm_strike'] = str(_new_atm)
                    _last_valid['atm_strike'] = str(_new_atm)
                _set_payload_futures_price(payload, latest_price)
                _state['futures_price'] = latest_price
                _last_valid['futures_price'] = latest_price
                # 重新跑 schema 守卫（F+ATM 都更新后）
                ok2, blocking2, _ = _guard_eod_payload_schema(payload)
                if not ok2:
                    print(f"[iv_smile] ❌ EOD 价校准后 schema 仍不一致: {blocking2} | 拒绝写盘")
                    return
            else:
                print(f"[iv_smile] ⚠️ EOD价格校准无TqSdk快照，沿用缓存价 {fallback_price}")
        import tempfile
        fd, tmp_path = tempfile.mkstemp(dir=_SNAPSHOT_DIR, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, _EOD_STATE_FILE)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        print(f"[iv_smile] 💾 EOD 收盘快照已保存: eod_point={eod_point} "
              f"ts={payload['timestamp'][:19]} OI={len(payload['state'].get('strike_oi') or {})}档 "
              f"Vol={len(payload['state'].get('strike_vol') or {})}档 "
              f"S={payload['state'].get('futures_price')}")
    except Exception as e:
        print(f"[iv_smile] ⚠️ EOD 收盘快照保存失败: {e}")


def _load_eod_state():
    """启动时加载 EOD 收盘快照恢复 _state 和 _last_valid。
    语义：盘后/夜盘时段的"当前最新状态"，是 _state 的来源。
    与 _load_close_state() 互不冲突：后者只设 _close_baseline。

    返回 True 表示成功恢复，False 表示无可用数据。"""
    global _state, _last_valid, _eod_state_loaded
    if not os.path.exists(_EOD_STATE_FILE):
        return False
    try:
        with open(_EOD_STATE_FILE, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        saved_state = payload.get('state', {})
        saved_valid = payload.get('last_valid', {})
        eod_point = payload.get('eod_point', '')
        ts = payload.get('timestamp', '')

        # [v2.11.42+] 边界优先：若今日 10:15/11:30/15:00/23:00 close_boundary 快照
        # 存在且比 eod_state.json 新，则跳过 EOD 加载，让 15min 恢复路径接管。
        # 避免昨日 23:00 拉回覆盖今日 11:30 收盘后的 current。
        boundary_ts, boundary_key, boundary_date = _get_latest_close_boundary_timestamp()
        if boundary_ts and ts and boundary_ts > ts:
            print(f"[iv_smile] ⏭ EOD ts={ts[:19]} 已被 {boundary_date} {boundary_key} close_boundary "
                  f"覆盖 (boundary_ts={boundary_ts[:19]})，跳过 _state 恢复")
            return False

        # 只接受"今天"或盘后/非交易日最近一次 23:00 收盘的 eod 快照。
        # 23:00 EOD 是夜盘收盘后的 current 状态；周末/节假日也要保留它，不能回退到15:00基准。
        now_dt = datetime.now()
        today = now_dt.strftime('%Y-%m-%d')
        now_hm = now_dt.hour * 60 + now_dt.minute
        # 23:00 EOD 是夜盘收盘后的 current 状态：
        # - 次日09:00前接受昨天23:00；
        # - 周末/节假日/非交易日也必须继续接受上一交易日23:00，否则会被15:00 close_state覆盖回退。
        is_eod_current_window = (now_hm < 9 * 60) or (not _is_trading_day(now_dt))
        ts_date = ts[:10] if ts else ''
        if ts_date != today:
            if is_eod_current_window and eod_point == '23:00':
                from datetime import timedelta
                # 接受最近7天内的23:00 EOD，用于周末/节假日盘后恢复 current。
                ts_dt = datetime.strptime(ts_date, '%Y-%m-%d').date() if ts_date else None
                if (not ts_dt) or ((now_dt.date() - ts_dt).days < 0) or ((now_dt.date() - ts_dt).days > 7):
                    print(f"[iv_smile] ⏭️ eod_state.json ts={ts_date} 距今过远或无效，跳过")
                    return False
                print(f"[iv_smile] 📌 盘后/非交易日，接受最近23:00收盘的 eod_state.json（ts={ts_date}）")
            else:
                print(f"[iv_smile] ⏭️ eod_state.json ts={ts_date} 不是今天({today})，且非盘后/非交易日窗口，跳过")
                return False

        # 校验关键字段
        if not saved_state.get('strike_oi') or not saved_state.get('futures_price'):
            print(f"[iv_smile] ⚠️ eod_state.json 数据不完整，跳过")
            return False

        # 恢复 _state（盘后/夜盘的"当前最新"），但禁止比当前状态更旧的 payload 回退 current。
        incoming_ts = _payload_state_timestamp(payload)
        if not _should_restore_current(incoming_ts, 'eod_state'):
            return False
        for key in ('futures_price', 'atm_strike', 'max_pain', 'ref_strike',
                     'smile_raw', 'smile_smooth', 'svi_params', 'last_update',
                     'strike_oi', 'strike_vol', 'expiry'):
            val = saved_state.get(key)
            if val is not None:
                _state[key] = val

        # 恢复 _last_valid
        for key in ('futures_price', 'atm_strike', 'max_pain', 'ref_strike',
                     'smile_raw', 'smile_smooth', 'svi_params', 'strike_oi', 'strike_vol'):
            val = saved_valid.get(key)
            if val is not None:
                _last_valid[key] = val

        _eod_state_loaded = True
        print(f"[iv_smile] 💾 EOD 收盘快照已恢复（盘后当前值）: eod_point={eod_point} "
              f"ts={ts[:19]} S={_state.get('futures_price')} "
              f"MP={_state.get('max_pain')} OI={len(_state.get('strike_oi') or {})}档 "
              f"Vol={len(_state.get('strike_vol') or {})}档")
        return True
    except Exception as e:
        print(f"[iv_smile] ⚠️ EOD 收盘快照加载失败: {e}")
        return False


def _load_close_state():
    """
    启动时加载收盘快照恢复 _state 和 _last_valid。
    返回 True 表示成功恢复，False 表示无可用数据。

    如果 _eod_state_loaded=True（EOD 收盘快照已先恢复 _state），
    本函数**只**设 _close_baseline（前次基准），不再覆盖 _state。

    v2.11.54+ 加载优先级：
      1. prev_baseline.json（"前次基准"独立快照，**只在 21:00 切换时被覆盖**）
      2. close_state.json（"最新一天 15:00 收盘"快照，每天 15:00 收盘被覆盖）
    优先 prev_baseline.json 的原因：6/25 14:59 启动时，close_state.json 已经是 6/25 15:00 写的状态
    （14:59 启动时 close_state.json 里还是 6/24 15:00；但若进程一直跑跨日，close_state 会被覆盖成今日），
    拿 prev_baseline.json 才是真正的"前次基准"。
    """
    global _state, _last_valid, _close_baseline
    # v2.11.54+: 优先从 prev_baseline.json 加载（不会因 close_state.json 被覆盖而丢"前次基准"）
    if os.path.exists(_PREV_BASELINE_FILE):
        try:
            with open(_PREV_BASELINE_FILE, 'r', encoding='utf-8') as f:
                payload = json.load(f)
            saved_state = payload.get('state', {})
            saved_valid = payload.get('last_valid', {})
            ts = payload.get('timestamp', '')
            close_point = payload.get('close_point', '15:00')
            if close_point != '15:00':
                print(f"[iv_smile] ⚠️ prev_baseline.json 的 close_point={close_point!r}（非 15:00），视为污染数据，丢弃。")
            elif not saved_state.get('smile_smooth') or not saved_state.get('futures_price'):
                print(f"[iv_smile] ⚠️ prev_baseline.json 数据不完整，跳过")
            else:
                # 关键：直接恢复 _close_baseline，不依赖 close_state.json
                semantic_ts = ts
                try:
                    ts_date = ts[:10]
                    if close_point == '15:00':
                        semantic_ts = f'{ts_date}T15:00:00'
                except Exception:
                    pass
                _close_baseline = {
                    'smooth': saved_state.get('smile_smooth', {}),
                    'raw': saved_state.get('smile_raw', {}),
                    'strike_oi': saved_state.get('strike_oi', {}),
                    'strike_vol': saved_state.get('strike_vol', {}),
                    'S': saved_state.get('futures_price'),
                    'max_pain': saved_state.get('max_pain'),
                    'atm_strike': saved_state.get('atm_strike'),
                    'ts': semantic_ts,
                    'close_point': close_point,
                    'contract': saved_state.get('active_contract'),  # v2.11.54+ 修复: alert_data 端点靠 _close_baseline.get('contract') == cur_contract 判断 baseline_contract_match
                    'expiry': saved_state.get('expiry'),
                }
                print(f"[iv_smile] 📂 从 prev_baseline.json 恢复 _close_baseline: "
                      f"ts={semantic_ts[:19]} S={saved_state.get('futures_price')} "
                      f"smooth={len(_close_baseline['smooth'])}档 "
                      f"oi={len(_close_baseline.get('strike_oi') or {})}档 "
                      f"contract={saved_state.get('active_contract')}")
                return True
        except Exception as e:
            print(f"[iv_smile] ⚠️ 加载 prev_baseline.json 失败: {e}")

    if not os.path.exists(_CLOSE_STATE_FILE):
        return False
    try:
        with open(_CLOSE_STATE_FILE, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        saved_state = payload.get('state', {})
        saved_valid = payload.get('last_valid', {})
        ts = payload.get('timestamp', '')
        # 校验 close_point：旧文件（无此字段）默认视为 15:00 兼容；新文件非 15:00 → 视为污染丢弃
        close_point = payload.get('close_point', '15:00')
        if close_point != '15:00':
            print(f"[iv_smile] ⚠️ close_state.json 的 close_point={close_point!r}（非 15:00），视为污染数据，丢弃。")
            print(f"             启动后改走 _prev_day_baseline 路径恢复前次基准。")
            return False

        # 检查数据有效性
        if not saved_state.get('smile_smooth') or not saved_state.get('futures_price'):
            print(f"[iv_smile] ⚠️ 收盘快照数据不完整，跳过")
            return False

        # 恢复 _state（仅在 EOD 未加载且 close_state 不会造成 current 时间回退时）。
        # close_state 的 15:00 baseline 始终会在下方恢复到 _close_baseline；这里只管 current。
        # [v2.11.42+] 边界优先：若今日 10:15/11:30/15:00/23:00 close_boundary 快照
        # 比本 close_state 新，跳过 _state 恢复（让 15min 恢复路径接管）。
        boundary_ts, boundary_key, boundary_date = _get_latest_close_boundary_timestamp()
        boundary_is_newer = bool(boundary_ts and ts and boundary_ts > ts)
        should_set_state = (not _eod_state_loaded) and not boundary_is_newer
        if should_set_state:
            incoming_ts = _payload_state_timestamp(payload)
            if _should_restore_current(incoming_ts, 'close_state'):
                for key in ('futures_price', 'atm_strike', 'max_pain', 'ref_strike',
                             'smile_raw', 'smile_smooth', 'svi_params', 'last_update', 'strike_oi', 'strike_vol',
                             'active_contract'):  # v2.11.53+ 修复: 不恢复 active_contract 会让 alert_data 的 baseline_contract_match 永远 False, 退到 _prev_day_baseline (昨天数据)
                    val = saved_state.get(key)
                    if val is not None:
                        _state[key] = val

                # 恢复 _last_valid
                for key in ('futures_price', 'atm_strike', 'max_pain', 'ref_strike',
                             'smile_raw', 'smile_smooth', 'svi_params', 'strike_oi', 'strike_vol'):
                    val = saved_valid.get(key)
                    if val is not None:
                        _last_valid[key] = val
            else:
                print(f"[iv_smile] 🔄 close_state.json 只恢复 _close_baseline，不覆盖 current _state")
        else:
            print(f"[iv_smile] 🔄 EOD 已先恢复 _state，close_state.json 跳过 _state 覆盖（保留盘后最新值）")

        # === 关键：恢复 _close_baseline 内存变量 ===
        # 不然 alert_data 拿不到今日基准 (会回退到 _prev_day_baseline)
        # 优先使用 save 时写入的 active_contract（v2.11.36+ 已写入 close_state.json），
        # 否则兜底用 _state（tqsdk_loop 启动后才设），再否则从 svi_params.note 反推。
        recovered_contract = saved_state.get('active_contract') or _state.get('active_contract')
        recovered_expiry = saved_state.get('expiry') or (_state.get('expiry').isoformat() if _state.get('expiry') else None)
        if not recovered_contract:
            # 兜底：svi_params.note 里通常有 contract；或者从 expiry 字段反推
            note = (saved_state.get('svi_params') or {}).get('note', '')
            if 'TA' in note:
                import re as _re
                m = _re.search(r'TA\d{3}', note)
                if m: recovered_contract = m.group(0)
        # v2.11.50+ 校准 ts：用 close_point 对应的"语义收盘时刻"（15:00 = 15:00:00），而不是落盘时间
        # 例如盘后 17:21 手工补盘 → _close_baseline.ts 应显示 "06/18 15:00"，这样前端标签就是"15:00收盘"
        # 否则前端显示 "06/18 17:21"，看起来像"17:21 才切到今日基准"，与实际语义不符
        semantic_ts = ts  # 兜底用文件落盘时间
        try:
            ts_date = ts[:10]  # 'YYYY-MM-DD'
            if close_point == '15:00':
                semantic_ts = f'{ts_date}T15:00:00'
            elif close_point == '10:15':
                semantic_ts = f'{ts_date}T10:15:00'
            elif close_point == '11:30':
                semantic_ts = f'{ts_date}T11:30:00'
            elif close_point == '23:00':
                semantic_ts = f'{ts_date}T23:00:00'
        except Exception:
            pass
        _close_baseline = {
            'smooth': saved_state.get('smile_smooth', {}),
            'raw': saved_state.get('smile_raw', {}),
            'strike_oi': saved_state.get('strike_oi', {}),
            'strike_vol': saved_state.get('strike_vol', {}),
            'S': saved_state.get('futures_price'),
            'max_pain': saved_state.get('max_pain'),  # 关键：注入的 max_pain 是用户自定义基准，不能用 OI 实时算
            'atm_strike': saved_state.get('atm_strike'),
            'ts': semantic_ts,  # ← 改用语义时刻，前端 label 显示 "MM/DD HH:MM" 对应收盘点
            'close_point': close_point,  # 标记这是 15:00 收盘基准
            'contract': recovered_contract,
            'expiry': recovered_expiry,
        }
        print(f"[iv_smile] 💾 _close_baseline 已恢复 contract={_close_baseline.get('contract')} "
              f"close_point={close_point} ts={semantic_ts[:19]} oi={len(_close_baseline.get('strike_oi') or {})}档")

        # === 补齐 svi_params 中缺少的 skew/curvature ===
        cur_svi = _state.get('svi_params')
        if isinstance(cur_svi, dict) and cur_svi.get('a') is not None:
            if cur_svi.get('skew') is None or cur_svi.get('curvature') is None:
                # 优先从 last_valid 补充
                lv_svi = _last_valid.get('svi_params', {})
                if isinstance(lv_svi, dict) and lv_svi.get('skew') is not None:
                    cur_svi['skew'] = lv_svi['skew']
                    cur_svi['curvature'] = lv_svi.get('curvature')
                    print(f"[iv_smile] 🔧 从last_valid补齐skew={lv_svi['skew']:.4f}, "
                          f"curvature={lv_svi.get('curvature', 'N/A')}")
                else:
                    # 用 svi_jw_params 重算
                    try:
                        _T_for_jw = 30 / _TRADING_DAYS_PER_YEAR  # 默认值
                        if _state.get('expiry'):
                            _T_for_jw = _calc_T_trading_days(_state['expiry'])
                        jw = svi_jw_params(cur_svi['a'], cur_svi['b'], cur_svi['rho'],
                                          cur_svi['m'], cur_svi['sigma'], _T_for_jw)
                        cur_svi['skew'] = jw['skew']
                        cur_svi['curvature'] = jw['curvature']
                        print(f"[iv_smile] 🔧 补算skew={jw['skew']:.4f}, curvature={jw['curvature']:.2f}")
                    except Exception as e:
                        print(f"[iv_smile] ⚠️ 补算skew/curvature失败: {e}")

        smooth_count = len(saved_state.get('smile_smooth', {}))
        print(f"[iv_smile] 💾 收盘快照已恢复: S={saved_state.get('futures_price')} "
              f"MP={saved_state.get('max_pain')} 档={smooth_count} "
              f"ts={ts[:19]}")
        # [v2.11.42+] 仅在本次实际恢复了 _state 时返回 True。
        # 若 EOD 已加载或今日 close_boundary 快照更新，_state 不被覆盖，
        # 返回 False 以便下方 15min 恢复路径接管。
        return should_set_state
    except Exception as e:
        print(f"[iv_smile] ⚠️ 收盘快照加载失败: {e}")
        return False


def _save_all_snapshots():
    """
    每15分钟调用一次：将 _interval_snapshots 完整写入磁盘（覆盖）。
    文件为 iv_snapshots_YYYYMMDD.json，包含当天所有 HH:MM 时间点的完整快照。
    日期从快照的实际 timestamp 推导（避免跨日运行时数据归错文件）。
    非交易日不写入（防止脏数据）。
    """
    if not _interval_snapshots:
        return
    # 非交易日不写入快照
    if not _is_trading_day():
        return
    _ensure_snapshot_dir()
    # 文件名用当前进程时间（session date）而非快照内的 timestamp，
    # 避免进程跨日后把新session数据写入旧文件（如6/4启动时把夜盘数据写进6/3文件）。
    date_str = datetime.now().strftime('%Y%m%d')
    path = _get_snapshot_path(date_str)
    # 先读出磁盘上已存在的快照，再与内存快照合并（避免进程重启时昨夜数据覆盖今日数据）
    existing = {}
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                existing = json.load(f).get('snapshots', {})
        except Exception:
            pass
    # 合并：磁盘快照 + 内存快照（内存快照优先级更高，覆盖同 key）
    # 写盘前再按快照自身 timestamp 过滤一次，防止昨日 15:00 等脏快照混入今日文件。
    merged = {}
    skipped_mismatch = []
    for source_name, source in (('disk', existing), ('memory', _interval_snapshots)):
        for k, v in (source or {}).items():
            snap_ts = (v or {}).get('timestamp', '') if isinstance(v, dict) else ''
            snap_date = snap_ts[:10].replace('-', '') if snap_ts else ''
            if snap_date != date_str:
                skipped_mismatch.append((source_name, k, snap_ts))
                continue
            merged[k] = v
    if skipped_mismatch:
        preview = ', '.join([f"{src}:{key}@{ts[:19]}" for src, key, ts in skipped_mismatch[:5]])
        print(f"[iv_smile] ⚠️ 跳过跨日脏快照 {len(skipped_mismatch)}个: {preview}")
    # v2.11.52+ 防御：merged 为空时不要覆盖磁盘文件（避免跨日运行进程把 6/23 文件覆盖成空，
    # 参见 6/22 进程 6/23 凌晨 36 次空写入事件）
    if not merged:
        print(f"[iv_smile] ⏭ 跨日过滤后 merged 为空, 跳过 {date_str} 写入（保留磁盘已有 {len(existing)} 个键）")
        return
    payload = {
        'date': date_str,
        'snapshots': merged,   # 合并后全量快照 dict（仅保留 timestamp 属于 date_str 的快照）

    }
    # 原子写入：先写临时文件，再 os.replace() 覆盖目标文件。
    # os.replace 在同一文件系统上是原子操作，即使进程被 kill -9 也不会
    # 出现半截文件（要么是旧的完整文件，要么是新的完整文件）。
    import tempfile
    try:
        fd, tmp_path = tempfile.mkstemp(dir=_SNAPSHOT_DIR, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
            print(f"[iv_smile] 📦 全量快照已持久化: {date_str} ({len(_interval_snapshots)}个时间点)")
        except BaseException:
            # 写入失败时清理临时文件
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as e:
        print(f"[iv_smile] ⚠️ 快照持久化失败: {e}")


# 中国法定节假日表（期货休市日），含调休后的实际休市区间
# 格式：(月, 日) 元组集合，按年份区分
_CN_HOLIDAYS = {
    2025: {
        (1,1),                                              # 元旦
        (1,28),(1,29),(1,30),(1,31),(2,1),(2,2),(2,3),(2,4), # 春节 1/28-2/4
        (4,4),(4,5),(4,6),                                  # 清明
        (5,1),(5,2),(5,3),(5,4),(5,5),                      # 劳动节
        (5,31),(6,1),(6,2),                                 # 端午
        (10,1),(10,2),(10,3),(10,4),(10,5),(10,6),(10,7),(10,8), # 国庆+中秋
    },
    2026: {
        (1,1),(1,2),                                        # 元旦
        (2,16),(2,17),(2,18),(2,19),(2,20),(2,21),(2,22),(2,23), # 春节 2/16-2/23（除夕2/16）
        (4,4),(4,5),(4,6),                                  # 清明
        (5,1),(5,2),(5,3),                                  # 劳动节
        (6,19),(6,20),(6,21),                               # 端午
        (9,25),(9,26),(9,27),                               # 中秋
        (10,1),(10,2),(10,3),(10,4),(10,5),(10,6),(10,7),(10,8), # 国庆
    },
    2027: {
        (1,1),                                              # 元旦
        (2,5),(2,6),(2,7),(2,8),(2,9),(2,10),(2,11),(2,12),  # 春节
        (4,4),(4,5),(4,6),                                  # 清明
        (5,1),(5,2),(5,3),                                  # 劳动节
        (6,8),(6,9),(6,10),                                 # 端午
        (9,15),(9,16),(9,17),                               # 中秋
        (10,1),(10,2),(10,3),(10,4),(10,5),(10,6),(10,7),    # 国庆
    },
}

def _is_cn_holiday(dt):
    """判断日期是否是法定节假日（期货休市日）"""
    year_holidays = _CN_HOLIDAYS.get(dt.year)
    if not year_holidays:
        return False  # 无数据年份保守返回False
    return (dt.month, dt.day) in year_holidays

def _is_trading_day(dt=None):
    """
    判断指定日期/时间是否是交易日（排除周末 + 法定节假日）。
    注意夜盘跨日：周五21:00开盘的夜盘延续到周六02:30，这仍属于周五交易日。
    节假日前一天没有夜盘（如周三是节假日，则周二没有夜盘）。
    判断逻辑：
    - 周一~周五且非节假日 → 交易日
    - 周六00:00-02:30 → 检查周五是否有夜盘（周五非节假日 且 周六非节假日的首日时才有）
    - 法定节假日 → 非交易日
    - 节假日前一天的夜盘也不交易（通过检查"次日是否休市"实现）

    入参 dt 可以是 datetime 或 date 或 None（默认 datetime.now()）。
    """
    if dt is None:
        dt = datetime.now()
    elif isinstance(dt, datetime):
        pass  # 已是 datetime
    elif hasattr(dt, 'weekday'):
        # date 类型：转成 datetime（用午夜时间）
        dt = datetime.combine(dt, datetime.min.time())
    else:
        return False

    wd = dt.weekday()  # 0=周一 ... 6=周日
    h, m = dt.hour, dt.minute
    total_min = h * 60 + m

    if wd == 6:  # 周日：永远不交易
        return False

    if wd == 5:  # 周六
        if total_min <= 150:  # 00:00-02:30 可能是周五夜盘延续
            # 检查周五是否是交易日（非节假日）
            friday = dt.date() - timedelta(days=1)
            return not _is_cn_holiday(friday)
        return False  # 周六02:30之后不交易

    # 周一~周五
    if _is_cn_holiday(dt):
        return False

    return True


# PTA有效交易时段（分钟）：09:00-10:15, 10:30-11:30, 13:30-15:00, 21:00-23:00
_PTA_TRADING_MINUTE_RANGES = (
    (9 * 60, 10 * 60 + 15),
    (10 * 60 + 30, 11 * 60 + 30),
    (13 * 60 + 30, 15 * 60),
    (21 * 60, 23 * 60),
)
_PTA_OPEN_TIMES = {(9, 0), (10, 30), (13, 30), (21, 0)}
_PTA_TRADING_MINUTES_PER_DAY = sum(end - start for start, end in _PTA_TRADING_MINUTE_RANGES)  # 345分钟


def _is_opening_first_minute(now=None):
    """开盘首分钟不写15分钟快照：等待TqSdk首个完整行情刷新后再落槽。"""
    if now is None:
        now = datetime.now()
    return (now.hour, now.minute) in _PTA_OPEN_TIMES


def _has_pta_night_session(day):
    """判断指定自然日晚上21:00-23:00是否有PTA夜盘。PTA夜盘不跨零点。"""
    if isinstance(day, datetime):
        day = day.date()
    if day.weekday() >= 5 or _is_cn_holiday(day):
        return False
    if day.weekday() == 4:  # 周五夜盘正常交易（PTA 23:00结束，不跨周六）
        return True
    tomorrow = day + timedelta(days=1)
    return tomorrow.weekday() < 5 and not _is_cn_holiday(tomorrow)


def _find_last_trading_day_before(day, max_lookback=8):
    """往前找最近的交易日（不含 day 本身）。返回 date 或 None。"""
    if isinstance(day, datetime):
        day = day.date()
    for delta in range(1, max_lookback + 1):
        d = day - timedelta(days=delta)
        if _is_trading_day(d):
            return d
    return None


def _is_post_holiday_first_trading_day(day):
    """判断 day 是否是节假日的第一个交易日（节后首日）。"""
    if isinstance(day, datetime):
        day = day.date()
    if not _is_trading_day(day):
        return False
    prev_td = _find_last_trading_day_before(day)
    if not prev_td:
        return False
    # 节后首日：上一交易日距今天超过 1 天（即中间隔了周末或节假日）
    return (day - prev_td).days > 1


def _cb_should_apply(cb_date, now_dt):
    """统一判断：_close_baseline（其 cb_date）当前是否应该作为前次基准。

    切换原则（v2.11.38+）：
    - 今日 15:00 已过 → 今日 cb（即 today）生效
    - 节后首个交易日 9:00 早盘开盘后 → 切到节前最后交易日
    - 有夜盘的交易日 21:00 夜盘开盘后 → 切到今日 cb（即 today）
    - 其他时段 → 用上一交易日（即 _find_last_trading_day_before(today)）

    cb_date 与上述"应生效的基准日期"匹配 → True，否则 False。
    """
    if isinstance(cb_date, datetime):
        cb_date = cb_date.date()
    if isinstance(now_dt, datetime):
        now = now_dt
    else:
        now = datetime.combine(now_dt, datetime.min.time())

    if cb_date > now.date():
        return False

    expected = _get_expected_baseline_date(now)
    return cb_date == expected


def _get_expected_baseline_date(now_dt):
    """根据当前时刻，返回"应当生效的前次基准"的 date。

    切换原则（v2.11.50+ 用户明确规则）：
    - 有夜盘的交易日 21:00 夜盘开盘后 → 切到今日 15:00（即 today）
    - 节后首个交易日 9:00 早盘开盘后 → 切到节前最后交易日（即 _find_last_trading_day_before(today)）
    - 其他时段 → 用"上一交易日 15:00"：
      * 今日是交易日（且不是节后首日）：今日 cb 在 21:00 才生效 → 用今日 cb 之前的"上一交易日"
      * 节假日/周末：节前最后交易日的 cb 还没生效（要等节后首日 9:00）→ 用"节前最后交易日 的上一交易日"

    即"前次基准" = 离当前最近的、已经生效的"前一次切换事件"指向的日期。
    """
    if isinstance(now_dt, datetime):
        now = now_dt
    else:
        now = datetime.combine(now_dt, datetime.min.time())

    today = now.date()

    # 1) 有夜盘的交易日 21:00 夜盘开盘后 → 切到今日 15:00（优先级最高，覆盖节后首日的 9:00 分支）
    if _is_trading_day(today) and _has_pta_night_session(today) and now.hour >= 21:
        return today

    # 2) 节后首个交易日 9:00 早盘开盘后 → 切到节前最后交易日（即上一交易日）
    if _is_trading_day(today) and _is_post_holiday_first_trading_day(today) and now.hour >= 9:
        prev_td = _find_last_trading_day_before(today)
        if prev_td:
            return prev_td

    # 3) 默认
    if _is_trading_day(today):
        # 今日是交易日（且不是节后首日），今日 cb 在 21:00 才生效 → 用上一交易日
        return _find_last_trading_day_before(today)
    else:
        # 节假日/周末：节前最后交易日的 cb 还没生效（要等节后首日 9:00）→ 再往前一个交易日
        last_td = _find_last_trading_day_before(today)
        if last_td:
            return _find_last_trading_day_before(last_td)
        return None


def _is_trading_hours():
    """
    判断当前是否在PTA交易时段（允许SVI校准）。
    PTA(CZCE)有效交易时段：
      上午: 09:00-10:15, 10:30-11:30（10:15-10:30短休）
      下午: 13:30-15:00
      夜盘: 21:00-23:00（当日结束，不跨零点）
    其余时段跳过校准，避免休盘期间虚假波动。
    """
    now = datetime.now()
    if not _is_trading_day(now):
        return False
    total = now.hour * 60 + now.minute

    # 日盘：短休10:15-10:30不算交易时段
    for start, end in _PTA_TRADING_MINUTE_RANGES[:3]:
        if start <= total < end:
            return True

    # 夜盘：还要检查节假日前夜盘规则
    night_start, night_end = _PTA_TRADING_MINUTE_RANGES[3]
    if night_start <= total < night_end:
        return _has_pta_night_session(now.date())
    return False


# ===================== 交易日T计算 =====================

_TRADING_DAYS_PER_YEAR = 245  # 中国期货每年约245个交易日

def _count_trading_days(start_date, end_date):
    """
    计算从 start_date 到 end_date（不含）之间的交易日数。
    排除周末和法定节假日。
    """
    from datetime import date
    if isinstance(start_date, datetime):
        start_date = start_date.date()
    if isinstance(end_date, datetime):
        end_date = end_date.date()
    count = 0
    d = start_date
    while d < end_date:
        wd = d.weekday()
        if wd < 5 and not _is_cn_holiday(d):
            count += 1
        d += timedelta(days=1)
    return count


def _remaining_trading_minutes_in_day(day, from_minute=0, until_minute=24 * 60):
    """计算某自然日从 from_minute 到 until_minute 之间剩余PTA有效交易分钟数。"""
    if isinstance(day, datetime):
        day = day.date()
    if day.weekday() >= 5 or _is_cn_holiday(day):
        return 0
    total = 0
    for start, end in _PTA_TRADING_MINUTE_RANGES:
        if start == 21 * 60 and not _has_pta_night_session(day):
            continue
        s = max(start, from_minute)
        e = min(end, until_minute)
        if e > s:
            total += e - s
    return total


def _count_remaining_trading_minutes(now, expiry):
    """
    计算从 now 到 expiry 之间的剩余PTA有效交易分钟。
    - date 型 expiry 按到期日 15:00 处理
    - 交易时段内按分钟递减
    - 10:15-10:30、午休、收盘后、周末/节假日期间自然冻结
    """
    if now is None:
        now = datetime.now()
    if isinstance(expiry, datetime):
        expiry_dt = expiry
        if expiry_dt.hour == 0 and expiry_dt.minute == 0 and expiry_dt.second == 0 and expiry_dt.microsecond == 0:
            expiry_dt = expiry_dt.replace(hour=15, minute=0)
    else:
        expiry_dt = datetime.combine(expiry, datetime.min.time()).replace(hour=15, minute=0)
    if now >= expiry_dt:
        return 0

    cur_date = now.date()
    expiry_date = expiry_dt.date()
    cur_min = now.hour * 60 + now.minute
    expiry_min = expiry_dt.hour * 60 + expiry_dt.minute

    total = 0
    d = cur_date
    while d <= expiry_date:
        if d == cur_date and d == expiry_date:
            total += _remaining_trading_minutes_in_day(d, cur_min, expiry_min)
        elif d == cur_date:
            total += _remaining_trading_minutes_in_day(d, cur_min, 24 * 60)
        elif d == expiry_date:
            total += _remaining_trading_minutes_in_day(d, 0, expiry_min)
        else:
            total += _remaining_trading_minutes_in_day(d, 0, 24 * 60)
        d += timedelta(days=1)
    return total


def _calc_T_trading_days(expiry, now=None):
    """
    用剩余有效交易分钟计算到期时间T（年化）。

    T = 剩余PTA有效交易分钟 / (245 * 345)
    PTA有效交易时段：09:00-10:15, 10:30-11:30, 13:30-15:00, 21:00-23:00。
    交易时段内T随分钟递减；短休/午休/收盘后/周末节假日T冻结。
    """
    if now is None:
        now = datetime.now()
    if expiry is None:
        return 30 / _TRADING_DAYS_PER_YEAR  # 默认30个交易日

    remaining_minutes = _count_remaining_trading_minutes(now, expiry)
    effective_minutes = max(remaining_minutes, 1)  # 最小1分钟，避免T=0导致IV爆炸
    return effective_minutes / (_TRADING_DAYS_PER_YEAR * _PTA_TRADING_MINUTES_PER_DAY)



def _load_previous_day_snapshots():
    """
    启动时加载快照：
    0. 优先从收盘快照 close_state.json 恢复（最快路径）
    1. 今日快照 → _interval_snapshots（服务中途重启恢复当天数据）
    2. 前一交易日的15:00快照 → _prev_day_baseline（收盘基准对比）
    3. 从最新快照恢复标的价格和微笑曲线到 _state
    
    关键：_interval_snapshots 只存当天数据，避免多天数据合并后写入磁盘造成污染。
    """
    global _interval_snapshots, _last_valid, _state, _prev_day_baseline

    _interval_snapshots = {}
    _prev_day_baseline = {}

    # === 清理残留的 .tmp 文件（kill -9 后原子写入的临时文件无法自动清理） ===
    try:
        import glob
        tmp_files = glob.glob(os.path.join(_SNAPSHOT_DIR, '*.tmp'))
        if tmp_files:
            for tf in tmp_files:
                try:
                    os.unlink(tf)
                except OSError:
                    pass
            print(f"[iv_smile] 🧹 清理残留临时文件: {len(tmp_files)}个")
    except Exception:
        pass

    # === 0a. 优先从 EOD 收盘快照恢复 _state（盘后/夜盘启动时立即有 OI/Vol/S/MP） ===
    eod_restored = _load_eod_state()

    # === 0b. 从日内收盘快照恢复 _state 和 _close_baseline（如果 EOD 未加载） ===
    close_restored = _load_close_state()

    today = datetime.now().strftime('%Y%m%d')

    # === 1. 加载今日快照（服务中途重启时恢复） ===
    today_path = _get_snapshot_path(today)
    latest_for_restore = None
    latest_for_restore_key = None
    latest_for_restore_ts = None

    if os.path.exists(today_path):
        try:
            with open(today_path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
            snaps = payload.get('snapshots', {})
            # 只加载 timestamp 属于今天的快照（过滤掉从旧天污染进来的数据）
            for k, v in snaps.items():
                snap_ts = v.get('timestamp', '')
                if snap_ts and snap_ts[:10].replace('-', '') == today:
                    _interval_snapshots[k] = v
                # 即使不放进 _interval_snapshots，也检查是否可用于恢复 _state
                if v.get('smooth'):
                    ts = v.get('timestamp', '')
                    if latest_for_restore_ts is None or ts > latest_for_restore_ts:
                        latest_for_restore = v
                        latest_for_restore_key = k
                        latest_for_restore_ts = ts
            _interval_loaded_from_disk.add(today)
            print(f"[iv_smile] 📂 已加载今日快照 ({today}): {len(_interval_snapshots)}个时间点")

        except Exception as e:
            print(f"[iv_smile] ⚠️ 加载今日快照失败: {e}")

    # === 2. 找最近一个交易日的15:00基准 ===
    # 交易日周期：21:00夜盘开盘 → 次日15:00收盘
    # - 21:00之前（盘后复盘时段）：基准 = 前一交易日15:00（方便复盘对比当天日盘变化）
    # - 21:00之后（新交易日开盘）：基准 = 当天15:00（切换到新周期）
    # 这样15:00-21:00之间仍可对比"今天vs昨天"的变化
    # 非交易日（周末/节假日）：始终找上一个交易日的15:00基准
    now = datetime.now()
    if _is_trading_day(now) and now.hour >= 21:
        start_days_ago = 0  # 交易日21:00后，可以用当天15:00
    else:
        start_days_ago = 1  # 其他情况（含非交易日），从昨天开始找
    # v2.11.50+ 节假日兜底：当前为非交易日且今天就是节假日时，
    # 预期基准日 = "上一交易日 的再上一交易日"（因为节前最后交易日的 cb 要等节后首日 9:00 才生效）。
    # 此时 start_days_ago=1 会先找到昨天（节前最后交易日）就 break，错误地把
    # 节前最后交易日的 15:00 当成 prev baseline；正确做法是直接用 _get_expected_baseline_date。
    expected_date = _get_expected_baseline_date(now)  # may be None
    expected_date_str = expected_date.strftime('%Y%m%d') if expected_date else None

    # v2.11.50+ 优先尝试 expected_date（节假日时跳过节前最后交易日，直接找上一交易日）
    if expected_date_str:
        try:
            exp_path = _get_snapshot_path(expected_date_str)
            if os.path.exists(exp_path):
                with open(exp_path, 'r', encoding='utf-8') as f:
                    exp_payload = json.load(f)
                exp_snaps = exp_payload.get('snapshots', {})
                exp_snap_15 = exp_snaps.get('15:00')
                if exp_snap_15 and exp_snap_15.get('smooth'):
                    exp_snap_ts = exp_snap_15.get('timestamp', '')
                    exp_snap_date = exp_snap_ts[:10].replace('-', '') if exp_snap_ts else ''
                    # v2.11.52+ 防御性过滤：timestamp 时间部分必须落在 14:00-15:59 窗口（盘中 9:24 误打会落在这里之外）
                    try:
                        _ts_dt = datetime.fromisoformat(exp_snap_ts)
                        _ts_in_window = (14 <= _ts_dt.hour <= 15)
                    except Exception:
                        _ts_in_window = False
                    if exp_snap_date == expected_date_str and _ts_in_window:
                        _prev_day_baseline = exp_snap_15
                        if not latest_for_restore:
                            latest_for_restore = exp_snap_15
                            latest_for_restore_key = f"15:00@{expected_date_str}"
                            latest_for_restore_ts = exp_snap_ts
                        print(f"[iv_smile] 📂 已加载预期基准日15:00基准 ({expected_date_str}): "
                              f"smooth={len(exp_snap_15.get('smooth',{}))}档 "
                              f"oi={len(exp_snap_15.get('strike_oi',{}))}档 "
                              f"ts={exp_snap_ts[:19]}")
                        # 找到后直接走"恢复 _state"逻辑，跳过下面的 days_ago 循环
                        # 把 days_ago 设为 99 跳出循环，然后继续 _state 恢复
                        # 更安全：用一个 flag 标记已找到
                        _found_expected = True
                    else:
                        reason = f"timestamp={exp_snap_ts[:19]} 不在 14:00-15:59 窗口" if not _ts_in_window else f"日期不匹配 {exp_snap_date}!={expected_date_str}"
                        print(f"[iv_smile] ⚠️ 预期基准日 {expected_date_str} 的15:00快照被过滤 ({reason})，跳过")
                        _found_expected = False
                else:
                    _found_expected = False
            else:
                _found_expected = False
        except Exception as e:
            print(f"[iv_smile] ⚠️ 加载预期基准日 {expected_date_str} 失败: {e}")
            _found_expected = False
    else:
        _found_expected = False

    if not _found_expected:
        for days_ago in range(start_days_ago, 8):
            if days_ago == 0:
                check_date = today
                check_path = today_path
            else:
                check_date = (now - timedelta(days=days_ago)).strftime('%Y%m%d')
                check_path = _get_snapshot_path(check_date)
            if not os.path.exists(check_path):
                continue
            # 跳过非交易日的快照（周末/节假日写入的脏数据）
            try:
                check_dt = datetime.strptime(check_date, '%Y%m%d')
                if check_dt.weekday() >= 5 or _is_cn_holiday(check_dt):
                    reason = f"weekday={check_dt.weekday()}" if check_dt.weekday() >= 5 else "法定节假日"
                    print(f"[iv_smile] ⏭ 跳过非交易日快照: {check_date} ({reason})")
                    continue
            except ValueError:
                pass
            try:
                with open(check_path, 'r', encoding='utf-8') as f:
                    payload = json.load(f)
                snaps = payload.get('snapshots', {})
                snap_15 = snaps.get('15:00')
                if snap_15 and snap_15.get('smooth'):
                    # 验证 timestamp 确实属于该日期（防止污染数据）
                    snap_ts = snap_15.get('timestamp', '')
                    snap_date = snap_ts[:10].replace('-', '') if snap_ts else ''
                    # v2.11.52+ 防御性过滤：timestamp 时间部分必须落在 14:00-15:59 窗口
                    try:
                        _ts_dt = datetime.fromisoformat(snap_ts)
                        _ts_in_window = (14 <= _ts_dt.hour <= 15)
                    except Exception:
                        _ts_in_window = False
                    if snap_date == check_date and _ts_in_window:
                        _prev_day_baseline = snap_15
                        # 同时用于恢复 _state（盘后冷启动时确保页面有数据）
                        if not latest_for_restore:
                            latest_for_restore = snap_15
                            latest_for_restore_key = f"15:00@{check_date}"
                            latest_for_restore_ts = snap_ts
                        label = "今日" if days_ago == 0 else "前一交易日"
                        print(f"[iv_smile] 📂 已加载{label}15:00基准 ({check_date}): "
                              f"smooth={len(snap_15.get('smooth',{}))}档 "
                              f"oi={len(snap_15.get('strike_oi',{}))}档 "
                              f"ts={snap_ts[:19]}")
                        break
                    else:
                        reason = f"timestamp={snap_ts[:19]} 不在 14:00-15:59 窗口" if not _ts_in_window else f"日期不匹配 {snap_date}!={check_date}"
                        print(f"[iv_smile] ⏭ 跳过{check_date} 15:00 键 ({reason})")
                # 如果该天没有15:00但有其他数据，也用于恢复 _state
                if not latest_for_restore and days_ago > 0:
                    valid_keys = [k for k in snaps if snaps[k].get('smooth')]
                    if valid_keys:
                        lk = max(valid_keys, key=lambda k: snaps[k].get('timestamp', ''))
                        latest_for_restore = snaps[lk]
                        latest_for_restore_key = lk
                        latest_for_restore_ts = snaps[lk].get('timestamp', '')
            except Exception as e:
                print(f"[iv_smile] ⚠️ 加载历史快照 {check_date} 失败: {e}")
                continue

    # === 3. 从最新快照恢复标的价格和微笑曲线 ===
    # 如果收盘快照已恢复 _state，跳过从15分钟快照恢复（避免被更旧数据覆盖）。
    # 即使未恢复，也必须经过 timestamp guard，禁止 15:00/旧快照覆盖 23:00 current。
    # 但仍需恢复 expiry/T 和 akshare 校正（不论哪种恢复路径都需要）
    can_restore_latest = bool(latest_for_restore and _should_restore_current(latest_for_restore_ts, f'interval_snapshot:{latest_for_restore_key}'))
    # [v2.11.42+] 15min 恢复必须先验证：仅当 15min 是 close_boundary 才允许覆盖 EOD。
    # 否则 09:00/09:15/09:30 等盘中 slot 会拉回覆盖昨日 23:00 EOD，
    # 违反"4 个休盘点后冻结"的语义。
    is_close_boundary = bool(latest_for_restore and latest_for_restore.get('close_boundary'))
    should_restore_latest = can_restore_latest and (is_close_boundary or not eod_restored)
    if not close_restored and should_restore_latest:
        restored_price = latest_for_restore.get('futures_price')
        restored_atm = latest_for_restore.get('atm_strike')
        restored_mp = latest_for_restore.get('max_pain')
        restored_ref = latest_for_restore.get('ref_strike')
        restored_smooth = latest_for_restore.get('smooth', {})
        restored_raw = latest_for_restore.get('raw', {})
        restored_sabr = latest_for_restore.get('svi_params') or latest_for_restore.get('sabr_params')  # 兼容旧快照

        if restored_price and restored_price > 0:
            _last_valid['futures_price'] = restored_price
            _state['futures_price'] = restored_price
        if restored_atm:
            _last_valid['atm_strike'] = restored_atm
            _state['atm_strike'] = restored_atm
        if restored_mp:
            _last_valid['max_pain'] = restored_mp
            _state['max_pain'] = restored_mp
        if restored_ref:
            _last_valid['ref_strike'] = restored_ref
            _state['ref_strike'] = restored_ref
        if restored_smooth:
            _last_valid['smile_smooth'] = restored_smooth
            _state['smile_smooth'] = restored_smooth
        if restored_raw:
            _last_valid['smile_raw'] = restored_raw
            _state['smile_raw'] = restored_raw
        if restored_sabr and isinstance(restored_sabr, dict) and (restored_sabr.get('a') is not None or restored_sabr.get('alpha') is not None):
            # SVI参数有效性检查
            if restored_sabr.get('a') is not None:
                # 新SVI格式 — 如果缺少 skew/curvature 则补算
                if restored_sabr.get('skew') is None or restored_sabr.get('curvature') is None:
                    _T = _state.get('T') or 30/365
                    try:
                        jw = svi_jw_params(restored_sabr['a'], restored_sabr['b'],
                                           restored_sabr['rho'], restored_sabr['m'],
                                           restored_sabr['sigma'], _T)
                        restored_sabr['skew'] = jw['skew']
                        restored_sabr['curvature'] = jw['curvature']
                        restored_sabr['atm_vol'] = jw['atm_vol']
                        print(f"[iv_smile] 🔧 补算SVI派生参数: skew={jw['skew']:.4f}, curvature={jw['curvature']:.2f}")
                    except Exception as e:
                        print(f"[iv_smile] ⚠️ 补算SVI派生参数失败: {e}")
                _last_valid['svi_params'] = restored_sabr
                _state['svi_params'] = restored_sabr
            else:
                # 旧SABR格式，标记为无效，触发SVI重新拟合
                print(f"[iv_smile] ⚠️ 快照中为旧SABR格式，将用SVI重新拟合")
                restored_sabr = None
        restored_oi = latest_for_restore.get('strike_oi', {})
        if restored_oi:
            _last_valid['strike_oi'] = restored_oi
            _state['strike_oi'] = restored_oi
        restored_vol = latest_for_restore.get('strike_vol', {})
        if restored_vol:
            _last_valid['strike_vol'] = restored_vol
            _state['strike_vol'] = restored_vol

        print(f"[iv_smile] 📂 已恢复标的价格: S={restored_price}, ATM={restored_atm}, MP={restored_mp} (from {latest_for_restore_key})")

        if restored_smooth:
            print(f"[iv_smile] 📂 已恢复微笑曲线: {len(restored_smooth)}档平滑IV (from {latest_for_restore_key})")


        # === 3.1 如果 svi_params 无效，用 raw 数据重新做 SVI 拟合 ===
        _svi_valid = (restored_sabr and isinstance(restored_sabr, dict)
                      and restored_sabr.get('a') is not None)
        if not _svi_valid and restored_raw and restored_price and restored_price > 0:
            print(f"[iv_smile] 🔧 svi_params 无效，用 raw 数据重新拟合SVI...")
            # 构建 K_list, IV_list — 用 OTM 端 IV（call for K>ATM, put for K<ATM）
            _atm = restored_atm or restored_mp or round(restored_price / 100) * 100
            K_list, IV_list = [], []
            for k_str, iv_dict in restored_raw.items():
                k = int(k_str) if k_str.isdigit() else float(k_str)
                # 优先用 OTM 端：K>ATM 用 call IV，K<ATM 用 put IV
                if k > _atm:
                    iv_val = iv_dict.get('C') or iv_dict.get('raw_C')
                elif k < _atm:
                    iv_val = iv_dict.get('P') or iv_dict.get('raw_P')
                else:
                    # ATM：取平均
                    c_iv = iv_dict.get('C') or iv_dict.get('raw_C')
                    p_iv = iv_dict.get('P') or iv_dict.get('raw_P')
                    if c_iv and p_iv:
                        iv_val = (c_iv + p_iv) / 2
                    else:
                        iv_val = c_iv or p_iv
                if iv_val and iv_val > 0:
                    K_list.append(k)
                    IV_list.append(iv_val)

            if len(K_list) >= 4:
                # 计算 T（到期时间）— 始终用 datetime.now()（时间持续流动）
                _expiry = _state.get('expiry')
                if _expiry:
                    T = _calc_T_trading_days(_expiry)
                else:
                    T = 30 / _TRADING_DAYS_PER_YEAR  # 默认30个交易日

                refit_smooth, refit_svi = smooth_smile(K_list, IV_list, restored_price, T)
                if refit_svi:
                    _state['svi_params'] = refit_svi
                    _last_valid['svi_params'] = refit_svi
                    print(f"[iv_smile] ✅ SVI重新拟合成功: a={refit_svi['a']:.4f}, b={refit_svi['b']:.4f}, "
                          f"rho={refit_svi['rho']:.4f}, m={refit_svi['m']:.4f}, sigma={refit_svi['sigma']:.4f}")
                    # 用 SVI 拟合结果重建 smooth 曲线（覆盖原始 smooth=raw 的数据）
                    if refit_smooth:
                        # 将拟合 smooth 的 key 转为字符串格式（与快照一致）
                        smooth_str = {str(int(k)) if isinstance(k, (int, float)) and k == int(k) else str(k): v
                                      for k, v in refit_smooth.items()}
                        _state['smile_smooth'] = smooth_str
                        _last_valid['smile_smooth'] = smooth_str
                        print(f"[iv_smile] ✅ 已用SVI重建smooth曲线: {len(smooth_str)}档")
                else:
                    print(f"[iv_smile] ⚠️ SVI重新拟合失败（{len(K_list)}个数据点）")
            else:
                print(f"[iv_smile] ⚠️ raw数据点不足({len(K_list)})，无法重新拟合SVI")

    # === 3.5 close_state 恢复成功但 svi_params 为空时，用已有 smile_raw 重新拟合 SVI ===
    _svi_ok = (_state.get('svi_params') and isinstance(_state['svi_params'], dict)
               and _state['svi_params'].get('a') is not None)
    if not _svi_ok and _state.get('smile_raw') and _state.get('futures_price'):
        print(f"[iv_smile] 🔧 svi_params 缺失，用 smile_raw 重新拟合SVI（close_state恢复路径）...")
        _refit_F = _state['futures_price']
        _refit_raw = _state['smile_raw']
        _refit_atm = _state.get('atm_strike') or round(_refit_F / 100) * 100
        _K_list, _IV_list = [], []
        for k_str, iv_dict in _refit_raw.items():
            k = int(k_str) if isinstance(k_str, str) and k_str.isdigit() else float(k_str)
            if isinstance(iv_dict, dict):
                if k > _refit_atm:
                    iv_val = iv_dict.get('C') or iv_dict.get('raw_C')
                elif k < _refit_atm:
                    iv_val = iv_dict.get('P') or iv_dict.get('raw_P')
                else:
                    c_iv = iv_dict.get('C') or iv_dict.get('raw_C')
                    p_iv = iv_dict.get('P') or iv_dict.get('raw_P')
                    iv_val = (c_iv + p_iv) / 2 if c_iv and p_iv else (c_iv or p_iv)
            elif isinstance(iv_dict, (int, float)):
                iv_val = iv_dict
            else:
                iv_val = None
            if iv_val and iv_val > 0:
                _K_list.append(k)
                _IV_list.append(iv_val)
        if len(_K_list) >= 4:
            _expiry = _state.get('expiry')
            if _expiry:
                _refit_T = _calc_T_trading_days(_expiry)
            else:
                _refit_T = 30 / _TRADING_DAYS_PER_YEAR
            _refit_smooth, _refit_svi = smooth_smile(_K_list, _IV_list, _refit_F, _refit_T)
            if _refit_svi:
                _state['svi_params'] = _refit_svi
                _last_valid['svi_params'] = _refit_svi
                print(f"[iv_smile] ✅ SVI补拟合成功: a={_refit_svi['a']:.4f}, b={_refit_svi['b']:.4f}, "
                      f"skew={_refit_svi.get('skew', 'N/A')}, curvature={_refit_svi.get('curvature', 'N/A')}")
            else:
                print(f"[iv_smile] ⚠️ SVI补拟合失败（{len(_K_list)}个数据点）")
        else:
            print(f"[iv_smile] ⚠️ raw数据点不足({len(_K_list)})，无法补拟合SVI")

    # === 4. 通用：恢复 expiry/T 和 akshare 价格校正（不论哪条路径） ===
    if not _state.get('expiry'):
        try:
            _contract, _exp = get_active_ta_contract()
            _state['expiry'] = _exp
            _state['active_contract'] = _contract
            # 用剩余有效交易分钟计算T
            _T = _calc_T_trading_days(_exp)
            _state['T'] = _T
            _mins = _count_remaining_trading_minutes(datetime.now(), _exp)
            _td_equiv = _mins / _PTA_TRADING_MINUTES_PER_DAY
            print(f"[iv_smile] 📂 已恢复到期日: {_contract} expiry={_exp.date()} 15:00 T={_T:.6f}yr ({_mins}有效分钟≈{_td_equiv:.2f}交易日)")
        except Exception as e:
            print(f"[iv_smile] ⚠️ 恢复到期日失败: {e}")
    if _state.get('futures_price'):
        try:
            from analysis.option_chain_api import _get_akshare_latest_price
            _contract_code = _state.get('active_contract', 'TA607')
            _ak_price = _get_akshare_latest_price(_contract_code)
            if _ak_price > 0 and _ak_price != _state.get('futures_price'):
                print(f"[iv_smile] 📂 akshare校正价格: {_state.get('futures_price')} → {_ak_price}（含夜盘）")
                _last_valid['futures_price'] = _ak_price
                _state['futures_price'] = _ak_price
        except Exception as e:
            print(f"[iv_smile] ⚠️ akshare价格校正失败: {e}")

    if not _interval_snapshots:
        print("[iv_smile] ⚠️ 未找到历史快照（正常，服务初次启动）")


def _ensure_today_close_baseline_after_21():
    """
    21:00新交易周期开始后，确保前次基准自动切到今日15:00收盘快照。

    场景：服务在15:00前/盘后启动时，_prev_day_baseline 会加载上一交易日15:00；
    到21:00后若进程不断线，必须自动把今日15:00快照灌入 _close_baseline，
    否则 curve/alert/gex 仍会继续拿上一交易日基准。
    """
    global _close_baseline
    now = datetime.now()
    if not (_is_trading_day(now) and now.hour >= 21):
        return False

    today = now.strftime('%Y%m%d')
    cur_ts = (_close_baseline or {}).get('ts') or (_close_baseline or {}).get('timestamp') or ''
    cur_close_point = (_close_baseline or {}).get('close_point', '')
    # 严格判断：必须 close_point='15:00' 且 ts 属于今天 且 有 smooth 数据，才视为已就绪
    # 旧版本（无 close_point 字段）的 15:00 收盘状态也兼容（cur_close_point=='' 时也允许）
    is_valid_15_baseline = (
        (cur_close_point == '' or cur_close_point == '15:00')
        and cur_ts[:10].replace('-', '') == today
        and bool((_close_baseline or {}).get('smooth'))
    )
    if is_valid_15_baseline:
        return True

    path = _get_snapshot_path(today)
    if not os.path.exists(path):
        return False
    try:
        with open(path, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        snap_15 = payload.get('snapshots', {}).get('15:00')
        if not snap_15 or not snap_15.get('smooth'):
            return False
        snap_ts = snap_15.get('timestamp', '')
        if snap_ts[:10].replace('-', '') != today:
            print(f"[iv_smile] ⚠️ 今日15:00基准timestamp不匹配({snap_ts})，不切换")
            return False
        _close_baseline = {
            'smooth': snap_15.get('smooth', {}),
            'raw': snap_15.get('raw', {}),
            'strike_oi': snap_15.get('strike_oi', {}),
            'strike_vol': snap_15.get('strike_vol', {}),
            'S': snap_15.get('S') or snap_15.get('futures_price'),
            'atm_strike': snap_15.get('atm_strike'),
            'ts': snap_ts,
            'close_point': '15:00',  # 明确标记：这是 15:00 收盘基准
        }
        # v2.11.54+: 同时把今日 15:00 写入 prev_baseline.json
        # 这样次日 14:59 启动时，_load_close_state() 从 prev_baseline.json 拿到今日 15:00（即"昨日 15:00"）
        # 不会被次日 15:00 收盘时 close_state.json 覆盖而污染
        _save_prev_baseline(snap_15, today)
        print(f"[iv_smile] 🔁 21:00基准自动切换: 今日15:00 ({today}) smooth={len(_close_baseline['smooth'])}档 oi={len(_close_baseline.get('strike_oi') or {})}档 ts={snap_ts[:19]}")
        return True
    except Exception as e:
        print(f"[iv_smile] ⚠️ 21:00基准自动切换失败: {e}")
        return False


def _try_restore_from_cache():
    """
    当TqSdk数据未到达时，用_last_valid缓存的数据恢复微笑曲线。
    这样即使TqSdk断线，页面仍能显示上次的曲线数据。
    """
    global _state
    if _last_valid.get('smile_smooth') and not _state.get('smile_smooth'):
        _state['smile_smooth'] = _last_valid['smile_smooth']
        _state['smile_raw'] = _last_valid.get('smile_raw', {})
        _state['svi_params'] = _last_valid.get('svi_params')
        if _last_valid.get('futures_price'):
            _state['futures_price'] = _last_valid['futures_price']
        if _last_valid.get('atm_strike'):
            _state['atm_strike'] = _last_valid['atm_strike']
        print("[iv_smile] ✅ 已从缓存恢复微笑曲线数据")

def _restore_from_latest_snapshot():
    """
    用_interval_snapshots中最新的快照数据恢复_state，
    使得TqSdk断开时API仍能返回有效的微笑曲线。
    """
    global _state
    if not _interval_snapshots:
        return
    all_keys = sorted(_interval_snapshots.keys(),
                     key=lambda k: (int(k.replace(':', '')), k))
    latest_key = all_keys[-1]
    snap = _interval_snapshots[latest_key]
    if snap.get('smooth'):
        incoming_ts = snap.get('last_update') or snap.get('timestamp')
        if not _should_restore_current(incoming_ts, f'interval_snapshot:{latest_key}'):
            return
        _state['smile_smooth'] = snap['smooth']
        _state['smile_raw'] = snap.get('raw', {})
        _state['svi_params'] = snap.get('svi_params') or snap.get('sabr_params')  # 兼容旧快照
        if snap.get('futures_price'):
            _state['futures_price'] = snap['futures_price']
        if snap.get('atm_strike'):
            _state['atm_strike'] = snap['atm_strike']
        if snap.get('last_update'):
            _state['last_update'] = snap['last_update']
        if snap.get('strike_oi'):
            _state['strike_oi'] = snap['strike_oi']
        if snap.get('strike_vol'):
            _state['strike_vol'] = snap['strike_vol']
        print(f"[iv_smile] ✅ 已从快照恢复数据 ({latest_key})")

# 启动时尝试加载上一交易日的全量快照（移到smooth_smile定义之后）
# 实际调用在 smooth_smile 定义之后（约第755行）

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
_tqsdk_restart_requested = False   # 请求重启 TqSdk 线程
_tqsdk_reconnect_count = 0         # 累计重连次数
_tqsdk_last_data_time = None      # 上次数据更新时间戳

# ===================== 动态查主力合约 =====================

_EXPIRY_CACHE = {}  # {contract_code: last_trade_date}
_OPTION_STRIKES_CACHE = {}  # {contract_code: [strike, ...]}

# 本地 PTA 期权合约-到期日 fallback 表（v2.11.36+ 修复硬编码 TA607+2026-06-11 bug）
# 当 akshare.option_contract_info_ctp() 完全失败（akshare 不可达/接口变化/超时）时使用。
# 优先级：akshare 实时 > _EXPIRY_CACHE（当日缓存）> _LOCAL_PTA_EXPIRY_FALLBACK（本地表）> 抛异常
# 数据来源：交易所月度合约上市公告 + 2026-06 历史 snapshot。
# 注意：实际到期日以交易所公告为准，本表"近似日期"用于 fallback 选合约即可。
# 维护规则：每季度在月初加 3-6 个月的新合约（按需更新）。
_LOCAL_PTA_EXPIRY_FALLBACK = {
    'TA608': '2026-07-14',  # 2026-07 月期权
    'TA609': '2026-08-12',  # 2026-08 月期权
    'TA610': '2026-09-15',  # 2026-09 月期权
    'TA611': '2026-10-15',  # 2026-10 月期权
    'TA612': '2026-11-13',  # 2026-11 月期权
    'TA701': '2026-12-15',  # 2026-12 月期权
    'TA702': '2027-01-15',  # 2027-01 月期权
    'TA703': '2027-02-12',  # 2027-02 月期权
    'TA704': '2027-03-15',  # 2027-03 月期权
    'TA705': '2027-04-15',  # 2027-04 月期权
    'TA706': '2027-05-14',  # 2027-05 月期权
}

def _get_option_strikes_for_contract(opt_prefix):
    """
    获取当前期权月份真实存在的全档行权价。
    T型表/PCR/Excel需要全档；若交易所合约表获取失败，再由调用方兜底ATM±10。
    """
    global _OPTION_STRIKES_CACHE
    import re
    import akshare as ak

    try:
        df = ak.option_contract_info_ctp()
        if df is None or df.empty:
            raise ValueError("option_contract_info_ctp returned empty")

        name_col = '合约名称'
        underlying_col = '标的合约ID'
        strike_col = '行权价'

        masks = []
        if underlying_col in df.columns:
            masks.append(df[underlying_col].astype(str).eq(opt_prefix))
        if name_col in df.columns:
            masks.append(df[name_col].astype(str).str.startswith(opt_prefix, na=False))
        if not masks:
            raise ValueError(f"missing contract columns: {list(df.columns)}")

        mask = masks[0]
        for m in masks[1:]:
            mask = mask | m
        sub = df[mask].copy()
        if sub.empty:
            raise ValueError(f"no option contracts for {opt_prefix}")

        strikes = []
        if strike_col in sub.columns:
            for v in sub[strike_col].tolist():
                try:
                    if v is not None and str(v).strip() != '':
                        strikes.append(int(float(v)))
                except Exception:
                    pass

        # 兜底：从 TA607C6600 / TA607P6600 这类合约名提取
        if name_col in sub.columns:
            for name in sub[name_col].astype(str).tolist():
                m = re.search(r'[CP](\d+)$', name)
                if m:
                    strikes.append(int(m.group(1)))

        strikes = sorted(set(strikes))
        if not strikes:
            raise ValueError(f"no strikes parsed for {opt_prefix}")

        _OPTION_STRIKES_CACHE[opt_prefix] = strikes
        return strikes
    except Exception as e:
        cached = _OPTION_STRIKES_CACHE.get(opt_prefix)
        if cached:
            print(f"[iv_smile] ⚠️ 获取{opt_prefix}全档行权价失败，使用缓存{len(cached)}档: {e}")
            return cached
        print(f"[iv_smile] ⚠️ 获取{opt_prefix}全档行权价失败: {e}")
        return []

def get_active_ta_contract():
    """
    从交易所实时数据获取最近未到期期权合约（与期权链T型报价 / T表数据切换保持一致）。
    数据源: akshare option_contract_info_ctp()
    统一规则：
      - 15:00 之前：选到期日 >= 今天的最近月合约（保留今天到期的合约，让其参与日内交易）
      - 15:00 之后：选到期日 > 今天的最近月合约（到期日 15:00 收盘后切换）
    返回: (opt_prefix, expiry_date)
    """
    global _EXPIRY_CACHE
    import akshare as ak
    from datetime import datetime

    now = datetime.now()
    today_str = now.strftime('%Y-%m-%d')
    after_1500 = now.strftime('%H%M') >= '1500'

    def _pick(expiry_dict):
        """从 {opt_prefix: 'YYYY-MM-DD'} 字典按 today_str + after_1500 选最近未到期合约。
        选不到时返回 dict 中日期最晚的（兜底，绝不返回 None/硬编码值）。"""
        if not expiry_dict:
            return None, None
        if after_1500:
            active = {k: v for k, v in expiry_dict.items() if v > today_str}
        else:
            active = {k: v for k, v in expiry_dict.items() if v >= today_str}
        if not active:
            sorted_items = sorted(expiry_dict.items(), key=lambda x: x[1])
            return sorted_items[-1]  # 全部过期 → 返回最晚的（异常兜底）
        nearest = sorted(active.items(), key=lambda x: x[1])[0]
        return nearest[0], nearest[1]

    try:
        df = ak.option_contract_info_ctp()
        mask = df['合约名称'].str.startswith('TA', na=False)
        ta_df = df[mask][['合约名称', '最后交易日', '标的合约ID']].copy()
        ta_df = ta_df.drop_duplicates(subset=['标的合约ID'])
        _EXPIRY_CACHE = {r['标的合约ID']: r['最后交易日'] for _, r in ta_df.iterrows()}

        contract_id, last_trade = _pick(_EXPIRY_CACHE)
        if not contract_id:
            # akshare 拉到数据但 pick 不到（极端：全过期或日期格式错）→ 本地 fallback
            contract_id, last_trade = _pick(_LOCAL_PTA_EXPIRY_FALLBACK)
            if not contract_id:
                raise RuntimeError("本地 PTA 合约 fallback 表也无可用合约")
            return contract_id, datetime.strptime(last_trade, '%Y-%m-%d')
        return contract_id, datetime.strptime(last_trade, '%Y-%m-%d')

    except Exception as e:
        # akshare 失败 → 优先用 cache，没有再走本地 fallback（绝对不硬编码 TA607+2026-06-11）
        if _EXPIRY_CACHE:
            contract_id, last_trade = _pick(_EXPIRY_CACHE)
            if contract_id:
                return contract_id, datetime.strptime(last_trade, '%Y-%m-%d')
        contract_id, last_trade = _pick(_LOCAL_PTA_EXPIRY_FALLBACK)
        if contract_id:
            print(f"[iv_smile] ⚠️ akshare+cache均失效，使用本地 PTA 合约 fallback: {contract_id} (到期 {last_trade})")
            return contract_id, datetime.strptime(last_trade, '%Y-%m-%d')
        # 实在无解 → 抛异常让调用方保留 _state['active_contract']
        raise RuntimeError(f"无法确定 PTA 主力合约: akshare失败+cache空+本地fallback也空: {e}")


# ===================== 无风险利率（akshare 国债收益率，1h 缓存） =====================

_rate_cache = {'value': None, 'src': None, 'ts': 0.0}
_RATE_TTL = 3600  # 1 小时刷新一次（日内国债波动 < 5bp）


def _get_risk_free_rate_cached(T=None, force=False):
    """
    拉取无风险利率 r，三层降级：
      1) 优先 .env  IV_RISK_FREE_RATE（手动覆盖）
      2) akshare.bond_zh_us_rate() 按 T 选 2Y/5Y/10Y/30Y
      3) 兜底 0.0225

    T: 标的到期时间（年），用于期限匹配
       T<=0.15 (≤1.5月) → 2Y; 0.15<T<=0.6 (1.5-7月) → 5Y;
       0.6<T<=2.0 (7-24月) → 10Y; T>2.0 → 30Y
    """
    import os, time
    now_ts = time.time()
    if not force and _rate_cache['value'] is not None and (now_ts - _rate_cache['ts']) < _RATE_TTL:
        return _rate_cache['value'], _rate_cache['src']

    default_r = 0.0225
    default_src = 'default(2.25%)'

    # 1) .env 覆盖
    env_r = os.getenv('IV_RISK_FREE_RATE')
    if env_r:
        try:
            r = float(env_r)
            _rate_cache.update({'value': r, 'src': f'env({r:.4f})', 'ts': now_ts})
            return r, f'env({r:.4f})'
        except ValueError:
            pass

    # 2) akshare 拉国债收益率
    try:
        import akshare as ak
        df = ak.bond_zh_us_rate()
        if df is None or len(df) == 0:
            raise ValueError('akshare 返回空数据')
        last = df.iloc[-1]
        if T is None or T <= 0.15:
            col, tenor = '中国国债收益率2年', '2Y'
        elif T <= 0.6:
            col, tenor = '中国国债收益率5年', '5Y'
        elif T <= 2.0:
            col, tenor = '中国国债收益率10年', '10Y'
        else:
            col, tenor = '中国国债收益率30年', '30Y'
        r = float(last[col]) / 100.0
        date_str = str(last.get('日期', ''))
        src = f'akshare({tenor} {date_str}={r*100:.3f}%)'
        _rate_cache.update({'value': r, 'src': src, 'ts': now_ts})
        return r, src
    except Exception as e:
        _rate_cache.update({'value': default_r, 'src': f'{default_src} akshare失败:{type(e).__name__}', 'ts': now_ts})
        return default_r, f'{default_src} akshare失败:{type(e).__name__}'


# ===================== Black76 (期货期权定价) =====================

def black76_price(F, K, T, r, sigma, option_type='C'):
    """
    Black76 期货期权定价公式.
    F: 期货价格 (forward price)
    K: 行权价
    T: 到期时间（年）
    r: 无风险利率
    sigma: 隐含波动率
    """
    from scipy.stats import norm
    if T <= 0 or sigma <= 0:
        return np.nan
    d1 = (np.log(F / K) + 0.5 * sigma ** 2 * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    df = np.exp(-r * T)  # 折现因子
    if option_type == 'C':
        return df * (F * norm.cdf(d1) - K * norm.cdf(d2))
    else:
        return df * (K * norm.cdf(-d2) - F * norm.cdf(-d1))

def bs_iv_brent(F, K, T, r, market_price, option_type='C'):
    """用 Brent 法从市场价格反算 Black76 隐含波动率."""
    from scipy.optimize import brentq
    if T <= 0 or market_price <= 0 or F <= 0 or K <= 0:
        return np.nan
    df = np.exp(-r * T)
    intrinsic = df * max(F - K, 0) if option_type == 'C' else df * max(K - F, 0)
    if market_price < intrinsic * 0.95:
        return np.nan
    if market_price < 0.5:
        return np.nan

    def objective(sigma):
        return black76_price(F, K, T, r, sigma, option_type) - market_price

    try:
        return brentq(objective, 0.01, 5.0, maxiter=200)
    except (ValueError, RuntimeError):
        return np.nan

# ===================== SVI 模型 (Gatheral's Stochastic Volatility Inspired) =====================

def svi_total_variance(k, a, b, rho, m, sigma):
    """
    SVI raw parameterization: total variance w(k) as a function of log-moneyness k.
    w(k) = a + b * [rho * (k - m) + sqrt((k - m)^2 + sigma^2)]
    
    Parameters:
        k: log-moneyness = log(K/F)
        a: overall variance level
        b: slope (controls wing steepness), b >= 0
        rho: correlation/skew, -1 < rho < 1
        m: translation (horizontal shift)
        sigma: smoothing (ATM curvature), sigma > 0
    
    Returns:
        w: total variance = sigma_BS^2 * T
    """
    return a + b * (rho * (k - m) + np.sqrt((k - m) ** 2 + sigma ** 2))


def svi_vol(k, T, a, b, rho, m, sigma):
    """
    从 SVI 参数计算 implied volatility (σ_BS).
    σ_BS = sqrt(w(k) / T)
    """
    w = svi_total_variance(k, a, b, rho, m, sigma)
    if w <= 0 or T <= 0:
        return np.nan
    return np.sqrt(w / T)


def svi_jw_params(a, b, rho, m, sigma, T):
    """
    从 SVI raw 参数计算 SVI-JW (Jim Gatheral's natural) 参数，用于前端展示。
    
    Returns dict with:
        atm_var: ATM total variance w(0) = a + b*(rho*(-m) + sqrt(m^2 + sigma^2))
        atm_vol: ATM implied vol = sqrt(atm_var / T)
        skew: ATM skew ≈ b * rho / (2 * sqrt(atm_var))  (d(sigma)/d(k) at k=0)
        curvature: ATM curvature (smile convexity)
        min_var: minimum total variance = a + b*sigma*sqrt(1-rho^2)
    """
    atm_var = svi_total_variance(0, a, b, rho, m, sigma)
    atm_vol = np.sqrt(atm_var / T) if atm_var > 0 and T > 0 else 0
    
    # ATM skew: dσ/dk at k=0
    # dw/dk = b * (rho + (k-m)/sqrt((k-m)^2 + sigma^2))
    dw_dk_0 = b * (rho + (-m) / np.sqrt(m ** 2 + sigma ** 2))
    # dσ/dk = (1/(2*σ*T)) * dw/dk = dw_dk / (2*sqrt(w*T))
    skew = dw_dk_0 / (2 * np.sqrt(atm_var * T)) if atm_var > 0 and T > 0 else 0
    
    # ATM curvature: d²σ/dk² at k=0 (smile convexity)
    # d²w/dk² = b * sigma^2 / ((k-m)^2 + sigma^2)^(3/2)
    d2w_dk2_0 = b * sigma ** 2 / (m ** 2 + sigma ** 2) ** 1.5
    # curvature = d²σ/dk² = (d²w/dk² - dw/dk²/(2*w)) / (2*σ*T)
    # Simplified practical curvature:
    curvature = d2w_dk2_0 / (2 * np.sqrt(atm_var * T)) if atm_var > 0 and T > 0 else 0
    
    # Minimum variance
    min_var = a + b * sigma * np.sqrt(1 - rho ** 2)
    
    return {
        'atm_var': float(atm_var),
        'atm_vol': float(atm_vol),
        'skew': float(skew),
        'curvature': float(curvature),
        'min_var': float(min_var),
    }


def fit_svi(K_list, IV_list, F, T):
    """
    Fit SVI parameters to market IV data.
    
    Steps:
    1. Convert strikes to log-moneyness k = log(K/F)
    2. Convert IV to total variance w = IV^2 * T
    3. Fit SVI raw params (a, b, rho, m, sigma) by minimizing squared error in w-space
    4. Apply no-arbitrage constraints: a + b*sigma*sqrt(1-rho^2) >= 0, b >= 0, |rho| < 1, sigma > 0
    
    Returns dict with SVI params + JW natural params, or None on failure.
    """
    from scipy.optimize import least_squares, differential_evolution
    
    K_arr = np.array(K_list, dtype=float)
    IV_arr = np.array(IV_list, dtype=float)

    # 过滤无效数据
    valid = ~(np.isnan(IV_arr) | (IV_arr <= 0) | (IV_arr > 2.5))
    if valid.sum() < 3:
        return None

    K_v = K_arr[valid]
    IV_v = IV_arr[valid]

    # 过滤深度OTM：moneyness ±15% 且 绝对距离 ≤1000
    # 深度OTM（如K=4550 IV=103%）会严重拉高SVI曲线ATM端，必须剔除
    moneyness_pct = np.abs(K_v - F) / F
    near_mask = moneyness_pct <= 0.15
    abs_mask = np.abs(K_v - F) <= 1000
    combined_mask = near_mask & abs_mask

    if combined_mask.sum() < 3:
        combined_mask = moneyness_pct <= 0.25
    if combined_mask.sum() < 3:
        return None

    K_v = K_v[combined_mask]
    IV_v = IV_v[combined_mask]

    # v2.11.51+ 异常点过滤：剔除与相邻档偏离过大的孤立点
    # 场景：TqSdk 偶发推送 raw IV 异常（如 6/18 K=6500 Put IV=23.2% vs 邻档 30%+），
    # 拉出 SVI 拟合局部下凹。拟合前按 OTM-Put 翼部单调性检测离群点。
    # 算法：按 K 排序后，计算 IV 的一阶差分，相邻差 > 5pp（绝对）且方向与左/右不一致
    # → 标记为离群点
    if len(K_v) >= 5:
        order = np.argsort(K_v)
        K_sorted = K_v[order]
        IV_sorted = IV_v[order]
        diffs = np.abs(np.diff(IV_sorted))
        median_diff = np.median(diffs)
        # 离群点：相邻 IV 差 > 5pp 且 与中位数差 > 3 倍
        outlier_mask_local = np.zeros(len(K_v), dtype=bool)
        for i in range(1, len(IV_sorted) - 1):
            left_diff = abs(IV_sorted[i] - IV_sorted[i-1])
            right_diff = abs(IV_sorted[i] - IV_sorted[i+1])
            # 中心点的左右差都很大（≥ 5pp），且与翼部中位数差异 > 3 倍
            if left_diff >= 0.05 and right_diff >= 0.05:
                if median_diff > 0 and (left_diff + right_diff) / 2 > median_diff * 3:
                    # 把 K_sorted[i] 对应回原 index
                    outlier_mask_local[order[i]] = True
        if outlier_mask_local.any():
            keep = ~outlier_mask_local
            K_v = K_v[keep]
            IV_v = IV_v[keep]
            if len(K_v) < 3:
                return None
            print(f"[fit_svi] v2.11.51+ 异常点过滤: 剔除 {outlier_mask_local.sum()} 个离群点 "
                  f"(K={sorted([K_v[k] for k in range(len(K_v)) if outlier_mask_local[k]][:5])})")
    
    # 转换到 SVI 空间
    k_arr = np.log(K_v / F)           # log-moneyness
    w_arr = IV_v ** 2 * T             # total variance
    
    # ATM 参考值
    atm_idx = np.argmin(np.abs(k_arr))
    w_atm = w_arr[atm_idx]
    iv_atm = IV_v[atm_idx]
    
    # 初始猜测
    a0 = float(w_atm * 0.5)           # 基础方差水平
    b0 = float(0.1)                   # 翼部斜率
    rho0 = -0.3                       # 负偏斜（商品期权典型）
    m0 = 0.0                          # 以ATM为中心
    sigma0 = float(0.1)               # 平滑参数
    
    def residuals(params):
        a, b, rho, m, sigma = params
        w_model = np.array([svi_total_variance(ki, a, b, rho, m, sigma) for ki in k_arr])
        return w_arr - w_model
    
    # 约束: a + b*sigma*sqrt(1-rho^2) >= 0 (no negative variance)
    # b >= 0, |rho| < 1, sigma > 0
    bounds_lo = [-0.5, 0.001, -0.999, -1.0, 0.001]
    bounds_hi = [ 1.0, 2.0,   0.999,  1.0, 2.0]
    
    best_result = None
    best_cost = np.inf
    
    # 多起点优化，增加鲁棒性
    init_guesses = [
        [a0, b0, rho0, m0, sigma0],
        [a0, 0.05, -0.1, 0.0, 0.2],
        [a0 * 0.8, 0.2, -0.5, 0.0, 0.05],
        [a0 * 1.2, 0.15, -0.2, 0.05, 0.15],
    ]
    
    for x0 in init_guesses:
        try:
            result = least_squares(
                residuals, x0,
                bounds=(bounds_lo, bounds_hi),
                method='trf',
                max_nfev=1000,
                ftol=1e-12,
                xtol=1e-12,
            )
            if result.cost < best_cost:
                best_cost = result.cost
                best_result = result
        except Exception:
            continue
    
    if best_result is None:
        return None
    
    a, b, rho, m, sigma = best_result.x
    
    # 检查无套利条件: min variance >= 0
    min_var = a + b * sigma * np.sqrt(1 - rho ** 2)
    if min_var < -0.01:
        # 尝试修正 a 使 min_var = 0
        a = -b * sigma * np.sqrt(1 - rho ** 2) + 0.001
    
    # 计算 JW 自然参数
    jw = svi_jw_params(a, b, rho, m, sigma, T)
    
    # 计算拟合质量
    w_fitted = np.array([svi_total_variance(ki, a, b, rho, m, sigma) for ki in k_arr])
    iv_fitted = np.sqrt(np.maximum(w_fitted, 0) / T)
    rmse = np.sqrt(np.mean((IV_v - iv_fitted) ** 2))
    
    return {
        'a': float(a),
        'b': float(b),
        'rho': float(rho),
        'm': float(m),
        'sigma': float(sigma),
        'atm_vol': jw['atm_vol'],
        'skew': jw['skew'],
        'curvature': jw['curvature'],
        'min_var': jw['min_var'],
        'rmse': float(rmse),
        'metric_note': {
            'skew': 'ATM skew = dσ/dk|0，表示ATM附近隐波对数价差的一阶斜率；不是rho本身，也不是翼部斜率。',
            'curvature': 'curvature = ATM附近二阶凸性近似值，数值越大表示微笑越弯。',
            'rho': 'rho 是 SVI 原始参数中的偏斜控制项，通常为负表示左偏，但与展示层 skew 不是同一数值。',
            'rmse': 'rmse 表示拟合误差，越小越好。',
        },
        'success': True,
    }


def smooth_smile(K_list, IV_list, F, T):
    """
    SVI拟合 → 重建平滑曲线。

    设计原则（用户指定）：
    1. 平滑：SVI 在全 moneyness 范围连续光滑
    2. 与隐波 raw 差值不能太大：SVI 拟合时直接用 raw 的 OTM 端 IV
    3. 输出键**只覆盖真实存在的行权价**（从 K_list 推导，不外推伪造中间点）：
       真实 PTA 期权只有 32 档（5000/5100/.../8100，100 步长），
       不应塞入 5250/5350/.../7750 等 SVI 外推出来的、不存在的合约。
       横坐标只展示真实合约 → SVI 曲线在真实 strike 上仍有数据点，
       曲线本身的连续性由 SVI 模型在 moneyness 范围 ±20% 内保证。
    """
    svi = fit_svi(K_list, IV_list, F, T)
    if svi is None:
        return {}, None

    a, b, rho, m, sigma = svi['a'], svi['b'], svi['rho'], svi['m'], svi['sigma']

    # moneyness 硬限：拟合在 ±20% 范围内才有意义；超过此范围的翼部外推不可信
    K_low_cap  = int(round(F * 0.80))
    K_high_cap = int(round(F * 1.20))

    # 只输出真实存在的行权价（CZCE PTA 实际合约是 100 步长，如 5000/5100/.../8100）
    real_strikes = sorted(set(int(k) for k in K_list))
    # 真实 strike 可能超出 moneyness 范围（深度虚值），裁剪到 [K_low_cap, K_high_cap]
    all_strikes = [k for k in real_strikes if K_low_cap <= k <= K_high_cap]

    smooth_iv = {}
    for k_strike in all_strikes:
        k_log = np.log(k_strike / F)
        iv = svi_vol(k_log, T, a, b, rho, m, sigma)
        if not np.isnan(iv) and 0 < iv < 2.5:
            smooth_iv[k_strike] = iv

    return smooth_iv, svi

# 启动时加载上一交易日快照（必须在 smooth_smile/fit_svi 定义之后）
_load_previous_day_snapshots()

_MAX_INIT_WAIT = 600  # 初始化等待秒数（10分钟，给模拟账户足够时间接收期权数据）
_MAX_CONNECT_WAIT = 90  # 期货行情等待秒数（每次0.1秒，共9秒）
_DATA_STALE_SECONDS = 120  # 数据超过此秒数未更新则触发重连

def _request_tqsdk_restart(reason=""):
    """请求重启 TqSdk 线程（异步安全）"""
    global _tqsdk_restart_requested
    _tqsdk_restart_requested = True
    print(f"[iv_smile] 🔄 请求重启 TqSdk: {reason}")


def tqsdk_loop():
    """独立线程运行TQSdk事件循环（支持初始化超时自重启）"""
    global _tqsdk_ready, _tqsdk_quotes, _state, _option_symbols
    global _tqsdk_restart_requested, _tqsdk_reconnect_count, _tqsdk_last_data_time

    import asyncio
    from tqsdk import TqApi, TqAuth, TqKq

    connect_attempts = 0
    max_restarts = 10  # 最多自动重连10次，避免无限循环

    while _state['running'] and connect_attempts < max_restarts:
        # 重置重启标志
        _tqsdk_restart_requested = False
        connect_attempts += 1
        _tqsdk_reconnect_count = connect_attempts - 1

        if connect_attempts > 1:
            print(f"[iv_smile] 🔄 第{connect_attempts-1}次重连中...（最多{max_restarts}次）")
            time.sleep(3)  # 重连前等3秒

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
            _state['data_ready'] = False  # 重置数据就绪标志
            print(f"[iv_smile] 主力合约: {opt_prefix} 到期: {expiry.date()}")

            # === 获取期货行情 ===
            fut_quote = api.get_quote(fut_sym)

            # === 生成期权列表（平值上下10档） ===
            # 先获取期货价格确定ATM
            S = None
            connect_wait = 0
            while connect_wait < _MAX_CONNECT_WAIT:
                if _tqsdk_restart_requested or not _state['running']:
                    break
                api.wait_update()
                loop.run_until_complete(asyncio.sleep(0.1))
                last = getattr(fut_quote, 'last_price', None)
                if last and last > 0:
                    S = last
                    break
                bid = getattr(fut_quote, 'bid_price1', None)
                ask = getattr(fut_quote, 'ask_price1', None)
                if bid and ask and bid > 0:
                    S = (bid + ask) / 2
                    break
                connect_wait += 1

            if not S:
                print(f"[iv_smile] ⚠️ 期货行情未到达，使用默认值 S=6500")
                S = 6500.0

            # 检查是否被请求重启（等待期货行情时被中断）
            if _tqsdk_restart_requested or not _state['running']:
                api.close()
                loop.close()
                continue

            # PTA 最小变动价位为2，取偶数
            S = round(S / 2) * 2
            atm_strike = round(S / 100) * 100

            # T型表/PCR/Excel必须订阅当前月份真实存在的全档行权价；ATM±10只作为合约表失败兜底。
            strikes = _get_option_strikes_for_contract(opt_prefix)
            if strikes:
                print(f"[iv_smile] S={S:.0f} ATM={atm_strike} 全档订阅{opt_prefix} 行权价数:{len(strikes)} 档位:{strikes[0]}~{strikes[-1]}")
            else:
                strikes = list(range(atm_strike - 10 * 100, atm_strike + 11 * 100, 100))
                print(f"[iv_smile] S={S:.0f} ATM={atm_strike} ⚠️ 全档获取失败，兜底ATM±10 档位:{strikes[0]}~{strikes[-1]}")

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

            # === 等待所有期权行情到达（持续等待，不设超时上限）===
            print("[iv_smile] 等待期权行情（持续等待，不放弃）...")
            data_ready_count = 0
            last_progress_time = time.time()
            wait_start = time.time()
            while True:
                if _tqsdk_restart_requested or not _state['running']:
                    break
                api.wait_update()
                loop.run_until_complete(asyncio.sleep(0.1))
                count = 0
                for sym, _, _ in option_symbols:
                    oq = option_quotes.get(sym)
                    if oq:
                        # 全档订阅后，深虚值/深实值期权经常没有bid，但仍有持仓/成交等T表所需字段。
                        # 等待条件不能只看bid，否则会卡在64/86，导致T表继续返回旧的21档快照。
                        bid = getattr(oq, 'bid_price1', None) or 0
                        ask = getattr(oq, 'ask_price1', None) or 0
                        last = getattr(oq, 'last_price', None) or 0
                        oi = getattr(oq, 'open_interest', None) or 0
                        vol = getattr(oq, 'volume', None) or 0
                        if bid > 0 or ask > 0 or last > 0 or oi > 0 or vol > 0:
                            count += 1
                elapsed = time.time() - wait_start
                # 全档链深档可能长期无报价（深度虚值/实值档休盘期间 TqSdk 也会推 OI/volume，但需要更多连接次数）。
                # 不再用 0.6/21 的过早硬门槛（否则 64 档只凑齐 21 档就 break，丢 11 档深档数据）。
                # 新策略：目标凑齐 95% 全档（akshare 合约表动态拉取，不硬编码具体档数）。
                # 兜底：60s 后还没到 95% 但已有 60%，先 break 进入主循环持续接收深档。
                target_ready = int(len(option_symbols) * 0.95)
                fallback_ready = int(len(option_symbols) * 0.60)
                if count > data_ready_count:
                    data_ready_count = count
                    print(f"  [{elapsed:.0f}s] {count}/{len(option_symbols)} 个期权字段已到达（目标 {target_ready}）")
                    if count >= target_ready:
                        print(f"[iv_smile] ✅ 期权字段全档就位 ({data_ready_count}/{len(option_symbols)})，继续...")
                        break
                # 60s 兜底：超时后即使没到 95%，也先进入主循环，剩余深档在主循环中继续接收
                if elapsed >= 60 and data_ready_count >= fallback_ready:
                    print(f"[iv_smile] ⏱️ 60s 已到但未凑齐 {target_ready}（当前 {data_ready_count}/{len(option_symbols)}），先进入主循环继续接收深档")
                    break
                # 每5秒报告一次进度（持续等待，不放弃）
                if time.time() - last_progress_time >= 5:
                    print(f"  [{elapsed:.0f}s] 等待中... {count}/{len(option_symbols)} 个期权字段已到达（深档无bid不阻塞）")
                    last_progress_time = time.time()
                loop.run_until_complete(asyncio.sleep(0.05))

            # 检查是否被请求重启（等待期权时被中断）
            if _tqsdk_restart_requested or not _state['running']:
                api.close()
                loop.close()
                continue

            # 即使没到 95%，只要 fallback_ready (60%) 就绪就继续
            if data_ready_count < fallback_ready:
                if data_ready_count > 0:
                    print(f"[iv_smile] ⚠️ 只有 {data_ready_count}/{len(option_symbols)} 期权有报价（fallback={fallback_ready}），持续等待（模拟账户数据可能延迟）")
                else:
                    print(f"[iv_smile] ⚠️ 期权数据暂未到达，持续等待（模拟账户数据可能延迟）...")
            else:
                print(f"[iv_smile] ✅ 数据就绪，{data_ready_count}/{len(option_symbols)} 个期权有有效报价（目标 95%={target_ready}）")

            _state['data_ready'] = True
            _tqsdk_ready = True
            _tqsdk_last_data_time = time.time()

            # === 主事件循环 ===
            counter = 0
            last_log_time = time.time()
            _last_integrity_check_time = time.time()
            _last_integrity_restart_time = 0.0
            # 期望档数（行权价数）= option_symbols 去重后的 strike 数
            _expected_strike_count = len(set(s[1] for s in option_symbols))
            # 档数不达标起始时间（持续低于 80% 才报警，避免误报）
            _integrity_alert_start = None
            while _state['running'] and not _tqsdk_restart_requested:
                try:
                    api.wait_update(deadline=loop.time() + 1.0)

                    # 每5秒快照一次（用于compute_once）
                    counter += 1
                    if counter % 5 == 0:
                        snap = {
                            'futures': {
                                'last': getattr(fut_quote, 'last_price', None),
                                'close': getattr(fut_quote, 'close', None),
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
                                    'open_interest': getattr(oq, 'open_interest', None) or 0,
                                    'volume': getattr(oq, 'volume', None) or 0,
                                }
                        _tqsdk_quotes['snap'] = snap
                        _tqsdk_last_data_time = time.time()

                    # 每60秒检查数据时效
                    if time.time() - last_log_time >= 60:
                        stale = time.time() - _tqsdk_last_data_time
                        if stale > _DATA_STALE_SECONDS:
                            print(f"[iv_smile] ⚠️ 数据超时 {stale:.0f}秒，触发重启")
                            _request_tqsdk_restart(f"data stale {stale:.0f}s")
                        last_log_time = time.time()

                    # 每60秒轮询 close_state.json mtime。盘后手工补盘（或定时落盘）
                    # 写入了新文件，而本进程未重启 → 内存 _close_baseline 还是旧基准。
                    # 检测到 mtime 变化就调一次 _load_close_state()：盘中通常
                    # _eod_state_loaded=True，函数走"只设 _close_baseline 不覆盖
                    # _state"分支，前端 T 表立刻切到新基准（不影响 current 实时值）。
                    # 独立计时器 _last_close_state_check_ts，避免与 last_log_time 抢节奏，
                    # 也避免每 1s wait_update 都 stat 文件。
                    global _close_state_last_mtime, _last_close_state_check_ts
                    if time.time() - _last_close_state_check_ts >= 60:
                        _last_close_state_check_ts = time.time()
                        try:
                            if os.path.exists(_CLOSE_STATE_FILE):
                                mtime = os.path.getmtime(_CLOSE_STATE_FILE)
                                if mtime > _close_state_last_mtime:
                                    # 第一次进入循环时 _close_state_last_mtime=0，盘上
                                    # 文件 mtime 一定 > 0，正常触发一次 reload（启动时
                                    # _load_close_state 已加载过，所以 reload 是 no-op
                                    # 但会打一行日志方便排查；后续就只在 mtime 真变化时触发）
                                    _close_state_last_mtime = mtime
                                    old_ts = _close_baseline.get('ts', '') if _close_baseline else ''
                                    if _load_close_state():
                                        new_ts = _close_baseline.get('ts', '') if _close_baseline else ''
                                        if new_ts != old_ts:
                                            print(f"[iv_smile] 🔄 盘外 reload close_state.json: 基准 ts {old_ts[:19] or '∅'} → {new_ts[:19]}")
                                        else:
                                            print(f"[iv_smile] 🔄 reload close_state.json（基准 ts 未变: {new_ts[:19]}）")
                        except Exception as e:
                            print(f"[iv_smile] ⚠️ close_state.json mtime 检查失败: {e}")

                    # 每60秒检测 _prev_day_baseline 是否需要切换（节后首日 9:00 触发）
                    # 场景：服务跨节假日长期运行（如 6/19 启动 → 6/22 9:00 开盘），
                    # 冷启动时按节假日兜底加载了 6/17 15:00 作为 _prev_day_baseline，
                    # 但服务进程没重启，_prev_day_baseline 不会自动换成 6/18 15:00。
                    # 修法：每 60s 调 _get_expected_baseline_date() 算出"应当生效的基准日"，
                    # 与 _prev_baseline_expected_date 对比，不一致就重新加载对应文件 15:00 键。
                    global _prev_baseline_expected_date, _last_prev_baseline_check_ts
                    if time.time() - _last_prev_baseline_check_ts >= 60:
                        _last_prev_baseline_check_ts = time.time()
                        try:
                            expected_dt = _get_expected_baseline_date(datetime.now())
                            expected_str = expected_dt.strftime('%Y%m%d') if expected_dt else None
                            if expected_str and expected_str != _prev_baseline_expected_date:
                                # 预期基准日变了 → 重新加载新基准日文件
                                old_expected = _prev_baseline_expected_date or '∅'
                                snap_path = _get_snapshot_path(expected_str)
                                if os.path.exists(snap_path):
                                    with open(snap_path, 'r', encoding='utf-8') as f:
                                        snap_payload = json.load(f)
                                    snap_15 = (snap_payload.get('snapshots') or {}).get('15:00')
                                    if snap_15 and snap_15.get('smooth'):
                                        # 校验 timestamp 与预期日匹配（防污染数据）
                                        snap_ts = snap_15.get('timestamp', '')
                                        snap_date = snap_ts[:10].replace('-', '') if snap_ts else ''
                                        if snap_date == expected_str:
                                            _prev_day_baseline = snap_15
                                            _prev_baseline_expected_date = expected_str
                                            print(f"[iv_smile] 🔄 _prev_day_baseline 切换: {old_expected} → {expected_str} "
                                                  f"(S={snap_15.get('futures_price', '?')}, "
                                                  f"smooth={len(snap_15.get('smooth', {}))}档, "
                                                  f"oi={len(snap_15.get('strike_oi', {}))}档, "
                                                  f"ts={snap_ts[:19]})")
                                        else:
                                            print(f"[iv_smile] ⚠️ 预期基准日 {expected_str} 的 15:00 快照 timestamp={snap_ts[:19]} 不匹配，跳过切换")
                                    else:
                                        print(f"[iv_smile] ⚠️ 预期基准日 {expected_str} 的 15:00 键缺失或无 smooth 字段，跳过切换")
                                else:
                                    print(f"[iv_smile] ⚠️ 预期基准日 {expected_str} 的快照文件不存在 ({snap_path})，跳过切换")
                        except Exception as e:
                            print(f"[iv_smile] ⚠️ _prev_day_baseline 切换检测失败: {e}")

                    # 每30秒检查档数完整性（防止 TqSdk 推送档数减少导致 T表/PCR 算错）
                    if time.time() - _last_integrity_check_time >= 30:
                        _last_integrity_check_time = time.time()
                        # 实际档数 = smile_raw 收到的行权价数（每个行权价同时有 C 和 P）
                        with _state['lock']:
                            _actual_strike_count = len(_state.get('smile_raw', {}))
                        ratio = _actual_strike_count / _expected_strike_count if _expected_strike_count else 0
                        if ratio < 0.80:
                            if _integrity_alert_start is None:
                                _integrity_alert_start = time.time()
                            else:
                                _alert_dur = time.time() - _integrity_alert_start
                                if _alert_dur >= 180:  # 持续 3 分钟
                                    # 最小重连间隔 5 分钟（避免重连风暴）
                                    if time.time() - _last_integrity_restart_time >= 300:
                                        print(f"[iv_smile] ⚠️ 档数不达标 {_actual_strike_count}/{_expected_strike_count}={ratio:.1%} 持续 {_alert_dur:.0f}s，触发 TqSdk 重连")
                                        _request_tqsdk_restart(f"integrity {ratio:.1%}")
                                        _last_integrity_restart_time = time.time()
                                        _integrity_alert_start = None
                        else:
                            # 档数达标，重置报警计时
                            if _integrity_alert_start is not None:
                                print(f"[iv_smile] ✅ 档数恢复 {_actual_strike_count}/{_expected_strike_count}={ratio:.1%}")
                                _integrity_alert_start = None

                except Exception as e:
                    if _state['running']:
                        print(f"[iv_smile] wait_update异常: {e}")
                        _request_tqsdk_restart(f"wait_update exception: {e}")
                    break

            api.close()
            loop.close()

            # wait_update异常/主动请求重启：走外层重连，不退出线程
            if _tqsdk_restart_requested:
                print("[iv_smile] 🔄 TqSdk 线程重启中...")
                continue

            # 非主动退出的异常，退出重试循环
            if _state['running']:
                print(f"[iv_smile] ⚠️ TqSdk 连接中断，退出（running={_state['running']}）")
                break

        except Exception as e:
            print(f"[iv_smile] TQSdk线程异常: {e}")
            import traceback; traceback.print_exc()
            _tqsdk_ready = False
            # 达到最大重连次数则放弃
            if connect_attempts >= max_restarts:
                print(f"[iv_smile] ❌ 已达最大重连次数（{max_restarts}），停止重连")
                break
            print(f"[iv_smile] 🔄 3秒后重连（第{connect_attempts}次）...")
            time.sleep(3)

    _tqsdk_ready = False
    print("[iv_smile] TQSdk线程已退出")

# ===================== 核心计算 =====================

def calc_max_pain(opt_snap, S):
    """
    计算最大痛点行权价（标准 Max Pain 公式）。
    opt_snap: {strike: {'C': oi, 'P': oi}}
    S: 当前期货价格（偶数化，仅用于兜底）
    返回: 最大痛点行权价（偶数），或 None

    标准公式: 对每个候选结算价 K，计算所有期权买方的总收益：
      pain(K) = Σᵢ [ call_oiᵢ × max(K - Kᵢ, 0) + put_oiᵢ × max(Kᵢ - K, 0) ]
    取 pain 最小的 K —— 买方总收益最低 = 卖方利益最大化 = 散户亏最多钱的位置。
    """
    if not opt_snap:
        return None

    # key可能是str/int/float，统一转float再计算
    unified = {}
    for k, v in opt_snap.items():
        try:
            unified[float(k)] = v
        except (ValueError, TypeError):
            continue

    strikes = sorted(unified.keys())
    if len(strikes) < 2:
        return None

    # 对每个候选结算价K，计算所有期权买方的总收益
    mp = {}
    for K in strikes:
        pain = 0
        for Ki in strikes:
            c_oi = unified[Ki].get('C') or 0
            p_oi = unified[Ki].get('P') or 0
            pain += c_oi * max(K - Ki, 0) + p_oi * max(Ki - K, 0)
        mp[K] = pain

    if not mp or sum(mp.values()) == 0:
        return None

    # 返回 pain 最小的行权价（偶数）
    min_pain_strike = min(mp, key=lambda k: mp[k])
    # PTA tick=2，保持偶数
    return round(min_pain_strike / 2) * 2


def compute_once(force=False):
    """执行一次IV计算（每分钟实时触发）
    
    只要TqSdk有数据就计算更新_state（GEX/MaxPain/IV等指标始终基于最新数据）。
    快照写入仅在交易时段进行，避免非交易时段产生脏快照。
    baseline(前次基准)由独立逻辑控制，每交易日21:00切换。
    
    Args:
        force: True时强制写入快照（手动触发场景）
    """
    global _state

    if 'snap' not in _tqsdk_quotes:
        # 即使 data_ready=False，也要尝试从快照恢复数据（保持微笑曲线活跃）
        _restore_from_latest_snapshot()
        print("[iv_smile] 数据尚未到达，已从快照恢复")
        return False

    snap = _tqsdk_quotes.get('snap')
    if not snap:
        return False

    # 1. 期货价格：优先用 last_price（真实成交价），盘中可用 bid/ask 中间价补充
    fut = snap.get('futures', {})
    S = None
    last = fut.get('last')
    if last and last > 0:
        S = last
    if not S:
        bid = fut.get('bid')
        ask = fut.get('ask')
        if bid and ask and bid > 0 and ask > 0:
            S = (bid + ask) / 2
    if not S or S <= 0:
        S = _last_valid.get('futures_price')
    if not S or S <= 0:
        print("[iv_smile] 无法获取期货价格")
        return False

    # PTA 最小变动价位=2，取偶数
    S = round(S / 2) * 2

    # 2. 持仓量/成交量数据 + 计算最大痛点
    opt_snap = snap.get('options', {})

    # 构建 {strike: {C/P: oi}} / {strike: {C/P: volume}} 结构
    # 修复：原本用 `if oi > 0` 过滤，导致 TqSdk 推送的深度虚值/实值档（OI=0）被丢弃，
    # strike_oi 永远只有 ATM±10 档（21 档）。改为全档填充（OI/Vol=0 也保留），
    # T 表/PCR/Max Pain 才能遍历 akshare 合约表的全档（动态档数，跟 _get_option_strikes_for_contract 保持一致）。
    strike_oi = {}
    strike_vol = {}
    for sym, strike, opt_type in _option_symbols:
        q = opt_snap.get(sym, {})
        oi = q.get('open_interest') or q.get('oi') or 0
        vol = q.get('volume') or q.get('vol') or 0
        if strike not in strike_oi:
            strike_oi[strike] = {'C': 0, 'P': 0}
        if strike not in strike_vol:
            strike_vol[strike] = {'C': 0, 'P': 0}
        strike_oi[strike][opt_type] = oi
        strike_vol[strike][opt_type] = vol

    max_pain = calc_max_pain(strike_oi, S)
    if max_pain is None:
        # 兜底：用期货价估算
        max_pain = round(S / 100) * 100

    # 参考行权价 = 最大痛点
    ref_strike = max_pain

    # 3. 剩余期限（年）— 用交易日计算
    expiry = _state.get('expiry')
    if not expiry:
        print("[iv_smile] 到期日未设置")
        return False
    T = _calc_T_trading_days(expiry)

    # 3.5 无风险利率：akshare 拉国债收益率（按 T 选期限），1h 缓存
    r, r_src = _get_risk_free_rate_cached(T)
    old_r = _state.get('rate', 0.0225)
    if abs(r - old_r) > 1e-6 or _state.get('rate_src', '').startswith('default'):
        print(f"[iv_smile] 💰 无风险利率 r 更新: {old_r*100:.3f}% → {r*100:.3f}% ({r_src}) T={T:.4f}y")
    _state['rate'] = r
    _state['rate_src'] = r_src

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

    # ATM行权价 = 最接近标的价的行权价
    atm_strike = min(raw_iv.keys(), key=lambda k: abs(k - S))

    # 5. SVI平滑 — 用OTM端IV（call for K>ATM, put for K<ATM），避免 ITM 端噪音
    K_list, IV_list = [], []
    for strike in sorted(raw_iv.keys()):
        if strike > atm_strike:
            # OTM call
            iv_val = raw_iv[strike].get('C')
        elif strike < atm_strike:
            # OTM put
            iv_val = raw_iv[strike].get('P')
        else:
            # ATM：取C和P的平均值
            c_iv = raw_iv[strike].get('C')
            p_iv = raw_iv[strike].get('P')
            if c_iv and p_iv:
                iv_val = (c_iv + p_iv) / 2
            else:
                iv_val = c_iv or p_iv
        if iv_val and iv_val > 0:
            K_list.append(strike)
            IV_list.append(iv_val)

    smooth_iv, svi = smooth_smile(K_list, IV_list, S, T)

    if not smooth_iv:
        print(f"[iv_smile] SVI拟合失败，跳过")
        return False

    with _state['lock']:
        now = datetime.now()
        
        # 快照写入：仅在交易时段 或 force 模式下写入，避免非交易时段脏快照
        is_trading = _is_trading_hours()
        if is_trading or force:
            # 按固定15分钟时间点存储快照
            # ⛔ 同一15分钟块内不覆盖：避免同一槽内多次计算导致数据被冲掉
            interval_key = get_interval_key(now)
            if _is_opening_first_minute(now):
                print(f"[iv_smile] ⏭ 跳过开盘首分钟快照: {interval_key}，等待下一分钟完整行情")
                interval_key = None
            elif interval_key in _interval_snapshots:
                print(f"[iv_smile] ⏭ 跳过重复写入: {interval_key}（该槽已存在）")
            else:
                _interval_snapshots[interval_key] = {
                    'smooth': {k: float(v) for k, v in smooth_iv.items()},
                    'raw': {k: dict(v) for k, v in raw_iv.items()},
                    'timestamp': now.isoformat(),
                    'svi_params': svi,
                    'futures_price': S,
                    'ref_strike': ref_strike,
                    'max_pain': max_pain,
                    'atm_strike': atm_strike,
                    'strike_oi': {k: dict(v) for k, v in strike_oi.items()},
                    'strike_vol': {k: dict(v) for k, v in strike_vol.items()},
                }
                print(f"[iv_smile] 📦 快照已存: {interval_key} ({len(_interval_snapshots)}个时间点)")
        else:
            print(f"[iv_smile] 📊 非交易时段，_state已更新（不写快照）")

        # 非交易时段保护：如果已有更完整的smile数据（如close_state恢复的），
        # 不用不完整的计算结果覆盖。仅在交易时段 或 新数据更完整时才更新smile。
        existing_smooth_count = len(_state.get('smile_smooth') or {})
        new_smooth_count = len(smooth_iv or {})
        should_update_smile = is_trading or force
        # 非交易时段且非force：不用实时计算的smile覆盖close_state恢复的数据
        # （因为非交易时段T用datetime.now()算会偏小，导致IV虚高）

        # 盘后兜底：如果 TqSdk 拉到的 OI/Vol 全部为 0（夜盘后/盘后心跳特征），
        # 保留 _last_valid 里的有效值（避免覆盖 23:00 收盘后的真实持仓）
        lv_oi = _last_valid.get('strike_oi') or {}
        lv_vol = _last_valid.get('strike_vol') or {}
        if lv_oi and not any((v.get('C', 0) or 0) + (v.get('P', 0) or 0) for v in strike_oi.values()):
            print(f"[iv_smile] ⚠️ TqSdk OI 全 0（盘后心跳），用 _last_valid 兜底 {len(lv_oi)}档")
            strike_oi = {k: dict(v) for k, v in lv_oi.items()}
        if lv_vol and not any((v.get('C', 0) or 0) + (v.get('P', 0) or 0) for v in strike_vol.values()):
            print(f"[iv_smile] ⚠️ TqSdk Vol 全 0（盘后心跳），用 _last_valid 兜底 {len(lv_vol)}档")
            strike_vol = {k: dict(v) for k, v in lv_vol.items()}

        # 更新缓存（价格/OI始终更新，smile视情况）
        _last_valid['futures_price'] = S
        _last_valid['ref_strike'] = ref_strike
        _last_valid['max_pain'] = max_pain
        _last_valid['atm_strike'] = atm_strike
        _last_valid['strike_oi'] = {k: dict(v) for k, v in strike_oi.items()}
        _last_valid['strike_vol'] = {k: dict(v) for k, v in strike_vol.items()}
        if should_update_smile:
            _last_valid['smile_raw'] = {k: v for k, v in raw_iv.items()}
            _last_valid['smile_smooth'] = smooth_iv
            _last_valid['svi_params'] = svi

        # 更新状态
        _state['strike_oi'] = {k: dict(v) for k, v in strike_oi.items()}
        _state['strike_vol'] = {k: dict(v) for k, v in strike_vol.items()}
        _state['futures_price'] = S
        _state['T'] = T                     # 保持T与数据同步（GEX API依赖此值）
        _state['ref_strike'] = ref_strike   # 最大痛点（参考行权价）
        _state['max_pain'] = max_pain        # 最大痛点
        _state['atm_strike'] = atm_strike      # ATM = 最接近标的价的行权价
        if should_update_smile:
            _state['smile_raw'] = {k: v for k, v in raw_iv.items()}
            _state['smile_smooth'] = smooth_iv
            _state['svi_params'] = svi
        else:
            print(f"[iv_smile] 📊 保留已有smile数据({existing_smooth_count}档)，不用不完整数据({new_smooth_count}档)覆盖")
        # v2.11.47+: last_update 必须在每次 compute_once 都同步,不能只在交易时段更新
        # 否则盘后/夜盘 last_update 会永远停在最后一次 14:59:xx,用户看到"最后更新 14:59"误以为停止刷新
        _state['last_update'] = now.isoformat()

    svi_str = (f"a={svi['a']:.4f} b={svi['b']:.4f} ρ={svi['rho']:.3f} ATMvol={svi['atm_vol']:.2%}") if svi else "失败"
    mp_str = f"MP={max_pain}" if max_pain else ""
    print(f"[iv_smile] ✅ S={S:.0f} {mp_str} 档位={len(raw_iv)} SVI({svi_str})")

    # IV变化报警检查（对比当日15:00收盘基准）
    _check_iv_alert(smooth_iv, raw_iv, strike_oi, S, max_pain)

    # 15:00收盘时记录基准快照（每个交易日只记一次）
    # v2.11.53+ 修复: 守门条件从 `not _close_baseline` 改为"今天不是 baseline 的日期"。
    # 旧逻辑会让 6/18 启动后加载的 6/18 baseline 一直存在, 此后每天 15:00 都因 _close_baseline 已设而跳过,
    # 导致 _close_baseline 永远停留在第一次启动的日期, 切换门控永远失败, 退到 _prev_day_baseline (6/18)。
    now = datetime.now()
    if now.hour == 15 and now.minute == 0:
        baseline_ts = (_close_baseline or {}).get('ts', '')
        baseline_is_today = False
        try:
            baseline_is_today = baseline_ts[:10] == now.strftime('%Y-%m-%d')
        except Exception:
            pass
        if not baseline_is_today:
            _record_close_baseline(smooth_iv, raw_iv, strike_oi, S, strike_vol)

    # PTA 四个收盘时间点（10:15/11:30/15:00/23:00）自动保存收盘快照
    _check_and_save_close_state()

    return True

# ===================== 定时调度 =====================

# 调度器
_last_snapshot_minute = -1  # 上次持久化的时间（分钟），避免重复

def _refresh_t_offhours():
    """休盘时段刷新T和依赖T的指标（GEX等），不写快照、不更新smile"""
    expiry = _state.get('expiry')
    if not expiry:
        return
    T = _calc_T_trading_days(expiry)
    with _state['lock']:
        old_T = _state.get('T')
        _state['T'] = T
    mins = _count_remaining_trading_minutes(datetime.now(), expiry)
    td_equiv = mins / _PTA_TRADING_MINUTES_PER_DAY
    print(f"[iv_smile] 🕐 休盘T刷新: T={T:.6f}yr ({mins}有效分钟≈{td_equiv:.2f}交易日) (前值={old_T:.6f})" if old_T else
          f"[iv_smile] 🕐 休盘T刷新: T={T:.6f}yr ({mins}有效分钟≈{td_equiv:.2f}交易日)")


def start_scheduler(interval_minutes=1):
    def loop():
        global _last_snapshot_minute
        print(f"[iv_smile] 调度器启动，间隔={interval_minutes}分钟")
        counter = 0
        offhours_t_counter = 0  # 休盘T刷新计数器
        _last_contract_roll_date = None  # 每日合约检查去重
        while _state['running']:
            # 每日 14:55 强制合约切换（不依赖 TqSdk 自愈）
            # 设计缺陷：get_active_ta_contract() 只在 tqsdk_loop 重连时被调用，
            # 而 TqSdk 长连接不重启 → 进程永远锁死在启动时选中的合约。
            # 5/29 启动后选 TA607，6/11 当日 14:35 后 iv_smile 一直显示旧值，
            # 直到人工重启才发现问题。这里 14:55 主动请求重启 TqSdk 线程，
            # 触发重新选合约 + 重新订阅。
            now_check = datetime.now()
            if (now_check.hour == 14 and now_check.minute == 55
                    and _last_contract_roll_date != now_check.date()):
                _last_contract_roll_date = now_check.date()
                try:
                    cur_active = _state.get('active_contract', '?')
                    new_pref, new_expiry = get_active_ta_contract()
                    if new_pref != cur_active:
                        print(f"[iv_smile] 🔄 14:55 主力切换: {cur_active} → {new_pref} (到期 {new_expiry.date()})")
                        _request_tqsdk_restart("daily 14:55 contract roll")
                    else:
                        print(f"[iv_smile] ✅ 14:55 合约检查通过: 仍为 {cur_active}")
                except Exception as e:
                    print(f"[iv_smile] ⚠️ 14:55 合约检查异常: {e}")

            # 休盘时段：跳过compute_once，避免用datetime.now()算T导致IV虚高
            if _is_trading_hours():
                compute_once()
                offhours_t_counter = 0  # 开盘重置
            else:
                # 休盘边界（11:30/15:00/23:00）不重算IV/SVI，只复制最后有效状态补齐收盘快照
                _check_and_save_close_state()
                offhours_t_counter += 1
                if offhours_t_counter >= 60:  # 60 × 1分钟 = 1小时
                    _refresh_t_offhours()
                    offhours_t_counter = 0
            counter += 1

            # 每15分钟持久化一次快照（每刻钟整点：0,15,30,45分钟）
            now = datetime.now()
            current_15min = (now.hour * 60 + now.minute) // 15
            if current_15min != _last_snapshot_minute:
                _save_all_snapshots()
                _last_snapshot_minute = current_15min

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
    from flask import render_template, jsonify, request

    @app.after_request
    def _no_cache_iv_smile_apis(response):
        """iv_smile 相关 API 永远不缓存：避免浏览器/代理保留过期 JSON
        （如 prev_timestamp、基准合约等关键字段刷新不及时）"""
        try:
            if request.path.startswith('/api/iv_smile/') or request.path == '/api/iv_smile/curve':
                response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
                response.headers['Pragma'] = 'no-cache'
                response.headers['Expires'] = '0'
        except Exception:
            pass
        return response

    @app.route('/iv_smile')
    def iv_smile_page():
        return render_template('iv_smile.html')

    @app.route('/api/iv_smile/status')
    def iv_api_status():
        from datetime import datetime as _dt_status
        with _state['lock']:
            # v2.11.47+: status 返回前同步 last_update,避免盘后/夜盘 compute_once 不跑导致
            # last_update 卡在 close_state 启动时恢复的旧值。S/T 等字段可能通过其他路径
            # (aksashare校正/夜间tqsdk_loop心跳)被更新,但 last_update 没跟,用户看到"最后更新 14:59"误以为停刷新。
            # 用 now 强制更新到本次返回的时刻,精度足够(分钟级,前端只显示到秒)。
            try:
                _state['last_update'] = _dt_status.now().isoformat()
            except Exception:
                pass
            # 返回快照时间点列表（用于ATM走势图）
            # 过滤掉无数据的空快照key（如 'night' 锚点），避免排序/取值时异常
            valid_keys = [k for k in _interval_snapshots if _interval_snapshots[k].get('smooth')]
            snapshot_times = sorted(valid_keys,
                                   key=lambda k: (int(k.replace(':', '')), k))
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
                'rate_src': _state.get('rate_src', 'unknown'),
                'active_contract': _state.get('active_contract'),
                'snapshot_times': snapshot_times,  # 格式: ["09:00","09:15",...]
                'reconnect_count': _tqsdk_reconnect_count,
            })

    @app.route('/api/iv_smile/curve')
    def iv_api_curve():
        _ensure_today_close_baseline_after_21()
        """
        返回当前曲线 + 上一快照曲线（用于对比）。
        逻辑：取快照中最新时间点作为当前，上一时间点作为对比基准。
        不依赖"当前时间对应哪个槽"——服务重启后快照仍然是正确的历史顺序。
        """
        with _state['lock']:
            # 按时间顺序排列所有快照
            all_keys = sorted(_interval_snapshots.keys(),
                             key=lambda k: (int(k.replace(':', '')), k))

            # 取最新和次新两个时间点
            if len(all_keys) < 2:
                # 只有一个快照：查一下昨日快照中是否有更早的时间点可以对比
                # 尝试加载昨日的快照，取其最后一个时间点作为prev（用于有意义的对比）
                prev_key_from_yesterday = None
                if len(all_keys) == 1:
                    # 当前只有一个时间点，尝试从昨日快照补充更早的时间点
                    yesterday_str = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
                    y_path = _get_snapshot_path(yesterday_str)
                    if os.path.exists(y_path):
                        try:
                            with open(y_path, 'r', encoding='utf-8') as f:
                                y_payload = json.load(f)
                            y_snaps = y_payload.get('snapshots', {})
                            if y_snaps:
                                y_keys = sorted(y_snaps.keys(),
                                               key=lambda k: (int(k.replace(':', '')), k))
                                if y_keys:
                                    prev_key_from_yesterday = y_keys[-1]  # 取昨日最后时间点
                        except Exception:
                            pass

                if prev_key_from_yesterday:
                    # 冷启动但有昨日数据可用：将prev指向昨日快照，同时标记冷启动
                    latest_key = all_keys[0] if all_keys else None
                    # prev_key 指向昨日快照，不指向当前
                    prev_key = prev_key_from_yesterday
                    # 从昨日快照读取prev_smooth/prev_raw
                    yesterday_str = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
                    y_path = _get_snapshot_path(yesterday_str)
                    with open(y_path, 'r', encoding='utf-8') as f:
                        y_payload = json.load(f)
                    y_snaps = y_payload.get('snapshots', {})
                    prev_snap = y_snaps.get(prev_key, {})
                    prev_smooth = prev_snap.get('smooth', {})
                    prev_raw = prev_snap.get('raw', {})
                    is_cold_start_fallback = True   # 仍是冷启动，但prev有历史数据
                    using_night_fallback = True   # 标记为昨夜盘兜底
                else:
                    # 真正冷启动（只有当前时间点，无昨日数据）：prev无意义
                    latest_key = all_keys[0] if all_keys else None
                    prev_key = None   # 明确设为None，避免prev_smooth和smooth相同
                    prev_smooth = {}
                    prev_raw = {}
                    is_cold_start_fallback = True
                    using_night_fallback = False
            else:
                latest_key = all_keys[-1]
                prev_key = all_keys[-2]
                prev_snap = _interval_snapshots.get(prev_key, {})
                prev_smooth = prev_snap.get('smooth', {})
                prev_raw = prev_snap.get('raw', {})
                is_cold_start_fallback = False
                using_night_fallback = False
                if prev_key and ':' in prev_key:
                    h = int(prev_key.split(':')[0])
                    using_night_fallback = (h >= 21)

            # 从当前状态取 raw/smooth（compute_once 最新结果）
            raw = _state.get('smile_raw', {})
            smooth = _state.get('smile_smooth', {})
            # X 轴只暴露 raw 实际有数据的档（100 增量）；smile_smooth 里的 50 增量插值点
            # 只用于平滑曲线本身，不在 X 轴上造出 6350/6450/6550 等无 raw 数据的档
            strikes = sorted(raw.keys(), key=lambda x: float(x)) if raw else sorted(smooth.keys(), key=lambda x: float(x))

            # 持仓数据（当前 strike_oi）
            strike_oi = _state.get('strike_oi', {})

            # 前次曲线：与 alert_data/gex 端点完全对齐的基准选择逻辑。
            # - 昨日 15:00 _close_baseline（人工注入或自动）在今天 21:00 前有效。
            # - 今日 15:00 _close_baseline 在 21:00 后才自动切入。
            # - 若 _close_baseline 为空/合约不匹配/时间窗不符合，再兜底 _prev_day_baseline。
            now_dt = datetime.now()
            cb = _close_baseline
            close_baseline = None
            cb_eligible = False
            if cb and cb.get('smooth'):
                cb_contract = cb.get('contract')
                cur_contract = _state.get('active_contract')
                contract_match = (not cb_contract or not cur_contract or cb_contract == cur_contract)
                cb_ts = cb.get('ts') or cb.get('timestamp') or ''
                if contract_match and cb_ts:
                    try:
                        cb_date = datetime.fromisoformat(cb_ts[:10] if len(cb_ts) >= 10 else cb_ts).date()
                        today = now_dt.date()
                        # ⚠️ 夜盘守卫 + 跨节假日守卫：
                        # - cb_date == today: 今日15:00写入的cb，全天有效（21:00前后都用）
                        # - cb_date < today 且 has_night: 历史基准在有效夜盘日生效（含节后首日）
                        # - cb_date > today: 异常（未来），忽略
                        # 这覆盖了三种情况：
                        #   (a) 节前最后一天 21:00 后 cb_date==today，has_night=False → 用今日cb（已是当日最终态）
                        #   (b) 节后首日 21:00 后 cb_date<today（如6/18→6/22），has_night=True → 切到节前最后日cb
                        #   (c) 节假日中 cb_date<today 且 has_night=False → 仍走历史cb（不切换）
                        # v2.11.38+ 切换原则：
                        # - 今日 15:00 已过 → 用今日 cb（today）
                        # - 节后首日 9:00 早盘开盘后 → 用节前最后交易日
                        # - 有夜盘的交易日 21:00 后 → 用今日 cb
                        # - 其他时段 → 用上一交易日
                        # cb_date == _get_expected_baseline_date(now) 即为有效
                        cb_eligible = _cb_should_apply(cb_date, now_dt)
                    except Exception:
                        pass

            if cb_eligible:
                close_baseline = cb
                prev_smooth = close_baseline.get('smooth', {})
                prev_raw = close_baseline.get('raw', {})
            else:
                prev_smooth = _prev_day_baseline.get('smooth', {}) if _prev_day_baseline else {}
                prev_raw = _prev_day_baseline.get('raw', {}) if _prev_day_baseline else {}
                if prev_smooth:
                    ts = _prev_day_baseline.get('timestamp', '')[:19]
                    # 仅首次打印，避免刷屏（通过prev_key是否已设来控制）
            prev_key = '15:00收盘' if prev_smooth else None

            # ---- 前次基准smooth直接使用快照原始值 ----
            # 快照里的smooth是当时BS反算+SVI拟合的结果,直接反映当时市场IV水平。
            # 不要用SVI参数重算——因为快照的raw IV和smooth都是用当时的T反算的,
            # 属于同一体系,直接对比方向是正确的。
            # (之前的重算逻辑会因为前后T值不同导致方向错误)

            # 前次ATM：优先取已选中的前次基准，其次从futures_price/S计算
            prev_atm_strike = None
            bl = close_baseline if close_baseline and (close_baseline.get('atm_strike') or close_baseline.get('S')) else _prev_day_baseline
            if bl:
                if bl.get('atm_strike'):
                    prev_atm_strike = int(bl['atm_strike'])
                elif bl.get('futures_price'):
                    prev_atm_strike = round(float(bl['futures_price']) / 100) * 100
                elif bl.get('S'):
                    prev_atm_strike = round(bl['S'] / 100) * 100

            curve_data = []
            for k in strikes:
                entry = {'strike': int(k)}
                if k in raw:
                    rv = raw[k]
                    if isinstance(rv, dict):
                        entry['raw_C'] = rv.get('C')
                        entry['raw_P'] = rv.get('P')
                        vals = [v for v in rv.values() if v and not np.isnan(v)]
                        entry['raw_avg'] = float(np.mean(vals)) if vals else None
                    elif isinstance(rv, (int, float)) and not np.isnan(rv):
                        entry['raw_C'] = rv
                        entry['raw_P'] = rv
                        entry['raw_avg'] = float(rv)
                if k in smooth:
                    entry['smooth'] = smooth[k]
                # 持仓数据（来自快照中的 strike_oi）
                if k in strike_oi:
                    entry['call_oi'] = strike_oi[k].get('C', 0) or 0
                    entry['put_oi'] = strike_oi[k].get('P', 0) or 0
                # 前次曲线（15:00收盘基准）
                k_str = str(k)
                if prev_smooth and k_str in prev_smooth:
                    entry['smooth_prev'] = prev_smooth[k_str]
                    entry['prev_avg'] = prev_smooth[k_str]
                # 线性插值兜底：当前K在前次基准中没值时，用左右邻近K线性插值
                # 解决"前次基准曲线因K范围不匹配而断开"的问题
                elif prev_smooth and k is not None:
                    k_int = int(k)
                    k_ints_sorted = sorted(int(kk) for kk in prev_smooth.keys())
                    # 找左右最近的K
                    left = None; right = None
                    for kk in k_ints_sorted:
                        if kk <= k_int:
                            left = kk
                        elif kk > k_int and right is None:
                            right = kk
                            break
                    if left is not None and right is not None:
                        # 仅在 prev_smooth 覆盖范围内才插值；超出首末两档的恒定延伸会产生
                        # 误导性的平台（5000-5300 全是 0.3541、7500-8100 全是 0.3666），
                        # 让用户误以为前次曲线有那些档的数据
                        entry['smooth_prev'] = float(v_interp)
                        entry['prev_avg'] = float(v_interp)
                    # 超出 prev_smooth 首/末端的档：不填 prev_smooth_prev，让前次曲线在那些
                    # 区域自然断开（ECharts scatter 模式下会显示 gap）
                # 前次原始 Call/Put IV
                if prev_raw and k_str in prev_raw:
                    pv = prev_raw[k_str]
                    if isinstance(pv, dict):
                        entry['raw_C_prev'] = pv.get('C')
                        entry['raw_P_prev'] = pv.get('P')
                    elif isinstance(pv, (int, float)):
                        # 快照中 raw 可能已是平均值（float），无C/P区分
                        entry['raw_C_prev'] = pv
                        entry['raw_P_prev'] = pv
                # 隐波变化（带符号）：当前smooth - 15:00收盘smooth
                # 不能取 abs，否则降波也会被显示成“剧升”。
                if 'smooth' in entry and 'smooth_prev' in entry:
                    entry['iv_change'] = round(entry['smooth'] - entry['smooth_prev'], 4)
                curve_data.append(entry)

        # 格式化prev_timestamp（更友好）
        if prev_smooth:
            close_ts = close_baseline.get('ts', '') if close_baseline else ''
            if close_ts:
                # 当天运行时记录的 _close_baseline
                try:
                    prev_dt = datetime.fromisoformat(close_ts)
                    prev_ts_display = prev_dt.strftime('%m/%d %H:%M')
                except:
                    prev_ts_display = close_ts[5:16]
            elif _prev_day_baseline:
                # 从 _prev_day_baseline 取时间戳
                ts = _prev_day_baseline.get('timestamp', '')
                if ts:
                    try:
                        prev_dt = datetime.fromisoformat(ts)
                        prev_ts_display = prev_dt.strftime('%m/%d %H:%M')
                    except:
                        prev_ts_display = ts[5:16]
                else:
                    prev_ts_display = '15:00收盘'
            else:
                prev_ts_display = '15:00收盘'
        else:
            prev_ts_display = None

        # 如果用了昨夜盘兜底，timestamp改为"昨收盘"
        if using_night_fallback and not prev_ts_display:
            prev_ts_display = '昨收盘'
        # 冷启动兜底时（无当日历史对比，但可能有昨夜盘数据）:
        # 若 prev_key 指向有效历史数据，仍显示时间标签
        # 只有 prev_key 为 None（真正无历史数据）时才清除时间标签
        if is_cold_start_fallback and prev_key is None:
            prev_ts_display = None

        # SVI 参数（从全局状态获取，即使冷启动也有快照中恢复的值）
        svi = _state.get('svi_params', {})
        skew_audit = None
        if isinstance(svi, dict) and svi.get('a') is not None:
            skew_val = svi.get('skew')
            rho_val = svi.get('rho')
            curv_val = svi.get('curvature')
            skew_abs = abs(float(skew_val)) if skew_val is not None else None
            if skew_abs is None:
                skew_label = '未知'
            elif skew_abs < 0.25:
                skew_label = '轻微偏斜'
            elif skew_abs < 0.75:
                skew_label = '中等偏斜'
            else:
                skew_label = '显著偏斜'
            skew_audit = {
                'status': 'ok',
                'formula': 'skew = dσ/dk|ATM = dw/dk / (2*sqrt(w*T)), k=ln(K/F)',
                'meaning': '展示的 skew 是ATM附近隐含波动率曲线一阶斜率，不是SVI原始参数rho；rho只控制左右偏斜方向。',
                'current_skew': skew_val,
                'current_rho': rho_val,
                'current_curvature': curv_val,
                'label': skew_label,
                'interpretation': f"当前skew={skew_val:.3f}，rho={rho_val:.3f}，口径判断为{skew_label}；负值表示左侧/低行权价方向隐波相对更高。" if skew_val is not None and rho_val is not None else None,
                'recommendation': '保留当前公式；前端/研报展示时标注为“ATM偏度(dσ/dlnK)”以避免与rho或翼部偏斜混淆。',
            }

        # 实时计算 max_pain（与 GEX API 一致，避免用 _state 中过时的缓存值）
        realtime_max_pain = _state.get('max_pain')
        try:
            oi_data = _state.get('strike_oi', {})
            if oi_data:
                realtime_max_pain = calc_max_pain(oi_data, _state.get('futures_price', 0))
                if realtime_max_pain is None:
                    realtime_max_pain = _state.get('max_pain')
        except Exception:
            pass

        # 基于期权链同源标的价 + 当前ATM IV计算到期价格波动置信区间。
        # 注意：这里必须使用 _state['futures_price']（期权链/GEX/IV口径），不能使用首页TA609盘面主力K线价。
        curve_T = (_calc_T_trading_days(_state['expiry'])
                   if _state.get('expiry') else _state.get('T'))
        confidence_band = None
        try:
            band_underlying = float(_state.get('futures_price') or 0)
            atm_iv = None
            if isinstance(svi, dict) and svi.get('atm_vol') is not None:
                atm_iv = float(svi.get('atm_vol'))
            if (not atm_iv or atm_iv <= 0) and _state.get('atm_strike') is not None:
                atm_key = _state.get('atm_strike')
                smooth = _state.get('smile_smooth') or {}
                for k in (atm_key, str(atm_key), int(atm_key) if isinstance(atm_key, float) else atm_key):
                    if k in smooth and smooth.get(k) is not None:
                        atm_iv = float(smooth.get(k))
                        break
            T_val = float(curve_T or 0)
            if band_underlying > 0 and atm_iv and atm_iv > 0 and T_val > 0:
                sigma_move_pct = atm_iv * (T_val ** 0.5)
                sigma_move = band_underlying * sigma_move_pct
                def _band(z, level):
                    move = sigma_move * z
                    return {
                        'level': level,
                        'z': z,
                        'lower': round(band_underlying - move, 1),
                        'upper': round(band_underlying + move, 1),
                        'move': round(move, 1),
                        'move_pct': round(sigma_move_pct * z * 100, 2),
                    }
                confidence_band = {
                    'status': 'ok',
                    'underlying_price': band_underlying,
                    'atm_iv': atm_iv,
                    'T': T_val,
                    'expiry': _state['expiry'].isoformat() if _state.get('expiry') else None,
                    'horizon': 'to_expiry',
                    'formula': 'S ± z * S * ATM_IV * sqrt(T)',
                    'source': 'iv_smile_curve.option_underlying_price + svi_params.atm_vol',
                    'bands': {
                        '68': _band(1.0, '约68%/1σ'),
                        '95': _band(1.96, '约95%/1.96σ'),
                    },
                }
        except Exception as e:
            confidence_band = {'status': 'error', 'error': str(e)}

        return jsonify({
            'futures_price': _state['futures_price'],
            'underlying_price': _state['futures_price'],   # 标的价格（前端指标栏用）
            'ref_strike': _state.get('ref_strike'),
            'max_pain': realtime_max_pain,
            'atm_strike': _state['atm_strike'],
            'prev_atm_strike': prev_atm_strike,
            'last_update': _state['last_update'],
            'expiry': _state['expiry'].isoformat() if _state.get('expiry') else None,
            'T': curve_T,  # 交易日T
            'svi_params': svi,
            'skew_audit': skew_audit,
            'confidence_band': confidence_band,
            'curve': curve_data,
            'prev_timestamp': prev_ts_display,      # 格式: "09:30" 或 "昨收盘"
            'prev_interval_key': prev_key,          # 格式: "09:30"
            'current_interval_key': latest_key,   # 格式: "10:45"
            'is_trading_hours': _is_trading_hours(),  # 当前是否处于交易时段（前端避免休盘显示“当前升波”）
            'using_night_fallback': using_night_fallback,  # 是否用了昨夜盘兜底
            'is_cold_start_fallback': is_cold_start_fallback,  # 冷启动兜底（prev与current相同，无对比意义）
        })

    @app.route('/api/iv_smile/trigger', methods=['POST'])
    def iv_api_trigger():
        from flask import request
        force = request.args.get('force', '0') in ('1', 'true')
        success = compute_once(force=force)
        # force模式下计算成功后立刻保存快照
        if force and success:
            _save_all_snapshots()
        return jsonify({'success': success, 'forced': force})

    @app.route('/api/iv_smile/inject_oi', methods=['POST'])
    def iv_api_inject_oi():
        """手工注入当前持仓数据（不影响基准，仅更新当前OI用于计算变化量）"""
        from flask import request
        data = request.get_json() or {}
        # 格式: {"4450": {"C": 6, "P": 1040}, "6000": {"C": 2749, "P": 37500}, ...}
        if not data:
            return jsonify({'success': False, 'error': 'empty data'}), 400
        with _state['lock']:
            _state['strike_oi'] = {str(k): v for k, v in data.items()}
        # 用新OI重算最大痛点
        S = _state.get('futures_price', 0)
        if S:
            oi_int_keys = {int(k): v for k, v in data.items()}
            new_mp = calc_max_pain(oi_int_keys, S)
            if new_mp:
                _state['max_pain'] = new_mp
                print(f"[iv_smile] 📥 OI注入后重算最大痛点: {new_mp}")
        # 同时更新到最新快照中（确保持久化，重启不丢失）
        now = datetime.now()
        interval_key = get_interval_key(now)
        oi_dict = {str(k): v for k, v in data.items()}
        if interval_key and interval_key in _interval_snapshots:
            _interval_snapshots[interval_key]['strike_oi'] = oi_dict
        else:
            # 非交易时段或无当前快照，写入最新的一个快照
            if _interval_snapshots:
                latest_key = max(_interval_snapshots.keys())
                _interval_snapshots[latest_key]['strike_oi'] = oi_dict
        _save_all_snapshots()
        print(f"[iv_smile] 📥 手工注入OI: {len(data)}档")
        return jsonify({'success': True, 'count': len(data)})

    @app.route('/api/iv_smile/save_close_state_now', methods=['POST'])
    def iv_api_save_close_state_now():
        """补打当前时刻作为 15:00 收盘快照。

        场景: 服务在 15:00 之后的 2 分钟窗口外才被触发（比如调度器卡顿、
        或者当前是盘后手工补打），手动写一次 close_state.json + 内存 _close_baseline
        + 15:00 interval 槽。**不**写入 _close_state_saved_slots（避免 23:00 重复写）。
        """
        from flask import request
        data = request.get_json(silent=True) or {}
        close_point = data.get('close_point', '15:00')  # 默 15:00
        try:
            # 1. 写 close_state.json
            # v2.11.54+: 手工补盘（save_close_state_now）是"补今日 15:00"，不应影响 prev_baseline.json
            # （prev_baseline.json 由 21:00 切换逻辑写入今日 15:00）
            _save_close_state(close_point=close_point)
            # 2. 同步内存 _close_baseline (用 _state 当前值)
            global _close_baseline
            # v2.11.50+ 语义校准：ts 用 close_point 对应的收盘时刻（15:00 = 15:00:00），不用 datetime.now()
            # 原因：盘后补打时 datetime.now() 是 17:21，但语义收盘点是 15:00，
            # 前端 label 显示 "06/18 15:00" 而不是 "06/18 17:21"，避免误读。
            _now = datetime.now()
            _semantic_ts = f"{_now.strftime('%Y-%m-%d')}T{close_point}:00"
            _close_baseline = {
                'smooth': dict(_state.get('smile_smooth') or _last_valid.get('smile_smooth') or {}),
                'raw': dict(_state.get('smile_raw') or _last_valid.get('smile_raw') or {}),
                'strike_oi': dict(_state.get('strike_oi') or _last_valid.get('strike_oi') or {}),
                'strike_vol': dict(_state.get('strike_vol') or _last_valid.get('strike_vol') or {}),
                'S': _state.get('futures_price') or _last_valid.get('futures_price'),
                'ts': _semantic_ts,
                'contract': _state.get('active_contract'),
                'expiry': _state.get('expiry').isoformat() if _state.get('expiry') else None,
                'close_point': close_point,
            }
            # 3. 补 15:00 边界槽
            _copy_close_state_to_interval_snapshot(int(close_point.split(':')[0]),
                                                  int(close_point.split(':')[1]),
                                                  datetime.now())
            _save_all_snapshots()
            print(f"[iv_smile] ✅ 手工补打收盘快照: close_point={close_point}")
            return jsonify({
                'success': True,
                'close_point': close_point,
                'F': _state.get('futures_price'),
                'ATM': _state.get('atm_strike'),
                'MP': _state.get('max_pain'),
                'OI_strikes': len(_close_baseline['strike_oi']),
                'smooth_strikes': len(_close_baseline['smooth']),
            })
        except Exception as e:
            print(f"[iv_smile] ❌ 手工补打收盘快照失败: {e}")
            import traceback; traceback.print_exc()
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/iv_smile/inject_baseline', methods=['POST'])
    def iv_api_inject_baseline():
        """手工注入收盘基准（完整T型数据：smooth IV + raw C/P IV + 持仓OI）"""
        global _close_baseline
        from flask import request
        data = request.get_json() or {}

        # 兼容旧格式（只有 strike_ivs）
        strike_ivs = data.get('strike_ivs', {})
        # 新格式：完整T型数据
        rows = data.get('rows', [])
        ts = data.get('ts', '2026-06-04T15:00:00')
        S = data.get('S', 0)

        if rows:
            # 新格式：从T型表格行构建完整基准
            smooth = {}
            raw = {}
            strike_oi = {}
            for r in rows:
                k = str(r['strike'])
                iv = r.get('iv', 0) or 0
                smooth[k] = float(iv) / 100.0  # 百分比转小数
                raw[k] = {
                    'C': float(r.get('iv_call', iv)) / 100.0,
                    'P': float(r.get('iv_put', iv)) / 100.0,
                }
                strike_oi[k] = {
                    'C': int(r.get('oi_call', 0)),
                    'P': int(r.get('oi_put', 0)),
                }
            _close_baseline = {
                'smooth': smooth,
                'raw': raw,
                'strike_oi': strike_oi,
                'S': float(S),
                'ts': ts,
                'close_point': '15:00',  # 手工注入的语义上就是 15:00 收盘基准
            }
            print(f"[iv_smile] ✅ 注入收盘基准(完整): {len(smooth)}档 OI={len(strike_oi)}档 ts={ts}")
            return jsonify({'success': True, 'count': len(smooth), 'has_oi': True, 'ts': ts})

        elif strike_ivs:
            # 旧格式兼容
            _close_baseline = {
                'smooth': {str(k): float(v) for k, v in strike_ivs.items()},
                'raw': {},
                'strike_oi': {},
                'S': float(S),
                'ts': ts,
                'close_point': '15:00',
            }
            print(f"[iv_smile] ✅ 注入收盘基准(仅IV): {len(strike_ivs)}档 ts={ts}")
            return jsonify({'success': True, 'count': len(strike_ivs), 'has_oi': False, 'ts': ts})

        return jsonify({'success': False, 'error': '缺少rows或strike_ivs'})

    @app.route('/api/iv_smile/alert/config', methods=['GET', 'POST'])
    def iv_api_alert_config():
        """查询/设置IV报警阈值和WebHook URL"""
        global _IV_ALERT_THRESHOLD, _IV_ALERT_COOLDOWN, _FEISHU_WEBHOOK
        from flask import request
        if request.method == 'POST':
            data = request.get_json() or {}
            if 'threshold' in data:
                _IV_ALERT_THRESHOLD = float(data['threshold'])
            if 'cooldown' in data:
                _IV_ALERT_COOLDOWN = int(data['cooldown'])
            if 'webhook' in data:
                _FEISHU_WEBHOOK = str(data['webhook'])
            return jsonify({'ok': True, 'threshold': _IV_ALERT_THRESHOLD,
                            'cooldown': _IV_ALERT_COOLDOWN,
                            'webhook_set': bool(_FEISHU_WEBHOOK)})
        return jsonify({
            'threshold': _IV_ALERT_THRESHOLD,
            'cooldown': _IV_ALERT_COOLDOWN,
            'webhook_set': bool(_FEISHU_WEBHOOK),
        })

    @app.route('/api/iv_smile/alert/test', methods=['POST'])
    def iv_api_alert_test():
        """发送测试飞书消息"""
        if not _FEISHU_WEBHOOK:
            return jsonify({'ok': False, 'error': '未配置 WebHook'})
        try:
            requests.post(_FEISHU_WEBHOOK,
                          json={'msg_type': 'text',
                                'content': {'text': '【PTA期权IV报警】测试消息\n期货价: 6500  最大痛点: 6500\n测试档位: 6500档: 22.0%→28.0% (↑6.0%) ⭐'}},
                          timeout=10)
            return jsonify({'ok': True})
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)})


    @app.route('/api/iv_smile/_debug_baseline')
    def iv_api_debug_baseline():
        """临时 debug: 返回 _close_baseline 关键字段（仅 debug 用）"""
        with _state['lock']:
            cb = dict(_close_baseline) if _close_baseline else {}
        cb['strike_oi_6000'] = cb.get('strike_oi', {}).get('6000') or cb.get('strike_oi', {}).get(6000)
        cb['strike_oi_6000_str'] = str(cb.get('strike_oi', {}).get('6000'))
        cb['_prev_day_baseline_oi_6000'] = (_prev_day_baseline or {}).get('strike_oi', {}).get('6000')
        cb['_state_strike_oi_6000'] = _state.get('strike_oi', {}).get('6000')
        return jsonify(cb)

    @app.route('/api/iv_smile/_debug_alert_full')
    def iv_api_debug_alert_full():
        """临时 debug: 实际执行 alert_data 端点计算（不输出 rows，只输出关键变量）"""
        with _state['lock']:
            strike_oi = _state.get('strike_oi', {})
            strike_vol = _state.get('strike_vol', {})
            smile_raw = _state.get('smile_raw', {})
            smile_smooth = _state.get('smile_smooth', {})
        cur_contract = _state.get('active_contract')
        baseline_ts_str = _close_baseline.get('ts', '') if _close_baseline else ''
        from datetime import datetime as _dt
        baseline_is_today = False
        baseline_is_postclose_yesterday = False
        baseline_date = None
        if baseline_ts_str:
            try:
                bd = _dt.fromisoformat(baseline_ts_str).date()
                baseline_date = bd
                baseline_is_today = (bd == _dt.now().date())
                yd = (_dt.now() - __import__('datetime').timedelta(days=1)).date()
                baseline_is_postclose_yesterday = (bd == yd and _dt.now().hour < 9)
            except Exception:
                pass
        baseline_contract_match = (cur_contract and _close_baseline.get('contract') == cur_contract) if _close_baseline else False
        # v2.11.38+ 切换原则（统一判断）
        baseline_is_valid = bool(_close_baseline and baseline_contract_match
                                  and baseline_date
                                  and _cb_should_apply(baseline_date, _dt.now()))
        if _close_baseline and baseline_is_valid:
            close_baseline = _close_baseline
        else:
            # v2.11.38+: baseline_is_valid 已经统一判断，这里直接 fallback
            close_baseline = {}
        b_smooth = close_baseline.get('smooth', {}) if close_baseline else {}
        b_raw = close_baseline.get('raw', {}) if close_baseline else {}
        b_oi = close_baseline.get('strike_oi', {}) if close_baseline else {}
        b_vol = close_baseline.get('strike_vol', {}) if close_baseline else {}
        has_baseline = bool(b_smooth)
        if (not has_baseline or not b_oi) and _prev_day_baseline:
            if not has_baseline:
                b_smooth = _prev_day_baseline.get('smooth', {})
                b_raw = _prev_day_baseline.get('raw', {})
            if not b_oi:
                snap_oi = _prev_day_baseline.get('strike_oi', {})
                if snap_oi:
                    b_oi = snap_oi
            if not b_vol:
                b_vol = _prev_day_baseline.get('strike_vol', {})
            has_baseline = bool(b_smooth)
        # 模拟 line 3185-3234
        out = {}
        for k in ['5400', '5900', '6000', '6100', '6500', '6700', '7400']:
            if k not in b_oi and k not in b_raw and k not in b_smooth:
                continue
            b_oi_s = b_oi.get(k) or b_oi.get(int(k)) or {'C': 0, 'P': 0}
            b_vol_s = b_vol.get(k) or b_vol.get(int(k)) or {'C': 0, 'P': 0}
            b_raw_s = b_raw.get(k) or b_raw.get(int(k)) or {}
            b_sm = b_smooth.get(k) or b_smooth.get(int(k)) or 0
            cur_oi = strike_oi.get(k) or strike_oi.get(int(k)) or {'C': 0, 'P': 0}
            cur_vol = strike_vol.get(k) or strike_vol.get(int(k)) or {'C': 0, 'P': 0}
            oi_call_b = int(b_oi_s.get('C', 0))
            oi_put_b = int(b_oi_s.get('P', 0))
            iv_c_b_raw = b_raw_s.get('C') if isinstance(b_raw_s, dict) else None
            iv_p_b_raw = b_raw_s.get('P') if isinstance(b_raw_s, dict) else None
            iv_c_b = (iv_c_b_raw * 100) if iv_c_b_raw else ((b_sm or 0) * 100)
            out[k] = {
                'b_oi_s': b_oi_s,
                'b_vol_s': b_vol_s,
                'b_raw_s': b_raw_s,
                'b_sm': b_sm,
                'cur_oi': cur_oi,
                'cur_vol': cur_vol,
                'oi_call_b': oi_call_b,
                'oi_put_b': oi_put_b,
                'iv_c_b_raw': iv_c_b_raw,
                'iv_p_b_raw': iv_p_b_raw,
                'iv_c_b': iv_c_b,
                'iv_p_b': (iv_p_b_raw * 100) if iv_p_b_raw else ((b_sm or 0) * 100),
            }
        return jsonify({
            'baseline_ts_str': baseline_ts_str,
            'baseline_is_today': baseline_is_today,
            'baseline_is_postclose_yesterday': baseline_is_postclose_yesterday,
            'baseline_contract_match': baseline_contract_match,
            'cur_contract': cur_contract,
            'b_smooth_档数': len(b_smooth),
            'b_oi_档数': len(b_oi),
            'b_vol_档数': len(b_vol),
            'has_baseline': has_baseline,
            'sample_rows': out,
        })
    def iv_api_debug_alert_paths_unused():
        baseline_ts_str = _close_baseline.get('ts', '') if _close_baseline else ''
        baseline_date = None
        if baseline_ts_str:
            try:
                from datetime import datetime as _dt
                baseline_date = _dt.fromisoformat(baseline_ts_str).date()
            except Exception:
                pass
        baseline_is_today = (baseline_date == datetime.now().date()) if baseline_date else False
        from datetime import timedelta as _td
        yesterday = (datetime.now() - _td(days=1)).date()
        baseline_is_postclose_yesterday = (baseline_date == yesterday and datetime.now().hour < 9) if baseline_date else False
        baseline_contract_match = (cur_contract and _close_baseline.get('contract') == cur_contract) if _close_baseline else False
        # v2.11.38+ 切换原则（统一判断）
        baseline_is_valid = bool(_close_baseline and baseline_contract_match
                                  and baseline_date
                                  and _cb_should_apply(baseline_date, datetime.now()))
        enter_close_branch = baseline_is_valid
        # 模拟 line 3067-3071
        if enter_close_branch:
            close_baseline = _close_baseline
        else:
            close_baseline = {}
        b_smooth = close_baseline.get('smooth', {}) if close_baseline else {}
        b_raw = close_baseline.get('raw', {}) if close_baseline else {}
        b_oi = close_baseline.get('strike_oi', {}) if close_baseline else {}
        b_vol = close_baseline.get('strike_vol', {}) if close_baseline else {}
        # 模拟 line 3078-3085
        snap_oi_6000_before = b_oi.get('6000')
        will_overwrite = bool((not b_smooth or not b_oi) and _prev_day_baseline)
        if will_overwrite:
            if not b_smooth:
                b_smooth = _prev_day_baseline.get('smooth', {})
                b_raw = _prev_day_baseline.get('raw', {})
            if not b_oi:
                b_oi = _prev_day_baseline.get('strike_oi', {})
            if not b_vol:
                b_vol = _prev_day_baseline.get('strike_vol', {})
        return jsonify({
            'cur_contract': cur_contract,
            'baseline_ts_str': baseline_ts_str,
            'baseline_date': str(baseline_date),
            'baseline_is_today': baseline_is_today,
            'baseline_is_postclose_yesterday': baseline_is_postclose_yesterday,
            'baseline_contract_match': baseline_contract_match,
            'enter_close_branch': enter_close_branch,
            'b_smooth_档数': len(b_smooth),
            'b_raw_档数': len(b_raw),
            'b_oi_档数': len(b_oi),
            'b_vol_档数': len(b_vol),
            'b_oi_6000': b_oi.get('6000'),
            'will_overwrite_with_prev': will_overwrite,
            '_prev_day_baseline_oi_6000': (_prev_day_baseline or {}).get('strike_oi', {}).get('6000'),
        })

    @app.route('/api/iv_smile/alert_data')
    def iv_api_alert_data():
        _ensure_today_close_baseline_after_21()
        """
        T型报价+报警数据：对比当日15:00收盘基准，返回带颜色标注级别的完整数据。
        用于前端T型表格颜色标注 + 弹窗声音报警判断。
        """
        now = datetime.now()
        with _state['lock']:
            strike_oi = _state.get('strike_oi', {})
            strike_vol = _state.get('strike_vol', {})
            smile_raw = _state.get('smile_raw', {})
            smile_smooth = _state.get('smile_smooth', {})
            futures_price = _state.get('futures_price')
            max_pain = _state.get('max_pain')

        # 前次基准选择（不破坏 15:00 自动写入 + 21:00 自动切换）：
        # - 若 _close_baseline 是昨日 15:00 且合约匹配：今天 21:00 前持续作为前次基准
        #   （合约切换日人工 TA608 基准就属于此类，不能在 09:00 后被 _prev_day_baseline 顶掉）。
        # - 若 _close_baseline 是今日 15:00 且合约匹配：21:00 后才切入，保持“15:00快照构成21:00切换基础”。
        cur_contract = _state.get('active_contract')
        now_dt = datetime.now()
        baseline_ts_str = _close_baseline.get('ts', '') if _close_baseline else ''
        baseline_is_today = False
        baseline_is_previous_calendar_day = False
        if baseline_ts_str:
            try:
                baseline_date = datetime.fromisoformat(baseline_ts_str).date()
                baseline_is_today = (baseline_date == now_dt.date())
                baseline_is_previous_calendar_day = (baseline_date == (now_dt - timedelta(days=1)).date())
            except Exception:
                pass
        baseline_contract_match = (cur_contract and _close_baseline.get('contract') == cur_contract) if _close_baseline else False

        close_baseline = {}
        if _close_baseline and baseline_contract_match and baseline_date is not None:
            # v2.11.38+ 切换原则（统一判断）
            if _cb_should_apply(baseline_date, now_dt):
                close_baseline = _close_baseline
        b_smooth = close_baseline.get('smooth', {}) if close_baseline else {}
        b_raw = close_baseline.get('raw', {}) if close_baseline else {}
        b_oi = close_baseline.get('strike_oi', {}) if close_baseline else {}
        b_vol = close_baseline.get('strike_vol', {}) if close_baseline else {}
        close_ts = close_baseline.get('ts', '') if close_baseline else ''
        has_baseline = bool(b_smooth)

        # 若 _close_baseline 为空 或 关键字段不完整，从 _prev_day_baseline 取
        if (not has_baseline or not b_oi) and _prev_day_baseline:
            if not has_baseline:
                b_smooth = _prev_day_baseline.get('smooth', {})
                b_raw = _prev_day_baseline.get('raw', {})
                close_ts = _prev_day_baseline.get('timestamp', '')
            if not b_oi:
                snap_oi = _prev_day_baseline.get('strike_oi', {})
                if snap_oi:
                    b_oi = snap_oi
                    print(f"[iv_smile] 📌 alert_data 从前一交易日基准恢复OI smooth={len(b_smooth)}档")
            if not b_vol:
                b_vol = _prev_day_baseline.get('strike_vol', {})
            has_baseline = bool(b_smooth)

        # 用ATM隐波判断波动环境（比全档位均值更准确）
        atm = _state.get('atm_strike')
        atm_iv = smile_smooth.get(atm) or smile_smooth.get(str(atm)) if atm else None
        if not atm_iv:
            vals = list(smile_smooth.values())
            atm_iv = sum(vals) / len(vals) if vals else 0
        iv_t = _get_iv_thresholds(atm_iv)

        # 合并所有行权价（统一为字符串key）
        all_keys = set(str(k) for k in list(strike_oi.keys()) + list(b_oi.keys()) + list(strike_vol.keys()) + list(b_vol.keys()))
        if not all_keys and smile_smooth:
            all_keys = set(str(k) for k in smile_smooth.keys())
            # 补充raw数据
            for k in all_keys:
                if k not in strike_oi:
                    strike_oi[k] = {'C': 0, 'P': 0}
                if k not in b_oi:
                    b_oi[k] = {'C': 0, 'P': 0}
                if k not in strike_vol:
                    strike_vol[k] = {'C': 0, 'P': 0}
                if k not in b_vol:
                    b_vol[k] = {'C': 0, 'P': 0}

        rows = []
        iv_alerts = []  # {'strike': int, 'level': str}
        oi_alerts = []

        for strike in sorted(all_keys, key=lambda x: int(x)):
            cur_oi = strike_oi.get(strike) or strike_oi.get(int(strike)) or {'C': 0, 'P': 0}
            b_oi_s = b_oi.get(strike) or b_oi.get(int(strike)) or {'C': 0, 'P': 0}
            cur_vol = strike_vol.get(strike) or strike_vol.get(int(strike)) or {'C': 0, 'P': 0}
            b_vol_s = b_vol.get(strike) or b_vol.get(int(strike)) or {'C': 0, 'P': 0}

            # IV（strike可能是str，但数据源key可能是int，双查找）
            raw = smile_raw.get(strike) or smile_raw.get(int(strike)) or {}
            sm = smile_smooth.get(strike) or smile_smooth.get(int(strike))

            # B 方案：moneyness > 15% 时强制 IV = None（SVI 外推不可信）
            # 仅过滤 IV，不影响 OI / 成交量 / 行权价显示
            try:
                _mp = abs(int(strike) - futures_price) / futures_price if futures_price else 0
            except Exception:
                _mp = 0
            _iv_overshoot = _mp > 0.15  # 超过 ±15% 视为外推区

            if isinstance(raw, dict):
                # 优先用raw C/P IV，缺失时用smooth IV兜底（深度OTM无成交的档位）
                iv_c_raw = raw.get('C')
                iv_p_raw = raw.get('P')
                iv_c = (iv_c_raw * 100) if iv_c_raw else ((sm or 0) * 100)
                iv_p = (iv_p_raw * 100) if iv_p_raw else ((sm or 0) * 100)
                # None表示真没数据（非零值兜底），0才是"用smooth兜底"——但前端要区分
                # 改为：raw有值用raw，raw无值用smooth；smooth也无值才为None
                if iv_c_raw is None and sm is None:
                    iv_c = None
                if iv_p_raw is None and sm is None:
                    iv_p = None
                # 强制外推区置空（SVI 拟合范围仅 ATM±15%）
                if _iv_overshoot:
                    iv_c = None
                    iv_p = None
            elif isinstance(raw, (int, float)):
                iv_c = raw * 100
                iv_p = raw * 100
                if _iv_overshoot:
                    iv_c = None
                    iv_p = None
            else:
                iv_c = None
                iv_p = None
            b_raw_s = b_raw.get(strike) or b_raw.get(int(strike)) or {}
            if isinstance(b_raw_s, dict):
                b_sm = b_smooth.get(strike) or b_smooth.get(int(strike)) or 0
                iv_c_b_raw = b_raw_s.get('C')
                iv_p_b_raw = b_raw_s.get('P')
                iv_c_b = (iv_c_b_raw * 100) if iv_c_b_raw else ((b_sm or 0) * 100)
                iv_p_b = (iv_p_b_raw * 100) if iv_p_b_raw else ((b_sm or 0) * 100)
                if iv_c_b_raw is None and not b_sm:
                    iv_c_b = None
                if iv_p_b_raw is None and not b_sm:
                    iv_p_b = None
            elif isinstance(b_raw_s, (int, float)):
                # 快照中 raw 可能已是平均值（float）
                iv_c_b = b_raw_s * 100
                iv_p_b = b_raw_s * 100
            else:
                iv_c_b = None
                iv_p_b = None
            b_sm = b_smooth.get(strike) or b_smooth.get(int(strike)) or 0

            # IV变化：close基准 + 报警后同向极值watermark反转。
            # T表颜色仍按close基准；弹窗IV报警必须与同侧OI变化联动。
            iv_chg_close = (sm - b_sm) * 100 if (sm and b_sm) else None
            iv_ref_type = 'close'
            iv_chg = iv_chg_close

            sig_t = iv_t['significant'] * 100   # 转为百分点
            ext_t = iv_t.get('extreme', 999) * 100
            def _iv_level_for(iv_cur, iv_prev):
                if iv_cur is None or iv_prev is None or iv_prev == 0:
                    return ''
                # 脏基准过滤：PTA正常IV多在20-40%，baseline偏离当前1.5倍以上视为脏
                if iv_prev > 60 and iv_cur > 0 and iv_prev > iv_cur * 1.5:
                    return ''
                chg = abs(iv_cur - iv_prev)
                if chg >= ext_t:
                    return 'major'
                if chg >= sig_t:
                    return 'significant'
                return ''
            def _iv_diff(iv_cur, iv_prev):
                return round(iv_cur - iv_prev, 2) if (iv_cur is not None and iv_prev is not None and iv_prev != 0) else None
            def _dir(v):
                if v is None or abs(v) < 1e-9:
                    return None
                return 'up' if v > 0 else 'down'
            def _better_level(a, b):
                if a == 'major' or b == 'major':
                    return 'major'
                if a == 'significant' or b == 'significant':
                    return 'significant'
                return ''

            # close基准：普通“较收盘/前次基准”异动
            iv_call_level_close = _iv_level_for(iv_c, iv_c_b)
            iv_put_level_close = _iv_level_for(iv_p, iv_p_b)
            iv_call_chg_close = _iv_diff(iv_c, iv_c_b)
            iv_put_chg_close = _iv_diff(iv_p, iv_p_b)

            # OI变化（比率）
            def oi_chg_ratio(cur, prv):
                if not prv or prv <= 0:
                    return None
                return (cur - prv) / prv

            oi_call = int(cur_oi.get('C', 0))
            oi_put = int(cur_oi.get('P', 0))
            oi_call_b = int(b_oi_s.get('C', 0))
            oi_put_b = int(b_oi_s.get('P', 0))
            vol_call = int(cur_vol.get('C', 0))
            vol_put = int(cur_vol.get('P', 0))
            vol_call_b = int(b_vol_s.get('C', 0))
            vol_put_b = int(b_vol_s.get('P', 0))

            oi_chg_call = oi_chg_ratio(oi_call, oi_call_b)
            oi_chg_put = oi_chg_ratio(oi_put, oi_put_b)
            vol_chg_call = oi_chg_ratio(vol_call, vol_call_b)
            vol_chg_put = oi_chg_ratio(vol_put, vol_put_b)

            # 兜底：baseline raw IV可能缺失，转float供输出
            iv_c_b = float(iv_c_b) if iv_c_b is not None else None
            iv_p_b = float(iv_p_b) if iv_p_b is not None else None

            # OI颜色级别（当前OI归零排除：到期清零不是异动）
            def oi_level(chg, base_oi, cur_oi):
                if chg is None or base_oi <= 0:
                    return ''
                if cur_oi <= 0:
                    return ''
                t = _get_oi_thresholds(base_oi)
                abs_c = abs(chg)
                if abs_c >= t['sigLow']:
                    return 'major' if abs_c >= t.get('extreme', 999) else 'significant'
                return ''

            oi_call_level_close = oi_level(oi_chg_call, oi_call_b, oi_call)
            oi_put_level_close = oi_level(oi_chg_put, oi_put_b, oi_put)

            # 报警后同向极值watermark：不是“上次报警点”，而是报警后原方向走出的最高/最低点。
            def iv_watermark_level(strike_key, side, cur_iv, close_chg, close_level):
                key = f"{strike_key}_{side}"
                st = _iv_alert_watermarks.get(key)
                close_dir = _dir(close_chg)
                # 首次close报警建立趋势与极值；之后同向继续刷新极值
                if st is None:
                    if close_level and close_dir:
                        _iv_alert_watermarks[key] = {'trend': close_dir, 'extreme': cur_iv}
                    return '', None
                trend = st.get('trend')
                extreme = st.get('extreme')
                if cur_iv is None or extreme is None or not trend:
                    return '', None
                # 同向延伸：刷新最高/最低，不报警
                if trend == 'up' and cur_iv >= extreme:
                    st['extreme'] = cur_iv
                    return '', None
                if trend == 'down' and cur_iv <= extreme:
                    st['extreme'] = cur_iv
                    return '', None
                # 从最高/最低反向回撤/反弹
                dyn_chg = _iv_diff(cur_iv, extreme)
                dyn_level = _iv_level_for(cur_iv, extreme)
                if dyn_level and _dir(dyn_chg) and _dir(dyn_chg) != trend:
                    # 反转触发后切换趋势，并以当前值作为新方向的初始极值
                    st['trend'] = _dir(dyn_chg)
                    st['extreme'] = cur_iv
                    return dyn_level, dyn_chg
                return '', dyn_chg

            def oi_watermark_level(strike_key, side, cur, close_chg, close_level):
                key = f"{strike_key}_{side}"
                st = _oi_alert_watermarks.get(key)
                close_dir = _dir(close_chg)
                if st is None:
                    if close_level and close_dir:
                        _oi_alert_watermarks[key] = {'trend': close_dir, 'extreme': cur}
                    return '', None
                trend = st.get('trend')
                extreme = st.get('extreme')
                if cur <= 0 or not extreme or extreme <= 0 or not trend:
                    return '', None
                if trend == 'up' and cur >= extreme:
                    st['extreme'] = cur
                    return '', None
                if trend == 'down' and cur <= extreme:
                    st['extreme'] = cur
                    return '', None
                dyn_chg = (cur - extreme) / extreme
                dyn_level = oi_level(dyn_chg, extreme, cur)
                if dyn_level and _dir(dyn_chg) and _dir(dyn_chg) != trend:
                    st['trend'] = _dir(dyn_chg)
                    st['extreme'] = cur
                    return dyn_level, dyn_chg
                return '', dyn_chg

            iv_call_level_dyn, iv_call_chg_dyn = iv_watermark_level(strike, 'C', iv_c, iv_call_chg_close, iv_call_level_close)
            iv_put_level_dyn, iv_put_chg_dyn = iv_watermark_level(strike, 'P', iv_p, iv_put_chg_close, iv_put_level_close)
            oi_call_level_dyn, oi_chg_call_dyn = oi_watermark_level(strike, 'C', oi_call, oi_chg_call, oi_call_level_close)
            oi_put_level_dyn, oi_chg_put_dyn = oi_watermark_level(strike, 'P', oi_put, oi_chg_put, oi_put_level_close)

            # 默认T表颜色仍按close基准显示
            iv_call_level = iv_call_level_close
            iv_put_level = iv_put_level_close
            oi_call_level = oi_call_level_close
            oi_put_level = oi_put_level_close

            # IV弹窗必须联动同侧OI变化：close基准和watermark反转分别判断；IV-only只在T表标色。
            linked_oi_keys = set()  # 已被IV+OI联动覆盖的OI，避免再弹单独持仓重大
            def linked_iv_item(side, iv_level, iv_chg_val, oi_level_val, oi_chg_val):
                if not iv_level or not oi_level_val:
                    return None
                return {
                    'side': side,
                    'level': _better_level(iv_level, oi_level_val),
                    'iv_level': iv_level,
                    'iv_chg': iv_chg_val,
                    'oi_level': oi_level_val,
                    'oi_chg': oi_chg_val,
                }

            close_items = []
            x = linked_iv_item('C', iv_call_level_close, iv_call_chg_close, oi_call_level_close, oi_chg_call)
            if x: close_items.append(x)
            x = linked_iv_item('P', iv_put_level_close, iv_put_chg_close, oi_put_level_close, oi_chg_put)
            if x: close_items.append(x)
            if close_items:
                best_level = 'major' if any(x['level'] == 'major' for x in close_items) else 'significant'
                for x in close_items:
                    linked_oi_keys.add((x['side'], 'close'))
                iv_alerts.append({
                    'strike': int(strike), 'level': best_level, 'iv_chg': iv_chg_close, 'ref_type': 'close',
                    'iv_call_level': next((x['iv_level'] for x in close_items if x['side'] == 'C'), ''),
                    'iv_put_level': next((x['iv_level'] for x in close_items if x['side'] == 'P'), ''),
                    'iv_call_chg': next((x['iv_chg'] for x in close_items if x['side'] == 'C'), None),
                    'iv_put_chg': next((x['iv_chg'] for x in close_items if x['side'] == 'P'), None),
                    'oi_call_level': next((x['oi_level'] for x in close_items if x['side'] == 'C'), ''),
                    'oi_put_level': next((x['oi_level'] for x in close_items if x['side'] == 'P'), ''),
                    'oi_call_chg': next((x['oi_chg'] for x in close_items if x['side'] == 'C'), None),
                    'oi_put_chg': next((x['oi_chg'] for x in close_items if x['side'] == 'P'), None),
                    'linked': True,
                })

            reversal_items = []
            x = linked_iv_item('C', iv_call_level_dyn, iv_call_chg_dyn, oi_call_level_dyn, oi_chg_call_dyn)
            if x: reversal_items.append(x)
            x = linked_iv_item('P', iv_put_level_dyn, iv_put_chg_dyn, oi_put_level_dyn, oi_chg_put_dyn)
            if x: reversal_items.append(x)
            if reversal_items:
                best_level = 'major' if any(x['level'] == 'major' for x in reversal_items) else 'significant'
                for x in reversal_items:
                    linked_oi_keys.add((x['side'], 'reversal'))
                iv_alerts.append({
                    'strike': int(strike), 'level': best_level, 'iv_chg': None, 'ref_type': 'reversal',
                    'iv_call_level': next((x['iv_level'] for x in reversal_items if x['side'] == 'C'), ''),
                    'iv_put_level': next((x['iv_level'] for x in reversal_items if x['side'] == 'P'), ''),
                    'iv_call_chg': next((x['iv_chg'] for x in reversal_items if x['side'] == 'C'), None),
                    'iv_put_chg': next((x['iv_chg'] for x in reversal_items if x['side'] == 'P'), None),
                    'oi_call_level': next((x['oi_level'] for x in reversal_items if x['side'] == 'C'), ''),
                    'oi_put_level': next((x['oi_level'] for x in reversal_items if x['side'] == 'P'), ''),
                    'oi_call_chg': next((x['oi_chg'] for x in reversal_items if x['side'] == 'C'), None),
                    'oi_put_chg': next((x['oi_chg'] for x in reversal_items if x['side'] == 'P'), None),
                    'linked': True,
                })

            # 持仓自身报警保留，但只保留“重大”单独弹窗；显著持仓已通过IV联动参与提示，避免刷屏。
            if oi_call_level_close == 'major' and ('C', 'close') not in linked_oi_keys:
                oi_alerts.append({'strike': int(strike), 'side': 'C', 'level': oi_call_level_close, 'oi_chg': oi_chg_call, 'ref_type': 'close', 'standalone': True})
            if oi_put_level_close == 'major' and ('P', 'close') not in linked_oi_keys:
                oi_alerts.append({'strike': int(strike), 'side': 'P', 'level': oi_put_level_close, 'oi_chg': oi_chg_put, 'ref_type': 'close', 'standalone': True})
            if oi_call_level_dyn == 'major' and ('C', 'reversal') not in linked_oi_keys:
                oi_alerts.append({'strike': int(strike), 'side': 'C', 'level': oi_call_level_dyn, 'oi_chg': oi_chg_call_dyn, 'ref_type': 'reversal', 'standalone': True})
            if oi_put_level_dyn == 'major' and ('P', 'reversal') not in linked_oi_keys:
                oi_alerts.append({'strike': int(strike), 'side': 'P', 'level': oi_put_level_dyn, 'oi_chg': oi_chg_put_dyn, 'ref_type': 'reversal', 'standalone': True})

            rows.append({
                'strike': int(strike),
                # OI
                'oi_call': oi_call,
                'oi_put': oi_put,
                'oi_call_prev': oi_call_b,
                'oi_put_prev': oi_put_b,
                'oi_call_chg': float(oi_chg_call * 100) if oi_chg_call is not None else None,
                'oi_put_chg': float(oi_chg_put * 100) if oi_chg_put is not None else None,
                'oi_call_level': oi_call_level,
                'oi_put_level': oi_put_level,
                # 成交量（同OI使用当前/基准对比口径；暂不触发报警色块）
                'vol_call': vol_call,
                'vol_put': vol_put,
                'vol_call_prev': vol_call_b,
                'vol_put_prev': vol_put_b,
                'vol_call_chg': float(vol_chg_call * 100) if vol_chg_call is not None else None,
                'vol_put_chg': float(vol_chg_put * 100) if vol_chg_put is not None else None,
                # IV（原始）
                'iv_call': round(iv_c, 2) if iv_c else None,
                'iv_put': round(iv_p, 2) if iv_p else None,
                'iv_call_prev': round(iv_c_b, 2) if iv_c_b else None,
                'iv_put_prev': round(iv_p_b, 2) if iv_p_b else None,
                # 平滑IV
                'iv_smooth': round(sm * 100, 2) if sm else None,
                # IV变化（对比基准）
                'iv_chg': round(iv_chg, 2) if iv_chg is not None else None,
                'iv_call_level': iv_call_level,
                'iv_put_level': iv_put_level,
                'iv_ref_type': iv_ref_type,
            })

        return jsonify({
            'rows': rows,
            'futures_price': futures_price,
            'atm_strike': _state.get('atm_strike'),
            'max_pain': max_pain,
            'has_baseline': has_baseline,
            'close_ts': close_ts,
            'close_expiry': _close_baseline.get('expiry') if _close_baseline else None,
            'active_contract': cur_contract,
            'baseline_contract_match': baseline_contract_match if _close_baseline else False,
            'avg_iv': round(atm_iv * 100, 2),
            'iv_thresholds': {k: round(v * 100, 1) for k, v in iv_t.items()},
            'iv_alerts': iv_alerts,
            'oi_alerts': oi_alerts,
            'last_update': _state.get('last_update'),
        })

    @app.route('/api/iv_smile/oi')
    def iv_api_oi():
        """期权持仓量T型报价：各行权价的Call/Put持仓量 + 隐波 + 15分钟变化"""
        now = datetime.now()
        with _state['lock']:
            strike_oi = _state.get('strike_oi', {})
            smile_raw = _state.get('smile_raw', {})
            smile_smooth = _state.get('smile_smooth', {})
            futures_price = _state.get('futures_price')

            # 前一个15分钟快照的OI和IV
            prev_key = get_prev_interval_key(now)
            prev_snap = _interval_snapshots.get(prev_key, {})
            prev_oi = prev_snap.get('strike_oi', {})
            prev_raw = prev_snap.get('raw', {})

        # 构建T型表格数据
        all_strikes = sorted(set(list(strike_oi.keys()) + list(prev_oi.keys())))

        rows = []
        for strike in all_strikes:
            cur = strike_oi.get(strike, {'C': 0, 'P': 0})
            prv = prev_oi.get(strike, {'C': 0, 'P': 0})
            raw = smile_raw.get(strike, {})
            sm = smile_smooth.get(strike)
            prv_raw = prev_raw.get(strike, {})

            # 当前IV
            iv_c = raw.get('C')
            iv_p = raw.get('P')
            # 前值IV
            iv_c_prev = prv_raw.get('C')
            iv_p_prev = prv_raw.get('P')
            # 平滑IV变化
            sm_prev = prev_snap.get('smooth', {}).get(strike)

            row = {
                'strike': int(strike),
                'oi_call': int(cur.get('C', 0)),
                'oi_put': int(cur.get('P', 0)),
                'oi_call_prev': int(prv.get('C', 0)),
                'oi_put_prev': int(prv.get('P', 0)),
                'iv_call': float(iv_c * 100) if iv_c else None,
                'iv_put': float(iv_p * 100) if iv_p else None,
                'iv_call_prev': float(iv_c_prev * 100) if iv_c_prev else None,
                'iv_put_prev': float(iv_p_prev * 100) if iv_p_prev else None,
                'iv_smooth': float(sm * 100) if sm else None,
                'iv_smooth_prev': float(sm_prev * 100) if sm_prev else None,
            }
            rows.append(row)

        return jsonify({
            'rows': rows,
            'futures_price': futures_price,
            'prev_key': prev_key,
            'last_update': _state.get('last_update'),
        })

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
                svi = _state.get('svi_params', {})
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

                svi_str = (f"a={svi.get('a',0):.4f} b={svi.get('b',0):.4f} ATMvol={svi.get('atm_vol',0):.2%}"
                            if svi else "SVI N/A")
                ax.set_title(f'PTA IV Smile | S={futures_price} | {last_update[:19]} | {svi_str}',
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

    @app.route('/api/iv_smile/gex')
    def iv_api_gex():
        _ensure_today_close_baseline_after_21()
        """
        Gamma Exposure API
        返回:
          - gex_bars / pain_curve / oi_dist / summary: 当前实时数据
          - prev_gex_bars / prev_pain_curve / prev_oi_dist / prev_summary: 前次基准
          - baseline_label: 基准时间标签 (e.g. "15:00收盘")
        """
        from scipy.stats import norm as sp_norm
        with _state['lock']:
            strike_oi = _state.get('strike_oi', {})
            smile_raw = _state.get('smile_raw', {})
            smile_smooth = _state.get('smile_smooth', {})
            futures_price = _state.get('futures_price')
            r = _state.get('rate', 0.02)
            max_pain_val = _state.get('max_pain')
            expiry = _state.get('expiry')
            last_update = _state.get('last_update', '')

        # T 用交易日计算
        if expiry:
            T = _calc_T_trading_days(expiry)
        else:
            T = _state.get('T')

        if not futures_price or not T or T <= 0:
            return jsonify({'error': 'data not ready', 'gex_bars': [], 'pain_curve': [],
                            'oi_dist': [], 'summary': {},
                            'prev_gex_bars': [], 'prev_pain_curve': [],
                            'prev_oi_dist': [], 'prev_summary': {}, 'baseline_label': None})

        F = futures_price
        sqrtT = np.sqrt(T) if T > 0 else 1e-6

        # 辅助函数：兼容字典key类型（可能是str/int/float）
        def _get(d, k, default=None):
            for key in [k, int(k), str(int(k))]:
                if key in d:
                    return d[key]
            return default

        # ---- 通用计算函数 ----
        def _calc_gex_pain_oi(oi_dict):
            """根据给定的 strike_oi 字典，计算 gex_bars, pain_curve, oi_dist 及摘要

            v2.11.35: GEX/Flip/Max Pain/PCR/OI 全部改为全档动态口径（与 T表/Excel 一致）。
            深度档 IV 来源: smile_smooth (SVI 拟合, moneyness ±20% 内) → smile_raw (实时报价) → None=gamma=0。
            之前是 ATM±10 (21档) 口径，导致 GEX summary PCR 与 T表全档 PCR 差 0.023，
            且深度虚值 Put (保险盘) 的 gamma 暴露被截断。
            验证: 实测 F=6502 时 21档→32档 Net GEX +9.9%, GEX Flip/方向 不变。
            """
            # GEX/Flip/Max Pain/PCR/OI 全部用全档 (32档) 动态计算，与 T表/Excel 保持一致。
            # SVI 拟合仍只覆盖 ATM±10 (moneyness ±20%)，深度档 IV 落到 raw 报价；
            # 极少数深度档 raw 无报价时 gamma=0（与之前 21档外 OI=0 同等处理）。
            oi_strikes = sorted(set(float(k) for k in oi_dict.keys()))
            # 1. GEX
            gex_list = []
            for K in oi_strikes:
                oi_data = _get(oi_dict, K, {'C': 0, 'P': 0})
                c_oi = oi_data.get('C', 0) or 0
                p_oi = oi_data.get('P', 0) or 0
                raw = _get(smile_raw, K, {})
                sm = _get(smile_smooth, K)
                if sm and sm > 0:
                    sigma = sm
                else:
                    iv_c = raw.get('C') if isinstance(raw, dict) else None
                    iv_p = raw.get('P') if isinstance(raw, dict) else None
                    vals = [v for v in [iv_c, iv_p] if v and v > 0]
                    sigma = sum(vals) / len(vals) if vals else None
                if not sigma or sigma <= 0 or K <= 0:
                    gex_list.append({'strike': int(K), 'call_gex': 0, 'put_gex': 0, 'net_gex': 0})
                    continue
                d1 = (np.log(F / K) + 0.5 * sigma ** 2 * T) / (sigma * sqrtT)
                gamma = np.exp(-r * T) * sp_norm.pdf(d1) / (F * sigma * sqrtT)
                CONTRACT_MULT = 5
                call_gex = c_oi * gamma * F * F * 0.01 * CONTRACT_MULT
                put_gex = -p_oi * gamma * F * F * 0.01 * CONTRACT_MULT
                net_gex = call_gex + put_gex
                gex_list.append({'strike': int(K), 'call_gex': round(call_gex, 0),
                                 'put_gex': round(put_gex, 0), 'net_gex': round(net_gex, 0)})
            # 2. Pain Curve（同样使用GEX 21档口径）
            oi_map = {K: _get(oi_dict, K, {'C': 0, 'P': 0}) for K in oi_strikes}
            sorted_ks = sorted(oi_map.keys())
            pain_list = []
            for K in sorted_ks:
                pain = 0
                for Ki in sorted_ks:
                    c_oi = oi_map[Ki].get('C', 0) or 0
                    p_oi = oi_map[Ki].get('P', 0) or 0
                    pain += (c_oi * max(K - Ki, 0) + p_oi * max(Ki - K, 0)) * 5
                pain_list.append({'strike': int(K), 'pain': round(pain, 0)})
            mp = None
            if pain_list:
                mp = min(pain_list, key=lambda x: x['pain'])['strike']
            # 3. OI Dist
            oi_list = []
            tc, tp = 0, 0
            for K in oi_strikes:
                oi_data = _get(oi_dict, K, {'C': 0, 'P': 0})
                c_oi = oi_data.get('C', 0) or 0
                p_oi = oi_data.get('P', 0) or 0
                tc += c_oi; tp += p_oi
                oi_list.append({'strike': int(K), 'call_oi': int(c_oi), 'put_oi': int(p_oi)})
            # 4. 摘要
            pcr = round(tp / tc, 3) if tc > 0 else None
            net_gex_total = sum(item['net_gex'] for item in gex_list)
            gex_flip = None
            nonzero = [b for b in sorted(gex_list, key=lambda x: x['strike']) if b['net_gex'] != 0]
            for i in range(1, len(nonzero)):
                pn = nonzero[i - 1]['net_gex']; cn = nonzero[i]['net_gex']
                if pn * cn < 0:
                    k1, k2 = nonzero[i-1]['strike'], nonzero[i]['strike']
                    ratio = abs(pn) / (abs(pn) + abs(cn)) if (abs(pn) + abs(cn)) > 0 else 0.5
                    gex_flip = round((k1 + ratio * (k2 - k1)) / 2) * 2
                    break
            # days_left 用日历天（自然日），更直观
            if expiry:
                if hasattr(expiry, 'hour'):
                    expiry_dt = expiry if expiry.hour or expiry.minute or expiry.second or expiry.microsecond else expiry.replace(hour=15, minute=0)
                else:
                    expiry_dt = datetime.combine(expiry, datetime.min.time()).replace(hour=15, minute=0)
                days_left = round((expiry_dt - datetime.now()).total_seconds() / 86400, 1)
                if days_left < 0:
                    days_left = 0
            else:
                days_left = None
            summ = {
                'futures_price': futures_price, 'max_pain': mp, 'pcr': pcr,
                'net_gex': round(net_gex_total, 0),
                'gex_direction': 'positive' if net_gex_total > 0 else 'negative',
                'gex_flip': gex_flip,
                'T': round(T, 6) if T else None, 'days_left': days_left,
                'expiry': expiry.isoformat() if expiry else None,
                'total_call_oi': int(tc), 'total_put_oi': int(tp),
                'last_update': last_update,
            }
            return gex_list, pain_list, oi_list, summ

        # ---- 当前实时数据 ----
        gex_bars, pain_curve, oi_dist, summary = _calc_gex_pain_oi(strike_oi)
        # 覆盖max_pain: 实时计算优先
        if pain_curve:
            max_pain_val = min(pain_curve, key=lambda x: x['pain'])['strike']
            summary['max_pain'] = max_pain_val

        # ---- 前次基准数据 ----
        # 优先用 _close_baseline（人工注入 / 今日 15:00 收盘），与 alert_data 端点保持完全一致的数据源
        # 兜底：_prev_day_baseline（自动写入的前一交易日 15:00）
        prev_gex_bars, prev_pain_curve, prev_oi_dist, prev_summary = [], [], [], {}
        baseline_label = None
        prev_oi = None
        prev_S = None
        prev_smile_raw = None
        prev_smile_smooth = None
        prev_expiry = expiry
        prev_T = T
        prev_r = r
        prev_last_update = None

        def _close_baseline_eligible(cb):
            """判断 _close_baseline 是否可用作'前次基准'，与 alert_data 端点逻辑完全对齐"""
            if not cb or not cb.get('strike_oi'):
                return False
            cb_contract = cb.get('contract')
            if cb_contract and _state.get('active_contract') and cb_contract != _state.get('active_contract'):
                return False
            cb_ts = cb.get('ts') or cb.get('timestamp') or ''
            if not cb_ts:
                return False
            try:
                cb_date = datetime.fromisoformat(cb_ts[:10] if len(cb_ts) >= 10 else cb_ts).date()
            except Exception:
                return False
            now_dt = datetime.now()
            today = now_dt.date()
            # v2.11.38+ 切换原则（统一判断）：cb_date 与当前期望基准日期匹配
            return _cb_should_apply(cb_date, now_dt)

        if _close_baseline_eligible(_close_baseline):
            cb = _close_baseline
            prev_oi = cb.get('strike_oi', {})
            prev_S = cb.get('S') or cb.get('futures_price') or cb.get('state', {}).get('S')
            prev_smile_raw = cb.get('raw', {})
            prev_smile_smooth = cb.get('smooth', {})
            cb_ts = (cb.get('ts') or cb.get('timestamp') or '')[:10]
            baseline_label = f"今日15:00 ({cb_ts[5:10]})" if cb_ts else '今日15:00收盘'
            # T/r/expiry 也用 15:00 收盘时点的（若可推断）
            cb_expiry_ts = cb.get('expiry') or cb.get('state', {}).get('expiry')
            if cb_expiry_ts:
                try:
                    prev_expiry = datetime.fromisoformat(cb_expiry_ts.replace('Z', '')) if isinstance(cb_expiry_ts, str) else cb_expiry_ts
                except Exception:
                    pass
            cb_T = cb.get('T') or cb.get('state', {}).get('T')
            if cb_T and cb_T > 0:
                prev_T = cb_T
            prev_last_update = cb.get('ts') or cb.get('timestamp')
        elif _prev_day_baseline and _prev_day_baseline.get('strike_oi'):
            pdb = _prev_day_baseline
            prev_oi = pdb.get('strike_oi', {})
            prev_S = pdb.get('S') or pdb.get('futures_price') or pdb.get('state', {}).get('S')
            prev_smile_raw = pdb.get('raw', {})
            prev_smile_smooth = pdb.get('smooth', {})
            ts = (pdb.get('timestamp') or '')[:19]
            baseline_label = f'前日15:00 ({ts[5:10]})' if ts else '前日15:00'
            prev_last_update = pdb.get('timestamp')

        if prev_oi and len(prev_oi) > 0:
            # 把 prev 用的 S/T/r/smile_raw/smile_smooth/futures_price 临时闭包替换后再调计算函数
            _saved_globals = (F, T, r, expiry, smile_raw, smile_smooth, last_update, futures_price)
            try:
                if prev_S and prev_S > 0:
                    F = float(prev_S)
                    futures_price = float(prev_S)  # 关键：summ 里用的也是这个闭包变量
                if prev_T and prev_T > 0:
                    T = float(prev_T)
                if prev_r is not None:
                    r = float(prev_r)
                if prev_expiry is not None:
                    expiry = prev_expiry
                if prev_smile_raw is not None:
                    smile_raw = prev_smile_raw
                if prev_smile_smooth is not None:
                    smile_smooth = prev_smile_smooth
                if prev_last_update is not None:
                    last_update = prev_last_update
                prev_gex_bars, prev_pain_curve, prev_oi_dist, prev_summary = _calc_gex_pain_oi(prev_oi)
            finally:
                F, T, r, expiry, smile_raw, smile_smooth, last_update, futures_price = _saved_globals

        return jsonify({
            'gex_bars': gex_bars,
            'pain_curve': pain_curve,
            'oi_dist': oi_dist,
            'summary': summary,
            'prev_gex_bars': prev_gex_bars,
            'prev_pain_curve': prev_pain_curve,
            'prev_oi_dist': prev_oi_dist,
            'prev_summary': prev_summary,
            'baseline_label': baseline_label,
        })


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

    # 不再阻塞等待——tqsdk_loop 内部有自重启机制
    print("[iv_smile] TqSdk线程已启动（内部自愈重连已启用）")

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


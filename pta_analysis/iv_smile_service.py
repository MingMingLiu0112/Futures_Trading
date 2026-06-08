






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
    'rate': 0.02,
    'running': False,
    'lock': Lock(),
    'active_contract': None,
    'data_ready': False,   # 数据是否真正到达
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
}

# 历史快照（按固定15分钟时间点存储）
# key: "HH:MM" 如 "09:00", "09:15", ... 或 'night'（昨夜盘锚点）
# value: {'smooth': {strike: iv}, 'raw': {strike: {'C': iv, 'P': iv}}, 'timestamp': str}
_interval_snapshots = {}          # 内存快照: key="HH:MM" 或 "night"（仅当天数据）
_interval_loaded_from_disk = set()  # 已从磁盘加载的日期，避免重复
_prev_day_baseline = {}           # 前一交易日15:00收盘快照（启动时从磁盘加载）
                                  # {'smooth': {}, 'raw': {}, 'strike_oi': {}, 'timestamp': str, 'futures_price': float}


# IV变化报警追踪（避免重复报警）
_iv_alert_sent_today = set()       # 今天已发送的报警记录: {(strike, direction), ...}
_iv_alert_last_send_time = {}      # 上次发送时间: {f"{strike}_{dir}": timestamp}
_iv_alert_last_direction = {}      # 上次报警方向: {f"{strike}": 'up'|'down', f"oi_{strike}_{side}": 'up'|'down'}
_iv_alert_dynamic_baseline = {}    # 动态基准: {strike: iv_value} — 每次IV报警触发后更新，用于捕捉盘中二次变化
_oi_alert_dynamic_baseline = {}    # OI动态基准: {"strike_side": oi_value} — 捕捉持仓盘中反转

# 每日收盘基准快照（15:00 收盘时记录，作为盘中对比基准）
_close_baseline = {}               # {'smooth': {}, 'raw': {}, 'strike_oi': {}, 'S': float, 'ts': str}

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

def _record_close_baseline(smile_smooth, smile_raw, strike_oi, S):
    """记录每日15:00收盘基准快照，同时重置报警状态"""
    global _close_baseline, _iv_alert_dynamic_baseline, _oi_alert_dynamic_baseline
    _close_baseline = {
        'smooth': {k: float(v) for k, v in smile_smooth.items()},
        'raw': {k: dict(v) for k, v in smile_raw.items()},
        'strike_oi': {k: dict(v) for k, v in strike_oi.items()},
        'S': float(S),
        'ts': datetime.now().isoformat(),
    }
    # 新基准生效，清空所有报警追踪状态
    _iv_alert_sent_today.clear()
    _iv_alert_last_send_time.clear()
    _iv_alert_last_direction.clear()
    _iv_alert_dynamic_baseline = {}
    _oi_alert_dynamic_baseline = {}
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
        p = _state.get('futures_price') or _last_valid.get('futures_price')
    if p and p > 0:
        return float(p), 'tqsdk'
    return None, 'none'

_dummy_lock = type('DummyLock', (), {'__enter__': lambda s: s, '__exit__': lambda *a: None})()

# ===================== 持久化配置 =====================
_SNAPSHOT_DIR = os.path.join(WORKSPACE, 'data', 'iv_snapshots')
_SAVED_DATES = set()   # 记录已写入磁盘的日期，避免重复保存

# PTA 收盘时间点（小盘、午盘、日盘收盘、夜盘收盘）
_PTA_CLOSE_TIMES = [(10, 15), (11, 30), (15, 0), (23, 0)]
_CLOSE_STATE_FILE = os.path.join(_SNAPSHOT_DIR, 'close_state.json')
_close_state_saved_slots = set()  # 记录本次进程已保存的收盘时间槽，避免重复

def _get_snapshot_path(date_str):
    """返回指定日期的日盘快照文件路径（包含全天所有15分钟时间点）。"""
    return os.path.join(_SNAPSHOT_DIR, f'iv_snapshots_{date_str}.json')

def _ensure_snapshot_dir():
    """确保快照目录存在"""
    os.makedirs(_SNAPSHOT_DIR, exist_ok=True)

def _save_close_state():
    """
    收盘快照：将当前 _state + _last_valid 完整写入 close_state.json。
    在 PTA 四个收盘时间点自动调用，重启后可立即恢复全部数据，无需等 TqSdk。
    """
    _ensure_snapshot_dir()
    # 只保存可序列化的字段
    payload = {
        'timestamp': datetime.now().isoformat(),
        'state': {
            'futures_price': _state.get('futures_price'),
            'atm_strike': _state.get('atm_strike'),
            'max_pain': _state.get('max_pain'),
            'ref_strike': _state.get('ref_strike'),
            'smile_raw': _state.get('smile_raw', {}),
            'smile_smooth': _state.get('smile_smooth', {}),
            'svi_params': _state.get('svi_params'),
            'last_update': _state.get('last_update'),
            'strike_oi': _state.get('strike_oi', {}),
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


def _check_and_save_close_state():
    """
    检查当前是否为 PTA 收盘时间点（±2分钟窗口），是则保存收盘快照。
    每个时间槽在本进程生命周期内只保存一次。
    """
    now = datetime.now()
    for hh, mm in _PTA_CLOSE_TIMES:
        slot_key = f"{now.strftime('%Y%m%d')}_{hh:02d}{mm:02d}"
        if slot_key in _close_state_saved_slots:
            continue
        # ±2分钟窗口
        target_min = hh * 60 + mm
        now_min = now.hour * 60 + now.minute
        if abs(now_min - target_min) <= 2:
            _close_state_saved_slots.add(slot_key)
            _save_close_state()
            break


def _load_close_state():
    """
    启动时加载收盘快照恢复 _state 和 _last_valid。
    返回 True 表示成功恢复，False 表示无可用数据。
    """
    global _state, _last_valid
    if not os.path.exists(_CLOSE_STATE_FILE):
        return False
    try:
        with open(_CLOSE_STATE_FILE, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        saved_state = payload.get('state', {})
        saved_valid = payload.get('last_valid', {})
        ts = payload.get('timestamp', '')

        # 检查数据有效性
        if not saved_state.get('smile_smooth') or not saved_state.get('futures_price'):
            print(f"[iv_smile] ⚠️ 收盘快照数据不完整，跳过")
            return False

        # 恢复 _state
        for key in ('futures_price', 'atm_strike', 'max_pain', 'ref_strike',
                     'smile_raw', 'smile_smooth', 'svi_params', 'last_update', 'strike_oi'):
            val = saved_state.get(key)
            if val is not None:
                _state[key] = val

        # 恢复 _last_valid
        for key in ('futures_price', 'atm_strike', 'max_pain', 'ref_strike',
                     'smile_raw', 'smile_smooth', 'svi_params', 'strike_oi'):
            val = saved_valid.get(key)
            if val is not None:
                _last_valid[key] = val

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
        return True
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
    merged = dict(existing)
    merged.update(_interval_snapshots)
    payload = {
        'date': date_str,
        'snapshots': merged,   # 合并后全量快照 dict

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
    """
    if dt is None:
        dt = datetime.now()
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


def _is_trading_hours():
    """
    判断当前是否在PTA交易时段（允许SVI校准）。
    PTA(CZCE)交易时段：
      日盘上午: 09:00-11:30
      日盘下午: 13:30-15:00
      夜盘:     21:00-23:00（当日结束，不跨零点）
    其余时段跳过校准，避免休盘期间虚假波动。
    同时检查交易日——周末/节假日不交易。
    节假日前一天没有夜盘（次日休市则当晚不开夜盘）。
    """
    now = datetime.now()
    if not _is_trading_day(now):
        return False
    h, m = now.hour, now.minute
    total = h * 60 + m
    # 日盘上午: 09:00-11:30 (540-690)
    am_start, am_end = 9 * 60, 11 * 60 + 30
    # 日盘下午: 13:30-15:00 (810-900)
    pm_start, pm_end = 13 * 60 + 30, 15 * 60
    # 夜盘: 21:00-23:00 (1260-1380), 不跨零点
    night_start, night_end = 21 * 60, 23 * 60
    # 日盘判断
    if am_start <= total < am_end:  # 09:00-11:30
        return True
    if pm_start <= total < pm_end:  # 13:30-15:00
        return True
    # 夜盘判断: 21:00-23:00
    if night_start <= total < night_end:
        # 规则：节假日/长假前一天没有夜盘（次交易日休市则今晚不开夜盘）
        # 周五正常有夜盘（PTA夜盘23:00结束，不跨到周六）
        today_wd = now.weekday()
        if today_wd == 4:  # 周五
            return True
        if today_wd >= 5:  # 周六周日不可能有夜盘
            return False
        tomorrow = now.date() + timedelta(days=1)
        if _is_cn_holiday(tomorrow) or tomorrow.weekday() >= 5:
            return False  # 次日休市，今晚没有夜盘
        return True
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


def _calc_T_trading_days(expiry, now=None):
    """
    用交易日计算到期时间T（年化）。
    行业标准：T = 剩余交易日 / 每年交易日数(245)。
    
    今天当天算一个完整交易日（盘中），到期日不算（到期日收盘后才真正到期，
    但最后一天时间价值几乎为0，用整数交易日足够准确）。
    
    最小值 0.5/245（到期日当天），避免T=0导致IV爆炸。
    """
    if now is None:
        now = datetime.now()
    if expiry is None:
        return 30 / _TRADING_DAYS_PER_YEAR  # 默认30个交易日
    
    expiry_date = expiry.date() if isinstance(expiry, datetime) else expiry
    today = now.date() if isinstance(now, datetime) else now
    
    if today >= expiry_date:
        return 0.5 / _TRADING_DAYS_PER_YEAR  # 到期日当天，给最小值
    
    trading_days = _count_trading_days(today, expiry_date)
    if trading_days <= 0:
        return 0.5 / _TRADING_DAYS_PER_YEAR
    
    return trading_days / _TRADING_DAYS_PER_YEAR


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

    # === 0. 优先从收盘快照恢复 _state（重启后立即有数据） ===
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
                if snap_date == check_date:
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
                    print(f"[iv_smile] ⚠️ {check_date} 的15:00快照timestamp不匹配({snap_ts})，跳过")
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
    # 如果收盘快照已恢复 _state，跳过从15分钟快照恢复（避免被更旧数据覆盖）
    # 但仍需恢复 expiry/T 和 akshare 校正（不论哪种恢复路径都需要）
    if not close_restored and latest_for_restore:
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
            # 用交易日计算T
            _T = _calc_T_trading_days(_exp)
            _state['T'] = _T
            _td = _count_trading_days(datetime.now().date(), _exp.date() if isinstance(_exp, datetime) else _exp)
            print(f"[iv_smile] 📂 已恢复到期日: {_contract} expiry={_exp.date()} T={_T:.6f}yr ({_td}个交易日)")
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
        'success': True,
    }


def smooth_smile(K_list, IV_list, F, T):
    """SVI拟合 → 重建平滑曲线（全行权价范围外推）"""
    svi = fit_svi(K_list, IV_list, F, T)
    if svi is None:
        return {}, None

    a, b, rho, m, sigma = svi['a'], svi['b'], svi['rho'], svi['m'], svi['sigma']

    # 生成平滑曲线：覆盖输入行权价范围，并向两端适度外推
    K_min = min(K_list)
    K_max = max(K_list)
    # 向两端外推（但不超过合理范围）
    # 关键修复：K_range_low 必须 <= K_min，否则深度OTM行权价没有smooth IV
    K_range_low = max(int(F * 0.7), K_min - 500)
    K_range_high = min(int(F * 1.3), K_max + 500)

    # 用输入的行权价 + 外推范围生成平滑点
    # 100步长外推 + 原始K_list去重合并
    all_strikes = sorted(set(K_list) | set(range(K_range_low, K_range_high + 1, 100)))

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
                        bid = getattr(oq, 'bid_price1', None)
                        if bid and bid > 0:
                            count += 1
                elapsed = time.time() - wait_start
                if count > data_ready_count:
                    data_ready_count = count
                    print(f"  [{elapsed:.0f}s] {count}/{len(option_symbols)} 个期权有报价")
                    if count >= len(option_symbols) * 0.8:
                        print(f"[iv_smile] ✅ 80%期权已就位 ({data_ready_count}/{len(option_symbols)})，继续...")
                        break
                # 每5秒报告一次进度（持续等待，不放弃）
                if time.time() - last_progress_time >= 5:
                    print(f"  [{elapsed:.0f}s] 等待中... {count}/{len(option_symbols)} 个期权有报价（持续等待，不放弃）")
                    last_progress_time = time.time()
                loop.run_until_complete(asyncio.sleep(0.05))

            # 检查是否被请求重启（等待期权时被中断）
            if _tqsdk_restart_requested or not _state['running']:
                api.close()
                loop.close()
                continue

            # 即使没到80%，只要有数据就继续（不做重启，继续等待）
            if data_ready_count < len(option_symbols) * 0.8:
                if data_ready_count > 0:
                    print(f"[iv_smile] ⚠️ 只有 {data_ready_count}/{len(option_symbols)} 期权有报价，持续等待（模拟账户数据可能延迟）")
                else:
                    print(f"[iv_smile] ⚠️ 期权数据暂未到达，持续等待（模拟账户数据可能延迟）...")
            else:
                print(f"[iv_smile] ✅ 数据就绪，{data_ready_count}/{len(option_symbols)} 个期权有有效报价")

            _state['data_ready'] = True
            _tqsdk_ready = True
            _tqsdk_last_data_time = time.time()

            # === 主事件循环 ===
            counter = 0
            last_log_time = time.time()
            while _state['running'] and not _tqsdk_restart_requested:
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
                                    'open_interest': getattr(oq, 'open_interest', None) or 0,
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

                except Exception as e:
                    if _state['running']:
                        print(f"[iv_smile] wait_update异常: {e}")
                    break

            api.close()
            loop.close()

            # 如果是主动请求重启，不算异常，继续重连
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

    # 3. 剩余期限（年）— 用交易日计算
    expiry = _state.get('expiry')
    if not expiry:
        print("[iv_smile] 到期日未设置")
        return False
    T = _calc_T_trading_days(expiry)

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
            if interval_key in _interval_snapshots:
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

        # 更新缓存（价格/OI始终更新，smile视情况）
        _last_valid['futures_price'] = S
        _last_valid['ref_strike'] = ref_strike
        _last_valid['max_pain'] = max_pain
        _last_valid['atm_strike'] = atm_strike
        _last_valid['strike_oi'] = {k: dict(v) for k, v in strike_oi.items()}
        if should_update_smile:
            _last_valid['smile_raw'] = {k: v for k, v in raw_iv.items()}
            _last_valid['smile_smooth'] = smooth_iv
            _last_valid['svi_params'] = svi

        # 更新状态
        _state['strike_oi'] = {k: dict(v) for k, v in strike_oi.items()}
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
        if should_update_smile:
            _state['last_update'] = now.isoformat()

    svi_str = (f"a={svi['a']:.4f} b={svi['b']:.4f} ρ={svi['rho']:.3f} ATMvol={svi['atm_vol']:.2%}") if svi else "失败"
    mp_str = f"MP={max_pain}" if max_pain else ""
    print(f"[iv_smile] ✅ S={S:.0f} {mp_str} 档位={len(raw_iv)} SVI({svi_str})")

    # IV变化报警检查（对比当日15:00收盘基准）
    _check_iv_alert(smooth_iv, raw_iv, strike_oi, S, max_pain)

    # 15:00收盘时记录基准快照（每个交易日只记一次）
    now = datetime.now()
    if now.hour == 15 and now.minute == 0 and not _close_baseline:
        _record_close_baseline(smooth_iv, raw_iv, strike_oi, S)

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
    td = _count_trading_days(datetime.now().date(), expiry.date() if isinstance(expiry, datetime) else expiry)
    print(f"[iv_smile] 🕐 休盘T刷新: T={T:.6f}yr ({td}个交易日) (前值={old_T:.6f})" if old_T else
          f"[iv_smile] 🕐 休盘T刷新: T={T:.6f}yr ({td}个交易日)")


def start_scheduler(interval_minutes=1):
    def loop():
        global _last_snapshot_minute
        print(f"[iv_smile] 调度器启动，间隔={interval_minutes}分钟")
        counter = 0
        offhours_t_counter = 0  # 休盘T刷新计数器
        while _state['running']:
            # 休盘时段：跳过compute_once，避免用datetime.now()算T导致IV虚高
            if _is_trading_hours():
                compute_once()
                offhours_t_counter = 0  # 开盘重置
            else:
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
    from flask import render_template, jsonify

    @app.route('/iv_smile')
    def iv_smile_page():
        return render_template('iv_smile.html')

    @app.route('/api/iv_smile/status')
    def iv_api_status():
        with _state['lock']:
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
                'active_contract': _state.get('active_contract'),
                'snapshot_times': snapshot_times,  # 格式: ["09:00","09:15",...]
                'reconnect_count': _tqsdk_reconnect_count,
            })

    @app.route('/api/iv_smile/curve')
    def iv_api_curve():
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
            strikes = sorted(set(list(raw.keys()) + list(smooth.keys()))) if smooth else sorted(raw.keys())

            # 持仓数据（当前 strike_oi）
            strike_oi = _state.get('strike_oi', {})

            # 前次曲线：15:00 收盘基准快照
            # 交易日周期：21:00夜盘开盘才切换基准
            # - 21:00之前：只用 _prev_day_baseline（前一交易日15:00），便于盘后复盘
            # - 21:00之后：优先 _close_baseline（当天15:00），兜底 _prev_day_baseline
            now_hour = datetime.now().hour
            if now_hour >= 21:
                # 新交易周期开始，使用当天15:00基准
                close_baseline = _close_baseline
                prev_smooth = close_baseline.get('smooth', {}) if close_baseline else {}
                prev_raw = close_baseline.get('raw', {}) if close_baseline else {}
                if not prev_smooth and _prev_day_baseline:
                    prev_smooth = _prev_day_baseline.get('smooth', {})
                    prev_raw = _prev_day_baseline.get('raw', {})
                    if prev_smooth:
                        ts = _prev_day_baseline.get('timestamp', '')[:19]
                        print(f"[iv_smile] 📌 使用前一交易日15:00基准 smooth={len(prev_smooth)}档 ts={ts}")
            else:
                # 盘后复盘时段（15:00-21:00）或日盘（09:00-15:00），保持前一交易日基准
                close_baseline = None
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

            # 前次ATM：优先取baseline的atm_strike，其次从futures_price/S计算
            prev_atm_strike = None
            if now_hour >= 21:
                bl = close_baseline if close_baseline and (close_baseline.get('atm_strike') or close_baseline.get('S')) else _prev_day_baseline
            else:
                bl = _prev_day_baseline
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
                        # 线性插值
                        v_left = prev_smooth[str(left)]
                        v_right = prev_smooth[str(right)]
                        ratio = (k_int - left) / (right - left)
                        v_interp = v_left + (v_right - v_left) * ratio
                        entry['smooth_prev'] = float(v_interp)
                        entry['prev_avg'] = float(v_interp)
                    elif left is not None:
                        entry['smooth_prev'] = prev_smooth[str(left)]
                        entry['prev_avg'] = prev_smooth[str(left)]
                    elif right is not None:
                        entry['smooth_prev'] = prev_smooth[str(right)]
                        entry['prev_avg'] = prev_smooth[str(right)]
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
                # 隐波变化绝对值（当前smooth - 15:00收盘smooth）
                if 'smooth' in entry and 'smooth_prev' in entry:
                    entry['iv_change'] = round(abs(entry['smooth'] - entry['smooth_prev']), 4)
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

        return jsonify({
            'futures_price': _state['futures_price'],
            'underlying_price': _state['futures_price'],   # 标的价格（前端指标栏用）
            'ref_strike': _state.get('ref_strike'),
            'max_pain': realtime_max_pain,
            'atm_strike': _state['atm_strike'],
            'prev_atm_strike': prev_atm_strike,
            'last_update': _state['last_update'],
            'expiry': _state['expiry'].isoformat() if _state.get('expiry') else None,
            'T': (_calc_T_trading_days(_state['expiry'])
                  if _state.get('expiry') else _state.get('T')),  # 交易日T
            'svi_params': svi,
            'curve': curve_data,
            'prev_timestamp': prev_ts_display,      # 格式: "09:30" 或 "昨收盘"
            'prev_interval_key': prev_key,          # 格式: "09:30"
            'current_interval_key': latest_key,   # 格式: "10:45"
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


    @app.route('/api/iv_smile/alert_data')
    def iv_api_alert_data():
        """
        T型报价+报警数据：对比当日15:00收盘基准，返回带颜色标注级别的完整数据。
        用于前端T型表格颜色标注 + 弹窗声音报警判断。
        """
        now = datetime.now()
        with _state['lock']:
            strike_oi = _state.get('strike_oi', {})
            smile_raw = _state.get('smile_raw', {})
            smile_smooth = _state.get('smile_smooth', {})
            futures_price = _state.get('futures_price')
            max_pain = _state.get('max_pain')

        # 前次曲线：优先 _close_baseline（运行时记录），兜底 _prev_day_baseline（前一交易日15:00）
        close_baseline = _close_baseline
        b_smooth = close_baseline.get('smooth', {}) if close_baseline else {}
        b_raw = close_baseline.get('raw', {}) if close_baseline else {}
        b_oi = close_baseline.get('strike_oi', {}) if close_baseline else {}
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
            has_baseline = bool(b_smooth)

        # 用ATM隐波判断波动环境（比全档位均值更准确）
        atm = _state.get('atm_strike')
        atm_iv = smile_smooth.get(atm) or smile_smooth.get(str(atm)) if atm else None
        if not atm_iv:
            vals = list(smile_smooth.values())
            atm_iv = sum(vals) / len(vals) if vals else 0
        iv_t = _get_iv_thresholds(atm_iv)

        # 合并所有行权价（统一为字符串key）
        all_keys = set(str(k) for k in list(strike_oi.keys()) + list(b_oi.keys()))
        if not all_keys and smile_smooth:
            all_keys = set(str(k) for k in smile_smooth.keys())
            # 补充raw数据
            for k in all_keys:
                if k not in strike_oi:
                    strike_oi[k] = {'C': 0, 'P': 0}
                if k not in b_oi:
                    b_oi[k] = {'C': 0, 'P': 0}

        rows = []
        iv_alerts = []  # {'strike': int, 'level': str}
        oi_alerts = []

        for strike in sorted(all_keys, key=lambda x: int(x)):
            cur_oi = strike_oi.get(strike) or strike_oi.get(int(strike)) or {'C': 0, 'P': 0}
            b_oi_s = b_oi.get(strike) or b_oi.get(int(strike)) or {'C': 0, 'P': 0}

            # IV（strike可能是str，但数据源key可能是int，双查找）
            raw = smile_raw.get(strike) or smile_raw.get(int(strike)) or {}
            sm = smile_smooth.get(strike) or smile_smooth.get(int(strike))
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
            elif isinstance(raw, (int, float)):
                iv_c = raw * 100
                iv_p = raw * 100
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

            # IV变化（用平滑IV）— 同时比较收盘基准和动态基准，取较大变化
            iv_chg_close = (sm - b_sm) * 100 if (sm and b_sm) else None
            dyn_iv = _iv_alert_dynamic_baseline.get(strike) or _iv_alert_dynamic_baseline.get(int(strike))
            iv_chg_dyn = (sm - dyn_iv) * 100 if (sm and dyn_iv) else None
            # 取变化更大的那个
            iv_ref_type = 'close'
            if iv_chg_close is not None and iv_chg_dyn is not None and abs(iv_chg_dyn) > abs(iv_chg_close):
                iv_chg = iv_chg_dyn
                iv_ref_type = 'reversal'
            else:
                iv_chg = iv_chg_close

            # IV颜色级别 — Call和Put各自独立判定（基于raw IV变化，与前端显示一致）
            sig_t = iv_t['significant'] * 100   # 转为百分点
            ext_t = iv_t.get('extreme', 999) * 100
            def _iv_level_for(iv_cur, iv_prev):
                if iv_cur is None or iv_prev is None or iv_prev == 0:
                    return ''
                # 脏基准过滤：
                # PTA期权正常IV在20-40%（深度OTM除外），baseline偏离当前值1.5倍以上视为脏
                if iv_prev > 60 and iv_cur > 0 and iv_prev > iv_cur * 1.5:
                    return ''
                chg = abs(iv_cur - iv_prev)
                if chg >= ext_t:
                    return 'major'
                if chg >= sig_t:
                    return 'significant'
                return ''
            iv_call_level = _iv_level_for(iv_c, iv_c_b)
            iv_put_level = _iv_level_for(iv_p, iv_p_b)

            # OI变化（比率）
            def oi_chg_ratio(cur, prv):
                if not prv or prv <= 0:
                    return None
                return (cur - prv) / prv

            oi_call = int(cur_oi.get('C', 0))
            oi_put = int(cur_oi.get('P', 0))
            oi_call_b = int(b_oi_s.get('C', 0))
            oi_put_b = int(b_oi_s.get('P', 0))

            oi_chg_call = oi_chg_ratio(oi_call, oi_call_b)
            oi_chg_put = oi_chg_ratio(oi_put, oi_put_b)

            # OI动态基准对比（盘中反转检测）
            def oi_dyn_chg(strike_key, side, cur, base_chg):
                dyn_key = f"{strike_key}_{side}"
                dyn_oi = _oi_alert_dynamic_baseline.get(dyn_key)
                if dyn_oi is not None and dyn_oi > 0:
                    dyn_ratio = (cur - dyn_oi) / dyn_oi
                    if abs(dyn_ratio) > abs(base_chg or 0):
                        return dyn_ratio, 'reversal'
                return base_chg, 'close'

            oi_chg_call_final, oi_call_ref_type = oi_dyn_chg(strike, 'C', oi_call, oi_chg_call)
            oi_chg_put_final, oi_put_ref_type = oi_dyn_chg(strike, 'P', oi_put, oi_chg_put)

            # 兜底：如果 baseline 没有 OI 数据但有 raw IV(prev)，用 raw IV(prev) 作为 IV 前值
            # 用于处理：某些档位（如5300/5400）在前收盘时无数据，现在有数据的情况
            # 注意：b_raw_s.get('C') 为 None 时 (None or 0)*100 = 0，需要还原为 None
            iv_c_b = float(iv_c_b) if iv_c_b is not None else None
            iv_p_b = float(iv_p_b) if iv_p_b is not None else None

            # OI颜色级别（当前OI归零的排除——到期清零不是异动）
            def oi_level(chg, base_oi, cur_oi):
                if chg is None or base_oi <= 0:
                    return ''
                if cur_oi <= 0:
                    return ''  # 持仓归零不报警
                t = _get_oi_thresholds(base_oi)
                abs_c = abs(chg)
                if abs_c >= t['sigLow']:
                    return 'major' if abs_c >= t.get('extreme', 999) else 'significant'
                return ''

            oi_call_level = oi_level(oi_chg_call_final, oi_call_b, oi_call)
            oi_put_level = oi_level(oi_chg_put_final, oi_put_b, oi_put)

            # 记录需要弹窗报警的档位
            if iv_call_level or iv_put_level:
                best_level = 'major' if (iv_call_level == 'major' or iv_put_level == 'major') else 'significant'
                # 弹窗文案：带上触发报警的具体维度（Call/Put raw IV变化），不只是smooth
                iv_call_chg = round(iv_c - iv_c_b, 2) if (iv_c is not None and iv_c_b is not None and iv_c_b != 0) else None
                iv_put_chg = round(iv_p - iv_p_b, 2) if (iv_p is not None and iv_p_b is not None and iv_p_b != 0) else None
                iv_alerts.append({
                    'strike': int(strike), 'level': best_level, 'iv_chg': iv_chg, 'ref_type': iv_ref_type,
                    'iv_call_level': iv_call_level, 'iv_put_level': iv_put_level,
                    'iv_call_chg': iv_call_chg, 'iv_put_chg': iv_put_chg,
                })
            if oi_call_level:
                oi_alerts.append({'strike': int(strike), 'side': 'C', 'level': oi_call_level, 'oi_chg': oi_chg_call_final, 'ref_type': oi_call_ref_type})
            if oi_put_level:
                oi_alerts.append({'strike': int(strike), 'side': 'P', 'level': oi_put_level, 'oi_chg': oi_chg_put_final, 'ref_type': oi_put_ref_type})

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
        """
        GEX (Gamma Exposure) + 疼痛曲线 + OI分布 + 综合摘要。
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
            """根据给定的 strike_oi 字典，计算 gex_bars, pain_curve, oi_dist 及摘要"""
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
            # 2. Pain Curve
            oi_map = {float(k): v for k, v in oi_dict.items()}
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
                days_left = round((expiry - datetime.now()).total_seconds() / 86400, 1)
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

        # ---- 前次基准数据（逻辑与IV Smile曲线完全一致）----
        # 21:00之后（新交易日开盘）：优先 _close_baseline（当天15:00），兜底 _prev_day_baseline
        # 21:00之前（盘后/日盘）：只用 _prev_day_baseline（前一交易日15:00）
        prev_gex_bars, prev_pain_curve, prev_oi_dist, prev_summary = [], [], [], {}
        baseline_label = None
        now_hour = datetime.now().hour
        prev_oi = None
        if now_hour >= 21:
            cb = _close_baseline
            if cb and cb.get('strike_oi'):
                prev_oi = cb['strike_oi']
                baseline_label = '15:00收盘'
            elif _prev_day_baseline and _prev_day_baseline.get('strike_oi'):
                prev_oi = _prev_day_baseline['strike_oi']
                ts = _prev_day_baseline.get('timestamp', '')[:19]
                baseline_label = f'前日15:00 ({ts[5:10]})'
        else:
            if _prev_day_baseline and _prev_day_baseline.get('strike_oi'):
                prev_oi = _prev_day_baseline['strike_oi']
                ts = _prev_day_baseline.get('timestamp', '')[:19]
                baseline_label = f'前日15:00 ({ts[5:10]})'

        if prev_oi and len(prev_oi) > 0:
            prev_gex_bars, prev_pain_curve, prev_oi_dist, prev_summary = _calc_gex_pain_oi(prev_oi)

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


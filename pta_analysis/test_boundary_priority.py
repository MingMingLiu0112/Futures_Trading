"""
场景模拟：4 个休盘点后到下次开盘前的 _state 恢复优先级。

不重启服务，直接 mock 关键函数验证 loader 逻辑。
"""
import json
import sys
import os
import shutil
import tempfile
from datetime import datetime, timedelta

# 设置工作目录
WORKSPACE = '/home/admin/.openclaw/workspace/Futures_Trading/pta_analysis'
os.chdir(WORKSPACE)
sys.path.insert(0, WORKSPACE)

# 备份原 _SNAPSHOT_DIR 指向临时目录，避免污染真实数据
TEST_DIR = tempfile.mkdtemp(prefix='iv_smile_test_')
os.makedirs(os.path.join(TEST_DIR, 'iv_snapshots'), exist_ok=True)
print(f"📂 测试用快照目录: {TEST_DIR}/iv_snapshots")

import iv_smile_service as svc
ORIG_SNAPSHOT_DIR = svc._SNAPSHOT_DIR
ORIG_EOD_FILE = svc._EOD_STATE_FILE
ORIG_CLOSE_FILE = svc._CLOSE_STATE_FILE
svc._SNAPSHOT_DIR = os.path.join(TEST_DIR, 'iv_snapshots')
svc._EOD_STATE_FILE = os.path.join(TEST_DIR, 'iv_snapshots', 'eod_state.json')
svc._CLOSE_STATE_FILE = os.path.join(TEST_DIR, 'iv_snapshots', 'close_state.json')

# 重置 module-level 状态
svc._state = {}
svc._last_valid = {}


def make_boundary_snapshot(key, ts_str, S=6360, ATM=6400, MP=6400):
    """构造一个 close_boundary=True 的 15min 快照"""
    return {
        'smooth': {str(K): 0.2 for K in [6000, 6100, 6200, 6300, 6400, 6500, 6600, 6700, 6800]},
        'raw': {str(K): {'C': 0.2, 'P': 0.2} for K in [6000, 6100, 6200, 6300, 6400, 6500, 6600, 6700, 6800]},
        'timestamp': ts_str,
        'svi_params': {'a': 0.1, 'b': 0.5, 'rho': -0.3, 'm': 0, 'sigma': 0.2, 'skew': -0.1, 'curvature': 0.05},
        'futures_price': S,
        'ref_strike': ATM,
        'max_pain': MP,
        'atm_strike': ATM,
        'strike_oi': {str(K): {'C': 100, 'P': 100} for K in [6000, 6100, 6200, 6300, 6400, 6500, 6600, 6700, 6800]},
        'strike_vol': {str(K): {'C': 10, 'P': 10} for K in [6000, 6100, 6200, 6300, 6400, 6500, 6600, 6700, 6800]},
        'close_boundary': True,
        'note': f'test boundary {key}'
    }


def setup_files(scenario_name, today_date, eod_ts, close_ts, today_boundaries, yesterday_eod_boundary=None):
    """为每个场景准备 iv_snapshots_*.json 和 eod_state.json / close_state.json"""
    # 清理上次残留 (仅在测试目录中)
    for f in os.listdir(svc._SNAPSHOT_DIR):
        if f.startswith('iv_snapshots_') or f in ('eod_state.json', 'close_state.json'):
            os.unlink(os.path.join(svc._SNAPSHOT_DIR, f))

    # 写今日 iv_snapshots (close_boundary 仅在 10:15/11:30/15:00 标记)
    today_path = svc._get_snapshot_path(today_date)
    today_snaps = {}
    CLOSE_KEYS = {'10:15', '11:30', '15:00', '23:00'}
    for key, ts_str in today_boundaries:
        snap = make_boundary_snapshot(key, ts_str)
        # 关键：只有收盘时段的快照才标 close_boundary
        if key not in CLOSE_KEYS:
            snap['close_boundary'] = False
        today_snaps[key] = snap
    with open(today_path, 'w', encoding='utf-8') as f:
        json.dump({'snapshots': today_snaps, 'date': today_date}, f, ensure_ascii=False, indent=2)

    # 写昨日 iv_snapshots (含 23:00 boundary, 用于兜底)
    if yesterday_eod_boundary is None:
        yesterday = (datetime.strptime(today_date, '%Y%m%d') - timedelta(days=1)).strftime('%Y%m%d')
        yesterday_eod_boundary = ('23:00', f'{yesterday[:4]}-{yesterday[4:6]}-{yesterday[6:8]}T23:00:24.921328')
    yesterday_date = yesterday_eod_boundary[1][:10].replace('-', '')
    yesterday_path = svc._get_snapshot_path(yesterday_date)
    with open(yesterday_path, 'w', encoding='utf-8') as f:
        json.dump({'snapshots': {yesterday_eod_boundary[0]: make_boundary_snapshot(yesterday_eod_boundary[0], yesterday_eod_boundary[1])},
                   'date': yesterday_date}, f, ensure_ascii=False, indent=2)

    # 写 eod_state.json
    if eod_ts:
        with open(svc._EOD_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                'eod_point': '23:00',
                'timestamp': eod_ts,
                'state': {
                    'futures_price': 6300,  # EOD 旧值
                    'atm_strike': 6300,
                    'max_pain': 6300,
                    'ref_strike': 6300,
                    'smile_raw': {str(K): {'C': 0.1, 'P': 0.1} for K in [6000, 6100, 6200, 6300, 6400]},
                    'smile_smooth': {str(K): 0.1 for K in [6000, 6100, 6200, 6300, 6400]},
                    'svi_params': {'a': 0.05, 'b': 0.3, 'rho': -0.1, 'm': 0, 'sigma': 0.1, 'skew': 0, 'curvature': 0},
                    'last_update': eod_ts,
                    'strike_oi': {str(K): {'C': 50, 'P': 50} for K in [6000, 6100, 6200, 6300, 6400]},
                    'strike_vol': {str(K): {'C': 5, 'P': 5} for K in [6000, 6100, 6200, 6300, 6400]},
                },
                'last_valid': {}
            }, f, ensure_ascii=False, indent=2)

    # 写 close_state.json
    if close_ts:
        with open(svc._CLOSE_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                'close_point': '15:00',
                'timestamp': close_ts,
                'state': {
                    'futures_price': 6360,  # 与 boundary 一致 (生产中 _save_close_state 用同一个 _state)
                    'atm_strike': 6400,
                    'max_pain': 6400,
                    'ref_strike': 6400,
                    'smile_raw': {str(K): {'C': 0.15, 'P': 0.15} for K in [6000, 6100, 6200, 6300, 6400, 6500, 6600]},
                    'smile_smooth': {str(K): 0.15 for K in [6000, 6100, 6200, 6300, 6400, 6500, 6600]},
                    'svi_params': {'a': 0.08, 'b': 0.4, 'rho': -0.2, 'm': 0, 'sigma': 0.15, 'skew': -0.05, 'curvature': 0.02},
                    'last_update': close_ts,
                    'strike_oi': {str(K): {'C': 80, 'P': 80} for K in [6000, 6100, 6200, 6300, 6400, 6500, 6600]},
                    'strike_vol': {str(K): {'C': 8, 'P': 8} for K in [6000, 6100, 6200, 6300, 6400, 6500, 6600]},
                },
                'last_valid': {}
            }, f, ensure_ascii=False, indent=2)


def run_scenario(scenario_name, today_date, eod_ts, close_ts, today_boundaries, expected_source):
    """运行一个场景，验证 _state 恢复的源"""
    print(f"\n{'='*70}")
    print(f"📋 场景: {scenario_name}")
    print(f"   今日: {today_date}, 期待源: {expected_source}")
    print(f"   EOD ts: {eod_ts}")
    print(f"   Close ts: {close_ts}")
    print(f"   今日边界: {[k for k,_ in today_boundaries]}")
    print(f"{'='*70}")

    setup_files(scenario_name, today_date, eod_ts, close_ts, today_boundaries)

    # 重置状态
    svc._state = {}
    svc._last_valid = {}
    svc._eod_state_loaded = False
    if hasattr(svc, '_interval_snapshots'):
        svc._interval_snapshots = {}

    # 跑 loader
    eod_restored = svc._load_eod_state()
    close_restored = svc._load_close_state()
    boundary_ts, boundary_key, boundary_date = svc._get_latest_close_boundary_timestamp()

    if not eod_restored and eod_ts:
        print(f"   ⏭ EOD 加载被跳过 (边界更新或被 close_state 接管)")
    if not close_restored and close_ts:
        print(f"   ⏭ close_state 加载被跳过 (边界更新或 EOD 已加载)")

    # 模拟 _load_previous_day_snapshots 中的 15min 恢复路径 (L1311-1373)
    # 找 latest_for_restore（今日 iv_snapshots 中 smooth 数据最新的）
    latest_for_restore = None
    latest_for_restore_key = None
    latest_for_restore_ts = None
    today_path = svc._get_snapshot_path(today_date)
    if os.path.exists(today_path):
        try:
            with open(today_path) as f:
                payload = json.load(f)
            for k, v in (payload.get('snapshots') or {}).items():
                if v.get('smooth'):
                    ts = v.get('timestamp', '')
                    if latest_for_restore_ts is None or ts > latest_for_restore_ts:
                        latest_for_restore = v
                        latest_for_restore_key = k
                        latest_for_restore_ts = ts
        except Exception:
            pass

    # 模拟 15min 恢复条件: not close_restored and (is_close_boundary or not eod_restored)
    can_restore = bool(latest_for_restore)
    is_close_boundary = bool(latest_for_restore and latest_for_restore.get('close_boundary'))
    should_restore = can_restore and (is_close_boundary or not eod_restored)
    if not close_restored and should_restore:
        # 恢复 _state (简化版, 只取关键字段)
        svc._state['futures_price'] = latest_for_restore.get('futures_price')
        svc._state['atm_strike'] = latest_for_restore.get('atm_strike')
        svc._state['max_pain'] = latest_for_restore.get('max_pain')
        svc._state['ref_strike'] = latest_for_restore.get('ref_strike')
        svc._state['smile_raw'] = latest_for_restore.get('raw', {})
        svc._state['smile_smooth'] = latest_for_restore.get('smooth', {})
        svc._state['svi_params'] = latest_for_restore.get('svi_params', {})
        svc._state['strike_oi'] = latest_for_restore.get('strike_oi', {})
        svc._state['strike_vol'] = latest_for_restore.get('strike_vol', {})
        svc._state['last_update'] = latest_for_restore_ts
        print(f"   📂 15min 恢复接管: key={latest_for_restore_key} ts={latest_for_restore_ts[:19]}")

    # 打印 _state
    state_F = svc._state.get('futures_price')
    state_lu = svc._state.get('last_update')
    print(f"   → _state.futures_price = {state_F}")
    print(f"   → _state.last_update   = {state_lu}")

    # 验证
    if state_F is None:
        print(f"   ❌ _state 未恢复")
        return False

    # 比对 expected_source
    if expected_source == 'eod':
        ok = abs(state_F - 6300) < 1
    elif expected_source == 'close_15':
        ok = abs(state_F - 6340) < 1
    elif expected_source.startswith('boundary_'):
        # 取对应 key 的 futures_price (boundary 默认 F=6360)
        target_key = expected_source.replace('boundary_', '')
        for k, ts in today_boundaries:
            if k == target_key:
                ok = abs(state_F - 6360) < 1
                break
        else:
            ok = False
    else:
        ok = False

    status = "✅" if ok else "❌"
    print(f"   {status} 验证 {'通过' if ok else '失败'}")
    return ok


# ========== 运行 6 个场景 ==========
# 用真实的 now 日期（_get_latest_close_boundary_timestamp 用 datetime.now 找"今天"）
from datetime import datetime as _dt
NOW_DT = _dt.now()
TODAY = NOW_DT.strftime('%Y%m%d')
YESTERDAY = (NOW_DT - timedelta(days=1)).strftime('%Y%m%d')

# 各场景的边界 timestamp 模板（用真实 today 的日期）
def ts(hh, mm):
    return f'{TODAY[:4]}-{TODAY[4:6]}-{TODAY[6:8]}T{hh:02d}:{mm:02d}:30.000000'
def yts(hh, mm):
    return f'{YESTERDAY[:4]}-{YESTERDAY[4:6]}-{YESTERDAY[6:8]}T{hh:02d}:{mm:02d}:30.000000'

# 场景 1: 早盘 09:30 启动 (无今日边界) → 应恢复 EOD
r1 = run_scenario(
    "09:30 早盘启动 (无今日边界)",
    TODAY,
    eod_ts=yts(23, 0),
    close_ts=yts(15, 0),
    today_boundaries=[('09:00', ts(9, 0))],
    expected_source='eod'
)

# 场景 2: 10:30 启动 (有 10:15 边界) → 应恢复 10:15 边界
r2 = run_scenario(
    "10:30 早盘启动 (有 10:15 边界)",
    TODAY,
    eod_ts=yts(23, 0),
    close_ts=yts(15, 0),
    today_boundaries=[
        ('09:00', ts(9, 0)),
        ('10:15', ts(10, 15)),
        ('10:30', ts(10, 30)),
    ],
    expected_source='boundary_10:15'
)

# 场景 3: 12:00 午休启动 (有 10:15 + 11:30 边界) → 应恢复 11:30 边界
r3 = run_scenario(
    "12:00 午休启动 (有 11:30 边界)",
    TODAY,
    eod_ts=yts(23, 0),
    close_ts=yts(15, 0),
    today_boundaries=[
        ('10:15', ts(10, 15)),
        ('11:30', ts(11, 30)),
    ],
    expected_source='boundary_11:30'
)

# 场景 4: 16:00 下午盘后启动 (有 15:00 边界) → 应恢复 15:00 边界
r4 = run_scenario(
    "16:00 下午盘后启动 (有 15:00 边界, 夜盘未开)",
    TODAY,
    eod_ts=yts(23, 0),
    close_ts=ts(15, 0),  # 今日 15:00 close
    today_boundaries=[
        ('10:15', ts(10, 15)),
        ('11:30', ts(11, 30)),
        ('15:00', ts(15, 0)),
    ],
    expected_source='boundary_15:00'
)

# 场景 5: 22:00 夜盘运行中 (15:00 边界是最近的) → 应恢复 15:00 边界
r5 = run_scenario(
    "22:00 夜盘运行中 (15:00 仍是最近边界)",
    TODAY,
    eod_ts=yts(23, 0),
    close_ts=ts(15, 0),
    today_boundaries=[
        ('10:15', ts(10, 15)),
        ('11:30', ts(11, 30)),
        ('15:00', ts(15, 0)),
        ('21:00', ts(21, 0)),
        ('21:15', ts(21, 15)),
        ('21:30', ts(21, 30)),
    ],
    expected_source='boundary_15:00'
)

# 场景 6: 次日 06:00 模拟 - 用 fake 模式：把 _eod_state_loaded 设为 False
# 这里直接在脚本里 hardcode 行为：把 EOD ts 设为真实 today 的 23:00，验证次日
# 由于 datetime.now 是真实的，今天就是 2026-06-13，昨天的 23:00 在 7 天内会被接受
r6 = run_scenario(
    "盘后/夜盘启动 (有昨日 23:00 EOD + 23:00 boundary)",
    TODAY,
    eod_ts=yts(23, 0),
    close_ts=yts(15, 0),
    today_boundaries=[],  # 今日无边界（盘后启动 / 夜盘开盘前）
    expected_source='eod'
)

print(f"\n{'='*70}")
print(f"📊 总览: {sum([r1,r2,r3,r4,r5,r6])}/6 场景通过")
print(f"{'='*70}")

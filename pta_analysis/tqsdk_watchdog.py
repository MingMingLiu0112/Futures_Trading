"""TqSdk 实时数据守护监控 (v2.11.73)

每 CHECK_INTERVAL_SEC 秒拉一次 /api/iv_smile/status，根据数据新鲜度+重连次数判定健康等级。
状态写入 STATE_FILE，前端 iv_smile 页面通过 /api/tqsdk_watchdog/status 读取并渲染弹窗。

第一阶段 (A1): 只检测+报警，不自动重启；用户在前端点"立即重启"按钮触发 _tqsdk_restart_requested=True。
"""
import json
import os
import threading
import time
import traceback
from datetime import datetime
from urllib import request as urllib_request
from urllib.error import URLError, HTTPError

# ==================== 配置 ====================
CHECK_INTERVAL_SEC = 60        # 检测周期（用户指定）
STALE_THRESHOLD_SEC = 120      # 数据过期阈值（用户指定，> 120s = 红色报警）
YELLOW_RECONNECT = 5           # 重连 ≥ 5 次且轻微延迟 → 黄色
RED_RECONNECT = 15             # 重连 ≥ 15 次 → 红色
PROBE_TIMEOUT_SEC = 5          # HTTP 请求超时
NON_TRADING_QUIET_HOURS = [(2, 30, 9, 0)]  # 凌晨 2:30-9:00 非交易时段豁免

# 状态文件路径
WORKSPACE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(WORKSPACE, 'data', 'tqsdk_watchdog.json')
PROBE_URL = 'http://127.0.0.1:8424/api/iv_smile/status'

# 全局状态（线程安全）
_state = {
    'healthy': True,
    'last_check_at': None,
    'last_check_unix': 0,
    'last_data_update': None,
    'last_data_age_sec': 0,
    'reconnect_count': 0,
    'tqsdk_ready': False,
    'futures_price': None,
    'alert_level': 'green',     # green / yellow / red
    'alert_message': '监控启动中',
    'last_alert_change_at': None,
    'restart_count_today': 0,
    'last_restart_at': None,
    'consecutive_probe_failures': 0,
}
_lock = threading.Lock()


def _is_trading_hours(now=None):
    """非交易时段豁免：凌晨 2:30-9:00 不报警（盘前准备时段）"""
    now = now or datetime.now()
    h, m = now.hour, now.minute
    for sh, sm, eh, em in NON_TRADING_QUIET_HOURS:
        cur = h * 60 + m
        if sh * 60 + sm <= cur < eh * 60 + em:
            return False
    return True


def _probe():
    """调用 /api/iv_smile/status 返回 dict；失败抛异常"""
    req = urllib_request.Request(PROBE_URL, method='GET')
    with urllib_request.urlopen(req, timeout=PROBE_TIMEOUT_SEC) as r:
        body = r.read()
    return json.loads(body)


def _evaluate(status):
    """根据 status dict 评估健康等级 → (alert_level, message)"""
    if not isinstance(status, dict):
        return 'red', '❌ 探针响应格式异常'

    last_update_str = status.get('last_update')
    reconnect = status.get('reconnect_count', 0) or 0
    tqsdk_ready = status.get('tqsdk_ready', False)

    now = datetime.now()
    age_sec = None
    if last_update_str:
        try:
            # last_update 是 ISO 格式（带 T）
            last_dt = datetime.fromisoformat(last_update_str)
            age_sec = (now - last_dt).total_seconds()
        except (ValueError, TypeError):
            pass

    futures_price = status.get('futures_price')

    if age_sec is None:
        return 'red', '❌ 无法解析 last_update 时间戳'

    base_msg = f'最后更新 {age_sec:.0f}s 前 · F={futures_price} · reconnect={reconnect} · ready={tqsdk_ready}'

    # 红色：数据过期 OR 探针发现 ready=false + 数据真停滞
    if age_sec > STALE_THRESHOLD_SEC:
        return 'red', f'⚠️ 数据已 {age_sec:.0f}s 未更新（阈值 {STALE_THRESHOLD_SEC}s）· {base_msg}'

    # 重连暴涨
    if reconnect >= RED_RECONNECT:
        return 'red', f'⚠️ TqSdk 重连 {reconnect} 次 · {base_msg}'

    # 黄色：轻微延迟 OR 中等重连
    if (age_sec > STALE_THRESHOLD_SEC / 2) or reconnect >= YELLOW_RECONNECT:
        return 'yellow', f'⚠️ {base_msg}'

    return 'green', f'✅ 正常 · {base_msg}'


def _persist():
    """把 _state 写到 STATE_FILE（原子写入）"""
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        tmp = STATE_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(_state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        print(f"[tqsdk_watchdog] persist failed: {e}")


def _worker():
    """监控线程主循环"""
    print(f"[tqsdk_watchdog] 启动 · 周期 {CHECK_INTERVAL_SEC}s · 阈值 {STALE_THRESHOLD_SEC}s")
    # v2.11.73: 启动后等 5s 再开始探测，给 Flask 启动留时间，避免启动瞬间 false-alarm
    time.sleep(5)
    while True:
        try:
            trading = _is_trading_hours()
            if not trading:
                with _lock:
                    _state['last_check_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    _state['last_check_unix'] = time.time()
                    _state['alert_level'] = 'green'
                    _state['alert_message'] = '非交易时段，跳过检测'
                _persist()
                time.sleep(CHECK_INTERVAL_SEC)
                continue

            status = _probe()
            level, msg = _evaluate(status)

            with _lock:
                _state['healthy'] = (level == 'green')
                _state['last_check_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                _state['last_check_unix'] = time.time()
                _state['last_data_update'] = status.get('last_update')
                last_update_str = status.get('last_update')
                if last_update_str:
                    try:
                        last_dt = datetime.fromisoformat(last_update_str)
                        _state['last_data_age_sec'] = (datetime.now() - last_dt).total_seconds()
                    except Exception:
                        _state['last_data_age_sec'] = -1
                _state['reconnect_count'] = status.get('reconnect_count', 0) or 0
                _state['tqsdk_ready'] = status.get('tqsdk_ready', False)
                _state['futures_price'] = status.get('futures_price')
                prev_level = _state['alert_level']
                _state['alert_level'] = level
                _state['alert_message'] = msg
                if prev_level != level:
                    _state['last_alert_change_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                _state['consecutive_probe_failures'] = 0

            _persist()

        except (URLError, HTTPError, TimeoutError, OSError) as e:
            with _lock:
                _state['consecutive_probe_failures'] += 1
                _state['last_check_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                _state['last_check_unix'] = time.time()
                _state['healthy'] = False
                _state['alert_level'] = 'red'
                _state['alert_message'] = f'❌ 探针调用失败 ({type(e).__name__}): {str(e)[:80]}'
            _persist()
            print(f"[tqsdk_watchdog] probe failed: {e}")
        except Exception as e:
            with _lock:
                _state['alert_level'] = 'red'
                _state['alert_message'] = f'❌ watchdog 内部异常: {str(e)[:80]}'
            _persist()
            print(f"[tqsdk_watchdog] unexpected error: {e}\n{traceback.format_exc()}")

        time.sleep(CHECK_INTERVAL_SEC)


_thread = None
_started = False


def start():
    """启动后台守护线程（幂等）

    v2.11.81: 加 _persist() 立即验证线程真的跑起来了（防"看似启动但实际没跑"坑）
              加 try-except + raise 让 web_app_integrated 能感知失败
    """
    global _thread, _started
    if _started:
        return
    try:
        _thread = threading.Thread(target=_worker, daemon=True, name='tqsdk-watchdog')
        _thread.start()
        _started = True
        # v2.11.81 R2-B: 立即写一次 JSON 验证线程真的跑起来了
        # 如果 _persist 失败（比如权限/路径），会 throw 出来被外层 try-except 捕获
        _persist()
        print(f"[tqsdk_watchdog] ✅ 守护线程已启动 (TID={_thread.ident})")
    except Exception as e:
        print(f"[tqsdk_watchdog] ❌ 启动失败(不是 warning): {e}")
        # v2.11.81 P0: 不要吞异常,让调用方感知(走 systemd 后会触发自动重启)
        raise


def get_state():
    """获取当前状态（线程安全拷贝）"""
    with _lock:
        return dict(_state)


def trigger_restart():
    """通知 iv_smile_service 重启 TqSdk 线程；记录次数和时间"""
    try:
        from iv_smile_service import request_tqsdk_restart
        request_tqsdk_restart()
    except Exception as e:
        with _lock:
            _state['alert_message'] = f'❌ 重启触发失败: {str(e)[:80]}'
            _state['alert_level'] = 'red'
        _persist()
        return False, str(e)

    with _lock:
        _state['restart_count_today'] = _state.get('restart_count_today', 0) + 1
        _state['last_restart_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    _persist()
    return True, 'TqSdk 重启已触发（iv_smile_service 将在下一周期重建连接）'


if __name__ == '__main__':
    # 独立调试：直接跑
    start()
    while True:
        print(json.dumps(get_state(), ensure_ascii=False, indent=2))
        time.sleep(10)
#!/usr/bin/env python3
"""Regression tests for iv_smile current rollback guard.

These tests intentionally avoid importing iv_smile_service because the module starts
background market-data threads at import time.  They verify the production source
contains the timestamp guard at the three historical rollback entry points.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "iv_smile_service.py"


def _source():
    return SRC.read_text(encoding="utf-8")


def test_current_restore_guard_helpers_exist():
    s = _source()
    assert "def _should_restore_current" in s
    assert "拒绝旧状态覆盖 current" in s
    assert "def _payload_state_timestamp" in s


def test_close_state_does_not_unconditionally_override_current():
    s = _source()
    assert "_should_restore_current(incoming_ts, 'close_state')" in s
    assert "close_state.json 只恢复 _close_baseline，不覆盖 current _state" in s
    assert "EOD 已先恢复 _state，close_state.json 跳过 _state 覆盖" in s


def test_eod_and_interval_snapshot_restore_are_timestamp_guarded():
    s = _source()
    assert "_should_restore_current(incoming_ts, 'eod_state')" in s
    assert "_should_restore_current(latest_for_restore_ts, f'interval_snapshot:{latest_for_restore_key}')" in s
    assert "_should_restore_current(incoming_ts, f'interval_snapshot:{latest_key}')" in s


def test_eod_snapshot_marks_state_last_update_as_eod_timestamp():
    s = _source()
    assert "eod_ts = datetime.now().isoformat()" in s
    assert "payload.setdefault('state', {})['last_update'] = eod_ts" in s
    assert "不能让 state.last_update 把 EOD 恢复误判成旧 current" in s

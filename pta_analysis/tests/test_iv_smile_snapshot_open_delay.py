from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "iv_smile_service.py"


def _service_text():
    return SERVICE.read_text(encoding="utf-8", errors="replace")


def test_opening_first_minute_snapshot_guard_exists():
    text = _service_text()
    assert "def _is_opening_first_minute" in text
    assert "_PTA_OPEN_TIMES" in text
    assert "return (now.hour, now.minute) in _PTA_OPEN_TIMES" in text


def test_compute_once_skips_snapshot_during_opening_first_minute():
    text = _service_text()
    assert "if _is_opening_first_minute(now):" in text
    assert "跳过开盘首分钟快照" in text
    assert "interval_key = None" in text
    assert "elif interval_key in _interval_snapshots:" in text

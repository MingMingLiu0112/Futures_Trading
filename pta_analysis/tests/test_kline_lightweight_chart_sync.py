from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "kline_lightweight.html"


def _text():
    return TEMPLATE.read_text(encoding="utf-8")


def _function_body(text, name):
    m = re.search(rf"function {name}\([^)]*\) \{{(?P<body>.*?)\n        \}}", text, re.S)
    assert m, f"{name} function not found"
    return m.group("body")


def test_resize_preserves_visible_range_instead_of_fit_content():
    text = _text()
    m = re.search(r"window\.addEventListener\('resize', \(\) => \{(?P<body>.*?)\n            \}\);", text, re.S)
    assert m, "resize handler not found"
    body = m.group("body")
    assert "preserveAndSyncVisibleRange" in body
    assert ".fitContent()" not in body


def test_main_chart_has_single_range_sync_subscription():
    text = _text()
    # 主图时间轴同步只能有一个，避免重复订阅/竞态；MACD标注重绘应合并进去。
    assert text.count("mainChart.timeScale().subscribeVisibleLogicalRangeChange") == 1
    assert "syncChartsToVisibleRange(mainChart);" in text
    assert "drawMacdWaveLabels" in text


def test_incremental_update_maintains_data_indicators_and_realtime_follow():
    text = _text()
    body = _function_body(text, "incrementalUpdate")
    assert "const wasAtRealtime = isAtRealtime();" in body
    assert "upsertLatestKlineBar(lastNew);" in body
    assert "calculateAndDrawMACD();" in body
    assert "calculateAndDrawKDJ();" in body
    assert "syncChartsToVisibleRange(mainChart);" in body
    assert "scrollChartsToRealTime();" in body

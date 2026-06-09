
import re
from pathlib import Path


HTML = Path(__file__).resolve().parents[1] / "templates" / "iv_smile.html"


def _script_text():
    return HTML.read_text(encoding="utf-8", errors="replace")


def test_smile_chart_has_atm_window_filter_helper():
    text = _script_text()
    assert "function filterSmileCurveAroundAtm" in text
    assert "const ATM_WINDOW_SIZE = 15" in text


def test_update_smile_chart_uses_filtered_window_not_full_curve_for_xaxis():
    text = _script_text()
    m = re.search(r"function updateSmileChart\(data\) \{(?P<body>.*?)\n\}\n\n// 更新指标栏", text, re.S)
    assert m, "updateSmileChart function block not found"
    body = m.group("body")
    assert "filterSmileCurveAroundAtm(curve, data.atm_strike, ATM_WINDOW_SIZE)" in body
    assert "const sorted = filterSmileCurveAroundAtm" in body
    assert "const sorted = [...curve].sort" not in body
    assert "const atmNum = Number(data.atm_strike);" in body
    assert "Number(d.strike) > atmNum" in body
    assert "Number(d.strike) < atmNum" in body
    assert "const callData = sorted.map(d => (Number(d.strike) > atmNum" in body
    assert "const putData = sorted.map(d => (Number(d.strike) < atmNum" in body


def test_smile_window_does_not_backfill_deep_wings_to_force_31_points():
    text = _script_text()
    m = re.search(r"function filterSmileCurveAroundAtm\(curve, atmStrike, windowSize = ATM_WINDOW_SIZE\) \{(?P<body>.*?)\n\}\n\nfunction updateSmileChart", text, re.S)
    assert m, "filterSmileCurveAroundAtm function block not found"
    body = m.group("body")
    assert "sorted.slice(start, end)" in body
    assert "maxPoints" not in body
    assert "如果一侧不足15档，用另一侧补足" not in body


def test_smile_chart_does_not_depend_on_gex_or_oi_domain():
    text = _script_text()
    m = re.search(r"function updateSmileChart\(data\) \{(?P<body>.*?)\n\}\n\n// 更新指标栏", text, re.S)
    assert m, "updateSmileChart function block not found"
    body = m.group("body")
    assert "gexData" not in body
    assert "oi_dist" not in body
    assert "updateSmileChart(data);" in text
    assert "updateSmileChart(data, gexData);" not in text

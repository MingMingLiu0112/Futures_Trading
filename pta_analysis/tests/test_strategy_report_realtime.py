from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "kline_lightweight.html"
WEB_APP = ROOT / "web_app_integrated.py"
REPORT_SCRIPT = ROOT / "scripts" / "generate_daily_report.py"


def test_daily_report_frontend_uses_cached_realtime_api_by_default():
    """研报面板默认加载不能强制refresh=1，否则外部数据慢会卡住页面。"""
    src = TEMPLATE.read_text(encoding="utf-8")
    m = re.search(r"async function loadDailyReport\([^)]*\) \{(?P<body>.*?)\n\s*async function refreshStrategyReport", src, re.S)
    assert m, "loadDailyReport function not found"
    body = m.group("body")
    assert "/api/daily_report?refresh=1" not in body
    assert "/api/strategy_report/realtime" in src
    assert "fetch(endpoint)" in body or "fetchWithTimeout(endpoint" in body
    assert "Promise.allSettled" in body
    assert "fetchWithTimeout('/api/fundamental'" in body
    assert "async function refreshStrategyReport" in src
    assert "/api/strategy_report/refresh" in src


def test_daily_report_api_has_15min_cache_and_close_report_support():
    """后端需要15分钟滚动缓存，并支持15:00后全天总研报。"""
    web = WEB_APP.read_text(encoding="utf-8")
    script = REPORT_SCRIPT.read_text(encoding="utf-8")
    assert "STRATEGY_REPORT_CACHE_MINUTES = 15" in web
    assert "/api/strategy_report/realtime" in web
    assert "/api/strategy_report/refresh" in web
    assert "/api/strategy_report/daily" in web
    assert "generate_close_report" in script
    assert "report_type" in script
    assert "market_session" in script
    assert "_trigger_strategy_report_background_refresh" in web
    assert "页面请求不再等待外部宏观/基本面抓取" in web
    assert "15:00收盘后生成全天总研报" in web
    assert "is_today and dt_datetime.now().hour < 15" in web


def test_intraday_analysis_schema_and_price_basis_are_generated():
    """新研报主展示必须是连续盘中综合研判，并拆分期权标的价和主页K线主力价。"""
    script = REPORT_SCRIPT.read_text(encoding="utf-8")
    assert "generate_intraday_analysis" in script
    assert "intraday_analysis" in script
    assert "option_underlying_price" in script
    assert "main_futures_price" in script
    assert "price_basis_note" not in script[script.index("def generate_intraday_analysis"):script.index("def generate_close_report")]
    assert "期权链标的参考价" in script
    assert "盘面主力参考价" in script
    assert "期货盘面" in script
    assert "期权结构" in script
    assert "宏观基本面" in script
    assert "report['intraday_analysis'] = intraday_analysis" in script
    assert "report['market_brief'] = intraday_analysis" in script
    assert "report['narrative_report'] = intraday_analysis.get('narrative')" in script


def test_strategy_text_does_not_use_ambiguous_price_label():
    """新成文研判不能再输出模糊的'价格6434'，策略段也要说明使用的是期权口径。"""
    script = REPORT_SCRIPT.read_text(encoding="utf-8")
    assert "期权链/期权服务标的价{pta_price:.0f}" in script
    assert "core_parts.append(f'价格{pta_price:.0f}" not in script


def test_intraday_analysis_requires_detailed_template_sections():
    """盘中综合研判必须是详尽版：类似人工盘中解答，包含分段、表格、关键价位和操作思路。"""
    script = REPORT_SCRIPT.read_text(encoding="utf-8")
    required = [
        "当前市场判断：",
        "1. 期货价格层面",
        "2. GEX结构",
        "3. Max Pain",
        "4. 持仓结构",
        "5. IV结构",
        "6. 基本面与宏观",
        "综合结论",
        "关键价位",
        "操作思路",
        "如果偏交易期货",
        "如果偏期权卖方",
        "如果偏买方",
        "一句话总结",
        "pain_curve",
        "oi_dist",
        "iv_rows",
        "top_put_oi",
        "top_call_oi",
    ]
    for text in required:
        assert text in script


def test_frontend_prioritizes_intraday_analysis_over_legacy_sections():
    """前端主展示优先渲染新成文研报字段；旧section1/2/3仅作兜底。"""
    src = TEMPLATE.read_text(encoding="utf-8")
    assert "const intraday = d.intraday_analysis || d.market_brief" in src
    assert "renderIntradayAnalysis" in src
    render_src = src[src.index("function renderIntradayAnalysis"):src.index("function legacyDailyReport")]
    assert "价格口径" not in render_src
    assert "option_underlying_price" in src
    assert "main_futures_price" in src
    assert "legacyDailyReport" in src
    assert src.index("renderIntradayAnalysis") < src.index("legacyDailyReport")



def test_intraday_report_is_trader_facing_not_engineering_jargon():
    """盘中研报正文面向交易员：不能再出现接口/路径/口径等工程话术和错误主力价标题。"""
    script = REPORT_SCRIPT.read_text(encoding="utf-8")
    bad_phrases = [
        "产业链/郑商所主力价",
        "首页K线接口当前价",
        "当前接口存在一个重要口径差异",
        "接口提示",
        "价格口径",
        "路径",
        "/api/",
    ]
    intraday_src = script[script.index("def generate_intraday_analysis"):script.index("def generate_close_report")]
    for phrase in bad_phrases:
        assert phrase not in intraday_src
    assert "盘面主力参考价" in intraday_src
    assert "期权链标的参考价" in intraday_src


def test_intraday_analysis_outputs_structured_tables_and_three_strategy_blocks():
    """后端需给前端结构化表格/三类策略，而不是只给一大段 narrative 平铺。"""
    script = REPORT_SCRIPT.read_text(encoding="utf-8")
    intraday_src = script[script.index("def generate_intraday_analysis"):script.index("def generate_close_report")]
    required = [
        "market_snapshot_table",
        "gex_table",
        "pain_table",
        "oi_tables",
        "iv_table",
        "macro_news_items",
        "strategy_blocks",
        "futures_strategy",
        "option_seller_strategy",
        "option_buyer_strategy",
    ]
    for text in required:
        assert text in intraday_src
    assert "库存" not in intraday_src
    assert "开工率" not in intraday_src


def test_frontend_renders_intraday_tables_cleanly_without_price_basis_line():
    """前端新主展示应使用清爽表格/分区渲染，不再显示价格口径说明行。"""
    src = TEMPLATE.read_text(encoding="utf-8")
    render_src = src[src.index("function renderIntradayAnalysis"):src.index("function legacyDailyReport")]
    assert "renderReportTable" in render_src
    assert "market_snapshot_table" in render_src
    assert "strategy_blocks" in render_src
    assert "option-seller" in render_src or "option_seller_strategy" in render_src
    assert "价格口径" not in render_src
    assert "price_basis_note" not in render_src


def test_intraday_snapshot_archive_and_daily_comparison_are_supported():
    """支持盘中15分钟快照归档、15:00后全天报告聚合，并与前一交易日动态对比。"""
    web = WEB_APP.read_text(encoding="utf-8")
    script = REPORT_SCRIPT.read_text(encoding="utf-8")
    required_script = [
        "INTRADAY_REPORT_DIR",
        "save_intraday_snapshot",
        "load_intraday_snapshots",
        "load_previous_trading_day_close_report",
        "build_daily_comparison",
        "intraday_snapshots",
        "previous_day_comparison",
    ]
    for text in required_script:
        assert text in script
    required_web = [
        "save_intraday_snapshot",
        "load_intraday_snapshots",
        "previous_day_comparison",
        "_maybe_write_close_report",
    ]
    for text in required_web:
        assert text in web



def test_main_futures_reference_uses_kline_price_not_fundamental_ta609():
    """盘面主力参考价必须来自K线当前价，不能混用产业链/fundamental里的TA609结算价。"""
    script = REPORT_SCRIPT.read_text(encoding="utf-8")
    intraday_src = script[script.index("def generate_intraday_analysis"):script.index("def generate_close_report")]
    assert "dominant_contract = pta.get('dominant_contract')" not in intraday_src
    assert "dominant_price = pta.get('dominant_price')" not in intraday_src
    assert "main_futures_label" in intraday_src
    assert "main_futures_price" in intraday_src
    assert "盘面主力参考价" in intraday_src


def test_macro_news_filters_empty_warehouse_receipt_titles():
    """宏观快讯过滤只有标题没有内容、且与PTA无关的仓单日报噪音。"""
    script = REPORT_SCRIPT.read_text(encoding="utf-8")
    intraday_src = script[script.index("def generate_intraday_analysis"):script.index("def generate_close_report")]
    assert "_clean_news_text" in intraday_src
    assert "仓单日报" in script
    assert "广州期货交易所" in script


def test_intraday_report_has_interpretation_fields_after_tables():
    """表格后必须有数据内涵解释，用来衔接后续策略建议。"""
    script = REPORT_SCRIPT.read_text(encoding="utf-8")
    intraday_src = script[script.index("def generate_intraday_analysis"):script.index("def generate_close_report")]
    for key in ["market_snapshot_interpretation", "gex_interpretation", "oi_interpretation", "iv_interpretation", "macro_interpretation", "strategy_logic"]:
        assert key in intraday_src
    template = TEMPLATE.read_text(encoding="utf-8")
    render_src = template[template.index("function renderIntradayAnalysis"):template.index("function legacyDailyReport")]
    assert "renderInterpretation" in render_src
    assert "strategy_logic" in render_src


def test_after_market_frontend_loads_daily_close_report_by_default():
    """盘后首页默认加载全天综合日报，而不是继续只显示盘中缓存。"""
    src = TEMPLATE.read_text(encoding="utf-8")
    assert "getStrategyReportEndpoint" in src
    assert "/api/strategy_report/daily" in src
    assert "/api/strategy_report/realtime" in src



def test_close_report_cache_rebuilds_when_old_ta609_or_missing_logic():
    """旧综合日报缓存含TA609/仓单日报或缺少解释闭环时必须自动重建。"""
    web = WEB_APP.read_text(encoding="utf-8")
    assert "def _close_report_needs_rebuild" in web
    fn = web[web.index("def _close_report_needs_rebuild"):web.index("def _trigger_strategy_report_background_refresh")]
    for term in ["TA609", "广州期货交易所", "仓单日报", "strategy_logic", "market_snapshot_interpretation"]:
        assert term in fn



def test_close_report_comparison_declares_data_coverage_limitations():
    """盘后综合日报必须说明日内快照和前日总报是否充足，不能假装完整动态对比。"""
    script = REPORT_SCRIPT.read_text(encoding="utf-8")
    fn = script[script.index("def build_daily_comparison"):script.index("def generate_close_report")]
    for key in ["intraday_coverage_status", "previous_day_available", "comparison_quality", "data_limitation_note"]:
        assert key in fn
    assert "样本不足" in fn
    assert "前一交易日收盘研报暂缺" in fn



def test_frontend_renders_close_report_comparison_quality_note():
    """首页盘后综合日报要展示日内/日间对比覆盖度提示。"""
    template = TEMPLATE.read_text(encoding="utf-8")
    render_src = template[template.index("function renderIntradayAnalysis"):template.index("function legacyDailyReport")]
    for key in ["previous_day_comparison", "comparison_quality", "data_limitation_note", "intraday_coverage_status"]:
        assert key in render_src



def test_strategy_report_export_endpoint_and_frontend_button_exist():
    """研报与策略支持一键导出存档。"""
    web = WEB_APP.read_text(encoding="utf-8")
    assert "/api/strategy_report/export" in web
    assert "Content-Disposition" in web
    assert "text/markdown" in web
    assert "format_strategy_report_markdown" in web

    template = TEMPLATE.read_text(encoding="utf-8")
    assert "exportStrategyReport" in template
    assert "导出Word" in template
    assert "/api/strategy_report/export" in template



def test_strategy_report_export_supports_word_docx():
    """研报导出默认支持Word docx格式，同时保留Markdown。"""
    web = WEB_APP.read_text(encoding="utf-8")
    assert "format_strategy_report_docx" in web
    assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in web
    assert ".docx" in web
    template = TEMPLATE.read_text(encoding="utf-8")
    assert "format=docx" in template
    assert "导出Word" in template



def test_export_does_not_add_extra_strategy_logic_section():
    """导出版不要额外新增前端没有的“策略逻辑闭环”独立章节。"""
    web = WEB_APP.read_text(encoding="utf-8")
    formatter = web[web.index("def format_strategy_report_markdown"):web.index("def _xml_escape")]
    assert "策略逻辑闭环" not in formatter
    assert "策略依据" in formatter



def test_frontend_integrates_strategy_logic_into_strategy_section():
    """前端完整展示策略逻辑，但应并入操作策略区，不另起独立逻辑块。"""
    template = TEMPLATE.read_text(encoding="utf-8")
    render_src = template[template.index("function renderIntradayAnalysis"):template.index("function legacyDailyReport")]
    assert "intraday.strategy_logic" in render_src
    assert "策略依据" in render_src
    assert "renderInterpretation(intraday.strategy_logic)" not in render_src



def test_frontend_renders_same_rich_sections_as_export():
    """前端展示应覆盖导出中的叙述和日内快照，但叙述应融合到相关解读。"""
    template = TEMPLATE.read_text(encoding="utf-8")
    render_src = template[template.index("function renderIntradayAnalysis"):template.index("function legacyDailyReport")]
    assert "splitNarrativeNotes" in render_src
    assert "综合摘要" in render_src
    assert "日内15分钟快照摘要" in render_src
    assert "reportData.intraday_snapshots" in render_src
    assert "narrative_notes" in render_src
    assert "splitNarrativeNotes(narrative)" not in render_src
    assert "综合叙述" not in render_src



def test_narrative_is_merged_into_related_interpretations_not_big_block():
    """综合叙述应拆入相关表后解读，避免前端/导出出现臃肿独立大段。"""
    template = TEMPLATE.read_text(encoding="utf-8")
    render_src = template[template.index("function renderIntradayAnalysis"):template.index("function legacyDailyReport")]
    assert "splitNarrativeNotes" in render_src
    assert "combinedInterpretation" in render_src
    assert "narrativeNotes.gex" in render_src
    assert "narrativeNotes.macro" in render_src
    assert "narrativeNotes.strategy" in render_src or "narrativeNotes['strategy']" in render_src
    assert "综合摘要" in render_src
    assert "综合叙述" not in render_src

    web = WEB_APP.read_text(encoding="utf-8")
    formatter = web[web.index("def format_strategy_report_markdown"):web.index("def _xml_escape")]
    assert "_split_narrative_notes" in formatter
    assert "narrative_notes.get('gex')" in formatter
    assert "narrative_notes.get('macro')" in formatter
    assert "综合摘要" in formatter
    assert "add_text('综合叙述'" not in formatter


def test_strategy_notes_do_not_slice_full_narrative_into_fragments():
    """策略依据不应从整篇叙述/Markdown表格硬切，避免残片和无用文本。"""
    template = TEMPLATE.read_text(encoding="utf-8")
    render_src = template[template.index("function renderIntradayAnalysis"):template.index("function legacyDailyReport")]
    assert "intraday.narrative_notes" in render_src
    assert "splitNarrativeNotes(narrative)" not in render_src
    assert "reportData.narrative_report" not in render_src

    web = WEB_APP.read_text(encoding="utf-8")
    formatter = web[web.index("def format_strategy_report_markdown"):web.index("def _xml_escape")]
    assert "ia.get('narrative_notes')" in formatter
    assert "_split_narrative_notes(ia.get('narrative')" not in formatter
    assert "_split_narrative_notes(report.get('narrative_report')" not in formatter


def test_intraday_snapshots_only_in_pta_trading_sessions():
    """15分钟盘中快照只能在PTA交易时段产生，盘后/休盘不能写入。"""
    import sys
    from datetime import datetime
    sys.path.insert(0, str(ROOT))
    from scripts.generate_daily_report import _is_pta_trading_session, save_intraday_snapshot, _slot_is_pta_trading_session

    assert _is_pta_trading_session(datetime(2026, 6, 9, 9, 15)) is True
    assert _is_pta_trading_session(datetime(2026, 6, 9, 14, 45)) is True
    assert _is_pta_trading_session(datetime(2026, 6, 9, 21, 15)) is True
    assert _is_pta_trading_session(datetime(2026, 6, 9, 15, 30)) is False
    assert _is_pta_trading_session(datetime(2026, 6, 9, 20, 30)) is False
    assert _slot_is_pta_trading_session('0915') is True
    assert _slot_is_pta_trading_session('1530') is False
    assert save_intraday_snapshot({'x': 1}, now=datetime(2026, 6, 9, 15, 30)) is None


def test_manual_macro_input_is_supported_and_prioritized():
    """用户盘前/休盘后补充的宏观基本面应有固定入口，并优先于自动快讯。"""
    web = WEB_APP.read_text(encoding="utf-8")
    script = REPORT_SCRIPT.read_text(encoding="utf-8")
    assert "/api/strategy_report/manual_macro" in web
    assert "manual_macro_input.json" in web
    assert "MANUAL_MACRO_INPUT_PATH" in script
    assert "load_manual_macro_input" in script
    assert "用户盘前/休盘后手工输入优先" in script
    assert "【人工宏观基本面】" in script
    assert "自动快讯只作补充" in script


def test_intraday_analysis_outputs_trader_report_template_text():
    """前端应展示交易员版研报正文，而不是只显示旧表格脚本。"""
    import sys
    sys.path.insert(0, str(ROOT))
    from scripts import generate_daily_report as gdr

    old = gdr.get_main_futures_price
    gdr.get_main_futures_price = lambda: {"symbol": "TA", "price": 6242, "change_20_bars": 12, "last_bar_change": 2}
    try:
        report = {
            "gex": {
                "summary": {
                    "futures_price": 6424, "max_pain": 6400, "gex_flip": 6454,
                    "net_gex": -47200000, "gex_direction": "negative", "pcr": 1.184,
                    "days_left": 1.1, "effective_support": 6200, "effective_resistance": 6700,
                    "max_put_oi": 37475, "max_call_oi": 21261, "total_call_oi": 100000, "total_put_oi": 118400,
                },
                "pain_curve": [{"strike": 6400, "pain": 100}, {"strike": 6500, "pain": 200}],
                "oi_dist": [
                    {"strike": 6000, "put_oi": 37475, "call_oi": 1000},
                    {"strike": 6200, "put_oi": 22779, "call_oi": 2000},
                    {"strike": 6500, "put_oi": 3000, "call_oi": 12635},
                    {"strike": 6600, "put_oi": 1000, "call_oi": 14330},
                    {"strike": 6700, "put_oi": 1000, "call_oi": 15428},
                    {"strike": 7000, "put_oi": 500, "call_oi": 21261},
                ],
            },
            "section1": {"iv_analysis": {"atm_vol": 23.7, "skew_desc": "深度左偏", "curv_desc": "曲率正常", "vol_level": "中波"}},
            "section3": {"direction": "震荡"},
            "iv_curve": {"atm_strike": 6400, "curve": [{"strike": 6400, "iv_call": 0.23, "iv_put": 0.25, "svi_iv": 0.237, "call_oi": 1000, "put_oi": 2000}]},
            "pta": {"spot_price": 6500, "near_basis": 212},
            "px": {"spot_price": 1166.33},
            "cost": {"profit": 624, "profit_pct": 10, "pta_cost": 6000},
            "crude": {"brent": {"price": 93.34, "change_pct": -2}, "wti": {"price": 90.17, "change_pct": -2}},
            "manual_macro_input": {"summary": "PX检修集中、PTA低库存与聚酯产销放量，短期围绕6400-6600偏强震荡。"},
        }
        ia = gdr.generate_intraday_analysis(report)
    finally:
        gdr.get_main_futures_price = old

    text = ia.get("trader_report") or ""
    assert "PTA 最新综合研判" in text
    assert "当前 PTA 不适合简单看空" in text
    assert "负 Gamma 区" in text
    assert "6400上方不追空" in text
    assert "期权卖方策略" in text
    assert ia.get("summary") == "当前 PTA 不适合简单看空。"


def test_frontend_prioritizes_trader_report_over_old_table_script():
    """页面有 trader_report 时必须优先渲染正文模板，避免用户看到旧脚本式表格。"""
    template = TEMPLATE.read_text(encoding="utf-8")
    render_src = template[template.index("function renderIntradayAnalysis"):template.index("function legacyDailyReport")]
    assert "intraday.trader_report" in render_src
    assert "renderTraderReport" in render_src
    assert "let out = '';" in render_src
    assert "out += renderTraderReport(intraday.trader_report" in render_src
    assert "return renderTraderReport(intraday.trader_report" not in render_src
    assert render_src.index("let out = '';") < render_src.index("out += renderTraderReport(intraday.trader_report")
    assert render_src.index("intraday.trader_report") < render_src.index("market_snapshot_table")

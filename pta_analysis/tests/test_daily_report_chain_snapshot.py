from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / 'scripts' / 'generate_daily_report.py'
HTML = Path(__file__).resolve().parents[1] / 'templates' / 'kline_lightweight.html'


def test_chain_operation_snapshot_helpers_and_intraday_export_exist():
    text = SRC.read_text(encoding='utf-8')
    assert 'def build_chain_operation_snapshot' in text
    assert "'chain_operation_snapshot': chain_operation_snapshot" in text
    assert "_table(['环节','开工率','较前值','库存','较前值']" in text


def test_macro_news_dedup_helpers_are_used():
    text = SRC.read_text(encoding='utf-8')
    assert 'def _dedupe_text_items' in text
    assert 'def _text_fingerprint' in text
    assert 'macro_news_items = _dedupe_text_items(macro_news_items)' in text
    assert 'narrative_notes = _dedupe_narrative_notes(narrative_notes)' in text
    assert 'def _remove_duplicate_note_bases' in text
    assert 'narrative_notes = _remove_duplicate_note_bases(narrative_notes' in text


def test_frontend_renders_chain_snapshot_compactly_and_dedupes_interpretation():
    html = HTML.read_text(encoding='utf-8')
    assert 'function renderChainOperationSnapshot' in html
    assert '产业链运行快照' in html
    assert 'intraday.chain_operation_snapshot' in html
    assert 'seen.has(key)' in html

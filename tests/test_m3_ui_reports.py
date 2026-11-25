"""M3 UI Reports (claude/m3-ui-reports): Verify strict-CSP compliance on reports.js.
Fictional data only.
"""
from pathlib import Path


def test_reports_js_respects_strict_csp():
    js = Path('studioos/static/reports.js').read_text(encoding='utf-8')
    assert 'style="' not in js and 'onclick=' not in js and 'onchange=' not in js

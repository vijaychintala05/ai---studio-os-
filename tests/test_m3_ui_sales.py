"""M3 UI Sales (claude/m3-ui-sales): Sales options endpoint for smart account auto-wiring,
outsider 403, and strict-CSP static asset verification for sales.js. Fictional data only.
"""
from pathlib import Path

from tests.test_m2_bill_form import _setup_company_and_vendor
from tests.test_v018_time_app import staff


def test_sales_options_and_outsider_guard(admin):
    _setup_company_and_vendor(admin)
    r = admin.get('/api/sales/options')
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body['companies']) >= 1 and 'accounts' in body and 'today' in body

    site, _ = staff(admin, 'site.slopt', 'site_engineer')
    try:
        assert site.get('/api/sales/options').status_code == 403
    finally:
        site.close()


def test_sales_js_respects_strict_csp():
    js = Path('studioos/static/sales.js').read_text(encoding='utf-8')
    assert 'style="' not in js and 'onclick=' not in js and 'onchange=' not in js

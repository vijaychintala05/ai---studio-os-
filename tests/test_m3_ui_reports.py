"""M3 UI Reports (claude/m3-ui-reports): Verify strict-CSP compliance on reports.js.
Fictional data only.
"""
from pathlib import Path
import csv

from .conftest import write
from .test_m2_bill_form import _setup_company_and_vendor
from .test_m3_invoices import _setup_sales_accounts


def test_reports_js_respects_strict_csp():
    js = Path('studioos/static/reports.js').read_text(encoding='utf-8')
    assert 'style="' not in js and 'onclick=' not in js and 'onchange=' not in js


def post_example_invoice(admin):
    entity, _, _, _, project = _setup_company_and_vendor(admin)
    accounts = _setup_sales_accounts(entity)
    draft = write(admin, 'post', '/api/sales/invoices', {
        'entity_id': entity, 'client_id': accounts['client_id'], 'project_id': project,
        'invoice_number': 'FICT-EXPORT-1', 'invoice_date': '2026-11-15', 'due_date': '2026-12-15',
        'place_of_supply': 'Karnataka (29)', 'supply_type': 'intra',
        'ar_account_id': accounts['ar_id'], 'cgst_account_id': accounts['cgst_id'],
        'sgst_account_id': accounts['sgst_id'],
        'lines': [{'income_account_id': accounts['rev_id'], 'description': 'Fictional design',
                   'quantity': 1, 'rate_paise': 10_000, 'tax_rate_bps': 1800}],
    })
    assert draft.status_code == 200, draft.text
    saved = write(admin, 'post', f"/api/tickets/{draft.json()['ticket_id']}/approve-and-save")
    assert saved.status_code == 200, saved.text
    return entity


def test_each_financial_report_exports_its_own_csv(admin):
    entity = post_example_invoice(admin)
    def download(kind, **params):
        return admin.get('/api/books/reports/export.csv', params={'entity_id': entity, 'kind': kind, **params})

    rows = {}
    for kind, heading in {
        'pnl': 'Section', 'balance-sheet': 'Section', 'trial-balance': 'Code',
        'project-profitability': 'Project', 'tds-register': 'Bill Date', 'cash-flow': 'Activity',
        'ar-ageing': 'Client', 'gstr1': 'Supply Type', 'gstr3b': 'Measure', 'budget-vs-actual': 'Code',
    }.items():
        response = download(kind, year_month='2026-11', date_from='2026-11-01', date_to='2026-11-30')
        assert response.status_code == 200, (kind, response.text)
        assert 'text/csv' in response.headers['content-type']
        assert f'studioos-{kind}-' in response.headers['content-disposition']
        rows[kind] = list(csv.reader(response.text.splitlines()))
        assert rows[kind][0][0] == heading
    assert any('FICT-EXPORT-1' in row and '118.00' in row for row in rows['gstr1'])
    assert any('Fictional Residency Client' in row and '118.00' in row for row in rows['ar-ageing'])
    assert any(row[:1] == ['Net GST Payable'] for row in rows['gstr3b'])
    trial_balance = rows['trial-balance']
    assert trial_balance[-1][1] == 'Totals'
    assert trial_balance[-1][3:] == ['0.00', '0.00', '118.00', '118.00', '118.00', '118.00']
    assert 'FICT-EXPORT-1' not in download('gstr1', date_to='2026-11-14').text
    assert 'Fictional Residency Client' not in download('ar-ageing', as_of='2026-11-14').text
    assert download('tds').status_code == 200  # Existing callers use this name.
    assert download('unknown').status_code == 422

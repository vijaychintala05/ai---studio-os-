"""M3-5 (claude/financial-statements): Profit & Loss, Balance Sheet (Assets == Liabilities
+ Equity + Net Profit), Cash Flow Statement, project-level P&L, and outsider 403.
Fictional data only.
"""
from studioos.db import GLAccount, SessionLocal
from tests.conftest import write
from tests.test_m2_bill_form import _setup_company_and_vendor
from tests.test_m3_invoices import _setup_sales_accounts
from tests.test_v018_time_app import staff


def test_pnl_balance_sheet_and_cash_flow_reconcile(admin):
    entity_id, vendor_id, exp_id, _, proj_id = _setup_company_and_vendor(admin)
    sa = _setup_sales_accounts(entity_id)
    with SessionLocal() as db:
        bank_id = db.query(GLAccount).filter_by(entity_id=entity_id, kind='bank').first().id

    # 1. Post sales invoice: Revenue 100,000 + CGST 9,000 + SGST 9,000 = AR 118,000
    inv = write(admin, 'post', '/api/sales/invoices', {
        'entity_id': entity_id, 'client_id': sa['client_id'], 'project_id': proj_id,
        'invoice_number': 'INV-FS-01', 'invoice_date': '2026-11-10', 'due_date': '2026-12-10',
        'supply_type': 'intra', 'ar_account_id': sa['ar_id'],
        'cgst_account_id': sa['cgst_id'], 'sgst_account_id': sa['sgst_id'],
        'lines': [{'income_account_id': sa['rev_id'], 'description': 'Design fee',
                   'sac_hsn': '998391', 'quantity': 1, 'rate_paise': 100_000, 'tax_rate_bps': 1800}],
    })
    assert inv.status_code == 200, inv.text
    assert write(admin, 'post', f'/api/tickets/{inv.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200
    inv_id = admin.get(f'/api/sales/invoices?entity_id={entity_id}').json()['invoices'][0]['id']

    # 2. Collect full client receipt of 118,000 into bank
    rec = write(admin, 'post', '/api/sales/receipts', {
        'invoice_id': inv_id, 'deposit_account_id': bank_id,
        'amount_paise': 118_000, 'receipt_date': '2026-11-12', 'reference': 'NEFT-FS-1',
    })
    assert rec.status_code == 200, rec.text
    assert write(admin, 'post', f'/api/tickets/{rec.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200

    # 3. Post supplier direct bill of 40,000 expense
    bill = write(admin, 'post', '/api/books/bills', {
        'entity_id': entity_id, 'supplier_id': vendor_id, 'invoice_number': 'SUP-FS-01',
        'bill_date': '2026-11-12', 'due_date': '2026-12-12', 'payment_terms_days': 30,
        'amount_paise': 40_000,
        'lines': [{'account_id': exp_id, 'project_id': proj_id, 'description': 'Site materials', 'amount_paise': 40_000}],
    })
    assert bill.status_code == 200, bill.text
    assert write(admin, 'post', f'/api/tickets/{bill.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200

    # P&L: Income 100,000 - Expense 40,000 = Net Profit 60,000
    pnl = admin.get(f'/api/books/reports/pnl?entity_id={entity_id}').json()
    assert pnl['total_income_paise'] == 100_000
    assert pnl['total_expense_paise'] == 40_000
    assert pnl['net_profit_paise'] == 60_000

    # Project-scoped P&L matches
    proj_pnl = admin.get(f'/api/books/reports/pnl?entity_id={entity_id}&project_id={proj_id}').json()
    assert proj_pnl['net_profit_paise'] == 60_000

    # Balance Sheet: Assets (118,000) == Liabilities (18,000 GST + 40,000 AP = 58,000) + Equity (0) + Net Profit (60,000)
    bs = admin.get(f'/api/books/reports/balance-sheet?entity_id={entity_id}').json()
    assert bs['balanced'] is True and bs['difference_paise'] == 0
    assert bs['total_assets_paise'] == 118_000
    assert bs['total_liabilities_paise'] == 58_000
    assert bs['retained_net_profit_paise'] == 60_000

    # Cash Flow: Bank inflow 118,000, outflow 0, net change +118,000
    cf = admin.get(f'/api/books/reports/cash-flow?entity_id={entity_id}').json()
    assert cf['inflow_paise'] == 118_000 and cf['outflow_paise'] == 0 and cf['net_cash_change_paise'] == 118_000


def test_outsider_cannot_view_financial_statements(admin):
    site, _ = staff(admin, 'site.fscheck', 'site_engineer')
    mgr, _ = staff(admin, 'mgr.fscheck', 'manager')
    try:
        for client in (site, mgr):
            assert client.get('/api/books/reports/pnl?entity_id=1').status_code == 403
            assert client.get('/api/books/reports/balance-sheet?entity_id=1').status_code == 403
            assert client.get('/api/books/reports/cash-flow?entity_id=1').status_code == 403
    finally:
        site.close()
        mgr.close()

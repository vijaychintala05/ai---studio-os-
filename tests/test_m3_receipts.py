"""M3-2 (claude/receipts): Client receipts (partial + client TDS), retainers/advances,
advance allocation, overpayment refusal, customer statement, balanced Trial Balance,
outsider 403, and schema v58 parity. Fictional data only.
"""
from sqlalchemy import create_engine, inspect, text

from studioos.accounting_kernel import trial_balance
from studioos.db import Base, GLAccount, SessionLocal
from studioos.migrations import LATEST_VERSION, apply_migrations
from tests.conftest import write
from tests.test_m2_bill_form import _setup_company_and_vendor
from tests.test_m3_invoices import _setup_sales_accounts
from tests.test_v018_time_app import staff


def test_client_receipts_tds_advances_and_statement(admin):
    entity_id, _, _, _, proj_id = _setup_company_and_vendor(admin)
    sa = _setup_sales_accounts(entity_id)
    with SessionLocal() as db:
        tds_rec = GLAccount(entity_id=entity_id, code='1210', name='TDS Receivable', kind='asset', active=True, posting_allowed=True)
        cli_adv = GLAccount(entity_id=entity_id, code='2210', name='Client Advances', kind='liability', active=True, posting_allowed=True)
        bank = db.query(GLAccount).filter_by(entity_id=entity_id, kind='bank').first()
        db.add_all([tds_rec, cli_adv])
        db.commit()
        tds_id, adv_acc_id, bank_id = tds_rec.id, cli_adv.id, bank.id

    # Create & approve an invoice for ₹1,180.00 (118,000 paise)
    inv_r = write(admin, 'post', '/api/sales/invoices', {
        'entity_id': entity_id, 'client_id': sa['client_id'], 'project_id': proj_id,
        'invoice_number': 'INV-REC-001', 'invoice_date': '2026-11-10', 'due_date': '2026-12-10',
        'supply_type': 'intra', 'ar_account_id': sa['ar_id'],
        'cgst_account_id': sa['cgst_id'], 'sgst_account_id': sa['sgst_id'],
        'lines': [{'income_account_id': sa['rev_id'], 'description': 'Design milestone',
                   'sac_hsn': '998391', 'quantity': 1, 'rate_paise': 100_000, 'tax_rate_bps': 1800}],
    })
    assert inv_r.status_code == 200, inv_r.text
    assert write(admin, 'post', f'/api/tickets/{inv_r.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200
    inv_id = admin.get(f'/api/sales/invoices?entity_id={entity_id}').json()['invoices'][0]['id']

    # Record client advance of ₹500 (50,000 paise)
    adv_r = write(admin, 'post', '/api/sales/advances', {
        'entity_id': entity_id, 'client_id': sa['client_id'], 'project_id': proj_id,
        'deposit_account_id': bank_id, 'advance_account_id': adv_acc_id,
        'amount_paise': 50_000, 'receipt_date': '2026-11-05', 'reference': 'RET-001',
    })
    assert adv_r.status_code == 200, adv_r.text
    assert write(admin, 'post', f'/api/tickets/{adv_r.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200
    adv_id = admin.get(f'/api/sales/clients/{sa["client_id"]}/statement').json()['advances'][0]['id']

    # Allocate ₹400 of advance to invoice
    al_r = write(admin, 'post', '/api/sales/advances/allocate', {
        'advance_id': adv_id, 'invoice_id': inv_id, 'amount_paise': 40_000, 'allocation_date': '2026-11-11',
    })
    assert al_r.status_code == 200, al_r.text
    assert write(admin, 'post', f'/api/tickets/{al_r.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200

    # Partial receipt ₹680 + ₹100 TDS = ₹780 (clears remaining ₹780 of ₹1,180)
    rec_r = write(admin, 'post', '/api/sales/receipts', {
        'invoice_id': inv_id, 'deposit_account_id': bank_id, 'tds_account_id': tds_id,
        'amount_paise': 68_000, 'tds_paise': 10_000, 'receipt_date': '2026-11-12', 'reference': 'NEFT-CLI-1',
    })
    assert rec_r.status_code == 200, rec_r.text
    assert write(admin, 'post', f'/api/tickets/{rec_r.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200

    # Overpayment refused (invoice is now fully settled)
    over = write(admin, 'post', '/api/sales/receipts', {
        'invoice_id': inv_id, 'deposit_account_id': bank_id,
        'amount_paise': 100, 'receipt_date': '2026-11-13', 'reference': 'NEFT-OVER',
    })
    assert over.status_code == 422

    # Customer statement agrees to the paisa: receivable 0, unallocated retainer ₹100 (10,000 paise)
    stmt = admin.get(f'/api/sales/clients/{sa["client_id"]}/statement').json()
    assert stmt['receivable_paise'] == 0 and stmt['unallocated_advance_paise'] == 10_000

    with SessionLocal() as db:
        tb = trial_balance(db, entity_id)
        assert tb['total_debit_paise'] == tb['total_credit_paise']


def test_outsider_cannot_access_sales_receipts(admin):
    site, _ = staff(admin, 'site.reccheck', 'site_engineer')
    try:
        assert site.get('/api/sales/clients/1/statement').status_code == 403
        assert write(site, 'post', '/api/sales/receipts', {}).status_code in (403, 422)
    finally:
        site.close()


def test_v58_upgraded_schema_matches_fresh_schema(tmp_path):
    fresh = create_engine(f'sqlite:///{tmp_path / "fresh.db"}')
    upgraded = create_engine(f'sqlite:///{tmp_path / "upgraded.db"}')
    try:
        Base.metadata.create_all(fresh)
        apply_migrations(upgraded)
        with upgraded.connect() as conn:
            assert conn.scalar(text('SELECT MAX(version) FROM schema_migrations')) == LATEST_VERSION
        fresh_insp, upg_insp = inspect(fresh), inspect(upgraded)
        for tbl in ('sales_receipts', 'sales_advances', 'sales_advance_allocations'):
            assert tbl in upg_insp.get_table_names()
            assert {c['name'] for c in fresh_insp.get_columns(tbl)} == {c['name'] for c in upg_insp.get_columns(tbl)}
    finally:
        fresh.dispose()
        upgraded.dispose()

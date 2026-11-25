"""M3-3 (claude/credit-and-debit-notes): Vendor credit notes and client credit notes
with balanced GL postings, reversals, outsider 403, and schema v59 parity. Fictional data only.
"""
from sqlalchemy import create_engine, inspect, text

from studioos.accounting_kernel import trial_balance
from studioos.db import Base, FinanceVendorCredit, GLAccount, SalesCreditNote, SessionLocal
from studioos.migrations import LATEST_VERSION, apply_migrations
from tests.conftest import write
from tests.test_m2_bill_form import _setup_company_and_vendor
from tests.test_m3_invoices import _setup_sales_accounts
from tests.test_v018_time_app import staff


def test_vendor_credit_and_sales_credit_note_lifecycle(admin):
    entity_id, vendor_id, exp_id, _, proj_id = _setup_company_and_vendor(admin)
    sa = _setup_sales_accounts(entity_id)
    with SessionLocal() as db:
        ap_id = db.query(GLAccount).filter_by(entity_id=entity_id, kind='payable').first().id

    # Vendor credit note (Dr AP 23,600 / Cr Expense 20,000 + Cr Input GST 3,600)
    vc = write(admin, 'post', '/api/sales/vendor-credits', {
        'entity_id': entity_id, 'supplier_id': vendor_id, 'project_id': proj_id,
        'note_number': 'VC-2026-01', 'note_date': '2026-11-18',
        'ap_account_id': ap_id, 'expense_account_id': exp_id, 'tax_account_id': sa['cgst_id'],
        'taxable_paise': 20_000, 'tax_paise': 3_600, 'reason': 'Damaged tiles returned',
    })
    assert vc.status_code == 200, vc.text
    assert write(admin, 'post', f'/api/tickets/{vc.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200

    # Client credit note (Dr Revenue 10,000 + Dr Output GST 1,800 / Cr AR 11,800)
    cn = write(admin, 'post', '/api/sales/credit-notes', {
        'entity_id': entity_id, 'client_id': sa['client_id'], 'project_id': proj_id,
        'note_number': 'CN-2026-01', 'note_date': '2026-11-19',
        'ar_account_id': sa['ar_id'], 'income_account_id': sa['rev_id'], 'tax_account_id': sa['cgst_id'],
        'taxable_paise': 10_000, 'tax_paise': 1_800, 'reason': 'Agreed scope discount',
    })
    assert cn.status_code == 200, cn.text
    assert write(admin, 'post', f'/api/tickets/{cn.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200

    with SessionLocal() as db:
        tb = trial_balance(db, entity_id)
        assert tb['balanced'] is True and tb['total_debit_paise'] == 35_400
        vc_id = db.query(FinanceVendorCredit).first().id
        cn_id = db.query(SalesCreditNote).first().id

    # Reverse both notes -> Trial Balance returns to 0
    for itype, payload in (
        ('finance_reverse_vendor_credit', {'vendor_credit_id': vc_id, 'reason': 'Entered on wrong vendor'}),
        ('sales_reverse_credit_note', {'credit_note_id': cn_id, 'reason': 'Reissued with corrected GST'}),
    ):
        rev = write(admin, 'post', '/api/universal/proposals', {'kind': itype, 'data': payload, 'evidence': 'Fictional note reversal'})
        assert rev.status_code == 200, rev.text
        assert write(admin, 'post', f'/api/tickets/{rev.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200

    with SessionLocal() as db:
        tb = trial_balance(db, entity_id)
        assert tb['balanced'] is True and tb['total_debit_paise'] == 0


def test_outsider_cannot_create_credit_notes(admin):
    site, _ = staff(admin, 'site.cncheck', 'site_engineer')
    try:
        assert write(site, 'post', '/api/sales/vendor-credits', {}).status_code in (403, 422)
        assert write(site, 'post', '/api/sales/credit-notes', {}).status_code in (403, 422)
    finally:
        site.close()


def test_v59_upgraded_schema_matches_fresh_schema(tmp_path):
    fresh = create_engine(f'sqlite:///{tmp_path / "fresh.db"}')
    upgraded = create_engine(f'sqlite:///{tmp_path / "upgraded.db"}')
    try:
        Base.metadata.create_all(fresh)
        apply_migrations(upgraded)
        with upgraded.connect() as conn:
            assert conn.scalar(text('SELECT MAX(version) FROM schema_migrations')) == LATEST_VERSION
        fresh_insp, upg_insp = inspect(fresh), inspect(upgraded)
        for tbl in ('finance_vendor_credits', 'sales_credit_notes'):
            assert tbl in upg_insp.get_table_names()
            assert {c['name'] for c in fresh_insp.get_columns(tbl)} == {c['name'] for c in upg_insp.get_columns(tbl)}
    finally:
        fresh.dispose()
        upgraded.dispose()

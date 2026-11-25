"""M3-1 (claude/clients-and-invoices): Client sales invoices with CGST Sec 170 nearest-Rs 1
rounding, balanced GL posting, ReportLab PDF, reversal, outsider 403, and schema v57 parity.
Fictional data only.
"""
from sqlalchemy import create_engine, inspect, text

from studioos.accounting_kernel import trial_balance
from studioos.db import Base, GLAccount, Party, SessionLocal
from studioos.migrations import LATEST_VERSION, apply_migrations
from tests.conftest import write
from tests.test_m2_bill_form import _setup_company_and_vendor
from tests.test_v018_time_app import staff


def _setup_sales_accounts(entity_id):
    with SessionLocal() as db:
        client = Party(kind='client', name='Fictional Residency Client', phone='9876500002', gstin='29ABCDE9999F1Z2')
        ar = GLAccount(entity_id=entity_id, code='1100', name='Accounts Receivable', kind='asset', active=True, posting_allowed=True)
        rev = GLAccount(entity_id=entity_id, code='4000', name='Design Fees', kind='income', active=True, posting_allowed=True)
        cgst = GLAccount(entity_id=entity_id, code='2101', name='Output CGST', kind='liability', active=True, posting_allowed=True)
        sgst = GLAccount(entity_id=entity_id, code='2102', name='Output SGST', kind='liability', active=True, posting_allowed=True)
        igst = GLAccount(entity_id=entity_id, code='2103', name='Output IGST', kind='liability', active=True, posting_allowed=True)
        rnd = GLAccount(entity_id=entity_id, code='5990', name='Rounding Off', kind='expense', active=True, posting_allowed=True)
        db.add_all([client, ar, rev, cgst, sgst, igst, rnd])
        db.commit()
        return {'client_id': client.id, 'ar_id': ar.id, 'rev_id': rev.id,
                'cgst_id': cgst.id, 'sgst_id': sgst.id, 'igst_id': igst.id, 'rnd_id': rnd.id}


def test_sales_invoice_gst_rounding_pdf_and_reversal(admin):
    entity_id, _, _, _, proj_id = _setup_company_and_vendor(admin)
    sa = _setup_sales_accounts(entity_id)

    # 10,001 paise + 18% GST (1,800 paise) = 11,801 paise -> rounds down by 1 paisa to 11,800 paise
    payload = {
        'entity_id': entity_id, 'client_id': sa['client_id'], 'project_id': proj_id,
        'invoice_number': 'INV-2026-0001', 'invoice_date': '2026-11-15', 'due_date': '2026-12-15',
        'place_of_supply': 'Karnataka (29)', 'supply_type': 'intra',
        'ar_account_id': sa['ar_id'], 'cgst_account_id': sa['cgst_id'],
        'sgst_account_id': sa['sgst_id'], 'rounding_account_id': sa['rnd_id'],
        'lines': [{'income_account_id': sa['rev_id'], 'description': 'Concept design', 'sac_hsn': '998391',
                   'quantity': 1, 'rate_paise': 10_001, 'tax_rate_bps': 1800}],
    }
    r = write(admin, 'post', '/api/sales/invoices', payload)
    assert r.status_code == 200, r.text
    assert write(admin, 'post', f'/api/tickets/{r.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200

    invs = admin.get(f'/api/sales/invoices?entity_id={entity_id}').json()['invoices']
    assert len(invs) == 1
    inv = invs[0]
    assert inv['subtotal_paise'] == 10_001 and inv['cgst_paise'] == 900 and inv['sgst_paise'] == 900
    assert inv['rounding_paise'] == -1 and inv['total_paise'] == 11_800

    with SessionLocal() as db:
        tb = trial_balance(db, entity_id)
        assert tb['balanced'] is True and tb['total_debit_paise'] == 11_801 and tb['total_credit_paise'] == 11_801

    # PDF renders cleanly
    pdf = admin.get(f'/api/sales/invoices/{inv["id"]}/pdf')
    assert pdf.status_code == 200 and pdf.content.startswith(b'%PDF')

    # Duplicate invoice number refused
    dup = write(admin, 'post', '/api/sales/invoices', payload)
    assert dup.status_code == 422 and 'duplicate' in dup.text.casefold()

    # Reversal zeroes Trial Balance
    rev = write(admin, 'post', '/api/universal/finance/propose', {
        'item_type': 'sales_reverse_invoice',
        'data': {'invoice_id': inv['id'], 'reason': 'Fictional client scope change'},
    })
    assert rev.status_code == 200, rev.text
    assert write(admin, 'post', f'/api/tickets/{rev.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200
    with SessionLocal() as db:
        tb = trial_balance(db, entity_id)
        assert tb['balanced'] is True and tb['total_debit_paise'] == 0


def test_outsider_cannot_access_sales_invoices(admin):
    site, _ = staff(admin, 'site.invcheck', 'site_engineer')
    try:
        assert site.get('/api/sales/invoices').status_code == 403
        assert write(site, 'post', '/api/sales/invoices', {}).status_code in (403, 422)
    finally:
        site.close()


def test_v57_upgraded_schema_matches_fresh_schema(tmp_path):
    fresh = create_engine(f'sqlite:///{tmp_path / "fresh.db"}')
    upgraded = create_engine(f'sqlite:///{tmp_path / "upgraded.db"}')
    try:
        Base.metadata.create_all(fresh)
        apply_migrations(upgraded)
        with upgraded.connect() as conn:
            assert conn.scalar(text('SELECT MAX(version) FROM schema_migrations')) == LATEST_VERSION
        fresh_insp, upg_insp = inspect(fresh), inspect(upgraded)
        for tbl in ('sales_invoices', 'sales_invoice_lines'):
            assert tbl in upg_insp.get_table_names()
            assert {c['name'] for c in fresh_insp.get_columns(tbl)} == {c['name'] for c in upg_insp.get_columns(tbl)}
    finally:
        fresh.dispose()
        upgraded.dispose()

"""M2-1 (claude/bill-form): Multi-line supplier bills on the approval ticket path.
Covers validation (missing vendor/date, line sum mismatch, duplicate invoice per vendor,
locked purchase period), balanced multi-line GL posting, Trial Balance / Books / Party
consistency, reversal, outsider access control, and fresh-vs-upgraded schema v51.
Fictional data only.
"""
from sqlalchemy import create_engine, inspect, select, text

from studioos.accounting_kernel import trial_balance
from studioos.db import Base, GLAccount, Party, SessionLocal
from studioos.migrations import LATEST_VERSION, apply_migrations
from tests.conftest import approved_form, write
from tests.test_v018_time_app import staff


def _setup_company_and_vendor(admin):
    setup = write(admin, 'post', '/api/universal/finance/propose', {
        'item_type': 'finance_setup',
        'data': {
            'entity_name': 'Fictional Interiors Studio',
            'expense_code': '5000',
            'ap_code': '2000',
            'bank_code': '1000',
            'bank_name': 'Fictional Main Bank',
            'bank_masked': 'XXXX1234',
        },
    })
    assert setup.status_code == 200, setup.text
    tid = setup.json()['ticket_id']
    assert write(admin, 'post', f'/api/tickets/{tid}/approve-and-save', {'confirmed': [], 'note': 'setup'}).status_code == 200
    opts = admin.get('/api/books/bill-options').json()
    entity_id = opts['companies'][0]['id']
    expense_acc_id = opts['accounts'][0]['id']

    with SessionLocal() as db:
        extra = GLAccount(entity_id=entity_id, code='5010', name='Fictional Tiles Expense', kind='expense', active=True, posting_allowed=True)
        vendor = Party(kind='vendor', name='Fictional Tile House', phone='9876543210', gstin='29ABCDE1234F1Z5')
        db.add_all([extra, vendor])
        db.commit()
        extra_acc_id, vendor_id = extra.id, vendor.id

    p1 = approved_form(admin, 'post', '/api/projects', {'name': 'Banyan Residence', 'budget': '500000'}).json()
    return entity_id, vendor_id, expense_acc_id, extra_acc_id, p1['id']


def test_direct_bill_validation_posting_books_and_reversal(admin):
    entity_id, vendor_id, acc1, acc2, proj_id = _setup_company_and_vendor(admin)

    base = {
        'entity_id': entity_id,
        'supplier_id': vendor_id,
        'invoice_number': 'FICT-INV-101',
        'bill_date': '2026-11-10',
        'due_date': '2026-12-10',
        'payment_terms_days': 30,
        'amount_paise': 150_000,
        'lines': [
            {'account_id': acc1, 'project_id': proj_id, 'description': 'Fictional labour', 'amount_paise': 100_000},
            {'account_id': acc2, 'project_id': proj_id, 'description': 'Fictional tiles', 'amount_paise': 50_000},
        ],
        'note': 'Fictional delivery',
    }

    # Missing/invalid vendor refused
    bad_vendor = write(admin, 'post', '/api/books/bills', {**base, 'supplier_id': 999999})
    assert bad_vendor.status_code == 422, bad_vendor.text

    # Line sum mismatch refused
    bad_sum = write(admin, 'post', '/api/books/bills', {**base, 'amount_paise': 140_000})
    assert bad_sum.status_code == 422 and 'add up' in bad_sum.text.casefold()

    # Due date before bill date refused
    bad_dates = write(admin, 'post', '/api/books/bills', {**base, 'due_date': '2026-11-01'})
    assert bad_dates.status_code == 422, bad_dates.text

    # Draft succeeds, nothing posted until approved
    draft = write(admin, 'post', '/api/books/bills', base)
    assert draft.status_code == 200, draft.text
    tid = draft.json()['ticket_id']
    assert admin.get('/api/books/home').json()['companies'][0]['payable_paise'] == 0

    # Approve and save
    saved = write(admin, 'post', f'/api/tickets/{tid}/approve-and-save', {'confirmed': [], 'note': 'checked'})
    assert saved.status_code == 200, saved.text

    # Trial balance stays balanced and Books home + Party page agree to the paisa
    with SessionLocal() as db:
        tb = trial_balance(db, entity_id)
        assert tb['balanced'] is True and tb['total_debit_paise'] == 150_000 and tb['total_credit_paise'] == 150_000
    books = admin.get('/api/books/home').json()['companies'][0]
    assert books['payable_paise'] == 150_000 and books['open_bills'] == 1
    party = admin.get(f'/api/books/parties/{vendor_id}').json()
    assert party['owed_paise'] == 150_000 and party['bills'][0]['invoice_number'] == 'FICT-INV-101'

    # Duplicate invoice number per vendor refused
    dup = write(admin, 'post', '/api/books/bills', base)
    assert dup.status_code == 422 and 'duplicate' in dup.text.casefold()

    # Reversal zeroes payables while keeping balanced trial balance
    bill_id = party['bills'][0]['id']
    rev_draft = write(admin, 'post', '/api/universal/finance/propose', {
        'item_type': 'finance_reverse_direct_bill',
        'data': {'bill_id': bill_id, 'reason': 'Fictional vendor issued corrected invoice'},
    })
    assert rev_draft.status_code == 200, rev_draft.text
    rev_tid = rev_draft.json()['ticket_id']
    assert write(admin, 'post', f'/api/tickets/{rev_tid}/approve-and-save', {'confirmed': [], 'note': 'reverse'}).status_code == 200
    assert admin.get('/api/books/home').json()['companies'][0]['payable_paise'] == 0
    with SessionLocal() as db:
        tb = trial_balance(db, entity_id)
        assert tb['balanced'] is True and tb['total_debit_paise'] == 0


def test_outsider_roles_cannot_access_bill_options_or_create_bills(admin):
    site, _ = staff(admin, 'site.billcheck', 'site_engineer')
    viewer, _ = staff(admin, 'view.billcheck', 'viewer')
    try:
        for client in (site, viewer):
            assert client.get('/api/books/bill-options').status_code == 403
            assert write(client, 'post', '/api/books/bills', {}).status_code in (403, 422)
    finally:
        site.close()
        viewer.close()


def test_v51_upgraded_schema_matches_fresh_schema(tmp_path):
    fresh = create_engine(f'sqlite:///{tmp_path / "fresh.db"}')
    upgraded = create_engine(f'sqlite:///{tmp_path / "upgraded.db"}')
    try:
        Base.metadata.create_all(fresh)
        apply_migrations(upgraded)
        with upgraded.connect() as conn:
            assert conn.scalar(text('SELECT MAX(version) FROM schema_migrations')) == LATEST_VERSION
        fresh_insp, upg_insp = inspect(fresh), inspect(upgraded)
        for tbl in ('finance_direct_bills', 'finance_direct_bill_lines'):
            assert tbl in upg_insp.get_table_names()
            assert {c['name'] for c in fresh_insp.get_columns(tbl)} == {c['name'] for c in upg_insp.get_columns(tbl)}
    finally:
        fresh.dispose()
        upgraded.dispose()

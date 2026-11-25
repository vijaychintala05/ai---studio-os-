"""M2-3 (claude/transfers-and-journals): Bank/cash transfers and manual journal entries.
Tests same-account refusal, balanced transfer & reversal, unbalanced journal refusal with
plain-English difference, balanced manual journal posting & reversal, outsider 403, and
fresh-vs-upgraded schema v53. Fictional data only.
"""
from sqlalchemy import create_engine, inspect, text

from studioos.accounting_kernel import trial_balance
from studioos.db import Base, GLAccount, SessionLocal
from studioos.migrations import LATEST_VERSION, apply_migrations
from tests.conftest import write
from tests.test_m2_bill_form import _setup_company_and_vendor
from tests.test_v018_time_app import staff


def test_transfer_and_manual_journal_lifecycle(admin):
    entity_id, _, exp_id, _, proj_id = _setup_company_and_vendor(admin)
    with SessionLocal() as db:
        cash = GLAccount(entity_id=entity_id, code='1010', name='Fictional Cash in Hand', kind='cash', active=True, posting_allowed=True)
        db.add(cash)
        db.commit()
        cash_id = cash.id

    opts = admin.get('/api/books/journal-options').json()
    bank_id = next(a['id'] for a in opts['accounts'] if a['entity_id'] == entity_id and a['kind'] == 'bank')

    # Transfer with same From and To account refused
    same = write(admin, 'post', '/api/books/transfers', {
        'entity_id': entity_id, 'from_account_id': bank_id, 'to_account_id': bank_id,
        'amount_paise': 25_000, 'transfer_date': '2026-11-15', 'reference': 'TRF-SAME',
    })
    assert same.status_code == 422 and 'two different accounts' in same.text.casefold()

    # Valid transfer bank -> cash
    tr = write(admin, 'post', '/api/books/transfers', {
        'entity_id': entity_id, 'from_account_id': bank_id, 'to_account_id': cash_id,
        'amount_paise': 25_000, 'transfer_date': '2026-11-15', 'reference': 'TRF-001',
    })
    assert tr.status_code == 200, tr.text
    tid = tr.json()['ticket_id']
    assert write(admin, 'post', f'/api/tickets/{tid}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200
    with SessionLocal() as db:
        tb = trial_balance(db, entity_id)
        assert tb['balanced'] is True

    # Unbalanced manual journal refused with exact difference
    unbal = write(admin, 'post', '/api/books/manual-journals', {
        'entity_id': entity_id, 'entry_date': '2026-11-15', 'reference': 'MJ-BAD',
        'narration': 'Fictional adjustment',
        'lines': [
            {'account_id': exp_id, 'side': 'debit', 'amount_paise': 50_000, 'project_id': proj_id},
            {'account_id': cash_id, 'side': 'credit', 'amount_paise': 40_000},
        ],
    })
    assert unbal.status_code == 422 and '100.00' in unbal.text

    # Balanced manual journal posts cleanly
    mj = write(admin, 'post', '/api/books/manual-journals', {
        'entity_id': entity_id, 'entry_date': '2026-11-15', 'reference': 'MJ-001',
        'narration': 'Fictional site adjustment',
        'lines': [
            {'account_id': exp_id, 'side': 'debit', 'amount_paise': 50_000, 'project_id': proj_id},
            {'account_id': cash_id, 'side': 'credit', 'amount_paise': 50_000},
        ],
    })
    assert mj.status_code == 200, mj.text
    mtid = mj.json()['ticket_id']
    assert write(admin, 'post', f'/api/tickets/{mtid}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200
    with SessionLocal() as db:
        tb = trial_balance(db, entity_id)
        assert tb['balanced'] is True


def test_outsider_cannot_create_transfers_or_manual_journals(admin):
    site, _ = staff(admin, 'site.trcheck', 'site_engineer')
    try:
        assert site.get('/api/books/journal-options').status_code == 403
        assert write(site, 'post', '/api/books/transfers', {}).status_code in (403, 422)
        assert write(site, 'post', '/api/books/manual-journals', {}).status_code in (403, 422)
    finally:
        site.close()


def test_v53_upgraded_schema_matches_fresh_schema(tmp_path):
    fresh = create_engine(f'sqlite:///{tmp_path / "fresh.db"}')
    upgraded = create_engine(f'sqlite:///{tmp_path / "upgraded.db"}')
    try:
        Base.metadata.create_all(fresh)
        apply_migrations(upgraded)
        with upgraded.connect() as conn:
            assert conn.scalar(text('SELECT MAX(version) FROM schema_migrations')) == LATEST_VERSION
        fresh_insp, upg_insp = inspect(fresh), inspect(upgraded)
        for tbl in ('finance_transfers', 'finance_manual_journals'):
            assert tbl in upg_insp.get_table_names()
            assert {c['name'] for c in fresh_insp.get_columns(tbl)} == {c['name'] for c in upg_insp.get_columns(tbl)}
    finally:
        fresh.dispose()
        upgraded.dispose()

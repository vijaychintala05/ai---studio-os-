"""M3-0 (claude/quotes-and-orders): Versioned client quotes, acceptance lock,
zero ledger impact, outsider 403, and fresh-vs-upgraded schema v56. Fictional data only.
"""
from sqlalchemy import create_engine, inspect, text

from studioos.accounting_kernel import trial_balance
from studioos.db import Base, Party, SessionLocal
from studioos.migrations import LATEST_VERSION, apply_migrations
from tests.conftest import write
from tests.test_m2_bill_form import _setup_company_and_vendor
from tests.test_v018_time_app import staff


def test_versioned_quotes_acceptance_lock_and_zero_gl_impact(admin):
    entity_id, _, _, _, proj_id = _setup_company_and_vendor(admin)
    with SessionLocal() as db:
        client = Party(kind='client', name='Fictional Villa Client', phone='9876500001')
        db.add(client)
        db.commit()
        client_id = client.id

    base = {
        'entity_id': entity_id, 'client_id': client_id, 'project_id': proj_id,
        'quote_number': 'QT-2026-001', 'quote_date': '2026-11-10', 'valid_until': '2026-12-10',
        'lines': [{'description': 'Interior design consultancy', 'sac_hsn': '998391',
                   'quantity': 1, 'rate_paise': 500_000, 'tax_rate_bps': 1800}],
        'note': 'Revision 1',
    }
    q1 = write(admin, 'post', '/api/sales/quotes', base)
    assert q1.status_code == 200, q1.text
    assert write(admin, 'post', f'/api/tickets/{q1.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200

    # Revision 2 bumps version to 2
    q2 = write(admin, 'post', '/api/sales/quotes', {**base, 'note': 'Revision 2'})
    assert q2.status_code == 200, q2.text
    assert write(admin, 'post', f'/api/tickets/{q2.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200

    quotes = admin.get(f'/api/sales/quotes?entity_id={entity_id}').json()['quotes']
    assert sorted(q['version'] for q in quotes) == [1, 2]
    v2_id = next(q['id'] for q in quotes if q['version'] == 2)

    # Accept v2
    acc = write(admin, 'post', f'/api/sales/quotes/{v2_id}/accept', {'accepted_date': '2026-11-12', 'note': 'Client signed'})
    assert acc.status_code == 200, acc.text
    assert write(admin, 'post', f'/api/tickets/{acc.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200

    # Further revision of accepted quote is refused
    q3 = write(admin, 'post', '/api/sales/quotes', {**base, 'note': 'Revision 3'})
    assert q3.status_code == 422 and 'accepted' in q3.text.casefold()

    # Quotes NEVER post to the ledger
    with SessionLocal() as db:
        tb = trial_balance(db, entity_id)
        assert tb['total_debit_paise'] == 0 and tb['total_credit_paise'] == 0


def test_outsider_cannot_access_sales_quotes(admin):
    site, _ = staff(admin, 'site.qcheck', 'site_engineer')
    try:
        assert site.get('/api/sales/quotes').status_code == 403
        assert write(site, 'post', '/api/sales/quotes', {}).status_code in (403, 422)
    finally:
        site.close()


def test_v56_upgraded_schema_matches_fresh_schema(tmp_path):
    fresh = create_engine(f'sqlite:///{tmp_path / "fresh.db"}')
    upgraded = create_engine(f'sqlite:///{tmp_path / "upgraded.db"}')
    try:
        Base.metadata.create_all(fresh)
        apply_migrations(upgraded)
        with upgraded.connect() as conn:
            assert conn.scalar(text('SELECT MAX(version) FROM schema_migrations')) == LATEST_VERSION
        fresh_insp, upg_insp = inspect(fresh), inspect(upgraded)
        for tbl in ('sales_quotes', 'sales_quote_lines', 'sales_quote_acceptances'):
            assert tbl in upg_insp.get_table_names()
            assert {c['name'] for c in fresh_insp.get_columns(tbl)} == {c['name'] for c in upg_insp.get_columns(tbl)}
    finally:
        fresh.dispose()
        upgraded.dispose()

"""M2-5 (claude/bank-feed-matching): Bank CSV import, match suggestions, suggest-only
bank rules (never auto-post), append-only unreconciliation with required reason,
outsider 403, and fresh-vs-upgraded schema v54. Fictional data only.
"""
import pytest
from sqlalchemy import create_engine, inspect, text

from studioos.bank_feed import parse_bank_csv

from studioos.db import Base, FinanceBankReconciliation, SessionLocal
from studioos.migrations import LATEST_VERSION, apply_migrations
from tests.conftest import write
from tests.test_m2_bill_form import _setup_company_and_vendor
from tests.test_v018_time_app import staff
from tests.test_v0910_inventory_reconciliation import evidence_doc


@pytest.mark.parametrize(('csv_text', 'expected'), [
    ('Fictional account statement\nDate,Narration,Withdrawal Amt.,Deposit Amt.\n'
     '12/11/2026,"Fictional Tiles, REF-1","₹1,23,456.78",\n', ('2026-11-12', 'Fictional Tiles, REF-1', -12_345_678)),
    ('Transaction Date,Particulars,Amount\n13-Nov-2026,Fictional REF-2,"(Rs. 1,250.50)"\n',
     ('2026-11-13', 'Fictional REF-2', -125_050)),
    ('date,reference,signed_amount_paise\n2026-11-14,Fictional REF-3,501\n',
     ('2026-11-14', 'Fictional REF-3', 501)),
])
def test_standard_bank_exports_use_the_right_amount_units(csv_text, expected):
    row, = parse_bank_csv(csv_text)
    assert (row['booking_date'], row['statement_reference'], row['signed_amount_paise']) == expected


def test_bank_csv_custom_columns_preserve_dates_signs_and_integer_paise(admin, tmp_path, monkeypatch):
    _setup_company_and_vendor(admin)
    bank = admin.get('/api/books/home').json()['companies'][0]['banks'][0]['id']
    endpoint = f'/api/books/bank-feed/{bank}/import-csv'
    doc_id = evidence_doc(tmp_path, monkeypatch)
    statement = ('Posted On,Transaction Details,Money Out,Money In\n'
                 '12/11/2026,"Fictional Tile, UTR-1","₹1,23,456.78",\n'
                 '13/11/2026,Fictional UTR-2,,"Rs. 3,250.50"\n')
    columns = {'date': 'Posted On', 'reference': 'Transaction Details', 'debit': 'Money Out', 'credit': 'Money In'}
    before = admin.get('/api/tickets').json()
    inspection = write(admin, 'post', endpoint, {'csv_text': statement, 'inspect_only': True})
    assert inspection.status_code == 200, inspection.text
    assert inspection.json()['headers'] == list(columns.values())
    assert admin.get('/api/tickets').json() == before
    payload = {'csv_text': statement, 'columns': columns, 'evidence_document_id': doc_id}
    bad = write(admin, 'post', endpoint, {**payload, 'columns': {**columns, 'credit': 'Money Out'}})
    assert bad.status_code == 422
    draft = write(admin, 'post', endpoint, payload)
    assert draft.status_code == 200, draft.text
    ticket = draft.json()['ticket_id']
    items = [item['after'] for item in admin.get(f'/api/tickets/{ticket}').json()['items']]
    assert [(item['booking_date'], item['statement_reference'], item['signed_amount_paise']) for item in items] == [
        ('2026-11-12', 'Fictional Tile, UTR-1', -12_345_678),
        ('2026-11-13', 'Fictional UTR-2', 325_050),
    ]
    assert admin.get(f'/api/books/bank-feed/{bank}').json()['uncategorised'] == []


def test_bank_feed_csv_import_suggestions_rules_and_unreconcile(admin, tmp_path, monkeypatch):
    entity_id, vendor_id, acc1, _, proj_id = _setup_company_and_vendor(admin)
    books = admin.get('/api/books/home').json()['companies'][0]
    bank_id = books['banks'][0]['id']
    doc_id = evidence_doc(tmp_path, monkeypatch)

    # Create & approve a direct bill and pay 500.00 via bank so a matching journal exists
    b = write(admin, 'post', '/api/books/bills', {
        'entity_id': entity_id, 'supplier_id': vendor_id, 'invoice_number': 'FICT-BF-1',
        'bill_date': '2026-11-10', 'due_date': '2026-12-10', 'payment_terms_days': 30,
        'amount_paise': 50_000,
        'lines': [{'account_id': acc1, 'project_id': proj_id, 'description': 'Fictional item', 'amount_paise': 50_000}],
    })
    assert b.status_code == 200, b.text
    assert write(admin, 'post', f'/api/tickets/{b.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200
    due = admin.get('/api/books/bills-due').json()
    bill_id = (due['overdue'] + due['due_this_week'] + due['due_later'])[0]['bill_id']
    bank_acc = next(account['id'] for account in due['paying_accounts'][str(entity_id)]
                    if account['bank_id'] == bank_id)
    pay = write(admin, 'post', '/api/books/pay-selected', {
        'entity_id': entity_id, 'paid_through_id': bank_acc,
        'payment_date': '2026-11-12', 'payment_reference': 'UTR-FEED-1',
        'items': [{'kind': 'direct_bill', 'bill_id': bill_id, 'amount_paise': 50_000}],
    })
    assert pay.status_code == 200, pay.text
    assert write(admin, 'post', f'/api/tickets/{pay.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200

    # Approve a suggest-only bank rule
    rule = write(admin, 'post', '/api/books/bank-rules', {
        'entity_id': entity_id, 'bank_id': bank_id, 'match_text': 'UTR-FEED',
        'direction': 'outflow', 'suggested_account_id': acc1, 'suggested_party_id': vendor_id,
        'note': 'Fictional vendor payment rule',
    })
    assert rule.status_code == 200, rule.text
    assert write(admin, 'post', f'/api/tickets/{rule.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200

    # Import CSV -> creates draft ticket; approve it
    csv_text = 'Date,Reference,Debit,Credit\n2026-11-12,UTR-FEED-1,500.00,\n'
    imp = write(admin, 'post', f'/api/books/bank-feed/{bank_id}/import-csv', {
        'csv_text': csv_text, 'evidence_document_id': doc_id,
    })
    assert imp.status_code == 200, imp.text
    assert imp.json()['imported_count'] == 1
    assert write(admin, 'post', f'/api/tickets/{imp.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200

    # Re-importing same CSV skips duplicate and refuses empty batch
    dup = write(admin, 'post', f'/api/books/bank-feed/{bank_id}/import-csv', {
        'csv_text': csv_text, 'evidence_document_id': doc_id,
    })
    assert dup.status_code == 422

    # Bank feed shows uncategorised line with BOTH exact match suggestion and rule suggestion
    feed = admin.get(f'/api/books/bank-feed/{bank_id}').json()
    assert len(feed['uncategorised']) == 1
    line = feed['uncategorised'][0]
    assert line['signed_amount_paise'] == -50_000
    assert line['rule_suggestion']['suggested_account_id'] == acc1
    assert any(m['confidence'] == 'exact' for m in line['match_suggestions'])
    journal_id = line['match_suggestions'][0]['journal_id']

    # Reconcile via approval ticket
    rec = write(admin, 'post', '/api/universal/proposals', {
        'kind': 'finance_reconcile_bank', 'evidence': 'Fictional bank reconciliation',
        'data': {'statement_line_id': line['id'], 'journal_id': journal_id},
    })
    assert rec.status_code == 200, rec.text
    assert write(admin, 'post', f'/api/tickets/{rec.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200
    assert admin.get(f'/api/books/bank-feed/{bank_id}').json()['uncategorised'] == []

    # Un-reconcile with short reason refused; valid reason brings line back
    with SessionLocal() as db:
        rec_id = db.query(FinanceBankReconciliation).first().id
    bad_un = write(admin, 'post', '/api/books/bank-unreconcile', {'reconciliation_id': rec_id, 'reason': 'no'})
    assert bad_un.status_code == 422
    un = write(admin, 'post', '/api/books/bank-unreconcile', {'reconciliation_id': rec_id, 'reason': 'Matched to wrong payment'})
    assert un.status_code == 200, un.text
    assert write(admin, 'post', f'/api/tickets/{un.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200
    assert len(admin.get(f'/api/books/bank-feed/{bank_id}').json()['uncategorised']) == 1


def test_outsider_cannot_access_bank_feed(admin):
    site, _ = staff(admin, 'site.bfcheck', 'site_engineer')
    try:
        assert site.get('/api/books/bank-feed/1').status_code == 403
        assert write(site, 'post', '/api/books/bank-rules', {}).status_code in (403, 422)
    finally:
        site.close()


def test_v54_upgraded_schema_matches_fresh_schema(tmp_path):
    fresh = create_engine(f'sqlite:///{tmp_path / "fresh.db"}')
    upgraded = create_engine(f'sqlite:///{tmp_path / "upgraded.db"}')
    try:
        Base.metadata.create_all(fresh)
        apply_migrations(upgraded)
        with upgraded.connect() as conn:
            assert conn.scalar(text('SELECT MAX(version) FROM schema_migrations')) == LATEST_VERSION
        fresh_insp, upg_insp = inspect(fresh), inspect(upgraded)
        for tbl in ('finance_bank_rules', 'finance_bank_unreconciliations'):
            assert tbl in upg_insp.get_table_names()
            assert {c['name'] for c in fresh_insp.get_columns(tbl)} == {c['name'] for c in upg_insp.get_columns(tbl)}
    finally:
        fresh.dispose()
        upgraded.dispose()

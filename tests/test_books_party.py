"""Books home and the Party page: what is owed, ageing, bank balances and matching come out exactly from the ledger; amounts only for the
roles that may see them; contacts only for roles and projects that may see them. Read-only. Fictional data."""
import re
from pathlib import Path

from tests.conftest import write
from tests.test_bank_file_performance import measure_request
from tests.test_v018_time_app import staff
from tests.test_v0913_finance_assurance import _start
from tests.test_v098_universal_accounting import propose, save

STATIC = Path(__file__).resolve().parent.parent / 'studioos' / 'static'


def books(admin):
    pid, supplier, entity, po, bank, accounts = _start(admin)
    bill = save(admin, propose(admin, 'finance_bill', {'po_id': po, 'invoice_number': 'FICT-BOOKS-BILL', 'amount_paise': 5_000_000}))
    save(admin, propose(admin, 'finance_payment', {'bill_id': bill['id'], 'bank_id': bank, 'amount_paise': 2_000_000,
                                                  'payment_reference': 'FICT-BOOKS-PAY', 'idempotency_key': 'unique-books-pay-1'}))
    return pid, supplier, entity


def test_books_home_matches_the_ledger_to_the_paisa(admin):
    pid, supplier, entity = books(admin)
    home = admin.get('/api/books/home').json()
    c = next(x for x in home['companies'] if x['entity_id'] == entity)
    assert c['payable_paise'] == 3_000_000 and c['open_bills'] == 1
    assert c['ageing'] == {'current': 3_000_000, 'days_31_60': 0, 'days_61_90': 0, 'over_90': 0}     # posted today
    assert c['banks'][0]['balance_paise'] == -2_000_000                                                # the payment left the bank
    assert c['unmatched_payments'] == {'count': 1, 'paise': 2_000_000}
    assert c['owed_by_supplier'][0]['party_id'] == supplier and c['owed_by_supplier'][0]['owed_paise'] == 3_000_000
    integrity = admin.get(f'/api/finance-ledger/integrity/{entity}').json()
    assert c['payable_paise'] == integrity['supplier_outstanding_paise']                              # agrees with the ledger's own check


def test_bank_balances_are_read_together_and_include_reversals(admin):
    from sqlalchemy import select

    from studioos.db import FinanceSupplierPayment, SessionLocal

    _, _, company = books(admin)
    for suffix in ('First Empty', 'Second Empty'):
        save(admin, propose(admin, 'finance_setup', {
            'entity_name': f'Fictional {suffix} Company', 'expense_code': '5000', 'ap_code': '2100',
            'bank_code': '1000', 'bank_name': f'Fictional {suffix} Bank', 'bank_masked': '****1234',
        }))
    for path in ('/api/books/home', '/api/home'):
        with measure_request(path) as queries:
            response = admin.get(path)
        assert response.status_code == 200
        bank_reads = [sql for sql in queries if 'FROM registered_banks' in sql or 'WHERE gl_lines.account_id =' in sql]
        assert len(bank_reads) == 1, bank_reads
        if path == '/api/books/home':
            companies = response.json()['companies']
            assert {row['entity_id']: row['banks'][0]['balance_paise'] for row in companies} == {
                row['entity_id']: -2_000_000 if row['entity_id'] == company else 0 for row in companies
            }
        else:
            assert next(w for w in response.json()['widgets'] if w['key'] == 'cash_bank')['value'] == -2_000_000
    with SessionLocal() as db:
        payment = db.scalar(select(FinanceSupplierPayment.id))
    save(admin, propose(admin, 'finance_reverse_payment', {'payment_id': payment, 'reason': 'Fictional bank correction'}))
    assert all(not row['banks'][0]['balance_paise'] for row in admin.get('/api/books/home').json()['companies'])
    assert next(w for w in admin.get('/api/home').json()['widgets'] if w['key'] == 'cash_bank')['value'] == 0


def test_the_party_page_shows_bills_payments_and_what_is_owed(admin):
    pid, supplier, entity = books(admin)
    d = admin.get(f'/api/books/parties/{supplier}').json()
    assert d['amounts'] is True and d['owed_paise'] == 3_000_000 and d['party']['kind'] == 'vendor'
    assert [b['owed_paise'] for b in d['bills']] == [3_000_000] and d['bills'][0]['paid_paise'] == 2_000_000
    assert d['payments'][0]['amount_paise'] == 2_000_000 and d['payments'][0]['matched'] is False
    assert pid in [p['id'] for p in d['projects']] and d['ageing']['current'] == 3_000_000
    assert admin.get('/api/books/parties/999999').status_code == 404


def test_roles_see_only_what_they_may(admin):
    pid, supplier, entity = books(admin)
    acc, _ = staff(admin, 'acc.books', 'accounts')
    mgr, _ = staff(admin, 'mgr.books', 'manager')
    arch, arch_id = staff(admin, 'arch.books', 'architect')
    site, _ = staff(admin, 'site.books', 'site_engineer')
    try:
        assert acc.get('/api/books/home').status_code == 200                                         # accounts see Books home
        assert mgr.get('/api/books/home').status_code == 403 and arch.get('/api/books/home').status_code == 403 and site.get('/api/books/home').status_code == 403
        assert mgr.get(f'/api/books/parties/{supplier}').json()['amounts'] is True                    # a manager sees amounts on a contact
        assert write(admin, 'put', f'/api/projects/{pid}/members', {'user_ids': [arch_id]}).status_code == 200
        a = arch.get(f'/api/books/parties/{supplier}')
        assert a.status_code == 200 and a.json()['amounts'] is False and 'bills' not in a.json() and 'owed_paise' not in a.json()   # a lead sees contact and projects only
        assert site.get(f'/api/books/parties/{supplier}').status_code == 404                          # site staff see no contacts
    finally:
        for c in (acc, mgr, arch, site):
            c.close()


def test_the_screens_are_wired_and_clean():
    js = (STATIC / 'books.js').read_text(encoding='utf-8')
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    assert '/static/books.js' in html and 'data-view="books"' in html
    assert not re.search(r'\sstyle\s*=', js) and 'eval(' not in js and '.style.' not in js
    assert '/api/books/home' in js and 'api(`/api/books/parties/${Number(id)}`)' in js

"""v64 (Zoho Books): an expense can be billable to a client with a mark-up; it waits as unbilled until it is put on that
client's invoice; it can never be on two live invoices; a reversed invoice frees it again. Fictional data only."""
import pytest
from sqlalchemy import select

from studioos.db import FinanceExpense, FinanceExpenseBilling, Party, SessionLocal
from studioos.expense_billing import billed_amount
from tests.conftest import write
from tests.test_finance_expense import expense_data
from tests.test_m2_bill_form import _setup_company_and_vendor
from tests.test_m3_invoices import _setup_sales_accounts
from tests.test_money_document_dates import draft
from tests.test_v098_universal_accounting import save


@pytest.fixture(autouse=True)
def _enforce(monkeypatch):
    monkeypatch.setenv('STUDIOOS_ENFORCE_REQUIRED_FIELDS', 'true')


def setup(admin, monkeypatch):
    monkeypatch.setenv('STUDIOOS_ENFORCE_REQUIRED_FIELDS', 'false')       # the shared helper creates a bare project
    entity, vendor_id, acc1, acc2, project = _setup_company_and_vendor(admin)
    monkeypatch.setenv('STUDIOOS_ENFORCE_REQUIRED_FIELDS', 'true')
    sales = _setup_sales_accounts(entity)
    return entity, project, sales


def post_expense(admin, entity, project, client_id, key, **extra):
    data = expense_data(admin, entity, project_id=project, request_key=key, amount_paise=100_000)
    r = draft(admin, 'finance_expense', {**data, 'customer_id': client_id, 'billable': True, **extra})
    assert r.status_code == 200, r.text
    return save(admin, r.json())


def invoice(admin, entity, sales, project, number, lines, expense_ids):
    return write(admin, 'post', '/api/sales/invoices', {
        'entity_id': entity, 'client_id': sales['client_id'], 'project_id': project, 'invoice_number': number,
        'invoice_date': '2026-11-15', 'due_date': '2026-12-15', 'supply_type': 'intra', 'ar_account_id': sales['ar_id'],
        'cgst_account_id': sales['cgst_id'], 'sgst_account_id': sales['sgst_id'], 'rounding_account_id': sales['rnd_id'],
        'lines': lines, 'expense_ids': expense_ids})


def line(sales, description, rate):
    return {'income_account_id': sales['rev_id'], 'description': description, 'sac_hsn': '998391', 'quantity': 1,
            'rate_paise': rate, 'tax_rate_bps': 1800}


def unbilled(admin, entity, sales):
    return admin.get(f"/api/sales/unbilled-expenses?entity_id={entity}&client_id={sales['client_id']}").json()['expenses']


def test_markup_is_added_to_the_cost():
    assert billed_amount(100_000, 0) == 100_000
    assert billed_amount(100_000, 1000) == 110_000          # 10%
    assert billed_amount(33_333, 1250) == 37_500            # 12.5%, to the nearest paisa


def test_billable_needs_a_client_and_a_sensible_markup(admin, monkeypatch):
    entity, project, sales = setup(admin, monkeypatch)
    data = expense_data(admin, entity, project_id=project, request_key='fict-bill-check-01')
    no_client = draft(admin, 'finance_expense', {**data, 'billable': True})
    assert no_client.status_code == 422 and 'client' in no_client.text.lower()
    not_a_client = draft(admin, 'finance_expense', {**data, 'billable': True, 'customer_id': data['vendor_id']})
    assert not_a_client.status_code == 422
    too_high = draft(admin, 'finance_expense', {**data, 'billable': True, 'customer_id': sales['client_id'], 'markup_bps': 10_001})
    assert too_high.status_code == 422
    markup_without_billable = draft(admin, 'finance_expense', {**data, 'customer_id': sales['client_id'], 'markup_bps': 500})
    assert markup_without_billable.status_code == 422
    ok = draft(admin, 'finance_expense', {**data, 'billable': True, 'customer_id': sales['client_id'], 'markup_bps': 1000,
                                         'reference_number': 'SUP-INV-77'})
    assert ok.status_code == 200, ok.text
    saved = save(admin, ok.json())
    with SessionLocal() as db:
        e = db.get(FinanceExpense, saved['id'])
        assert (e.customer_id, e.billable, e.markup_bps, e.reference_number) == (sales['client_id'], True, 1000, 'SUP-INV-77')


def test_unbilled_expense_goes_on_an_invoice_once_and_is_freed_by_reversal(admin, monkeypatch):
    entity, project, sales = setup(admin, monkeypatch)
    saved = post_expense(admin, entity, project, sales['client_id'], 'fict-billable-01', markup_bps=1000)
    listed = unbilled(admin, entity, sales)
    assert [(x['id'], x['amount_paise'], x['billable_paise']) for x in listed] == [(saved['id'], 100_000, 110_000)]

    short = invoice(admin, entity, sales, project, 'INV-BILL-0', [line(sales, 'Site supplies', 50_000)], [saved['id']])
    assert short.status_code == 422 and 'less than' in short.text
    r = invoice(admin, entity, sales, project, 'INV-BILL-1', [line(sales, 'Site supplies (recharged)', 110_000)], [saved['id']])
    assert r.status_code == 200, r.text
    assert write(admin, 'post', f"/api/tickets/{r.json()['ticket_id']}/approve-and-save", {'confirmed': [], 'note': 'ok'}).status_code == 200
    assert unbilled(admin, entity, sales) == []
    with SessionLocal() as db:
        link = db.scalar(select(FinanceExpenseBilling))
        assert (link.expense_id, link.billed_paise) == (saved['id'], 110_000)

    twice = invoice(admin, entity, sales, project, 'INV-BILL-2', [line(sales, 'Again', 110_000)], [saved['id']])
    assert twice.status_code == 422 and 'already on an invoice' in twice.text

    inv = admin.get(f'/api/sales/invoices?entity_id={entity}').json()['invoices'][0]
    rev = write(admin, 'post', '/api/universal/proposals', {
        'kind': 'sales_reverse_invoice', 'evidence': 'Fictional invoice reversal',
        'data': {'invoice_id': inv['id'], 'reason': 'Billed by mistake'}})
    assert rev.status_code == 200, rev.text
    assert write(admin, 'post', f"/api/tickets/{rev.json()['ticket_id']}/approve-and-save", {'confirmed': [], 'note': 'ok'}).status_code == 200
    assert [x['id'] for x in unbilled(admin, entity, sales)] == [saved['id']]     # the reversed invoice freed the expense
    again = invoice(admin, entity, sales, project, 'INV-BILL-3', [line(sales, 'Site supplies (recharged)', 110_000)], [saved['id']])
    assert again.status_code == 200, again.text


def test_another_clients_or_non_billable_expense_cannot_go_on_the_invoice(admin, monkeypatch):
    entity, project, sales = setup(admin, monkeypatch)
    with SessionLocal() as db:
        other = Party(kind='client', name='Fictional Other Client')
        db.add(other)
        db.commit()
        other_id = other.id
    theirs = post_expense(admin, entity, project, other_id, 'fict-other-client-1')
    r = invoice(admin, entity, sales, project, 'INV-OTHER', [line(sales, 'Not ours', 100_000)], [theirs['id']])
    assert r.status_code == 422 and 'not billable to this client' in r.text
    plain = draft(admin, 'finance_expense', expense_data(admin, entity, project_id=project, request_key='fict-plain-expense-1'))
    plain_saved = save(admin, plain.json())
    r = invoice(admin, entity, sales, project, 'INV-PLAIN', [line(sales, 'Not billable', 100_000)], [plain_saved['id']])
    assert r.status_code == 422


def test_the_screens_offer_billable_and_the_real_chart_of_accounts_and_the_invoice_picker():
    from pathlib import Path
    static = Path(__file__).resolve().parent.parent / 'studioos' / 'static'
    money = (static / 'money_form.js').read_text(encoding='utf-8')
    assert 'name="billable"' in money and "'Markup'" in money and "'Expense Account'" in money and "'Paid Through'" in money
    assert "x.code ? x.code + ' · '" in money and 'customer_id' in money and 'receipt_ids' in money and 'markup_bps:billableMarkup' in money
    assert 'data-drop-files' in money and 'Attach Receipt' in money and 'Send and add another' in money
    css = (static / 'expenseform.css').read_text(encoding='utf-8')
    assert '.zx-row.req .zx-label{color:var(--bad)}' in css and '.zx-footer{position:sticky' in css
    sales = (static / 'sales.js').read_text(encoding='utf-8')
    assert 'data-sales-billable' in sales and 'bill_expense' in sales and 'expense_ids: expenseIds' in sales
    app = (static / 'app.js').read_text(encoding='utf-8')
    assert 'state.booksActive&&type===\'cost\'' in app


def test_entry_form_offers_clients_and_account_codes(admin, monkeypatch):
    entity, project, sales = setup(admin, monkeypatch)
    expense = next(r for r in admin.get(f'/api/finance-ledger/entry-form/{entity}').json()['recipes'] if r['key'] == 'expense')
    assert sales['client_id'] in [c['id'] for c in expense['customers']]
    assert all(a['code'] for a in expense['items'])
    assert admin.get('/api/form-fields').json()['books_active'] is True

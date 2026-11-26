"""v65 (Zoho Books): an expense split across several expense accounts with GST on it. Fictional data only."""
import pytest
from sqlalchemy import select

from studioos.accounting_kernel import trial_balance
from studioos.db import FinanceExpense, FinanceExpenseLine, GLAccount, GLLine, SessionLocal
from studioos.expense_lines import split_tax
from tests.conftest import write
from tests.test_finance_expense import expense_data
from tests.test_m2_bill_form import _setup_company_and_vendor
from tests.test_m3_invoices import _setup_sales_accounts
from tests.test_money_document_dates import draft
from tests.test_v098_universal_accounting import save


def test_gst_is_added_or_taken_out_to_the_paisa():
    assert split_tax(100_000, 1800, 'exclusive') == (100_000, 18_000)
    assert split_tax(118_000, 1800, 'inclusive') == (100_000, 18_000)
    assert split_tax(99_999, 500, 'inclusive') == (95_237, 4_762)
    assert split_tax(5_000, 0, 'exclusive') == (5_000, 0)
    assert split_tax(5_000, 1800, 'none') == (5_000, 0)
    for amount in (1, 7, 999, 123_457, 10_000_001):                      # no paisa is ever lost
        for mode in ('exclusive', 'inclusive'):
            net, tax = split_tax(amount, 1200, mode)
            assert net + tax == (amount if mode == 'inclusive' else amount + tax) and net >= 0 and tax >= 0


@pytest.fixture
def books(admin, monkeypatch):
    monkeypatch.setenv('STUDIOOS_ENFORCE_REQUIRED_FIELDS', 'false')
    entity, vendor_id, acc1, acc2, project = _setup_company_and_vendor(admin)
    with SessionLocal() as db:
        for code, name in (('INPUT_CGST', 'Input CGST'), ('INPUT_SGST', 'Input SGST'), ('INPUT_IGST', 'Input IGST')):
            db.add(GLAccount(entity_id=entity, code=code, name=name, kind='input_tax', active=True, posting_allowed=True))
        db.commit()
    return entity, project, acc1, acc2


def lines_data(admin, entity, project, acc1, acc2, mode='exclusive', **extra):
    lines = [{'expense_account_id': acc1, 'description': 'Cement', 'amount_paise': 100_000, 'tax_bps': 1800},
             {'expense_account_id': acc2, 'description': 'Sand', 'amount_paise': 50_000, 'tax_bps': 500}]
    base = expense_data(admin, entity, project_id=project, expense_account_id=acc1)
    return {**base, 'lines': lines, 'tax_mode': mode, 'amount_paise': 150_000 + 18_000 + 2_500, **extra}


def balances(entity):
    with SessionLocal() as db:
        out = {}
        for line in db.scalars(select(GLLine).join(GLAccount, GLAccount.id == GLLine.account_id).where(GLAccount.entity_id == entity)):
            account = db.get(GLAccount, line.account_id)
            out[account.name] = out.get(account.name, 0) + (line.amount_paise if line.side == 'debit' else -line.amount_paise)
        return out


def test_itemised_expense_with_gst_posts_balanced_lines_and_can_be_reversed(admin, books):
    entity, project, acc1, acc2 = books
    r = draft(admin, 'finance_expense', lines_data(admin, entity, project, acc1, acc2))
    assert r.status_code == 200, r.text
    saved = save(admin, r.json())
    with SessionLocal() as db:
        e = db.get(FinanceExpense, saved['id'])
        assert (e.amount_paise, e.tax_paise, e.tax_mode, e.place_of_supply) == (170_500, 20_500, 'exclusive', '29')
        got = [(x.net_paise, x.tax_bps, x.tax_paise) for x in db.scalars(select(FinanceExpenseLine).where(FinanceExpenseLine.expense_id == e.id).order_by(FinanceExpenseLine.id))]
        assert got == [(100_000, 1800, 18_000), (50_000, 500, 2_500)]
    tb = trial_balance(db := SessionLocal(), entity)
    db.close()
    assert tb['total_debit_paise'] == tb['total_credit_paise'] == 170_500
    moved = balances(entity)
    assert moved['Input CGST'] == 10_250 and moved['Input SGST'] == 10_250 and moved.get('Input IGST', 0) == 0
    assert sum(moved.values()) == 0
    rev = write(admin, 'post', '/api/finance-ledger/proposals', {'kind': 'finance_reverse_expense', 'evidence': 'Fictional reversal',
                                                                 'data': {'expense_id': saved['id'], 'reason': 'Entered twice by mistake'}})
    assert rev.status_code == 200, rev.text
    save(admin, rev.json())
    assert all(v == 0 for v in balances(entity).values())


def test_inclusive_gst_and_other_state_use_igst(admin, books):
    entity, project, acc1, acc2 = books
    data = lines_data(admin, entity, project, acc1, acc2, mode='inclusive', place_of_supply='27', request_key='fict-igst-0001')
    data['amount_paise'] = 150_000                    # the typed amounts already contain GST
    r = draft(admin, 'finance_expense', data)
    assert r.status_code == 200, r.text
    save(admin, r.json())
    moved = balances(entity)
    assert moved.get('Input IGST') == split_tax(100_000, 1800, 'inclusive')[1] + split_tax(50_000, 500, 'inclusive')[1]
    assert moved.get('Input CGST', 0) == 0 and sum(moved.values()) == 0


def test_totals_must_match_and_gst_needs_its_accounts(admin, books, monkeypatch):
    entity, project, acc1, acc2 = books
    wrong = lines_data(admin, entity, project, acc1, acc2, amount_paise=999)
    assert draft(admin, 'finance_expense', wrong).status_code == 422
    bad_rate = lines_data(admin, entity, project, acc1, acc2)
    bad_rate['lines'][0]['tax_bps'] = 1700
    assert 'GST rate' in draft(admin, 'finance_expense', bad_rate).text
    no_mode = lines_data(admin, entity, project, acc1, acc2, mode='none')
    assert draft(admin, 'finance_expense', no_mode).status_code == 422
    no_lines = {**expense_data(admin, entity, project_id=project), 'tax_mode': 'exclusive'}
    assert draft(admin, 'finance_expense', no_lines).status_code == 422


def test_an_expense_without_lines_posts_exactly_as_before(admin, books):
    entity, project, acc1, acc2 = books
    r = draft(admin, 'finance_expense', expense_data(admin, entity, project_id=project, request_key='fict-plain-0001'))
    assert r.status_code == 200, r.text
    saved = save(admin, r.json())
    with SessionLocal() as db:
        e = db.get(FinanceExpense, saved['id'])
        assert (e.tax_mode, e.tax_paise) == ('none', 0)
        assert db.scalars(select(FinanceExpenseLine).where(FinanceExpenseLine.expense_id == e.id)).all() == []
    assert sum(balances(entity).values()) == 0


def test_billing_a_client_uses_the_cost_before_gst(admin, books):
    entity, project, acc1, acc2 = books
    sales = _setup_sales_accounts(entity)
    data = lines_data(admin, entity, project, acc1, acc2, customer_id=sales['client_id'], billable=True, markup_bps=1000,
                      request_key='fict-bill-gst-01')
    saved = save(admin, draft(admin, 'finance_expense', data).json())
    listed = admin.get(f"/api/sales/unbilled-expenses?entity_id={entity}&client_id={sales['client_id']}").json()['expenses']
    assert [(x['id'], x['amount_paise'], x['billable_paise']) for x in listed] == [(saved['id'], 150_000, 165_000)]


def test_gst_cannot_be_claimed_until_the_company_has_its_input_gst_accounts(admin, monkeypatch):
    monkeypatch.setenv('STUDIOOS_ENFORCE_REQUIRED_FIELDS', 'false')
    entity, vendor_id, acc1, acc2, project = _setup_company_and_vendor(admin)       # no Input GST accounts here
    r = draft(admin, 'finance_expense', lines_data(admin, entity, project, acc1, acc2, request_key='fict-nogst-0001'))
    assert r.status_code == 422 and 'Input GST accounts' in r.text
    # without GST the same two lines are fine
    plain = lines_data(admin, entity, project, acc1, acc2, mode='none', request_key='fict-nogst-0002')
    for ln in plain['lines']:
        ln['tax_bps'] = 0
    plain['amount_paise'] = 150_000
    ok = draft(admin, 'finance_expense', plain)
    assert ok.status_code == 200, ok.text
    save(admin, ok.json())
    assert sum(balances(entity).values()) == 0


def test_the_expense_page_offers_itemize_tax_inclusive_exclusive_and_place_of_supply():
    from pathlib import Path
    static = Path(__file__).resolve().parent.parent / 'studioos' / 'static'
    money = (static / 'money_form.js').read_text(encoding='utf-8')
    for text in ('data-zx="itemize"', 'data-zx="add-item"', 'Back to a single account', "'Amount is'", 'Tax Exclusive', 'Tax Inclusive',
                 "'Place of Supply'", 'Sub Total', 'zxLinesPayload', 'tax_mode:itemised.mode', 'place_of_supply:itemised.place'):
        assert text in money, text
    css = (static / 'expenseform.css').read_text(encoding='utf-8')
    assert '.zx-itemrow' in css and '.zx-totals' in css


def test_entry_form_tells_the_screen_about_gst(admin, books):
    entity = books[0]
    expense = next(r for r in admin.get(f'/api/finance-ledger/entry-form/{entity}').json()['recipes'] if r['key'] == 'expense')
    assert expense['gst'] == {'rates_bps': [0, 500, 1200, 1800, 2800], 'company_state': '29', 'intra_ready': True, 'inter_ready': True}

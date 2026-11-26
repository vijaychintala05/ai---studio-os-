"""v68: a money entry needs a company and its chart of accounts. Fictional data only."""
import pytest
from sqlalchemy import select

from studioos import money_rules
from studioos.db import ApprovalTicketItem, FinanceExpense, FinancePurchaseOrder, SessionLocal
from tests.conftest import write
from tests.test_v0914_chart_of_accounts import approve, chat
from tests.test_v098_universal_accounting import finance_setup, project, vendor


@pytest.fixture(autouse=True)
def _rule_on(monkeypatch):
    monkeypatch.setenv('STUDIOOS_REQUIRE_CHART_OF_ACCOUNTS', 'true')
    monkeypatch.setenv('STUDIOOS_ENFORCE_REQUIRED_FIELDS', 'false')


def test_without_a_company_no_money_entry_can_be_made_and_the_screens_say_why(admin):
    pid = project(admin)
    form = admin.get('/api/form-fields').json()
    assert form['chart_missing'] is True and 'chart of accounts' in form['setup_message']
    cost = write(admin, 'post', '/api/costs', {'project_id': pid, 'kind': 'expense', 'title': 'Fictional survey', 'amount': '1000'})
    assert cost.status_code == 400 and money_rules.SETUP_MESSAGE in cost.text
    site = write(admin, 'post', '/api/site-expenses', {'project_id': pid, 'title': 'Tea for the crew', 'amount': '200'})
    assert site.status_code == 400 and 'chart of accounts' in site.text


def test_without_a_company_the_chat_asks_for_the_setup_instead_of_drafting_money(admin):
    project(admin)
    for sentence in ('Expense 4500 sand for Fictional Project A', 'Ordered 50 sheets of plywood for Fictional Project A for ₹90,000',
                     'Paid 5000 to ABC Fictional Suppliers against cost #1'):
        r = chat(admin, sentence)
        assert money_rules.SETUP_MESSAGE in r['reply'], (sentence, r['reply'])
        assert not r.get('ticket_id')
    with SessionLocal() as db:
        assert db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.item_type.in_(('record_cost', 'record_payment')))).all() == []
    # things that are not money still work
    assert chat(admin, 'create a project named Villa 40 client name Srinu').get('ticket_id')


def test_once_a_company_exists_money_goes_through_books_and_the_older_tracker_is_closed(admin):
    pid = project(admin)
    finance_setup(admin)
    assert admin.get('/api/form-fields').json()['chart_missing'] is False
    old = write(admin, 'post', '/api/costs', {'project_id': pid, 'kind': 'expense', 'title': 'Fictional survey', 'amount': '1000'})
    assert old.status_code == 400 and 'Accounting is active' in old.text


def test_chat_makes_a_books_expense_as_soon_as_the_company_is_set_up_even_without_the_standard_chart(admin, monkeypatch):
    pid = project(admin)
    finance_setup(admin)
    vendor(admin)
    monkeypatch.setenv('STUDIOOS_ENFORCE_REQUIRED_FIELDS', 'true')
    r = chat(admin, 'Expense 4500 sand for Fictional Project A paid by cash')
    item = r['preview']['items'][0]
    assert item['item_type'] == 'finance_expense'
    f = {x['key']: x for x in item['fields']}
    assert f['amount_paise']['raw'] == 450_000 and f['expense_account_id']['choices'] and f['vendor_id']['choices']
    assert any('MISSING required' in x and 'Vendor' in x for x in item['flags'])


def test_chat_raises_a_purchase_order_without_the_standard_chart_and_it_is_saved_on_the_chart(admin):
    pid = project(admin)
    finance_setup(admin)
    vendor(admin)
    r = chat(admin, 'Raise a purchase order for ABC Fictional Suppliers for Fictional Project A for ₹21,000')
    assert r['preview']['items'][0]['item_type'] == 'finance_po'
    done = approve(admin, r)
    assert done.status_code == 200, done.text
    with SessionLocal() as db:
        po = db.scalar(select(FinancePurchaseOrder))
        assert po is not None and po.amount_paise == 2_100_000


def test_the_rule_can_be_switched_off_only_by_the_environment(monkeypatch, admin):
    monkeypatch.setenv('STUDIOOS_REQUIRE_CHART_OF_ACCOUNTS', 'false')
    pid = project(admin)
    ok = write(admin, 'post', '/api/costs', {'project_id': pid, 'kind': 'expense', 'title': 'Fictional survey', 'amount': '1000'})
    assert ok.status_code == 200, ok.text


def test_the_screens_send_the_person_to_the_setup():
    from pathlib import Path
    static = Path(__file__).resolve().parent.parent / 'studioos' / 'static'
    app = (static / 'app.js').read_text(encoding='utf-8')
    assert "state.chartMissing&&['cost','payment'].includes(type)" in app and "switchView('ledger')" in app
    assert 'chart_missing' in (static / 'forms.js').read_text(encoding='utf-8')

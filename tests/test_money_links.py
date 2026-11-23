"""Money-link validation at both drafting and final approval."""
from studioos.db import Party, SessionLocal

from .conftest import write
from .test_finance_expense import expense_data
from .test_money_document_dates import bill_data, draft
from .test_v0913_finance_assurance import _start
from .test_v098_universal_accounting import finance_setup, project, save


def test_a_bill_rechecks_its_vendor_before_posting(admin):
    _, vendor_id, entity, order, _, _ = _start(admin)
    proposal = draft(admin, 'finance_bill', bill_data(order))
    assert proposal.status_code == 200, proposal.text
    with SessionLocal() as db:
        db.get(Party, vendor_id).kind = 'client'
        db.commit()
    result = draft(admin, 'finance_bill', bill_data(order))
    assert result.status_code == 422 and 'vendor' in result.text
    saved = write(admin, 'post', f'/api/tickets/{proposal.json()["ticket_id"]}/approve-and-save', {})
    assert saved.status_code in (409, 422) and 'vendor' in saved.text
    assert admin.get(f'/api/finance-ledger/journals/{entity}').json() == []


def test_posted_direct_expense_closes_the_parallel_tracker_even_without_a_chart(admin):
    pid = project(admin)
    company = finance_setup(admin)
    cost = {'project_id': pid, 'kind': 'expense', 'title': 'Fictional tracker entry', 'amount': '100'}
    old = write(admin, 'post', '/api/costs', cost)
    assert old.status_code == 200, old.text
    data = expense_data(admin, company, project_id=pid)
    save(admin, draft(admin, 'finance_expense', data).json())
    new = write(admin, 'post', '/api/costs', cost)
    assert new.status_code in (400, 422) and 'Record expense' in new.text
    saved = write(admin, 'post', f'/api/tickets/{old.json()["ticket_id"]}/approve-and-save', {})
    assert saved.status_code in (409, 422) and 'Record expense' in saved.text
    trial = admin.get(f'/api/finance-ledger/trial-balance/{company}').json()
    assert trial['total_debit_paise'] == trial['total_credit_paise'] == data['amount_paise']

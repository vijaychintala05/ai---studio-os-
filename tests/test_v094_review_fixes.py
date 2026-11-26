"""v0.9.4 fixes for the independent v0.9.3 review (C2, H1, H2, M3, M4, M10). Fictional data only.
Needs FastAPI and SQLAlchemy; runs in the automatic pipeline."""
from fastapi.testclient import TestClient
from sqlalchemy import select
from .books_fixtures import draft_project_expense
from .conftest import write, approved_form
from .test_money_form_tickets import _payment_form
from .test_v080_chat_app import expense as books_expense
from .test_v098_universal_accounting import finance_setup, propose, save
from studioos.main import app
from studioos.db import ApprovalTicket, ApprovalTicketItem, FinanceDirectBillPayment, FinanceExpense, GLAccount, Project, SessionLocal


def login(username, password):
    c = TestClient(app)
    assert c.post('/api/auth/login', json={'username': username, 'password': password}).status_code == 200
    return c


# Test-only fictional secret independent of the username; complies with v0.9.5 policy.
FICTIONAL_USER_PASSWORD = 'fictional-safe-test-secret-2026-long'

def user(admin, username, role):
    r = write(admin, 'post', '/api/users', {'username': username, 'display_name': username.title(), 'role': role,
                                           'password': FICTIONAL_USER_PASSWORD})
    assert r.status_code == 200, r.text
    return login(username, FICTIONAL_USER_PASSWORD)


def project(admin, name='Review Villa', budget='500000'):
    assert approved_form(admin,'post','/api/projects', {'name': name, 'budget': budget}).status_code == 200
    return next(p['id'] for p in admin.get('/api/projects').json() if p['name'] == name)


def chat(c, msg, sid=''):
    r = write(c, 'post', '/api/chat', {'message': msg, 'session_id': sid})
    assert r.status_code == 200, r.text
    return r.json()


def test_c2_manager_cannot_approve_own_cost_on_the_approvals_screen(admin):
    finance_setup(admin)
    project_id = project(admin)
    limits = write(admin, 'put', '/api/approval-limits', {'manager_per_transaction_paise': 500000})
    assert limits.status_code == 200
    with user(admin, 'mgr21', 'manager') as manager, user(admin, 'mgr22', 'manager') as other:
        draft = draft_project_expense(manager, project_id, 500000, note='Fictional plywood')
        assert draft.status_code == 200, draft.text
        path = f"/api/tickets/{draft.json()['ticket_id']}/approve-and-save"
        assert write(manager, 'post', path, {}).status_code == 403
        saved = write(other, 'post', path, {})
        assert saved.status_code == 200, saved.text
    with SessionLocal() as db:
        expense = db.get(FinanceExpense, saved.json()['committed_records'][0]['id'])
        item = db.get(ApprovalTicketItem, draft.json()['item_id'])
        assert expense.submitted_by_id != item.decided_by


def test_c2_payment_creator_cannot_approve_it(admin):
    body = _payment_form(admin)
    with user(admin, 'acc21', 'accounts') as accounts:
        proposal = write(accounts, 'post', '/api/universal/proposals', body)
        assert proposal.status_code == 200, proposal.text
        draft = proposal.json()
        assert write(accounts, 'post', f"/api/tickets/{draft['ticket_id']}/approve-and-save", {}).status_code == 403
    record = save(admin, draft)
    with SessionLocal() as db:
        payment = db.get(FinanceDirectBillPayment, record['id'])
        ticket = db.get(ApprovalTicket, payment.ticket_id)
        item = db.get(ApprovalTicketItem, draft['item_id'])
        assert item.decided_by is not None and ticket.submitter_id != item.decided_by
        assert payment.paid_through_id == body['data']['paid_through_id']
        assert payment.payment_date == body['data']['payment_date']


def test_h1_ticket_approval_is_the_only_money_approval(admin):
    r = books_expense(admin, 'Review Villa')
    assert write(admin, 'post', f"/api/tickets/{r['ticket_id']}/approve-and-save", {}).status_code == 200
    assert admin.get('/api/approvals').json()['costs'] == []
    budgets = {b['name']: b for b in admin.get('/api/budgets').json()}
    assert budgets['Review Villa']['actual'] == 3200


def test_h2_every_approved_field_is_saved(admin):
    draft = books_expense(admin, 'Review Villa')
    fields = draft['preview']['items'][0]['after']
    posted = save(admin, draft)
    with SessionLocal() as db:
        expense = db.get(FinanceExpense, posted['id'])
        assert db.get(GLAccount, expense.paid_through_id).kind == 'cash'
        for field in ('date', 'project_id', 'vendor_id', 'paid_through_id', 'expense_account_id', 'amount_paise', 'note'):
            assert getattr(expense, field) == fields[field]


def test_h2_m3_correction_shows_net_before_and_applies_description(admin):
    posted = save(admin, books_expense(admin, 'Review Villa'))
    original_id = posted['id']
    old_amount = 320000
    for amount, note in ((300000, 'Fictional plumbing labour'), (280000, 'Fictional plumbing labour, final')):
        draft = propose(admin, 'finance_correct_expense', {'expense_id': posted['id'], 'before_amount_paise': old_amount,
                        'amount_paise': amount, 'note': note, 'reason': 'Fictional corrected supplier invoice'})
        assert draft['accounting_preview']['before_amount_paise'] == old_amount
        assert draft['accounting_preview']['note'] == note
        posted = save(admin, draft)
        old_amount = amount
    with SessionLocal() as db:
        expense = db.get(FinanceExpense, posted['id'])
        assert (expense.note, expense.amount_paise) == ('Fictional plumbing labour, final', 280000)
        assert db.get(FinanceExpense, original_id).amount_paise == 320000
    refused = write(admin, 'post', '/api/universal/proposals', {'kind': 'finance_correct_expense',
        'data': {'expense_id': posted['id'], 'before_amount_paise': 280000, 'amount_paise': 280000,
                 'kind': 'commitment', 'reason': 'Fictional effort to convert an expense'},
        'evidence': 'A correction cannot replace an expense with a purchase order'})
    assert refused.status_code == 422


def test_m4_rename_onto_existing_project_is_refused_clearly(admin, monkeypatch):
    import studioos.main as main
    project(admin, 'Alpha Villa'); pid = project(admin, 'Beta Villa')
    monkeypatch.setattr(main, 'extract', lambda *a, **k: {'intent': 'update_project', 'data': {'id': pid, 'name': 'alpha villa'}})
    u = chat(admin, 'Rename Beta Villa to Alpha Villa')
    s = write(admin, 'post', f"/api/tickets/{u['ticket_id']}/approve-and-save", {})
    assert s.status_code == 422 and 'already has this name' in s.text
    with SessionLocal() as db:
        assert db.get(Project, pid).name == 'Beta Villa'

"""Owner decision 5: the owner may still approve their own money entry, but it is flagged in the audit log.
Fictional data only."""
from sqlalchemy import select
from studioos.db import SessionLocal, Audit
from studioos.two_person import is_own_entry, is_owner_self_approval
from .books_fixtures import draft_project_expense
from .conftest import write, approved_form
from .test_v098_universal_accounting import finance_setup


def audit_texts():
    with SessionLocal() as db:
        return [a.description for a in db.scalars(select(Audit)).all()]


def test_the_helper_only_fires_for_the_owner_on_their_own_entry():
    assert is_owner_self_approval('admin', 5, 5) is True
    assert is_owner_self_approval('admin', 5, 6) is False
    assert is_owner_self_approval('manager', 5, 5) is False       # a manager is blocked, not flagged
    assert is_owner_self_approval('admin', 5, None) is False
    assert is_own_entry('admin', 5, 5) is False                    # the owner's exception itself is unchanged


def test_owner_approving_their_own_cost_is_allowed_and_flagged(admin):
    finance_setup(admin)
    pid = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Own Approval Site', 'budget': '1000000'}).json()['id']
    r = draft_project_expense(admin, pid, 120000, note='Fictional tiles')
    assert r.status_code == 200, r.text
    assert write(admin, 'post', f'/api/tickets/{r.json()["ticket_id"]}/approve-and-save', {}).status_code == 200
    assert any('owner approved their own money entry' in t.lower() for t in audit_texts())


def test_owner_approving_someone_elses_entry_is_not_flagged(admin):
    finance_setup(admin)
    pid = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Other Approval Site', 'budget': '1000000'}).json()['id']
    write(admin, 'post', '/api/users', {'username': 'own_acc', 'display_name': 'Fictional Accounts', 'role': 'accounts', 'password': 'fictional-accounts-own-1'})
    from fastapi.testclient import TestClient
    from studioos.main import app
    acc = TestClient(app)
    assert acc.post('/api/auth/login', json={'username': 'own_acc', 'password': 'fictional-accounts-own-1'}).status_code == 200
    r = draft_project_expense(acc, pid, 90000, note='Fictional paint')
    assert r.status_code == 200, r.text
    assert write(admin, 'post', f'/api/tickets/{r.json()["ticket_id"]}/approve-and-save', {}).status_code == 200
    assert not any('owner approved their own money entry' in t.lower() for t in audit_texts())


def test_bank_statement_lines_are_not_flagged_one_by_one():
    import pathlib
    src = pathlib.Path('studioos/main.py').read_text()
    block = src[src.index('OWNER_FLAGGED_ENTRY_TYPES=('):].split('\n', 1)[0]
    assert 'finance_bank_statement_line' not in block and 'finance_reconcile_bank' not in block

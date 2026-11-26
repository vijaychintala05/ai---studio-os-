"""v0.23.1: the two-person money rule lives in one place (studioos/two_person.py).
Behaviour must not change: the Admin (owner) may approve their own entry, nobody else may."""
import pathlib
import re
from .books_fixtures import draft_project_expense
from .conftest import write, approved_form
from .test_v098_universal_accounting import finance_setup


def test_rule_blocks_everyone_but_the_admin_from_approving_their_own_entry():
    from studioos.two_person import is_own_entry
    assert is_own_entry('manager', 5, 5) is True
    assert is_own_entry('accounts', 5, 5) is True
    assert is_own_entry('admin', 5, 5) is False          # the owner's exception stays
    assert is_own_entry('manager', 5, 6) is False
    assert is_own_entry('manager', 5, None) is False      # an old entry with no creator is not blocked


def test_message_for_a_blocked_approver_is_plain_english():
    from studioos.two_person import OWN_ENTRY_MESSAGE
    assert 'someone else' in OWN_ENTRY_MESSAGE


def test_the_rule_is_not_copied_inline_any_more():
    root = pathlib.Path('studioos')
    for name in ('main.py', 'legacy_money.py'):
        text = (root / name).read_text()
        assert not re.search(r"user\.role!='admin'\s*and\s*ticket\.submitter_id", text), name
        assert not re.search(r"actor\.role!='admin'\s*and\s*obj\.created_by_id", text), name
        assert 'two_person' in text, name


def test_a_manager_still_cannot_approve_their_own_money_ticket(admin):
    finance_setup(admin)
    pid = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Second Person Site', 'budget': '100000'}).json()['id']
    write(admin, 'post', '/api/users', {'username': 'mgr23', 'display_name': 'Manager', 'role': 'manager', 'password': 'fictional-manager-231'})
    from fastapi.testclient import TestClient
    from studioos.main import app
    m = TestClient(app)
    assert m.post('/api/auth/login', json={'username': 'mgr23', 'password': 'fictional-manager-231'}).status_code == 200
    r = draft_project_expense(m, pid, 120000, note='Fictional tiles')
    assert r.status_code == 200, r.text
    own = write(m, 'post', f'/api/tickets/{r.json()["ticket_id"]}/approve-and-save', {})
    assert own.status_code == 403, own.text
    assert write(admin, 'post', f'/api/tickets/{r.json()["ticket_id"]}/approve-and-save', {}).status_code == 200

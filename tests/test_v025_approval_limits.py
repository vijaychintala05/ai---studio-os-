"""v0.25: the owner can let the Manager role approve money items up to a per-transaction limit.
Off by default. The two-person rule still applies. Fictional data only."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from studioos.main import app
from studioos.db import SessionLocal, Audit
from .conftest import write, approved_form


def login(name, pw):
    c = TestClient(app)
    assert c.post('/api/auth/login', json={'username': name, 'password': pw}).status_code == 200
    return c


@pytest.fixture
def team(admin):
    pid = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Limit Site', 'budget': '10000000'}).json()['id']
    for name, role in (('lim_mgr', 'manager'), ('lim_acc', 'accounts')):
        assert write(admin, 'post', '/api/users', {'username': name, 'display_name': name, 'role': role, 'password': f'fictional-{role}-limit-1'}).status_code == 200
    return pid, login('lim_mgr', 'fictional-manager-limit-1'), login('lim_acc', 'fictional-accounts-limit-1')


def draft_cost(c, pid, amount, title=None):
    r = write(c, 'post', '/api/costs', {'project_id': pid, 'kind': 'expense', 'title': title or f'Fictional purchase {amount} {len(str(amount))}{amount % 97}', 'vendor': f'Fictional Vendor {amount}', 'amount': str(amount)})
    assert r.status_code == 200, r.text
    return r.json()['ticket_id']


def approve(c, ticket):
    return write(c, 'post', f'/api/tickets/{ticket}/approve-and-save', {})


def test_no_limit_set_means_no_change_manager_cannot_approve_money(admin, team):
    pid, mgr, acc = team
    assert admin.get('/api/approval-limits').json() == {'manager_per_transaction_paise': 0}
    assert approve(mgr, draft_cost(acc, pid, 1200)).status_code == 403


def test_only_the_owner_can_read_or_set_limits(admin, team):
    pid, mgr, acc = team
    assert mgr.get('/api/approval-limits').status_code == 403
    assert write(mgr, 'put', '/api/approval-limits', {'manager_per_transaction_paise': 500000}).status_code == 403
    assert write(acc, 'put', '/api/approval-limits', {'manager_per_transaction_paise': 500000}).status_code == 403


def test_manager_can_approve_up_to_the_limit_but_not_above(admin, team):
    pid, mgr, acc = team
    assert write(admin, 'put', '/api/approval-limits', {'manager_per_transaction_paise': 500000}).status_code == 200
    assert approve(mgr, draft_cost(acc, pid, 2000)).status_code == 200
    assert approve(mgr, draft_cost(acc, pid, 5000)).status_code == 200      # exactly the limit is allowed
    assert approve(mgr, draft_cost(acc, pid, 7000)).status_code == 403      # above it waits for the owner


def test_the_two_person_rule_still_applies(admin, team):
    pid, mgr, acc = team
    write(admin, 'put', '/api/approval-limits', {'manager_per_transaction_paise': 500000})
    own = draft_cost(mgr, pid, 1200)
    assert approve(mgr, own).status_code == 403          # a manager still cannot approve their own entry
    assert approve(admin, own).status_code == 200        # the owner can, as before


def test_removing_the_limit_takes_the_power_back(admin, team):
    pid, mgr, acc = team
    write(admin, 'put', '/api/approval-limits', {'manager_per_transaction_paise': 500000})
    t = draft_cost(acc, pid, 1200)
    write(admin, 'put', '/api/approval-limits', {'manager_per_transaction_paise': 0})
    assert approve(mgr, t).status_code == 403


def test_bad_limits_are_refused_and_changes_are_audited(admin):
    for bad in (-1, 'abc', 10 ** 13, 1.5):
        assert write(admin, 'put', '/api/approval-limits', {'manager_per_transaction_paise': bad}).status_code in (400, 422), bad
    assert write(admin, 'put', '/api/approval-limits', {'manager_per_transaction_paise': 250000}).status_code == 200
    with SessionLocal() as db:
        assert any('approval limit' in (a.description or '').lower() for a in db.scalars(select(Audit)).all())


def test_owner_screen_has_a_limit_panel_and_it_says_the_amount_back():
    import pathlib
    js = pathlib.Path('studioos/static/app.js').read_text()
    assert 'id="approvalLimitPanel"' in js and "manager_per_transaction_paise:paise" in js and "state.view==='team'&&isAdmin()" in js
    assert 'style="' not in js

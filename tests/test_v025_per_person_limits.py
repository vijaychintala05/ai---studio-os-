"""v0.25.0: the owner can give each Manager their own approval limits. A person's own entry overrides the role-wide
limit; with none, they inherit it. No schema change: the entries live in the existing owner setting. Fictional data only."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from studioos.main import app
from studioos.db import SessionLocal, Audit
from .books_fixtures import draft_project_expense
from .conftest import write, approved_form
from .test_v098_universal_accounting import finance_setup


def login(name, pw):
    c = TestClient(app)
    assert c.post('/api/auth/login', json={'username': name, 'password': pw}).status_code == 200
    return c


@pytest.fixture
def team(admin):
    finance_setup(admin)
    pid = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Person Limit Site', 'budget': '100000000'}).json()['id']
    ids = {}
    for name, role in (('pl_acc', 'accounts'), ('pl_mgr_a', 'manager'), ('pl_mgr_b', 'manager'), ('pl_arch', 'architect')):
        r = write(admin, 'post', '/api/users', {'username': name, 'display_name': f'Fictional {name}', 'role': role, 'password': f'fictional-{role}-person-1'})
        assert r.status_code == 200, r.text
    ids = {u['username']: u['id'] for u in admin.get('/api/users').json()}
    clients = {n: login(n, f'fictional-{r}-person-1') for n, r in (('pl_acc', 'accounts'), ('pl_mgr_a', 'manager'), ('pl_mgr_b', 'manager'))}
    return pid, ids, clients


def draft(c, pid, amount):
    r = draft_project_expense(c, pid, amount * 100, note=f'Fictional purchase {amount}')
    assert r.status_code == 200, r.text
    return r.json()['ticket_id']


def approve(c, ticket):
    return write(c, 'post', f'/api/tickets/{ticket}/approve-and-save', {})


def role_limits(admin, per_tx, monthly=0):
    assert write(admin, 'put', '/api/approval-limits', {'manager_per_transaction_paise': per_tx, 'monthly_per_manager_paise': monthly}).status_code == 200


def person(admin, uid, per_tx, monthly=0):
    return write(admin, 'put', f'/api/approval-limits/people/{uid}', {'per_transaction_paise': per_tx, 'monthly_paise': monthly})


def test_only_the_owner_sees_or_sets_person_limits(admin, team):
    pid, ids, c = team
    assert c['pl_mgr_a'].get('/api/approval-limits/people').status_code == 403
    assert write(c['pl_mgr_a'], 'put', f'/api/approval-limits/people/{ids["pl_mgr_a"]}', {'per_transaction_paise': 100, 'monthly_paise': 0}).status_code == 403


def test_the_list_shows_every_manager_and_whether_they_inherit(admin, team):
    pid, ids, c = team
    role_limits(admin, 500000)
    rows = {r['username']: r for r in admin.get('/api/approval-limits/people').json()}
    assert set(rows) == {'pl_mgr_a', 'pl_mgr_b'}                       # managers only
    assert rows['pl_mgr_a']['inherits_role'] is True and rows['pl_mgr_a']['per_transaction_paise'] == 500000
    assert person(admin, ids['pl_mgr_a'], 200000).status_code == 200
    rows = {r['username']: r for r in admin.get('/api/approval-limits/people').json()}
    assert rows['pl_mgr_a']['inherits_role'] is False and rows['pl_mgr_a']['per_transaction_paise'] == 200000
    assert rows['pl_mgr_b']['inherits_role'] is True


def test_a_personal_limit_lower_than_the_role_limit_applies(admin, team):
    pid, ids, c = team
    role_limits(admin, 500000)                                          # ₹5,000 for managers in general
    person(admin, ids['pl_mgr_a'], 200000)                              # ₹2,000 for A
    assert approve(c['pl_mgr_a'], draft(c['pl_acc'], pid, 3000)).status_code == 403
    assert approve(c['pl_mgr_b'], draft(c['pl_acc'], pid, 3050)).status_code == 200    # B inherits ₹5,000


def test_a_personal_limit_can_be_higher_than_no_role_limit(admin, team):
    pid, ids, c = team
    person(admin, ids['pl_mgr_a'], 500000)                              # only A is trusted; no role-wide limit
    assert approve(c['pl_mgr_a'], draft(c['pl_acc'], pid, 4000)).status_code == 200
    assert approve(c['pl_mgr_b'], draft(c['pl_acc'], pid, 4100)).status_code == 403


def test_a_personal_zero_takes_the_power_away_even_when_the_role_has_a_limit(admin, team):
    pid, ids, c = team
    role_limits(admin, 500000)
    person(admin, ids['pl_mgr_a'], 0)
    assert approve(c['pl_mgr_a'], draft(c['pl_acc'], pid, 1000)).status_code == 403
    assert approve(c['pl_mgr_b'], draft(c['pl_acc'], pid, 1100)).status_code == 200


def test_clearing_a_personal_limit_goes_back_to_the_role_limit(admin, team):
    pid, ids, c = team
    role_limits(admin, 500000)
    person(admin, ids['pl_mgr_a'], 0)
    r = admin.delete(f'/api/approval-limits/people/{ids["pl_mgr_a"]}', headers={'X-CSRF-Token': admin.cookies.get('studioos_csrf', '')})
    assert r.status_code == 200, r.text
    assert approve(c['pl_mgr_a'], draft(c['pl_acc'], pid, 1000)).status_code == 200


def test_the_monthly_total_is_personal_and_ignores_the_role_wide_one(admin, team):
    pid, ids, c = team
    role_limits(admin, 500000, 100000)                                  # role monthly ₹1,000 (would block everyone)
    person(admin, ids['pl_mgr_a'], 500000, 700000)                      # A: ₹5,000 each, ₹7,000 a month
    assert approve(c['pl_mgr_a'], draft(c['pl_acc'], pid, 4000)).status_code == 200
    r = approve(c['pl_mgr_a'], draft(c['pl_acc'], pid, 3500))
    assert r.status_code == 403 and 'monthly' in r.text.lower()         # 4,000 + 3,500 is over A's 7,000
    assert approve(c['pl_mgr_b'], draft(c['pl_acc'], pid, 600)).status_code == 200       # B is held to the role-wide ₹1,000


def test_only_managers_can_be_given_limits_and_values_are_checked(admin, team):
    pid, ids, c = team
    assert person(admin, ids['pl_arch'], 100000).status_code == 404     # an architect is not a manager
    assert person(admin, 999999, 100000).status_code == 404
    for bad in (-1, 10 ** 13, 'x', 1.5):
        assert write(admin, 'put', f'/api/approval-limits/people/{ids["pl_mgr_a"]}', {'per_transaction_paise': bad, 'monthly_paise': 0}).status_code in (400, 422), bad


def test_the_two_person_rule_still_applies_to_a_manager_with_a_personal_limit(admin, team):
    pid, ids, c = team
    person(admin, ids['pl_mgr_a'], 500000)
    own = draft(c['pl_mgr_a'], pid, 1000)
    assert approve(c['pl_mgr_a'], own).status_code == 403


def test_changes_are_audited_and_my_rights_show_the_personal_numbers(admin, team):
    pid, ids, c = team
    person(admin, ids['pl_mgr_a'], 200000, 900000)
    with SessionLocal() as db:
        assert any('pl_mgr_a' in (a.description or '') and 'limit' in (a.description or '').lower() for a in db.scalars(select(Audit)).all())
    r = c['pl_mgr_a'].get('/api/my-approval-rights').json()
    assert r['money_limit_rupees'] == 2000 and r['monthly_total_rupees'] == 9000


def test_latest_schema_includes_approval_tracking():
    from studioos.migrations import LATEST_VERSION
    assert LATEST_VERSION >= 39


def test_saving_the_role_wide_limits_keeps_personal_entries(admin, team):
    pid, ids, c = team
    person(admin, ids['pl_mgr_a'], 200000, 300000)
    role_limits(admin, 700000, 900000)                                   # change the role-wide numbers afterwards
    rows = {r['username']: r for r in admin.get('/api/approval-limits/people').json()}
    assert rows['pl_mgr_a']['per_transaction_paise'] == 200000 and rows['pl_mgr_a']['monthly_paise'] == 300000 and not rows['pl_mgr_a']['inherits_role']
    assert rows['pl_mgr_b']['per_transaction_paise'] == 700000 and rows['pl_mgr_b']['inherits_role']


def test_owner_screen_lists_managers_with_their_own_amount_fields():
    import json, pathlib, subprocess
    js = pathlib.Path('studioos/static/app.js').read_text()
    fn = js[js.index('function personLimitsPanel'):js.index('async function loadPersonLimits')]
    script = ("const esc=s=>String(s);const amountEcho=t=>'₹'+t;const state={personLimits:[{user_id:7,username:'asha',display_name:'Fictional Asha',per_transaction_paise:500000,monthly_paise:0,inherits_role:true},"
              "{user_id:8,username:'ravi',display_name:'Fictional Ravi',per_transaction_paise:200000,monthly_paise:900000,inherits_role:false}]};\n" + fn + "\nconsole.log(personLimitsPanel());")
    html = subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True).stdout
    assert 'Fictional Asha' in html and 'follows the limit above' in html
    assert 'Fictional Ravi' in html and 'has their own limits' in html
    assert html.count('data-person-clear=') == 1            # only a Manager with their own limits can go back to the role limit
    assert 'value="5000"' in html and 'value="2000"' in html and 'value="9000"' in html
    assert 'style="' not in html


def test_screen_calls_the_person_endpoints_and_is_shown_on_the_team_view():
    import pathlib
    js = pathlib.Path('studioos/static/app.js').read_text()
    assert "'/api/approval-limits/people/'" in js and "method:'DELETE'" in js and 'approvalLimitPanel()+personLimitsPanel()' in js

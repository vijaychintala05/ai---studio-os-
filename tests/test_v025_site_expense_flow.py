"""v0.25: a site engineer can draft a small expense on their own project from site. It is only a draft:
a ticket that someone else approves. They still cannot see money screens. Fictional data only."""
import pytest
from fastapi.testclient import TestClient
from studioos.main import app
from .conftest import write, approved_form


def login(name, pw):
    c = TestClient(app)
    assert c.post('/api/auth/login', json={'username': name, 'password': pw}).status_code == 200
    return c


@pytest.fixture
def site(admin):
    mine = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Site Expense Villa', 'budget': '10000000'}).json()['id']
    other = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Other Mall', 'budget': '10000000'}).json()['id']
    for name, role in (('se_eng', 'site_engineer'), ('se_acc', 'accounts'), ('se_arch', 'architect')):
        assert write(admin, 'post', '/api/users', {'username': name, 'display_name': f'Fictional {name}', 'role': role, 'password': f'fictional-{role}-site-1'}).status_code == 200
    users = {u['username']: u['id'] for u in admin.get('/api/users').json()}
    assert write(admin, 'put', f'/api/projects/{mine}/members', {'user_ids': [users['se_eng'], users['se_arch']]}).status_code == 200
    return mine, other, login('se_eng', 'fictional-site_engineer-site-1'), login('se_acc', 'fictional-accounts-site-1'), login('se_arch', 'fictional-architect-site-1')


def body(pid, amount='1200', **kw):
    return {'project_id': pid, 'title': 'Fictional site tea and snacks', 'vendor': 'Fictional Canteen', 'amount': amount, 'request_key': 'site-exp-0001-abcd', **kw}


def test_site_engineer_drafts_a_small_expense_that_waits_for_approval(admin, site):
    mine, other, eng, acc, arch = site
    r = write(eng, 'post', '/api/site-expenses', body(mine))
    assert r.status_code == 200 and r.json()['ticket_id'], r.text
    before = len(admin.get('/api/costs').json())
    assert len(admin.get('/api/costs').json()) == before          # nothing saved yet
    assert write(eng, 'post', f'/api/tickets/{r.json()["ticket_id"]}/approve-and-save', {}).status_code == 403   # cannot approve their own
    assert write(admin, 'post', f'/api/tickets/{r.json()["ticket_id"]}/approve-and-save', {}).status_code == 200
    assert len(admin.get('/api/costs').json()) == before + 1


def test_the_same_form_sent_twice_gives_one_ticket(admin, site):
    mine, other, eng, acc, arch = site
    a = write(eng, 'post', '/api/site-expenses', body(mine)); b = write(eng, 'post', '/api/site-expenses', body(mine))
    assert a.json()['ticket_id'] == b.json()['ticket_id']


def test_above_the_small_expense_limit_is_refused_with_a_plain_message(admin, site):
    mine, other, eng, acc, arch = site
    r = write(eng, 'post', '/api/site-expenses', body(mine, amount='5001'))
    assert r.status_code == 400 and '5,000' in r.text


def test_only_their_own_projects(admin, site):
    mine, other, eng, acc, arch = site
    assert write(eng, 'post', '/api/site-expenses', body(other, request_key='site-exp-0002-abcd')).status_code in (403, 404)


def test_other_roles_use_their_normal_routes_not_this_one(admin, site):
    mine, other, eng, acc, arch = site
    assert write(acc, 'post', '/api/site-expenses', body(mine, request_key='site-exp-0003-abcd')).status_code == 403
    assert write(arch, 'post', '/api/site-expenses', body(mine, request_key='site-exp-0004-abcd')).status_code == 403


def test_engineer_still_cannot_see_money(admin, site):
    mine, other, eng, acc, arch = site
    assert eng.get('/api/costs').status_code == 403
    assert write(eng, 'post', '/api/costs', {'project_id': mine, 'kind': 'expense', 'title': 'Fictional x', 'amount': '100'}).status_code == 403


def test_strict_amounts_apply_here_too(admin, site):
    mine, other, eng, acc, arch = site
    assert write(eng, 'post', '/api/site-expenses', body(mine, amount='1,2,0', request_key='site-exp-0005-abcd')).status_code == 400


def test_site_screen_has_the_button_and_form_and_posts_to_the_new_route():
    import pathlib
    js = pathlib.Path('studioos/static/app.js').read_text()
    assert 'data-action="siteexpense"' in js
    assert "'siteexpense'" in js and "siteexpense:'/api/site-expenses'" in js
    assert "['project' ,'task','cost','payment','site','siteexpense','user','index-nas'].includes(a)" in js

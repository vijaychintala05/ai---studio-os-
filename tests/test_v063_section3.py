"""v0.6.3 tests: per-project access, persistent login throttling, two-factor login,
account management screens' API, and security headers. Fictional data only."""
import os
import re
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, create_engine, inspect, text
from .conftest import write
from studioos.main import app
from studioos import totp
from studioos.db import (SessionLocal, User, Project, Task, SiteReport, Document, LoginAttempt,
                         LoginSession, ChatSession, ChatMessage, ProjectMember)

ADMIN_PW = os.environ['STUDIOOS_ADMIN_PASSWORD']
STATIC = Path(__file__).resolve().parent.parent / 'studioos' / 'static'
FIXED_STEP = 1_000_000


def login(c, username, password, otp=''):
    return c.post('/api/auth/login', json={'username': username, 'password': password, 'otp': otp})


def add_user(admin, username, role, password):
    r = write(admin, 'post', '/api/users', {'username': username, 'display_name': username.title(),
                                           'role': role, 'password': password})
    assert r.status_code == 200, r.text
    return r.json()['id']


def project(admin, name):
    r = write(admin, 'post', '/api/projects', {'name': name, 'budget': '100000'})
    assert r.status_code == 200, r.text
    return r.json()['id']


def staff_client(admin, username='arch01', role='architect', password='fictional-architect-pass'):
    uid = add_user(admin, username, role, password)
    c = TestClient(app)
    assert login(c, username, password).status_code == 200
    return uid, c


@pytest.fixture
def fixed_clock(monkeypatch):
    """Freeze the authenticator clock so codes are deterministic."""
    monkeypatch.setattr(totp, 'current_step', lambda at=None: FIXED_STEP)
    return FIXED_STEP


# ---------------------------------------------------------------- per-project access

def test_staff_see_only_assigned_projects(admin):
    a = project(admin, 'Access Villa A'); b = project(admin, 'Access Villa B')
    uid, arch = staff_client(admin)
    assert arch.get('/api/projects').json() == []
    r = write(admin, 'put', f'/api/projects/{a}/members', {'user_ids': [uid]})
    assert r.status_code == 200, r.text
    assert [m['username'] for m in r.json()['members']] == ['arch01']
    assert [p['id'] for p in arch.get('/api/projects').json()] == [a]
    assert arch.get('/api/summary').json()['projects'] == 1
    assert {p['id'] for p in admin.get('/api/projects').json()} == {a, b}


def test_tasks_site_reports_and_documents_are_filtered(admin):
    a = project(admin, 'Filter Villa A'); b = project(admin, 'Filter Villa B')
    for pid, title in ((a, 'Task in A'), (b, 'Task in B')):
        assert write(admin, 'post', '/api/tasks', {'project_id': pid, 'title': title}).status_code == 200
        assert write(admin, 'post', '/api/site-reports', {'project_id': pid, 'note': 'Report for ' + title}).status_code == 200
    with SessionLocal() as db:
        db.add_all([Document(project_id=a, name='a.pdf', relative_path='A/a.pdf', doc_type='pdf', size_bytes=1),
                    Document(project_id=b, name='b.pdf', relative_path='B/b.pdf', doc_type='pdf', size_bytes=1),
                    Document(project_id=None, name='loose.pdf', relative_path='loose.pdf', doc_type='pdf', size_bytes=1)])
        db.commit()
    uid, arch = staff_client(admin)
    assert write(admin, 'put', f'/api/projects/{a}/members', {'user_ids': [uid]}).status_code == 200
    assert [t['title'] for t in arch.get('/api/tasks').json()] == ['Task in A']
    assert [s['note'] for s in arch.get('/api/site-reports').json()] == ['Report for Task in A']
    assert [d['name'] for d in arch.get('/api/documents').json()] == ['a.pdf']
    assert len(admin.get('/api/documents').json()) == 3


def test_staff_cannot_write_to_unassigned_project(admin):
    a = project(admin, 'Write Villa A'); b = project(admin, 'Write Villa B')
    assert write(admin, 'post', '/api/tasks', {'project_id': b, 'title': 'Admin task in B'}).status_code == 200
    uid, arch = staff_client(admin)
    assert write(admin, 'put', f'/api/projects/{a}/members', {'user_ids': [uid]}).status_code == 200
    assert write(arch, 'post', '/api/tasks', {'project_id': a, 'title': 'Allowed task'}).status_code == 200
    assert write(arch, 'post', '/api/tasks', {'project_id': b, 'title': 'Blocked task'}).status_code == 404
    with SessionLocal() as db:
        task_b = db.scalar(select(Task).where(Task.title == 'Admin task in B')).id
    assert write(arch, 'patch', f'/api/tasks/{task_b}/complete').status_code == 404
    site_uid, site = staff_client(admin, 'site01', 'site_engineer', 'fictional-site-pass-1')
    assert write(site, 'post', '/api/site-reports', {'project_id': b, 'note': 'Should be blocked'}).status_code == 404


def test_ai_is_only_shown_assigned_projects(admin, monkeypatch):
    import studioos.main as main
    a = project(admin, 'Visible Villa'); project(admin, 'Hidden Villa')
    uid, arch = staff_client(admin)
    assert write(admin, 'put', f'/api/projects/{a}/members', {'user_ids': [uid]}).status_code == 200
    seen = {}
    def fake_extract(msg, projects, provider, **kwargs):
        seen['projects'] = [p['name'] for p in projects]
        return {'intent': 'unknown', 'data': {}}
    monkeypatch.setattr(main, 'extract', fake_extract)
    r = write(arch, 'post', '/api/chat', {'message': 'what is happening today'})
    assert r.status_code == 200, r.text
    assert seen['projects'] == ['Visible Villa']


def test_staff_cannot_point_a_proposal_at_unassigned_project(admin):
    from studioos.tickets import add_proposal
    a = project(admin, 'Proposal Villa A'); project(admin, 'Proposal Villa B')
    uid, arch = staff_client(admin)
    assert write(admin, 'put', f'/api/projects/{a}/members', {'user_ids': [uid]}).status_code == 200
    with SessionLocal() as db:
        session = ChatSession(id='arch-proposal', user_id=uid, pending=None); db.add(session); db.flush()
        msg = ChatMessage(session_id=session.id, user_id=uid, speaker='user', content='Add a task to check tiles')
        db.add(msg); db.flush()
        ticket, item = add_proposal(db, session, 'create_task', {'project': 'Proposal Villa A', 'title': 'Check tiles'}, msg.id)
        item_id = item.id; db.commit()
    blocked = write(arch, 'patch', f'/api/tickets/items/{item_id}',
                    {'after': {'project': 'Proposal Villa B', 'title': 'Check tiles'}})
    assert blocked.status_code == 422 and 'not assigned' in blocked.json()['detail']
    ok = write(arch, 'patch', f'/api/tickets/items/{item_id}', {'after': {'project': 'Proposal Villa A', 'title': 'Check floor tiles'}})
    assert ok.status_code == 200, ok.text


def test_firm_wide_roles_see_everything_and_only_admin_assigns(admin):
    a = project(admin, 'Firm Villa A'); project(admin, 'Firm Villa B')
    for name, role, pw in (('manager01', 'manager', 'fictional-manager-pass'), ('accounts01', 'accounts', 'fictional-accounts-pass')):
        uid, c = staff_client(admin, name, role, pw)
        assert len(c.get('/api/projects').json()) == 2
        assert write(c, 'put', f'/api/projects/{a}/members', {'user_ids': []}).status_code == 403
    assert write(admin, 'put', f'/api/projects/{a}/members', {'user_ids': [99999]}).status_code == 400
    users = {u['username']: u for u in admin.get('/api/users').json()}
    assert users['manager01']['sees_all_projects'] is True and users['admin']['sees_all_projects'] is True


# ---------------------------------------------------------------- login throttling

def test_failed_logins_are_stored_and_block_the_username(client):
    import studioos.main as main
    assert not hasattr(main, '_failed')  # no more in-memory counter
    for _ in range(6):
        assert login(client, 'admin', 'wrong-password-xyz').status_code == 401
    with SessionLocal() as db:
        assert db.scalar(select(LoginAttempt).where(LoginAttempt.key_type == 'user', LoginAttempt.key == 'admin')) is not None
    # Even the right password is refused while the username is locked.
    assert login(client, 'admin', ADMIN_PW).status_code == 429


def test_network_address_limit_covers_many_usernames(client, monkeypatch):
    monkeypatch.setenv('STUDIOOS_LOGIN_MAX_PER_IP', '3')
    for name in ('guess01', 'guess02', 'guess03'):
        assert login(client, name, 'wrong-password-xyz').status_code == 401
    assert login(client, 'admin', ADMIN_PW).status_code == 429


def test_successful_login_clears_username_failures(client):
    for _ in range(3):
        assert login(client, 'admin', 'wrong-password-xyz').status_code == 401
    assert login(client, 'admin', ADMIN_PW).status_code == 200
    with SessionLocal() as db:
        assert db.scalars(select(LoginAttempt).where(LoginAttempt.key_type == 'user')).all() == []


def test_forwarded_address_used_only_when_proxy_trusted(client, monkeypatch):
    login(client, 'nobody01', 'wrong-password-xyz')
    client.post('/api/auth/login', json={'username': 'nobody02', 'password': 'x'},
                headers={'X-Forwarded-For': '203.0.113.9'})
    monkeypatch.setenv('STUDIOOS_TRUST_PROXY', 'true')
    client.post('/api/auth/login', json={'username': 'nobody03', 'password': 'x'},
                headers={'X-Forwarded-For': '203.0.113.9, 10.0.0.1'})
    with SessionLocal() as db:
        ips = [a.key for a in db.scalars(select(LoginAttempt).where(LoginAttempt.key_type == 'ip').order_by(LoginAttempt.id)).all()]
    assert ips[0] == ips[1] != '203.0.113.9'  # header ignored without trust
    assert ips[2] == '203.0.113.9'


# ---------------------------------------------------------------- two-factor login

def wrong_code(secret, step):
    """A 6-digit code that is NOT valid for any step the server will accept."""
    valid = {totp.code_at(secret, step + d) for d in (-1, 0, 1, 2)}
    return next(c for c in ('123456', '654321', '000001', '999998', '424242') if c not in valid)


def enable_2fa(c, password, fixed_step):
    assert write(c, 'post', '/api/auth/2fa/setup', {'password': 'wrong-password-xyz'}).status_code == 403
    setup = write(c, 'post', '/api/auth/2fa/setup', {'password': password})
    assert setup.status_code == 200, setup.text
    secret = setup.json()['secret']
    assert setup.json()['otpauth_uri'].startswith('otpauth://totp/')
    assert write(c, 'post', '/api/auth/2fa/enable', {'code': wrong_code(secret, fixed_step)}).status_code == 400
    r = write(c, 'post', '/api/auth/2fa/enable', {'code': totp.code_at(secret, fixed_step)})
    assert r.status_code == 200, r.text
    assert len(r.json()['recovery_codes']) == 10
    return secret, r.json()['recovery_codes']


def test_two_factor_login_flow(admin, fixed_clock):
    secret, codes = enable_2fa(admin, ADMIN_PW, fixed_clock)
    assert admin.get('/api/auth/2fa').json()['enabled'] is True
    phone = TestClient(app)
    need = login(phone, 'admin', ADMIN_PW)
    assert need.status_code == 401 and need.json()['otp_required'] is True
    # The code already used to switch it on cannot be replayed.
    assert login(phone, 'admin', ADMIN_PW, totp.code_at(secret, fixed_clock)).status_code == 401
    ok = login(phone, 'admin', ADMIN_PW, totp.code_at(secret, fixed_clock + 1))
    assert ok.status_code == 200, ok.text
    assert ok.json()['user']['two_factor'] is True


def test_recovery_code_works_once(admin, fixed_clock):
    secret, codes = enable_2fa(admin, ADMIN_PW, fixed_clock)
    c = TestClient(app)
    assert login(c, 'admin', ADMIN_PW, codes[0].upper()).status_code == 200
    assert login(TestClient(app), 'admin', ADMIN_PW, codes[0]).status_code == 401
    assert c.get('/api/auth/2fa').json()['recovery_codes_left'] == 9


def test_wrong_code_counts_as_a_failed_sign_in(admin, fixed_clock):
    secret, _ = enable_2fa(admin, ADMIN_PW, fixed_clock)
    r = login(TestClient(app), 'admin', ADMIN_PW, wrong_code(secret, fixed_clock))
    assert r.status_code == 401 and r.json()['otp_required'] is True
    with SessionLocal() as db:
        assert db.scalar(select(LoginAttempt).where(LoginAttempt.key_type == 'user', LoginAttempt.key == 'admin')) is not None


def test_required_admin_two_factor_locks_everything_until_set_up(admin, monkeypatch, fixed_clock):
    monkeypatch.setenv('STUDIOOS_REQUIRE_ADMIN_2FA', 'true')
    c = TestClient(app)
    r = login(c, 'admin', ADMIN_PW)
    assert r.status_code == 200 and r.json()['two_factor_setup_required'] is True
    assert c.get('/api/projects').status_code == 403
    assert c.get('/api/auth/me').status_code == 200
    assert c.get('/api/auth/2fa').json()['required'] is True
    secret, _ = enable_2fa(c, ADMIN_PW, fixed_clock)
    assert c.get('/api/projects').status_code == 200
    blocked = write(c, 'post', '/api/auth/2fa/disable', {'password': ADMIN_PW, 'code': totp.code_at(secret, fixed_clock + 1)})
    assert blocked.status_code == 409


def test_employee_can_turn_off_two_factor_and_admin_can_reset_it(admin, fixed_clock):
    uid, arch = staff_client(admin)
    secret, _ = enable_2fa(arch, 'fictional-architect-pass', fixed_clock)
    assert {u['username']: u for u in admin.get('/api/users').json()}['arch01']['two_factor'] is True
    off = write(arch, 'post', '/api/auth/2fa/disable', {'password': 'fictional-architect-pass', 'code': totp.code_at(secret, fixed_clock + 1)})
    assert off.status_code == 200 and off.json()['enabled'] is False
    secret, _ = enable_2fa(arch, 'fictional-architect-pass', fixed_clock)
    r = write(admin, 'post', f'/api/users/{uid}/reset-2fa', {'reason': 'Lost their phone'})
    assert r.status_code == 200 and r.json()['sessions_ended'] >= 1
    assert arch.get('/api/auth/me').status_code == 401
    assert login(TestClient(app), 'arch01', 'fictional-architect-pass').status_code == 200


def test_server_console_recovery_turns_off_admin_two_factor(admin, fixed_clock):
    from studioos.recover_admin import disable_admin_2fa
    enable_2fa(admin, ADMIN_PW, fixed_clock)
    assert disable_admin_2fa() == 'admin'
    assert admin.get('/api/auth/me').status_code == 401  # signed out everywhere
    assert login(TestClient(app), 'admin', ADMIN_PW).status_code == 200


def test_totp_matches_rfc_6238_vectors():
    import base64
    secret = base64.b32encode(b'12345678901234567890').decode()
    for at, want in {59: '287082', 1111111109: '081804', 1234567890: '005924', 2000000000: '279037'}.items():
        assert totp.code_at(secret, at // 30) == want


# ---------------------------------------------------------------- security headers

def test_content_security_policy_is_strict(client):
    r = client.get('/')
    csp = r.headers['content-security-policy']
    assert "script-src 'self'" in csp and "style-src 'self'" in csp and 'unsafe-inline' not in csp
    assert "frame-ancestors 'none'" in csp
    assert r.headers['referrer-policy'] == 'no-referrer'
    assert client.get('/health').headers['content-security-policy'] == csp
    assert 'content-security-policy' not in client.get('/docs').headers


def test_front_end_has_no_inline_scripts_or_styles():
    html = (STATIC / 'index.html').read_text()
    js = (STATIC / 'app.js').read_text()
    assert 'style="' not in html and 'style="' not in js
    assert not re.search(r'<script(?![^>]*\bsrc=)[^>]*>', html)
    assert not re.search(r'\son[a-z]+="', html + js)


# ---------------------------------------------------------------- migration

def test_fresh_database_reaches_v10(tmp_path):
    from studioos.migrations import apply_migrations, LATEST_VERSION
    e = create_engine('sqlite:///' + str(tmp_path / 'fresh.db'))
    apply_migrations(e)
    assert LATEST_VERSION >= 10   # v0.9.0 moved the latest to 11; v10 must still be included
    tables = set(inspect(e).get_table_names())
    assert {'project_members', 'login_attempts'} <= tables
    cols = {c['name'] for c in inspect(e).get_columns('users')}
    assert {'totp_enabled', 'totp_secret', 'totp_last_step', 'recovery_code_hashes'} <= cols
    with e.connect() as conn:
        assert conn.execute(text('SELECT MAX(version) FROM schema_migrations')).scalar() == LATEST_VERSION

"""Client portal step 1: per-project address, one-time-code sign-in, client sessions. Fictional data only."""
import os

import pytest
from sqlalchemy import select, text, inspect

from studioos import portal_sender
from studioos.client_portal_models import ClientLoginCode, ClientSession
from studioos.db import SessionLocal, Project, Audit, engine
from tests.conftest import write

DOMAIN = 'portal.example.test'


@pytest.fixture(autouse=True)
def portal_env(monkeypatch):
    monkeypatch.setenv('STUDIOOS_PORTAL_DOMAIN', DOMAIN)
    monkeypatch.setenv('STUDIOOS_PORTAL_SENDER', 'memory')
    portal_sender.OUTBOX.clear()


def _project(name):
    with SessionLocal() as db:
        p = Project(name=name, client='Fictional Client')
        db.add(p); db.commit()
        return p.id


def _setup(admin, name='Villa One', slug='villa-one', phone='9876543210', email='asha@example.test'):
    pid = _project(name)
    assert write(admin, 'put', f'/api/portal/{pid}', {'slug': slug, 'enabled': True}).status_code == 200
    r = write(admin, 'post', f'/api/portal/{pid}/contacts', {'name': 'Asha Fictional', 'phone': phone, 'email': email})
    assert r.status_code == 200, r.text
    return pid, r.json()['id']


def _host(slug):
    return {'host': f'{slug}.{DOMAIN}'}


def _sign_in(client, slug, ident='9876543210'):
    h = _host(slug)
    assert client.post('/portal-api/login/request', json={'identifier': ident}, headers=h).status_code == 200
    code = portal_sender.OUTBOX[-1]['code']
    r = client.post('/portal-api/login/verify', json={'identifier': ident, 'code': code}, headers=h)
    return r


@pytest.fixture
def portal_client(admin):
    """A second, cookie-free client so staff cookies never leak into portal calls."""
    from fastapi.testclient import TestClient
    from studioos.main import app
    with TestClient(app) as c:
        yield c


def test_client_signs_in_and_sees_only_name_and_project(admin, portal_client):
    _setup(admin)
    assert _sign_in(portal_client, 'villa-one').status_code == 200
    me = portal_client.get('/portal-api/me', headers=_host('villa-one'))
    assert me.json() == {'name': 'Asha Fictional', 'project': 'Villa One'}


def test_same_answer_for_unknown_person(admin, portal_client):
    _setup(admin)
    h = _host('villa-one')
    a = portal_client.post('/portal-api/login/request', json={'identifier': '9876543210'}, headers=h)
    b = portal_client.post('/portal-api/login/request', json={'identifier': '9000000000'}, headers=h)
    assert a.status_code == b.status_code == 200 and a.json() == b.json()
    assert len(portal_sender.OUTBOX) == 1   # only the real person got a code


def test_wrong_and_expired_and_reused_codes_fail(admin, portal_client):
    _setup(admin)
    h = _host('villa-one')
    portal_client.post('/portal-api/login/request', json={'identifier': '9876543210'}, headers=h)
    code = portal_sender.OUTBOX[-1]['code']
    wrong = f'{(int(code) + 1) % 10**6:06d}'
    assert portal_client.post('/portal-api/login/verify', json={'identifier': '9876543210', 'code': wrong}, headers=h).status_code == 401
    assert portal_client.post('/portal-api/login/verify', json={'identifier': '9876543210', 'code': code}, headers=h).status_code == 200
    portal_client.cookies.clear()
    # a used code cannot be used again
    assert portal_client.post('/portal-api/login/verify', json={'identifier': '9876543210', 'code': code}, headers=h).status_code == 401
    # an expired code fails
    portal_client.post('/portal-api/login/request', json={'identifier': '9876543210'}, headers=h)
    code2 = portal_sender.OUTBOX[-1]['code']
    with SessionLocal() as db:
        db.execute(text("UPDATE client_login_codes SET expires_at='2000-01-01 00:00:00' WHERE used_at IS NULL")); db.commit()
    assert portal_client.post('/portal-api/login/verify', json={'identifier': '9876543210', 'code': code2}, headers=h).status_code == 401


def test_code_is_burnt_after_five_wrong_tries(admin, portal_client):
    _setup(admin)
    h = _host('villa-one')
    portal_client.post('/portal-api/login/request', json={'identifier': '9876543210'}, headers=h)
    code = portal_sender.OUTBOX[-1]['code']
    wrong = f'{(int(code) + 1) % 10**6:06d}'
    for _ in range(5):
        assert portal_client.post('/portal-api/login/verify', json={'identifier': '9876543210', 'code': wrong}, headers=h).status_code == 401
    assert portal_client.post('/portal-api/login/verify', json={'identifier': '9876543210', 'code': code}, headers=h).status_code == 401


def test_code_is_not_stored_in_clear(admin, portal_client):
    _setup(admin)
    portal_client.post('/portal-api/login/request', json={'identifier': '9876543210'}, headers=_host('villa-one'))
    code = portal_sender.OUTBOX[-1]['code']
    with SessionLocal() as db:
        row = db.scalar(select(ClientLoginCode))
        assert code not in row.code_hash and len(row.code_hash) == 64


def test_client_of_one_project_cannot_use_another_projects_address(admin, portal_client):
    _setup(admin)
    _setup(admin, name='Villa Two', slug='villa-two', phone='9123456780', email='ravi@example.test')
    assert _sign_in(portal_client, 'villa-one').status_code == 200
    # the cookie is valid for villa-one only: replaying it on villa-two's address is refused
    r = portal_client.get('/portal-api/me', headers=_host('villa-two'))
    assert r.status_code == 401


def test_phone_of_project_one_gets_no_code_on_project_two(admin, portal_client):
    _setup(admin)
    _setup(admin, name='Villa Two', slug='villa-two', phone='9123456780', email='ravi@example.test')
    portal_client.post('/portal-api/login/request', json={'identifier': '9876543210'}, headers=_host('villa-two'))
    assert portal_sender.OUTBOX == []


def test_staff_pages_and_staff_api_are_not_reachable_on_a_portal_address(admin, portal_client):
    _setup(admin)
    h = _host('villa-one')
    for path in ('/api/auth/me', '/api/projects', '/docs', '/openapi.json', '/mcp', '/static/app.js', '/health', '/sw.js'):   # '/' is the portal page itself (step 5)
        assert portal_client.get(path, headers=h).status_code == 404, path


def test_portal_api_is_not_reachable_on_the_staff_address(admin, portal_client):
    _setup(admin)
    assert portal_client.post('/portal-api/login/request', json={'identifier': '9876543210'}).status_code == 404
    assert portal_client.get('/portal-api/me').status_code == 404


def test_unknown_disabled_or_junk_addresses_are_404(admin, portal_client):
    pid, _ = _setup(admin)
    for slug in ('nobody', 'a', 'bad_slug', 'VILLA-ONE.extra'):
        h = {'host': f'{slug}.{DOMAIN}'}
        assert portal_client.post('/portal-api/login/request', json={'identifier': '9876543210'}, headers=h).status_code == 404, slug
    assert portal_client.post('/portal-api/login/request', json={'identifier': '9876543210'}, headers={'host': DOMAIN}).status_code == 404
    assert write(admin, 'put', f'/api/portal/{pid}', {'slug': 'villa-one', 'enabled': False}).status_code == 200
    assert portal_client.post('/portal-api/login/request', json={'identifier': '9876543210'}, headers=_host('villa-one')).status_code == 404


def test_portal_does_nothing_when_no_domain_is_set(admin, portal_client, monkeypatch):
    _setup(admin)
    monkeypatch.delenv('STUDIOOS_PORTAL_DOMAIN')
    assert portal_client.post('/portal-api/login/request', json={'identifier': '9876543210'}, headers=_host('villa-one')).status_code == 404


def test_staff_login_cookie_does_not_open_the_portal(admin, portal_client):
    _setup(admin)
    # the admin's staff cookies, sent to a portal address, give nothing
    r = admin.get('/portal-api/me', headers=_host('villa-one'))
    assert r.status_code == 401


def test_switching_a_contact_off_signs_them_out(admin, portal_client):
    pid, cid = _setup(admin)
    assert _sign_in(portal_client, 'villa-one').status_code == 200
    assert write(admin, 'patch', f'/api/portal/{pid}/contacts/{cid}', {'active': False}).status_code == 200
    assert portal_client.get('/portal-api/me', headers=_host('villa-one')).status_code == 401
    portal_client.cookies.clear()
    portal_client.post('/portal-api/login/request', json={'identifier': '9876543210'}, headers=_host('villa-one'))
    assert len(portal_sender.OUTBOX) == 1   # only the first sign-in; no new code for an off contact


def test_logout_and_csrf(admin, portal_client):
    _setup(admin)
    _sign_in(portal_client, 'villa-one')
    h = _host('villa-one')
    assert portal_client.post('/portal-api/logout', headers=h).status_code == 403   # no CSRF token
    csrf = portal_client.cookies.get('studioos_portal_csrf')
    assert portal_client.post('/portal-api/logout', headers={**h, 'X-CSRF-Token': csrf}).status_code == 200
    assert portal_client.get('/portal-api/me', headers=h).status_code == 401


def test_cookie_is_host_only_httponly_strict(admin, portal_client):
    _setup(admin)
    r = _sign_in(portal_client, 'villa-one')
    session_cookie = [c for c in r.headers.get_list('set-cookie') if c.startswith('studioos_portal=')][0].lower()
    assert 'httponly' in session_cookie and 'samesite=strict' in session_cookie and 'domain=' not in session_cookie


def test_per_person_code_request_limit(admin, portal_client, monkeypatch):
    monkeypatch.setenv('STUDIOOS_PORTAL_MAX_CODES_PER_PERSON', '2')
    _setup(admin)
    for _ in range(4):
        portal_client.post('/portal-api/login/request', json={'identifier': '9876543210'}, headers=_host('villa-one'))
    assert len(portal_sender.OUTBOX) == 2


def test_only_admin_manages_the_portal(admin, portal_client):
    pid = _project('Villa Three')
    # unauthenticated
    assert portal_client.get(f'/api/portal/{pid}').status_code == 401


def test_staff_input_is_checked(admin):
    pid = _project('Villa Four')
    for slug in ('www', 'a', 'Bad Slug', '-x-', 'admin'):
        assert write(admin, 'put', f'/api/portal/{pid}', {'slug': slug, 'enabled': True}).status_code in (422,), slug
    assert write(admin, 'put', f'/api/portal/{pid}', {'slug': 'villa-four', 'enabled': True}).status_code == 200
    other = _project('Villa Five')
    assert write(admin, 'put', f'/api/portal/{other}', {'slug': 'villa-four', 'enabled': True}).status_code == 409
    assert write(admin, 'post', f'/api/portal/{pid}/contacts', {'name': 'No Way'}).status_code == 422
    assert write(admin, 'post', f'/api/portal/{pid}/contacts', {'name': 'Bad Phone', 'phone': '123'}).status_code == 422


def test_no_code_is_sent_when_no_provider_is_set(admin, portal_client, monkeypatch):
    monkeypatch.setenv('STUDIOOS_PORTAL_SENDER', 'off')
    _setup(admin)
    r = portal_client.post('/portal-api/login/request', json={'identifier': '9876543210'}, headers=_host('villa-one'))
    assert r.status_code == 200 and portal_sender.OUTBOX == []
    with SessionLocal() as db:
        assert db.scalar(select(Audit).where(Audit.action == 'portal_code_not_sent')) is not None


def test_new_tables_are_additive_and_versioned(client):
    names = set(inspect(engine).get_table_names())
    assert {'project_portals', 'client_contacts', 'client_login_codes', 'client_sessions'} <= names
    with engine.connect() as c:
        assert c.execute(text('SELECT COUNT(*) FROM schema_migrations WHERE version=40')).scalar() == 1

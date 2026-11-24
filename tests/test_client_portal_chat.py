"""Client portal step 4: the client chat. Separate from the internal chat; permanent; fingerprinted. Fictional data only."""
import pytest
from sqlalchemy import select

from studioos.client_portal_models import ClientChatMessage
from studioos.db import SessionLocal
from tests.conftest import write
from tests.test_client_portal_foundation import portal_env, portal_client, _setup, _host, _sign_in  # noqa: F401
from tests.test_v0100_one_graph import add_user, client_for


def _say(client, slug, body):
    h = {**_host(slug), 'X-CSRF-Token': client.cookies.get('studioos_portal_csrf', '')}
    return client.post('/portal-api/chat', json={'body': body}, headers=h)


def _read(client, slug, after=0):
    r = client.get(f'/portal-api/chat?after={after}', headers=_host(slug))
    assert r.status_code == 200, r.text
    return r.json()['messages']


def test_client_and_studio_talk_in_one_thread(admin, portal_client):
    pid, _ = _setup(admin)
    _sign_in(portal_client, 'villa-one')
    assert _say(portal_client, 'villa-one', 'Can we move the sink?').status_code == 200
    assert write(admin, 'post', f'/api/portal/{pid}/chat', {'body': 'Yes, we will send a revised layout.'}).status_code == 200
    msgs = _read(portal_client, 'villa-one')
    assert [(m['from'], m['body']) for m in msgs] == [('client', 'Can we move the sink?'), ('staff', 'Yes, we will send a revised layout.')]
    assert set(msgs[0]) == {'id', 'from', 'author', 'body', 'at'}          # no account or contact ids
    assert _read(portal_client, 'villa-one', after=msgs[0]['id'])[0]['from'] == 'staff'
    staff_view = admin.get(f'/api/portal/{pid}/chat').json()['messages']
    assert [m['body'] for m in staff_view] == [m['body'] for m in msgs]


def test_internal_project_chat_never_reaches_the_client(admin, portal_client):
    pid, _ = _setup(admin)
    assert write(admin, 'post', f'/api/projects/{pid}/chat', {'body': 'INTERNAL: client is difficult about the budget'}).status_code == 200
    _sign_in(portal_client, 'villa-one')
    assert _read(portal_client, 'villa-one') == []
    # and a client message does not appear in the internal chat
    _say(portal_client, 'villa-one', 'Hello team')
    internal = admin.get(f'/api/projects/{pid}/chat').json()['messages']
    assert all('Hello team' not in m['body'] for m in internal)


def test_a_client_only_sees_their_own_projects_thread(admin, portal_client):
    p1, _ = _setup(admin)
    p2, _ = _setup(admin, name='Villa Two', slug='villa-two', phone='9123456780', email='ravi@example.test')
    write(admin, 'post', f'/api/portal/{p2}/chat', {'body': 'For Villa Two only'})
    _sign_in(portal_client, 'villa-one')
    assert _read(portal_client, 'villa-one') == []
    assert portal_client.get('/portal-api/chat', headers=_host('villa-two')).status_code == 401   # the cookie is for villa-one


def test_signed_out_and_wrong_address_get_nothing(admin, portal_client):
    pid, _ = _setup(admin)
    assert portal_client.get('/portal-api/chat', headers=_host('villa-one')).status_code == 401
    assert admin.get('/portal-api/chat', headers=_host('villa-one')).status_code == 401      # a staff session is not a client session
    assert admin.get('/portal-api/chat').status_code == 404                                 # not on the staff address


def test_csrf_and_input_checks(admin, portal_client):
    _setup(admin)
    _sign_in(portal_client, 'villa-one')
    assert portal_client.post('/portal-api/chat', json={'body': 'x'}, headers=_host('villa-one')).status_code == 403
    assert _say(portal_client, 'villa-one', '').status_code == 422
    assert _say(portal_client, 'villa-one', 'a' * 2001).status_code == 422
    assert _say(portal_client, 'villa-one', '   ').status_code == 422
    assert _say(portal_client, 'villa-one', '<script>alert(1)</script>').status_code == 200
    assert _read(portal_client, 'villa-one')[0]['body'] == '<script>alert(1)</script>'      # stored as plain text; the screen must show it as text


def test_client_hourly_limit(admin, portal_client, monkeypatch):
    monkeypatch.setattr('studioos.client_portal_chat.CLIENT_PER_HOUR', 2)
    _setup(admin)
    _sign_in(portal_client, 'villa-one')
    assert [_say(portal_client, 'villa-one', f'm{i}').status_code for i in range(3)] == [200, 200, 429]


def test_messages_are_permanent(admin, portal_client):
    _setup(admin)
    _sign_in(portal_client, 'villa-one')
    _say(portal_client, 'villa-one', 'Original words')
    with SessionLocal() as db:
        m = db.scalar(select(ClientChatMessage)); m.body = 'Changed words'
        with pytest.raises(PermissionError):
            db.flush()
        db.rollback()
    with SessionLocal() as db:
        db.delete(db.scalar(select(ClientChatMessage)))
        with pytest.raises(PermissionError):
            db.flush()
        db.rollback()


def test_fingerprints_chain_and_tampering_is_found(admin, portal_client):
    pid, _ = _setup(admin)
    _sign_in(portal_client, 'villa-one')
    for t in ('one', 'two', 'three'):
        _say(portal_client, 'villa-one', t)
    write(admin, 'post', f'/api/portal/{pid}/chat', {'body': 'four'})
    assert admin.get(f'/api/portal/{pid}/chat/verify').json() == {'checked': 4, 'ok': True, 'first_broken_id': None}
    from sqlalchemy import text
    with SessionLocal() as db:   # a raw database edit that bypasses the application
        db.execute(text("UPDATE client_chat_messages SET body='tampered' WHERE body='two'")); db.commit()
    r = admin.get(f'/api/portal/{pid}/chat/verify').json()
    assert r['ok'] is False and r['first_broken_id'] is not None


def test_staff_rules(admin, portal_client):
    pid, _ = _setup(admin)
    add_user(admin, 'eng.one', 'site_engineer')
    add_user(admin, 'arch.one', 'architect')
    eng, arch = client_for('eng.one'), client_for('arch.one')
    assert write(eng, 'post', f'/api/portal/{pid}/chat', {'body': 'hi'}).status_code == 403            # a site engineer does not speak to clients
    assert write(arch, 'post', f'/api/portal/{pid}/chat', {'body': 'hi'}).status_code == 404           # an architect not on this project
    assert arch.get(f'/api/portal/{pid}/chat').status_code == 404
    assert portal_client.get(f'/api/portal/{pid}/chat').status_code == 401
    assert arch.get(f'/api/portal/{pid}/chat/verify').status_code == 403                    # verifying is admin/manager only
    assert write(admin, 'post', '/api/portal/999999/chat', {'body': 'hi'}).status_code == 404

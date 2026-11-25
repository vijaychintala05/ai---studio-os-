"""The public portal listener forwards portal addresses only; everything else is answered here and never reaches StudioOS."""
import pytest
from fastapi.testclient import TestClient

from studioos import portal_sender
from studioos.portal_listener import app as listener
from tests.test_client_portal_foundation import portal_env, _setup, _host, DOMAIN  # noqa: F401


@pytest.fixture
def pub(admin):
    with TestClient(listener) as c:
        yield c


def test_portal_page_and_api_are_forwarded_on_a_portal_address(admin, pub):
    _setup(admin)
    h = _host('villa-one')
    assert pub.get('/', headers=h).status_code == 200
    r = pub.post('/portal-api/login/request', json={'identifier': '9876543210'}, headers=h)
    assert r.status_code == 200 and portal_sender.OUTBOX and portal_sender.OUTBOX[-1]['via'] == 'phone'


@pytest.mark.parametrize('path', ['/api/auth/login', '/api/auth/me', '/api/projects', '/docs', '/openapi.json', '/mcp', '/health', '/sw.js',
                                  '/static/app.js', '/api/intake/whatsapp', '/api/portal/1', '/api/portal/1/chat', '/index.html'])
def test_nothing_but_the_portal_is_reachable_on_the_public_listener(admin, pub, path):
    _setup(admin)
    for host in (f'villa-one.{DOMAIN}', DOMAIN, 'studio.example.test', ''):
        for method in ('get', 'post'):
            r = getattr(pub, method)(path, headers={'host': host} if host else {})
            assert r.status_code == 404 and r.text == 'Not found', (method, path, host)


def test_portal_paths_on_a_wrong_address_are_refused_by_the_listener(admin, pub):
    _setup(admin)
    for host in ('studio.example.test', 'villa-one.other.test', f'{DOMAIN}.evil.test'):
        assert pub.get('/portal-api/ui/', headers={'host': host}).text == 'Not found'
        assert pub.get('/', headers={'host': host}).text == 'Not found'


def test_websockets_are_closed(admin, pub):
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with pub.websocket_connect('/portal-api/chat', headers=_host('villa-one')):
            pass


def test_production_needs_a_long_pepper(admin, monkeypatch):
    _setup(admin)
    monkeypatch.setenv('STUDIOOS_ENV', 'production')
    monkeypatch.delenv('STUDIOOS_PORTAL_PEPPER', raising=False)
    from fastapi.testclient import TestClient as TC
    from studioos.main import app
    c = TC(app)       # no 'with': the app's own start-up checks for live data are not what is tested here
    if True:
        h = _host('villa-one')
        assert c.post('/portal-api/login/request', json={'identifier': '9876543210'}, headers=h).status_code == 503
        monkeypatch.setenv('STUDIOOS_PORTAL_PEPPER', 'short')
        assert c.post('/portal-api/login/request', json={'identifier': '9876543210'}, headers=h).status_code == 503
        monkeypatch.setenv('STUDIOOS_PORTAL_PEPPER', 'p' * 40)
        assert c.post('/portal-api/login/request', json={'identifier': '9876543210'}, headers=h).status_code == 200

"""Client portal step 5: the pages are served only on a portal address, with the strict policy, and contain no inline code."""
import re
from pathlib import Path

from tests.test_client_portal_foundation import portal_env, portal_client, _setup, _host  # noqa: F401

STATIC = Path(__file__).resolve().parents[1] / 'studioos' / 'static'


def test_portal_address_serves_the_page_and_its_two_files(admin, portal_client):
    _setup(admin)
    h = _host('villa-one')
    page = portal_client.get('/', headers=h)
    assert page.status_code == 200 and 'text/html' in page.headers['content-type'] and 'Client portal' in page.text
    assert 'Villa One' not in page.text                       # nothing about the project before sign-in
    assert "script-src 'self'" in page.headers['content-security-policy'] and 'unsafe-inline' not in page.headers['content-security-policy']
    assert page.headers['x-frame-options'] == 'DENY' and page.headers['cache-control'] == 'no-store'
    assert portal_client.get('/portal-api/ui/portal.js', headers=h).status_code == 200
    assert 'text/css' in portal_client.get('/portal-api/ui/portal.css', headers=h).headers['content-type']


def test_page_has_no_inline_script_style_or_event_handlers():
    html = (STATIC / 'portal.html').read_text()
    assert not re.search(r'<script(?![^>]*\bsrc=)', html)           # every script has a src
    assert not re.search(r'\sstyle\s*=', html) and '<style' not in html
    assert not re.search(r'\son[a-z]+\s*=', html)                   # no onclick= and friends


def test_script_never_builds_html_from_server_text():
    js = (STATIC / 'portal.js').read_text()
    for banned in ('innerHTML', 'outerHTML', 'insertAdjacentHTML', 'document.write', 'eval(', 'new Function'):
        assert banned not in js, banned


def test_unknown_or_off_addresses_and_odd_names_serve_nothing(admin, portal_client):
    _setup(admin)
    assert portal_client.get('/', headers=_host('nobody')).status_code == 404
    h = _host('villa-one')
    for name in ('portal.html', '../db.py', '..%2fdb.py', 'index.html', 'chat.js', '%2e%2e/main.py'):
        assert portal_client.get(f'/portal-api/ui/{name}', headers=h).status_code == 404, name
    assert portal_client.get('/static/app.js', headers=h).status_code == 404          # the staff app's files are not on a portal address
    assert portal_client.get('/index.html', headers=h).status_code == 404


def test_staff_address_is_unchanged(admin, portal_client):
    _setup(admin)
    assert portal_client.get('/portal-api/ui/').status_code == 404        # the portal page is not served on the staff address
    r = portal_client.get('/')
    assert r.status_code == 200 and 'Client portal' not in r.text           # '/' is still the staff app

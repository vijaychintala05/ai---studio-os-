"""Tests for easy AI API connection and live connection testing in Settings.

Uses fictional keys and mocked HTTP responses only — never real credentials or live external calls.
"""
from __future__ import annotations

import io
import json
from urllib import error

import pytest

from studioos import providers, secret_box
from tests.conftest import write


class _FakeResponse:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode('utf-8')

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_demo_connection_test_works_offline(admin):
    r = write(admin, 'post', '/api/settings/provider/test', {'provider': 'demo'})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['ok'] is True
    assert body['provider'] == 'demo'
    assert 'working properly' in body['message'].lower()


def test_connect_save_mask_test_and_disconnect_openai(admin, monkeypatch, tmp_path):
    # Enable secret_box encryption to verify saved API keys are encrypted at rest
    key_file = tmp_path / 'fict_2fa.key'
    secret_box.create_key_file(str(key_file))
    monkeypatch.setenv('STUDIOOS_2FA_KEY_FILE', str(key_file))
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)

    fictional_key = 'sk-fictional-test-key-9876'
    saved = write(admin, 'post', '/api/settings/provider/config', {
        'provider': 'openai',
        'api_key': fictional_key,
        'model': 'gpt-4o-mini',
        'activate': True,
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()['activated'] is True

    # GET /api/settings must NEVER return the raw key — only masked last 4 chars
    st = admin.get('/api/settings').json()
    assert st['provider'] == 'openai'
    openai_row = next(p for p in st['providers'] if p['id'] == 'openai')
    assert openai_row['configured'] is True
    assert openai_row['source'] == 'saved'
    assert openai_row['model'] == 'gpt-4o-mini'
    assert openai_row['key_hint'] == '••••9876'
    assert fictional_key not in json.dumps(st)

    # Live connection test (mocked 200 OK)
    monkeypatch.setattr(
        providers.request,
        'urlopen',
        lambda req, timeout=12: _FakeResponse({'choices': [{'message': {'content': 'OK'}}]}),
    )
    ok = write(admin, 'post', '/api/settings/provider/test', {'provider': 'openai'})
    assert ok.status_code == 200, ok.text
    assert ok.json()['ok'] is True
    assert 'Connected to OpenAI (gpt-4o-mini)' in ok.json()['message']

    # Live connection test (mocked 401 bad key — plain-English message, key never leaked)
    def _raise_401(req, timeout=12):
        raise error.HTTPError(req.full_url, 401, 'Unauthorized', {}, io.BytesIO(b'bad key'))

    monkeypatch.setattr(providers.request, 'urlopen', _raise_401)
    bad = write(admin, 'post', '/api/settings/provider/test', {'provider': 'openai'})
    assert bad.status_code == 200
    assert bad.json()['ok'] is False
    assert 'rejected the API key (401)' in bad.json()['message']
    assert fictional_key not in bad.text

    # Disconnect removes saved key and safely falls back to demo
    disc = admin.delete(
        '/api/settings/provider/config/openai',
        headers={'X-CSRF-Token': admin.cookies.get('studioos_csrf', '')},
    )
    assert disc.status_code == 200, disc.text
    st2 = admin.get('/api/settings').json()
    assert st2['provider'] == 'demo'
    openai_row2 = next(p for p in st2['providers'] if p['id'] == 'openai')
    assert openai_row2['configured'] is False
    assert openai_row2['key_hint'] == ''


def test_non_admin_cannot_configure_or_test_providers(admin):
    from fastapi.testclient import TestClient
    from studioos.main import app
    write(admin, 'post', '/api/users', {
        'username': 'fict_mgr_ai', 'display_name': 'Fictional Manager', 'role': 'manager', 'password': 'FictionalPassword123!',
    })
    mgr = TestClient(app)
    assert mgr.post('/api/auth/login', json={'username': 'fict_mgr_ai', 'password': 'FictionalPassword123!'}).status_code == 200
    assert write(mgr, 'post', '/api/settings/provider/config', {
        'provider': 'gemini', 'api_key': 'AIza-fictional-0000', 'model': 'gemini-2.0-flash',
    }).status_code == 403
    assert write(mgr, 'post', '/api/settings/provider/test', {'provider': 'demo'}).status_code == 403
    assert mgr.delete(
        '/api/settings/provider/config/gemini',
        headers={'X-CSRF-Token': mgr.cookies.get('studioos_csrf', '')},
    ).status_code == 403

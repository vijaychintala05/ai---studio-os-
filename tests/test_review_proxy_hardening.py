import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from uvicorn import Config as ServerConfig

from studioos import safekeeping
from studioos.db import LoginAttempt, SessionLocal
from studioos.main import app
from .test_v070_safekeeping import cfg_for
from .test_v093_mcp_app import key, on, rpc


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(('trusted', 'peer', 'expected'), [
    ('127.0.0.1', '127.0.0.1', '203.0.113.23'),
    ('192.0.2.1', '127.0.0.1', '127.0.0.1'),
    (None, '127.0.0.1', '127.0.0.1'),
    ('127.0.0.1', '198.51.100.8', '198.51.100.8'),
])
def test_docker_sign_in_uses_only_studioos_proxy_list(client, monkeypatch, trusted, peer, expected):
    if trusted is None:
        monkeypatch.delenv('STUDIOOS_TRUSTED_PROXIES', raising=False)
    else:
        monkeypatch.setenv('STUDIOOS_TRUSTED_PROXIES', trusted)
    command = json.loads(next(line[4:] for line in (ROOT / 'Dockerfile').read_text().splitlines() if line.startswith('CMD ')))
    server = ServerConfig(app, proxy_headers='--no-proxy-headers' not in command,
                          forwarded_allow_ips='127.0.0.1', lifespan='off')
    server.load()
    with TestClient(server.loaded_app, client=(peer, 51000)) as service:
        result = service.post('/api/auth/login', headers={'X-Forwarded-For': '203.0.113.23'},
                              json={'username': 'fictional-sign-in', 'password': 'fictional-incorrect-password'})
    assert result.status_code == 401
    with SessionLocal() as db:
        assert db.scalar(select(LoginAttempt.key).where(LoginAttempt.key_type == 'ip')) == expected


@pytest.mark.parametrize('host', ['connector.example', 'unrelated.example', 'connector.example:8443'])
def test_connector_listener_ignores_host_for_route_selection(admin, monkeypatch, host):
    on(monkeypatch)
    monkeypatch.setenv('STUDIOOS_PUBLIC_HOST', 'connector.example:8443')
    token = key(admin).json()['token']
    if importlib.util.find_spec('studioos.connector_listener') is None:
        listener = app  # The old Docker setup used the main app as its connector listener.
    else:
        from studioos.connector_listener import app as listener

    with TestClient(listener, base_url='http://127.0.0.1:8001', headers={'Host': host}) as public:
        for path in ('/', '/health', '/api/auth/login', '/api/intake/whatsapp', '/static/app.js'):
            result = public.get(path)
            assert result.status_code == 404, (host, path, result.status_code)
        result = rpc(public, token, 'ping')
        assert result.status_code == 200 and 'result' in result.json()


def test_every_compose_service_has_bounded_logs():
    compose = (ROOT / 'compose.yaml').read_text()
    service_block = compose.split('\nservices:\n', 1)[1].split('\nvolumes:\n', 1)[0]
    services = list(re.finditer(r'^  ([\w-]+):\s*$', service_block, re.MULTILINE))
    assert services and {'db', 'app', 'migrate', 'backup'} <= {match[1] for match in services}
    missing = []
    for index, match in enumerate(services):
        end = services[index+1].start() if index+1 < len(services) else len(service_block)
        body = service_block[match.end():end]
        if not re.search(r'^    logging: \*bounded_logs$', body, re.MULTILINE):
            missing.append(match[1])
    assert not missing, f'Services without log limits: {missing}'
    logging = compose.split('&bounded_logs', 1)[1].split('\nservices:', 1)[0]
    assert re.search(r'^    max-size: "[1-9]\d*m"$', logging, re.MULTILINE)
    assert re.search(r'^    max-file: "[1-9]\d*"$', logging, re.MULTILINE)


def test_first_backup_failure_is_visible_on_screen_and_status(admin, monkeypatch, tmp_path):
    cfg = cfg_for(tmp_path)
    monkeypatch.setenv('STUDIOOS_BACKUP_STATUS_DIR', str(cfg.status_dir))

    def fail(*args):
        raise safekeeping.SafekeepingError('Fictional backup space is full.')

    monkeypatch.setattr(safekeeping, 'check_free_space', fail)
    safekeeping.service(cfg, once=True)
    payload = admin.get('/api/system/data-safety').json()
    check = next(check for check in payload['checks'] if check['key'] == 'backup')
    assert check['level'] == 'fail' and check['title'] == 'Latest backup failed'
    assert 'Fictional backup space is full.' in check['detail']

    script = tmp_path / 'status.sh'
    script.write_text((ROOT / 'ops/status.sh').read_text())
    (tmp_path / '_common.sh').write_text(
        'set -euo pipefail\nTARGET=test\nsay() { echo "$*"; }\ndc() { :; }\n'
        'safekeeping() { if [[ "$1" == list ]]; then seq 1 20000;'
        ' else "$TEST_PYTHON" -m studioos.safekeeping "$@"; fi; }\n'
    )
    result = subprocess.run(['bash', str(script)], cwd=ROOT,
                            env={**os.environ, 'TEST_PYTHON': sys.executable},
                            check=True, text=True, capture_output=True)
    assert 'WARNING: Latest backup failed' in result.stdout


def test_manual_backup_failure_is_recorded_and_busy_session_is_not(tmp_path, monkeypatch):
    cfg = cfg_for(tmp_path)

    def fail(*args):
        raise safekeeping.SafekeepingError('Fictional backup space is full.')

    monkeypatch.setattr(safekeeping, 'check_free_space', fail)
    with pytest.raises(safekeeping.SafekeepingError, match='Fictional backup'):
        safekeeping.backup(cfg)
    error = safekeeping.read_status(cfg)['last_backup_error']
    assert error['error'] == 'Fictional backup space is full.'
    with safekeeping.exclusive_lock(cfg.primary):
        with pytest.raises(safekeeping.SafekeepingError, match='already running'):
            safekeeping.backup(cfg)
    assert safekeeping.read_status(cfg)['last_backup_error'] == error

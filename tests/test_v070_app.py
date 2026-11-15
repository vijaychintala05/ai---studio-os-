"""v0.7.0 app tests: Data safety endpoint, environment label, live-data startup guard."""
import json
import os
import pytest
from fastapi.testclient import TestClient
from .conftest import write
from studioos.main import app


def test_health_and_settings_report_environment(admin, monkeypatch):
    monkeypatch.setenv('STUDIOOS_ENV', 'test')
    assert admin.get('/health').json()['environment'] == 'test'
    assert admin.get('/api/settings').json()['environment'] == 'test'
    monkeypatch.setenv('STUDIOOS_ENV', 'something-else')
    assert admin.get('/health').json()['environment'] == 'development'


def test_data_safety_reads_backup_status(admin, monkeypatch, tmp_path):
    monkeypatch.setenv('STUDIOOS_BACKUP_STATUS_DIR', str(tmp_path))
    r = admin.get('/api/system/data-safety')
    assert r.status_code == 200 and r.json()['overall'] == 'fail'  # no status yet
    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc)
    (tmp_path / 'status.json').write_text(json.dumps({
        'heartbeat': now.isoformat(), 'config': {'backup_every_hours': 6, 'restore_drill_every_hours': 24, 'offsite_configured': True},
        'last_backup': {'time': now.isoformat(), 'size_bytes': 1000, 'rows_total': 5, 'backups_kept': 1, 'offsite': {'configured': True, 'ok': True}},
        'last_drill': {'time': now.isoformat(), 'ok': True, 'tables_checked': 3, 'rows_checked': 5}}))
    assert admin.get('/api/system/data-safety').json()['overall'] == 'ok'


def test_data_safety_is_admin_only(admin):
    write(admin, 'post', '/api/users', {'username': 'viewer01', 'display_name': 'Viewer', 'role': 'viewer',
                                        'password': 'fictional-viewer-pass'})
    c = TestClient(app)
    assert c.post('/api/auth/login', json={'username': 'viewer01', 'password': 'fictional-viewer-pass'}).status_code == 200
    assert c.get('/api/system/data-safety').status_code == 403


def test_app_refuses_to_start_with_unsafe_live_settings(monkeypatch):
    monkeypatch.setenv('STUDIOOS_ENV', 'production')   # but conftest uses SQLite and no backup status
    with pytest.raises(RuntimeError, match='will not start with live data'):
        with TestClient(app):
            pass


def test_version_matches_version_file(client):
    # v0.8.0: no longer pinned to 0.7.0; the app and the VERSION file must agree.
    from studioos.main import APP_VERSION
    from pathlib import Path
    assert (Path(__file__).resolve().parent.parent / 'VERSION').read_text().strip() == APP_VERSION
    assert client.get('/health').json()['version'] == APP_VERSION

"""Data safety checks for the app (v0.7.0). Standard library only.

* health(): turns the backup service's status.json into plain-language checks
  for the Admin's Data safety screen and the overview warning.
* production_problems(): settings that must be right before StudioOS will start
  with real data (STUDIOOS_ENV=production). The app refuses to start otherwise.
"""
from __future__ import annotations
import datetime as dt
import json
import os
from pathlib import Path

UTC = dt.timezone.utc
ENVIRONMENTS = ('development', 'test', 'production')


def environment() -> str:
    value = os.getenv('STUDIOOS_ENV', 'development').strip().lower()
    return value if value in ENVIRONMENTS else 'development'


def status_dir() -> Path | None:
    value = os.getenv('STUDIOOS_BACKUP_STATUS_DIR', '').strip()
    return Path(value) if value else None


def read_status() -> dict:
    folder = status_dir()
    if folder is None:
        return {}
    try:
        return json.loads((folder / 'status.json').read_text())
    except (OSError, ValueError):
        return {}


def _parse(value):
    try:
        t = dt.datetime.fromisoformat(value)
        return t if t.tzinfo else t.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def _ago(t: dt.datetime, now: dt.datetime) -> str:
    minutes = int((now - t).total_seconds() // 60)
    if minutes < 60:
        return f'{max(minutes, 0)} min ago'
    if minutes < 48 * 60:
        return f'{minutes // 60} h ago'
    return f'{minutes // 1440} days ago'


def health(status: dict | None = None, now: dt.datetime | None = None, env: str | None = None) -> dict:
    status = read_status() if status is None else status
    now = now or dt.datetime.now(UTC)
    env = env or environment()
    cfg = status.get('config') or {}
    every = int(cfg.get('backup_every_hours') or 6)
    drill_every = int(cfg.get('restore_drill_every_hours') or 24)
    checks = []

    def add(key, level, title, detail):
        checks.append({'key': key, 'level': level, 'title': title, 'detail': detail})

    beat = _parse(status.get('heartbeat'))
    if not status:
        add('service', 'fail', 'Backup service not found',
            'No backup status is available. Start the backup service and set STUDIOOS_BACKUP_STATUS_DIR.')
    elif beat is None or now - beat > dt.timedelta(minutes=30):
        add('service', 'fail', 'Backup service is not running',
            f"Last sign of life {_ago(beat, now) if beat else 'never'}. Check the backup container.")
    else:
        add('service', 'ok', 'Backup service running', f'Last check {_ago(beat, now)}.')

    last = status.get('last_backup') or {}
    t = _parse(last.get('time'))
    error = status.get('last_backup_error') or {}
    err_t = _parse(error.get('time'))
    if t is None:
        add('backup', 'fail', 'No verified backup yet', 'Do not enter real data until the first backup has verified.')
    elif err_t and err_t > t:
        add('backup', 'fail', 'Latest backup failed', f"{error.get('error', 'Unknown error')} Last good backup {_ago(t, now)}.")
    elif now - t > dt.timedelta(hours=2 * every + 1):
        add('backup', 'fail', 'Backups have stopped', f'Last verified backup {_ago(t, now)}; one should run every {every} h.')
    else:
        size = last.get('size_bytes') or 0
        add('backup', 'ok', 'Latest backup verified',
            f"{_ago(t, now)} · {size / 1048576:.1f} MB · {last.get('rows_total', 0)} rows · {last.get('backups_kept', 0)} kept")

    off = last.get('offsite') or {}
    if not cfg.get('offsite_configured', off.get('configured')):
        add('offsite', 'fail' if env == 'production' else 'warn', 'No copy off the NAS',
            'If the NAS fails, every backup on it goes too. Set STUDIOOS_OFFSITE_DIR to a USB drive, a second NAS or a cloud-synced folder.')
    elif off.get('ok') is False:
        add('offsite', 'fail', 'Off-NAS copy failed', off.get('error') or 'The copy could not be verified.')
    elif off.get('ok'):
        add('offsite', 'ok', 'Off-NAS copy verified', 'The latest backup also exists outside the NAS, checksum matched.')

    files = last.get('files') or {}
    if t is not None and files:
        if not files.get('configured'):
            add('files', 'fail' if env == 'production' else 'warn', 'Attached files are not backed up',
                'Set FILES_PATH so photos and files people attach are kept on the NAS and copied with every backup.')
        elif files.get('problems'):
            add('files', 'fail', 'Some attached files could not be backed up', '; '.join(files['problems'][:3]))
        else:
            add('files', 'ok', 'Attached files backed up', f"{files.get('files', 0)} files, {files.get('bytes', 0) / 1048576:.1f} MB, each checked by fingerprint")

    d = status.get('last_drill') or {}
    dt_ = _parse(d.get('time'))
    if dt_ is None:
        add('drill', 'warn' if env != 'production' else 'fail', 'Restore not tested yet',
            'A backup only counts once it has been restored. The service tests one automatically after the first backup.')
    elif not d.get('ok'):
        add('drill', 'fail', 'Restore test failed', d.get('error') or 'The restored data did not match the backup.')
    elif now - dt_ > dt.timedelta(hours=2 * drill_every + 1):
        add('drill', 'warn', 'Restore test is overdue', f'Last successful test {_ago(dt_, now)}.')
    else:
        add('drill', 'ok', 'Restore test passed', f"{_ago(dt_, now)} · {d.get('tables_checked', 0)} tables and {d.get('rows_checked', 0)} rows matched")

    order = {'ok': 0, 'warn': 1, 'fail': 2}
    overall = max((c['level'] for c in checks), key=order.get, default='fail')
    return {'overall': overall, 'environment': env, 'checks': checks,
            'last_backup': last or None, 'last_drill': d or None, 'updated_at': status.get('updated_at')}


def production_problems(environ=None) -> list[str]:
    """Everything that must be true before StudioOS will start with real data."""
    e = os.environ if environ is None else environ
    problems = []
    if e.get('STUDIOOS_SIMULATION_CLOCK'):
        problems.append('Simulation clock is forbidden with production data')
    url = e.get('DATABASE_URL', '')
    if not url.startswith(('postgresql', 'postgres')):
        problems.append('DATABASE_URL must point to PostgreSQL (SQLite is for testing only).')
    if e.get('STUDIOOS_REQUIRE_ADMIN_2FA', 'false').strip().lower() != 'true':
        problems.append('STUDIOOS_REQUIRE_ADMIN_2FA must be true.')
    inbox = e.get('STUDIOOS_INBOX_DIR', '').strip()
    if not inbox or not inbox.startswith('/') or inbox.startswith(('/app/data', './')):
        problems.append('STUDIOOS_INBOX_DIR must be a folder on the NAS (set FILES_PATH), so attached files survive updates and are backed up.')
    if e.get('STUDIOOS_SECURE_COOKIE', 'false').strip().lower() != 'true':
        problems.append('STUDIOOS_SECURE_COOKIE must be true: serve StudioOS over HTTPS (tailscale serve) so sign-in cookies never travel unencrypted.')
    if e.get('STUDIOOS_MCP_ENABLED', 'false').strip().lower() == 'true':
        # v0.9.3: the AI connector endpoint is reachable from outside; limit who can call it.
        if not e.get('STUDIOOS_MCP_ALLOWED_IPS', '').strip() and e.get('STUDIOOS_MCP_ALLOW_ANY_IP', 'false').strip().lower() != 'true':
            problems.append('STUDIOOS_MCP_ENABLED is on: set STUDIOOS_MCP_ALLOWED_IPS to the AI provider\'s published addresses '
                            '(or, knowingly, STUDIOOS_MCP_ALLOW_ANY_IP=true).')
        if not e.get('STUDIOOS_PUBLIC_HOST', '').strip():
            problems.append('STUDIOOS_MCP_ENABLED is on: set STUDIOOS_PUBLIC_HOST to the public connector address so only /mcp is reachable there.')
    if not e.get('STUDIOOS_BACKUP_STATUS_DIR', '').strip():
        problems.append('STUDIOOS_BACKUP_STATUS_DIR must be set so the app can see backup health.')
    if e.get('STUDIOOS_LIVE_TEST_ONLY', 'false').strip().lower() == 'true':
        problems.append('STUDIOOS_LIVE_TEST_ONLY is for the fictional benchmark; turn it off for live data.')
    if e.get('STUDIOOS_DEMO_DATA', 'false').strip().lower() == 'true':
        problems.append('STUDIOOS_DEMO_DATA must be false; demo records must not mix with real data.')
    pw = e.get('STUDIOOS_ADMIN_PASSWORD', '')
    if pw and len(pw) < 16:
        problems.append('Use an Admin password of at least 16 characters for live data.')
    return problems


def database_role_problems(engine) -> list[str]:
    """v0.16.0: on live data the app must connect as a role that owns nothing (see db_roles)."""
    from sqlalchemy import text
    from . import db_roles as R
    if engine.dialect.name != 'postgresql':
        return ['DATABASE_URL must point to PostgreSQL (SQLite is for testing only).']
    if os.getenv('STUDIOOS_DB_ROLE', 'owner').strip().lower() != 'app':
        return ['Set STUDIOOS_APP_DB_USER and STUDIOOS_APP_DB_PASSWORD in the env file so the app connects as the restricted '
                'role, not the database owner (RUNBOOK "Database roles").']
    with engine.connect() as conn:
        row = conn.execute(text(R.ROLE_QUERY)).first()
    return R.role_problems(tuple(row) if row else None)

"""v0.7.0 safekeeping tests. No web framework needed.

Retention and status tests always run. The PostgreSQL tests run when
STUDIOOS_TEST_PG_URL points at a DISPOSABLE PostgreSQL database, e.g.
    STUDIOOS_TEST_PG_URL=postgresql://studioos:pw@localhost:5432/studioos_safekeeping_test
They create and drop tables in that database. Never point it at real data.
Run alone with:  python -m pytest -q --noconftest tests/test_v070_safekeeping.py
"""
import datetime as dt
import json
import os
import subprocess
from pathlib import Path
import pytest
from studioos import safekeeping as sk

UTC = dt.timezone.utc
PG_URL = os.environ.get('STUDIOOS_TEST_PG_URL', '')
needs_pg = pytest.mark.skipif(not PG_URL, reason='set STUDIOOS_TEST_PG_URL to a disposable PostgreSQL database')


def cfg_for(tmp_path, **extra):
    env = {'DATABASE_URL': PG_URL or 'postgresql://u:p@localhost:5432/studioos_safekeeping_test',
           'STUDIOOS_BACKUP_DIR': str(tmp_path / 'primary'), 'STUDIOOS_OFFSITE_DIR': str(tmp_path / 'offsite'),
           'STUDIOOS_BACKUP_MIN_FREE_MB': '50', **extra}
    return sk.Config(env)


def fake_backups(folder, start, hours, count, label_every=None):
    folder.mkdir(parents=True, exist_ok=True)
    made = []
    for i in range(count):
        t = start - dt.timedelta(hours=hours * i)
        label = '_pre-upgrade' if label_every and i % label_every == 0 and i else ''
        p = folder / f"studioos_{t.strftime('%Y%m%dT%H%M%SZ')}{label}.dump"
        p.write_text('x')
        made.append(p)
    return made


# ---------------------------------------------------------------- retention

def test_retention_keeps_recent_daily_weekly_monthly(tmp_path):
    cfg = cfg_for(tmp_path)
    at = dt.datetime(2026, 11, 13, 12, tzinfo=UTC)
    files = fake_backups(tmp_path / 'primary', at, 6, 4 * 400)  # every 6 hours for 400 days
    keep = sk.choose_keep(sorted(files, key=lambda p: sk.parse_stamp(p.name), reverse=True), cfg, at)
    stamps = sorted(sk.parse_stamp(p.name) for p in keep)
    assert files[0] in keep                                   # newest always kept
    assert len(keep) <= cfg.keep_recent + cfg.keep_daily + cfg.keep_weekly + cfg.keep_monthly
    assert len({s.date() for s in stamps if at - s <= dt.timedelta(days=14)}) >= 14   # one per day, 2 weeks
    assert any(dt.timedelta(days=300) < at - s < dt.timedelta(days=380) for s in stamps)  # about a year back
    assert all(at - s <= dt.timedelta(days=31 * cfg.keep_monthly + 1) for s in stamps)


def test_labeled_backups_are_kept_longer(tmp_path):
    cfg = cfg_for(tmp_path, STUDIOOS_KEEP_LABELED_DAYS='180')
    at = dt.datetime(2026, 11, 13, 12, tzinfo=UTC)
    files = fake_backups(tmp_path / 'primary', at, 6, 4 * 200, label_every=37)
    ordered = sorted(files, key=lambda p: sk.parse_stamp(p.name), reverse=True)
    keep = sk.choose_keep(ordered, cfg, at)
    for p in ordered:
        if '_pre-upgrade' in p.name and at - sk.parse_stamp(p.name) <= dt.timedelta(days=180):
            assert p in keep


def test_prune_never_goes_below_the_floor(tmp_path):
    cfg = cfg_for(tmp_path)
    fake_backups(tmp_path / 'primary', sk.now(), 6, cfg.keep_recent)
    assert sk.prune(tmp_path / 'primary', cfg) == []
    assert len(sk.backups_in(tmp_path / 'primary')) == cfg.keep_recent


def test_partial_files_are_never_counted_as_backups(tmp_path):
    folder = tmp_path / 'primary'; folder.mkdir()
    (folder / 'studioos_20261113T000000Z.dump.partial').write_text('x')
    (folder / 'notes.txt').write_text('x')
    assert sk.backups_in(folder) == []


def test_status_file_is_written_atomically_and_merged(tmp_path):
    cfg = cfg_for(tmp_path)
    sk.write_status(cfg, last_backup={'file': 'a'})
    sk.write_status(cfg, heartbeat='now')
    status = json.loads((cfg.status_dir / 'status.json').read_text())
    assert status['last_backup'] == {'file': 'a'} and status['heartbeat'] == 'now'
    assert status['config']['offsite_configured'] is True
    assert not list(cfg.status_dir.glob('*.tmp'))


def test_due_logic():
    assert sk.due(None, 6)
    assert sk.due((sk.now() - dt.timedelta(hours=7)).isoformat(), 6)
    assert not sk.due((sk.now() - dt.timedelta(hours=1)).isoformat(), 6)


def test_password_never_on_command_line(tmp_path):
    cfg = sk.Config({'DATABASE_URL': 'postgresql+psycopg://studioos:s3cr%40t@db:5432/studioos'})
    env = cfg.pg_env()
    assert env['PGPASSWORD'] == 's3cr@t' and env['PGHOST'] == 'db' and env['PGDATABASE'] == 'studioos'
    with pytest.raises(sk.SafekeepingError):
        sk.Config({'DATABASE_URL': 'sqlite:///./data/studioos.db'}).pg_env()


def test_test_copy_refuses_outside_test_environment(tmp_path):
    with pytest.raises(sk.SafekeepingError, match='test environment'):
        sk.make_test_copy(cfg_for(tmp_path, STUDIOOS_ENV='production'))


# ---------------------------------------------------------------- real PostgreSQL

@pytest.fixture
def pg(tmp_path):
    cfg = cfg_for(tmp_path)
    env = cfg.pg_env()
    sk.psql(env, 'DROP TABLE IF EXISTS projects, costs, schema_migrations CASCADE')
    sk.psql(env, "CREATE TABLE schema_migrations (version int PRIMARY KEY); INSERT INTO schema_migrations SELECT generate_series(1,10);"
                 "CREATE TABLE projects (id serial PRIMARY KEY, name text, client_phone varchar(10) DEFAULT '');"
                 "CREATE TABLE costs (id serial PRIMARY KEY, project_id int REFERENCES projects(id), amount_paise bigint);"
                 "INSERT INTO projects (name, client_phone) SELECT 'Fixture ' || g, '98000000' || lpad(g::text, 2, '0') FROM generate_series(1, 30) g;"
                 "INSERT INTO costs (project_id, amount_paise) SELECT (g % 30) + 1, g * 100 FROM generate_series(1, 300) g;")
    yield cfg, env
    for db in ('studioos_restore_check', 'inspect_fixture_copy'):
        sk.psql(env, f'DROP DATABASE IF EXISTS {db}', 'postgres')


@needs_pg
def test_backup_is_verified_and_copied_off_nas(pg):
    cfg, env = pg
    r = sk.backup(cfg, label='pre-upgrade')
    assert r['verified'] and r['tables'] == 3 and r['rows_total'] == 340 and r['schema_version'] == 10
    assert r['offsite']['ok'] is True
    main = cfg.primary / r['file']; copy = cfg.offsite / r['file']
    assert sk.sha256_of(main) == sk.sha256_of(copy) == r['sha256']
    assert sk.read_status(cfg)['last_backup']['file'] == r['file']


@needs_pg
def test_restore_drill_proves_backup_restores(pg):
    cfg, env = pg
    sk.backup(cfg)
    d = sk.drill(cfg)
    assert d['ok'] and d['tables_checked'] == 3 and d['rows_checked'] == 340 and not d['mismatches']
    assert sk.psql(env, "SELECT count(*) FROM pg_database WHERE datname='studioos_restore_check'", 'postgres') == '0'


@needs_pg
def test_tampered_backup_fails_the_drill(pg):
    cfg, env = pg
    r = sk.backup(cfg)
    path = cfg.primary / r['file']
    data = bytearray(path.read_bytes()); data[len(data) // 2] ^= 0xFF; path.write_bytes(bytes(data))
    d = sk.drill(cfg)
    assert d['ok'] is False and 'checksum' in d['error']


@needs_pg
def test_restore_never_targets_live_and_copy_matches(pg):
    cfg, env = pg
    r = sk.backup(cfg)
    with pytest.raises(sk.SafekeepingError, match='live database'):
        sk.restore_copy(cfg, cfg.primary / r['file'], cfg.live_db)
    out = sk.restore_copy(cfg, cfg.primary / r['file'], 'inspect_fixture_copy')
    assert out['tables_checked'] == 3 and not out['mismatches']


@needs_pg
def test_offsite_failure_is_reported_not_hidden(pg, tmp_path):
    cfg, env = pg
    blocker = tmp_path / 'not-a-folder'; blocker.write_text('x')
    cfg.offsite = blocker  # a file where the off-NAS folder should be
    r = sk.backup(cfg)
    assert r['verified'] and r['offsite']['ok'] is False and r['offsite']['error']
    assert sk.read_status(cfg)['last_offsite_error']


@needs_pg
def test_v090_backup_records_the_history_fingerprint(pg):
    """v0.9.0: each backup keeps the newest chat and audit fingerprints (off the NAS too)."""
    cfg, env = pg
    assert sk.backup(cfg)['chain_heads'] == {}            # older schema: no fingerprints, backup still works
    sk.psql(env, "DROP TABLE IF EXISTS chat_messages, audit_events;"
                 "CREATE TABLE chat_messages (id serial PRIMARY KEY, content text, chain_hash varchar(64));"
                 "CREATE TABLE audit_events (id serial PRIMARY KEY, description text, chain_hash varchar(64));"
                 "INSERT INTO chat_messages (content, chain_hash) VALUES ('a', repeat('1', 64)), ('b', repeat('2', 64));")
    try:
        r = sk.backup(cfg)
        assert r['chain_heads'] == {'chat_messages': {'id': 2, 'hash': '2' * 64}}
        anchors = sk.read_status(cfg)['chain_anchors']
        assert anchors[-1]['file'] == r['file'] and anchors[-1]['heads'] == r['chain_heads']
        manifest = json.loads((cfg.offsite / (r['file'] + '.json')).read_text())
        assert manifest['chain_heads'] == r['chain_heads']
    finally:
        sk.psql(env, 'DROP TABLE IF EXISTS chat_messages, audit_events')


@needs_pg
def test_v091_attached_files_are_backed_up_and_checked_in_the_drill(tmp_path, pg):
    """v0.9.1 (audit F-04): the restore test fails if a file the database refers to is not in the backup."""
    import hashlib
    _, env = pg
    uploads = tmp_path / 'files' / 'new_type_uploads'; uploads.mkdir(parents=True)
    data = b'fictional bill photo'; digest = hashlib.sha256(data).hexdigest()
    (uploads / digest).write_bytes(data)
    cfg = cfg_for(tmp_path, STUDIOOS_INBOX_DIR=str(uploads))
    sk.psql(env, "DROP TABLE IF EXISTS new_type_inbox; CREATE TABLE new_type_inbox (id serial PRIMARY KEY, attachments json);"
                 f"INSERT INTO new_type_inbox (attachments) VALUES ('[{{\"sha256\": \"{digest}\", \"filename\": \"bill.jpg\"}}]')")
    try:
        r = sk.backup(cfg)
        assert r['files']['files'] == 1 and r['files']['copied'] == 1 and r['files']['offsite_copied'] == 1
        assert (cfg.offsite / 'files' / digest).read_bytes() == data
        d = sk.drill(cfg)
        assert d['ok'] and d['files_checked'] == 1 and d['files_missing'] == 0
        (cfg.primary / 'files' / digest).unlink()
        d = sk.drill(cfg)
        assert d['ok'] is False and d['files_missing'] == 1 and 'Attached files' in d['error']
    finally:
        sk.psql(env, 'DROP TABLE IF EXISTS new_type_inbox')


@needs_pg
def test_nested_inbox_files_are_required_by_a_populated_restore_drill(tmp_path,pg):
    import hashlib
    _,env=pg;root=tmp_path/'files';intake=root/'intake';old=root/'new_type_uploads'
    intake.mkdir(parents=True);old.mkdir()
    photo=b'Fictional populated Inbox photo';bill=b'Fictional historical attachment'
    photo_hash=hashlib.sha256(photo).hexdigest();bill_hash=hashlib.sha256(bill).hexdigest()
    (intake/photo_hash).write_bytes(photo);(old/bill_hash).write_bytes(bill)
    cfg=cfg_for(tmp_path,STUDIOOS_FILES_DIR=str(root))
    sk.psql(env,"CREATE TABLE intake_items (id serial PRIMARY KEY,sha256 text,stored_path text);"
        f"INSERT INTO intake_items (sha256,stored_path) VALUES ('{photo_hash}','/app/data/intake/{photo_hash}')")
    try:
        assert sk.referenced_files(env,cfg.live_db)=={'intake/'+photo_hash}
        backup=sk.backup(cfg);assert backup['files']['files']==2 and backup['files']['offsite_copied']==2,backup
        drill=sk.drill(cfg);assert drill['ok']and drill['files_checked']==2 and drill['files_missing']==0,drill
        restored=sk.restore_files(cfg.primary,tmp_path/'restored-files');assert restored['ok']and restored['restored']==2,restored
        assert (tmp_path/'restored-files/intake'/photo_hash).read_bytes()==photo
        assert (tmp_path/'restored-files/new_type_uploads'/bill_hash).read_bytes()==bill
        (cfg.primary/'files/intake'/photo_hash).unlink()
        drill=sk.drill(cfg);assert not drill['ok']and drill['files_missing']==1,drill
    finally:sk.psql(env,'DROP TABLE IF EXISTS intake_items')

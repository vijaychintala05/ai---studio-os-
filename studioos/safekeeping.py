"""StudioOS safekeeping: verified PostgreSQL backups, off-NAS copies, restore
drills and safe restores (v0.7.0).

Standard library only, plus PostgreSQL's own tools (pg_dump, pg_restore, psql).
It never imports the web app, so a broken app release cannot stop backups.

Commands (inside the `backup` container: docker compose exec backup python -m studioos.safekeeping ...):

    run                      the service: back up every few hours, restore-test daily
    backup [--label NAME]    one verified backup now (e.g. --label pre-upgrade)
    drill                    restore the newest backup into a scratch database and compare
    status                   print the current safety status as JSON
    list                     list backups, newest first
    restore-copy --file F --into NAME
                             restore a backup into a NEW database for inspection
    swap-in --file F --confirm-live-replace
                             disaster recovery: replace the live database with a backup.
                             The current live database is RENAMED, never dropped.
    make-test-copy [--file F]
                             test environment only: load the newest live backup into the
                             test database and mask personal details

Safety rules built in:
  * A backup counts only after pg_restore can read it, its checksum is recorded and
    (for the off-NAS copy) the copy's checksum matches.
  * Old backups are pruned only after a new one verifies, and never below a floor.
  * A restore never writes into the live database. swap-in renames the live database
    aside first, so nothing is ever destroyed.
  * Status is written atomically to status.json for the app's Data safety screen.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, unquote

NAME_RE = re.compile(r'^studioos_(\d{8}T\d{6}Z)(?:_([a-z0-9-]{1,40}))?\.dump$')
SCRATCH_DB = 'studioos_restore_check'
UTC = dt.timezone.utc


# ----------------------------------------------------------------- configuration

class Config:
    def __init__(self, environ=None):
        e = os.environ if environ is None else environ
        self.database_url = e.get('DATABASE_URL', '')
        self.primary = Path(e.get('STUDIOOS_BACKUP_DIR', '/backups/primary'))
        offsite = e.get('STUDIOOS_OFFSITE_DIR', '').strip()
        self.offsite = Path(offsite) if offsite else None
        self.status_dir = Path(e.get('STUDIOOS_BACKUP_STATUS_DIR', str(self.primary / 'status')))
        self.interval_hours = env_int_from(e, 'STUDIOOS_BACKUP_EVERY_HOURS', 6, 1, 24)
        self.drill_every_hours = env_int_from(e, 'STUDIOOS_RESTORE_DRILL_EVERY_HOURS', 24, 1, 24 * 14)
        self.keep_recent = env_int_from(e, 'STUDIOOS_KEEP_RECENT', 8, 2, 500)
        self.keep_daily = env_int_from(e, 'STUDIOOS_KEEP_DAILY', 14, 1, 365)
        self.keep_weekly = env_int_from(e, 'STUDIOOS_KEEP_WEEKLY', 8, 1, 260)
        self.keep_monthly = env_int_from(e, 'STUDIOOS_KEEP_MONTHLY', 12, 1, 120)
        self.keep_labeled_days = env_int_from(e, 'STUDIOOS_KEEP_LABELED_DAYS', 180, 7, 3650)
        self.min_free_mb = env_int_from(e, 'STUDIOOS_BACKUP_MIN_FREE_MB', 500, 50, 10 ** 7)
        self.environment = e.get('STUDIOOS_ENV', 'development').strip().lower()
        self.live_backups = Path(e.get('STUDIOOS_LIVE_BACKUPS_DIR', '/live-backups'))
        # v0.9.1 (audit F-04): files people attach (photos, bills) live outside the
        # database. They are mirrored into both backup locations and checked in drills.
        files = (e.get('STUDIOOS_FILES_DIR') or e.get('STUDIOOS_INBOX_DIR','')).strip()
        self.files_dir = Path(files) if files else None
        self.files_are_root=bool(e.get('STUDIOOS_FILES_DIR','').strip())

    def pg_env(self) -> dict:
        """libpq variables from DATABASE_URL, so the password never appears on a command line."""
        url = self.database_url.replace('postgresql+psycopg://', 'postgresql://', 1)
        parts = urlsplit(url)
        if parts.scheme not in ('postgresql', 'postgres') or not parts.path.strip('/'):
            raise SafekeepingError('DATABASE_URL must be a PostgreSQL URL (postgresql+psycopg://user:pass@host:5432/db)')
        env = dict(os.environ)
        env.update({'PGHOST': unquote(parts.hostname or 'localhost'), 'PGPORT': str(parts.port or 5432),
                    'PGUSER': unquote(parts.username or ''), 'PGDATABASE': unquote(parts.path.strip('/')),
                    'PGCONNECT_TIMEOUT': '15', 'PGAPPNAME': 'studioos-safekeeping'})
        if parts.password is not None:
            env['PGPASSWORD'] = unquote(parts.password)
        if parts.hostname and parts.hostname.startswith('/'):
            env['PGHOST'] = parts.hostname
        query = dict(p.split('=', 1) for p in parts.query.split('&') if '=' in p)
        if 'host' in query:  # socket directory form: postgresql://user@/db?host=/var/run/postgresql
            env['PGHOST'] = unquote(query['host'])
        return env

    @property
    def live_db(self) -> str:
        return self.pg_env()['PGDATABASE']


def env_int_from(e, name, default, low, high):
    try:
        value = int(e.get(name, str(default)))
    except ValueError:
        value = default
    return min(max(value, low), high)


class SafekeepingError(RuntimeError):
    pass


# ----------------------------------------------------------------- helpers

def now() -> dt.datetime:
    return dt.datetime.now(UTC)


def iso(t: dt.datetime | None) -> str | None:
    return t.astimezone(UTC).isoformat(timespec='seconds') if t else None


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def run(cmd: list[str], env: dict, *, capture=True, timeout=3600, input_text: str | None = None) -> str:
    try:
        done = subprocess.run(cmd, env=env, capture_output=capture, text=True, timeout=timeout, input=input_text)
    except FileNotFoundError:
        raise SafekeepingError(f'{cmd[0]} is not installed in this container') from None
    except subprocess.TimeoutExpired:
        raise SafekeepingError(f'{cmd[0]} took longer than {timeout} seconds') from None
    if done.returncode != 0:
        detail = (done.stderr or done.stdout or '').strip().splitlines()[-3:]
        raise SafekeepingError(f'{cmd[0]} failed: ' + ' | '.join(detail))
    return done.stdout if capture else ''


def psql_transaction(env: dict, statements: str, db: str) -> str:
    """Stream a trusted recovery DML batch atomically, without OS argv limits.

    Kept separate from psql(): CREATE/DROP DATABASE operations must not run
    inside a transaction. The isolated masked-copy fingerprint batches must.
    """
    cmd = ['psql', '-X', '-q', '-At', '-v', 'ON_ERROR_STOP=1', '-1', '-f', '-', '-d', db]
    return run(cmd, env, input_text=statements).strip()


def psql(env: dict, sql: str, db: str | None = None) -> str:
    cmd = ['psql', '-X', '-q', '-At', '-v', 'ON_ERROR_STOP=1', '-c', sql]
    if db:
        cmd += ['-d', db]
    return run(cmd, env).strip()


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def parse_stamp(name: str) -> dt.datetime | None:
    m = NAME_RE.match(name)
    return dt.datetime.strptime(m.group(1), '%Y%m%dT%H%M%SZ').replace(tzinfo=UTC) if m else None


def backups_in(folder: Path | None) -> list[Path]:
    """Finished backups (never .partial files), newest first."""
    if not folder or not folder.is_dir():
        return []
    files = [p for p in folder.iterdir() if p.is_file() and NAME_RE.match(p.name)]
    return sorted(files, key=lambda p: parse_stamp(p.name), reverse=True)


@contextlib.contextmanager
def exclusive_lock(folder: Path):
    """One backup, drill or restore at a time, even across containers sharing the folder."""
    folder.mkdir(parents=True, exist_ok=True)
    handle = (folder / '.safekeeping.lock').open('w')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise SafekeepingError('Another backup, restore test or restore is already running') from None
    try:
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


# ----------------------------------------------------------------- status file

def read_status(cfg: Config) -> dict:
    try:
        return json.loads((cfg.status_dir / 'status.json').read_text())
    except (OSError, ValueError):
        return {}


def write_status(cfg: Config, **changes) -> dict:
    cfg.status_dir.mkdir(parents=True, exist_ok=True)
    status = read_status(cfg)
    status.update(changes)
    status['updated_at'] = iso(now())
    status['config'] = {'backup_every_hours': cfg.interval_hours, 'restore_drill_every_hours': cfg.drill_every_hours,
                        'offsite_configured': cfg.offsite is not None, 'environment': cfg.environment,
                        'keep': {'recent': cfg.keep_recent, 'daily': cfg.keep_daily, 'weekly': cfg.keep_weekly,
                                 'monthly': cfg.keep_monthly, 'labeled_days': cfg.keep_labeled_days}}
    target = cfg.status_dir / 'status.json'
    tmp = target.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(status, indent=2))
    os.replace(tmp, target)  # atomic: the app never reads a half-written file
    return status


# ----------------------------------------------------------------- dump contents

COPY_RE = re.compile(r'^COPY (\S+) \(.*\) FROM stdin;$')


def dump_row_counts(path: Path, env: dict) -> dict[str, int]:
    """Rows per table as stored INSIDE the backup file (independent of any database)."""
    proc = subprocess.Popen(['pg_restore', '--data-only', '--file=-', str(path)], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    counts: dict[str, int] = {}
    current = None
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip('\n')
        if current is None:
            m = COPY_RE.match(line)
            if m:
                current = m.group(1)
                counts[current] = 0
        elif line == '\\.':
            current = None
        else:
            counts[current] += 1
    err = proc.stderr.read() if proc.stderr else ''
    if proc.wait() != 0:
        raise SafekeepingError('pg_restore could not read the backup data: ' + err.strip()[-300:])
    return counts


def table_counts(env: dict, db: str, tables) -> dict[str, int]:
    out = {}
    for t in tables:
        out[t] = int(psql(env, f'SELECT count(*) FROM {t}', db))
    return out


def schema_version(env: dict, db: str) -> int | None:
    exists = psql(env, "SELECT to_regclass('public.schema_migrations') IS NOT NULL", db)
    if exists != 't':
        return None
    value = psql(env, 'SELECT COALESCE(MAX(version),0) FROM public.schema_migrations', db)
    return int(value or 0)


def chain_heads(env: dict, db: str) -> dict:
    """v0.9.0: the newest fingerprint of the conversation and audit history. Kept in
    every backup manifest (and so off the NAS) to prove later that history was not
    rewritten. Never fails a backup: older databases simply have no fingerprints."""
    heads = {}
    for table in ('chat_messages', 'audit_events'):
        try:
            has = psql(env, "SELECT count(*) FROM information_schema.columns "
                            f"WHERE table_schema='public' AND table_name='{table}' AND column_name='chain_hash'", db)
            if has != '1':
                continue
            row = psql(env, f"SELECT id || ',' || chain_hash FROM {table} WHERE chain_hash IS NOT NULL ORDER BY id DESC LIMIT 1", db)
            if row:
                ident, digest = row.split(',', 1)
                heads[table] = {'id': int(ident), 'hash': digest}
        except (SafekeepingError, ValueError):
            continue
    return heads


# ----------------------------------------------------------------- attached files

HEX64 = re.compile(r'[0-9a-f]{64}')


def attachment_files(root: Path):
    """Regular fingerprint files in both current nested and historical flat layouts."""
    if not root.is_dir():return []
    return sorted((p for p in root.rglob('*') if HEX64.fullmatch(p.name) and (p.is_file() or p.is_symlink())),key=lambda p:p.as_posix())


def attachment_destination(root:Path,relative:Path):
    path=root/relative
    if path.is_symlink()or not path.parent.resolve().is_relative_to(root.resolve()):
        raise SafekeepingError('Attachment destination escapes its configured folder')
    path.parent.mkdir(parents=True,exist_ok=True)
    return path


def mirror_files(src: Path | None, dest: Path) -> dict:
    """Add-only, hash-checked mirror preserving the two attachment folder layouts."""
    out={'configured':src is not None,'files':0,'copied':0,'bytes':0,'problems':[]}
    if src is None:return out
    if not src.is_dir():
        if not src.parent.is_dir():out['problems'].append(f'Attachment folder {src.parent} is missing; check FILES_PATH')
        return out
    target=dest/'files';target.mkdir(parents=True,exist_ok=True)
    for source in attachment_files(src):
        relative=source.relative_to(src);out['files']+=1
        if source.is_symlink()or not source.resolve().is_relative_to(src.resolve()):
            out['problems'].append('Unsafe attachment path: '+relative.as_posix());continue
        out['bytes']+=source.stat().st_size
        if sha256_of(source)!=source.name:
            out['problems'].append(source.name[:12]+'… does not match its fingerprint; not copied');continue
        try:final=attachment_destination(target,relative)
        except SafekeepingError as error:out['problems'].append(str(error));continue
        if final.exists():
            if sha256_of(final)!=source.name:out['problems'].append('Existing attachment mirror is damaged: '+relative.as_posix())
            continue
        partial=final.with_name(final.name+'.partial');shutil.copyfile(source,partial)
        with partial.open('rb')as fh:os.fsync(fh.fileno())
        if sha256_of(partial)!=source.name:
            partial.unlink(missing_ok=True);out['problems'].append('Copy did not verify: '+relative.as_posix());continue
        os.replace(partial,final);out['copied']+=1
    return out


def check_file_mirror(folder: Path, referenced: set[str]) -> dict:
    files=folder/'files';paths=attachment_files(files);present=set();damaged=[]
    for path in paths:
        relative=path.relative_to(files).as_posix();present.add(relative)
        # Old new-data references contain only their hash. Inbox references retain
        # their folder, so a different family cannot disguise a missing Inbox file.
        if '/'not in relative or relative.startswith('new_type_uploads/'):present.add(path.name)
        if path.is_symlink()or sha256_of(path)!=path.name:damaged.append(relative)
    missing=sorted(referenced-present)
    return {'files_checked':len(paths),'files_damaged':len(damaged),'files_missing':len(missing),'missing_examples':[p[:12]for p in missing[:5]]}


def restore_files(source: Path, target: Path, *, full_root=False) -> dict:
    files=source/'files'
    if not files.is_dir():raise SafekeepingError(f'No attached-file backup found in {source}')
    target.mkdir(parents=True,exist_ok=True)
    out={'source':str(source),'target':str(target),'restored':0,'already_present':0,'damaged_in_backup':[]}
    for path in attachment_files(files):
        relative=path.relative_to(files)
        if full_root and relative.parent==Path('.'):relative=Path('new_type_uploads')/relative
        if path.is_symlink()or sha256_of(path)!=path.name:
            out['damaged_in_backup'].append(path.name[:12]);continue
        final=attachment_destination(target,relative)
        if final.exists():
            if sha256_of(final)!=path.name:raise SafekeepingError('Existing restored attachment is damaged; not overwritten')
            out['already_present']+=1;continue
        partial=final.with_name(final.name+'.partial');shutil.copyfile(path,partial)
        if sha256_of(partial)!=path.name:
            partial.unlink(missing_ok=True);out['damaged_in_backup'].append(path.name[:12]);continue
        os.chmod(partial,0o400);os.replace(partial,final);out['restored']+=1
    out['ok']=not out['damaged_in_backup'];return out


def referenced_files(env: dict, db: str) -> set[str]:
    referenced=set()
    if psql(env,"SELECT to_regclass('public.new_type_inbox') IS NOT NULL",db)=='t':
        rows=psql(env,"SELECT a->>'sha256' FROM new_type_inbox, json_array_elements(COALESCE(attachments::json, '[]'::json)) a",db)
        referenced.update(r.strip()for r in rows.splitlines()if HEX64.fullmatch(r.strip()))
    if psql(env,"SELECT to_regclass('public.intake_items') IS NOT NULL",db)=='t':
        rows=psql(env,"SELECT json_build_object('sha256',sha256,'stored_path',stored_path)::text FROM intake_items WHERE stored_path <> ''",db)
        for line in rows.splitlines():
            item=json.loads(line);digest=item['sha256'];name=Path(item['stored_path'].replace('\\','/')).name
            if not HEX64.fullmatch(digest)or name!=digest:raise SafekeepingError('Inbox attachment path does not match its fingerprint')
            referenced.add('intake/'+digest)
    return referenced

# ----------------------------------------------------------------- backup

def check_free_space(folder: Path, cfg: Config, last_size: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    free_mb = shutil.disk_usage(folder).free // (1024 * 1024)
    needed_mb = max(cfg.min_free_mb, (3 * last_size) // (1024 * 1024))
    if free_mb < needed_mb:
        raise SafekeepingError(f'Only {free_mb} MB free in {folder}; need at least {needed_mb} MB. Free space or add storage.')


def copy_verified(src: Path, folder: Path, digest: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    partial = folder / (src.name + '.partial')
    final = folder / src.name
    shutil.copyfile(src, partial)
    with partial.open('rb') as f:
        os.fsync(f.fileno())
    if sha256_of(partial) != digest:
        partial.unlink(missing_ok=True)
        raise SafekeepingError(f'Copy to {folder} did not match the original checksum')
    os.replace(partial, final)
    (folder / (src.name + '.sha256')).write_text(f'{digest}  {src.name}\n')
    return final


def backup(cfg: Config, label: str | None = None) -> dict:
    env = cfg.pg_env()
    if label is not None and not re.fullmatch(r'[a-z0-9-]{1,40}', label):
        raise SafekeepingError('Label must be 1-40 lowercase letters, digits or dashes')
    with exclusive_lock(cfg.primary):
        previous = backups_in(cfg.primary)
        check_free_space(cfg.primary, cfg, previous[0].stat().st_size if previous else 0)
        stamp = now().strftime('%Y%m%dT%H%M%SZ')
        name = f'studioos_{stamp}' + (f'_{label}' if label else '') + '.dump'
        final = cfg.primary / name
        partial = cfg.primary / (name + '.partial')
        started = time.monotonic()
        heads = chain_heads(env, cfg.live_db)   # read before the dump: these rows are inside it
        try:
            run(['pg_dump', '--format=custom', '--compress=6', '--no-owner', '--no-privileges',
                 '--file=' + str(partial)], env, timeout=6 * 3600)
            with partial.open('rb') as f:
                os.fsync(f.fileno())
            if partial.stat().st_size == 0:
                raise SafekeepingError('pg_dump produced an empty file')
            toc = run(['pg_restore', '--list', str(partial)], env)
            tables = dump_row_counts(partial, env)
            digest = sha256_of(partial)
            os.replace(partial, final)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        (cfg.primary / (name + '.sha256')).write_text(f'{digest}  {name}\n')
        manifest = {'file': name, 'created_at': iso(parse_stamp(name)), 'label': label, 'size_bytes': final.stat().st_size,
                    'sha256': digest, 'toc_entries': sum(1 for line in toc.splitlines() if line and not line.startswith(';')),
                    'tables': tables, 'rows_total': sum(tables.values()),
                    'schema_version': schema_version(env, cfg.live_db), 'seconds': round(time.monotonic() - started, 1),
                    'chain_heads': heads}
        (cfg.primary / (name + '.json')).write_text(json.dumps(manifest, indent=2))
        offsite = {'configured': cfg.offsite is not None, 'ok': None, 'path': None, 'error': None}
        if cfg.offsite is not None:
            try:
                check_free_space(cfg.offsite, cfg, final.stat().st_size)
                copy = copy_verified(final, cfg.offsite, digest)
                shutil.copyfile(cfg.primary / (name + '.json'), cfg.offsite / (name + '.json'))
                offsite.update(ok=True, path=str(copy))
            except (OSError, SafekeepingError) as err:
                offsite.update(ok=False, error=str(err)[:300])
        files = mirror_files(cfg.files_dir, cfg.primary)
        if cfg.offsite is not None and offsite['ok']:
            off_files = mirror_files(cfg.files_dir, cfg.offsite)
            files['offsite_copied'] = off_files['copied']
            files['problems'] += ['Off-NAS: ' + p for p in off_files['problems']]
        pruned = prune(cfg.primary, cfg) + (prune(cfg.offsite, cfg) if cfg.offsite and offsite['ok'] else [])
        result = {'time': iso(now()), 'file': name, 'size_bytes': manifest['size_bytes'], 'sha256': digest,
                  'verified': True, 'tables': len(tables), 'rows_total': manifest['rows_total'],
                  'schema_version': manifest['schema_version'], 'label': label, 'offsite': offsite,
                  'pruned': [p.name for p in pruned], 'backups_kept': len(backups_in(cfg.primary)), 'chain_heads': heads,
                  'files': files}
        anchors = [a for a in (read_status(cfg).get('chain_anchors') or []) if isinstance(a, dict)]
        if heads:
            anchors = (anchors + [{'file': name, 'time': result['time'], 'heads': heads}])[-30:]
        status_changes = {}
        masked = dict(read_status(cfg).get('masked_test_copy') or {})
        if cfg.environment == 'test' and masked:
            masked.update(requires_verified_backup=False, verified_backup=name)
            status_changes['masked_test_copy'] = masked
        write_status(cfg, last_backup=result, last_backup_error=None, chain_anchors=anchors,
                     last_offsite_error=offsite['error'] if offsite['configured'] else None, **status_changes)
        return result


# ----------------------------------------------------------------- retention

def choose_keep(files: list[Path], cfg: Config, at: dt.datetime | None = None) -> set[Path]:
    """Keep: the newest few; newest per day/week/month for a while; labeled ones for a long time."""
    at = at or now()
    keep: set[Path] = set(files[:cfg.keep_recent])
    seen_day, seen_week, seen_month = set(), set(), set()
    for p in files:  # newest first
        t = parse_stamp(p.name)
        age = at - t
        day, week, month = t.date(), t.isocalendar()[:2], (t.year, t.month)
        if age <= dt.timedelta(days=cfg.keep_daily) and day not in seen_day:
            keep.add(p); seen_day.add(day)
        if age <= dt.timedelta(weeks=cfg.keep_weekly) and week not in seen_week:
            keep.add(p); seen_week.add(week)
        if age <= dt.timedelta(days=31 * cfg.keep_monthly) and month not in seen_month:
            keep.add(p); seen_month.add(month)
        if NAME_RE.match(p.name).group(2) and age <= dt.timedelta(days=cfg.keep_labeled_days):
            keep.add(p)
    return keep


def prune(folder: Path, cfg: Config) -> list[Path]:
    files = backups_in(folder)
    if len(files) <= cfg.keep_recent:
        return []
    keep = choose_keep(files, cfg)
    removed = []
    for p in files:
        if p in keep:
            continue
        for extra in (p, p.with_name(p.name + '.sha256'), p.with_name(p.name + '.json')):
            extra.unlink(missing_ok=True)
        removed.append(p)
    return removed


# ----------------------------------------------------------------- restore drill

def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def terminate_connections(env: dict, db: str) -> None:
    psql(env, "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
              f"WHERE datname = {sql_literal(db)} AND pid <> pg_backend_pid()", 'postgres')


def restore_into_new(env: dict, path: Path, db: str, cfg: Config, *, prepare_test_copy=False) -> None:
    if db == cfg.live_db:
        raise SafekeepingError('Refusing to restore into the live database')
    if prepare_test_copy and(cfg.environment!='test'or db!=cfg.live_db+'_incoming'):
        raise SafekeepingError('Masked preparation is restricted to the incoming test-copy database')
    if not re.fullmatch(r'[a-z][a-z0-9_]{2,62}', db):
        raise SafekeepingError('Database name must be lowercase letters, digits and underscores')
    exists = psql(env, f"SELECT 1 FROM pg_database WHERE datname = {sql_literal(db)}", 'postgres')
    if exists:
        raise SafekeepingError(f'Database {db} already exists; choose another name')
    psql(env, f'CREATE DATABASE {quote_ident(db)}', 'postgres')
    if prepare_test_copy:psql(env,f'REVOKE CONNECT ON DATABASE {quote_ident(db)} FROM PUBLIC','postgres')
    try:
        sections=['--section=pre-data','--section=data']if prepare_test_copy else[]
        run(['pg_restore', '--no-owner', '--no-privileges', '--exit-on-error', '--single-transaction',
             *sections,'--dbname=' + db, str(path)], env, timeout=6 * 3600)
        # pg_dump carries no planner statistics. Reports must work on the first
        # open, without waiting for autovacuum. A masked incoming copy must wait
        # until masking is complete so statistics never retain unmasked samples.
        if not prepare_test_copy:psql(env,'ANALYZE',db)
    except SafekeepingError:
        psql(env, f'DROP DATABASE IF EXISTS {quote_ident(db)}', 'postgres')
        raise


def compare_restored(env: dict, path: Path, db: str) -> dict:
    expected = dump_row_counts(path, env)
    actual = table_counts(env, db, expected)
    mismatches = {t: {'in_backup': expected[t], 'restored': actual[t]} for t in expected if expected[t] != actual[t]}
    return {'tables_checked': len(expected), 'rows_checked': sum(expected.values()), 'mismatches': mismatches,
            'schema_version': schema_version(env, db)}


def drill(cfg: Config, file: Path | None = None) -> dict:
    env = cfg.pg_env()
    with exclusive_lock(cfg.primary):
        target = file or next(iter(backups_in(cfg.primary)), None)
        if target is None:
            raise SafekeepingError('No backup exists yet to test')
        recorded = (target.with_name(target.name + '.sha256')).read_text().split()[0] if target.with_name(target.name + '.sha256').exists() else None
        if recorded and sha256_of(target) != recorded:
            result = {'time': iso(now()), 'file': target.name, 'ok': False, 'error': 'Backup file changed since it was made (checksum mismatch)'}
            write_status(cfg, last_drill=result)
            return result
        started = time.monotonic()
        try:
            terminate_connections(env, SCRATCH_DB)
            psql(env, f'DROP DATABASE IF EXISTS {quote_ident(SCRATCH_DB)}', 'postgres')
            restore_into_new(env, target, SCRATCH_DB, cfg)
            check = compare_restored(env, target, SCRATCH_DB)
            # v0.9.1: the attached files the restored database refers to must all be in the backup.
            files = check_file_mirror(cfg.primary, referenced_files(env, SCRATCH_DB))
            check = {**check, **files}
            ok = not check['mismatches'] and check['tables_checked'] > 0 and not files['files_damaged'] and not files['files_missing']
            result = {'time': iso(now()), 'file': target.name, 'ok': ok, 'seconds': round(time.monotonic() - started, 1),
                      **check, 'error': None if ok else ('Attached files are missing or damaged in the backup' if not check['mismatches'] and check['tables_checked'] else 'Restored data did not match the backup')}
        except SafekeepingError as err:
            result = {'time': iso(now()), 'file': target.name, 'ok': False, 'error': str(err)[:400]}
        finally:
            with contextlib.suppress(SafekeepingError):
                psql(env, f'DROP DATABASE IF EXISTS {quote_ident(SCRATCH_DB)}', 'postgres')
        write_status(cfg, last_drill=result)
        return result


# ----------------------------------------------------------------- restores

def restore_copy(cfg: Config, file: Path, into: str) -> dict:
    env = cfg.pg_env()
    with exclusive_lock(cfg.primary):
        restore_into_new(env, file, into, cfg)
        check = compare_restored(env, file, into)
        return {'restored_into': into, 'file': file.name, **check}


def swap_in(cfg: Config, file: Path, confirmed: bool) -> dict:
    """Replace the live database with a backup. The current live database is renamed
    to <live>_replaced_<time>, never dropped, so this can itself be undone."""
    if not confirmed:
        raise SafekeepingError('Add --confirm-live-replace. Stop the app first (docker compose stop app).')
    env = cfg.pg_env()
    live = cfg.live_db
    staging = f'{live}_incoming'
    aside = f"{live}_replaced_{now().strftime('%Y%m%d%H%M%S')}"
    with exclusive_lock(cfg.primary):
        terminate_connections(env, staging)
        psql(env, f'DROP DATABASE IF EXISTS {quote_ident(staging)}', 'postgres')
        restore_into_new(env, file, staging, cfg)       # 1. restore beside the live database
        check = compare_restored(env, file, staging)    # 2. prove it is complete
        if check['mismatches'] or not check['tables_checked']:
            raise SafekeepingError('Restored copy did not match the backup; live database left untouched')
        terminate_connections(env, live)                # 3. only now touch live: rename it aside
        psql(env, f'ALTER DATABASE {quote_ident(live)} RENAME TO {quote_ident(aside)}', 'postgres')
        try:
            terminate_connections(env, staging)
            psql(env, f'ALTER DATABASE {quote_ident(staging)} RENAME TO {quote_ident(live)}', 'postgres')
        except SafekeepingError:
            psql(env, f'ALTER DATABASE {quote_ident(aside)} RENAME TO {quote_ident(live)}', 'postgres')
            raise
        result = {'time': iso(now()), 'file': file.name, 'live_database': live, 'previous_live_kept_as': aside, **check}
        write_status(cfg, last_swap_in=result)
        return result


# ----------------------------------------------------------------- test copy

MASKING_SQL = r"""
-- These temporary functions exist only while constructing an isolated test copy.
CREATE FUNCTION pg_temp.studioos_mask_plain_text(value text) RETURNS text LANGUAGE SQL IMMUTABLE AS $fn$
 SELECT regexp_replace(regexp_replace(regexp_replace(value,
  '(?<![0-9])(?:\+?91[ -]?)?[6-9][0-9]{9}(?![0-9])','9000000000','g'),
  '[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]','MASKEDGSTIN0000','g'),
  '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}','x@x.invalid','g')
$fn$;
CREATE FUNCTION pg_temp.studioos_mask_text(value text) RETURNS text LANGUAGE plpgsql IMMUTABLE AS $fn$
DECLARE remaining text:=value; result text:=''; segment text[];
BEGIN
 LOOP
  segment=regexp_match(remaining,'^(.*?)([0-9a-f]{64})(.*)$','s');
  EXIT WHEN segment IS NULL;
  result=result||pg_temp.studioos_mask_plain_text(segment[1])||segment[2];remaining=segment[3];
 END LOOP;
 RETURN result||pg_temp.studioos_mask_plain_text(remaining);
END $fn$;
CREATE FUNCTION pg_temp.studioos_mask_json(value jsonb,field_name text DEFAULT '') RETURNS jsonb LANGUAGE plpgsql AS $fn$
DECLARE result jsonb; child record;
BEGIN
 IF jsonb_typeof(value)='object' THEN
  result='{}'::jsonb;
  FOR child IN SELECT key,val FROM jsonb_each(value) AS pairs(key,val) LOOP
   result=result||jsonb_build_object(child.key,pg_temp.studioos_mask_json(child.val,child.key));
  END LOOP;RETURN result;
 ELSIF jsonb_typeof(value)='array' THEN
  result='[]'::jsonb;
  FOR child IN SELECT val FROM jsonb_array_elements(value)AS items(val) LOOP
   result=result||jsonb_build_array(pg_temp.studioos_mask_json(child.val,field_name));
  END LOOP;RETURN result;
 ELSIF jsonb_typeof(value)='string' AND field_name !~* '(^|_)(amount|paise|price|balance|cost|total|budget|quantity|rate)(_|$)' THEN
  RETURN to_jsonb(pg_temp.studioos_mask_text(value#>>'{}'));
 END IF;
 -- JSON numbers (including paise) are never personal-text patterns.
 RETURN value;
END $fn$;
DO $mask$
DECLARE c record; expression text; condition text;
BEGIN
 FOR c IN SELECT table_name,column_name,data_type FROM information_schema.columns
  WHERE table_schema='public'AND data_type IN('text','character varying','json','jsonb')
   AND NOT(table_name='users'AND column_name IN('password_hash','username','role'))
   AND table_name<>'schema_migrations'
 LOOP
  IF c.data_type IN('json','jsonb')THEN
   expression=format('pg_temp.studioos_mask_json(%I::jsonb)::%s',c.column_name,c.data_type);
   condition=format('%I::jsonb IS DISTINCT FROM (%s)::jsonb',c.column_name,expression);
  ELSE
   expression=format('pg_temp.studioos_mask_text(%I)::%s',c.column_name,CASE WHEN c.data_type='character varying'THEN'varchar'ELSE'text'END);
   condition=format('%I IS DISTINCT FROM %s',c.column_name,expression);
  END IF;
  EXECUTE format('UPDATE %I SET %I=%s WHERE %s',c.table_name,c.column_name,expression,condition);
 END LOOP;
END $mask$;
-- 2. Free text that may hold names and addresses.
UPDATE chat_messages SET content = '[masked message ' || id || ']';
UPDATE context_summaries SET summary = '[masked summary ' || id || ']';
UPDATE new_type_inbox SET raw_payload = jsonb_build_object('text', '[masked source ' || id || ']');
-- 3. Accounts: only the Admin can sign in, with the TEST password; no sessions; no two-factor.
DELETE FROM login_sessions;
DELETE FROM login_attempts;
-- v0.9.5 (review F07): no live credentials of any kind survive into the test copy.
DO $keys$ BEGIN
  IF to_regclass('public.mcp_calls') IS NOT NULL THEN DELETE FROM mcp_calls; END IF;
  IF to_regclass('public.connector_tokens') IS NOT NULL THEN DELETE FROM connector_tokens; END IF;
END $keys$;
-- Masking changed the history, so its fingerprints no longer apply. The test app
-- fingerprints it again at start-up, as a TEST-ONLY baseline (see migrations.py).
DO $chain$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='chat_messages' AND column_name='chain_hash') THEN
    UPDATE chat_messages SET chain_hash = NULL; UPDATE audit_events SET chain_hash = NULL;
  END IF;
END $chain$;
UPDATE users SET active = true, totp_enabled = false, totp_secret = NULL, totp_pending_secret = NULL, totp_secret_enc = NULL, totp_pending_secret_enc = NULL,
                 recovery_code_hashes = NULL, password_hash = :'admin_hash'
  WHERE role = 'admin';
UPDATE users SET active = false, password_hash = 'disabled-in-test-copy', totp_enabled = false,
                 totp_secret = NULL, totp_pending_secret = NULL, totp_secret_enc = NULL, totp_pending_secret_enc = NULL,
                 recovery_code_hashes = NULL
  WHERE role <> 'admin';
"""


def pbkdf2_hash(password: str) -> str:
    import secrets
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 480_000)
    return f'pbkdf2_sha256$480000${salt.hex()}${digest.hex()}'


def masked_history_baseline(env:dict,database:str,source:Path):
    """Fingerprint the new, explicitly masked dataset before runtime guards activate.
    The original backup and its immutable history remain untouched.
    """
    from .chain import CHAINED,GENESIS,row_hash
    grouped={}
    rows=psql(env,"SELECT json_build_object('id',id,'ticket_id',ticket_id,'type',item_type,'after',after_data,'status',status)::text FROM approval_ticket_items ORDER BY id",database)
    for line in rows.splitlines():
        row=json.loads(line)
        if row['status']=='approved':grouped.setdefault(row['ticket_id'],[]).append([row['id'],row['type'],row['after']])
    changes=[]
    for ticket,items in grouped.items():
        digest=hashlib.sha256(json.dumps(items,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()
        changes.append(f"UPDATE audit_events SET description={sql_literal('sha256:'+digest)} WHERE action='ticket_content_fingerprint'AND entity_id={int(ticket)};")
    changes.append("INSERT INTO audit_events(actor,action,entity_type,entity_id,description,created_at)VALUES('system','masked_test_copy','backup',0,"+sql_literal('Masked test dataset; source backup '+source.name+' sha256:'+sha256_of(source))+",CURRENT_TIMESTAMP);")
    psql_transaction(env,'\n'.join(changes),database)
    for table,fields in CHAINED.items():
        rows=psql(env,f"SELECT row_to_json(history)::text FROM(SELECT {','.join(fields)} FROM {table} ORDER BY id)history",database)
        previous=GENESIS;updates=[]
        for line in rows.splitlines():
            row=json.loads(line);previous=row_hash(table,previous,row)
            updates.append(f"UPDATE {table} SET chain_hash={sql_literal(previous)} WHERE id={int(row['id'])};")
        if updates:psql_transaction(env,'\n'.join(updates),database)


def reset_masked_copy_status(cfg: Config, source: Path) -> dict:
    """A masked refresh is a NEW test dataset, not a continuation of old history.
    Preserve the old external proof byte-for-byte, then require a verified backup
    of the new dataset. Live history and its backup status are never reset.
    """
    if cfg.environment != 'test':
        raise SafekeepingError('History reset only runs in the test environment')
    import secrets
    previous = cfg.status_dir / 'status.json'
    old = previous.read_bytes() if previous.exists() else b'{}\n'
    relative = 'test-copy-history/' + now().strftime('%Y%m%dT%H%M%S%fZ') + '-' + secrets.token_hex(6) + '.json'
    archive = cfg.status_dir / relative
    archive.parent.mkdir(parents=True, exist_ok=True)
    with archive.open('xb') as output:
        output.write(old)
        output.flush()
        os.fsync(output.fileno())
    proof = {'time': iso(now()), 'source': source.name, 'source_sha256': sha256_of(source),
             'previous_status_archive': relative, 'previous_status_sha256': hashlib.sha256(old).hexdigest(),
             'requires_verified_backup': True}
    write_status(cfg, chain_anchors=[], last_backup=None, last_drill=None,
                 last_backup_error=None, last_offsite_error=None, masked_test_copy=proof)
    return proof


def make_test_copy(cfg: Config, file: Path | None = None) -> dict:
    """Refuses to run anywhere except the TEST environment."""
    if cfg.environment != 'test':
        raise SafekeepingError('make-test-copy only runs in the test environment (STUDIOOS_ENV=test)')
    password = os.environ.get('STUDIOOS_ADMIN_PASSWORD', '')
    if len(password) < 12:
        raise SafekeepingError('Set STUDIOOS_ADMIN_PASSWORD (12+ characters) for the test copy Admin')
    source = file or next(iter(backups_in(cfg.live_backups)), None)
    if source is None:
        raise SafekeepingError(f'No live backups found in {cfg.live_backups}')
    env = cfg.pg_env()
    test_db = cfg.live_db
    incoming = f'{test_db}_incoming'
    with exclusive_lock(cfg.primary):
        terminate_connections(env, incoming)
        psql(env, f'DROP DATABASE IF EXISTS {quote_ident(incoming)}', 'postgres')
        restore_into_new(env, source, incoming, cfg, prepare_test_copy=True)
        try:
            attachments=check_file_mirror(source.parent,referenced_files(env,incoming))
            if attachments['files_missing']or attachments['files_damaged']:raise SafekeepingError('Test-copy attachments are missing or damaged')
            if referenced_files(env,incoming)and cfg.files_dir is None:raise SafekeepingError('Set FILES_PATH for the test-copy attachments')
            if cfg.files_dir is not None and (source.parent/'files').is_dir():
                restored=restore_files(source.parent,cfg.files_dir,full_root=cfg.files_are_root)
                if not restored['ok']:raise SafekeepingError('Test-copy attachment restore did not verify')
        except (SafekeepingError,OSError):
            psql(env,f'DROP DATABASE IF EXISTS {quote_ident(incoming)}','postgres');raise
        proc = subprocess.run(['psql', '-X', '-q', '-v', 'ON_ERROR_STOP=1', '-v', 'admin_hash=' + pbkdf2_hash(password),
                               '-d', incoming, '-1'], input=MASKING_SQL, env=env, capture_output=True, text=True)
        if proc.returncode != 0:
            psql(env, f'DROP DATABASE IF EXISTS {quote_ident(incoming)}', 'postgres')
            raise SafekeepingError('Masking failed; test copy not replaced: ' + proc.stderr.strip()[-300:])
        try:
            masked_history_baseline(env,incoming,source)
            run(['pg_restore','--no-owner','--no-privileges','--exit-on-error','--single-transaction','--section=post-data','--dbname='+incoming,str(source)],env,timeout=6*3600)
            psql(env,'ANALYZE',incoming)
            unbalanced=psql(env,"SELECT count(*) FROM(SELECT journal_id FROM gl_lines GROUP BY journal_id HAVING sum(CASE WHEN side='debit'THEN amount_paise ELSE -amount_paise END)<>0)bad",incoming)
            if unbalanced!='0':raise SafekeepingError('Masked test ledger is unbalanced; test copy not replaced')
        except SafekeepingError:
            psql(env,f'DROP DATABASE IF EXISTS {quote_ident(incoming)}','postgres');raise
        terminate_connections(env, test_db)
        psql(env, f'DROP DATABASE IF EXISTS {quote_ident(test_db)}', 'postgres')
        psql(env, f'ALTER DATABASE {quote_ident(incoming)} RENAME TO {quote_ident(test_db)}', 'postgres')
        reset_masked_copy_status(cfg, source)
        return {'time': iso(now()), 'source': source.name, 'test_database': test_db,
                'masked': ['mobile numbers, GSTINs and email addresses in every text field',
                           'chat messages and summaries', 'new-data inbox source text',
                           'sessions and sign-in attempts'],
                'accounts': 'Only the Admin can sign in, with the test password; two-factor is off; all staff accounts are disabled.'}


# ----------------------------------------------------------------- service loop

def due(last_iso: str | None, hours: int) -> bool:
    if not last_iso:
        return True
    try:
        last = dt.datetime.fromisoformat(last_iso)
    except ValueError:
        return True
    return now() - last >= dt.timedelta(hours=hours) - dt.timedelta(minutes=2)


def service(cfg: Config, once: bool = False) -> None:
    print(f'StudioOS safekeeping: backup every {cfg.interval_hours} h, restore test every {cfg.drill_every_hours} h, '
          f'off-NAS copy {"ON -> " + str(cfg.offsite) if cfg.offsite else "NOT CONFIGURED"}', flush=True)
    while True:
        status = read_status(cfg)
        write_status(cfg, heartbeat=iso(now()))
        if due((status.get('last_backup') or {}).get('time'), cfg.interval_hours):
            try:
                r = backup(cfg)
                print(f"backup ok: {r['file']} ({r['size_bytes']} bytes, {r['rows_total']} rows); off-NAS: {r['offsite']}", flush=True)
            except Exception as err:  # keep the service alive and report it
                write_status(cfg, last_backup_error={'time': iso(now()), 'error': str(err)[:400]})
                print('BACKUP FAILED:', err, flush=True)
        status = read_status(cfg)
        if status.get('last_backup') and due((status.get('last_drill') or {}).get('time'), cfg.drill_every_hours):
            try:
                r = drill(cfg)
                print(f"restore test {'ok' if r['ok'] else 'FAILED'}: {r.get('file')} {r.get('error') or ''}", flush=True)
            except Exception as err:
                write_status(cfg, last_drill={'time': iso(now()), 'ok': False, 'error': str(err)[:400]})
                print('RESTORE TEST FAILED:', err, flush=True)
        if once:
            return
        time.sleep(300)


# ----------------------------------------------------------------- CLI

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='python -m studioos.safekeeping', description='StudioOS backups and restores')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('run', help='service loop')
    b = sub.add_parser('backup'); b.add_argument('--label')
    d = sub.add_parser('drill'); d.add_argument('--file')
    sub.add_parser('status'); sub.add_parser('list')
    rc = sub.add_parser('restore-copy'); rc.add_argument('--file', required=True); rc.add_argument('--into', required=True)
    sw = sub.add_parser('swap-in'); sw.add_argument('--file', required=True); sw.add_argument('--confirm-live-replace', action='store_true')
    tc = sub.add_parser('make-test-copy'); tc.add_argument('--file')
    rf = sub.add_parser('restore-files', help='copy attached files back from a backup folder')
    rf.add_argument('--source', required=True, help='backup folder, e.g. /backups/primary or /backups/offsite')
    rf.add_argument('--target', help='attachment folder (default: STUDIOOS_INBOX_DIR)')
    args = parser.parse_args(argv)
    cfg = Config()

    def resolve(name):
        p = Path(name)
        if not p.is_absolute():
            for folder in (cfg.primary, cfg.offsite, cfg.live_backups):
                if folder and (folder / name).exists():
                    return folder / name
        if not p.exists():
            raise SafekeepingError(f'Backup file not found: {name}')
        return p

    try:
        if args.command == 'run':
            service(cfg); return 0
        if args.command == 'backup':
            out = backup(cfg, args.label)
        elif args.command == 'drill':
            out = drill(cfg, resolve(args.file) if args.file else None)
        elif args.command == 'status':
            out = read_status(cfg)
        elif args.command == 'list':
            out = [{'file': p.name, 'size_bytes': p.stat().st_size, 'created_at': iso(parse_stamp(p.name))} for p in backups_in(cfg.primary)]
        elif args.command == 'restore-copy':
            out = restore_copy(cfg, resolve(args.file), args.into)
        elif args.command == 'swap-in':
            out = swap_in(cfg, resolve(args.file), args.confirm_live_replace)
        elif args.command == 'restore-files':
            target = Path(args.target) if args.target else cfg.files_dir
            if target is None:
                raise SafekeepingError('Give --target or set STUDIOOS_INBOX_DIR')
            out = restore_files(Path(args.source), target,full_root=cfg.files_are_root and not args.target)
        else:
            out = make_test_copy(cfg, resolve(args.file) if args.file else None)
    except SafekeepingError as err:
        print('ERROR:', err, file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2))
    return 0 if not (isinstance(out, dict) and out.get('ok') is False) else 1


if __name__ == '__main__':
    sys.exit(main())

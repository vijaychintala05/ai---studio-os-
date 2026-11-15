"""Verifiable offline backup/restore commands. Run as `python -m studioos.backup ...`.

SQLite uses SQLite's transactional backup API; never copy a live SQLite database
file with a plain `cp`. PostgreSQL requires pg_dump and supports backup here;
restore to a separate database is deliberately left to the administrator.
"""
from __future__ import annotations
import argparse
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from datetime import datetime,timezone
from sqlalchemy.engine.url import make_url

def sqlite_path():
    url=make_url(os.getenv('DATABASE_URL','sqlite:///./data/studioos.db'))
    if not url.drivername.startswith('sqlite'): return None
    return Path(url.database).resolve()

def backup_sqlite(source:Path,target:Path):
    if not source.is_file(): raise FileNotFoundError(f'Database not found: {source}')
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists(): raise FileExistsError('Backup already exists; choose a unique destination')
    with sqlite3.connect(str(source)) as src,sqlite3.connect(str(target)) as dest:
        src.backup(dest)
        check=dest.execute('PRAGMA integrity_check').fetchone()[0]
        if check!='ok':raise RuntimeError('Backup integrity check failed: '+check)
    return {'backup':str(target),'bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'integrity':'ok'}

def restore_sqlite(source:Path,target:Path):
    if not source.is_file():raise FileNotFoundError('Backup not found')
    if target.exists():raise FileExistsError('Refusing to overwrite any database; restore to a NEW path')
    with sqlite3.connect(str(source)) as src:
        if src.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Backup is not valid SQLite')
    target.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(str(source)) as src,sqlite3.connect(str(target)) as dest:
        src.backup(dest)
        if dest.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Restored database failed integrity check')
    return {'restored_to':str(target),'integrity':'ok'}

def _major(text):
    """Major version from 'pg_dump (PostgreSQL) 16.4 (Debian ...)'."""
    import re
    m=re.search(r'\(PostgreSQL\)\s+(\d+)',text or '')
    return int(m.group(1)) if m else None

def check_pg_dump_version(env):
    """pg_dump must be the same major version as the server or newer, or the
    backup can fail or be incomplete. Refuse early instead (v0.7.0)."""
    out=subprocess.run(['pg_dump','--version'],capture_output=True,text=True,env=env)
    tool=_major(out.stdout)
    srv=subprocess.run(['psql','-X','-At','-c','SHOW server_version_num'],capture_output=True,text=True,env=env)
    if srv.returncode!=0:raise RuntimeError('Cannot reach PostgreSQL to check its version: '+srv.stderr.strip()[-200:])
    server=int(srv.stdout.strip())//10000
    if tool is None or tool<server:
        raise RuntimeError(f'pg_dump {tool} is older than PostgreSQL {server}; install postgresql-client-{server} or newer before upgrading')
    return {'pg_dump':tool,'server':server}

def backup_postgres(target:Path):
    """Verified pre-migration snapshot. The password goes through the environment,
    never the command line, and the file must be readable by pg_restore."""
    from .safekeeping import Config, sha256_of
    if target.exists():raise FileExistsError('Backup destination exists')
    if not shutil.which('pg_dump'):raise RuntimeError('pg_dump is not installed')
    env=Config().pg_env()
    versions=check_pg_dump_version(env)
    target.parent.mkdir(parents=True,exist_ok=True)
    partial=target.with_name(target.name+'.partial')
    try:
        subprocess.run(['pg_dump','--format=custom','--no-owner','--no-privileges','--file='+str(partial)],check=True,env=env)
        subprocess.run(['pg_restore','--list',str(partial)],check=True,env=env,capture_output=True)
        os.replace(partial,target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return {'backup':str(target),'bytes':target.stat().st_size,'format':'PostgreSQL custom pg_dump',
            'sha256':sha256_of(target),'verified':True,**versions}

def main():
    import json
    parser=argparse.ArgumentParser(description='StudioOS database backup and isolated restore')
    sub=parser.add_subparsers(dest='command',required=True)
    b=sub.add_parser('backup');b.add_argument('--output',required=True)
    r=sub.add_parser('restore');r.add_argument('--backup',required=True);r.add_argument('--target',required=True)
    args=parser.parse_args()
    path=sqlite_path()
    if args.command=='backup':out=backup_sqlite(path,Path(args.output)) if path else backup_postgres(Path(args.output))
    elif path:out=restore_sqlite(Path(args.backup),Path(args.target))
    else:raise SystemExit('Use pg_restore to a separate PostgreSQL database after verifying the backup; this tool never replaces a live database.')
    print(json.dumps(out,indent=2))

if __name__=='__main__':main()

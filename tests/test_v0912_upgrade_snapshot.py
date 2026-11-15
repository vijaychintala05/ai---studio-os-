"""v18→19 verified SQLite snapshot and fail-closed migration rehearsal.
Real PostgreSQL/Docker restore is a separate release gate.
"""
import sqlite3
from studioos.backup import restore_sqlite
from .test_v098_upgrade_snapshot import run_version, NEW
from studioos.migrations import LATEST_VERSION

NEW_TABLES={'universal_document_definition_revisions','universal_document_issues'}


def seed_v18(tmp_path):
    src=tmp_path/'fictional_v18.sqlite'
    code='''from studioos.db import Base,engine,SessionLocal,Project
from sqlalchemy import text
for t in Base.metadata.sorted_tables:
    if t.name not in {'universal_document_definition_revisions','universal_document_issues'}:
        t.create(engine,checkfirst=True)
with engine.begin() as c:
    c.execute(text("INSERT INTO schema_migrations(version,description,applied_at) VALUES (18,'Fictional v18',CURRENT_TIMESTAMP)"))
with SessionLocal() as db:
    db.add(Project(name='Fictional retained v18 project',budget_paise=420000))
    db.commit()
'''
    r=run_version(NEW,src,tmp_path/'no-op',code)
    assert r.returncode==0,r.stderr
    return src


def test_v19_snapshot_verified_and_restore(tmp_path):
    source=seed_v18(tmp_path);backup_dir=tmp_path/'safe-backups'
    run=run_version(NEW,source,backup_dir,'from studioos.db import init_db; init_db()')
    assert run.returncode==0,run.stderr
    with sqlite3.connect(source) as db:
        assert db.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]==LATEST_VERSION>=22
        assert db.execute('SELECT name FROM projects').fetchone()[0]=='Fictional retained v18 project'
        for name in NEW_TABLES:
            assert db.execute('SELECT name FROM sqlite_master WHERE type="table" AND name=?',(name,)).fetchone()
    backups=list(backup_dir.glob('*.sqlite3'))
    assert len(backups)==1
    recovered=tmp_path/'recovered.sqlite'
    assert restore_sqlite(backups[0],recovered)['integrity']=='ok'
    with sqlite3.connect(recovered) as db:
        assert db.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]==18
        assert db.execute('SELECT name FROM projects').fetchone()[0]=='Fictional retained v18 project'
        for name in NEW_TABLES:
            assert db.execute('SELECT name FROM sqlite_master WHERE type="table" AND name=?',(name,)).fetchone() is None


def test_v19_failed_backup_blocks_upgrade(tmp_path):
    source=seed_v18(tmp_path)
    blocked=tmp_path/'not-a-directory';blocked.write_text('fictional sabotage')
    result=run_version(NEW,source,blocked,'from studioos.db import init_db; init_db()')
    assert result.returncode!=0
    with sqlite3.connect(source) as db:
        assert db.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]==18
        for name in NEW_TABLES:
            assert db.execute('SELECT name FROM sqlite_master WHERE type="table" AND name=?',(name,)).fetchone() is None

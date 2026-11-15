"""Safe upgrade from v14 to current infrastructure version, using fictional SQLite.
This is NOT real PostgreSQL or NAS restore certification.
"""
import sqlite3
from pathlib import Path
from studioos.backup import restore_sqlite
from studioos.migrations import LATEST_VERSION
from .test_v098_upgrade_snapshot import run_version, NEW

NEW_TABLES={'universal_saved_views','universal_workflows','universal_workflow_notices',
            'finance_reversals','finance_advance_policies','finance_supplier_advances',
            'finance_advance_allocations'}


def _make_v14(tmp_path):
    target=tmp_path/'fictional_v14.sqlite'
    script='''from studioos.db import Base,engine,SessionLocal,Project
from sqlalchemy import text
skip={"universal_saved_views","universal_workflows","universal_workflow_notices",
      "finance_reversals","finance_advance_policies","finance_supplier_advances","finance_advance_allocations"}
for table in Base.metadata.sorted_tables:
    if table.name not in skip:table.create(engine,checkfirst=True)
with engine.begin() as conn:
    conn.execute(text("INSERT INTO schema_migrations(version,description,applied_at) VALUES (14,'Fictional v14 baseline',CURRENT_TIMESTAMP)"))
with SessionLocal() as db:
    db.add(Project(name='Fictional V14 Building',budget_paise=500000));db.commit()
'''
    r=run_version(NEW,target,tmp_path/'old-snaps',script)
    assert r.returncode==0,r.stderr
    with sqlite3.connect(target) as c:
        assert c.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]==14
        for t in NEW_TABLES:
            assert not c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(t,)).fetchone()
    return target


def test_upgrade_v14_to_current_verified_snapshot_restore(tmp_path):
    db=_make_v14(tmp_path)
    snaps=tmp_path/'snapshots'
    r=run_version(NEW,db,snaps,'from studioos.db import init_db; init_db()')
    assert r.returncode==0,r.stderr
    with sqlite3.connect(db) as c:
        assert c.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]==LATEST_VERSION
        assert c.execute('SELECT name FROM projects').fetchone()[0]=='Fictional V14 Building'
        for t in NEW_TABLES:
            assert c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(t,)).fetchone()
    images=list(snaps.glob('*.sqlite3'))
    assert len(images)==1
    with sqlite3.connect(images[0]) as c:
        assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert c.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]==14
    restored=tmp_path/'recovered_v14.sqlite'
    assert restore_sqlite(images[0],restored)['integrity']=='ok'
    with sqlite3.connect(restored) as c:
        assert c.execute('SELECT name FROM projects').fetchone()[0]=='Fictional V14 Building'
        for t in NEW_TABLES:
            assert not c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(t,)).fetchone()


def test_backup_failure_blocks_v16_upgrade(tmp_path):
    db=_make_v14(tmp_path)
    blocked=tmp_path/'blocked-directory'
    blocked.write_text('not a folder')
    r=run_version(NEW,db,blocked,'from studioos.db import init_db; init_db()')
    assert r.returncode!=0
    with sqlite3.connect(db) as c:
        assert c.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]==14
        assert c.execute('SELECT name FROM projects').fetchone()[0]=='Fictional V14 Building'
        for t in NEW_TABLES:
            assert not c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(t,)).fetchone()

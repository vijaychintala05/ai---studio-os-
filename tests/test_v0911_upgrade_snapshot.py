"""v17→18 controlled SQLite upgrade and fail-closed snapshot rehearsal.
Cannot substitute for a real PostgreSQL production restore."""
import sqlite3
from studioos.backup import restore_sqlite
from .test_v098_upgrade_snapshot import run_version, NEW
from studioos.migrations import LATEST_VERSION

NEW_TABLES={'universal_calculations','universal_document_templates'}


def seed_v17(tmp_path):
    path=tmp_path/'fictional_v17.sqlite'
    code='''from studioos.db import Base, engine, SessionLocal, Project
from sqlalchemy import text
for t in Base.metadata.sorted_tables:
    if t.name not in {'universal_calculations','universal_document_templates'}:
        t.create(engine, checkfirst=True)
with engine.begin() as c:
    c.execute(text("INSERT INTO schema_migrations(version,description,applied_at) VALUES (17,'Fictional schema v17',CURRENT_TIMESTAMP)"))
with SessionLocal() as db:
    db.add(Project(name='Fictional retained project v17',budget_paise=600000));db.commit()
'''
    r=run_version(NEW,path,tmp_path/'before-initial',code)
    assert r.returncode==0,r.stderr
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]==17
        for t in NEW_TABLES:
            assert db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(t,)).fetchone() is None
    return path


def test_v17_upgrade_takes_verified_snapshot_and_restores(tmp_path):
    src=seed_v17(tmp_path);snaps=tmp_path/'v18-snapshots'
    r=run_version(NEW,src,snaps,'from studioos.db import init_db; init_db()')
    assert r.returncode==0,r.stderr
    with sqlite3.connect(src) as db:
        assert db.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]==LATEST_VERSION>=22
        assert db.execute('SELECT name FROM projects').fetchone()[0]=='Fictional retained project v17'
        for table in NEW_TABLES:
            assert db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
    images=list(snaps.glob('*.sqlite3'));assert len(images)==1
    recovered=tmp_path/'restored_to_v17.sqlite'
    assert restore_sqlite(images[0],recovered)['integrity']=='ok'
    with sqlite3.connect(recovered) as db:
        assert db.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]==17
        assert db.execute('SELECT name FROM projects').fetchone()[0]=='Fictional retained project v17'
        for table in NEW_TABLES:
            assert db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone() is None


def test_v18_snapshot_failure_blocks_ddl(tmp_path):
    src=seed_v17(tmp_path)
    notdir=tmp_path/'not_a_directory';notdir.write_text('Cannot use as snapshot destination')
    r=run_version(NEW,src,notdir,'from studioos.db import init_db; init_db()')
    assert r.returncode!=0
    with sqlite3.connect(src) as db:
        assert db.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]==17
        assert db.execute('SELECT name FROM projects').fetchone()[0]=='Fictional retained project v17'
        for table in NEW_TABLES:
            assert db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone() is None

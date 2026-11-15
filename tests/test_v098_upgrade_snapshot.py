"""v13→v14 fictional upgrade / restore rehearsal. Uses real v0.9.7 sibling source when
provided locally, otherwise builds synthetic pre-v14 schema from ORM for standalone CI.
Neither proves PostgreSQL or production NAS reliability.
"""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from studioos.backup import restore_sqlite
from studioos.migrations import LATEST_VERSION

OLD=Path(__file__).resolve().parents[2]/'studioos-v097-evolving'
NEW=Path(__file__).resolve().parents[1]


def run_version(src,db,snapshots,code,extra=None):
    env=dict(os.environ,DATABASE_URL='sqlite:///'+str(db),PYTHONPATH=str(src),
             STUDIOOS_ENV='test',STUDIOOS_SNAPSHOTS_DIR=str(snapshots),
             STUDIOOS_HOOK_LOG_DIR=str(snapshots.parent/'hooks'),
             STUDIOOS_ADMIN_PASSWORD='fictional-isolated-test-strong-password')
    if extra:env.update(extra)
    return subprocess.run([sys.executable,'-c',code],cwd=src,env=env,capture_output=True,text=True,timeout=50)


def old_db(tmp_path):
    db=tmp_path/'legacy_v097.sqlite'
    # When the actual v0.9.7 sibling source tree is available, exercise it.
    # Standalone ZIP / CI still gets a self-contained *synthetic* v13 schema
    # by creating exactly the pre-v14 tables from the tested ORM metadata.
    if (OLD/'studioos'/'db.py').exists():
        cmd="""from studioos.db import init_db,SessionLocal,Project
init_db()
with SessionLocal() as s:
    s.add(Project(name='Fictional Migrated Project',budget_paise=1000000));s.commit()
"""
        r=run_version(OLD,db,tmp_path/'old-snaps',cmd)
    else:
        cmd="""from sqlalchemy import create_engine,text
from studioos.db import Base,SessionLocal,Project
from studioos.migrations import LATEST_VERSION
from studioos.db import engine
new_tables={'universal_relationship_types','universal_edges','universal_metadata_versions',
  'universal_record_revisions','accounting_entities','gl_accounts','accounting_policies',
  'registered_banks','finance_purchase_orders','finance_supplier_bills',
  'finance_supplier_payments','gl_journals','gl_lines','closed_accounting_periods',
  'universal_saved_views','universal_workflows','universal_workflow_notices',
  'finance_reversals','finance_advance_policies','finance_supplier_advances','finance_advance_allocations'}
for table in Base.metadata.sorted_tables:
    if table.name not in new_tables:table.create(engine,checkfirst=True)
with engine.begin() as con:
    con.execute(text("INSERT INTO schema_migrations(version, description, applied_at) VALUES (13,'Fictional synthetic v13',CURRENT_TIMESTAMP)"))
with SessionLocal() as s:
    s.add(Project(name='Fictional Migrated Project',budget_paise=1000000));s.commit()
"""
        r=run_version(NEW,db,tmp_path/'old-snaps',cmd)
    assert r.returncode==0,r.stderr
    with sqlite3.connect(db) as x:
        assert x.execute('select max(version) from schema_migrations').fetchone()[0]==13
        assert not x.execute("select name from sqlite_master where type='table' and name='gl_journals'").fetchone()
    return db


def test_v097_upgrade_v14_preserves_data_and_verified_snapshot(tmp_path):
    db=old_db(tmp_path);snapshots=tmp_path/'v14-snaps'
    r=run_version(NEW,db,snapshots,'from studioos.db import init_db; init_db()')
    assert r.returncode==0,r.stderr
    with sqlite3.connect(db) as x:
        assert x.execute('select max(version) from schema_migrations').fetchone()[0]==LATEST_VERSION
        assert x.execute('select name from projects').fetchone()[0]=='Fictional Migrated Project'
        assert x.execute("select count(*) from sqlite_master where type='table' and name='gl_journals'").fetchone()[0]==1
    shots=list(snapshots.glob('*.sqlite3'))
    assert len(shots)==1
    with sqlite3.connect(shots[0]) as x:
        assert x.execute('pragma integrity_check').fetchone()[0]=='ok'
        assert x.execute('select max(version) from schema_migrations').fetchone()[0]==13
    restored=tmp_path/'restored_v097.sqlite'
    assert restore_sqlite(shots[0],restored)['integrity']=='ok'
    with sqlite3.connect(restored) as x:
        assert x.execute('select name from projects').fetchone()[0]=='Fictional Migrated Project'
    assert any('before_schema_migration' in ln and 'verified' in ln for ln in
               (tmp_path/'hooks'/'events.jsonl').read_text().splitlines())


def test_failed_snapshot_blocks_v14_upgrade(tmp_path):
    db=old_db(tmp_path)
    blocked=tmp_path/'not_a_directory'
    blocked.write_text('Prevent snapshots in this fictional rehearsal')
    r=run_version(NEW,db,blocked,'from studioos.db import init_db; init_db()')
    assert r.returncode!=0
    with sqlite3.connect(db) as x:
        assert x.execute('select max(version) from schema_migrations').fetchone()[0]==13
        assert x.execute("select count(*) from sqlite_master where type='table' and name='gl_journals'").fetchone()[0]==0

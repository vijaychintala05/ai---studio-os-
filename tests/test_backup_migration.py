import sqlite3
import pytest
from sqlalchemy import create_engine,inspect
from studioos.backup import backup_sqlite,restore_sqlite
from studioos.migrations import LATEST_VERSION, apply_migrations

def test_sqlite_backup_restore_roundtrip(tmp_path):
    src=tmp_path/'working.db';target=tmp_path/'backup.db';restored=tmp_path/'restored.db'
    with sqlite3.connect(src) as db:
        db.execute('create table important (id integer primary key, amount integer not null)')
        db.execute('insert into important (amount) values (925000)')
    info=backup_sqlite(src,target)
    assert info['integrity']=='ok' and len(info['sha256'])==64
    assert restore_sqlite(target,restored)['integrity']=='ok'
    with sqlite3.connect(restored) as db:assert db.execute('select amount from important').fetchone()[0]==925000
    try:restore_sqlite(target,restored)
    except FileExistsError:pass
    else:raise AssertionError('Restore must refuse to overwrite an existing database')

@pytest.mark.parametrize('populated', [False, True])
def test_migrate_legacy_v01_database(tmp_path, populated):
    filename=tmp_path/'legacy.db'
    with sqlite3.connect(filename) as db:
        db.execute('create table costs (id integer primary key, project_id integer, kind varchar(20), title varchar(400), vendor varchar(200), amount_paise bigint, created_at datetime)')
        if populated:
            db.execute("insert into costs (project_id,kind,title,vendor,amount_paise) values (1,'expense','old expense','',10000)")
        db.execute('create table payments (id integer primary key,project_id integer,cost_id integer,amount_paise bigint,created_at datetime)')
        db.execute('create table chat_sessions (id varchar(70) primary key,pending json,created_at datetime)')
    e=create_engine('sqlite:///'+str(filename))
    try:
        if populated:
            with pytest.raises(RuntimeError, match='Old tracker entries were found'):
                apply_migrations(e)
            assert set(inspect(e).get_table_names()) == {'costs', 'payments', 'chat_sessions'}
            with sqlite3.connect(filename) as db:
                assert db.execute('select title, amount_paise from costs').fetchall() == [('old expense', 10000)]
        else:
            apply_migrations(e)
            schema = inspect(e)
            columns = {col['name'] for col in schema.get_columns('payments')}
            assert {'status', 'idempotency_key'} <= columns
            cost_status = next(col for col in schema.get_columns('costs') if col['name'] == 'status')
            assert cost_status['default'] == "'approved'"
            apply_migrations(e)
            with sqlite3.connect(filename) as db:
                assert db.execute('select version from schema_migrations order by version').fetchall() == [
                    (version,) for version in range(1, LATEST_VERSION + 1)
                ]
    finally:
        e.dispose()

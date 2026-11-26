"""Relational upgrades preserve records and reject unexpected tracker data."""
from contextlib import ExitStack
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateSchema, DropSchema

from studioos.db import Base, Project, SchemaMigration, SessionLocal, engine as app_engine
from studioos.migrations import LATEST_VERSION, apply_migrations


@pytest.fixture
def migration_engines(monkeypatch):
    monkeypatch.setattr('studioos.migrations.before_schema_migration', lambda *_: None)
    def drop_schema(name):
        with app_engine.begin() as conn:
            conn.execute(DropSchema(name, cascade=True))

    with ExitStack() as cleanup:
        engines = []
        for _ in range(2):
            if app_engine.dialect.name == 'postgresql':
                name = f'fictional_project_upgrade_{uuid4().hex}'
                with app_engine.begin() as conn:
                    conn.execute(CreateSchema(name))
                cleanup.callback(drop_schema, name)
                engine = create_engine(app_engine.url, connect_args={'options': f'-csearch_path={name}'})
            else:
                engine = create_engine('sqlite://')
            cleanup.callback(engine.dispose)
            engines.append(engine)
        yield tuple(engines)


@pytest.fixture
def schemas(migration_engines):
    old, fresh = migration_engines
    timestamp = 'TIMESTAMP WITH TIME ZONE' if old.dialect.name == 'postgresql' else 'DATETIME'
    with old.begin() as conn:
        conn.exec_driver_sql(f'CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, description TEXT, applied_at {timestamp})')
        conn.exec_driver_sql("INSERT INTO schema_migrations VALUES (62, 'Previous version', CURRENT_TIMESTAMP)")
        conn.exec_driver_sql(f"""
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY, name VARCHAR(200) NOT NULL,
                client VARCHAR(200) NOT NULL, stage VARCHAR(100) NOT NULL,
                budget_paise BIGINT NOT NULL, created_at {timestamp} NOT NULL,
                client_phone VARCHAR(10) NOT NULL, location VARCHAR(200) NOT NULL,
                start_date VARCHAR(30) NOT NULL, deleted_at {timestamp}
            )
        """)
        conn.exec_driver_sql('CREATE UNIQUE INDEX ix_projects_name ON projects(name)')
    return old, fresh


def _project_structure(engine):
    schema = inspect(engine)
    return (
        {c['name']: (c['type'].compile(dialect=engine.dialect), c['nullable'])
         for c in schema.get_columns('projects') if c['name'] != 'id'},
        {tuple(fk['constrained_columns']): fk['referred_table'] for fk in schema.get_foreign_keys('projects')},
        {i['name']: tuple(i['column_names']) for i in schema.get_indexes('projects')},
    )


def _add_project(conn):
    conn.exec_driver_sql("""
        INSERT INTO projects VALUES
        (1, 'Fictional Lake House', 'Fictional Client', 'Planning', 0, CURRENT_TIMESTAMP, '', '', '', NULL)
    """)


def test_v63_upgrade_matches_fresh_projects_schema(schemas):
    old, fresh = schemas
    with old.begin() as conn:
        _add_project(conn)
    apply_migrations(fresh)
    apply_migrations(old)
    apply_migrations(old)

    assert _project_structure(old) == _project_structure(fresh)
    columns, foreign_keys, indexes = _project_structure(old)
    assert columns['company_id'] == columns['client_id'] == ('INTEGER', True)
    assert foreign_keys == {('company_id',): 'accounting_entities', ('client_id',): 'parties'}
    assert indexes['ix_projects_company_id'] == ('company_id',)
    assert indexes['ix_projects_client_id'] == ('client_id',)
    with old.connect() as conn:
        assert conn.scalar(text('SELECT COUNT(*) FROM schema_migrations WHERE version = 63')) == 1
        assert conn.execute(text('SELECT client, company_id, client_id FROM projects')).one() == ('Fictional Client', None, None)


@pytest.mark.parametrize('legacy_mapping', [False, True])
def test_v63_stops_before_schema_changes_when_old_links_need_review(schemas, legacy_mapping):
    old, _ = schemas
    with old.begin() as conn:
        _add_project(conn)
        if legacy_mapping:
            conn.exec_driver_sql('CREATE TABLE finance_project_companies (id INTEGER PRIMARY KEY)')
            conn.exec_driver_sql('INSERT INTO finance_project_companies VALUES (1)')
        else:
            conn.exec_driver_sql('CREATE TABLE accounting_entities (id INTEGER PRIMARY KEY)')
            conn.exec_driver_sql('INSERT INTO accounting_entities VALUES (1)')

    with pytest.raises(RuntimeError, match='This upgrade expected no project data yet'):
        apply_migrations(old)
    assert 'company_id' not in _project_structure(old)[0]
    with old.connect() as conn:
        assert conn.scalar(text('SELECT MAX(version) FROM schema_migrations')) == 62


def test_schema_versions_unique_and_in_order(client):
    with app_engine.connect() as conn:
        versions = conn.scalars(text('SELECT version FROM schema_migrations ORDER BY version')).all()
    assert versions == list(range(1, LATEST_VERSION + 1))


@pytest.mark.parametrize('column', ['company_id', 'client_id'])
def test_foreign_keys_enforced(client, column):
    with SessionLocal() as db:
        db.add(Project(name='Fictional Project With An Invalid Link', **{column: 987654321}))
        with pytest.raises(IntegrityError, match=r'(?i)foreign key'):
            db.flush()
        db.rollback()


@pytest.mark.parametrize('table', ['costs', 'payments', 'financial_adjustments', 'payment_reversals'])
def test_v65_empty_data_check_stops_on_tracker_rows(migration_engines, monkeypatch, table):
    old, _ = migration_engines
    with old.begin() as conn:
        SchemaMigration.__table__.create(conn)
        conn.execute(text("INSERT INTO schema_migrations VALUES (64, 'Previous version', CURRENT_TIMESTAMP)"))
        conn.exec_driver_sql(f'CREATE TABLE {table} (id INTEGER PRIMARY KEY)')
        conn.exec_driver_sql(f'INSERT INTO {table} VALUES (42)')

    def unexpected_snapshot(*_):
        pytest.fail('The cut-over must stop before starting the migration snapshot')

    monkeypatch.setattr('studioos.migrations.before_schema_migration', unexpected_snapshot)
    with pytest.raises(RuntimeError, match=r'Old tracker entries were found\. Stop and tell the developer\.'):
        apply_migrations(old)

    assert set(inspect(old).get_table_names()) == {'schema_migrations', table}
    with old.connect() as conn:
        assert conn.scalar(text('SELECT MAX(version) FROM schema_migrations')) == 64
        assert conn.scalar(text(f'SELECT id FROM {table}')) == 42


def test_v65_upgrade_matches_fresh_database(migration_engines):
    old, fresh = migration_engines
    Base.metadata.create_all(old)
    with old.begin() as conn:
        conn.execute(text("INSERT INTO schema_migrations VALUES (64, 'Previous version', CURRENT_TIMESTAMP)"))
        conn.execute(Project.__table__.insert().values(name='Fictional Cut-over Project'))
    apply_migrations(old)
    apply_migrations(old)
    apply_migrations(fresh)

    assert set(inspect(old).get_table_names()) == set(inspect(fresh).get_table_names())
    assert _project_structure(old) == _project_structure(fresh)
    for database in (old, fresh):
        with database.connect() as conn:
            assert conn.scalars(text('SELECT version FROM schema_migrations ORDER BY version')).all() == list(range(1, 66))
        for table in ('costs', 'payments', 'financial_adjustments', 'payment_reversals'):
            with database.begin() as conn:
                assert conn.scalar(text(f'SELECT COUNT(*) FROM {table}')) == 0
                if database.dialect.name == 'sqlite':
                    triggers = conn.scalars(text("SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = :table"),
                                            {'table': table}).all()
                    assert {f'guard_{table}_{verb}_read_only' for verb in ('insert', 'update', 'delete')} <= set(triggers)
            operations = [f'INSERT INTO {table} DEFAULT VALUES']
            if database.dialect.name == 'postgresql':
                operations.extend((f'UPDATE {table} SET id = id', f'DELETE FROM {table}'))
            for operation in operations:
                with pytest.raises(IntegrityError, match='The old money tracker is read-only'):
                    with database.begin() as conn:
                        conn.exec_driver_sql(operation)
        if database.dialect.name == 'postgresql':
            with pytest.raises(IntegrityError, match='The old money tracker is read-only'):
                with database.begin() as conn:
                    conn.exec_driver_sql('TRUNCATE costs, payments, financial_adjustments, payment_reversals')
    with old.connect() as conn:
        assert conn.scalars(text('SELECT name FROM projects')).all() == ['Fictional Cut-over Project']

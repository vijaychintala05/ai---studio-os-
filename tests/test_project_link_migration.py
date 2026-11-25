"""The first relational upgrade adds links without moving project records."""
import pytest
from sqlalchemy import create_engine, inspect, text

from studioos.migrations import apply_migrations


@pytest.fixture
def schemas(monkeypatch):
    monkeypatch.setattr('studioos.migrations.before_schema_migration', lambda *_: None)
    old, fresh = create_engine('sqlite://'), create_engine('sqlite://')
    with old.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, description TEXT, applied_at DATETIME)')
        conn.exec_driver_sql("INSERT INTO schema_migrations VALUES (62, 'Previous version', CURRENT_TIMESTAMP)")
        conn.exec_driver_sql("""
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY, name VARCHAR(200) NOT NULL,
                client VARCHAR(200) NOT NULL, stage VARCHAR(100) NOT NULL,
                budget_paise BIGINT NOT NULL, created_at DATETIME NOT NULL,
                client_phone VARCHAR(10) NOT NULL, location VARCHAR(200) NOT NULL,
                start_date VARCHAR(30) NOT NULL, deleted_at DATETIME
            )
        """)
        conn.exec_driver_sql('CREATE UNIQUE INDEX ix_projects_name ON projects(name)')
    try:
        yield old, fresh
    finally:
        old.dispose()
        fresh.dispose()


def _project_structure(engine):
    schema = inspect(engine)
    return (
        {c['name']: (str(c['type']), c['nullable']) for c in schema.get_columns('projects') if c['name'] != 'id'},
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

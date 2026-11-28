"""Test the additive form schema against a fictional pre-v68 database."""
from contextlib import contextmanager
from uuid import uuid4

from sqlalchemy import create_engine, inspect, MetaData, text

from studioos.db import Base, engine
from studioos.migrations import apply_migrations


NEW_TABLES = {'field_rules', 'custom_field_values'}
NEW_COLUMNS = {
    'projects': {'project_code', 'project_type', 'manager', 'end_date', 'description'},
    'tasks': {'priority', 'start_date', 'description'},
    'users': {'email', 'phone', 'designation', 'department', 'joining_date'},
}


@contextmanager
def isolated_engine(tmp_path, label):
    if engine.dialect.name != 'postgresql':
        temporary = create_engine(f'sqlite:///{tmp_path / (label + ".sqlite")}')
        try:
            yield temporary
        finally:
            temporary.dispose()
        return
    # The PostgreSQL test job supplies a disposable database. Isolated schemas
    # let both versions run the real migration without touching other fixtures.
    schema = f'form_v68_{uuid4().hex}'
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA {schema}'))
    temporary = create_engine(engine.url, connect_args={'options': f'-c search_path={schema}'})
    try:
        yield temporary
    finally:
        temporary.dispose()
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))


def table_shape(conn, table):
    inspector = inspect(conn)
    columns = {col['name']: (str(col['type']), col['nullable']) for col in inspector.get_columns(table)}
    unique = {tuple(key['column_names']) for key in inspector.get_unique_constraints(table)}
    indexes = {(tuple(index['column_names']), index['unique']) for index in inspector.get_indexes(table)}
    return columns, unique, indexes


def test_v68_upgrade_matches_fresh_and_preserves_existing_project(tmp_path, monkeypatch):
    # Safekeeping is tested separately. This test never reads backup settings.
    monkeypatch.setattr('studioos.migrations.before_schema_migration', lambda *_: None)
    with isolated_engine(tmp_path, 'upgraded') as upgraded, isolated_engine(tmp_path, 'fresh') as fresh:
        old = MetaData()
        for table in Base.metadata.sorted_tables:
            if table.name not in NEW_TABLES | {'record_attachments'}:
                table.to_metadata(old)
        for table, names in NEW_COLUMNS.items():
            for name in names:
                column = old.tables[table].c.get(name)
                if column is not None:
                    old.tables[table]._columns.remove(column)
        old.create_all(upgraded)
        with upgraded.begin() as conn:
            conn.execute(old.tables['projects'].insert().values(name='Fictional Existing Studio'))
            conn.execute(old.tables['schema_migrations'].insert().values(
                version=67, description='Fictional v67 baseline',
            ))
        apply_migrations(upgraded)
        apply_migrations(fresh)
        with upgraded.connect() as prior, fresh.connect() as clean:
            assert prior.scalar(text('SELECT MAX(version) FROM schema_migrations')) >= 68
            assert prior.scalar(text('SELECT name FROM projects')) == 'Fictional Existing Studio'
            for table in NEW_TABLES | NEW_COLUMNS.keys():
                assert table_shape(prior, table) == table_shape(clean, table)
            for table, names in NEW_COLUMNS.items():
                assert names <= table_shape(prior, table)[0].keys()

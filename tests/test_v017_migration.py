"""v0.17 schema v28 is additive: only new tables, and the version row is recorded once."""
from sqlalchemy import create_engine, inspect, text

from studioos.db import REVIEW_INDEXES, WORK_HISTORY_TABLES, engine
from studioos.migrations import LATEST_VERSION, apply_migrations


def test_v28_tables_and_version(client):
    names = set(inspect(engine).get_table_names())
    assert {'project_stages', 'task_structure', 'task_links', 'work_workflows', 'work_templates', 'project_baselines',
            'work_deletions', 'work_transition_log'} <= names
    assert LATEST_VERSION >= 39
    with engine.connect() as c:
        assert c.execute(text('SELECT COUNT(*) FROM schema_migrations WHERE version=32')).scalar() == 1


def test_review_migration_brings_existing_schema_to_fresh_schema(tmp_path, monkeypatch):
    fresh = create_engine(f'sqlite:///{tmp_path / "fresh.sqlite"}')
    upgraded = create_engine(f'sqlite:///{tmp_path / "upgraded.sqlite"}')
    monkeypatch.setattr('studioos.migrations.before_schema_migration', lambda *_: None)
    try:
        apply_migrations(fresh)
        apply_migrations(upgraded)
        # Reconstruct the previous schema on this empty disposable test database.
        with upgraded.begin() as conn:
            conn.execute(text('DELETE FROM schema_migrations WHERE version=40'))
            conn.execute(text('ALTER TABLE users DROP COLUMN totp_pending_session_hash'))
            for index in REVIEW_INDEXES:
                index.drop(conn)
            for table in WORK_HISTORY_TABLES:
                for operation in ('update', 'delete'):
                    conn.execute(text(f'DROP TRIGGER guard_{table}_{operation}'))
        apply_migrations(upgraded)
        for schema in (fresh, upgraded):
            inspector = inspect(schema)
            assert 'totp_pending_session_hash' in {item['name'] for item in inspector.get_columns('users')}
            for index in REVIEW_INDEXES:
                assert index.name in {item['name'] for item in inspector.get_indexes(index.table.name)}
            with schema.connect() as conn:
                triggers = set(conn.scalars(text("SELECT name FROM sqlite_master WHERE type='trigger'")))
                assert {f'guard_{table}_{op}' for table in WORK_HISTORY_TABLES for op in ('update', 'delete')} <= triggers
                assert conn.scalar(text('SELECT MAX(version) FROM schema_migrations')) == LATEST_VERSION
    finally:
        fresh.dispose()
        upgraded.dispose()

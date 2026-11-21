"""v0.17 schema v28 is additive: only new tables, and the version row is recorded once."""
from sqlalchemy import inspect, text

from studioos.db import engine
from studioos.migrations import LATEST_VERSION


def test_v28_tables_and_version(client):
    names = set(inspect(engine).get_table_names())
    assert {'project_stages', 'task_structure', 'task_links', 'work_workflows', 'work_templates', 'project_baselines',
            'work_deletions', 'work_transition_log'} <= names
    assert LATEST_VERSION == 39   # v38 approval timing and edit history; v39 records the project of an AI correction
    with engine.connect() as c:
        assert c.execute(text('SELECT COUNT(*) FROM schema_migrations WHERE version=32')).scalar() == 1

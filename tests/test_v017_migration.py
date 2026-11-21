"""v0.17 schema v28 is additive: only new tables, and the version row is recorded once."""
from sqlalchemy import inspect, text

from studioos.db import engine
from studioos.migrations import LATEST_VERSION


def test_v28_tables_and_version(client):
    names = set(inspect(engine).get_table_names())
    assert {'project_stages', 'task_structure', 'task_links', 'work_workflows', 'work_templates', 'project_baselines',
            'work_deletions', 'work_transition_log'} <= names
    assert LATEST_VERSION == 36   # v33 PO lines; v34 stored views; v35 encrypted 2FA secret columns; v36 project chat
    with engine.connect() as c:
        assert c.execute(text('SELECT COUNT(*) FROM schema_migrations WHERE version=32')).scalar() == 1

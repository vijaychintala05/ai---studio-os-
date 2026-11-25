"""Every tracked table requires an approved item on ordinary API write paths."""
import pytest
from sqlalchemy import text

from studioos.db import SessionLocal, _TRACKED


def test_no_write_path_without_ticket(admin):
    unguarded = []
    for table in sorted(_TRACKED):
        with SessionLocal() as db:
            db.info['write_source'] = 'api:POST /fictional-direct-write'
            identifier = db.bind.dialect.identifier_preparer.quote(table)
            try:
                # A no-op statement exercises the write guard without changing fixture data.
                db.execute(text(f'DELETE FROM {identifier} WHERE 1 = 0'))
            except PermissionError as exc:
                assert 'approved ticket item' in str(exc), (table, exc)
            else:
                unguarded.append(table)
    assert not unguarded, f'API writes bypass approval on {unguarded}'


@pytest.mark.parametrize(('origin', 'table'), [
    ('api:PUT /api/projects/1/members', 'project_members'),
    ('api:POST /api/projects/1/chat', 'project_chat_messages'),
    ('api:POST /api/portal/1/inbox/seen', 'portal_activity_reads'),
    ('api:GET /api/graph/notices', 'universal_workflow_notices'),
    ('api:POST /api/documents/index-nas', 'documents'),
])
def test_existing_operational_exceptions_are_route_and_table_specific(admin, origin, table):
    with SessionLocal() as db:
        db.info['write_source'] = origin
        db.execute(text(f'DELETE FROM {table} WHERE 1 = 0'))
        with pytest.raises(PermissionError, match='approved ticket item'):
            db.execute(text('DELETE FROM projects WHERE 1 = 0'))
        db.rollback()
    with SessionLocal() as db:
        db.info.update(write_source=origin, ai_origin=True)
        with pytest.raises(PermissionError):
            db.execute(text(f'DELETE FROM {table} WHERE 1 = 0'))

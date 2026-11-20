"""Previewing a draft view (approval ticket and MCP): problems, the changes against the stored version, warnings about the audience, what it
would show, and the owner's preview as another role. Nothing is stored. Fictional data."""
from pathlib import Path

from sqlalchemy import select

from studioos.viewspec_models import ViewSpecRow
from studioos.db import SessionLocal
from tests.conftest import approved_form, write
from tests.test_v018_time_app import staff
from tests.test_v093_mcp_app import call, key, on
from tests.test_viewspec_app import save, task_list

STATIC = Path(__file__).resolve().parent.parent / 'studioos' / 'static'


def preview(client, body):
    return write(client, 'post', '/api/viewspecs/preview', body)


def test_a_draft_previews_with_its_changes_and_what_it_shows(admin):
    p = approved_form(admin, 'post', '/api/projects', {'name': 'Villa Preview Views', 'budget': '100000'}).json()
    approved_form(admin, 'post', '/api/tasks', {'project_id': p['id'], 'title': 'Pour slab', 'assignee': 'X', 'due_date': '2026-12-01'})
    r = preview(admin, {'spec': task_list()}).json()
    assert r['valid'] and r['base_version'] is None and all(d.startswith('added ') for d in r['diff'])
    assert 'Pour slab' in [c for row in r['shown']['result']['rows'] for c in row['cells']]
    save(admin, admin, 'view_create', {'spec': task_list(), 'scope': 'system'})
    again = preview(admin, {'spec': task_list(name='Renamed')}).json()
    assert again['base_version'] == 1 and any('changed name' in d for d in again['diff'])
    bad = preview(admin, {'spec': {**task_list(), 'primitive': 'map'}}).json()
    assert bad['valid'] is False and bad['shown'] is None and bad['errors']
    with SessionLocal() as db:
        assert len(db.scalars(select(ViewSpecRow)).all()) == 1                                  # previews store nothing


def test_a_rollback_previews_the_version_it_would_restore(admin):
    save(admin, admin, 'view_create', {'spec': task_list(), 'scope': 'system'})
    with SessionLocal() as db:
        vid = db.scalar(select(ViewSpecRow.id))
    save(admin, admin, 'view_change', {'view_id': vid, 'base_version': 1, 'spec': task_list(name='Second name')})
    r = preview(admin, {'view_id': vid, 'to_version': 1}).json()
    assert r['valid'] and any("'Second name' -> 'Open tasks'" in d for d in r['diff'])
    assert preview(admin, {'view_id': vid, 'to_version': 9}).status_code == 404 and preview(admin, {}).status_code == 404


def test_the_owner_can_preview_as_a_role_and_nobody_else(admin):
    p = approved_form(admin, 'post', '/api/projects', {'name': 'Villa Role Views', 'budget': '100000'}).json()
    approved_form(admin, 'post', '/api/tasks', {'project_id': p['id'], 'title': 'Pour slab', 'assignee': 'X', 'due_date': '2026-12-01'})
    spec = {**task_list(), 'audience': {'roles': ['manager']}}
    as_site = preview(admin, {'spec': spec, 'as_role': 'site_engineer'}).json()
    assert as_site['as_role'] == 'site_engineer' and any('audience' in w for w in as_site['warnings'])
    assert [c for row in as_site['shown']['result']['rows'] for c in row['cells']] == []          # a site engineer with no projects sees none
    as_mgr = preview(admin, {'spec': spec, 'as_role': 'manager'}).json()
    assert not as_mgr['warnings'] and 'Pour slab' in [c for row in as_mgr['shown']['result']['rows'] for c in row['cells']]
    assert preview(admin, {'spec': spec, 'as_role': 'root'}).status_code == 422 and preview(admin, {'spec': spec, 'as_role': 'client'}).status_code == 422
    mgr, _ = staff(admin, 'mgr.vprev', 'manager')
    try:
        assert preview(mgr, {'spec': spec, 'as_role': 'site_engineer'}).status_code == 403
        assert preview(mgr, {'spec': spec}).status_code == 200
    finally:
        mgr.close()


def test_the_mcp_preview_tool_is_read_only(admin, monkeypatch):
    on(monkeypatch)
    t = key(admin).json()['token']                                                              # a read-only key
    r = call(admin, t, 'preview_view', {'spec': task_list()})
    assert r['isError'] is False and r['structuredContent']['valid'] and r['structuredContent']['sample']['kind'] == 'table'
    assert 'approval ticket' in r['content'][0]['text']
    bad = call(admin, t, 'preview_view', {'spec': {**task_list(), 'script': 'x'}})
    assert bad['structuredContent']['valid'] is False
    with SessionLocal() as db:
        assert db.scalars(select(ViewSpecRow)).all() == []


def test_the_ticket_page_shows_a_preview_for_view_items():
    js = (STATIC / 'newwork.js').read_text(encoding='utf-8')
    assert "startsWith('view_')" in js and '/api/viewspecs/preview' in js and 'data-vp=' in js and 'vp-role' in js

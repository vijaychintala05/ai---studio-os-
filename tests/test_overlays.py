"""Overlays: search is scoped and role-safe, the chat starts narrowed to the project in view, preview as role is owner-only, and the overlay
files are wired with no inline styles. Fictional data."""
import re
from pathlib import Path

from sqlalchemy import select

from studioos.db import ApprovalTicketItem, FlexibleRecord, SessionLocal
from tests.conftest import approved_form, write
from tests.test_project_page import make_project
from tests.test_v018_time_app import staff

STATIC = Path(__file__).resolve().parent.parent / 'studioos' / 'static'


def test_search_groups_results_and_respects_the_project_scope(admin):
    a = make_project(admin, 'Villa Alpha')
    b = approved_form(admin, 'post', '/api/projects', {'name': 'Villa Beta', 'budget': '1000'}).json()
    approved_form(admin, 'post', '/api/tasks', {'project_id': b['id'], 'title': 'Pour slab at Beta', 'assignee': 'Zed', 'due_date': '2099-01-01'})
    wide = admin.get('/api/search?q=slab').json()
    assert wide['total'] >= 2 and {x['project_id'] for x in wide['groups']['tasks']} == {a['id'], b['id']}
    narrow = admin.get(f"/api/search?q=slab&project_id={a['id']}").json()
    assert {x['project_id'] for x in narrow['groups']['tasks']} == {a['id']} and 'projects' not in narrow['groups']
    assert admin.get('/api/search?q=villa').json()['groups']['projects']
    snag = admin.get(f"/api/search?q=crack&project_id={a['id']}").json()
    assert snag['groups']['snags'][0]['title'] == 'Crack in wall'
    assert admin.get('/api/search?q=zzzzqq').json() == {'query': 'zzzzqq', 'project_id': None, 'groups': {}, 'total': 0}


def test_search_input_is_validated_and_wildcards_are_literal(admin):
    make_project(admin, 'Villa 100%')
    assert admin.get('/api/search?q=a').status_code == 422 and admin.get('/api/search?q=' + 'x' * 81).status_code == 422
    assert [x['title'] for x in admin.get('/api/search?q=100%25').json()['groups']['projects']] == ['Villa 100%']     # % is not a wildcard
    assert 'projects' not in admin.get('/api/search?q=%25%25').json()['groups'] or admin.get('/api/search?q=%25%25').json()['total'] == 0


def test_search_never_shows_a_person_what_their_role_or_projects_hide(admin):
    mine = make_project(admin, 'Villa Mine')
    hidden = make_project(admin, 'Villa Hidden Two')
    site, site_id = staff(admin, 'site.search', 'site_engineer')
    try:
        assert write(admin, 'put', f"/api/projects/{mine['id']}/members", {'user_ids': [site_id]}).status_code == 200
        got = site.get('/api/search?q=villa').json()
        assert [x['title'] for x in got['groups']['projects']] == ['Villa Mine'] and 'contacts' not in got['groups']
        assert all(x['project_id'] == mine['id'] for g in got['groups'].values() for x in g)
        assert site.get(f"/api/search?q=slab&project_id={hidden['id']}").status_code == 404           # not confirmed to exist
        with SessionLocal() as db:
            db.add(FlexibleRecord(record_type='work_issue', project_id=hidden['id'], data={'title': 'Secret crack', 'issue_status': 'Open'}))
            db.commit()
        assert 'snags' not in site.get('/api/search?q=secret').json()['groups']
    finally:
        site.close()


def test_the_chat_starts_narrowed_to_the_project_in_view(admin):
    p = approved_form(admin, 'post', '/api/projects', {'name': 'Villa Scope', 'budget': '100000'}).json()
    other = approved_form(admin, 'post', '/api/projects', {'name': 'Villa Other', 'budget': '100000'}).json()
    r = write(admin, 'post', '/api/chat', {'message': 'Create task: Review drawings', 'project_id': p['id']})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        items = db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.item_type == 'create_task')).all()
        assert items and items[-1].after_data.get('project') in (p['id'], 'Villa Scope')
    assert write(admin, 'post', '/api/chat', {'message': 'Create task: x', 'project_id': 999999}).status_code == 404
    site, _ = staff(admin, 'site.scope', 'site_engineer')                                                   # cannot scope to a project they are not on
    try:
        assert write(site, 'post', '/api/chat', {'message': 'hello', 'project_id': other['id']}).status_code == 404
    finally:
        site.close()


def test_preview_as_role_is_owner_only_and_changes_nothing(admin):
    p = make_project(admin, 'Villa Preview')
    as_site = admin.get(f"/api/projects/{p['id']}/page?as_role=site_engineer").json()
    assert as_site['as_role'] == 'site_engineer' and 'money' not in as_site['sections'] and 'money' not in as_site['data']
    assert admin.get(f"/api/projects/{p['id']}/page?as_role=accounts").json()['sections'] == ['money']
    assert admin.get(f"/api/projects/{p['id']}/page?as_role=root").status_code == 403
    mgr, _ = staff(admin, 'mgr.preview', 'manager')
    try:
        assert mgr.get(f"/api/projects/{p['id']}/page?as_role=site_engineer").status_code == 403
    finally:
        mgr.close()


def test_overlay_files_are_wired_and_clean():
    js = (STATIC / 'overlays.js').read_text(encoding='utf-8')
    css = (STATIC / 'overlays.css').read_text(encoding='utf-8')
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    assert html.index('/static/projectpage.js') < html.index('/static/overlays.js') and '/static/overlays.css' in html
    assert not re.search(r'\sstyle\s*=', js) and 'eval(' not in js and '.style.' not in js
    for kind in ('search', 'scope', 'filter', 'newform', 'peek', 'role'):
        assert f"{kind}:" in js.split('const OV_TITLES = {')[1].split('};')[0]
    assert "key === 'Escape'" in js and 'popstate' in js and 'touchend' in js and 'min-height:48px' in css
    assert "project_id: state.scope.project_id" in (STATIC / 'chat.js').read_text(encoding='utf-8')

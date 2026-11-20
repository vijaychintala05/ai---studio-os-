"""Record and form view types: a record view shows one record's fields for a person who may see it; a form view lists a record type's fields
and its submit goes through the normal proposal path (a ticket), never straight to a table. Fictional data."""
from pathlib import Path

from sqlalchemy import select

from studioos.db import ApprovalTicketItem, SessionLocal
from tests.conftest import approved_form, write
from tests.test_v018_time_app import staff
from tests.test_v0100_one_graph import install
from tests.test_viewspec_app import save, task_list

STATIC = Path(__file__).resolve().parent.parent / 'studioos' / 'static'


def record_spec():
    s = task_list('mine.task_page', 'Task page')
    s['primitive'] = 'record'
    s['source']['items'][0].pop('filter', None)
    return s


def form_spec(type_key='milestone', fields=('title', 'due_date', 'milestone_status')):
    return {'spec_version': 1, 'id': f'form.{type_key}', 'name': 'New milestone', 'primitive': 'form',
            'source': {'items': [{'record_type': type_key, 'fields': [{'field': f} for f in fields]}]}}


def test_a_record_view_shows_one_record_for_someone_who_may_see_it(admin):
    p = approved_form(admin, 'post', '/api/projects', {'name': 'Villa Record', 'budget': '1000'}).json()
    t = approved_form(admin, 'post', '/api/tasks', {'project_id': p['id'], 'title': 'Pour slab', 'assignee': 'Asha', 'due_date': '2026-12-01'}).json()
    approved_form(admin, 'post', '/api/tasks', {'project_id': p['id'], 'title': 'Order tiles', 'assignee': 'Ravi', 'due_date': '2026-12-02'})
    save(admin, admin, 'view_create', {'spec': record_spec(), 'scope': 'system'})
    r = admin.get(f"/api/viewspecs/mine.task_page/run?record_id={t['id']}")
    assert r.status_code == 200, r.text
    shown = r.json()['shown']
    assert shown['kind'] == 'record' and shown['record_id'] == t['id']
    values = [f['value'] for f in shown['fields']]
    assert shown['title'] == 'Pour slab' and 'Pour slab' in values and '2026-12-01' in values and 'Order tiles' not in values         # that one record, with the view's fields
    assert [f['label'] for f in shown['fields']][:1] == ['Title'] or len(shown['fields']) == 3
    assert admin.get('/api/viewspecs/mine.task_page/run').status_code == 422                                                          # it needs a record number
    assert admin.get('/api/viewspecs/mine.task_page/run?record_id=999999').status_code == 404
    site, _ = staff(admin, 'site.record', 'site_engineer')                                                                           # not on the project
    try:
        assert site.get(f"/api/viewspecs/mine.task_page/run?record_id={t['id']}").status_code == 404                                  # not found, not "forbidden"
    finally:
        site.close()


def test_a_form_view_lists_the_fields_of_a_built_record_type(admin):
    install(admin, 'work')
    save(admin, admin, 'view_create', {'spec': form_spec(), 'scope': 'system'})
    body = admin.get('/api/viewspecs/form.milestone/run').json()
    shown = body['shown']
    assert body['primitive'] == 'form' and shown['kind'] == 'form' and shown['type_key'] == 'milestone'
    by = {f['name']: f for f in shown['fields']}
    assert set(by) == {'title', 'due_date', 'milestone_status'} and by['title']['required'] is True
    assert by['milestone_status']['options'] == ['Planned', 'In progress', 'Done', 'Delayed'] and by['due_date']['kind'] == 'date'
    only_title = form_spec('milestone', ('title',))
    only_title['id'] = 'form.milestone.title'
    save(admin, admin, 'view_create', {'spec': only_title, 'scope': 'system'})
    assert [f['name'] for f in admin.get('/api/viewspecs/form.milestone.title/run').json()['shown']['fields']] == ['title']          # only the fields the view names
    tasks = form_spec('system.task', ('title', 'due_date'))
    tasks['id'] = 'form.task'
    save(admin, admin, 'view_create', {'spec': tasks, 'scope': 'system'})
    refused = admin.get('/api/viewspecs/form.task/run')
    assert refused.status_code == 422 and 'already have their own forms' in refused.text                                         # tasks have their own form


def test_a_form_submit_is_a_proposal_and_saves_nothing_until_approved(admin):
    install(admin, 'work')
    save(admin, admin, 'view_create', {'spec': form_spec(), 'scope': 'system'})
    fields = admin.get('/api/viewspecs/form.milestone/run').json()['shown']
    values = {'title': 'Slab cast', 'due_date': '2026-12-10', 'milestone_status': 'Planned'}
    r = write(admin, 'post', '/api/universal/proposals', {'kind': 'metadata_record', 'data': {'type_key': fields['type_key'], 'project_id': None, 'values': values}, 'evidence': 'Typed into a form view'})
    assert r.status_code == 200, r.text
    assert admin.get('/api/graph/records/milestone').json()['total'] == 0                                                            # a draft saves nothing
    bad = write(admin, 'post', '/api/universal/proposals', {'kind': 'metadata_record', 'data': {'type_key': 'milestone', 'project_id': None, 'values': {'milestone_status': 'Nonsense'}}, 'evidence': 'x'})
    assert bad.status_code in (400, 422)                                                                                              # the record type's own checks still apply
    with SessionLocal() as db:
        assert db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.item_type == 'metadata_record')).all()


def test_the_screens_are_wired_and_clean():
    js = (STATIC / 'newwork.js').read_text(encoding='utf-8')
    assert 'function nwRecordView' in js and 'function nwFormView' in js and 'nwRecordForm' in js and "'/api/universal/proposals'" in js
    assert 'Propose this record' in js and 'nothing is saved until it is approved' in js
    import re
    assert not re.search(r'\sstyle\s*=', js) and 'eval(' not in js

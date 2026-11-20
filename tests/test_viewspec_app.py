"""Stored views through the real approval path: create, change against a base version, roll back, who may do what, visibility,
and the dry-run check with its diff. Fictional data."""
import copy

from studioos import viewspec_catalog as vc
from studioos import viewspec_core as core
from tests.conftest import write
from tests.test_v018_time_app import staff


def task_list(view_id='mine.open_tasks', name='Open tasks'):
    return {'spec_version': 1, 'id': view_id, 'name': name, 'primitive': 'table',
            'source': {'items': [{'record_type': 'system.task', 'fields': [{'field': 'title'}, {'field': 'due_date'}, {'field': 'status'}],
                                  'filter': {'and': [{'field': 'status', 'op': 'neq', 'value': 'done'}]}, 'sort': [{'field': 'due_date'}]}]},
            'actions': ['open']}


def propose(client, kind, data):
    return write(client, 'post', '/api/viewspecs/propose', {'kind': kind, 'data': data})


def save(owner, client, kind, data):
    r = propose(client, kind, data)
    assert r.status_code == 200, r.text
    s = write(owner, 'post', f"/api/tickets/{r.json()['ticket_id']}/approve-and-save", {'confirmed': [], 'note': 'fictional test'})
    assert s.status_code == 200, s.text
    return s.json()


def test_primitives_catalogue(admin):
    body = admin.get('/api/viewspecs/primitives').json()
    assert body['primitives'] == list(core.PRIMITIVES) and 'eq' in body['operators_by_kind']['select'] and body['limits']['bytes'] == 32768


def test_the_real_catalog_adapter_includes_tasks():
    cat = vc.from_graph({'types': {'snag': {'fields': {'title': {'name': 'title', 'type': 'text'}, 'owner': {'name': 'owner', 'type': 'reference', 'target': 'system.user'},
                                                      'sev': {'name': 'sev', 'type': 'enum', 'options': ['Low', 'High']}}}}})
    assert cat['system.task']['due_date']['kind'] == 'date' and cat['snag']['owner'] == {'kind': 'relation', 'target': 'system.user'}
    assert cat['snag']['sev']['kind'] == 'select' and cat['snag']['sev']['options'] == ['Low', 'High']


def test_create_change_and_roll_back_with_versions(admin):
    save(admin, admin, 'view_create', {'spec': task_list(), 'scope': 'system'})
    got = admin.get('/api/viewspecs/mine.open_tasks').json()
    assert got['version'] == 1 and got['spec']['name'] == 'Open tasks' and len(got['versions']) == 1
    changed = task_list(name='Open tasks, newest first')
    save(admin, admin, 'view_change', {'view_id': _id(admin), 'base_version': 1, 'spec': changed})
    got = admin.get('/api/viewspecs/mine.open_tasks').json()
    assert got['version'] == 2 and got['spec']['name'] == 'Open tasks, newest first'
    v1 = admin.get('/api/viewspecs/mine.open_tasks/versions/1').json()
    assert v1['spec']['name'] == 'Open tasks'
    save(admin, admin, 'view_rollback', {'view_id': _id(admin), 'to_version': 1})
    got = admin.get('/api/viewspecs/mine.open_tasks').json()
    assert got['version'] == 3 and got['spec'] == v1['spec']                        # a rollback adds a version; nothing is edited in place
    assert [v['version'] for v in got['versions']] == [3, 2, 1]
    assert got['versions'][0]['hash'] == v1['hash']


def _id(admin):
    from sqlalchemy import select
    from studioos.db import SessionLocal
    from studioos.viewspec_models import ViewSpecRow
    with SessionLocal() as db:
        return db.scalar(select(ViewSpecRow.id).where(ViewSpecRow.spec_key == 'mine.open_tasks'))


def test_a_stale_base_version_and_bad_specs_are_refused(admin):
    save(admin, admin, 'view_create', {'spec': task_list(), 'scope': 'system'})
    vid = _id(admin)
    save(admin, admin, 'view_change', {'view_id': vid, 'base_version': 1, 'spec': task_list(name='Second')})
    stale = propose(admin, 'view_change', {'view_id': vid, 'base_version': 1, 'spec': task_list(name='Third')})
    assert stale.status_code == 400 and 'moved on' in stale.text
    bad = task_list()
    bad['primitive'] = 'calendar'                                                    # no date_field in layout
    assert propose(admin, 'view_change', {'view_id': vid, 'base_version': 2, 'spec': bad}).status_code == 400
    renamed = task_list(view_id='mine.other')
    assert propose(admin, 'view_change', {'view_id': vid, 'base_version': 2, 'spec': renamed}).status_code == 400
    assert propose(admin, 'view_create', {'spec': task_list(), 'scope': 'system'}).status_code == 400   # the id exists
    assert propose(admin, 'view_rollback', {'view_id': vid, 'to_version': 2}).status_code == 400          # that is the current one
    assert propose(admin, 'view_create', {'spec': {**task_list('x.y'), 'script': 'alert(1)'}}).status_code == 400


def test_roles_scopes_and_visibility(admin):
    site, _ = staff(admin, 'site.view', 'site_engineer')
    other, _ = staff(admin, 'arch.view', 'architect')
    try:
        assert propose(site, 'view_create', {'spec': task_list('site.all'), 'scope': 'system'}).status_code == 400   # only owner or manager
        mine = propose(site, 'view_create', {'spec': task_list('site.mine'), 'scope': 'user'}).json()
        assert mine['auto_approved'] is True                                              # a personal view needs no second person
        assert [v['key'] for v in site.get('/api/viewspecs').json()] == ['site.mine']
        assert other.get('/api/viewspecs').json() == [] and other.get('/api/viewspecs/site.mine').status_code == 404   # a personal view is private
        assert 'site.mine' in [v['key'] for v in admin.get('/api/viewspecs').json()]
        sid = _by_key(admin, 'site.mine')
        assert propose(other, 'view_change', {'view_id': sid, 'base_version': 1, 'spec': task_list('site.mine', 'Hijack')}).status_code == 400
        save(admin, admin, 'view_create', {'spec': {**task_list('for.managers'), 'audience': {'roles': ['manager']}}, 'scope': 'role'})
        assert 'for.managers' not in [v['key'] for v in site.get('/api/viewspecs').json()]
    finally:
        site.close()
        other.close()


def _by_key(admin, key):
    from sqlalchemy import select
    from studioos.db import SessionLocal
    from studioos.viewspec_models import ViewSpecRow
    with SessionLocal() as db:
        return db.scalar(select(ViewSpecRow.id).where(ViewSpecRow.spec_key == key))


def test_dry_run_returns_errors_or_a_diff(admin):
    ok = write(admin, 'post', '/api/viewspecs/validate', {'spec': task_list()}).json()
    assert ok['valid'] and ok['base_version'] is None and 'table' in ok['fits'] and all(d.startswith('added ') for d in ok['diff'])
    save(admin, admin, 'view_create', {'spec': task_list(), 'scope': 'system'})
    again = write(admin, 'post', '/api/viewspecs/validate', {'spec': task_list(name='Renamed')}).json()
    assert again['valid'] and again['base_version'] == 1 and any('changed name' in d for d in again['diff'])
    bad = copy.deepcopy(task_list())
    bad['source']['items'][0]['fields'].append({'field': 'ghost'})
    res = write(admin, 'post', '/api/viewspecs/validate', {'spec': bad}).json()
    assert not res['valid'] and any('ghost' in e['message'] for e in res['errors'])

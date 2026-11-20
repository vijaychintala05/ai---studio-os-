"""Ready-made views: offered only where their record types exist, proposed as tickets (never written directly), and every one runs. Fictional data."""
import json

from studioos import view_templates as T
from studioos import viewspec_core as core
from tests.conftest import approved_form, write
from tests.test_v018_time_app import staff
from tests.test_v0100_one_graph import install


def listing(client):
    return {t['key']: t for t in client.get('/api/viewspecs/templates').json()}


def approve(admin, ticket):
    r = write(admin, 'post', f'/api/tickets/{ticket}/approve-and-save', {'confirmed': [], 'note': 'fictional'})
    assert r.status_code == 200, r.text


def test_templates_are_plain_data_with_unique_ids():
    ids = [t['spec']['id'] for t in T.TEMPLATES]
    assert len(ids) == len(set(ids)) == 8 and len({t['key'] for t in T.TEMPLATES}) == 8
    for t in T.TEMPLATES:
        json.dumps(t['spec'])                                                  # data only
        assert t['spec']['primitive'] in core.PRIMITIVES and t['spec']['spec_version'] == 1 and t['about'] and t['title']
        assert core.spec_to_report(t['spec'])[1]['kind'] in ('board', 'table', 'calendar', 'bar')   # every one can run on the report engine


def test_only_templates_whose_record_types_exist_are_offered(admin):
    before = listing(admin)
    assert set(before) == {'task_board', 'overdue_tasks', 'task_calendar'}      # tasks exist; the Work pack is not installed yet
    install(admin, 'work')
    after = listing(admin)
    assert set(after) == {t['key'] for t in T.TEMPLATES} and not any(t['in_use'] for t in after.values())


def test_a_template_is_proposed_approved_and_runs(admin):
    install(admin, 'work')
    p = approved_form(admin, 'post', '/api/projects', {'name': 'Villa Templates', 'budget': '1000'}).json()
    approved_form(admin, 'post', '/api/tasks', {'project_id': p['id'], 'title': 'Pour slab', 'assignee': 'X', 'due_date': '2020-01-01'})
    drafted = write(admin, 'post', '/api/viewspecs/templates/task_board/propose', {'scope': 'system'})
    assert drafted.status_code == 200, drafted.text
    assert admin.get('/api/viewspecs/tpl.task_board').status_code == 404       # a draft stores nothing
    approve(admin, drafted.json()['ticket_id'])
    run = admin.get('/api/viewspecs/tpl.task_board/run').json()
    assert run['shown']['kind'] == 'board' and any(c['name'] == 'open' and c['count'] == 1 for c in run['shown']['lanes'])
    assert listing(admin)['task_board']['in_use'] is True
    for key in ('overdue_tasks', 'task_calendar', 'snag_board', 'snags_by_severity', 'milestones', 'site_visits', 'timesheets'):
        t = write(admin, 'post', f'/api/viewspecs/templates/{key}/propose', {'scope': 'system'})
        assert t.status_code == 200, (key, t.text)
        approve(admin, t.json()['ticket_id'])
        r = admin.get(f"/api/viewspecs/{core_id(key)}/run")
        assert r.status_code == 200, (key, r.text)
    overdue = admin.get('/api/viewspecs/tpl.overdue_tasks/run').json()['shown']['result']['rows']
    assert [c for row in overdue for c in row['cells']].count('Pour slab') == 1


def core_id(key):
    return next(t['spec']['id'] for t in T.TEMPLATES if t['key'] == key)


def test_a_personal_copy_has_its_own_id_and_roles_and_unknown_keys_are_checked(admin):
    site, site_id = staff(admin, 'site.tpl', 'site_engineer')
    try:
        assert write(site, 'post', '/api/viewspecs/templates/task_board/propose', {'scope': 'system'}).status_code == 400       # only owner or manager
        mine = write(site, 'post', '/api/viewspecs/templates/task_board/propose', {'scope': 'user'})
        assert mine.status_code == 200, mine.text
        assert mine.json()['auto_approved'] is True                                                                              # personal and plain: approved automatically
        assert [v['key'] for v in site.get('/api/viewspecs').json()] == [f'tpl.task_board.u{site_id}']
        assert write(site, 'post', '/api/viewspecs/templates/ghost/propose', {'scope': 'user'}).status_code == 404
        assert write(site, 'post', '/api/viewspecs/templates/snag_board/propose', {'scope': 'user'}).status_code == 404         # the pack is not installed
    finally:
        site.close()

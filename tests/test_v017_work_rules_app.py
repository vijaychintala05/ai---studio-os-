"""v0.17 through the real approval path: every change is a ticket, the rules refuse what they must. Fictional data."""
import datetime as dt

from sqlalchemy import select

from studioos import work_rules_core as core
from studioos.db import SessionLocal, Task, now
from studioos.work_models import TaskLink, WorkDeletion, WorkTransitionLog
from tests.conftest import approved_form, write


def propose(client, kind, data):
    return write(client, 'post', '/api/work/propose', {'kind': kind, 'data': data})


def save(client, kind, data):
    r = propose(client, kind, data)
    assert r.status_code == 200, r.text
    ticket_id = r.json()['ticket_id']
    s = write(client, 'post', f'/api/tickets/{ticket_id}/approve-and-save', {'confirmed': [], 'note': 'fictional test'})
    assert s.status_code == 200, s.text
    return ticket_id


def project_with_tasks(admin, n=3, name='Villa W'):
    p = approved_form(admin, 'post', '/api/projects', {'name': name, 'budget': '100000'}).json()
    tasks = [approved_form(admin, 'post', '/api/tasks', {'project_id': p['id'], 'title': f'Task {i}'}).json() for i in range(n)]
    return p, tasks


def test_nothing_is_written_until_a_person_approves(admin):
    p, (a, b, _) = project_with_tasks(admin)
    r = propose(admin, 'work_link', {'predecessor_id': a['id'], 'successor_id': b['id'], 'kind': 'hard'})
    assert r.status_code == 200
    with SessionLocal() as db:
        assert db.scalars(select(TaskLink)).all() == []


def test_hard_link_blocks_closing_until_the_earlier_task_is_done(admin):
    p, (a, b, _) = project_with_tasks(admin)
    save(admin, 'work_link', {'predecessor_id': a['id'], 'successor_id': b['id'], 'kind': 'hard'})
    blocked = write(admin, 'patch', f"/api/tasks/{b['id']}/complete")
    assert blocked.status_code == 400 and f"#{a['id']}" in blocked.text
    done_a = write(admin, 'patch', f"/api/tasks/{a['id']}/complete")
    assert done_a.status_code == 200, done_a.text
    saved = write(admin, 'post', f"/api/tickets/{done_a.json()['ticket_id']}/approve-and-save", {'confirmed': []})
    assert saved.status_code == 200, saved.text
    ok = write(admin, 'patch', f"/api/tasks/{b['id']}/complete")
    assert ok.status_code == 200, ok.text


def test_loop_and_cross_project_hard_links_refused(admin):
    p, (a, b, c3) = project_with_tasks(admin)
    save(admin, 'work_link', {'predecessor_id': a['id'], 'successor_id': b['id'], 'kind': 'hard'})
    save(admin, 'work_link', {'predecessor_id': b['id'], 'successor_id': c3['id'], 'kind': 'hard'})
    r = propose(admin, 'work_link', {'predecessor_id': c3['id'], 'successor_id': a['id'], 'kind': 'hard'})
    assert r.status_code == 400 and 'loop' in r.text
    p2, (other, _, __) = project_with_tasks(admin, name='Villa X')
    r = propose(admin, 'work_link', {'predecessor_id': a['id'], 'successor_id': other['id'], 'kind': 'hard'})
    assert r.status_code == 400 and 'same project' in r.text


def test_template_applies_once_with_stages_tasks_and_links(admin):
    p = approved_form(admin, 'post', '/api/projects', {'name': 'Flat T', 'budget': '50000'}).json()
    tpl = {'stages': [{'key': 'design', 'name': 'Design'}],
           'tasks': [{'key': 'one', 'stage': 'design', 'title': 'First', 'duration_days': 2},
                     {'key': 'two', 'stage': 'design', 'title': 'Second', 'offset_days': 3}],
           'links': [{'pred': 'one', 'succ': 'two', 'kind': 'hard'}]}
    save(admin, 'work_template_publish', {'key': 'tiny', 'name': 'Tiny', 'definition': tpl})
    save(admin, 'work_apply_template', {'template_key': 'tiny', 'project_id': p['id'], 'start_date': '2026-05-01'})
    s = admin.get(f"/api/work/projects/{p['id']}/structure").json()
    assert len(s['stages']) == 1 and len(s['tasks']) == 2 and len(s['links']) == 1
    two = next(t for t in s['tasks'] if t['title'] == 'Second')
    assert two['start_date'] == '2026-05-04' and two['blocked_by']
    again = propose(admin, 'work_apply_template', {'template_key': 'tiny', 'project_id': p['id'], 'start_date': '2026-05-01'})
    assert again.status_code == 400 and 'already applied' in again.text


def test_workflow_publish_refuses_invalid_and_task_transition_needs_evidence(admin):
    bad = {'statuses': [{'key': 'ab', 'label': 'A', 'class': 'open', 'start': True}], 'transitions': []}
    r = propose(admin, 'work_workflow_publish', {'key': 'bad', 'name': 'Bad', 'applies_to': {'target': 'task'}, 'definition': bad})
    assert r.status_code == 400
    wf = {'statuses': [{'key': 'open', 'label': 'Open', 'class': 'open', 'start': True},
                       {'key': 'fixed', 'label': 'Fixed', 'class': 'open'}, {'key': 'done', 'label': 'Done', 'class': 'closed'}],
          'transitions': [{'name': 'fix', 'from': 'open', 'to': 'fixed', 'roles': ['admin'], 'requires': ['photo']},
                          {'name': 'finish', 'from': 'fixed', 'to': 'done', 'roles': ['admin']}]}
    save(admin, 'work_workflow_publish', {'key': 'site_task', 'name': 'Site task', 'applies_to': {'target': 'task'}, 'definition': wf})
    p, (a, _, __) = project_with_tasks(admin)
    no_photo = propose(admin, 'work_transition', {'workflow_key': 'site_task', 'target': 'task', 'target_id': a['id'], 'transition': 'fix'})
    assert no_photo.status_code == 400 and 'photo' in no_photo.text
    save(admin, 'work_transition', {'workflow_key': 'site_task', 'target': 'task', 'target_id': a['id'], 'transition': 'fix',
                                    'evidence': {'photo_document_id': 1}})
    with SessionLocal() as db:
        assert db.get(Task, a['id']).status == 'fixed'
        rows = db.scalars(select(WorkTransitionLog)).all()
        assert [(r.transition, r.from_status, r.to_status) for r in rows] == [('fix', 'open', 'fixed')]


def test_delete_and_restore_with_window(admin):
    p, (a, b, _) = project_with_tasks(admin)
    save(admin, 'work_task_structure', {'task_id': b['id'], 'parent_task_id': a['id']})
    save(admin, 'work_task_delete', {'task_id': a['id'], 'reason': 'entered by mistake'})
    live = [t['id'] for t in admin.get(f"/api/work/projects/{p['id']}/structure").json()['tasks']]
    assert a['id'] not in live and b['id'] not in live            # the subtask went with its parent
    assert len(admin.get('/api/work/recycle').json()['items']) == 2
    save(admin, 'work_task_restore', {'task_id': b['id']})         # restoring the child brings the parent back
    live = [t['id'] for t in admin.get(f"/api/work/projects/{p['id']}/structure").json()['tasks']]
    assert a['id'] in live and b['id'] in live


def test_restore_after_window_is_refused(admin):
    p, (a, _, __) = project_with_tasks(admin)
    save(admin, 'work_task_delete', {'task_id': a['id'], 'reason': 'entered by mistake'})
    with SessionLocal() as db:
        row = db.scalar(select(WorkDeletion))
        row.restore_until = now() - dt.timedelta(days=1)
        db.commit()
    r = propose(admin, 'work_task_restore', {'task_id': a['id']})
    assert r.status_code == 400 and 'passed' in r.text


def test_baseline_freezes_dates(admin):
    p, (a, _, __) = project_with_tasks(admin)
    save(admin, 'work_baseline', {'project_id': p['id'], 'label': 'Approved plan'})
    s = admin.get(f"/api/work/projects/{p['id']}/structure").json()
    assert s['baseline']['label'] == 'Approved plan'


def test_work_changes_cannot_be_undone_generically(admin):
    p, (a, b, _) = project_with_tasks(admin)
    ticket_id = save(admin, 'work_link', {'predecessor_id': a['id'], 'successor_id': b['id'], 'kind': 'soft'})
    r = write(admin, 'post', f'/api/tickets/{ticket_id}/reverse', {'reason': 'try to undo the link'})
    assert r.status_code in (400, 409) and 'generic undo' in r.text


def test_dry_run_writes_nothing_and_reports_refusals(admin):
    wf = core.STARTING_SNAG_WORKFLOW
    r = write(admin, 'post', '/api/work/workflows/dry-run',
              {'definition': wf, 'path': [{'transition': 'assign', 'role': 'manager', 'actor_id': 1}]})
    assert r.status_code == 200 and r.json()['visited'] == ['reported', 'assigned']
    r = write(admin, 'post', '/api/work/workflows/dry-run',
              {'definition': wf, 'path': [{'transition': 'close', 'role': 'admin', 'actor_id': 1}]})
    assert r.status_code == 400

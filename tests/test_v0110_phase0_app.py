"""v0.11.0 Phase 0 (app level; needs FastAPI + SQLAlchemy; runs in CI, NOT RUN in the build sandbox).

1. Employees read their own attendance, leave and (shared) weekly reviews without a manager role;
   other staff cannot, in lists, reports and the record page.
2. Links that start at a task or a staff member: Admin approves the link type, access is checked
   for the task's project, removal works, and the record page shows the incoming side.
3. metadata_type_options adds self_read to a type installed before v0.11.0 (Admin only).
Fictional data, disposable database."""
from sqlalchemy import select

from .conftest import write, approved_form
from .test_v098_universal_accounting import propose, save, project
from .test_v0100_one_graph import install, add_user, client_for, task
from studioos.db import SessionLocal, UniversalEdge


def _record(admin, type_key, values, project_id=None):
    return save(admin, propose(admin, 'metadata_record', {'type_key': type_key, 'project_id': project_id, 'values': values}))['id']


def test_employee_reads_own_attendance_leave_and_shared_review_only(admin):
    install(admin, 'people')
    asha, ravi = add_user(admin, 'asha.rao', 'site_engineer'), add_user(admin, 'ravi.kumar', 'architect')
    a1 = _record(admin, 'attendance_entry', {'employee': asha, 'attendance_date': '2026-11-13', 'attendance_status': 'Present'})
    a2 = _record(admin, 'attendance_entry', {'employee': ravi, 'attendance_date': '2026-11-13', 'attendance_status': 'Present'})
    l1 = _record(admin, 'leave_request', {'employee': asha, 'from_date': '2026-11-20', 'to_date': '2026-11-21',
                                          'leave_type': 'Casual', 'reason': 'Fictional family function', 'decision': 'Requested'})
    draft = _record(admin, 'weekly_review', {'employee': asha, 'week_start': '2026-11-09', 'reviewer': 1, 'review_status': 'Draft'})
    shared = _record(admin, 'weekly_review', {'employee': asha, 'week_start': '2026-11-02', 'reviewer': 1, 'review_status': 'Shared with employee'})
    other = _record(admin, 'weekly_review', {'employee': ravi, 'week_start': '2026-11-02', 'reviewer': 1, 'review_status': 'Shared with employee'})
    ca, cr = client_for('asha.rao'), client_for('ravi.kumar')
    ids = lambda c, t: {r['id'] for r in c.get(f'/api/graph/records/{t}').json()['records']}
    assert ids(ca, 'attendance_entry') == {a1}
    assert ids(cr, 'attendance_entry') == {a2}
    assert ids(ca, 'leave_request') == {l1} and ids(cr, 'leave_request') == set()
    assert ids(ca, 'weekly_review') == {shared}                    # the draft stays with the manager
    assert ids(cr, 'weekly_review') == {other}
    assert ca.get(f'/api/graph/record/{a1}').status_code == 200
    for rid in (a2, draft, other):
        assert ca.get(f'/api/graph/record/{rid}').status_code == 404
    assert cr.get(f'/api/graph/record/{l1}').status_code == 404


def test_type_options_ticket_adds_self_read_admin_only(admin):
    save(admin, propose(admin, 'metadata_type', {'key': 'overtime_entry', 'title': 'Overtime entry', 'fields': [
        {'name': 'employee', 'type': 'reference', 'target': 'system.user', 'required': True},
        {'name': 'hours', 'type': 'decimal', 'required': True}]}))
    asha = add_user(admin, 'asha.rao', 'site_engineer')
    rid = _record(admin, 'overtime_entry', {'employee': asha, 'hours': '2.5'})
    ca = client_for('asha.rao')
    assert ca.get(f'/api/graph/record/{rid}').status_code == 404
    save(admin, propose(admin, 'metadata_type_options', {'type_key': 'overtime_entry', 'self_read': {'field': 'employee'}}))
    assert ca.get(f'/api/graph/record/{rid}').status_code == 200
    bad = write(admin, 'post', '/api/universal/proposals', {'kind': 'metadata_type_options',
                'data': {'type_key': 'overtime_entry', 'self_read': {'field': 'hours'}}, 'evidence': 'wrong field'})
    assert bad.status_code == 422


def test_links_from_tasks_and_staff_with_access_checks(admin):
    install(admin, 'sops')
    pa = project(admin)
    pb = approved_form(admin,'post','/api/projects', {'name': 'Fictional Project B', 'budget': '500000'}).json()['id']
    t_a, t_b = task(pa, 'Kitchen shutters'), task(pb, 'Villa deck')
    save(admin, propose(admin, 'metadata_relation', {'key': 'task_follows_sop', 'source_type': 'system.task',
                                                     'target_type': 'sop', 'cardinality': 'many', 'inverse_label': 'Tasks following this SOP'}))
    save(admin, propose(admin, 'metadata_relation', {'key': 'staff_trained_on', 'source_type': 'system.user',
                                                     'target_type': 'sop', 'cardinality': 'many', 'inverse_label': 'Trained staff'}))
    owner = add_user(admin, 'meera.iyer', 'manager')
    sop = _record(admin, 'sop', {'sop_code': 'SOP-001', 'title': 'Fictional carpentry check', 'purpose': 'Fictional purpose',
                                 'scope': 'Fictional scope', 'owner': owner, 'sop_version': '1', 'sop_status': 'Approved'})
    e = save(admin, propose(admin, 'metadata_edge', {'relation_key': 'task_follows_sop', 'source_id': t_a, 'target_id': sop}))
    with SessionLocal() as db:
        edge = db.get(UniversalEdge, e['id'])
        assert edge.source_id is None and edge.source_system == 'task' and edge.source_system_id == t_a
    dup = write(admin, 'post', '/api/universal/proposals', {'kind': 'metadata_edge',
                'data': {'relation_key': 'task_follows_sop', 'source_id': t_a, 'target_id': sop}, 'evidence': 'again'})
    assert dup.status_code == 422
    page = admin.get(f'/api/graph/links-from/system.task/{t_a}').json()
    assert page['outgoing'][0]['items'][0]['id'] == sop
    incoming = admin.get(f'/api/graph/record/{sop}').json()['incoming']
    assert any(g['relation'] == 'task_follows_sop' and g['items'][0]['id'] == t_a for g in incoming)
    # A staff member only on project A cannot link from project B's task, and cannot see it.
    asha = add_user(admin, 'asha.rao', 'site_engineer')
    assert write(admin, 'put', f'/api/projects/{pa}/members', {'user_ids': [asha]}).status_code == 200
    ca = client_for('asha.rao')
    refused = write(ca, 'post', '/api/universal/proposals', {'kind': 'metadata_edge',
                    'data': {'relation_key': 'task_follows_sop', 'source_id': t_b, 'target_id': sop}, 'evidence': 'other project'})
    assert refused.status_code == 422
    assert ca.get(f'/api/graph/links-from/system.task/{t_b}').status_code == 404
    # Staff may link from themselves, not from another staff member.
    ravi = add_user(admin, 'ravi.kumar', 'architect')
    assert write(ca, 'post', '/api/universal/proposals', {'kind': 'metadata_edge',
                 'data': {'relation_key': 'staff_trained_on', 'source_id': ravi, 'target_id': sop}, 'evidence': 'fictional test evidence'}).status_code == 422
    assert write(ca, 'post', '/api/universal/proposals', {'kind': 'metadata_edge',
                 'data': {'relation_key': 'staff_trained_on', 'source_id': asha, 'target_id': sop}, 'evidence': 'fictional test evidence'}).status_code == 200
    # Removal keeps the row and marks it removed.
    save(admin, propose(admin, 'metadata_edge_remove', {'edge_id': e['id'], 'reason': 'Fictional: wrong SOP'}))
    with SessionLocal() as db:
        assert db.get(UniversalEdge, e['id']).removed_at is not None
    assert admin.get(f'/api/graph/links-from/system.task/{t_a}').json()['outgoing'][0]['items'] == []

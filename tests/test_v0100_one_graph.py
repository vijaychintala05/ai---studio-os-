"""v0.10.0 "One graph": staff, tasks and files as link targets and reference fields; link removal;
business packs (people, work, SOPs) installed as data; reports across types; daily rules;
per-type approvers; chat drafts for any universal type; the audit's zero-code test end to end.
Fictional data, disposable database. Runs in CI on SQLite and PostgreSQL 16."""
import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, func

from .conftest import write, approved_form
from .test_v098_universal_accounting import propose, save, project
from studioos.db import (SessionLocal, engine, UniversalEdge, UniversalWorkflowNotice, UniversalPackInstall, FlexibleRecord,
                         RecordType, Task, User)
from studioos.main import app

ROOT = Path(__file__).resolve().parents[1]


def tables():
    return set(inspect(engine).get_table_names())


def source_fingerprint():
    h = hashlib.sha256()
    for p in sorted((ROOT / 'studioos').rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts:
            h.update(str(p.relative_to(ROOT)).encode()); h.update(p.read_bytes())
    return h.hexdigest()


def install(admin, key):
    pack = next(p for p in admin.get('/api/graph/catalog').json()['packs'] if p['key'] == key)
    return save(admin, propose(admin, 'metadata_pack_install', {'pack': key, 'version': pack['version'], 'sha256': pack['sha256']}))


def add_user(admin, username, role):
    r = write(admin, 'post', '/api/users', {'username': username, 'display_name': username.replace('.', ' ').title(),
                                           'role': role, 'password': 'Fixture-Strong-Moss7!Keystone'})
    assert r.status_code == 200, r.text
    return r.json()['id']


def client_for(username):
    c = TestClient(app)
    assert c.post('/api/auth/login', json={'username': username, 'password': 'Fixture-Strong-Moss7!Keystone'}).status_code == 200
    return c


def task(pid, title='Kitchen shutters'):
    with SessionLocal() as db:
        t = Task(project_id=pid, title=title, assignee='Ravi')
        db.add(t); db.commit(); return t.id


# ------------------------------------------------------------------ packs

def test_packs_install_by_one_admin_ticket_and_add_no_tables(admin):
    before = tables()
    assert install(admin, 'work')['type'] == 'universal_pack'
    install(admin, 'people')
    install(admin, 'sops')
    assert tables() == before                                   # types, links, reports and rules are rows, not tables
    cat = admin.get('/api/graph/catalog').json()
    keys = {t['key'] for t in cat['types']}
    assert {'timesheet_entry', 'work_issue', 'milestone', 'meeting_note', 'employee_profile', 'attendance_entry',
            'leave_request', 'weekly_review', 'sop', 'sop_step', 'sop_run', 'sop_acknowledgement', 'sop_change_request'} <= keys
    assert {r['key'] for r in cat['reports']} >= {'hours_this_week', 'open_issues_by_owner', 'sop_register', 'attendance_this_month'}
    assert all(p['installed_version'] == p['version'] for p in cat['packs'])   # v0.13.0: the people pack is version 2
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(UniversalPackInstall)) == 3
    pack = next(p for p in cat['packs'] if p['key'] == 'work')
    again = write(admin, 'post', '/api/universal/proposals', {'kind': 'metadata_pack_install',
                  'data': {'pack': 'work', 'version': 1, 'sha256': pack['sha256']}, 'evidence': 'again'})
    assert again.status_code == 422 and 'already installed' in again.text
    forged = write(admin, 'post', '/api/universal/proposals', {'kind': 'metadata_pack_install',
                   'data': {'pack': 'people', 'version': 1, 'sha256': '0' * 64}, 'evidence': 'changed file'})
    assert forged.status_code == 422


# ------------------------------------------------------------------ the audit's zero-code test (A–E)

def test_site_safety_inspection_end_to_end_with_no_code_change(admin):
    fingerprint, before = source_fingerprint(), tables()
    pa = project(admin)
    pb = approved_form(admin,'post','/api/projects', {'name': 'Fictional Project B', 'budget': '500000'}).json()['id']
    asha, ravi = add_user(admin, 'asha.rao', 'site_engineer'), add_user(admin, 'ravi.kumar', 'architect')
    # A. a type StudioOS has never seen, with staff references
    save(admin, propose(admin, 'metadata_type', {'key': 'site_safety_inspection', 'title': 'Site Safety Inspection', 'label_field': 'site_location',
        'fields': [{'name': 'inspection_date', 'type': 'date', 'required': True},
                   {'name': 'inspection_category', 'type': 'enum', 'required': True, 'options': ['Scaffolding', 'Electrical', 'Fire']},
                   {'name': 'site_location', 'type': 'text', 'required': True},
                   {'name': 'inspector', 'type': 'reference', 'target': 'system.user', 'required': True},
                   {'name': 'severity', 'type': 'enum', 'required': True, 'options': ['Low', 'Medium', 'High']},
                   {'name': 'observations', 'type': 'text', 'required': True},
                   {'name': 'evidence_file', 'type': 'reference', 'target': 'system.document', 'required': False}]}))
    save(admin, propose(admin, 'metadata_type', {'key': 'corrective_action', 'title': 'Corrective Action', 'label_field': 'action_text',
        'fields': [{'name': 'action_text', 'type': 'text', 'required': True},
                   {'name': 'responsible', 'type': 'reference', 'target': 'system.user', 'required': True},
                   {'name': 'deadline', 'type': 'date', 'required': False},
                   {'name': 'action_status', 'type': 'enum', 'required': True, 'options': ['Open', 'Done']}]}))
    # B. links, including to a task
    save(admin, propose(admin, 'metadata_relation', {'key': 'action_from_inspection', 'source_type': 'corrective_action',
                                                     'target_type': 'site_safety_inspection', 'cardinality': 'one', 'inverse_label': 'Actions'}))
    save(admin, propose(admin, 'metadata_relation', {'key': 'action_for_task', 'source_type': 'corrective_action',
                                                     'target_type': 'system.task', 'cardinality': 'many'}))
    ins = {}
    for pid, loc, sev, who in ((pa, 'Tower B L3', 'High', asha), (pb, 'Villa deck', 'Low', ravi), (pb, 'Villa stairs', 'High', ravi)):
        ins[loc] = save(admin, propose(admin, 'metadata_record', {'type_key': 'site_safety_inspection', 'project_id': pid, 'values': {
            'inspection_date': '2026-11-10', 'inspection_category': 'Scaffolding', 'site_location': loc, 'inspector': who,
            'severity': sev, 'observations': 'Fictional observation'}}))['id']
    acts = {}
    for pid, text, who, loc, status in ((pa, 'Fit toe boards', asha, 'Tower B L3', 'Open'), (pa, 'Replace net', ravi, 'Tower B L3', 'Open'),
                                        (pb, 'Add handrail', ravi, 'Villa stairs', 'Open'), (pb, 'Sand deck', ravi, 'Villa deck', 'Open'),
                                        (pa, 'Old fix', asha, 'Tower B L3', 'Done')):
        acts[text] = save(admin, propose(admin, 'metadata_record', {'type_key': 'corrective_action', 'project_id': pid,
            'values': {'action_text': text, 'responsible': who, 'action_status': status},
            'links': [{'relation_key': 'action_from_inspection', 'target_id': ins[loc]}]}))['id']
    t = task(pa)
    save(admin, propose(admin, 'metadata_edge', {'relation_key': 'action_for_task', 'source_id': acts['Fit toe boards'], 'target_id': t}))
    # cross-project and missing targets refused
    bad = write(admin, 'post', '/api/universal/proposals', {'kind': 'metadata_edge', 'evidence': 'fictional test evidence',
                'data': {'relation_key': 'action_for_task', 'source_id': acts['Add handrail'], 'target_id': t}})
    assert bad.status_code == 422 and 'another project' in bad.text
    bad = write(admin, 'post', '/api/universal/proposals', {'kind': 'metadata_record', 'evidence': 'fictional test evidence', 'data': {
        'type_key': 'corrective_action', 'project_id': pa, 'values': {'action_text': 'x', 'responsible': 99999, 'action_status': 'Open'}}})
    assert bad.status_code == 422 and 'Staff member' in bad.text
    # C. generic record page shows links in both directions
    page = admin.get(f'/api/graph/record/{ins["Tower B L3"]}').json()
    assert page['label'] == 'Tower B L3' and next(v for v in page['values'] if v['name'] == 'inspector')['display'] == 'Asha Rao'
    actions = next(g for g in page['incoming'] if g['relation'] == 'action_from_inspection')['items']
    assert sorted(a['label'] for a in actions) == ['Fit toe boards', 'Old fix', 'Replace net']
    act_page = admin.get(f'/api/graph/record/{acts["Fit toe boards"]}').json()
    assert next(g for g in act_page['outgoing'] if g['relation'] == 'action_for_task')['items'][0]['label'] == 'Kitchen shutters'
    listing = admin.get('/api/graph/records/corrective_action?q=toe').json()
    assert [r['label'] for r in listing['records']] == ['Fit toe boards']
    # D. the report, through a link, grouped by the responsible person
    save(admin, propose(admin, 'metadata_report', {'key': 'open_high_actions', 'title': 'Open high-severity actions by person',
        'base': 'corrective_action', 'filters': [{'path': 'action_status', 'op': 'eq', 'value': 'Open'},
                                                 {'path': '@action_from_inspection.severity', 'op': 'eq', 'value': 'High'}],
        'group_by': ['responsible'], 'measures': [{'agg': 'count', 'label': 'Actions'}]}))
    out = admin.get('/api/graph/reports/open_high_actions/run').json()
    assert {r['group'][0]: r['values'][0] for r in out['rows']} == {'Asha Rao': '1', 'Ravi Kumar': '2'}
    # E. nothing in the application changed
    assert source_fingerprint() == fingerprint and tables() == before


# ------------------------------------------------------------------ access, approvers, links

def test_company_wide_sops_readable_by_staff_but_reviews_are_not(admin):
    install(admin, 'sops'); install(admin, 'people')
    me = admin.get('/api/auth/me').json()['user']['id']
    sop = save(admin, propose(admin, 'metadata_record', {'type_key': 'sop', 'project_id': None, 'values': {
        'sop_code': 'SOP-001', 'title': 'Site handover', 'purpose': 'Hand over a finished site', 'scope': 'All projects',
        'owner': me, 'sop_version': '1.0', 'sop_status': 'Approved'}}))['id']
    for n, text in ((2, 'Hand over keys'), (1, 'Walk the site with the client')):
        save(admin, propose(admin, 'metadata_record', {'type_key': 'sop_step', 'project_id': None,
             'values': {'step_no': n, 'instruction': text}, 'links': [{'relation_key': 'step_of_sop', 'target_id': sop}]}))
    review = save(admin, propose(admin, 'metadata_record', {'type_key': 'weekly_review', 'project_id': None, 'values': {
        'employee': me, 'week_start': '2026-11-09', 'reviewer': me, 'review_status': 'Draft'}}))['id']
    add_user(admin, 'site.one', 'site_engineer')
    staff = client_for('site.one')
    page = staff.get(f'/api/graph/record/{sop}')
    assert page.status_code == 200
    steps = next(g for g in page.json()['incoming'] if g['relation'] == 'step_of_sop')['items']
    assert [s['label'] for s in steps] == ['Walk the site with the client', 'Hand over keys']     # ordered by step number
    assert staff.get(f'/api/graph/record/{review}').status_code == 404
    assert staff.get('/api/graph/records/weekly_review').json()['total'] == 0


def test_manager_approves_pack_records_but_not_new_types(admin):
    install(admin, 'work')
    pid = project(admin)
    add_user(admin, 'manager.one', 'manager')
    mgr = client_for('manager.one')
    owner = mgr.get('/api/auth/me').json()['user']['id']
    p = propose(mgr, 'metadata_record', {'type_key': 'work_issue', 'project_id': pid, 'values': {
        'title': 'Glass delayed', 'owner': owner, 'severity': 'High', 'issue_status': 'Open'}})
    assert write(mgr, 'post', f'/api/tickets/{p["ticket_id"]}/approve-and-save', {}).status_code == 200
    t = propose(mgr, 'metadata_type', {'key': 'tool_loan', 'title': 'Tool loan', 'fields': [{'name': 'tool', 'type': 'text', 'required': True}]})
    assert write(mgr, 'post', f'/api/tickets/{t["ticket_id"]}/approve-and-save', {}).status_code == 403


def test_link_removal_then_delete_and_relink(admin):
    install(admin, 'work')
    pid = project(admin)
    me = admin.get('/api/auth/me').json()['user']['id']
    issue = save(admin, propose(admin, 'metadata_record', {'type_key': 'work_issue', 'project_id': pid, 'values': {
        'title': 'Hinge problem', 'owner': me, 'severity': 'Low', 'issue_status': 'Open'}}))['id']
    t = task(pid)
    edge = save(admin, propose(admin, 'metadata_edge', {'relation_key': 'issue_blocks_task', 'source_id': issue, 'target_id': t}))['id']
    version = admin.get(f'/api/graph/record/{issue}').json()['current_version']
    blocked = write(admin, 'post', '/api/universal/proposals', {'kind': 'metadata_record_delete', 'evidence': 'fictional test evidence',
                    'data': {'type_key': 'work_issue', 'record_id': issue, 'expected_version': version}})
    assert blocked.status_code == 422 and 'remove the links first' in blocked.text
    save(admin, propose(admin, 'metadata_edge_remove', {'edge_id': edge, 'reason': 'Linked by mistake'}))
    with SessionLocal() as db:
        assert db.get(UniversalEdge, edge).removed_at is not None              # kept, marked removed
    again = save(admin, propose(admin, 'metadata_edge', {'relation_key': 'issue_blocks_task', 'source_id': issue, 'target_id': t}))
    assert again['id'] == edge                                                # the same link comes back
    save(admin, propose(admin, 'metadata_edge_remove', {'edge_id': edge, 'reason': 'Not related after all'}))
    save(admin, propose(admin, 'metadata_record_delete', {'type_key': 'work_issue', 'record_id': issue, 'expected_version': version}))


def test_undo_is_refused_for_universal_saves(admin):
    install(admin, 'work')
    pid = project(admin)
    me = admin.get('/api/auth/me').json()['user']['id']
    p = propose(admin, 'metadata_record', {'type_key': 'work_issue', 'project_id': pid, 'values': {
        'title': 'Undo me', 'owner': me, 'severity': 'Low', 'issue_status': 'Open'}})
    rec = save(admin, p)['id']
    r = write(admin, 'post', f'/api/tickets/{p["ticket_id"]}/reverse', {'reason': 'Trying a generic undo'})
    assert r.status_code == 409 and 'Undo is not available' in r.text
    with SessionLocal() as db:
        assert db.get(FlexibleRecord, rec).deleted_at is None


# ------------------------------------------------------------------ rules, reports, chat

def test_daily_rule_notifies_the_owner_once(admin):
    install(admin, 'work')
    pid = project(admin)
    uid = add_user(admin, 'asha.rao', 'manager')
    save(admin, propose(admin, 'metadata_record', {'type_key': 'work_issue', 'project_id': pid, 'values': {
        'title': 'Overdue fictional issue', 'owner': uid, 'severity': 'Medium', 'due_date': '2026-01-05', 'issue_status': 'Open'}}))
    first = write(admin, 'post', '/api/graph/rules/run', {}).json()['notices_created']
    second = write(admin, 'post', '/api/graph/rules/run', {}).json()['notices_created']
    assert first == 1 and second == 0
    asha = client_for('asha.rao')
    mine = [n for n in asha.get('/api/graph/notices').json()['notices'] if n['for_me']]
    assert {n['rule'] for n in mine} == {'issue_assigned', 'issue_overdue'}
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(UniversalWorkflowNotice).where(UniversalWorkflowNotice.for_user_id == uid)) == 2


def test_report_counts_only_what_the_reader_may_see(admin):
    install(admin, 'work')
    pa = project(admin)
    pb = approved_form(admin,'post','/api/projects', {'name': 'Fictional Project B', 'budget': '500000'}).json()['id']
    uid = add_user(admin, 'arch.one', 'architect')
    assert write(admin, 'put', f'/api/projects/{pa}/members', {'user_ids': [uid]}).status_code == 200
    for pid in (pa, pb, pb):
        save(admin, propose(admin, 'metadata_record', {'type_key': 'timesheet_entry', 'project_id': pid, 'values': {
            'employee': uid, 'work_date': '2026-11-10', 'hours': '2.5', 'activity': 'Drawings'}}))
    full = admin.get('/api/graph/reports/hours_by_project_month/run').json()
    arch = client_for('arch.one').get('/api/graph/reports/hours_by_project_month/run').json()
    assert full['matched'] in (0, 3) and arch['matched'] in (0, 1)        # 0 only when the run is in a later month
    if full['matched']:
        assert sorted(r['values'][0] for r in full['rows']) == ['2.50', '5']
        assert [r['group'][0] for r in arch['rows']] == ['Fictional Project A']


def test_chat_sentence_becomes_a_timesheet_draft(admin):
    install(admin, 'work')
    pid = project(admin)
    me = admin.get('/api/auth/me').json()['user']
    name = me.get('display_name') or me['username']
    r = write(admin, 'post', '/api/chat', {'message': f'Timesheet: {name} 6.5 hours on drawings yesterday for Fictional Project A'})
    assert r.status_code == 200, r.text
    reply = r.json()
    item = next(i for i in reply['preview']['items'] if i['item_type'] == 'metadata_record')
    assert item['after']['type_key'] == 'timesheet_entry' and item['after']['project_id'] == pid
    assert item['after']['values']['hours'] == '6.5' and item['after']['values']['activity'] == 'Drawings'
    assert item['after']['values']['employee'] == me['id']
    saved = write(admin, 'post', f'/api/tickets/{reply["ticket_id"]}/approve-and-save', {})
    assert saved.status_code == 200, saved.text
    with SessionLocal() as db:
        rec = db.scalar(select(FlexibleRecord).where(FlexibleRecord.record_type == 'timesheet_entry'))
        assert rec.data['hours'] == '6.5000'


def test_chat_built_type_can_be_adopted(admin):
    with SessionLocal() as db:
        db.add(RecordType(key='client_visit_feedback', title='client visit feedback', status='active', design={
            'table_name': 'client_visit_feedback', 'fields': [
                {'name': 'visit_date', 'type': 'date', 'required_level': 'draft', 'meaning': 'Visit date'},
                {'name': 'comments', 'type': 'text', 'required_level': 'optional', 'meaning': 'Comments'},
                {'name': 'extra_attributes', 'type': 'jsonb', 'universal': True}]}))
        db.commit()
    assert 'client_visit_feedback' in [t['key'] for t in admin.get('/api/graph/catalog').json()['legacy_types']]
    save(admin, propose(admin, 'metadata_type_adopt', {'type_key': 'client_visit_feedback'}))
    with SessionLocal() as db:
        fields = db.get(RecordType, 'client_visit_feedback').design['runtime_fields']
    assert [(f['name'], f['type'], f['required']) for f in fields] == [('visit_date', 'date', True), ('comments', 'text', False)]
    rec = save(admin, propose(admin, 'metadata_record', {'type_key': 'client_visit_feedback', 'project_id': None,
                                                         'values': {'visit_date': '2026-11-12', 'comments': 'Liked the veneer'}}))
    assert admin.get(f'/api/graph/record/{rec["id"]}').status_code == 200

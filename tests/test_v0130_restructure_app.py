"""v0.13.0 safe restructuring (app level; needs FastAPI + SQLAlchemy; runs in CI, NOT RUN in the build
sandbox).

Rename a field: records, report and rule follow in the same Admin ticket, a backup is taken, history
keeps the old values; undo by ticket brings back the same data; a blocked change is refused; a
manager cannot approve; the people pack upgrades from version 1 to 2 by one ticket. Fictional data,
disposable database."""
import json

from sqlalchemy import select

from .conftest import write
from .test_v098_universal_accounting import propose, save, project
from .test_v0100_one_graph import add_user, client_for
from studioos.db import (SessionLocal, FlexibleRecord, RecordType, UniversalPackInstall, UniversalRecordRevision,
                         UniversalTypeChange, UniversalPackInstall as PI)
from studioos import graph_query as gq


def _install(admin, key):
    pack = next(p for p in admin.get('/api/graph/catalog').json()['packs'] if p['key'] == key)
    return save(admin, propose(admin, 'metadata_pack_install', {'pack': key, 'version': pack['version'], 'sha256': pack['sha256']}))


def test_rename_field_follows_everywhere_and_undoes_exactly(admin):
    _install(admin, 'work')
    pa = project(admin)
    owner = add_user(admin, 'ravi.kumar', 'architect')
    ids = [save(admin, propose(admin, 'metadata_record', {'type_key': 'work_issue', 'project_id': pa, 'values': {
        'title': f'Fictional issue {i}', 'owner': owner, 'severity': 'High', 'issue_status': 'Open'}}))['id'] for i in range(3)]
    with SessionLocal() as db:
        before = {i: json.dumps(db.get(FlexibleRecord, i).data) for i in ids}
    report_before = admin.get('/api/graph/reports/open_issues_by_owner/run').json()['rows']
    pv = write(admin, 'post', '/api/restructure/draft', {'text': 'rename field severity to priority in work issue'}).json()
    assert pv['blockers'] == [] and 'open_issues_by_owner' in pv['impact']['reports']
    save(admin, propose(admin, 'metadata_type_change', pv['change']))
    with SessionLocal() as db:
        assert all('priority' in db.get(FlexibleRecord, i).data for i in ids)
        assert db.scalars(select(UniversalRecordRevision).where(UniversalRecordRevision.record_id == ids[0])).all()[-1].before_data['severity'] == 'High'
        assert 'priority' in [f['name'] for f in db.get(RecordType, 'work_issue').design['runtime_fields']]
        assert gq.report_definition(db, db.get(gq.UniversalReport, 'open_issues_by_owner'))['group_by'][1] == 'priority'
        change = db.scalar(select(UniversalTypeChange))
    assert admin.get('/api/graph/reports/open_issues_by_owner/run').json()['rows'] == report_before
    save(admin, propose(admin, 'metadata_type_change_undo', {'change_id': change.id}))
    with SessionLocal() as db:
        assert {i: json.dumps(db.get(FlexibleRecord, i).data) for i in ids} == before
        assert 'severity' in [f['name'] for f in db.get(RecordType, 'work_issue').design['runtime_fields']]
    again = write(admin, 'post', '/api/universal/proposals', {'kind': 'metadata_type_change_undo', 'data': {'change_id': change.id}, 'evidence': 'fictional test evidence'})
    assert again.status_code == 422


def test_blocked_changes_and_admin_only(admin):
    _install(admin, 'work')
    blocked = write(admin, 'post', '/api/universal/proposals', {'kind': 'metadata_type_change',
                    'data': {'op': 'remove_field', 'type_key': 'work_issue', 'field': 'severity'}, 'evidence': 'fictional test evidence'})
    assert blocked.status_code == 422 and 'cannot be approved' in blocked.text
    add_user(admin, 'meera.iyer', 'manager')
    mgr = client_for('meera.iyer')
    assert mgr.post('/api/restructure/preview', json={'change': {}}, headers={'X-CSRF-Token': mgr.cookies.get('studioos_csrf', '')}).status_code == 403
    p = write(mgr, 'post', '/api/universal/proposals', {'kind': 'metadata_type_change',
              'data': {'op': 'rename_type', 'type_key': 'work_issue', 'new_title': 'Snag'}, 'evidence': 'fictional test evidence'})
    if p.status_code == 200:
        assert write(mgr, 'post', f'/api/tickets/{p.json()["ticket_id"]}/approve-and-save', {}).status_code == 403
    ledger = write(admin, 'post', '/api/universal/proposals', {'kind': 'metadata_type_change',
                   'data': {'op': 'rename_type', 'type_key': 'gl_accounts', 'new_title': 'Accounts'}, 'evidence': 'fictional test evidence'})
    assert ledger.status_code == 422


def test_people_pack_upgrades_from_version_one(admin):
    """A firm that installed People v1 (before v0.11.0) upgrades to v2: staff can read their own records."""
    pack = next(p for p in admin.get('/api/graph/catalog').json()['packs'] if p['key'] == 'people')
    assert pack['version'] == 2
    # simulate the v1 install: the same types without self_read
    v1 = gq.available_packs()['people']['pack']
    import copy
    types = copy.deepcopy(v1['types'])
    for t in types:
        t.pop('self_read', None)
        save(admin, propose(admin, 'metadata_type', t))
    with SessionLocal() as db:
        from studioos.db import ApprovalTicket
        tid = db.scalar(select(ApprovalTicket.id).order_by(ApprovalTicket.id.desc()))
        db.info.update(ticket_commit=True, ticket_item_id=1)
        db.add(PI(pack_key='people', version=1, sha256='0' * 64, ticket_id=tid)); db.commit()
    plan = admin.get('/api/restructure/pack-upgrade/people').json()
    assert [i['kind'] for i in plan['items']] == ['metadata_type_options'] * 4
    save(admin, propose(admin, 'metadata_pack_upgrade', {'pack': 'people', 'version': 2, 'sha256': plan['sha256']}))
    with SessionLocal() as db:
        assert db.get(RecordType, 'attendance_entry').design['self_read'] == {'field': 'employee'}
        assert {p.version for p in db.scalars(select(UniversalPackInstall).where(UniversalPackInstall.pack_key == 'people'))} == {1, 2}

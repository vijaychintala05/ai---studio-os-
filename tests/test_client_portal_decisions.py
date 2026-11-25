"""Client portal step 3: a client approves or asks for changes; the answer is permanent and tied to one version."""
import pytest
from sqlalchemy import select

from studioos import portal_sender
from studioos.client_portal_models import ClientDecision
from studioos.db import SessionLocal, Audit
from tests.conftest import write
from tests.test_v098_universal_accounting import propose, save
from tests.test_client_portal_foundation import portal_env, portal_client, _setup, _host, _sign_in  # noqa: F401
from tests.test_client_portal_content import pack, real_file, _doc  # noqa: F401


def _item(admin, pid, doc_id, title='Kitchen layout', needs=True, shared=True, release='Final'):
    v = {'title': title, 'kind': 'Drawing', 'file': doc_id, 'release': release, 'shared_with_client': shared, 'needs_client_approval': needs}
    return save(admin, propose(admin, 'metadata_record', {'type_key': 'client_deliverable', 'project_id': pid, 'values': v}))['id']


def _decide(client, slug, rid, decision, comment='', csrf=True):
    h = dict(_host(slug))
    if csrf:
        h['X-CSRF-Token'] = client.cookies.get('studioos_portal_csrf', '')
    return client.post(f'/portal-api/deliverables/{rid}/decision', json={'decision': decision, 'comment': comment}, headers=h)


def _state(client, slug, rid):
    items = client.get('/portal-api/deliverables', headers=_host(slug)).json()['items']
    return next(i for i in items if i['id'] == rid)['approval']


def test_client_approves_and_it_is_recorded_and_audited(admin, portal_client, pack):
    pid, cid = _setup(admin)
    rid = _item(admin, pid, _doc(pid))
    _sign_in(portal_client, 'villa-one')
    assert _state(portal_client, 'villa-one', rid)['state'] == 'pending'
    r = _decide(portal_client, 'villa-one', rid, 'approved')
    assert r.status_code == 200 and r.json()['approval']['state'] == 'approved'
    st = _state(portal_client, 'villa-one', rid)
    assert st['state'] == 'approved' and st['by'] == 'Asha Fictional'
    with SessionLocal() as db:
        row = db.scalar(select(ClientDecision))
        assert (row.project_id, row.record_id, row.contact_id, row.record_version) == (pid, rid, cid, 1)
        a = db.scalar(select(Audit).where(Audit.action == 'client_decision'))
        assert a.actor == f'client:{cid}' and a.chain_hash and 'approved' in a.description
    d = admin.get(f'/api/portal/{pid}/decisions').json()['decisions']
    assert len(d) == 1 and d[0]['deliverable'] == 'Kitchen layout' and d[0]['decision'] == 'approved'


def test_changes_need_a_comment_and_a_new_answer_is_a_new_row(admin, portal_client, pack):
    pid, _ = _setup(admin)
    rid = _item(admin, pid, _doc(pid))
    _sign_in(portal_client, 'villa-one')
    assert _decide(portal_client, 'villa-one', rid, 'changes_requested').status_code == 422
    assert _decide(portal_client, 'villa-one', rid, 'changes_requested', 'Move the sink to the east wall').status_code == 200
    assert _state(portal_client, 'villa-one', rid)['state'] == 'changes_requested'
    assert _decide(portal_client, 'villa-one', rid, 'approved').status_code == 200   # changed their mind
    assert _state(portal_client, 'villa-one', rid)['state'] == 'approved'
    with SessionLocal() as db:
        assert [r.decision for r in db.scalars(select(ClientDecision).order_by(ClientDecision.id))] == ['changes_requested', 'approved']


def test_a_double_tap_records_nothing_new(admin, portal_client, pack):
    pid, _ = _setup(admin)
    rid = _item(admin, pid, _doc(pid))
    _sign_in(portal_client, 'villa-one')
    for _ in range(3):
        assert _decide(portal_client, 'villa-one', rid, 'approved').status_code == 200
    with SessionLocal() as db:
        assert len(db.scalars(select(ClientDecision)).all()) == 1


def test_a_decision_is_tied_to_the_version_the_client_saw(admin, portal_client, pack):
    pid, _ = _setup(admin)
    rid = _item(admin, pid, _doc(pid))
    _sign_in(portal_client, 'villa-one')
    _decide(portal_client, 'villa-one', rid, 'approved')
    # staff change the item (a new approved version): the old approval no longer counts
    v = {'title': 'Kitchen layout v2', 'kind': 'Drawing', 'file': _doc(pid, n=9), 'release': 'Final', 'shared_with_client': True, 'needs_client_approval': True}
    save(admin, propose(admin, 'metadata_record_update', {'type_key': 'client_deliverable', 'record_id': rid, 'project_id': pid,
                                                           'expected_version': 1, 'values': v}))
    st = _state(portal_client, 'villa-one', rid)
    assert st['state'] == 'pending' and st['earlier_version'] is True
    _decide(portal_client, 'villa-one', rid, 'approved')
    with SessionLocal() as db:
        assert [r.record_version for r in db.scalars(select(ClientDecision).order_by(ClientDecision.id))] == [1, 2]


def test_nothing_to_decide_when_approval_was_not_asked(admin, portal_client, pack):
    pid, _ = _setup(admin)
    rid = _item(admin, pid, _doc(pid), needs=False)
    _sign_in(portal_client, 'villa-one')
    assert _decide(portal_client, 'villa-one', rid, 'approved').status_code == 404
    assert portal_client.get('/portal-api/deliverables', headers=_host('villa-one')).json()['items'][0]['approval'] is None


def test_cannot_decide_on_hidden_or_other_projects_items(admin, portal_client, pack):
    p1, _ = _setup(admin)
    p2, _ = _setup(admin, name='Villa Two', slug='villa-two', phone='9123456780', email='ravi@example.test')
    draft = _item(admin, p1, _doc(p1, n=1), release='Draft')
    unshared = _item(admin, p1, _doc(p1, n=2), shared=False)
    other = _item(admin, p2, _doc(p2, n=3))
    _sign_in(portal_client, 'villa-one')
    for rid in (draft, unshared, other, 999999):
        assert _decide(portal_client, 'villa-one', rid, 'approved').status_code == 404
    with SessionLocal() as db:
        assert db.scalars(select(ClientDecision)).all() == []


def test_csrf_and_sign_in_are_required(admin, portal_client, pack):
    pid, _ = _setup(admin)
    rid = _item(admin, pid, _doc(pid))
    assert _decide(portal_client, 'villa-one', rid, 'approved', csrf=False).status_code == 401   # not signed in
    _sign_in(portal_client, 'villa-one')
    assert _decide(portal_client, 'villa-one', rid, 'approved', csrf=False).status_code == 403
    assert _decide(portal_client, 'villa-one', rid, 'maybe').status_code == 422


def test_a_switched_off_contact_cannot_decide(admin, portal_client, pack):
    pid, cid = _setup(admin)
    rid = _item(admin, pid, _doc(pid))
    _sign_in(portal_client, 'villa-one')
    write(admin, 'patch', f'/api/portal/{pid}/contacts/{cid}', {'active': False})
    assert _decide(portal_client, 'villa-one', rid, 'approved').status_code == 401


def test_decisions_cannot_be_edited_or_deleted(admin, portal_client, pack):
    pid, _ = _setup(admin)
    rid = _item(admin, pid, _doc(pid))
    _sign_in(portal_client, 'villa-one')
    _decide(portal_client, 'villa-one', rid, 'approved')
    with SessionLocal() as db:
        row = db.scalar(select(ClientDecision))
        row.decision = 'changes_requested'
        with pytest.raises(PermissionError):
            db.flush()
        db.rollback()
    with SessionLocal() as db:
        db.delete(db.scalar(select(ClientDecision)))
        with pytest.raises(PermissionError):
            db.flush()
        db.rollback()


def test_hourly_limit(admin, portal_client, pack, monkeypatch):
    monkeypatch.setattr('studioos.client_portal_content.PER_HOUR', 2)
    pid, _ = _setup(admin)
    rid = _item(admin, pid, _doc(pid))
    _sign_in(portal_client, 'villa-one')
    assert _decide(portal_client, 'villa-one', rid, 'changes_requested', 'one more thing').status_code == 200
    assert _decide(portal_client, 'villa-one', rid, 'approved').status_code == 200
    assert _decide(portal_client, 'villa-one', rid, 'changes_requested', 'actually, a change').status_code == 429


def test_staff_list_needs_staff_login(admin, portal_client, pack):
    pid, _ = _setup(admin)
    assert portal_client.get(f'/api/portal/{pid}/decisions').status_code == 401

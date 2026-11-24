"""Client portal step 2: a client sees only Final + shared deliverables of their own project. Fictional data only."""
from pathlib import Path

import pytest
from sqlalchemy import select, inspect

from studioos import portal_sender
from studioos.db import SessionLocal, Document, FlexibleRecord, Audit, engine
from tests.conftest import write
from tests.test_v098_universal_accounting import propose, save
from tests.test_v0100_one_graph import install
from tests.test_client_portal_foundation import portal_env, portal_client, _setup, _host, _sign_in  # noqa: F401

HEX = 'a' * 64


@pytest.fixture
def pack(admin):
    before = set(inspect(engine).get_table_names())
    install(admin, 'client_portal')
    assert set(inspect(engine).get_table_names()) == before   # a pack adds no tables


@pytest.fixture
def real_file(monkeypatch, tmp_path):
    f = tmp_path / 'render.png'
    f.write_bytes(b'fictional-render-bytes')
    monkeypatch.setattr('studioos.intake_documents.approved_source', lambda db, doc: (f, doc.name, HEX))
    return f


def _doc(pid, name='Living room render.png', n=1):
    with SessionLocal() as db:
        d = Document(project_id=pid, name=name, relative_path=f'intake/{n:064x}', doc_type='png', size_bytes=22)
        db.add(d); db.commit()
        return d.id


def _deliverable(admin, pid, doc_id, title='Living room render', status='Final', shared=True, note=''):
    values = {'title': title, 'kind': 'Render', 'file': doc_id, 'release': status, 'shared_with_client': shared}
    if note:
        values['note_for_client'] = note
    return save(admin, propose(admin, 'metadata_record', {'type_key': 'client_deliverable', 'project_id': pid, 'values': values}))['id']


def _titles(client, slug):
    r = client.get('/portal-api/deliverables', headers=_host(slug))
    assert r.status_code == 200, r.text
    return sorted(i['title'] for i in r.json()['items'])


def test_only_final_and_shared_items_are_visible(admin, portal_client, pack):
    pid, _ = _setup(admin)
    _deliverable(admin, pid, _doc(pid, n=1), 'Final and shared', 'Final', True, note='Please review')
    _deliverable(admin, pid, _doc(pid, n=2), 'Final not shared', 'Final', False)
    _deliverable(admin, pid, _doc(pid, n=3), 'Draft shared', 'Draft', True)
    _deliverable(admin, pid, _doc(pid, n=4), 'Old version', 'Superseded', True)
    _sign_in(portal_client, 'villa-one')
    r = portal_client.get('/portal-api/deliverables', headers=_host('villa-one')).json()['items']
    assert [i['title'] for i in r] == ['Final and shared']
    assert r[0]['note'] == 'Please review' and r[0]['file_name'] == 'Living room render.png'
    assert set(r[0]) == {'id', 'title', 'kind', 'note', 'file_name', 'size_bytes', 'added'}   # no paths, no staff fields


def test_staff_can_withdraw_by_ticket_and_it_disappears(admin, portal_client, pack):
    pid, _ = _setup(admin)
    rid = _deliverable(admin, pid, _doc(pid), 'Plan A')
    _sign_in(portal_client, 'villa-one')
    assert _titles(portal_client, 'villa-one') == ['Plan A']
    save(admin, propose(admin, 'metadata_record_update', {'type_key': 'client_deliverable', 'record_id': rid, 'project_id': pid,
         'expected_version': 1, 'values': {'title': 'Plan A', 'kind': 'Render', 'file': _doc(pid, n=9), 'release': 'Superseded',
                                           'shared_with_client': True}}))
    assert _titles(portal_client, 'villa-one') == []


def test_a_client_never_sees_another_projects_items(admin, portal_client, pack, real_file):
    p1, _ = _setup(admin)
    p2, _ = _setup(admin, name='Villa Two', slug='villa-two', phone='9123456780', email='ravi@example.test')
    other = _deliverable(admin, p2, _doc(p2, 'Secret.png', n=5), 'Villa Two secret')
    _sign_in(portal_client, 'villa-one')
    h = _host('villa-one')
    assert _titles(portal_client, 'villa-one') == []
    # guessing the id of another project's item gives the same answer as a missing item
    assert portal_client.get(f'/portal-api/deliverables/{other}/file', headers=h).status_code == 404
    assert portal_client.get('/portal-api/deliverables/999999/file', headers=h).status_code == 404


def test_download_works_for_a_visible_item_and_is_logged(admin, portal_client, pack, real_file):
    pid, _ = _setup(admin)
    rid = _deliverable(admin, pid, _doc(pid))
    _sign_in(portal_client, 'villa-one')
    r = portal_client.get(f'/portal-api/deliverables/{rid}/file', headers=_host('villa-one'))
    assert r.status_code == 200 and r.content == b'fictional-render-bytes'
    assert r.headers['content-type'] == 'application/octet-stream'
    assert r.headers['x-content-type-options'] == 'nosniff' and 'sandbox' in r.headers['content-security-policy']
    assert 'attachment' in r.headers['content-disposition']
    with SessionLocal() as db:
        assert db.scalar(select(Audit).where(Audit.action == 'portal_file_opened', Audit.entity_id == rid)) is not None


def test_hidden_item_cannot_be_downloaded_by_id(admin, portal_client, pack, real_file):
    pid, _ = _setup(admin)
    draft = _deliverable(admin, pid, _doc(pid, n=1), 'Draft', 'Draft', True)
    unshared = _deliverable(admin, pid, _doc(pid, n=2), 'Unshared', 'Final', False)
    _sign_in(portal_client, 'villa-one')
    for rid in (draft, unshared):
        assert portal_client.get(f'/portal-api/deliverables/{rid}/file', headers=_host('villa-one')).status_code == 404


def test_deleted_item_is_hidden(admin, portal_client, pack, real_file):
    pid, _ = _setup(admin)
    rid = _deliverable(admin, pid, _doc(pid))
    with SessionLocal() as db:
        from studioos.db import now
        db.get(FlexibleRecord, rid).deleted_at = now(); db.commit()
    _sign_in(portal_client, 'villa-one')
    assert _titles(portal_client, 'villa-one') == []
    assert portal_client.get(f'/portal-api/deliverables/{rid}/file', headers=_host('villa-one')).status_code == 404


def test_file_from_another_project_or_no_project_is_never_served(admin, portal_client, pack, real_file):
    pid, _ = _setup(admin)
    rid = _deliverable(admin, pid, _doc(pid))
    with SessionLocal() as db:   # staff later re-file the document under another project, or none
        db.get(Document, db.get(FlexibleRecord, rid).data['file']).project_id = None; db.commit()
    _sign_in(portal_client, 'villa-one')
    assert _titles(portal_client, 'villa-one') == []
    assert portal_client.get(f'/portal-api/deliverables/{rid}/file', headers=_host('villa-one')).status_code == 404


def test_other_record_types_are_not_exposed(admin, portal_client, pack):
    pid, _ = _setup(admin)
    with SessionLocal() as db:   # a different record type that happens to carry the same field names
        db.add(FlexibleRecord(record_type='milestone', project_id=pid, data={'title': 'Internal', 'release': 'Final', 'shared_with_client': True, 'file': 1}))
        db.commit()
    _sign_in(portal_client, 'villa-one')
    assert _titles(portal_client, 'villa-one') == []


def test_file_not_an_approved_upload_is_not_served(admin, portal_client, pack):
    pid, _ = _setup(admin)
    with SessionLocal() as db:
        d = Document(project_id=pid, name='nas.pdf', relative_path='Projects/Villa One/nas.pdf', doc_type='pdf', size_bytes=1)
        db.add(d); db.commit(); doc_id = d.id
    rid = _deliverable(admin, pid, doc_id)
    _sign_in(portal_client, 'villa-one')
    assert portal_client.get(f'/portal-api/deliverables/{rid}/file', headers=_host('villa-one')).status_code == 404


def test_signed_out_and_staff_cookies_get_nothing(admin, portal_client, pack, real_file):
    pid, _ = _setup(admin)
    rid = _deliverable(admin, pid, _doc(pid))
    h = _host('villa-one')
    for path in ('/portal-api/deliverables', f'/portal-api/deliverables/{rid}/file'):
        assert portal_client.get(path, headers=h).status_code == 401
        assert admin.get(path, headers=h).status_code == 401     # the Admin's staff session is not a client session


def test_deliverable_routes_are_not_on_the_staff_address(admin, pack):
    assert admin.get('/portal-api/deliverables').status_code == 404

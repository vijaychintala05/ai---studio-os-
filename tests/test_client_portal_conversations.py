"""Client conversation records: summary + checklist + proof tags to exact client-chat messages. Fictional data only."""
import pytest
from sqlalchemy import select, text

from studioos import portal_sender
from studioos.client_portal_models import ClientChatMessage, ClientConversationProof
from studioos.db import SessionLocal, Document
from tests.conftest import write
from tests.test_v098_universal_accounting import propose, save
from tests.test_v0100_one_graph import add_user, client_for
from tests.test_client_portal_foundation import portal_env, portal_client, _setup, _host, _sign_in  # noqa: F401
from tests.test_client_portal_content import pack, real_file, _doc, _deliverable  # noqa: F401


def _talk(admin, portal_client, pid, slug='villa-one'):
    """Three messages: client, studio, client. Returns their ids."""
    h = {**_host(slug), 'X-CSRF-Token': portal_client.cookies.get('studioos_portal_csrf', '')}
    a = portal_client.post('/portal-api/chat', json={'body': 'Please move the sink to the east wall.'}, headers=h).json()['id']
    b = write(admin, 'post', f'/api/portal/{pid}/chat', {'body': 'Sure, we will send a revised layout by Friday.'}).json()['id']
    c = portal_client.post('/portal-api/chat', json={'body': 'Also add a socket near the window.'}, headers=h).json()['id']
    return a, b, c


def _record(admin, pid, ids, shared=True, actions=None, title='Kitchen changes agreed'):
    body = {'title': title, 'summary': 'Sink moves east; socket added by the window.', 'message_ids': ids, 'shared_with_client': shared,
            'actions': actions if actions is not None else [
                {'text': 'Send revised kitchen layout', 'message_ids': ids[:2], 'due_date': '2026-12-05'},
                {'text': 'Add a socket near the window', 'message_ids': [ids[2]]}]}
    r = write(admin, 'post', f'/api/portal/{pid}/conversation-records', body)
    assert r.status_code == 200, r.text
    ticket = r.json()
    x = write(admin, 'post', f'/api/tickets/{ticket["ticket_id"]}/approve-and-save', {})
    assert x.status_code == 200, x.text
    return x.json()['committed_records'][0]['id']


def _client_records(portal_client, slug='villa-one'):
    r = portal_client.get('/portal-api/conversations', headers=_host(slug))
    assert r.status_code == 200, r.text
    return r.json()['records']


@pytest.fixture
def world(admin, portal_client, pack):
    pid, cid = _setup(admin)
    _sign_in(portal_client, 'villa-one')
    ids = _talk(admin, portal_client, pid)
    return pid, ids


def test_record_with_checklist_and_proof_is_created_by_one_approved_ticket(admin, portal_client, world):
    pid, ids = world
    rid = _record(admin, pid, list(ids))
    rec = admin.get(f'/api/portal/{pid}/conversations').json()
    assert rec['thread_ok'] is True and len(rec['records']) == 1
    r = rec['records'][0]
    assert r['id'] == rid and r['shared_with_client'] is True
    assert [m['id'] for m in r['messages']] == list(ids) and all(m['verified'] for m in r['messages'])
    assert [(a['text'], a['state']) for a in r['actions']] == [('Send revised kitchen layout', 'Open'), ('Add a socket near the window', 'Open')]
    assert r['actions'][0]['message_ids'] == [ids[0], ids[1]] and r['actions'][1]['message_ids'] == [ids[2]]


def test_nothing_is_saved_until_a_person_approves(admin, portal_client, world):
    pid, ids = world
    body = {'title': 'Draft only', 'summary': 'Not yet approved', 'message_ids': list(ids), 'shared_with_client': True, 'actions': []}
    assert write(admin, 'post', f'/api/portal/{pid}/conversation-records', body).status_code == 200
    assert admin.get(f'/api/portal/{pid}/conversations').json()['records'] == []
    assert _client_records(portal_client) == []


def test_client_sees_only_shared_records(admin, portal_client, world):
    pid, ids = world
    _record(admin, pid, list(ids), shared=False, title='Internal only')
    _record(admin, pid, list(ids), shared=True, title='For the client')
    seen = _client_records(portal_client)
    assert [r['title'] for r in seen] == ['For the client']
    assert 'shared_with_client' not in seen[0]
    assert [m['body'] for m in seen[0]['messages']][0] == 'Please move the sink to the east wall.'


def test_other_projects_records_never_reach_a_client(admin, portal_client, world):
    pid, ids = world
    p2, _ = _setup(admin, name='Villa Two', slug='villa-two', phone='9123456780', email='ravi@example.test')
    c2 = _talk_for_other(admin, p2)
    _record(admin, p2, c2, title='Villa Two secret')
    assert _client_records(portal_client) == []
    assert portal_client.get('/portal-api/conversations', headers=_host('villa-two')).status_code == 401


def _talk_for_other(admin, pid):
    ids = []
    for t in ('one', 'two', 'three'):
        ids.append(write(admin, 'post', f'/api/portal/{pid}/chat', {'body': f'Villa Two {t}'}).json()['id'])
    return ids


def test_validation_rules(admin, portal_client, world):
    pid, ids = world
    p2, _ = _setup(admin, name='Villa Two', slug='villa-two', phone='9123456780', email='ravi@example.test')
    foreign = _talk_for_other(admin, p2)
    base = {'title': 'T title', 'summary': 'Summary text', 'message_ids': list(ids), 'shared_with_client': True, 'actions': []}

    def attempt(**changes):
        r = write(admin, 'post', f'/api/portal/{pid}/conversation-records', {**base, **changes})
        return r.status_code

    assert attempt(message_ids=foreign) == 422                                            # messages from another project's thread
    assert attempt(message_ids=[999999]) == 422
    assert attempt(message_ids=[]) == 422
    assert attempt(actions=[{'text': 'Do it', 'message_ids': [foreign[0]]}]) == 422       # cites a message not tagged on the record
    assert attempt(actions=[{'text': 'Do it', 'message_ids': []}]) == 422                 # every item needs proof
    assert attempt(actions=[{'text': 'Do it', 'message_ids': [ids[0]], 'owner': 99999}]) == 422
    assert attempt(actions=[{'text': 'Do it', 'message_ids': [ids[0]], 'due_date': '2026-13-45'}]) == 422
    assert attempt(actions=[{'text': 'Do it', 'message_ids': [ids[0]]}] * 31) == 422
    assert attempt() == 200
    assert attempt(actions=[{'text': 'Do it', 'message_ids': [ids[0]], 'owner': 1}]) == 200       # admin is staff on every project


def test_internal_chat_cannot_be_recorded(admin, portal_client, world):
    pid, ids = world
    internal = write(admin, 'post', f'/api/projects/{pid}/chat', {'body': 'INTERNAL talk'}).json()['id']
    body = {'title': 'Bad', 'summary': 'Bad one', 'message_ids': [internal + 1000], 'shared_with_client': False, 'actions': []}
    assert write(admin, 'post', f'/api/portal/{pid}/conversation-records', body).status_code == 422


def test_who_may_propose(admin, portal_client, world):
    pid, ids = world
    add_user(admin, 'eng.two', 'site_engineer'); add_user(admin, 'arch.two', 'architect')
    body = {'title': 'T title', 'summary': 'Summary text', 'message_ids': list(ids), 'shared_with_client': False, 'actions': []}
    assert write(client_for('eng.two'), 'post', f'/api/portal/{pid}/conversation-records', body).status_code == 403
    assert write(client_for('arch.two'), 'post', f'/api/portal/{pid}/conversation-records', body).status_code == 404   # not on this project
    assert write(portal_client, 'post', f'/api/portal/{pid}/conversation-records', body).status_code == 401


def test_tampering_with_a_tagged_message_is_detected_everywhere(admin, portal_client, world):
    pid, ids = world
    _record(admin, pid, list(ids))
    with SessionLocal() as db:   # a raw database edit that bypasses the application
        db.execute(text("UPDATE client_chat_messages SET body='We never agreed to that.' WHERE id=:i"), {'i': ids[0]}); db.commit()
    staff = admin.get(f'/api/portal/{pid}/conversations').json()
    assert staff['thread_ok'] is False and not any(m['verified'] for m in staff['records'][0]['messages'])
    assert not any(m['verified'] for m in _client_records(portal_client)[0]['messages'])


def test_proof_tags_are_permanent(admin, portal_client, world):
    pid, ids = world
    _record(admin, pid, list(ids))
    with SessionLocal() as db:
        p = db.scalar(select(ClientConversationProof)); p.chain_hash = 'f' * 64
        with pytest.raises(PermissionError):
            db.flush()
        db.rollback()
    with SessionLocal() as db:
        db.delete(db.scalar(select(ClientConversationProof)))
        with pytest.raises(PermissionError):
            db.flush()
        db.rollback()


def _update_action(admin, pid, action, **changes):
    d = dict(action['data'])
    d.update(changes)
    return save(admin, propose(admin, 'metadata_record_update', {'type_key': 'conversation_action', 'record_id': action['id'], 'project_id': pid,
                                                                  'expected_version': action['version'], 'values': d}))


def _action_rows():
    with SessionLocal() as db:
        from studioos.db import FlexibleRecord, UniversalRecordRevision
        from sqlalchemy import func
        out = []
        for a in db.scalars(select(FlexibleRecord).where(FlexibleRecord.record_type == 'conversation_action').order_by(FlexibleRecord.id)):
            v = db.scalar(select(func.max(UniversalRecordRevision.version)).where(UniversalRecordRevision.record_id == a.id))
            out.append({'id': a.id, 'data': dict(a.data), 'version': v})
        return out


def test_done_updates_show_the_client_the_file_that_addresses_the_conversation(admin, portal_client, world, real_file):
    pid, ids = world
    _record(admin, pid, list(ids))
    first = _action_rows()[0]
    final = _deliverable(admin, pid, _doc(pid, 'Revised kitchen layout.pdf', n=7), 'Revised kitchen layout', 'Final', True)
    draft = _deliverable(admin, pid, _doc(pid, 'Draft.pdf', n=8), 'Unfinished draft', 'Draft', True)
    upload = _doc(pid, 'Site photo of socket.png', n=9)
    second = _action_rows()[1]
    _update_action(admin, pid, first, progress='Done', resolution_note='Sent on Friday', resolution_deliverable=final)
    _update_action(admin, pid, second, progress='Done', resolution_note='Socket added', resolution_file=upload)
    rec = _client_records(portal_client)[0]
    a1, a2 = rec['actions']
    assert (a1['state'], a1['note'], a1['deliverable']) == ('Done', 'Sent on Friday', {'id': final, 'title': 'Revised kitchen layout'})
    assert a2['file'] == {'id': a2['id'], 'name': 'Site photo of socket.png'} and a2['deliverable'] is None
    # the client downloads the uploaded proof of work
    r = portal_client.get(f'/portal-api/conversations/actions/{a2["id"]}/file', headers=_host('villa-one'))
    assert r.status_code == 200 and r.content == b'fictional-render-bytes'
    assert 'sandbox' in r.headers['content-security-policy'] and 'attachment' in r.headers['content-disposition']
    # a draft file is never pointed at for a client, but staff do see it
    _update_action(admin, pid, _action_rows()[0], resolution_deliverable=draft)
    assert _client_records(portal_client)[0]['actions'][0]['deliverable'] is None
    staff = admin.get(f'/api/portal/{pid}/conversations').json()['records'][0]['actions'][0]
    assert staff['deliverable']['title'] == 'Unfinished draft'


def test_action_file_is_refused_when_not_allowed(admin, portal_client, world, real_file):
    pid, ids = world
    _record(admin, pid, list(ids), shared=False, title='Hidden record')
    action = _action_rows()[0]
    _update_action(admin, pid, action, resolution_file=_doc(pid, 'Proof.png', n=11))
    h = _host('villa-one')
    assert portal_client.get(f'/portal-api/conversations/actions/{action["id"]}/file', headers=h).status_code == 404   # record not shared
    assert portal_client.get('/portal-api/conversations/actions/999999/file', headers=h).status_code == 404
    other = _action_rows()[1]['id']
    assert portal_client.get(f'/portal-api/conversations/actions/{other}/file', headers=h).status_code == 404         # that action has no file


def test_signed_out_and_wrong_address(admin, portal_client, world):
    pid, ids = world
    _record(admin, pid, list(ids))
    portal_client.cookies.clear()
    assert portal_client.get('/portal-api/conversations', headers=_host('villa-one')).status_code == 401
    assert admin.get('/portal-api/conversations', headers=_host('villa-one')).status_code == 401
    assert admin.get('/portal-api/conversations').status_code == 404


def test_pack_must_be_installed(admin, portal_client):
    pid, _ = _setup(admin)
    _sign_in(portal_client, 'villa-one')
    ids = _talk(admin, portal_client, pid)
    body = {'title': 'T title', 'summary': 'Summary text', 'message_ids': list(ids), 'shared_with_client': True, 'actions': []}
    assert write(admin, 'post', f'/api/portal/{pid}/conversation-records', body).status_code == 422

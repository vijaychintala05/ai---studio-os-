"""Staff edit conversation records (eligible roles only, by approved ticket, history kept); clients are view-only but can ask anything in chat."""
import pytest
from sqlalchemy import select

from studioos import portal_sender
from studioos.db import SessionLocal, UniversalRecordRevision, FlexibleRecord, User
from tests import api_surface as S
from tests.conftest import write
from tests.test_v0100_one_graph import add_user, client_for
from tests.test_client_portal_foundation import portal_env, portal_client, _setup, _host, _sign_in  # noqa: F401
from tests.test_client_portal_content import pack, real_file, _doc, _deliverable  # noqa: F401
from tests.test_client_portal_conversations import (world, _record, _talk, _client_records, _action_rows, _update_action)  # noqa: F401


def _approve(admin, draft):
    x = write(admin, 'post', f'/api/tickets/{draft["ticket_id"]}/approve-and-save', {})
    assert x.status_code == 200, x.text
    return x


def _first_record_id():
    with SessionLocal() as db:
        return db.scalar(select(FlexibleRecord.id).where(FlexibleRecord.record_type == 'conversation_record').order_by(FlexibleRecord.id))


def test_staff_edit_a_record_by_ticket_and_history_is_kept(admin, portal_client, world):
    pid, ids = world
    rid = _record(admin, pid, list(ids))
    r = write(admin, 'post', f'/api/portal/{pid}/conversations/{rid}/edit', {'summary': 'Sink moves east; socket added; tap changed to matt black.'})
    assert r.status_code == 200, r.text
    assert _client_records(portal_client)[0]['summary'].startswith('Sink moves east; socket added by')   # not changed until approved
    _approve(admin, r.json())
    seen = _client_records(portal_client)[0]
    assert seen['summary'].endswith('matt black.') and seen['updated'] and seen['title'] == 'Kitchen changes agreed'
    with SessionLocal() as db:
        revs = db.scalars(select(UniversalRecordRevision).where(UniversalRecordRevision.record_id == rid).order_by(UniversalRecordRevision.version)).all()
        assert [x.version for x in revs] == [1, 2]
        assert revs[1].before_data['summary'].startswith('Sink moves east; socket added by')     # the old words are still on record


def test_unshare_a_record_by_edit(admin, portal_client, world):
    pid, ids = world
    rid = _record(admin, pid, list(ids))
    _approve(admin, write(admin, 'post', f'/api/portal/{pid}/conversations/{rid}/edit', {'shared_with_client': False}).json())
    assert _client_records(portal_client) == []


def test_staff_edit_a_checklist_item_and_clear_a_field(admin, portal_client, world, real_file):
    pid, ids = world
    _record(admin, pid, list(ids))
    first = _action_rows()[0]
    r = write(admin, 'post', f'/api/portal/{pid}/conversation-actions/{first["id"]}/edit',
              {'progress': 'Done', 'resolution_note': 'Sent by email on Friday', 'text': 'Send revised kitchen layout (v2)'})
    _approve(admin, r.json())
    a = _client_records(portal_client)[0]['actions'][0]
    assert (a['state'], a['note'], a['text']) == ('Done', 'Sent by email on Friday', 'Send revised kitchen layout (v2)')
    _approve(admin, write(admin, 'post', f'/api/portal/{pid}/conversation-actions/{first["id"]}/edit', {'progress': 'Open', 'clear': ['resolution_note', 'due_date']}).json())
    a = _client_records(portal_client)[0]['actions'][0]
    assert (a['state'], a['note'], a['due_date']) == ('Open', '', '')
    assert write(admin, 'post', f'/api/portal/{pid}/conversation-actions/{first["id"]}/edit', {}).status_code == 422


def test_add_checklist_items_to_an_existing_record_with_proof(admin, portal_client, world):
    pid, ids = world
    rid = _record(admin, pid, list(ids), actions=[{'text': 'First item', 'message_ids': [ids[0]]}])
    h = {**_host('villa-one'), 'X-CSRF-Token': portal_client.cookies.get('studioos_portal_csrf', '')}
    later = portal_client.post('/portal-api/chat', json={'body': 'One more thing: please repaint the hallway.'}, headers=h).json()['id']
    r = write(admin, 'post', f'/api/portal/{pid}/conversations/{rid}/add-items',
              {'message_ids': [later], 'actions': [{'text': 'Repaint the hallway', 'message_ids': [later]}]})
    assert r.status_code == 200, r.text
    _approve(admin, r.json())
    rec = _client_records(portal_client)[0]
    assert [a['text'] for a in rec['actions']] == ['First item', 'Repaint the hallway']
    assert later in [m['id'] for m in rec['messages']] and all(m['verified'] for m in rec['messages'])
    assert rec['actions'][1]['message_ids'] == [later]
    # an item may not cite a message that is not tagged on the record
    bad = write(admin, 'post', f'/api/portal/{pid}/conversations/{rid}/add-items', {'actions': [{'text': 'Bad item', 'message_ids': [later + 50]}]})
    assert bad.status_code == 422
    # a message from the thread that is not tagged yet needs to be listed first
    extra = write(admin, 'post', f'/api/portal/{pid}/conversations/{rid}/add-items', {'actions': [{'text': 'Needs tagging', 'message_ids': [ids[1]]}]})
    assert extra.status_code == 200      # ids[1] is already tagged on the record, so it can be cited


def test_only_eligible_staff_can_edit(admin, portal_client, world):
    pid, ids = world
    rid = _record(admin, pid, list(ids))
    act = _action_rows()[0]
    add_user(admin, 'eng.edit', 'site_engineer'); add_user(admin, 'acc.edit', 'accounts'); add_user(admin, 'arch.edit', 'architect')
    eng, acc, arch = client_for('eng.edit'), client_for('acc.edit'), client_for('arch.edit')
    paths = [(f'/api/portal/{pid}/conversations/{rid}/edit', {'title': 'Changed title'}),
             (f'/api/portal/{pid}/conversation-actions/{act["id"]}/edit', {'progress': 'Done'}),
             (f'/api/portal/{pid}/conversations/{rid}/add-items', {'actions': [{'text': 'New item', 'message_ids': [ids[0]]}]})]
    for who in (eng, acc):
        for path, body in paths:
            assert write(who, 'post', path, body).status_code == 403, (path,)
    for path, body in paths:                       # an architect who is not on this project cannot even see it
        assert write(arch, 'post', path, body).status_code == 404
    # assign the architect to the project: now eligible
    with SessionLocal() as db:
        arch_id = db.scalar(select(User.id).where(User.username == 'arch.edit'))
    assert write(admin, 'put', f'/api/projects/{pid}/members', {'user_ids': [arch_id]}).status_code == 200
    assert write(arch, 'post', paths[0][0], paths[0][1]).status_code == 200
    # not signed in at all
    assert write(portal_client, 'post', paths[0][0], paths[0][1]).status_code == 401


def test_the_general_ticket_route_cannot_be_used_to_get_around_it(admin, portal_client, world):
    pid, ids = world
    _record(admin, pid, list(ids))
    act = _action_rows()[0]
    add_user(admin, 'eng.edit2', 'site_engineer')
    eng = client_for('eng.edit2')
    with SessionLocal() as db:
        eng_id = db.scalar(select(User.id).where(User.username == 'eng.edit2'))
    assert write(admin, 'put', f'/api/projects/{pid}/members', {'user_ids': [eng_id]}).status_code == 200   # on the project, but not an eligible role
    d = dict(act['data']); d['progress'] = 'Done'
    r = write(eng, 'post', '/api/universal/proposals', {'kind': 'metadata_record_update', 'evidence': 'fictional test evidence',
              'data': {'type_key': 'conversation_action', 'record_id': act['id'], 'project_id': pid, 'expected_version': act['version'], 'values': d}})
    assert r.status_code == 422 and 'may not change client portal records' in r.text
    r2 = write(eng, 'post', '/api/universal/proposals', {'kind': 'metadata_record', 'evidence': 'fictional test evidence',
               'data': {'type_key': 'client_deliverable', 'project_id': pid, 'values': {'title': 'Sneaky', 'kind': 'Render', 'file': _doc(pid, n=33), 'release': 'Final', 'shared_with_client': True}}})
    assert r2.status_code == 422


def test_two_people_editing_at_once_cannot_overwrite_each_other(admin, portal_client, world):
    pid, ids = world
    rid = _record(admin, pid, list(ids))
    one = write(admin, 'post', f'/api/portal/{pid}/conversations/{rid}/edit', {'title': 'Title from person one'}).json()
    two = write(admin, 'post', f'/api/portal/{pid}/conversations/{rid}/edit', {'title': 'Title from person two'}).json()
    _approve(admin, one)
    stale = write(admin, 'post', f'/api/tickets/{two["ticket_id"]}/approve-and-save', {})
    assert stale.status_code in (409, 422) and 'tale' in stale.text
    assert _client_records(portal_client)[0]['title'] == 'Title from person one'


# ---------------------------------------------------------------- the client is view-only, but can ask anything

CLIENT_WRITES = {('POST', '/portal-api/login/request'), ('POST', '/portal-api/login/verify'), ('POST', '/portal-api/logout'),
                 ('POST', '/portal-api/chat'), ('POST', '/portal-api/deliverables/{record_id}/decision')}


def test_the_only_things_a_client_can_write_are_these_five():
    """A reviewed list. If a new portal route changes data, this test fails until the list (and its review) is updated."""
    found = {(m, r['path']) for r in S.current_surface()['routes'] if r['path'].startswith('/portal-api') for m in r['methods'] if m not in ('GET', 'HEAD')}
    assert found == CLIENT_WRITES


def test_a_client_cannot_change_a_record_in_any_way(admin, portal_client, world):
    pid, ids = world
    rid = _record(admin, pid, list(ids))
    act = _action_rows()[0]
    h = {**_host('villa-one'), 'X-CSRF-Token': portal_client.cookies.get('studioos_portal_csrf', '')}
    for method in ('post', 'put', 'patch', 'delete'):
        assert getattr(portal_client, method)('/portal-api/conversations', headers=h).status_code in (404, 405)
        assert getattr(portal_client, method)(f'/portal-api/conversations/{rid}', headers=h).status_code in (404, 405)
        assert getattr(portal_client, method)(f'/portal-api/conversations/actions/{act["id"]}', headers=h).status_code in (404, 405)
        # staff edit routes do not exist on a portal address, and a client session is not a staff session on the staff address
        assert getattr(portal_client, method)(f'/api/portal/{pid}/conversations/{rid}/edit', headers=h).status_code == 404
        assert getattr(portal_client, method)(f'/api/portal/{pid}/conversations/{rid}/edit').status_code in (401, 403, 405)
    with SessionLocal() as db:
        assert db.get(FlexibleRecord, rid).data['title'] == 'Kitchen changes agreed'


def test_a_client_can_ask_anything_in_chat(admin, portal_client, world):
    pid, ids = world
    _record(admin, pid, list(ids))
    h = {**_host('villa-one'), 'X-CSRF-Token': portal_client.cookies.get('studioos_portal_csrf', '')}
    for text in ('About “Kitchen changes agreed”: why is the socket not on the island?', 'Can I change the tile colour?',
                 'अभी बजट क्या है? 🙂', 'x' * 2000):
        assert portal_client.post('/portal-api/chat', json={'body': text}, headers=h).status_code == 200, text[:30]
    assert 'Kitchen changes agreed' in portal_client.get('/portal-api/chat', headers=_host('villa-one')).json()['messages'][-4]['body']
    assert portal_client.post('/portal-api/chat', json={'body': 'x' * 2001}, headers=h).status_code == 422
    # the studio sees the question in the same thread
    assert any('tile colour' in m['body'] for m in admin.get(f'/api/portal/{pid}/chat').json()['messages'])


def test_screens_offer_an_ask_button_on_everything():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / 'studioos' / 'static' / 'portal.js').read_text()
    assert js.count('askButton(') >= 4 and "tab-agreed" in js

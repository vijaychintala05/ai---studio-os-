"""Staff manage the files a client sees: list, add and edit as DRAFT tickets; only eligible staff; only this project's approved uploads."""
from sqlalchemy import select

from studioos.db import SessionLocal, Document, User
from tests.conftest import write
from tests.test_v0100_one_graph import add_user, client_for
from tests.test_client_portal_foundation import portal_env, portal_client, _setup, _host, _sign_in  # noqa: F401
from tests.test_client_portal_content import pack, real_file, _doc  # noqa: F401


def _approve(admin, draft):
    x = write(admin, 'post', f'/api/tickets/{draft["ticket_id"]}/approve-and-save', {})
    assert x.status_code == 200, x.text


def _body(doc, **kw):
    return {'title': 'Living room render', 'kind': 'Render', 'file': doc, 'release': 'Final', 'shared_with_client': True,
            'needs_client_approval': False, 'note_for_client': 'Final render', **kw}


def test_documents_list_only_this_projects_approved_uploads(admin, portal_client, pack):
    pid, _ = _setup(admin)
    p2, _ = _setup(admin, name='Villa Two', slug='villa-two', phone='9123456780', email='ravi@example.test')
    mine, other = _doc(pid, 'Mine.png', n=1), _doc(p2, 'Theirs.png', n=2)
    with SessionLocal() as db:
        db.add(Document(project_id=pid, name='nas-only.pdf', relative_path='Projects/Villa/nas-only.pdf', doc_type='pdf', size_bytes=5)); db.commit()
    names = [d['name'] for d in admin.get(f'/api/portal/{pid}/documents').json()['documents']]
    assert names == ['Mine.png']


def test_add_then_edit_a_file_by_draft_tickets(admin, portal_client, pack, real_file):
    pid, _ = _setup(admin)
    doc = _doc(pid)
    r = write(admin, 'post', f'/api/portal/{pid}/deliverables', _body(doc))
    assert r.status_code == 200, r.text
    assert admin.get(f'/api/portal/{pid}/deliverables').json()['deliverables'] == []      # a draft changes nothing
    _approve(admin, r.json())
    item = admin.get(f'/api/portal/{pid}/deliverables').json()['deliverables'][0]
    assert item['client_sees'] is True and item['file']['name'] == 'Living room render.png' and item['version'] == 1
    _sign_in(portal_client, 'villa-one')
    assert [i['title'] for i in portal_client.get('/portal-api/deliverables', headers=_host('villa-one')).json()['items']] == ['Living room render']
    e = write(admin, 'post', f'/api/portal/{pid}/deliverables/{item["id"]}/edit', {'release': 'Superseded', 'needs_client_approval': True})
    assert e.status_code == 200, e.text
    _approve(admin, e.json())
    item = admin.get(f'/api/portal/{pid}/deliverables').json()['deliverables'][0]
    assert (item['release'], item['client_sees'], item['version']) == ('Superseded', False, 2)
    assert portal_client.get('/portal-api/deliverables', headers=_host('villa-one')).json()['items'] == []
    assert write(admin, 'post', f'/api/portal/{pid}/deliverables/{item["id"]}/edit', {}).status_code == 422


def test_validation(admin, portal_client, pack):
    pid, _ = _setup(admin)
    p2, _ = _setup(admin, name='Villa Two', slug='villa-two', phone='9123456780', email='ravi@example.test')
    mine, theirs = _doc(pid, n=1), _doc(p2, n=2)
    assert write(admin, 'post', f'/api/portal/{pid}/deliverables', _body(theirs)).status_code == 422        # another project's file
    assert write(admin, 'post', f'/api/portal/{pid}/deliverables', _body(999999)).status_code == 422
    assert write(admin, 'post', f'/api/portal/{pid}/deliverables', _body(mine, kind='Invoice')).status_code == 422
    assert write(admin, 'post', f'/api/portal/{pid}/deliverables', _body(mine, release='Maybe')).status_code == 422
    assert write(admin, 'post', f'/api/portal/{pid}/deliverables', _body(mine, title='x')).status_code == 422
    assert write(admin, 'post', '/api/portal/999999/deliverables', _body(mine)).status_code == 404


def test_only_eligible_staff_and_project_scope(admin, portal_client, pack):
    pid, _ = _setup(admin)
    doc = _doc(pid)
    for role in ('site_engineer', 'accounts'):
        add_user(admin, f'{role}.files', role)
        c = client_for(f'{role}.files')
        assert write(c, 'post', f'/api/portal/{pid}/deliverables', _body(doc)).status_code == 403
        assert c.get(f'/api/portal/{pid}/deliverables').status_code == 403 and c.get(f'/api/portal/{pid}/documents').status_code == 403
    add_user(admin, 'arch.files', 'architect')
    arch = client_for('arch.files')
    assert write(arch, 'post', f'/api/portal/{pid}/deliverables', _body(doc)).status_code == 404       # not on the project
    assert arch.get(f'/api/portal/{pid}/deliverables').status_code == 404
    with SessionLocal() as db:
        aid = db.scalar(select(User.id).where(User.username == 'arch.files'))
    write(admin, 'put', f'/api/projects/{pid}/members', {'user_ids': [aid]})
    assert write(arch, 'post', f'/api/portal/{pid}/deliverables', _body(doc)).status_code == 200
    assert write(portal_client, 'post', f'/api/portal/{pid}/deliverables', _body(doc)).status_code == 401


def test_client_approval_state_is_visible_to_staff(admin, portal_client, pack, real_file):
    pid, _ = _setup(admin)
    _approve(admin, write(admin, 'post', f'/api/portal/{pid}/deliverables', _body(_doc(pid), needs_client_approval=True)).json())
    _sign_in(portal_client, 'villa-one')
    rid = admin.get(f'/api/portal/{pid}/deliverables').json()['deliverables'][0]['id']
    h = {**_host('villa-one'), 'X-CSRF-Token': portal_client.cookies.get('studioos_portal_csrf', '')}
    portal_client.post(f'/portal-api/deliverables/{rid}/decision', json={'decision': 'changes_requested', 'comment': 'Brighter please'}, headers=h)
    a = admin.get(f'/api/portal/{pid}/deliverables').json()['deliverables'][0]['approval']
    assert a['state'] == 'changes_requested' and a['comment'] == 'Brighter please' and a['by'] == 'Asha Fictional'

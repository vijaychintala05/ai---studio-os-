"""v0.26: "what is waiting for me" is counted by the server across ALL tickets, not just the page the screen loaded, and it
includes tickets that are approved but not yet saved. Fictional data only."""
from fastapi.testclient import TestClient
from studioos.main import app
from .conftest import write, approved_form


def login(name, pw):
    c = TestClient(app)
    assert c.post('/api/auth/login', json={'username': name, 'password': pw}).status_code == 200
    return c


def project(admin, name='Fictional Queue Site'):
    return approved_form(admin, 'post', '/api/projects', {'name': name, 'budget': '10000000'}).json()['id']


def draft_task(c, pid, title):
    r = write(c, 'post', '/api/tasks', {'project_id': pid, 'title': title})
    assert r.status_code == 200, r.text
    return r.json()


def test_nothing_waiting_is_a_real_zero(admin):
    q = admin.get('/api/work-queue').json()
    assert q['to_review'] == 0 and q['approved_to_save'] == 0 and q['parked'] == 0


def test_counts_every_ticket_not_only_a_page(admin):
    pid = project(admin)
    for i in range(7):
        draft_task(admin, pid, f'Fictional queue task {i}')
    assert admin.get('/api/work-queue').json()['to_review'] == 7
    assert len(admin.get('/api/tickets?limit=3').json()) == 3          # the list is paged, the count is not


def test_an_approved_ticket_waiting_to_be_saved_is_counted_separately(admin):
    pid = project(admin)
    a = draft_task(admin, pid, 'Fictional approve me')
    draft_task(admin, pid, 'Fictional still pending')
    assert write(admin, 'post', f'/api/tickets/items/{a["item_id"]}/approve', {'note': ''}).status_code == 200
    q = admin.get('/api/work-queue').json()
    assert q['to_review'] == 1 and q['approved_to_save'] == 1


def test_saved_and_rejected_tickets_are_not_counted(admin):
    pid = project(admin)
    saved = draft_task(admin, pid, 'Fictional saved one')
    assert write(admin, 'post', f'/api/tickets/{saved["ticket_id"]}/approve-and-save', {}).status_code == 200
    rejected = draft_task(admin, pid, 'Fictional rejected one')
    assert write(admin, 'post', f'/api/tickets/items/{rejected["item_id"]}/reject', {'note': ''}).status_code == 200
    q = admin.get('/api/work-queue').json()
    assert q['to_review'] == 0 and q['approved_to_save'] == 0


def test_other_people_see_only_their_own_tickets(admin):
    pid = project(admin)
    write(admin, 'post', '/api/users', {'username': 'wq_acc', 'display_name': 'Fictional Accounts', 'role': 'accounts', 'password': 'fictional-accounts-wq-1'})
    write(admin, 'post', '/api/users', {'username': 'wq_arch', 'display_name': 'Fictional Architect', 'role': 'architect', 'password': 'fictional-architect-wq-1'})
    users = {u['username']: u['id'] for u in admin.get('/api/users').json()}
    write(admin, 'put', f'/api/projects/{pid}/members', {'user_ids': [users['wq_arch']]})
    arch = login('wq_arch', 'fictional-architect-wq-1')
    draft_task(arch, pid, 'Fictional architect task')
    draft_task(admin, pid, 'Fictional owner task')
    assert arch.get('/api/work-queue').json()['to_review'] == 1         # only their own
    assert admin.get('/api/work-queue').json()['to_review'] == 2        # the owner sees all
    acc = login('wq_acc', 'fictional-accounts-wq-1')
    assert acc.get('/api/work-queue').json()['to_review'] == 0


def test_the_inbox_strip_uses_the_server_count_and_loads_it_with_every_refresh():
    import pathlib
    js = pathlib.Path('studioos/static/app.js').read_text()
    assert "'work-queue'" in js[js.index('function refreshKeys'):js.index('async function refresh()')]
    counts = js[js.index('function waitingCounts'):js.index('function waitingItems')]
    assert 'st.workQueue' in counts and 'wq.to_review' in counts          # the server's number wins over the loaded page

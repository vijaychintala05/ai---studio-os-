"""v0.24: each person can see, in plain words, what their role may approve. Fictional users only."""
from fastapi.testclient import TestClient
from studioos.main import app
from .conftest import write


def login(name, pw):
    c = TestClient(app)
    assert c.post('/api/auth/login', json={'username': name, 'password': pw}).status_code == 200
    return c


def test_owner_may_approve_everything_and_others_see_only_theirs(admin):
    for name, role in (('rights_mgr', 'manager'), ('rights_eng', 'site_engineer')):
        assert write(admin, 'post', '/api/users', {'username': name, 'display_name': name, 'role': role, 'password': f'fictional-{role}-rights-1'}).status_code == 200
    owner = admin.get('/api/my-approval-rights').json()
    assert owner['role'] == 'admin' and owner['can_approve_everything'] is True
    mgr = login('rights_mgr', 'fictional-manager-rights-1').get('/api/my-approval-rights').json()
    assert mgr['role'] == 'manager' and mgr['can_approve_everything'] is False
    assert 'own entries' in mgr['own_entry_rule'].lower() or 'someone else' in mgr['own_entry_rule'].lower()
    eng = login('rights_eng', 'fictional-site_engineer-rights-1').get('/api/my-approval-rights').json()
    assert eng['can_approve'] == [] and eng['money_limit_rupees'] is None


def test_manager_sees_the_money_limit_once_the_owner_sets_it(admin):
    write(admin, 'post', '/api/users', {'username': 'rights_mgr2', 'display_name': 'Rights Manager', 'role': 'manager', 'password': 'fictional-manager-rights-2'})
    m = login('rights_mgr2', 'fictional-manager-rights-2')
    assert m.get('/api/my-approval-rights').json()['money_limit_rupees'] is None
    write(admin, 'put', '/api/approval-limits', {'manager_per_transaction_paise': 500000})
    assert m.get('/api/my-approval-rights').json()['money_limit_rupees'] == 5000


def test_labels_are_plain_words_not_internal_names(admin):
    mgr_rows = admin.get('/api/my-approval-rights').json()
    assert all('_' not in label for label in mgr_rows['can_approve'])


def test_approval_screen_shows_the_panel():
    import pathlib
    js = pathlib.Path('studioos/static/app.js').read_text()
    assert 'my-approval-rights' in js and 'What you can approve' in js

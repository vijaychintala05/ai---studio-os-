"""v0.25: Part A of ROLE_MATRIX.md (what is built today) must match what the code actually allows.
If the code or the document changes alone, this test fails. Fictional users only."""
import pathlib
import re
import pytest
from fastapi.testclient import TestClient
from studioos.main import app
from studioos.security import FINANCE_READ, FINANCE_WRITE, APPROVERS
from .conftest import write, approved_form

DOC = pathlib.Path('ROLE_MATRIX.md').read_text()
ROLES = ['admin', 'manager', 'architect', 'site_engineer', 'accounts', 'viewer']


def part_a():
    block = DOC.split('## Part A')[1].split('## Part B')[0]
    rows = {}
    for line in block.splitlines():
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) == 7 and cells[0] not in ('Area', '---') and not cells[0].startswith('-'):
            rows[cells[0]] = dict(zip(ROLES, cells[1:]))
    return rows


def allowed(cell):
    return cell.startswith('Yes') or cell in ('All', 'Own', 'Everything') or cell.startswith('Drafts') or cell.startswith('Finance')


def roles_with(row):
    return {r for r, c in part_a()[row].items() if allowed(c)}


def test_the_table_was_read():
    assert {'Create a project', 'Post site reports', 'Approve money items'} <= set(part_a())


def test_money_permissions_in_code_match_the_document():
    assert set(FINANCE_READ) == roles_with('See costs, payments, budgets, ledger')
    assert set(FINANCE_WRITE) == roles_with('Draft costs and payments')
    assert set(APPROVERS) == roles_with('Approve money items')


@pytest.fixture
def people(admin):
    clients = {'admin': admin}
    pid = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Matrix Site', 'budget': '100000'}).json()['id']
    for role in ROLES[1:]:
        name = f'matrix_{role}'
        assert write(admin, 'post', '/api/users', {'username': name, 'display_name': role, 'role': role, 'password': f'fictional-{role}-pass-1'}).status_code == 200
        write(admin, 'put', f'/api/projects/{pid}/members', {'user_ids': [u['id'] for u in admin.get('/api/users').json() if u['username'] == name]})
        c = TestClient(app)
        assert c.post('/api/auth/login', json={'username': name, 'password': f'fictional-{role}-pass-1'}).status_code == 200
        clients[role] = c
    return clients, pid


def _ok(r):
    return r.status_code not in (401, 403)


def test_who_can_create_a_project_matches_the_document(people):
    clients, _ = people
    expected = roles_with('Create a project')
    for role, c in clients.items():
        r = write(c, 'post', '/api/projects', {'name': f'Fictional {role} Villa', 'budget': '1000'})
        assert _ok(r) == (role in expected), (role, r.status_code)


def test_who_can_post_a_site_report_matches_the_document(people):
    clients, pid = people
    expected = roles_with('Post site reports')
    for role, c in clients.items():
        r = write(c, 'post', '/api/site-reports', {'project_id': pid, 'note': 'Fictional slab poured'})
        assert _ok(r) == (role in expected), (role, r.status_code)


def test_who_can_see_costs_matches_the_document(people):
    clients, _ = people
    expected = roles_with('See costs, payments, budgets, ledger')
    for role, c in clients.items():
        assert _ok(c.get('/api/costs')) == (role in expected), role


def test_site_expense_and_manager_limit_rows_match_the_code(people):
    clients, pid = people
    expected = roles_with('Draft a small site expense (up to ₹5,000, own projects, waits for approval)')
    assert expected == {'admin', 'manager', 'site_engineer'}
    for role, c in clients.items():
        r = write(c, 'post', '/api/site-expenses', {'project_id': pid, 'title': 'Fictional tea', 'amount': '100', 'request_key': f'matrix-exp-{role}-0001'})
        assert _ok(r) == (role in expected), (role, r.status_code)
    assert "Yes, only up to the owner's limit" in part_a()['Approve money items']['manager']

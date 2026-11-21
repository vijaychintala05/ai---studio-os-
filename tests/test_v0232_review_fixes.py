"""Fixes from the code review of 20 Nov 2026: (1) a manager's monthly total must count approvals that are approved
but not yet saved, so approving several tickets before saving cannot pass the cap; (2) sign-out clears every
screen's data and late responses from an earlier session are ignored. Fictional data only."""
import pathlib
from fastapi.testclient import TestClient
from studioos.main import app
from .conftest import write, approved_form
from .test_v025_approval_limits import team, draft_cost, set_limits, login  # noqa: F401  (fixture reuse)


def test_monthly_total_counts_approved_but_unsaved_items(admin, team):
    pid, mgr, acc = team
    assert set_limits(admin, 500000, 600000).status_code == 200          # ₹6,000 a month each (paise)
    t1 = draft_cost(acc, pid, 4000)
    t2 = draft_cost(acc, pid, 3950)
    first = mgr.post(f'/api/tickets/items/{t1_item(admin, t1)}/approve', json={'note': ''}, headers={'X-CSRF-Token': mgr.cookies.get('studioos_csrf', '')})
    assert first.status_code == 200, first.text
    second = mgr.post(f'/api/tickets/items/{t1_item(admin, t2)}/approve', json={'note': ''}, headers={'X-CSRF-Token': mgr.cookies.get('studioos_csrf', '')})
    assert second.status_code == 403 and 'monthly' in second.text.lower(), second.text


def t1_item(client, ticket):
    return client.get(f'/api/tickets/{ticket}').json()['items'][0]['id']


def test_sign_out_clears_the_screens_data_in_the_page():
    js = pathlib.Path('studioos/static/app.js').read_text()
    assert 'function clearSessionData(' in js and 'clearSessionData();' in js[js.index('function showLogin('):js.index('function showLogin(') + 400]
    assert "state.session=(state.session||0)+1" in js or "state.session = (state.session || 0) + 1" in js


def test_late_responses_from_an_earlier_session_are_ignored():
    js = pathlib.Path('studioos/static/app.js').read_text()
    refresh = js[js.index('async function refresh()'):js.index('async function refresh()') + 900]
    assert 'const gen=state.session' in refresh and 'gen!==state.session' in refresh


def test_ticket_open_ignores_a_late_answer_from_an_earlier_session():
    js = pathlib.Path('studioos/static/app.js').read_text()
    assert "const gen=state.session;const t=await api('/api/tickets/'+b.dataset.id);if(gen!==state.session)return;" in js

"""v0.26: faster screens: a refresh asks only for what the open screen needs. NAS documents and agent data load when that screen opens."""
import json
import pathlib
import subprocess

JS = pathlib.Path('studioos/static/app.js').read_text()


def keys(view, role='admin', must2fa=False):
    fn = JS[JS.index('const VIEW_DATA'):JS.index('async function refresh()')]
    script = (f"const state={{view:{json.dumps(view)},user:{{role:{json.dumps(role)}}},mustSetup2fa:{json.dumps(must2fa)},ticketPageOffset:0}};"
              "const hasFinance=()=>['admin','manager','accounts'].includes(state.user.role);const isApprover=()=>['admin','manager'].includes(state.user.role);const isAdmin=()=>state.user.role==='admin';\n"
              + fn + "\nconsole.log(JSON.stringify(refreshKeys()));")
    return json.loads(subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True).stdout)


def test_ordinary_screens_do_not_load_documents_or_agents():
    k = keys('overview')
    assert 'documents' not in k and 'agents' not in k and 'schema-suggestions' not in k
    assert {'projects', 'summary', 'tasks', 'budgets', 'costs', 'approvals', 'users'} <= set(k)


def test_those_screens_load_their_data_when_opened():
    assert 'documents' in keys('documents')
    assert 'agents' in keys('agents')


def test_agents_data_is_only_asked_for_by_approvers():
    assert 'agents' not in keys('agents', role='site_engineer')
    assert 'documents' in keys('documents', role='site_engineer')


def test_setup_screen_still_asks_for_nothing_else():
    assert keys('overview', must2fa=True) == ['auth/2fa']


def test_switching_to_such_a_screen_triggers_a_load():
    assert "if(VIEW_DATA[v]&&state.user)refresh();" in JS

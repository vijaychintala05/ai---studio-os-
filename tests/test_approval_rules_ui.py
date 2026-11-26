"""Settings -> Approval rules (approvalrules.js), and that its fixed rows match what the server refuses."""
from tests.conftest import write
from tests.gk_harness import assert_wired, needs_node, run

SETUP = r"""
replies['/api/tickets/policy'] = {create_task: ['admin'], record_cost: ['accounts', 'admin'], finance_po: ['admin'], suggest_schema: ['admin']};
state.view = 'approvalrules';
"""


@needs_node
def test_editable_and_fixed_rows_and_saving_sends_the_whole_policy():
    got = run(['approvalrules.js'], SETUP + r"""
(async () => {
  const page = await settle(arView);
  GK_SCREENS.approvalrules.change.role({dataset: {type: 'create_task', role: 'manager'}, checked: true});
  GK_SCREENS.approvalrules.change.role({dataset: {type: 'record_cost', role: 'accounts'}, checked: false});
  await arSave();
  console.log(JSON.stringify({page, sent: calls.find(c => c[1] === 'PUT')}));
})();
""")
    page = got['page']
    assert 'data-type="create_task"' in page and 'data-type="finance_po"' not in page and 'Finance po' in page
    assert got['sent'][2] == {'approvers': {'create_task': ['admin', 'manager'], 'record_cost': ['admin'],
                                            'finance_po': ['admin'], 'suggest_schema': ['admin']}}


@needs_node
def test_screen_rule_for_admin_only_kinds_matches_the_server(admin):
    policy = admin.get('/api/tickets/policy').json()
    editable = run(['approvalrules.js'], f"console.log(JSON.stringify(Object.keys({policy!r}).filter(t => !arAdminOnly(t))));")
    # Every row the screen lets you edit must be accepted by the server with a second role ticked.
    body = {t: (['admin', 'manager'] if t in editable else ['admin']) for t in policy}
    assert write(admin, 'put', '/api/tickets/policy', {'approvers': body}).status_code == 200
    locked = next(t for t in policy if t not in editable)
    refused = write(admin, 'put', '/api/tickets/policy', {'approvers': {**body, locked: ['admin', 'manager']}})
    assert refused.status_code == 400


@needs_node
def test_only_the_admin_sees_it():
    got = run(['approvalrules.js'], r"""
state.user.role = 'manager'; state.view = 'approvalrules';
var out = '';
$ = () => ({set innerHTML(v) { out = v; }, set textContent(v) {}});
render();
console.log(JSON.stringify(out));
""")
    assert 'does not include this screen' in got


def test_wired():
    assert_wired('approvalrules.js', 'approvalrules', accounts=False)

"""Client portal staff screens: client decisions and adding checklist items (portal_admin.js). Fictional data."""
from tests.gk_harness import STATIC, needs_node, run


@needs_node
def test_decisions_and_new_items_use_the_server_shapes():
    got = run(['portal_admin.js'], r"""
state.user.role = 'manager';
state.pa = {pid: 7, records: {records: [{id: 3, messages: [{id: 11}, {id: 12}]}]}, picked: [], decisions: [
  {decision: 'changes_requested', deliverable: 'Fictional plan', version: 2, by: 'Fictional Client', at: '2026-10-01T10:00:00', comment: 'Move the door'}]};
paDrafted = async () => {};
replies['/api/portal/7/conversations/3/add-items'] = {ticket_id: 5};
(async () => {
  const page = paDecisions();
  await paSubmit({dataset: {paForm: 'add-items', id: '3'}, values: {actions: 'Send revised plan\n\nConfirm tile choice'}});
  console.log(JSON.stringify({page, sent: calls.find(c => c[1] === 'POST')}));
})();
""")
    assert 'Fictional plan' in got['page'] and 'Asked for changes' in got['page'] and 'Move the door' in got['page']
    body = got['sent'][2]
    assert body == {'message_ids': [], 'actions': [{'text': 'Send revised plan', 'message_ids': [11, 12]},
                                                   {'text': 'Confirm tile choice', 'message_ids': [11, 12]}]}


def test_decisions_are_asked_for_only_by_roles_the_server_allows():
    js = (STATIC / 'portal_admin.js').read_text(encoding='utf-8')
    assert "['admin', 'manager'].includes(state.user?.role)) a.decisions" in js and 'data-pa="add-items"' in js

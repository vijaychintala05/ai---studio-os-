"""Status and links, Admin tools and Record designer tools (moretools.js), with fictional data."""
from tests.gk_harness import assert_wired, needs_node, run

SETUP = r"""
state.users = [{id: 2, display_name: 'Fictional Person', active: true}];
state.tasks = [{id: 5, title: 'Fictional task', status: 'open'}];
state.costs = [{id: 8, title: 'Fictional old cost', amount: 120}];
replies['/api/rhythm/projects'] = {projects: [{project_id: 7, project: 'Fictional Villa', health: 'on_track'}]};
replies['/api/projects'] = [{id: 7, name: 'Fictional Villa'}];
replies['/api/universal/documents/due?project_id=7'] = {due: [{template_key: 'fictional_report', cadence: 'weekly', due_at: '2026-10-01T00:00:00', is_due: true}]};
replies['/api/universal/types'] = [{key: 'fictional_type', label: 'Fictional type'}];
replies['/api/universal/records/fictional_type'] = [{id: 3, title: 'Fictional record'}];
replies['/api/universal/links/from/3'] = [{to: 'x'}];
replies['/api/graph/links-from/system.task/5'] = [{to: 'y'}];
replies['/api/graph/catalog'] = {packs: [{key: 'fictional_pack', title: 'Fictional pack'}]};
replies['/api/graph/packs/fictional_pack'] = {installed: false};
replies['/api/graph/systems'] = [{key: 'system.task'}];
replies['/api/system/integrity'] = {ok: true};
replies['/api/rhythm/run/rhythm_morning'] = {ran: true};
replies['/api/graph/rules/run'] = {made: 0};
replies['/api/intake/senders'] = {saved: true};
replies['/api/intake/email/poll'] = {created: 0};
replies['/api/costs/8/correct'] = {ticket_id: 99};
replies['/api/new-types/inbox'] = [{id: 4, raw_payload: {text: 'Fictional register'}, state: 'parked', attachments: [{sha256: 'abc', filename: 'fictional.csv'}], proposal: {fields: [{name: 'ref'}]}}];
replies['/api/new-types/dictionary'] = {ref: 'text'};
replies['/api/new-types/approved-designs'] = [];
replies['/api/new-types/4/capability'] = {capability: null};
replies['/api/new-types/4/validate-record'] = {valid: true};
replies['/api/new-types/4/capability-preview'] = {valid: true};
replies['/api/new-types/4/propose-required-rule-change'] = {ticket_id: 100};
replies['/api/new-types/analyze-capability'] = {decision: 'new_type'};
const posts = () => calls.filter(c => c[1] === 'POST').map(c => [c[0], c[2]]);
"""


@needs_node
def test_status_documents_due_and_links():
    got = run(['moretools.js'], SETUP + r"""
state.view = 'projectstatus';
(async () => {
  await settle(mtStatusView);
  const s = GK_SCREENS.projectstatus.submit;
  await s.linksFrom({values: {from: 'system.task:5'}});
  await s.recordLinks({values: {record: '3'}});
  console.log(JSON.stringify(await settle(mtStatusView)));
})();
""")
    for text in ('Fictional Villa', 'health: on_track', 'fictional_report', 'Due now', 'Fictional record', 'Fictional task'):
        assert text in got, text


@needs_node
def test_admin_tools_call_the_right_endpoints():
    got = run(['moretools.js'], SETUP + r"""
state.view = 'admintools';
(async () => {
  const page = await settle(mtAdminView);
  const s = GK_SCREENS.admintools;
  await s.click.integrity();
  await s.click.job({dataset: {job: 'rhythm_morning'}});
  await s.click.rules();
  await s.click.poll();
  await s.submit.sender({values: {address: 'someone@example.test', user_id: '2'}});
  await s.submit.correct({values: {cost: '8', amount: '100', reason: 'Fictional mistake'}});
  await s.submit.pack({values: {key: 'fictional_pack'}});
  console.log(JSON.stringify({page, posts: posts(), urls: calls.map(c => c[0])}));
})();
""")
    assert 'Fictional pack' in got['page'] and 'Fictional old cost' in got['page']
    assert {'/api/system/integrity', '/api/graph/packs/fictional_pack'} <= set(got['urls'])
    posts = dict(got['posts'])
    assert posts['/api/costs/8/correct'] == {'new_amount': '100', 'reason': 'Fictional mistake'}
    assert posts['/api/intake/senders'] == {'address': 'someone@example.test', 'user_id': 2}
    assert {'/api/rhythm/run/rhythm_morning', '/api/graph/rules/run', '/api/intake/email/poll'} <= set(posts)


@needs_node
def test_record_designer_tools():
    got = run(['moretools.js'], SETUP + r"""
state.view = 'typetools';
(async () => {
  const page = await settle(mtTypesView);
  const s = GK_SCREENS.typetools;
  await s.click.capability();
  await s.submit.record({values: {record: '{"ref": "x"}', mode: 'validate-record'}});
  await s.submit.record({values: {record: '{}', mode: 'capability-preview'}});
  await s.submit.rule({values: {field: 'ref', required_level: 'approve', impact_plan: 'Older fictional records stay valid.'}});
  await s.submit.analyse({values: {text: 'A fictional register'}});
  console.log(JSON.stringify({page, posts: posts()}));
})();
""")
    assert '/api/new-types/4/attachments/abc' in got['page'] and 'Fictional register' in got['page']
    posts = dict(got['posts'])
    assert posts['/api/new-types/4/validate-record'] == {'record': {'ref': 'x'}, 'phase': 'approve'}
    assert posts['/api/new-types/4/propose-required-rule-change']['required_level'] == 'approve'
    assert '/api/new-types/4/capability-preview' in posts and posts['/api/new-types/analyze-capability'] == {'text': 'A fictional register'}


def test_wired():
    for view in ('projectstatus', 'admintools', 'typetools'):
        assert_wired('moretools.js', view, accounts=False)

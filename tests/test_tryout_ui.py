"""Settings -> Try before proposing (tryout.js): previews send the server's request shapes and save nothing."""
from tests.gk_harness import assert_wired, needs_node, run

SETUP = r"""
replies['/api/viewspecs'] = [{key: 'fictional_view', name: 'Fictional view'}];
replies['/api/viewspecs/primitives'] = {primitives: ['table'], field_kinds: ['text'], colour_tokens: ['good']};
replies['/api/viewspecs/fictional_view'] = {versions: [{version: 2, created_by: 'fictional', created_at: '2026-10-01'}]};
replies['/api/viewspecs/fictional_view/versions/2'] = {version: 2, spec: {name: 'Older fictional'}};
replies['/api/universal/types'] = [{key: 'fictional_type', label: 'Fictional type'}];
replies['/api/views/layout/fictional_type'] = {layout: {columns: 1}};
replies['/api/views/layout/fictional_type/suggest'] = {layout: {columns: 2}, source: 'offline'};
replies['/api/viewspecs/validate'] = {valid: true, errors: [], diff: []};
replies['/api/viewspecs/propose'] = {ticket_id: 91};
replies['/api/graph/reports/preview'] = {rows: []};
replies['/api/restructure/preview'] = {summary: 'x'};
replies['/api/work/workflows/dry-run'] = {ok: true, visited: []};
replies['/api/work/workflows/wf/available?status=open'] = {transitions: []};
replies['/api/work/transitions?workflow_key=wf&target_id=3'] = [];
state.view = 'tryout';
"""


@needs_node
def test_history_layout_and_previews():
    got = run(['tryout.js'], SETUP + r"""
(async () => {
  await settle(toView_);
  const s = GK_SCREENS.tryout;
  await s.click.version({dataset: {version: '2'}});
  await s.click.suggest({dataset: {}});
  await s.submit.validate({values: {spec: '{"id": "v"}'}});
  await s.submit.report({values: {definition: '{"a": 1}'}});
  await s.submit.restructure({values: {change: '{"b": 2}'}});
  await s.submit.dryrun({values: {definition: '{"c": 3}', path: '[{"s": 1}]'}});
  await s.submit.available({values: {key: 'wf', status: 'open'}});
  await s.submit.history({values: {key: 'wf', target: '3'}});
  const page = await settle(toView_);
  await s.click.proposeView({dataset: {}});
  let bad = '';
  try { await s.submit.report({values: {definition: 'not json'}}); } catch (e) { bad = e.message; }
  console.log(JSON.stringify({page, bad, posts: calls.filter(c => c[1] === 'POST').map(c => [c[0], c[2]])}));
})();
""")
    assert 'Older fictional' in got['page'] and 'Draft this new view' in got['page'] and 'table' in got['page']
    posts = dict(got['posts'])
    assert posts['/api/viewspecs/validate'] == {'spec': {'id': 'v'}}
    assert posts['/api/graph/reports/preview'] == {'definition': {'a': 1}}
    assert posts['/api/restructure/preview'] == {'change': {'b': 2}}
    assert posts['/api/work/workflows/dry-run'] == {'definition': {'c': 3}, 'path': [{'s': 1}]}
    assert posts['/api/viewspecs/propose'] == {'kind': 'view_create', 'data': {'spec': {'id': 'v'}, 'scope': 'user'}}
    assert 'not valid JSON' in got['bad']


def test_wired():
    assert_wired('tryout.js', 'tryout', accounts=False)

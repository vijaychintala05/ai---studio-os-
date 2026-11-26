"""Money -> Tax rules (taxrules.js): list, what applies on a date, add and retire drafts. Fictional data."""
from tests.gk_harness import assert_wired, needs_node, run

SETUP = r"""
replies['/api/tax-rules'] = [{id: 4, kind: 'rate', key: 'gst_fictional', scope: '', value: {basis_points: 1800}, effective_from: '2026-04-01'}];
replies['/api/tax-rules/resolve?kind=rate&key=gst_fictional&on_date=2026-05-01&scope='] = {rule: {id: 4, value: {basis_points: 1800}, effective_from: '2026-04-01', scope: ''}};
replies['/api/tax-rules/propose'] = {ticket_id: 61};
state.view = 'taxrules';
"""
SHIM = "var URLSearchParams = class { constructor(o) { this.o = o; } toString() { return Object.entries(this.o).map(([k, v]) => k + '=' + encodeURIComponent(v)).join('&'); } };\n"


@needs_node
def test_lists_rules_resolves_and_drafts():
    got = run(['taxrules.js'], SHIM + SETUP + r"""
(async () => {
  await settle(trView);
  const s = GK_SCREENS.taxrules;
  await s.submit.resolve({values: {kind: 'rate', key: 'gst_fictional', on_date: '2026-05-01', scope: ''}});
  const page = await settle(trView);
  await s.submit.add({values: {kind: 'threshold', key: 'fictional_limit', scope: 'vendor:6', value: 'paise = 3000000\nnote = test only', effective_from: '2026-04-01'}});
  await s.click.retire({dataset: {id: '4'}});
  console.log(JSON.stringify({page, sent: calls.filter(c => c[0] === '/api/tax-rules/propose').map(c => c[2])}));
})();
""")
    assert 'basis_points = 1800' in got['page'] and 'Applies:' in got['page'] and 'data-gk-click="retire"' in got['page']
    assert got['sent'] == [
        {'kind': 'tax_rule_add', 'data': {'kind': 'threshold', 'key': 'fictional_limit', 'scope': 'vendor:6',
                                          'value': {'paise': 3000000, 'note': 'test only'}, 'effective_from': '2026-04-01'}},
        {'kind': 'tax_rule_retire', 'data': {'rule_id': 4}},
    ]


@needs_node
def test_decimal_values_are_refused_before_sending():
    got = run(['taxrules.js'], r"""
let message = '';
try { trParseValue('rate = 18.5'); } catch (e) { message = e.message; }
console.log(JSON.stringify(message));
""")
    assert 'whole numbers' in got


@needs_node
def test_manager_can_read_but_not_change():
    got = run(['taxrules.js'], SETUP + r"""
state.user.role = 'manager';
(async () => { console.log(JSON.stringify(await settle(trView))); })();
""")
    assert 'gst_fictional' in got and 'data-gk-click="retire"' not in got and 'Draft new rule' not in got


def test_wired():
    assert_wired('taxrules.js', 'taxrules')

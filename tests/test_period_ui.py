"""Money -> Period close (period.js): locks, legal holds, tax registrations and the locked-date warning. Fictional data."""
from tests.gk_harness import assert_wired, needs_node, run

SETUP = r"""
replies['/api/sales/options'] = {companies: [{id: 2, name: 'Fictional Studio'}], clients: [{id: 5, name: 'Fictional Client'}], vendors: [{id: 6, name: 'Fictional Vendor'}]};
replies['/api/period/locks?entity_id=2'] = [{id: 9, year_month: '2026-09', area: 'purchases', locked_by: 'fictional', reason: 'Filed', open: true}];
replies['/api/period/holds'] = [{id: 3, project_id: 7, reason: 'Fictional dispute', placed_by: 'fictional', active: true}];
replies['/api/projects'] = [{id: 7, name: 'Fictional Villa'}];
replies['/api/period/tax-profiles?party_id=5'] = [{registration_type: 'composition', effective_from: '2026-04-01'}];
replies['/api/period/propose'] = {ticket_id: 55};
replies['/api/books/home'] = {companies: [{entity_id: 2}]};
state.view = 'periodclose';
"""
@needs_node
def test_shows_locks_holds_and_registrations():
    got = run(['period.js'], SETUP + r"""
(async () => { console.log(JSON.stringify(await settle(pcView))); })();
""")
    for text in ('2026-09', 'Purchases', 'Locked', 'Fictional Villa', 'Fictional dispute', 'Composition', 'Draft month lock', 'data-gk-click="reopen"'):
        assert text in got, text


@needs_node
def test_only_the_admin_can_reopen_or_hold():
    got = run(['period.js'], SETUP + r"""
state.user.role = 'accounts';
(async () => { console.log(JSON.stringify(await settle(pcView))); })();
""")
    assert 'data-gk-click="reopen"' not in got and 'Draft legal hold' not in got and 'Draft month lock' in got


@needs_node
def test_drafts_use_the_server_field_names_and_reopen_needs_a_reason():
    got = run(['period.js'], SETUP + r"""
(async () => {
  await settle(pcView);
  const s = GK_SCREENS.periodclose;
  await s.submit.lock({values: {year_month: '2026-10', area: 'sales', reason: 'Returns filed'}});
  replies.reason = 'no';
  await s.click.reopen({dataset: {id: '9'}});
  replies.reason = 'Fictional correction needed';
  await s.click.reopen({dataset: {id: '9'}});
  console.log(JSON.stringify(calls.filter(c => c[0] === '/api/period/propose').map(c => c[2])));
})();
""")
    assert got == [
        {'kind': 'period_area_lock', 'data': {'entity_id': 2, 'year_month': '2026-10', 'area': 'sales', 'reason': 'Returns filed'}},
        {'kind': 'period_area_reopen', 'data': {'lock_id': 9, 'reason': 'Fictional correction needed'}},
    ]


@needs_node
def test_a_locked_date_on_a_money_form_warns():
    got = run(['period.js'], SETUP + r"""
replies['/api/period/check?entity_id=2&area=purchases&document_date=2026-09-03'] = {locked: true, why: 'September 2026 is closed.'};
state.view = 'books';
(async () => {
  await pcWarn({type: 'date', name: 'bill_date', value: '2026-09-03', form: null});
  await pcWarn({type: 'date', name: 'valid_until', value: '2026-09-03', form: null});
  console.log(JSON.stringify(calls.filter(c => c[0] === 'notify')));
})();
""")
    assert len(got) == 1 and 'September 2026 is closed' in got[0][1] and got[0][2] is True


def test_wired():
    assert_wired('period.js', 'periodclose')

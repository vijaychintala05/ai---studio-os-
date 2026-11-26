"""The screens' fit with the SENSE design, and the three endpoints that version added. Fictional data."""
from tests.gk_harness import STATIC, assert_wired, needs_node, run

@needs_node
def test_related_screens_share_a_tab_and_show_their_own_tab_bar():
    nav = (STATIC / 'nav.js').read_text(encoding='utf-8')
    for inside in ("view: 'moneyfiles'", "view: 'periodclose'", "view: 'taxrules'", "view: 'findetail'"):
        line = next(x for x in nav.splitlines() if inside in x)
        assert "inside: 'bankfeed'" in line, line
    assert 'class="sense-tabs"' in nav and '.filter(t => !t.inside)' in nav


@needs_node
def test_sections_are_pills_and_only_the_chosen_one_is_drawn():
    got = run([], r"""
state.gk.ui.sectionAll = false;
const draw = () => gkSections('x', [['a', 'First', () => 'AAA'], ['b', 'Second', () => 'BBB']]);
const before = draw();
GK_SCREENS._any.click.section({dataset: {key: 'x', id: 'b'}});
console.log(JSON.stringify({before, after: draw()}));
""")
    assert 'sense-filter-pill active' in got['before'] and 'AAA' in got['before'] and 'BBB' not in got['before']
    assert 'BBB' in got['after'] and 'AAA' not in got['after']


@needs_node
def test_a_draft_offers_the_review_sheet():
    got = run([], r"""
let offered = null;
var senseOfferImmediateReview = (ticket, what) => { offered = [ticket, what]; };
replies['/api/x'] = {ticket_id: 12};
(async () => { await gkDraft('/api/x', {}, 'Thing drafted'); console.log(JSON.stringify(offered)); })();
""")
    assert got == [12, 'Thing drafted']


@needs_node
def test_account_change_drafts_with_the_server_fields():
    got = run(['accountedit.js'], r"""
state.coa = {entity: {id: 2}, chart: {tree: [{id: 5, code: '6100', name: 'Fictional costs', children: [{id: 6, code: '6110', name: 'Fictional child'}]}]}};
replies['/api/books/accounts/update'] = {ticket_id: 3};
(async () => {
  const page = aePanel();
  await GK_SCREENS._any.submit.account({values: {account_id: '6', description: '', is_active: 'false', why: 'Fictional tidy'}});
  console.log(JSON.stringify({page, sent: calls.find(c => c[1] === 'POST')[2]}));
})();
""")
    assert 'Fictional child' in got['page']
    assert {k: v for k, v in got['sent'].items() if k != 'request_key'} == {'entity_id': 2, 'account_id': 6, 'is_active': False, 'why': 'Fictional tidy'}


def test_gstr1_and_reconciliation_statement_are_offered():
    assert "['gstr1', 'GSTR-1']" in (STATIC / 'reports.js').read_text(encoding='utf-8')
    assert "['brs', 'Reconciliation statement']" in (STATIC / 'bankfeed.js').read_text(encoding='utf-8')


def test_wired():
    assert_wired('accountedit.js')

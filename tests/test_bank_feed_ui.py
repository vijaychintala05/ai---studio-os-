"""Bank feed screen (studioos/static/bankfeed.js), run in node with fictional banks, lines and book entries.

The server side of these endpoints is covered by tests/test_m2_bank_feed.py and the bank reconciliation tests.
This file checks what the page shows and what it sends: exact matches only, one entry per line, a reason for
un-matching, and that the old type-the-IDs prompts are gone.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / 'studioos' / 'static'
needs_node = pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')

HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const calls = [];
const listeners = {};
const replies = {};
const ctx = vm.createContext({
  assert, calls, replies, console, JSON, Promise, Number, String, Object, Math, Date, Set,
  state: {user: {role: 'admin'}, view: 'bankfeed'},
  esc: s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;'),
  inr: n => 'Rs ' + n, pill: (label, tone) => `<span class="tag ${tone}">${label}</span>`,
  head: (title, sub) => `<h1>${title}</h1><p>${sub}</p>`,
  notify: (message, error) => calls.push(['notify', message, Boolean(error)]),
  askText: async () => replies.reason, updateIdentity() {}, $: () => ({}),
  render() {}, switchView() {}, refresh() { calls.push(['refresh']); },
  document: {body: {classList: {remove() {}}}, addEventListener: (type, fn) => { listeners[type] = fn; }, getElementById: () => null},
  FormData: class { constructor(form) { this.v = form.values; } get(k) { return this.v[k]; } },
  async api(url, opts = {}) {
    calls.push([url, opts.method || 'GET', opts.body ? JSON.parse(opts.body) : null]);
    if (url in replies) return replies[url];
    throw new Error('unexpected call ' + url);
  },
});
ctx.listeners = listeners;
vm.runInContext(fs.readFileSync(SCRIPT_PATH, 'utf8'), ctx);
vm.runInContext(TEST_BODY, ctx);
"""


def run(body):
    program = (HARNESS.replace('SCRIPT_PATH', json.dumps(str(STATIC / 'bankfeed.js')))
               .replace('TEST_BODY', json.dumps(body)))
    out = subprocess.run(['node', '-'], input=program, capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert out.returncode == 0, out.stderr
    return out.stdout


SETUP = r"""
replies['/api/books/home'] = {companies: [{entity_id: 2, name: 'Fictional Studio', banks: [{id: 51, name: 'Fictional Bank', masked: 'xx01', balance_paise: 0}]}]};
replies['/api/sales/options'] = {accounts: [{id: 70, entity_id: 2, code: '6100', name: 'Fictional Office Costs'}]};
replies['/api/books/bank-feed/51'] = {bank: {id: 51, entity_id: 2}, rules: [], reconciliations: [{id: 9, statement_line_id: 4, journal_id: 30, unreconciled: true}],
  uncategorised: [
    {id: 11, booking_date: '2026-11-03', statement_reference: 'FICTIONAL-UTR-001', signed_amount_paise: -250000,
     match_suggestions: [{journal_id: 31, posted_date: '2026-11-02', memo: 'SUPPLIER_PAYMENT_POSTED', signed_amount_paise: -250000, confidence: 'exact', diff_paise: 0, day_gap: 1},
                         {journal_id: 32, posted_date: '2026-11-03', memo: 'MANUAL_JOURNAL', signed_amount_paise: -250300, confidence: 'near', diff_paise: 300, day_gap: 0}],
     rule_suggestion: {rule_id: 5, match_text: 'FICTIONAL', suggested_account_id: 70}},
    {id: 12, booking_date: '2026-11-04', statement_reference: 'FICTIONAL-UTR-002', signed_amount_paise: 90000, match_suggestions: [], rule_suggestion: null}]};
"""


@needs_node
def test_feed_shows_lines_and_only_exact_matches_can_be_ticked():
    html = run(SETUP + r"""
(async () => {
  await bfInit();
  const page = bfView();
  console.log(JSON.stringify(page));
})();
""")
    page = json.loads(html)
    assert 'FICTIONAL-UTR-001' in page and 'FICTIONAL-UTR-002' in page
    assert 'Out Rs 2500' in page and 'In Rs 900' in page
    exact = re.search(r'<input type="checkbox"[^>]*data-journal="31"[^>]*>', page).group(0)
    near = re.search(r'<input type="checkbox"[^>]*data-journal="32"[^>]*>', page).group(0)
    assert 'disabled' not in exact and 'disabled' in near
    assert 'Only exact amounts can be matched' in page
    assert 'Rule “FICTIONAL” suggests 6100 Fictional Office Costs' in page
    assert 'Record the payment or receipt first' in page            # the line with no candidate
    assert 'Draft 0 matches for approval</button>' in page and 'data-bf="match" disabled' in page


@needs_node
def test_ticked_matches_are_sent_as_one_batch_with_one_entry_per_line():
    out = run(SETUP + r"""
replies['/api/finance-ledger/banks/51/reconciliation-draft'] = {ticket_id: 77, to_review: 1, status: 'draft'};
(async () => {
  await bfInit();
  bfTogglePick(11, 31, true);
  bfTogglePick(12, 31, true);          // the same book entry cannot match two lines: the later pick wins
  assert.deepEqual(state.bf.picked, {12: 31});
  bfTogglePick(11, 31, true);
  await bfDraftMatches();
  const sent = calls.find(c => c[0].endsWith('/reconciliation-draft'));
  console.log(JSON.stringify({sent, picked: state.bf.picked, refreshed: calls.some(c => c[0] === 'refresh'), note: calls.find(c => c[0] === 'notify')}));
})();
""")
    got = json.loads(out)
    assert got['sent'][1] == 'POST' and got['sent'][2] == {'matches': [{'statement_line_id': 11, 'journal_id': 31}]}
    assert got['picked'] == {} and got['refreshed']        # the new request shows in Change requests at once
    assert 'change request #77' in got['note'][1] and 'Nothing is matched until it is approved' in got['note'][1]


@needs_node
def test_unmatch_needs_a_reason_and_matched_tab_shows_undone_matches():
    out = run(SETUP + r"""
replies['/api/finance-ledger/bank-reconciliations/51'] = {total: 2, has_more: false, matches: [
  {id: 8, statement_line_id: 3, journal_id: 29, signed_amount_paise: 5000, statement_reference: 'FICTIONAL-UTR-OLD'},
  {id: 9, statement_line_id: 4, journal_id: 30, signed_amount_paise: -7000, statement_reference: 'FICTIONAL-UTR-UNDONE'}]};
replies['/api/books/bank-unreconcile'] = {ticket_id: 78};
(async () => {
  await bfInit();
  state.bf.tab = 'matched';
  await bfLoadTab();
  const page = bfView();
  replies.reason = 'no';
  await bfUnmatch(8);
  const refused = calls.filter(c => c[0] === '/api/books/bank-unreconcile').length;
  replies.reason = 'Matched to the wrong fictional payment';
  await bfUnmatch(8);
  console.log(JSON.stringify({page, refused, sent: calls.find(c => c[0] === '/api/books/bank-unreconcile')}));
})();
""")
    got = json.loads(out)
    assert 'data-bf="unmatch" data-id="8"' in got['page']
    assert 'data-id="9"' not in got['page'] and 'Un-matched' in got['page']
    assert got['refused'] == 0
    body = got['sent'][2]
    assert body['reconciliation_id'] == 8 and body['reason'] == 'Matched to the wrong fictional payment' and body['request_key']


@needs_node
def test_csv_import_sends_the_file_text_and_proof_document():
    out = run(SETUP + r"""
replies['/api/documents'] = [{id: 5, name: 'fictional-photo.jpg', doc_type: 'image'}, {id: 6, name: 'fictional-statement.pdf', doc_type: 'pdf'}];
replies['/api/books/bank-feed/51/import-csv'] = {ticket_id: 79, imported_count: 2, skipped_count: 1, status: 'draft'};
(async () => {
  await bfInit();
  state.bf.importOpen = true;
  state.bf.docs = await api('/api/documents');
  const before = bfImportHtml();
  state.bf.csv = {name: 'fictional.csv', text: 'date,reference,amount\n2026-11-05,FICTIONAL-UTR-003,-10.00\n', rows: 1};
  const ready = bfImportHtml();
  await bfDraftImport();
  console.log(JSON.stringify({before, ready, sent: calls.find(c => c[0].endsWith('/import-csv')), note: calls.filter(c => c[0] === 'notify').pop()}));
})();
""")
    got = json.loads(out)
    assert 'fictional-photo.jpg' not in got['ready'] and 'fictional-statement.pdf' in got['ready']   # only statement-type files are proof
    assert 'data-bf="import" disabled' in got['before'] and 'data-bf="import" disabled' not in got['ready']
    body = got['sent'][2]
    assert body['evidence_document_id'] == 6 and 'FICTIONAL-UTR-003' in body['csv_text'] and body['request_key']
    assert 'change request #79' in got['note'][1] and '1 already brought in were skipped' in got['note'][1]


@needs_node
def test_rule_form_drafts_a_suggest_only_rule():
    out = run(SETUP + r"""
replies['/api/books/bank-rules'] = {ticket_id: 80};
(async () => {
  await bfInit();
  state.bf.ruleFor = 11;
  const page = bfView();
  await bfDraftRule({values: {match_text: ' FICTIONAL-UTR ', direction: 'outflow', suggested_account_id: '70', note: ''}});
  console.log(JSON.stringify({page, sent: calls.find(c => c[0] === '/api/books/bank-rules')}))
})();
""")
    got = json.loads(out)
    assert 'never adds or matches anything by itself' in got['page']
    assert got['sent'][2] == {'entity_id': 2, 'bank_id': 51, 'match_text': 'FICTIONAL-UTR', 'direction': 'outflow',
                              'suggested_account_id': 70, 'note': '', 'request_key': got['sent'][2]['request_key']}


@needs_node
def test_people_outside_owner_and_accounts_see_no_bank_feed():
    out = run(r"""state.user.role = 'manager'; console.log(JSON.stringify(bfView()));""")
    assert 'for the owner and accounts' in json.loads(out)


def test_bank_feed_is_wired_into_the_page_and_menus():
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    order = re.findall(r'<script src="/static/([^"]+)"', html)
    assert order.index('books.js') < order.index('bankfeed.js') < order.index('shell.js')
    nav = (STATIC / 'nav.js').read_text(encoding='utf-8')
    assert "{view: 'bankfeed', label: 'Bank feed', need: 'books'" in nav
    assert "'bankfeed'" in (STATIC / 'interaction.js').read_text(encoding='utf-8')


def test_old_type_the_ids_prompts_for_bank_lines_are_gone():
    js = (STATIC / 'universal.js').read_text(encoding='utf-8')
    assert 'finance_reconcile_bank' not in js and 'finance_bank_statement_line' not in js
    assert "if(action==='finance-statement'||action==='finance-reconcile'){switchView('bankfeed');return;}" in js


def test_bank_feed_respects_strict_csp():
    js = (STATIC / 'bankfeed.js').read_text(encoding='utf-8')
    assert 'style="' not in js and not re.search(r'\son[a-z]+=', js)


@needs_node
def test_screen_reads_the_real_server_answers(admin, tmp_path, monkeypatch):
    """Build a fictional bank line and a matching payment through the real endpoints, then show them on the screen."""
    from tests.conftest import write
    from tests.test_m2_bill_form import _setup_company_and_vendor
    from tests.test_v0910_inventory_reconciliation import evidence_doc

    def approve(response):
        assert response.status_code == 200, response.text
        saved = write(admin, 'post', f'/api/tickets/{response.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'})
        assert saved.status_code == 200, saved.text

    entity_id, vendor_id, acc1, _, proj_id = _setup_company_and_vendor(admin)
    bank_id = admin.get('/api/books/home').json()['companies'][0]['banks'][0]['id']
    doc_id = evidence_doc(tmp_path, monkeypatch)
    approve(write(admin, 'post', '/api/books/bills', {
        'entity_id': entity_id, 'supplier_id': vendor_id, 'invoice_number': 'FICT-BFUI-1',
        'bill_date': '2026-11-10', 'due_date': '2026-12-10', 'payment_terms_days': 30, 'amount_paise': 50_000,
        'lines': [{'account_id': acc1, 'project_id': proj_id, 'description': 'Fictional item', 'amount_paise': 50_000}]}))
    due = admin.get('/api/books/bills-due').json()
    bill_id = (due['overdue'] + due['due_this_week'] + due['due_later'])[0]['bill_id']
    paying = next(a['id'] for a in due['paying_accounts'][str(entity_id)] if a['bank_id'] == bank_id)
    approve(write(admin, 'post', '/api/books/pay-selected', {
        'entity_id': entity_id, 'paid_through_id': paying, 'payment_date': '2026-11-12', 'payment_reference': 'UTR-BFUI-1',
        'items': [{'kind': 'direct_bill', 'bill_id': bill_id, 'amount_paise': 50_000}]}))
    approve(write(admin, 'post', f'/api/books/bank-feed/{bank_id}/import-csv', {
        'csv_text': 'Date,Reference,Debit,Credit\n2026-11-12,UTR-BFUI-1,500.00,\n', 'evidence_document_id': doc_id}))

    replies = {url: admin.get(url).json() for url in (
        '/api/books/home', '/api/sales/options', f'/api/books/bank-feed/{bank_id}',
        f'/api/finance-ledger/bank-statement-lines/{bank_id}', f'/api/finance-ledger/bank-book/{bank_id}')}
    out = run('Object.assign(replies, ' + json.dumps(replies) + r""");
(async () => {
  await bfInit();
  const feed = bfView();
  state.bf.tab = 'statement'; await bfLoadTab(); const statement = bfView();
  state.bf.tab = 'book'; await bfLoadTab(); const book = bfView();
  console.log(JSON.stringify({feed, statement, book, bank: state.bf.bankId}));
})();
""")
    got = json.loads(out)
    assert got['bank'] == bank_id
    assert 'UTR-BFUI-1' in got['feed'] and 'Out Rs 500' in got['feed']
    exact = re.search(r'<input type="checkbox"[^>]*data-line="\d+"[^>]*>', got['feed']).group(0)
    assert 'disabled' not in exact and pill_exact(got['feed'])
    assert 'UTR-BFUI-1' in got['statement'] and 'To match' in got['statement']
    assert 'Balance in the books' in got['book'] and 'Not matched' in got['book']


def pill_exact(page):
    return '<span class="tag good">Exact</span>' in page

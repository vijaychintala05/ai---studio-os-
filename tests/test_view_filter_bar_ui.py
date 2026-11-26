"""The filter bar and builder screen (static/viewbar.js), run in node with fictional view data: the query it sends, which
operators it offers, the chips, the builder's checks, and that it carries no inline scripts or styles. The page itself is
exercised in a real browser by the PR author; these pin the logic."""
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

STATIC = Path(__file__).resolve().parents[1] / 'studioos' / 'static'
SCRIPT = (STATIC / 'viewbar.js').read_text(encoding='utf-8')

pytestmark = pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')

PRELUDE = """
const state = {user: {id: 7, role: 'manager'}, nw: {}};
const document = {addEventListener() {}, querySelectorAll() { return []; }};
let renders = 0;
let render = () => { renders += 1; };
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const pill = (t, v) => `<span class="tag ${v}">${esc(t)}</span>`;
const vRender = s => `<div class="rendered">${esc(s && s.kind)}</div>`;
const notify = () => {};
const api = async () => ({});
"""

CAT = {'enabled': True, 'operators': {'text': ['contains', 'empty', 'eq', 'in', 'neq', 'not_empty'], 'date': ['after', 'before', 'empty', 'eq', 'neq', 'not_empty'],
                     'number': ['eq', 'gt', 'gte', 'lt', 'lte', 'neq', 'empty', 'not_empty'], 'select': ['eq', 'in', 'neq', 'empty', 'not_empty'],
                     'boolean': ['eq', 'neq'], 'relation': ['empty', 'not_empty']},
       'types': [{'key': 'system.task', 'title': 'Task', 'fields': [
           {'name': 'title', 'label': 'Title', 'kind': 'text'}, {'name': 'assignee', 'label': 'Assignee', 'kind': 'text'},
           {'name': 'due_date', 'label': 'Due date', 'kind': 'date'}, {'name': 'status', 'label': 'Status', 'kind': 'text'}]},
           {'key': 'snag', 'title': 'Snag', 'fields': [{'name': 'title', 'label': 'Title', 'kind': 'text'},
                                                       {'name': 'severity', 'label': 'Severity', 'kind': 'select', 'options': ['Low', 'High']},
                                                       {'name': 'raised', 'label': 'Raised', 'kind': 'date'}]}], 'looks': ['table', 'board', 'calendar']}
RAN = {'key': 'v', 'name': 'All tasks', 'version': 1, 'primitive': 'table', 'record_type': 'system.task', 'looks': ['table', 'board', 'calendar'], 'look': 'table',
       'filtered': False, 'filter_bar': True, 'shown': {'kind': 'table'},
       'fields': [{'name': 'title', 'kind': 'text'}, {'name': 'assignee', 'kind': 'text'}, {'name': 'due_date', 'kind': 'date'}, {'name': 'status', 'kind': 'text'}]}


def run(body):
    script = PRELUDE + SCRIPT + f"""
state.nw.ran = {json.dumps(RAN)};
state.nw.fb.catalog = {json.dumps(CAT)};
""" + body
    done = subprocess.run(['node', '-'], input=script, capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_query_has_only_finished_conditions_and_the_look():
    out = run("""
const fb = state.nw.fb, r = state.nw.ran;
fb.conds = [{field: 'assignee', op: 'eq', value: ' Ravi '}, {field: 'title', op: 'contains', value: ''}, {field: 'status', op: 'not_empty', value: ''}, {field: 'nope', op: 'eq', value: 'x'}];
const one = fbQuery(r);
fb.mode = 'or'; fb.look = 'board';
const two = fbQuery(r);
fb.conds = [{field: 'due_date', op: 'before', value: 'today'}]; fb.look = null;
const single = fbQuery(r);
fb.conds = [{field: 'title', op: 'in', value: 'a, b ,,c'}];
const list = fbQuery(r);
fb.conds = []; const none = fbQuery(r);
console.log(JSON.stringify({one, two, single, list, none}));""")
    q = lambda s: {k: v for k, v in (p.split('=', 1) for p in s.split('&') if p)}
    from urllib.parse import unquote_plus
    flt = lambda s: json.loads(unquote_plus(q(s)['filter']))
    assert flt(out['one']) == {'and': [{'field': 'assignee', 'op': 'eq', 'value': 'Ravi'}, {'field': 'status', 'op': 'not_empty'}]}
    assert flt(out['two']) == {'or': [{'field': 'assignee', 'op': 'eq', 'value': 'Ravi'}, {'field': 'status', 'op': 'not_empty'}]} and q(out['two'])['as'] == 'board'
    assert flt(out['single']) == {'field': 'due_date', 'op': 'before', 'value': 'today'}                       # one condition is sent bare
    assert flt(out['list']) == {'field': 'title', 'op': 'in', 'value': ['a', 'b', 'c']}
    assert out['none'] == ''


def test_each_row_offers_only_the_operators_its_field_allows():
    out = run("""
const fields = state.nw.ran.fields.map(f => ({...f, label: fbLabel(f.name)}));
const html = fbRows([{field: 'due_date', op: 'before', value: ''}, {field: 'assignee', op: 'eq', value: ''}], fields, state.nw.fb.catalog.operators, 'bar');
const opsOf = i => [...html.split('<div class="fb-row">')[i + 1].matchAll(/<option value="([a-z_]+)"[^>]*>(?:is|is not|is one of|contains|is empty|is filled in|is more than|is at least|is less than|is at most|is before|is after)</g)].map(m => m[1]);
console.log(JSON.stringify({date: opsOf(0), text: opsOf(1), dateInput: html.includes('data-fb="shortcut"'), textShortcut: html.split('<div class="fb-row">')[2].includes('shortcut')}));""")
    assert out['date'] == ['after', 'before', 'empty', 'eq', 'neq', 'not_empty'] and 'between' not in out['date']
    assert out['text'] == ['contains', 'empty', 'eq', 'in', 'neq', 'not_empty']
    assert out['dateInput'] is True and out['textShortcut'] is False                                           # date shortcuts only on dates


def test_a_select_field_offers_its_choices_and_no_value_for_empty():
    out = run("""
const f = {name: 'severity', kind: 'select', label: 'Severity', options: ['Low', 'High']};
console.log(JSON.stringify({choice: fbValueControl({op: 'eq', value: 'High'}, f, 'data-i="0"'), none: fbValueControl({op: 'empty', value: ''}, f, 'data-i="0"')}));""")
    assert '<option value="High" selected>' in out['choice'] and '<option value="Low">' in out['choice'] and out['none'] == ''


def test_the_sentence_says_what_is_shown_in_plain_words():
    out = run("""
const fb = state.nw.fb, r = state.nw.ran;
fb.conds = [{field: 'assignee', op: 'eq', value: 'Ravi'}, {field: 'due_date', op: 'before', value: 'today'}];
const all = fbWords(r); fb.mode = 'or'; const any = fbWords(r); fb.conds = []; const none = fbWords(r);
console.log(JSON.stringify({all, any, none}));""")
    assert out['all'] == 'Showing records where assignee is Ravi and due date is before today.'
    assert out['any'] == 'Showing records where assignee is Ravi or due date is before today.' and out['none'] == ''


def test_quick_filter_chips_leave_out_finished_work_and_cover_the_right_days():
    out = run("""
const names = ['title', 'due_date', 'status'];
console.log(JSON.stringify({overdue: FB_CHIPS.overdue('due_date', names), plain: FB_CHIPS.overdue('due_date', ['title', 'due_date']),
  week: FB_CHIPS.week('due_date', names), next7: FB_CHIPS.next7('due_date', names), chips: fbChips(state.nw.ran),
  none: fbChips({fields: [{name: 'title', kind: 'text'}]})}));""")
    assert out['overdue'] == [{'field': 'due_date', 'op': 'before', 'value': 'today'}, {'field': 'status', 'op': 'neq', 'value': 'done'}]
    assert out['plain'] == [{'field': 'due_date', 'op': 'before', 'value': 'today'}]                           # no status shown: nothing to leave out
    assert out['week'] == [{'field': 'due_date', 'op': 'after', 'value': 'week_start-1'}, {'field': 'due_date', 'op': 'before', 'value': 'week_start+7'}]
    assert out['next7'] == [{'field': 'due_date', 'op': 'after', 'value': 'today-1'}, {'field': 'due_date', 'op': 'before', 'value': 'today+8'}]
    assert 'Due this week' in out['chips'] and out['none'] == ''                                               # no date field: no date chips


def test_the_owners_switch_hides_the_bar_and_the_builder_and_only_the_owner_sees_it():
    out = run("""
const off = fbBar({...state.nw.ran, filter_bar: false});
const results = {};
state.nw.fb.catalog = {...state.nw.fb.catalog, enabled: false};
for (const role of ['admin', 'manager', 'viewer']) { state.user.role = role; const html = fbBuilderPanel(); results[role] = {turnOn: html.includes('data-on="true"'), builder: html.includes('New view')}; }
state.nw.fb.catalog = {...state.nw.fb.catalog, enabled: true};
state.user.role = 'admin'; const onAdmin = fbBuilderPanel();
state.user.role = 'manager'; const onManager = fbBuilderPanel();
console.log(JSON.stringify({off, results, turnOff: onAdmin.includes('data-on="false"') && onAdmin.includes('New view'), manager: onManager.includes('New view') && !onManager.includes('data-fb="switch"')}));""")
    assert out['off'] == ''
    assert out['results'] == {'admin': {'turnOn': True, 'builder': False}, 'manager': {'turnOn': False, 'builder': False}, 'viewer': {'turnOn': False, 'builder': False}}
    assert out['turnOff'] is True and out['manager'] is True                                                    # the owner can turn it off; a manager just builds


def test_the_bar_shows_looks_only_when_there_is_a_choice():
    out = run("""
const many = fbBar(state.nw.ran);
const one = fbBar({...state.nw.ran, looks: ['table']});
const feed = fbBar({...state.nw.ran, fields: []});
console.log(JSON.stringify({many: many.includes('data-look="board"'), pressed: many.includes('data-look="table" aria-pressed="true"'), one: one.includes('data-look='), feed}));""")
    assert out == {'many': True, 'pressed': True, 'one': False, 'feed': ''}


def test_task_boards_offer_mark_done_only_on_open_cards_and_only_for_tasks():
    out = run("""
const shown = {kind: 'board', lanes: [{name: 'open', count: 1, cards: [{id: 4, label: 'Order tiles'}]}, {name: 'done', count: 1, cards: [{id: 5, label: 'Pour slab'}]}]};
const tasks = fbBoard(shown, {record_type: 'system.task'});
state.nw.fb.moved[4] = 12;
const waiting = fbBoard(shown, {record_type: 'system.task'});
const snags = fbBoard(shown, {record_type: 'snag'});
console.log(JSON.stringify({open: tasks.includes('data-fb="mark-done" data-id="4"'), done: tasks.includes('data-id="5">Mark done'), waiting: waiting.includes('Waiting for approval') && !waiting.includes('data-id="4">Mark done'), snags: snags.includes('mark-done')}));""")
    assert out == {'open': True, 'done': False, 'waiting': True, 'snags': False}


def test_the_builder_checks_what_it_is_given_in_plain_words():
    out = run("""
const b = state.nw.fb.b;
const attempt = () => { try { return {spec: fbSpec()}; } catch (e) { return {error: e.message}; } };
const results = {};
Object.assign(b, {open: true, name: '', type: '', fields: [], look: 'table', conds: []}); results.noType = attempt().error;
b.type = 'system.task'; results.noName = attempt().error;
b.name = 'My Ravi tasks'; results.noFields = attempt().error;
b.fields = ['title', 'assignee']; b.look = 'board'; results.noStatus = attempt().error;
b.look = 'calendar'; results.noDate = attempt().error;
b.look = 'table'; b.conds = [{field: 'assignee', op: 'eq', value: 'Ravi'}, {field: 'title', op: 'contains', value: ''}];
const table = attempt().spec;
b.fields = ['title', 'status']; b.look = 'board'; const board = attempt().spec;
b.fields = ['title', 'due_date']; b.look = 'calendar'; b.conds = []; const calendar = attempt().spec;
b.type = 'snag'; b.fields = ['title', 'severity']; b.look = 'board'; const snag = attempt().spec;
console.log(JSON.stringify({results, table, board, calendar, snag}));""")
    r = out['results']
    assert r == {'noType': 'Choose what the view shows.', 'noName': 'Give the view a name.', 'noFields': 'Tick at least one field to show.',
                 'noStatus': 'A board needs a status-like field. Tick one, or choose Table.', 'noDate': 'A calendar needs a date field. Tick one, or choose Table.'}
    assert re.fullmatch(r'[a-z][a-z0-9_.]{1,59}', out['table']['id']) and out['table']['id'].startswith('mine.u7.my_ravi_tasks.')   # a personal id of the right shape
    assert out['table']['source']['items'][0]['filter'] == {'and': [{'field': 'assignee', 'op': 'eq', 'value': 'Ravi'}]}          # the unfinished row is dropped
    assert out['table']['primitive'] == 'table' and 'group' not in out['table'] and out['table']['spec_version'] == 1
    assert out['board']['group'] == {'columns': {'field': 'status'}} and out['calendar']['layout'] == {'date_field': 'due_date'}
    assert out['snag']['group'] == {'columns': {'field': 'severity'}}                                           # a choice field makes the board's columns


def test_only_people_who_may_propose_views_see_the_builder():
    out = run("""
const results = {};
for (const role of ['admin', 'manager', 'architect', 'site_engineer', 'accounts', 'viewer']) { state.user.role = role; results[role] = fbBuilderPanel().includes('New view'); }
state.user.role = 'architect'; state.nw.fb.b.open = true; state.nw.fb.b.type = 'system.task';
const architect = fbBuilderPanel();
state.user.role = 'admin'; const admin = fbBuilderPanel();
console.log(JSON.stringify({results, everyone: architect.includes('for everyone'), adminEveryone: admin.includes('for everyone')}));""")
    assert out['results'] == {'admin': True, 'manager': True, 'architect': True, 'site_engineer': True, 'accounts': True, 'viewer': False}
    assert out['everyone'] is False and out['adminEveryone'] is True                                           # "for everyone" is the owner's and managers' only


def test_no_inline_scripts_or_styles_and_the_page_loads_the_file():
    assert not re.search(r'\bon[a-z]+=|\.style\.|setAttribute\(.style|style="|javascript:', SCRIPT)
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    assert html.index('/static/newwork.js') < html.index('/static/viewbar.js')                                  # newwork.js defines what viewbar.js extends
    css = (STATIC / 'overlays.css').read_text(encoding='utf-8')
    block = css[css.index('Filter bar, look switcher'):]
    assert not re.search(r'#[0-9a-fA-F]{3,8}(?![0-9a-fA-F])', re.sub(r'var\(--[a-z-]+,#[0-9a-fA-F]{3,8}\)', '', block))      # colours come from the theme tokens


def test_the_screen_says_when_it_shows_only_the_first_records():
    out = run("""
const rows = n => Array.from({length: n}, (_, i) => ({cells: [String(i)]}));
const cut = fbMore({shown: {kind: 'table', result: {rows: rows(200), matched: 5000}}});
const atLeast = fbMore({shown: {kind: 'table', result: {rows: rows(200), matched: 520, incomplete: true}}});
const all = fbMore({shown: {kind: 'table', result: {rows: rows(3), matched: 3}}});
const board = fbMore({shown: {kind: 'board', lanes: []}});
console.log(JSON.stringify({cut, atLeast, all, board}));""")
    assert 'Showing the first 200 of 5000 records' in out['cut'] and 'at least' not in out['cut']
    assert 'Showing the first 200 of at least 520 records' in out['atLeast']
    assert out['all'] == '' and out['board'] == ''

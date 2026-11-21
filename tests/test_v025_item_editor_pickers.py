"""v0.25.0 pickers: editing a proposed item uses proper fields (rupees with an echo, project and person pickers, date picker)
instead of a raw JSON box, and amounts are never typed in paise. Fictional data only."""
import json
import pathlib
import subprocess

JS = pathlib.Path('studioos/static/app.js').read_text()
START = JS.index('const IMMUTABLE_ITEM_KEYS')
END = JS.index('function formRequestKey')
BLOCK = JS[START:END]
def _slice(start, end):
    return JS[JS.index(start):JS.index(end)]


REAL_AMOUNTS = (JS[JS.index('function inr('):JS.index('\n', JS.index('function inr('))] + '\n'
                + _slice('function amountEcho', 'const field=') + '\n'
                + JS[JS.index('function rupeesToPaise'):JS.index('\n', JS.index('function rupeesToPaise'))] + '\n')   # the app's own amount rules
STATE = ("const state={projects:[{id:3,name:'Fictional Villa'},{id:4,name:'Fictional Mall'}],costs:[{id:7,title:'Fictional tiles',project:'Fictional Villa',outstanding:500}],"
         "users:[{display_name:'Fictional Ravi',username:'ravi',role:'site_engineer',active:true}]};"
         "const esc=s=>String(s==null?'':s);\n" + REAL_AMOUNTS)


def node(expr):
    out = subprocess.run(['node', '-e', STATE + '\n' + BLOCK + f'\nconsole.log(JSON.stringify({expr}));'], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_each_field_gets_the_right_kind_of_editor():
    plan = node("itemFieldPlan({project:3,title:'Fictional tiles',vendor:'Fictional Tiles Co',amount_paise:120000,due_date:'2026-12-01',assignee:'Fictional Ravi',progress:40,id:9,idempotency_key:'abcdefghijkl'})")
    kinds = {f['key']: f['kind'] for f in plan}
    assert kinds == {'project': 'project', 'title': 'text', 'vendor': 'text', 'amount_paise': 'amount', 'due_date': 'date',
                     'assignee': 'person', 'progress': 'number', 'id': 'readonly', 'idempotency_key': 'readonly'}


def test_items_with_nested_data_keep_the_text_editor():
    assert node("itemFieldPlan({record_type:'x',data:{a:1}})") is None
    assert node("itemFieldPlan({slots:{amount:'5'}})") is None


def test_amount_field_shows_rupees_not_paise():
    html = node("itemEditorMarkup(itemFieldPlan({amount_paise:120000}))")
    assert 'value="1200"' in html and '120000' not in html and 'inputmode="decimal"' in html and 'data-amount-for="amount_paise"' in html


def test_project_field_is_a_picker_and_keeps_the_stored_form():
    by_id = node("itemEditorMarkup(itemFieldPlan({project:3}))")
    assert '<select' in by_id and 'value="3" selected' in by_id and 'Fictional Mall' in by_id
    by_name = node("itemEditorMarkup(itemFieldPlan({project:'Fictional Mall'}))")
    assert 'value="Fictional Mall" selected' in by_name


def test_edited_values_become_the_proposed_item_with_paise_and_ids_restored():
    after = node("collectItemEdit(itemFieldPlan({project:3,title:'Old',amount_paise:120000,due_date:'',progress:40,id:9}),{project:'4',title:'New title',amount_paise:'1,500.50',due_date:'2026-12-01',progress:'60'})")
    assert after == {'project': 4, 'title': 'New title', 'amount_paise': 150050, 'due_date': '2026-12-01', 'progress': 60, 'id': 9}


def test_a_name_valued_project_stays_a_name():
    after = node("collectItemEdit(itemFieldPlan({project:'Fictional Villa'}),{project:'Fictional Mall'})")
    assert after == {'project': 'Fictional Mall'}


def test_bad_input_gives_a_plain_message_and_changes_nothing():
    out = subprocess.run(['node', '-e', STATE + '\n' + BLOCK + "\ntry{collectItemEdit(itemFieldPlan({amount_paise:100}),{amount_paise:'12,50'});console.log('NO ERROR')}catch(e){console.log(e.message)}"], capture_output=True, text=True).stdout.strip()
    assert 'amount' in out.lower() and 'NO ERROR' not in out
    out2 = subprocess.run(['node', '-e', STATE + '\n' + BLOCK + "\ntry{collectItemEdit(itemFieldPlan({progress:5}),{progress:'abc'});console.log('NO ERROR')}catch(e){console.log(e.message)}"], capture_output=True, text=True).stdout.strip()
    assert 'whole number' in out2.lower()


def test_the_review_screen_opens_the_field_editor_and_falls_back_to_text():
    assert "const plan=itemFieldPlan(item?.after);if(plan){openItemEditor(item,plan);return;}" in JS
    assert "type==='ticket-item'" in JS and "raw=await askText('Edit proposed values" in JS


def test_single_field_edit_asks_for_rupees_when_the_field_is_in_paise():
    assert "key.endsWith('_paise')" in JS[JS.index("a==='edit-ticket-field'"):JS.index("a==='commit-ticket'")]

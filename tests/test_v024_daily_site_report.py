"""v0.24: the daily site report is a standard form that is saved as one note. Fictional text only."""
import pathlib
import subprocess

JS = pathlib.Path('studioos/static/app.js').read_text()


def compose(obj):
    fn = JS[JS.index('function composeSiteReport'):JS.index('function formRequestKey')]
    import json
    out = subprocess.run(['node', '-e', fn + f"\nconsole.log(JSON.stringify(composeSiteReport({json.dumps(obj)})));"], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def test_filled_fields_become_labelled_lines_and_empty_ones_are_left_out():
    text = compose({'work_done': 'Slab shuttering finished', 'people_on_site': '12', 'materials': '', 'issues': ' None ', 'tomorrow': ''})
    assert text.splitlines() == ['Work done today: Slab shuttering finished', 'People on site: 12', 'Delays or problems: None']


def test_nothing_filled_gives_an_empty_note_so_the_server_refuses_it():
    assert compose({}) == ''


def test_form_has_the_standard_fields_and_work_done_is_required():
    assert "field('Work done today','work_done','textarea'" in JS
    assert "field('Delays or problems','issues','textarea','Anything that held work up, or \"None\"',false)" in JS


def test_saved_note_reaches_the_server_as_one_note(admin):
    from .conftest import write, approved_form
    pid = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Daily Site', 'budget': '1000'}).json()['id']
    note = 'Work done today: Slab shuttering finished\nPeople on site: 12'
    r = write(admin, 'post', '/api/site-reports', {'project_id': pid, 'note': note, 'request_key': 'form-site-daily-0001'})
    assert r.status_code == 200, r.text
    assert write(admin, 'post', '/api/site-reports', {'project_id': pid, 'note': '', 'request_key': 'form-site-daily-0002'}).status_code == 422


def test_task_form_offers_a_people_picker_when_the_team_is_known():
    import json
    fn = JS[JS.index('function assigneeField'):JS.index('function formRequestKey')]
    script = ("const esc=s=>String(s);const field=()=>'TEXTBOX';const state={users:[{display_name:'Fictional Ravi',username:'ravi',role:'site_engineer',active:true},{display_name:'Old',username:'old',role:'architect',active:false},{display_name:'Watcher',username:'w',role:'viewer',active:true}]};\n"
              + fn + "\nconsole.log(assigneeField());state.users=[];console.log(assigneeField());")
    out = subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True).stdout
    assert 'Fictional Ravi · site engineer' in out and 'Old' not in out and 'Watcher' not in out
    assert out.strip().splitlines()[-1] == 'TEXTBOX'

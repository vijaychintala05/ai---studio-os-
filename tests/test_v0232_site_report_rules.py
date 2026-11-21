"""Owner decisions 9 and 10: the site report needs work done AND people on site, and an unsent draft stays on the phone."""
import json
import pathlib
import subprocess

JS = pathlib.Path('studioos/static/app.js').read_text()


def run(script):
    fn = JS[JS.index('const SITE_DRAFT_FIELDS'):JS.index('function formRequestKey')]
    store = "const m={};const store={setItem:(k,v)=>{m[k]=v},getItem:k=>(k in m?m[k]:null),removeItem:k=>{delete m[k]}};\n"
    return subprocess.run(['node', '-e', store + fn + "\n" + script], capture_output=True, text=True, check=True).stdout.strip()


def test_both_work_done_and_people_on_site_are_required():
    assert "field('Work done today','work_done','textarea'" in JS and "field('People on site (number)','people_on_site','number','e.g. 12')" in JS
    assert "field('People on site (number)','people_on_site','number','e.g. 12',false)" not in JS


def test_a_draft_is_kept_per_person_and_cleared_when_sent():
    out = run("saveSiteDraft(store,'ravi',{work_done:'Slab shuttering',people_on_site:'12',issues:'  '});"
              "console.log(JSON.stringify(readSiteDraft(store,'ravi')),JSON.stringify(readSiteDraft(store,'asha')));"
              "clearSiteDraft(store,'ravi');console.log(JSON.stringify(readSiteDraft(store,'ravi')));")
    first, second = out.splitlines()
    assert first == '{"work_done":"Slab shuttering","people_on_site":"12"} null'      # empty fields are not kept, another person sees nothing
    assert second == 'null'


def test_an_empty_form_removes_the_draft():
    out = run("saveSiteDraft(store,'ravi',{work_done:'x'});saveSiteDraft(store,'ravi',{work_done:' '});console.log(JSON.stringify(readSiteDraft(store,'ravi')));")
    assert out == 'null'


def test_draft_is_restored_on_open_autosaved_and_cleared_after_a_successful_send():
    assert "readSiteDraft(window.localStorage,state.user?.username)" in JS
    assert "d.dataset.type!=='site'" in JS and "saveSiteDraft(window.localStorage,state.user.username" in JS
    assert "if(type==='site')clearSiteDraft(window.localStorage,state.user?.username)" in JS

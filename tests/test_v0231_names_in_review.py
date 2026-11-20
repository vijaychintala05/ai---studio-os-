"""v0.23.1: the ticket review screen shows project, cost and task names, not numbers."""
import re
import subprocess
import pathlib

JS = pathlib.Path('studioos/static/app.js').read_text()


def _run(expr):
    fn = JS[JS.index('function friendlyValue'):JS.index('function evidenceGrid')]
    script = ("const state={projects:[{id:3,name:'Fictional Villa'}],costs:[{id:7,title:'Fictional tiles',project:'Fictional Villa'}],"
              "tasks:[{id:9,title:'Fictional plaster'}]};\n" + fn + "\nconsole.log(JSON.stringify(" + expr + "));")
    return subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True).stdout.strip()


def test_project_cost_and_task_ids_show_as_names():
    assert _run("friendlyValue('project',3,'create_task')") == '"Fictional Villa"'
    assert _run("friendlyValue('project_id','3','record_cost')") == '"Fictional Villa"'
    assert _run("friendlyValue('cost_id',7,'record_payment')") == '"Fictional tiles (Fictional Villa)"'
    assert _run("friendlyValue('id',9,'update_task')") == '"Fictional plaster"'


def test_unknown_ids_and_text_are_left_alone():
    assert _run("friendlyValue('project',99,'create_task')") == 'null'
    assert _run("friendlyValue('project','Fictional Villa','create_task')") == 'null'
    assert _run("friendlyValue('title','x','create_task')") == 'null'


def test_review_grid_uses_the_helper():
    assert 'friendlyValue(k,value,i.item_type)' in JS

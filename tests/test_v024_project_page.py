"""v0.24: one page gathers a project's tasks, costs and site reports. Fictional data only."""
import json
import pathlib
import subprocess

JS = pathlib.Path('studioos/static/app.js').read_text()


def data(st, pid):
    fn = JS[JS.index('function projectPageData'):JS.index('function projectPage(')]
    out = subprocess.run(['node', '-e', fn + f"\nconsole.log(JSON.stringify(projectPageData({json.dumps(st)},{pid})));"], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


ST = {'projects': [{'id': 1, 'name': 'Fictional Villa'}, {'id': 2, 'name': 'Fictional Mall'}],
      'budgets': [{'id': 1, 'budget': 100}],
      'tasks': [{'project_id': 1, 'title': 'a', 'status': 'open'}, {'project_id': 1, 'title': 'b', 'status': 'cancelled'}, {'project_id': 1, 'title': 'c', 'status': 'done'}, {'project_id': 2, 'title': 'd', 'status': 'open'}],
      'costs': [{'project_id': 1, 'id': 5}, {'project_id': 2, 'id': 6}],
      'site': [{'project': 'Fictional Villa', 'note': 'x'}, {'project': 'Fictional Mall', 'note': 'y'}]}


def test_only_that_projects_items_are_gathered_and_closed_tasks_are_not_open():
    d = data(ST, 1)
    assert [t['title'] for t in d['openTasks']] == ['a']
    assert [t['title'] for t in d['doneTasks']] == ['b', 'c']
    assert [c['id'] for c in d['costs']] == [5]
    assert [r['note'] for r in d['reports']] == ['x']
    assert d['budget']['budget'] == 100


def test_unknown_project_gives_nothing():
    assert data(ST, 99) is None


def test_project_cards_have_an_open_button_and_it_is_wired():
    assert JS.count('data-open-project=') >= 2
    assert "state.view==='projectpage'" in JS

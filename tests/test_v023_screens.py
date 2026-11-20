"""v0.23 screens: the page loads the new script, adds the three navigation entries, uses no inline styles (strict CSP),
and every API path the screens call exists with the method used. Fictional data; static checks only."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / 'studioos' / 'static'
JS = (STATIC / 'newwork.js').read_text(encoding='utf-8')
HTML = (STATIC / 'index.html').read_text(encoding='utf-8')


def test_page_loads_the_script_after_app_and_adds_the_three_entries():
    assert '/static/newwork.js' in HTML and HTML.index('/static/app.js') < HTML.index('/static/newwork.js')
    for view in ('today', 'mytime', 'planbudget', 'recycle'):
        assert f'data-view="{view}"' in HTML
        assert f"{view}:" in JS


def test_no_inline_styles_or_event_attributes_in_the_screens():
    assert not re.search(r'\sstyle\s*=', JS)
    assert not re.search(r'\son[a-z]+\s*=\s*["\']', JS)
    assert 'innerHTML' in JS and 'eval(' not in JS


def test_every_called_path_exists_on_the_api():
    from tests.api_surface import current_surface
    routes = {}
    for r in current_surface()['routes']:
        routes.setdefault(r['path'], set()).update(r['methods'])
    called = re.findall(r"nwApi\(\s*[`'](/api/[^`'?]*)[`']\s*(,)?", JS)
    assert len(called) >= 8
    for path, has_body in called:
        pattern = re.sub(r'\$\{[^}]+\}', '{x}', path)
        norm = lambda x: re.sub(r'\{[^}]+\}', '{x}', x)
        match = [p for p in routes if norm(p) == norm(pattern)]
        assert match, f'no route for {path}'
        needed = 'POST' if has_body else 'GET'
        assert any(needed in routes[m] for m in match), f'{path} is not a {needed} route'


def test_the_payloads_the_plan_forms_send_are_accepted(admin):
    """The exact bodies newwork.js posts for a link, a stage, a baseline and a restore open tickets."""
    from tests.test_v017_work_rules_app import project_with_tasks, propose, save
    p, (a, b) = project_with_tasks(admin, 2, 'Villa Screens')
    assert propose(admin, 'work_link', {'predecessor_id': a['id'], 'successor_id': b['id'], 'kind': 'hard'}).status_code == 200
    assert propose(admin, 'work_stage', {'project_id': p['id'], 'name': 'Foundation', 'client_visible': False}).status_code == 200
    assert propose(admin, 'work_baseline', {'project_id': p['id'], 'label': 'Approved plan'}).status_code == 200
    save(admin, 'work_task_delete', {'task_id': b['id'], 'reason': 'fictional test'})
    assert propose(admin, 'work_task_restore', {'task_id': b['id']}).status_code == 200
    assert [i['task_id'] for i in admin.get('/api/work/recycle').json()['items']] == [b['id']]

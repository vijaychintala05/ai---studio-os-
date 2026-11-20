"""v0.23 screens: the page loads the new script, adds the three navigation entries, uses no inline styles (strict CSP),
and every API path the screens call exists with the method used. Fictional data; static checks only."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / 'studioos' / 'static'
JS = (STATIC / 'newwork.js').read_text(encoding='utf-8')
HTML = (STATIC / 'index.html').read_text(encoding='utf-8')


def test_page_loads_the_script_after_app_and_adds_the_three_entries():
    assert '/static/newwork.js' in HTML and HTML.index('/static/app.js') < HTML.index('/static/newwork.js')
    for view in ('today', 'mytime', 'planbudget'):
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

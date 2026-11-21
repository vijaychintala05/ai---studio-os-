"""Guards for problems that only appear when several branches are merged together (found when the open PRs were integrated)."""
import pathlib
import re

STATIC = pathlib.Path('studioos/static')
HTML = (STATIC / 'index.html').read_text()


def test_every_script_and_stylesheet_is_included_once():
    tags = re.findall(r'<script src="([^"]+)"|<link rel="stylesheet" href="([^"]+)"', HTML)
    names = [a or b for a, b in tags]
    dupes = sorted({n for n in names if names.count(n) > 1})
    assert not dupes, f'included more than once (a script declared twice stops the whole page): {dupes}'


def test_every_included_file_exists():
    for src in re.findall(r'(?:src|href)="/static/([^"]+)"', HTML):
        assert (STATIC / src).is_file(), src


def test_shell_script_loads_after_the_feature_scripts_it_wraps_and_before_flows():
    order = re.findall(r'<script src="/static/([^"]+)"', HTML)
    assert order.index('shell.js') > order.index('app.js')
    for late in ('books.js', 'home.js', 'projectpage.js', 'overlays.js'):
        if late in order:
            assert order.index(late) < order.index('shell.js'), late
    if 'flows.js' in order:
        assert order.index('flows.js') > order.index('shell.js')


def test_top_bar_wraps_on_phones_so_the_theme_switch_and_icon_buttons_fit():
    css = (STATIC / 'shell.css').read_text()
    block = css[css.index('Integration of the theme switch'):]
    assert 'max-width: 760px' in block and 'flex-wrap: wrap' in block and '.top-right' in block

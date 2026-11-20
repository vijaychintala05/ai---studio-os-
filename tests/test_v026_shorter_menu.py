"""v0.26: the side menu shows the everyday screens; the less-used ones sit behind one 'Show more' button."""
import pathlib
import re

HTML = pathlib.Path('studioos/static/index.html').read_text()
EVERYDAY = ['assistant', 'overview', 'projects', 'inbox', 'tasks', 'site', 'documents', 'tickets', 'budget', 'approvals', 'today', 'account']


def link(view):
    return re.search(r'<button class="([^"]*)" data-view="%s"' % view, HTML).group(1)


def test_everyday_screens_stay_in_the_short_menu():
    for v in EVERYDAY:
        assert 'nav-more' not in link(v), v


def test_less_used_screens_are_behind_the_more_button():
    for v in ('universal', 'ledger', 'selfcheck', 'restructure', 'aireader', 'savedviews'):
        assert 'nav-more' in link(v), v


def test_role_rules_are_kept_on_hidden_items():
    assert 'finance-only' in link('ledger') and 'admin-only' in link('restructure')


def test_there_is_a_button_and_the_script_and_style_back_it():
    assert 'id="navMoreBtn"' in HTML and 'aria-expanded="false"' in HTML
    assert 'navMoreBtn' in pathlib.Path('studioos/static/app.js').read_text()
    assert '.sidebar:not(.more-open) .nav-more:not(.active)' in pathlib.Path('studioos/static/styles.css').read_text()

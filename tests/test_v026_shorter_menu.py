"""The side menu stays short. v0.26 hid the less-used screens behind a 'Show more' button; the new menu replaces that with five places
(Home, Inbox, Projects, Money, Settings) whose screens are tabs inside each place, so nothing is hidden and nothing needs a button.
The fuller checks are in tests/test_nav_menu.py."""
import pathlib
import re

HTML = pathlib.Path('studioos/static/index.html').read_text()
NAV = pathlib.Path('studioos/static/nav.js').read_text()


def test_the_menu_has_five_places_and_no_show_more_button():
    assert HTML.count('data-section=') == 5
    assert 'navMoreBtn' not in HTML and 'Show more' not in HTML


def test_every_everyday_screen_is_one_click_from_its_place():
    for view in ('assistant', 'overview', 'projects', 'inbox', 'tasks', 'site', 'documents', 'tickets', 'budget', 'approvals', 'today', 'account'):
        assert f"view: '{view}'" in NAV or view in ('assistant', 'account'), view


def test_less_used_screens_are_tabs_not_hidden_buttons():
    for view in ('universal', 'ledger', 'selfcheck', 'restructure', 'aireader', 'savedviews'):
        assert f"view: '{view}'" in NAV, view


def test_role_rules_are_kept_on_the_tabs():
    assert re.search(r"view: 'ledger'[^}]*need: 'finance'", NAV) and re.search(r"view: 'restructure'[^}]*need: 'admin'", NAV)

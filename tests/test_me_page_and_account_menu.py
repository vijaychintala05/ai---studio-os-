"""The phone's Me page (every screen, by place) and the account menu on the top bar (name, colour theme, My account, Sign out).
The list logic is run with node; the markup, wiring and styles are checked as text. Fictional roles only."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / 'studioos' / 'static'
NAV = (STATIC / 'nav.js').read_text(encoding='utf-8')
HTML = (STATIC / 'index.html').read_text(encoding='utf-8')
SHELL = (STATIC / 'shell.js').read_text(encoding='utf-8')
CHAT = (STATIC / 'chat.js').read_text(encoding='utf-8')
CSS = (STATIC / 'nav.css').read_text(encoding='utf-8')
INTERACTION = (STATIC / 'interaction.js').read_text(encoding='utf-8')
needs_node = pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')


def run_node(expr):
    pure = NAV.split('/* --- page wiring')[0].replace("'use strict';", '')
    menu = '{' + INTERACTION.split('const ROLE_MENU = {')[1].split('};')[0] + '}'
    out = subprocess.run(['node', '-e', pure + f"\nconst ROLE_MENU = {menu};\nconsole.log(JSON.stringify({expr}));"], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@needs_node
def test_me_lists_every_screen_the_role_may_open_by_place():
    got = run_node("navMeSections('admin', undefined).map(s => [s.id, s.items.length])")
    assert [g[0] for g in got] == ['home', 'inbox', 'projects', 'money', 'settings']
    flat = run_node("navMeSections('admin', undefined).flatMap(s => s.items.map(i => i.view))")
    assert set(flat) == set(run_node("navEntriesFor('admin', undefined).map(e => e.view)")) - {'assistant', 'account', 'me'}   # the menu map and Me agree


@needs_node
@pytest.mark.parametrize('role', ['architect', 'site_engineer', 'viewer'])
def test_me_never_lists_a_screen_the_role_may_not_open(role):
    flat = set(run_node(f"navMeSections({json.dumps(role)}, ROLE_MENU[{json.dumps(role)}]).flatMap(s => s.items.map(i => i.view))"))
    assert not flat & {'books', 'ledger', 'chart', 'budget', 'activity', 'team', 'safety', 'settings', 'aireader', 'agents', 'approvals', 'restructure'}, flat


@needs_node
def test_a_tab_that_has_its_own_view_name_keeps_its_tab():
    items = run_node("navMeSections('admin', undefined).flatMap(s => s.items).filter(i => i.view === 'newtypes')")
    assert sorted(i['tab'] for i in items) == ['types', 'waiting']


def test_the_phone_me_tab_opens_the_me_page_and_the_chat_menu_button_does_too():
    assert "top: 'me', views: ['me', 'account'" in SHELL
    assert "switchView('me')" in CHAT.split("a === 'cx-menu'")[1].split('\n')[0] and "(max-width:599px)" in CHAT.split("a === 'cx-menu'")[1].split('\n')[0]
    assert "state.view === 'me'" in NAV and 'navMeView()' in NAV


def test_the_top_bar_has_an_account_menu_instead_of_loose_buttons():
    bar = HTML.split('<header class="topbar">')[1].split('</header>')[0]
    assert 'id="userMenuBtn"' in bar and 'aria-haspopup="true"' in bar and 'aria-expanded="false"' in bar and 'id="userMenuPanel"' in bar
    outside = bar.split('<div class="user-menu"')[0]
    assert 'data-theme-set' not in outside and 'logoutBtn' not in outside and 'Sign out' not in outside          # now inside the menu only
    panel = bar.split('id="userMenuPanel"')[1]
    assert panel.count('data-theme-set=') == 3 and panel.count('id="logoutBtn"') == 1 and 'data-view="account"' in panel and 'hidden' in bar.split('id="userMenuPanel"')[1][:200]
    assert HTML.count('id="logoutBtn"') == 1                                                                  # app.js binds this id


def test_the_menu_opens_closes_with_escape_and_outside_clicks_and_keeps_focus_sensible():
    assert "e.key === 'Escape'" in NAV and 'navUserMenuClose(true)' in NAV
    assert "e.target.closest('#userMenuPanel')" in NAV and "aria-expanded" in NAV
    assert "data-nav=\"signout\"" in NAV and "getElementById('logoutBtn')?.click()" in NAV


def test_the_phone_hides_the_menu_button_because_the_bottom_tabs_and_me_replace_it():
    assert re.search(r'@media \(max-width:599px\)\{[^}]*\.menu-toggle\{display:none\}', CSS)


def test_styles_follow_the_themes_and_nothing_is_inline():
    block = CSS.split('/* the account menu on the top bar */')[1].split('/* on a phone:')[0]
    assert 'var(--card)' in block and 'var(--edge)' in block and 'var(--sel)' in block and 'min-height:48px' in block
    assert not re.search(r'#[0-9a-fA-F]{3,6}\b', block.replace('rgba(0,0,0,.18)', ''))
    for text in (NAV, HTML):
        assert not re.search(r'\sstyle\s*=', text) and '<style' not in text
    assert 'eval(' not in NAV

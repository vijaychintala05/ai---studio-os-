"""The left menu and the section tabs: five places at most, one map shared by the menu, the tabs and search, role rules kept,
every old screen still reachable, plain words, and the files wired in with no inline styles. The map logic is run with node.
All names and roles are fictional."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / 'studioos' / 'static'
NAV = (STATIC / 'nav.js').read_text(encoding='utf-8')
CSS = (STATIC / 'nav.css').read_text(encoding='utf-8')
HTML = (STATIC / 'index.html').read_text(encoding='utf-8')
INTERACTION = (STATIC / 'interaction.js').read_text(encoding='utf-8')
APP = (STATIC / 'app.js').read_text(encoding='utf-8')
OVERLAYS = (STATIC / 'overlays.js').read_text(encoding='utf-8')

ROLES = ['admin', 'manager', 'architect', 'site_engineer', 'accounts', 'viewer']
# every screen the old side menu offered (33 entries; "newtypes" had two tabs), so none may be lost
OLD_SCREENS = ['home', 'assistant', 'overview', 'projects', 'inbox', 'insights', 'work', 'today', 'mytime', 'planbudget', 'recycle', 'savedviews',
               'tickets', 'newtypes', 'universal', 'chart', 'ledger', 'books', 'tasks', 'budget', 'site', 'documents', 'approvals', 'activity',
               'agents', 'team', 'settings', 'aireader', 'restructure', 'selfcheck', 'safety', 'account']


def role_menu():
    block = INTERACTION.split('const ROLE_MENU = {')[1].split('};')[0]
    return '{' + block + '}'


def run_node(expr):
    pure = NAV.split('/* --- page wiring')[0].replace("'use strict';", '')
    script = pure + f"\nconst ROLE_MENU = {role_menu()};\nconsole.log(JSON.stringify({expr}));"
    out = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


needs_node = pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')


@needs_node
@pytest.mark.parametrize('role', ROLES)
def test_at_most_five_places_in_the_left_menu(role):
    ids = run_node(f"navSectionsFor({json.dumps(role)}, ROLE_MENU[{json.dumps(role)}]).map(s => s.id)")
    assert 1 <= len(ids) <= 5, ids


@needs_node
def test_places_by_role():
    def ids(role):
        return run_node(f"navSectionsFor({json.dumps(role)}, ROLE_MENU[{json.dumps(role)}]).map(s => s.id)")
    assert ids('admin') == ['home', 'inbox', 'projects', 'money', 'settings'] == ids('manager')
    assert ids('accounts') == ['home', 'inbox', 'projects', 'money']
    assert ids('site_engineer') == ['home', 'inbox', 'projects'] == ids('architect')
    assert ids('viewer') == ['home', 'projects']


@needs_node
def test_every_old_screen_is_still_reachable_by_the_owner():
    got = set(run_node("navEntriesFor('admin', undefined).map(e => e.view)"))
    assert set(OLD_SCREENS) <= got, set(OLD_SCREENS) - got
    tabs = run_node("navEntriesFor('admin', undefined).filter(e => e.view === 'newtypes').map(e => e.tab)")
    assert sorted(tabs) == ['types', 'waiting']                      # both of the old "newtypes" entries


@needs_node
@pytest.mark.parametrize('role', ['architect', 'site_engineer', 'viewer'])
def test_role_rules_are_kept(role):
    got = set(run_node(f"navEntriesFor({json.dumps(role)}, ROLE_MENU[{json.dumps(role)}]).map(e => e.view)"))
    assert not got & {'books', 'sales', 'receipts', 'reports', 'taxtools', 'ledger', 'chart', 'budget', 'activity', 'team', 'safety', 'settings', 'aireader', 'agents', 'approvals', 'restructure'}, got


@needs_node
def test_manager_and_accounts_rules():
    mgr = set(run_node("navEntriesFor('manager', undefined).map(e => e.view)"))
    assert {'approvals', 'agents', 'budget', 'sales', 'receipts'} <= mgr and 'books' not in mgr and 'reports' not in mgr and 'taxtools' not in mgr
    assert run_node("navTabsFor(NAV_SECTIONS.find(s => s.id === 'money'), 'manager')[0].view") == 'sales'
    assert not mgr & {'team', 'safety', 'settings', 'aireader', 'restructure'}            # admin only
    acc = set(run_node("navEntriesFor('accounts', ROLE_MENU.accounts).map(e => e.view)"))
    assert {'books', 'sales', 'receipts', 'reports', 'taxtools', 'ledger', 'chart', 'budget', 'activity'} <= acc and not acc & {'approvals', 'team', 'safety', 'tasks'}


@needs_node
def test_the_menu_follows_the_screen():
    assert run_node("navSectionOf('planbudget')") == 'projects'
    assert run_node("navSectionOf('party')") == 'money' and run_node("navSectionOf('project')") == 'projects'
    assert run_node("navSectionOf('newtypes', 'waiting')") == 'inbox' and run_node("navSectionOf('newtypes', 'types')") == 'settings'
    assert run_node("navSectionOf('newtypes')") == 'inbox'
    assert run_node("navSectionOf('assistant')") == '' and run_node("navSectionOf('account')") == ''


@needs_node
def test_search_finds_screens_in_plain_words_and_only_for_the_role():
    def top(role, query):
        got = run_node(f"navSearch(navEntriesFor({json.dumps(role)}, ROLE_MENU[{json.dumps(role)}]), {json.dumps(query)}).map(e => e.view)")
        return got
    assert top('site_engineer', 'site report')[0] == 'site'
    # 'bank' finds the Bank feed first (its name says bank) and Books home, where bank balances are, right after.
    assert top('admin', 'bills')[0] == 'budget' and top('accounts', 'bank')[:2] == ['bankfeed', 'books']
    assert top('site_engineer', 'ledger') == [] and top('viewer', 'team') == []          # hidden screens never appear in search
    assert top('admin', 'zzzz') == [] and top('admin', '') == []


def test_the_page_has_no_show_more_and_no_shouting_labels():
    for old in ('navMoreBtn', 'nav-more', 'Show more', 'WORKSPACE', 'FIRM OPERATING SYSTEM', 'nav-section'):
        assert old not in HTML, old
    assert 'navMoreBtn' not in APP and 'nav-more' not in INTERACTION
    assert HTML.count('data-section=') == 5 and 'aria-label="Main menu"' in HTML


def test_the_menu_keeps_the_ids_other_screens_use():
    for needed in ('id="approvalBadge"', 'id="safetyBadge"', 'id="userDisplay"', 'id="userRole"', 'id="breadcrumb"', 'id="sectionTabs"', 'id="logoutBtn"'):
        assert needed in HTML, needed
    assert 'Workspace' not in HTML                                                       # the constant, empty-meaning crumb is gone


def test_plain_menu_words():
    for new in ('Automatic checks', 'AI settings', 'Other record types', 'System check', 'Change a record type', 'Files to sort', 'Waiting for a place',
                'Templates and recycle bin', 'Budgets and costs'):
        assert f"'{new}'" in NAV, new
    for old in ('Agents &amp; Hooks', 'Agents & Hooks', 'AI Providers', 'Universal Types', 'Self-check'):
        assert old not in HTML and old not in NAV, old


def test_search_shows_screens_and_the_slash_key_is_not_taken_twice():
    assert 'ovScreenRows' in OVERLAYS and 'ovScreenRows' in NAV
    assert NAV.count("e.key === '/'") == 0                                               # overlays.js already owns the / key
    assert "toLowerCase() === 'k'" in NAV


def test_files_are_wired_and_clean():
    assert '/static/nav.css' in HTML and HTML.index('/static/shell.css') < HTML.index('/static/nav.css')
    assert HTML.index('/static/shell.js') < HTML.index('/static/nav.js') and HTML.index('/static/flows.js') < HTML.index('/static/nav.js')
    assert not re.search(r'\sstyle\s*=', NAV) and '.style.' not in NAV and 'eval(' not in NAV
    assert not re.search(r'\sstyle\s*=', HTML) and '<style' not in HTML
    assert 'prefers-reduced-motion' in CSS and 'min-height:48px' in CSS and 'var(--sel)' in CSS and 'var(--subtle)' in CSS
    assert '#0d192b' not in CSS and re.search(r'#[0-9a-fA-F]{6}', CSS.replace('#fff', '')) is None, 'colours come from the theme tokens'


def test_sign_in_waits_for_the_page_to_load():
    assert "document.addEventListener('DOMContentLoaded',initialize)" in APP            # a quick answer must not clear the screens' starting values

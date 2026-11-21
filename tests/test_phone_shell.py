"""Phone shell: five tabs for everyone, Books instead of Projects for Accounts, a role-based Home, every tab opening a screen that exists,
and the files wired into the page with no inline styles. The tab logic is run with node when it is available. Fictional."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / 'studioos' / 'static'
JS = (STATIC / 'shell.js').read_text(encoding='utf-8')
CSS = (STATIC / 'shell.css').read_text(encoding='utf-8')
HTML = (STATIC / 'index.html').read_text(encoding='utf-8')
APP = (STATIC / 'app.js').read_text(encoding='utf-8')
NEWWORK = (STATIC / 'newwork.js').read_text(encoding='utf-8')


def run_node(role, view):
    script = (JS.split('function shellRefresh')[0].replace("'use strict';", '') +
              f"\nconsole.log(JSON.stringify({{tabs: shellTabs({json.dumps(role)}), active: shellActive(shellTabs({json.dumps(role)}), {json.dumps(view)})}}));")
    out = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')
@pytest.mark.parametrize('role,home', [('site_engineer', 'home'), ('architect', 'home'), ('manager', 'home'), ('admin', 'home'), ('accounts', 'home')])
def test_five_tabs_and_a_role_based_home(role, home):
    got = run_node(role, 'overview')
    keys = [t['key'] for t in got['tabs']]
    assert len(keys) == 5 and keys[:3] == ['home', 'inbox', 'capture'] and keys[-1] == 'me'
    assert keys[3] == ('books' if role == 'accounts' else 'projects')                 # only Accounts has Books in place of Projects
    assert got['tabs'][0]['top'] == home and got['tabs'][2]['top'] == 'assistant'


@pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')
def test_the_active_tab_follows_the_screen():
    assert run_node('manager', 'planbudget')['active'] == 'projects'
    assert run_node('manager', 'tickets')['active'] == 'inbox'
    assert run_node('manager', 'assistant')['active'] == 'capture'
    assert run_node('accounts', 'ledger')['active'] == 'books' and run_node('accounts', 'books')['active'] == 'books' and run_node('accounts', 'party')['active'] == 'books'
    assert run_node('manager', 'home')['active'] == 'home'
    assert run_node('manager', 'account')['active'] == 'me' and run_node('manager', 'something_new')['active'] == 'me'


def test_every_tab_opens_a_screen_that_exists():
    known = set(re.findall(r'data-view="([a-z]+)"', HTML)) | set(re.findall(r"^(?:\s+)?([a-z]+):", NEWWORK.split('const NW_VIEWS = {')[1].split('};')[0], re.M)) | \
        set(re.findall(r"[{,]\s*([a-z]+)(?::|,)", APP.split('const views={')[1].split('};')[0]))
    tops = set(re.findall(r"top: '([a-z]+)'", JS)) | set(re.findall(r": '([a-z]+)'", JS.split('const SHELL_HOME = {')[1].split('};')[0]))
    assert tops and tops <= known, tops - known


def test_files_are_wired_and_clean():
    assert '/static/shell.css' in HTML and HTML.index('/static/styles.css') < HTML.index('/static/shell.css')
    assert HTML.index('/static/newwork.js') < HTML.index('/static/shell.js')
    assert not re.search(r'\sstyle\s*=', JS) and '.style.' not in JS and 'eval(' not in JS
    assert '@media (max-width:599px)' in CSS and 'min-height:48px' in CSS and 'safe-area-inset-bottom' in CSS and 'prefers-reduced-motion' in CSS
    assert 'aria-label' in JS and 'aria-current' in JS

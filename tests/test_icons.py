"""StudioOS icons: one outline style on a 24 by 24 grid, drawn in the current colour, every fixed meaning has its own icon, none is empty,
the shell and overlays use them instead of text glyphs, and nothing needs an outside source or an inline style. Fictional."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / 'studioos' / 'static'
ICONS = (STATIC / 'icons.js').read_text(encoding='utf-8')
SHELL = (STATIC / 'shell.js').read_text(encoding='utf-8')
OVERLAYS = (STATIC / 'overlays.js').read_text(encoding='utf-8')
HTML = (STATIC / 'index.html').read_text(encoding='utf-8')
NODE = shutil.which('node') is not None

FIXED_MEANINGS = ('done', 'overdue', 'attention', 'blocked', 'info', 'draft', 'locked', 'offline')      # the plan's table of fixed meanings
TABS = ('home', 'inbox', 'capture', 'projects', 'me', 'books')


def run(expr):
    out = subprocess.run(['node', '-e', ICONS.replace("'use strict';", '') + f'\nconsole.log(JSON.stringify({expr}));'], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.skipif(not NODE, reason='node is not installed')
def test_every_icon_is_drawn_on_the_grid_in_the_current_colour():
    names = run('Object.keys(ICONS)')
    assert len(names) >= 45 and len(names) == len(set(names))
    for n in names:
        svg = run(f'icon({json.dumps(n)}, 24)')
        assert 'viewBox="0 0 24 24"' in svg and 'stroke="currentColor"' in svg and 'stroke-width="2"' in svg and 'fill="none"' in svg
        assert 'stroke-linecap="round"' in svg and 'stroke-linejoin="round"' in svg and 'aria-hidden="true"' in svg      # outline, round, never read aloud
        assert re.search(r'<(path|circle|rect)\b', svg), n
        assert 'style=' not in svg and '<script' not in svg and 'href' not in svg and 'on' + 'click' not in svg
    assert run("icon('nope')") == '' and 'width="16"' in run("icon('home', 16)") and 'width="32"' in run("icon('home', 32)")


def test_the_tab_bar_and_the_fixed_meanings_each_have_an_icon():
    names = set(re.findall(r"^  (\w+): '<", ICONS, re.M))
    assert set(FIXED_MEANINGS) <= names and set(TABS) <= names and {'search', 'scope', 'plus', 'filter', 'eye', 'close', 'snag'} <= names
    plan_site = {'snag', 'visit', 'report', 'measure', 'handover', 'gang'}                                              # the plan's site, design, materials and money icons
    plan_design = {'sheet', 'revision', 'view3d', 'swatch', 'moodboard'}
    plan_materials = {'tile', 'plywood', 'laminate', 'paint', 'hardware', 'electrical', 'plumbing', 'ceiling', 'boq'}
    plan_money = {'payment', 'bill', 'reconcile', 'periodlock'}
    assert plan_site | plan_design | plan_materials | plan_money <= names
    # one icon per meaning: no two icons are drawn identically
    bodies = re.findall(r"^  \w+: '(<.*)',?$", ICONS, re.M)
    assert len(bodies) == len(set(bodies))


def test_the_shell_and_overlays_use_icons_not_text_glyphs():
    for glyph in '⌂⇣✦₹▤◉⌕◎＋⚲◐✕':
        assert glyph not in SHELL and glyph not in OVERLAYS, glyph
    assert SHELL.count("${icon(t.icon, 24)}") == 1 and "icon: 'home'" in SHELL and "icon: 'me'" in SHELL
    assert OVERLAYS.count('${icon(') >= 6 and 'aria-label="Search"' in OVERLAYS and 'aria-label="Close"' in OVERLAYS       # an icon-only button keeps its name
    assert 'tab-label' in SHELL                                                                                         # tab icons always show their label


def test_icons_are_inline_same_origin_and_clean():
    assert '/static/icons.js' in HTML and HTML.index('/static/app.js') < HTML.index('/static/icons.js') < HTML.index('/static/shell.js')
    assert not re.search(r'https?://', ICONS.replace('http://www.w3.org', '')) and 'importScripts' not in ICONS and 'eval(' not in ICONS
    assert not re.search(r'\sstyle\s*=', ICONS)
    assert not re.search(r'[\U0001F300-\U0001FAFF☀-➿]', ICONS + (STATIC / 'shell.css').read_text(encoding='utf-8'))   # no emoji in the interface

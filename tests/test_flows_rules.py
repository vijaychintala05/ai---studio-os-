"""Navigation rules from the App Flows map: reopen at the last screen within 30 minutes, the Inbox split, the 10 second approval undo, Back
through screens, long-press on Capture. The pure rules are run with node; the wiring is checked in the files. Fictional."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / 'studioos' / 'static'
JS = (STATIC / 'flows.js').read_text(encoding='utf-8')
HTML = (STATIC / 'index.html').read_text(encoding='utf-8')
NODE = shutil.which('node') is not None


def node(expr):
    pure = JS.split('function flowSave')[0].replace("'use strict';", '').replace("Object.assign(state, {flow: {inbox: 'needs', started: false, pop: false, ovPop: false}});", '')
    out = subprocess.run(['node', '-e', pure + f'\nconsole.log(JSON.stringify({expr}));'], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.skipif(not NODE, reason='node is not installed')
def test_reopen_at_the_last_screen_only_within_30_minutes_and_only_if_it_exists():
    views = json.dumps(['tasks', 'tickets', 'overview'])
    now = 10_000_000
    assert node(f"flowChooseStart({{view:'tasks',ts:{now - 5 * 60 * 1000}}}, {now}, {views}, 'overview')") == 'tasks'
    assert node(f"flowChooseStart({{view:'tasks',ts:{now - 31 * 60 * 1000}}}, {now}, {views}, 'overview')") == 'overview'      # away too long: Home
    assert node(f"flowChooseStart({{view:'ghost',ts:{now}}}, {now}, {views}, 'overview')") == 'overview'                         # no such screen
    assert node(f"flowChooseStart(null, {now}, {views}, 'today')") == 'today'
    assert node(f"flowChooseStart({{view:'tasks',ts:{now + 9999}}}, {now}, {views}, 'overview')") == 'overview'                  # a clock in the future is not trusted
    assert node(f"flowChooseStart({{view:'tasks'}}, {now}, {views}, 'overview')") == 'overview'


@pytest.mark.skipif(not NODE, reason='node is not installed')
def test_the_inbox_splits_into_needs_you_and_updates():
    rows = json.dumps([{'id': 1, 'status': 'draft'}, {'id': 2, 'status': 'committed'}, {'id': 3, 'status': 'reversed'}, {'id': 4, 'status': 'approved'}])
    got = node(f'flowInboxSplit({rows})')
    assert [t['id'] for t in got['needs']] == [1, 4] and [t['id'] for t in got['updates']] == [2, 3]


def test_approvals_are_held_for_ten_seconds_with_an_undo():
    assert 'FLOW_UNDO_SECONDS = 10' in JS
    for action in ('approve-ticket-item', 'commit-ticket', 'approve-cost', 'approve-payment'):
        assert f"'{action}'" in JS
    assert "stopImmediatePropagation" in JS and "flowGo" in JS and 'data-flow="undo"' in JS and 'Nothing was changed' in JS
    assert "{capture" not in JS and '}, true);' in JS                    # the hold runs before the app's own handler


def test_back_history_long_press_and_wiring():
    assert 'history.pushState' in JS and "addEventListener('popstate'" in JS and 'history.replaceState' in JS
    assert "pointerdown" in JS and "ovOpen('newform')" in JS and '500' in JS
    assert HTML.index('/static/shell.js') < HTML.index('/static/flows.js') and HTML.index('/static/overlays.js') < HTML.index('/static/flows.js')
    assert not re.search(r'\sstyle\s*=', JS) and 'eval(' not in JS and '.style.' not in JS
    ov = (STATIC / 'overlays.js').read_text(encoding='utf-8')
    assert 'state.flow.ovPop = true' in ov                                  # closing an overlay with Back does not also change screen
    assert '.undo-bar' in (STATIC / 'overlays.css').read_text(encoding='utf-8')

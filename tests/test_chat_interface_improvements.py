"""Tests for StudioOS chat interface improvements: rich safe Markdown, history search/filter/grouping,
composer attachments/drag-drop/paste, inline retry, copy/timestamps, draft card polish, theme tokens,
and project team chat bubbles & incremental refresh. Fictional data only."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / 'studioos' / 'static'
CHAT_JS = (STATIC / 'chat.js').read_text(encoding='utf-8')
STYLES_CSS = (STATIC / 'styles.css').read_text(encoding='utf-8')
PROJECT_JS = (STATIC / 'projectpage.js').read_text(encoding='utf-8')
needs_node = pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')


def run_node_ux(expr):
    block = CHAT_JS.split('// --- pure chat ux helpers')[1].split('\n', 1)[1].split('// --- end pure chat ux helpers')[0]
    out = subprocess.run(['node', '-e', block + f'\nconsole.log(JSON.stringify({expr}));'], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@needs_node
def test_markdown_renders_headings_lists_code_and_tables_safely():
    sample = (
        '## Budget Summary\n'
        'Total is **₹2,50,000** for `PRJ-01`.\n'
        '1. Civil works\n'
        '2. Electricals\n'
        '- Site note\n'
        '| Project | Spent |\n'
        '| --- | --- |\n'
        '| Fictional Villa | ₹1,20,000 |\n'
        '<script>alert(1)</script>'
    )
    html = run_node_ux(f'md({json.dumps(sample)})')
    assert '<div class="cx-h">Budget Summary</div>' in html
    assert '<strong>₹2,50,000</strong>' in html
    assert '<code class="cx-code">PRJ-01</code>' in html
    assert '<ol><li>Civil works</li><li>Electricals</li></ol>' in html
    assert '<ul><li>Site note</li></ul>' in html
    assert '<table class="cx-table">' in html and '<th>Project</th>' in html and '<td>Fictional Villa</td>' in html
    assert '<script>' not in html and '&lt;script&gt;alert(1)&lt;/script&gt;' in html


@needs_node
def test_history_filtering_and_date_grouping():
    now_ms = 1795651200000  # 2026-11-26T00:00:00Z + 12h check below
    sessions = [
        {'id': 's1', 'title': 'Paid 12,500 to Ravi Electricals', 'updated_at': '2026-11-26T10:00:00Z', 'ticket_status': 'draft'},
        {'id': 's2', 'title': 'Fictional Villa site note', 'updated_at': '2026-11-25T14:00:00Z', 'ticket_status': 'committed'},
        {'id': 's3', 'title': 'Old vendor bill', 'updated_at': '2026-11-10T09:00:00Z', 'ticket_status': 'in_review'},
    ]
    assert [s['id'] for s in run_node_ux(f'cxFilterSessions({json.dumps(sessions)}, "", "open")')] == ['s1', 's3']
    assert [s['id'] for s in run_node_ux(f'cxFilterSessions({json.dumps(sessions)}, "", "saved")')] == ['s2']
    assert [s['id'] for s in run_node_ux(f'cxFilterSessions({json.dumps(sessions)}, "villa", "all")')] == ['s2']
    groups = run_node_ux(f'cxGroupSessions({json.dumps(sessions)}, Date.parse("2026-11-26T12:00:00Z"))')
    assert [g['label'] for g in groups] == ['Today', 'Yesterday', 'Earlier']
    assert groups[0]['items'][0]['id'] == 's1'
    assert groups[1]['items'][0]['id'] == 's2'
    assert groups[2]['items'][0]['id'] == 's3'


def test_chat_composer_history_cards_and_error_recovery_hooks():
    # Attachment previews, compression, file input reset, drag-and-drop, paste
    assert 'function cxCompressImage(' in CHAT_JS
    assert 'cx-att-thumb' in CHAT_JS and "e.target.value = ''" in CHAT_JS
    assert "document.addEventListener('paste'" in CHAT_JS
    assert "document.addEventListener('drop'" in CHAT_JS
    # Scope bar, jump to latest, copy, inline retry, discard draft, contextual placeholder
    assert 'cx-scope-bar' in CHAT_JS and 'data-action="cx-clear-scope"' in CHAT_JS
    assert 'data-action="cx-jump-bottom"' in CHAT_JS
    assert 'data-action="cx-copy"' in CHAT_JS
    assert 'data-action="cx-retry"' in CHAT_JS and 'data-action="cx-dismiss-failed"' in CHAT_JS
    assert 'data-action="cx-discard-draft"' in CHAT_JS
    assert 'function cxOpenDraft()' in CHAT_JS and 'function cxCanSend()' in CHAT_JS
    # Missing fields already in the missing-details form are not duplicated in the top grid
    assert 'inMissingForm.has(item.id' in CHAT_JS
    # History drawer loading state, search, filter pills
    assert 'Loading conversations…' in CHAT_JS
    assert 'id="cxHistorySearch"' in CHAT_JS and 'data-action="cx-hfilter"' in CHAT_JS
    # Strict CSP: no inline styles or event handlers
    assert not re.search(r'\sstyle\s*=', CHAT_JS)
    assert not re.search(r'\son[a-z]+\s*=\s*["\']', CHAT_JS)


def test_chat_css_uses_theme_tokens_and_responsive_field_grid():
    chat_block = STYLES_CSS.split('body[data-env="test"] .cx-bar')[1].split('/* v0.9.3 AI connectors */')[0]
    for legacy_hex in ('#e5953c', '#9aa8bd', '#3047e3', '#f2c4c8', '#c9d3ff', '#b7c1e8', '#f0d7b0'):
        assert legacy_hex not in chat_block, legacy_hex
    assert 'minmax(104px,34%)' in chat_block
    assert '.cx-scope-bar' in STYLES_CSS and '.pp-chat-bubble' in STYLES_CSS


def test_project_team_chat_has_bubbles_and_incremental_refresh():
    assert 'pp-chat-list' in PROJECT_JS and 'pp-chat-me' in PROJECT_JS
    assert 'data-pp="chat-refresh"' in PROJECT_JS and '?after=' in PROJECT_JS
    assert '.style.' not in PROJECT_JS and not re.search(r'\sstyle\s*=', PROJECT_JS)

"""Offline outbox: only draft-making requests are kept, the summary line, the service worker never keeps API answers, and the route serves
the worker from the root. The queue rules are run with node. Fictional."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / 'studioos' / 'static'
OUTBOX = (STATIC / 'outbox.js').read_text(encoding='utf-8')
SW = (STATIC / 'sw.js').read_text(encoding='utf-8')
HTML = (STATIC / 'index.html').read_text(encoding='utf-8')
NODE = shutil.which('node') is not None


def node(expr):
    pure = OUTBOX.split('// ------------------------------------------------------------------ storage')[0].replace("'use strict';", '')
    out = subprocess.run(['node', '-e', pure + f'\nconsole.log(JSON.stringify({expr}));'], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.skipif(not NODE, reason='node is not installed')
@pytest.mark.parametrize('method,path,want', [
    ('POST', '/api/site-reports', True), ('POST', '/api/tasks', True), ('POST', '/api/time/propose', True), ('POST', '/api/work/propose', True),
    ('POST', '/api/rhythm/status/reply', True), ('post', '/api/tasks?x=1', True),
    ('GET', '/api/tasks', False), ('PATCH', '/api/tasks/5/complete', False), ('POST', '/api/tickets/3/approve-and-save', False),
    ('POST', '/api/costs', False), ('POST', '/api/payments', False), ('POST', '/api/chat', False), ('POST', '/api/auth/login', False),
    ('POST', '/api/time/timer/stop', False), ('POST', '/api/tasks/../tickets/1/approve-and-save', False),
])
def test_only_draft_making_requests_are_kept(method, path, want):
    assert node(f'outboxQueueable({json.dumps(method)}, {json.dumps(path)})') is want


@pytest.mark.skipif(not NODE, reason='node is not installed')
def test_the_status_line_says_what_is_waiting():
    items = json.dumps([{'id': 1}, {'id': 2}, {'id': 3, 'failed': True}])
    assert node(f'outboxSummary({items}, null)') == 'Saved on phone · 2 waiting · 1 could not be sent'
    assert node('outboxSummary([], null)') == ''
    assert 'last synced' in node(f'outboxSummary({items}, 1700000000000)')


def test_money_approvals_and_sign_in_are_never_queued():
    queue_rules = OUTBOX.split('const OUTBOX_PATHS = [')[1].split('];')[0]
    for word in ('approve', 'payments', 'costs', 'login', 'commit', 'chat'):
        assert word not in queue_rules                                  # nothing that approves, pays or signs in
    assert 'err instanceof TypeError' in OUTBOX                          # only a network failure is kept, never an answer from the server
    assert 'failed: true' in OUTBOX and 'do not retry' in OUTBOX


def test_the_service_worker_keeps_no_api_answers():
    assert "url.pathname.startsWith('/api/')" in SW and 'return;' in SW
    assert "req.method !== 'GET'" in SW and 'url.origin !== self.location.origin' in SW
    assert 'caches.put' not in SW and not re.search(r"cache.*'/api", SW.replace("url.pathname.startsWith('/api/')", ''))


def test_the_worker_is_served_from_the_root_with_the_right_headers(client):
    r = client.get('/sw.js')
    assert r.status_code == 200 and r.headers['content-type'].startswith('application/javascript')
    assert r.headers['service-worker-allowed'] == '/' and r.headers['cache-control'] == 'no-cache'
    assert 'studioos-shell-' in r.text and 'frame-ancestors' in r.headers.get('content-security-policy', '')


def test_files_are_wired_and_clean():
    assert HTML.index('/static/newwork.js') < HTML.index('/static/outbox.js')
    for src in (OUTBOX, SW):
        assert not re.search(r'\sstyle\s*=', src) and 'eval(' not in src and 'importScripts' not in src
    assert "register('/sw.js')" in OUTBOX and 'indexedDB' in OUTBOX

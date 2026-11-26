"""Run the gap screens' page scripts in node with fictional server replies.

`run(scripts, body)` loads gapkit.js and the named scripts, then runs `body`. Inside it, `replies` maps an
address to what the server would answer, and `calls` records every request and notice.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / 'studioos' / 'static'
needs_node = pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')

_HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const calls = [];
const replies = {};
const ctx = vm.createContext({
  assert, calls, replies, console, JSON, Promise, Number, String, Object, Array, Math, Date, Set, Map, RegExp,
  encodeURIComponent, setTimeout,
  state: {user: {id: 1, role: 'admin'}, view: ''},
  esc: s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;'),
  inr: n => 'Rs ' + n, pill: (label, tone) => `<span class="tag ${tone || ''}">${label}</span>`,
  head: (title, sub) => `<h1>${title}</h1><p>${sub || ''}</p>`,
  empty: (icon, title) => `<p>${title}</p>`, time: s => String(s),
  isAdmin: () => ctx.state.user.role === 'admin', isApprover: () => ['admin', 'manager'].includes(ctx.state.user.role),
  hasFinance: () => ['admin', 'manager', 'accounts'].includes(ctx.state.user.role),
  notify: (message, error) => calls.push(['notify', message, Boolean(error)]),
  askText: async () => replies.reason, askConfirm: async () => replies.confirm !== false,
  updateIdentity() {}, $: () => ({}), render() {}, switchView() {}, refresh() {},
  document: {body: {classList: {remove() {}}}, addEventListener() {}, getElementById: () => null, querySelector: () => null},
  FormData: class { constructor(form) { const entries = Object.entries(form.values); entries.get = k => form.values[k]; return entries; } },
  async api(url, opts = {}) {
    calls.push([url, opts.method || 'GET', opts.body ? JSON.parse(opts.body) : null]);
    if (url in replies) return replies[url];
    throw new Error('unexpected call ' + url);
  },
});
for (const file of SCRIPT_FILES) vm.runInContext(fs.readFileSync(file, 'utf8'), ctx);
vm.runInContext(TEST_BODY, ctx);
"""

# Ask for a screen until nothing on it is still loading.
SETTLE = r"""
async function settle(view) {
  let page = '';
  for (let i = 0; i < 20; i++) {
    page = view();
    await new Promise(r => setTimeout(r, 0));
    if (!page.includes('Loading…')) return page;
  }
  return page;
}
"""


def run(scripts, body):
    files = [str(STATIC / 'gapkit.js'), *[str(STATIC / s) for s in scripts]]
    program = (_HARNESS.replace('SCRIPT_FILES', json.dumps(files))
               .replace('TEST_BODY', json.dumps(SETTLE + body)))
    out = subprocess.run(['node', '-'], input=program, capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout) if out.stdout.strip() else None


def assert_wired(script, view=None, accounts=True):
    """The page loads the script (after the helper it needs, before the shell) and the menus list the screen."""
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    order = re.findall(r'<script src="/static/([^"]+)"', html)
    assert order.index('app.js') < order.index('gapkit.js') <= order.index(script) < order.index('shell.js')
    if view:
        assert f"view: '{view}'" in (STATIC / 'nav.js').read_text(encoding='utf-8')
        if accounts:
            assert f"'{view}'" in (STATIC / 'interaction.js').read_text(encoding='utf-8')
    js = (STATIC / script).read_text(encoding='utf-8')
    assert 'style="' not in js and not re.search(r'\son[a-z]+=', js)       # strict Content Security Policy

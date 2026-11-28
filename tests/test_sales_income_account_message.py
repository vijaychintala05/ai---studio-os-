"""N11 from the blind audit (SAL-03): the invoice error for a missing income account must say what to do.

An invoice line takes its income account from its SAC or HSN code (turnkey 9954..., design 998391) and falls back to
the company's only income account. With several income accounts and no matching code there was no account, and the
screen told the Accounts user to "Ask Accounts". Fictional data only.
"""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which('node') is None, reason='Node is not installed')
def test_missing_income_account_says_how_to_fix_it():
    static = Path(__file__).resolve().parents[1] / 'studioos' / 'static'
    program = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ctx = vm.createContext({assert, esc: t => String(t ?? ''), state: {}, render() {}, refresh() {}, switchView() {},
  document: {addEventListener() {}, querySelector() { return null; }}});
vm.runInContext(fs.readFileSync(path.join(process.argv[2], 'sales.js'), 'utf8'), ctx);
vm.runInContext(String.raw`
assert.equal(salesNeedAccount(7, 'sales income'), 7);
let income;
try { salesNeedAccount(null, 'sales income'); } catch (error) { income = error.message; }
assert.match(income, /SAC or HSN/);
assert.match(income, /998391/);
assert.match(income, /9954/);
assert.doesNotMatch(income, /^Ask Accounts/);
let other;
try { salesNeedAccount(null, 'output CGST'); } catch (error) { other = error.message; }
assert.equal(other, 'Ask Accounts to set up the output CGST account for this company.');
`, ctx);
"""
    result = subprocess.run(['node', '-', str(static)], input=program, text=True, encoding='utf-8', capture_output=True)
    assert result.returncode == 0, result.stderr

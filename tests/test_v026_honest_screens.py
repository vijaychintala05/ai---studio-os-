"""v0.26: screens say what really happens. A button that rejects says Reject; a form that sends something for approval says so;
a refresh that fails says so and offers a retry, instead of leaving old numbers on screen. Fictional data only."""
import json
import pathlib
import subprocess

APP = pathlib.Path('studioos/static/app.js').read_text()
CHAT = pathlib.Path('studioos/static/chat.js').read_text()


def test_the_chat_button_that_rejects_is_called_reject():
    assert 'Not now</button>' not in CHAT and 'Not now (from the chat)' not in CHAT
    line = next(l for l in CHAT.splitlines() if 'data-action="cx-reject-item"' in l)
    assert '>Reject</button>' in line
    assert "note: 'Rejected from the chat'" in CHAT


def test_forms_that_send_for_approval_say_so_and_adding_an_employee_does_not():
    block = APP[APP.index('function modal(type)'):APP.index('async function submitModal')]
    assert "(type==='user'?'Save entry':'Send for approval')" in block


def test_failed_requests_are_collected_and_shown_with_a_retry():
    fn = APP[APP.index('function failedKeys'):APP.index('function refreshBanner')]
    out = subprocess.run(['node', '-e', fn + "\nconsole.log(JSON.stringify(failedKeys([{status:'fulfilled'},{status:'rejected'},{status:'fulfilled'},{status:'rejected'}],['a','b','c','d'])));"], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == ['b', 'd']
    banner = APP[APP.index('function refreshBanner'):APP.index('function refreshBanner') + 900]
    assert 'could not be refreshed' in banner and 'data-action="retry-refresh"' in banner
    assert 'state.refreshFailed=failedKeys(results,keys)' in APP
    assert "closest('[data-action=\"retry-refresh\"]')" in APP and "insertAdjacentHTML('afterbegin',refreshBanner())" in APP


def test_banner_is_empty_when_nothing_failed():
    fn = APP[APP.index('function refreshBanner'):APP.index('\n', APP.index('function refreshBanner'))]
    out = subprocess.run(['node', '-e', "const state={refreshFailed:[]};const esc=s=>s;\n" + fn + "\nconsole.log(JSON.stringify(refreshBanner()));"], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == ''

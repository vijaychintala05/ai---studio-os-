"""v0.23.1: typed text survives a sign-out or timeout, and error messages stay until closed."""
import pathlib
import subprocess

JS = pathlib.Path('studioos/static/app.js').read_text()


def _node(expr):
    fn = JS[JS.index('function typingToKeep'):JS.index('function keepTyping')]
    return subprocess.run(['node', '-e', fn + '\nconsole.log(JSON.stringify(' + expr + '));'],
                          capture_output=True, text=True, check=True).stdout.strip()


def test_typed_chat_and_form_values_are_kept():
    out = _node("typingToKeep('fictional-user','Log expense 2000','cost',{title:'Fictional tiles',amount:''},'form-abc')")
    assert '"chat":"Log expense 2000"' in out and 'Fictional tiles' in out and '"requestKey":"form-abc"' in out


def test_nothing_typed_keeps_nothing():
    assert _node("typingToKeep('fictional-user','   ','cost',{title:'',amount:' '},'form-abc')") == 'null'


def test_kept_text_is_tied_to_the_person_and_restored_only_for_them():
    assert "kept.user!==state.user.username" in JS


def test_text_is_saved_on_timeout_and_on_sign_out_and_restored_after_sign_in():
    show_login = JS[JS.index('function showLogin('):JS.index('function showLogin(') + 300]
    assert 'keepTyping();' in show_login
    assert "$('logoutBtn').addEventListener('click',signOut);" in JS
    assert 'showLogin();' in JS[JS.index('async function signOut'):JS.index('async function signOut') + 400]
    assert 'restoreTyping()' in JS[JS.index('async function refresh()'):JS.index('async function refresh()') + 1500]


def test_error_messages_stay_until_closed():
    assert "if(!error)setTimeout(()=>node.remove(),4200)" in JS
    assert 'toast-close' in JS and 'toast-close' in pathlib.Path('studioos/static/styles.css').read_text()

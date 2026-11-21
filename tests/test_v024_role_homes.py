"""v0.24: each role lands on the screen it uses most. Admin and Manager keep the chat, as today."""
import pathlib
import subprocess

JS = pathlib.Path('studioos/static/app.js').read_text()


def home(role):
    fn = JS[JS.index('function homeViewFor'):JS.index('function formRequestKey')]
    return subprocess.run(['node', '-e', fn + f"\nconsole.log(homeViewFor({role!r}));"], capture_output=True, text=True, check=True).stdout.strip()


def test_homes_by_role():
    assert home('site_engineer') == 'home'      # the owner's Home screen (PR #31) builds each role's own widgets
    assert home('accounts') == 'home'
    assert home('architect') == 'home'
    assert home('viewer') == 'home'
    assert home('admin') == 'assistant' and home('manager') == 'assistant'
    assert home('something_new') == 'assistant'


def test_every_home_is_a_screen_that_role_may_open():
    # accounts sees costs; site engineers see site reports; architects see tasks; viewers see projects (ROLE_MATRIX.md Part A)
    matrix = pathlib.Path('ROLE_MATRIX.md').read_text().split('## Part B')[0]
    assert 'See costs, payments, budgets, ledger | Yes | Yes | - | - | Yes | - |' in matrix
    assert 'Post site reports | Yes | Yes | - | Yes | - | - |' in matrix


def test_sign_in_uses_the_role_home():
    assert 'state.view=homeViewFor(r.user&&r.user.role)' in JS

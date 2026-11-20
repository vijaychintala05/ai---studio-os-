"""v0.24 (daily flow): a cost that needs approval is tagged in plain words, "Waiting for approval"."""
import pathlib
import subprocess

JS = pathlib.Path('studioos/static/app.js').read_text()


def test_status_words_are_plain_english():
    fn = JS[JS.index('function statusWords'):JS.index('function pill(')]
    out = subprocess.run(['node', '-e', fn + "\nconsole.log(JSON.stringify([statusWords('pending'),statusWords('approved'),statusWords('some_new_state'),statusWords(null)]));"],
                         capture_output=True, text=True, check=True).stdout.strip()
    assert out == '["Waiting for approval","Approved","some new state",""]'


def test_cost_register_uses_the_plain_words():
    assert 'statusWords(c.status)' in JS

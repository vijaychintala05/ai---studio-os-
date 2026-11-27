"""Pending Books requests use the shared plain-English approval status."""
import pathlib
import subprocess

JS = pathlib.Path('studioos/static/app.js').read_text()


def test_status_words_are_plain_english():
    fn = JS[JS.index('function statusWords'):JS.index('function pill(')]
    out = subprocess.run(['node', '-e', fn + "\nconsole.log(JSON.stringify([statusWords('pending'),statusWords('approved'),statusWords('some_new_state'),statusWords(null)]));"],
                         capture_output=True, text=True, check=True).stdout.strip()
    assert out == '["Waiting for approval","Approved","some new state",""]'


def test_change_request_items_use_the_plain_words():
    assert 'statusWords(i.status)' in JS[JS.index('function ticketDetail'):]

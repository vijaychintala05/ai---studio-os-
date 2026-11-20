"""v0.24: the Inbox screen shows everything waiting for the person in one strip. Fictional data only."""
import json
import pathlib
import subprocess

JS = pathlib.Path('studioos/static/app.js').read_text()


def counts(st):
    fn = JS[JS.index('function waitingCounts'):JS.index('function waitingForYou')]
    out = subprocess.run(['node', '-e', fn + f"\nconsole.log(JSON.stringify(waitingCounts({json.dumps(st)})));"], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def test_counts_only_open_tickets_with_pending_items_and_unfinished_parked_items():
    st = {'tickets': [{'status': 'draft', 'items': [{'status': 'pending'}]},
                      {'status': 'committed', 'items': [{'status': 'pending'}]},
                      {'status': 'draft', 'items': [{'status': 'approved'}]},
                      {'status': 'draft', 'items': []}],
          'newTypes': [{'state': 'waiting_for_approval'}, {'state': 'rejected'}, {'state': 'approved_design_only'}]}
    assert counts(st) == {'tickets': 1, 'parked': 1}


def test_empty_state_is_zero():
    assert counts({}) == {'tickets': 0, 'parked': 0}


def test_inbox_screen_includes_the_strip():
    assert 'waitingForYou()' in pathlib.Path('studioos/static/intake.js').read_text()

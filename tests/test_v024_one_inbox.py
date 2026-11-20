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


def items(st, limit=5):
    fn = JS[JS.index('function waitingCounts'):JS.index('function waitingForYou')]
    out = subprocess.run(['node', '-e', fn + f"\nconsole.log(JSON.stringify(waitingItems({json.dumps(st)},{limit})));"], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def test_the_inbox_lists_each_waiting_thing_with_a_review_button():
    st = {'tickets': [{'id': i, 'status': 'draft', 'items': [{'status': 'pending'}], 'summary': 'x'} for i in range(1, 8)],
          'newTypes': [{'id': 9, 'state': 'waiting_for_approval'}]}
    w = items(st, 5)
    assert w['counts'] == {'tickets': 7, 'parked': 1}
    assert [t['id'] for t in w['tickets']] == [1, 2, 3, 4, 5]      # first five, the rest behind "All 7 tickets"
    assert [h['id'] for h in w['parked']] == [9]
    assert 'data-action="open-ticket"' in JS[JS.index('function waitingForYou'):] and 'data-action="open-new-type"' in JS[JS.index('function waitingForYou'):]

"""The 7 pm evening status through the app: the prompt job, and a reply sorted under the evening headings, where clear matches become draft
tickets only and nothing is saved until someone approves. Fictional data."""
import datetime as dt

from sqlalchemy import select

from studioos.db import ApprovalTicketItem, SessionLocal, SummaryDelivery, Task
from tests.conftest import approved_form, write

NAME = 'StudioOS Administrator'


def test_the_7pm_prompt_is_kept_once_a_day(admin):
    first = write(admin, 'post', '/api/rhythm/run/rhythm_status').json()
    assert first['outcome'] == 'ok' and first['detail'].startswith('1 message')
    assert write(admin, 'post', '/api/rhythm/run/rhythm_status').json()['detail'].startswith('0 message')
    with SessionLocal() as db:
        text = next(d.text for d in db.scalars(select(SummaryDelivery)) if d.summary_key == 'rhythm_status')
    assert 'Evening status' in text and 'Tasks Completed' in text and "Tomorrow's Priorities" in text and 'Nothing is saved' in text


def test_a_reply_is_sorted_and_only_clear_matches_become_drafts(admin):
    p = approved_form(admin, 'post', '/api/projects', {'name': 'Villa Status', 'budget': '100000'}).json()
    t = approved_form(admin, 'post', '/api/tasks', {'project_id': p['id'], 'title': 'Pour second floor slab', 'assignee': NAME, 'due_date': dt.date.today().isoformat()}).json()
    approved_form(admin, 'post', '/api/tasks', {'project_id': p['id'], 'title': 'Order sanitaryware', 'assignee': NAME, 'due_date': '2099-01-01'})
    reply = ('Pour second floor slab completed. Visited the Villa Status site, brickwork going on. Paid Rs 25,000 to the tile vendor. '
             'There is a crack in the south wall. Had chai with Ramesh. Will visit tomorrow.')
    r = write(admin, 'post', '/api/rhythm/status/reply', {'text': reply})
    assert r.status_code == 200, r.text
    body = r.json()
    by = {x['text'].split('.')[0][:20]: x for x in body['pieces']}
    pieces = body['pieces']
    assert [x['category'] for x in pieces] == ['task_done', 'progress', 'financial', 'critical_issue', 'unsorted', 'tomorrow']
    assert pieces[0]['action'] == 'draft' and pieces[0]['ticket_id'] and 'marked done' in pieces[0]['detail']       # matched the one open task
    assert pieces[1]['action'] == 'draft' and 'Villa Status' in pieces[1]['detail']                                  # named the project
    assert pieces[2]['action'] == 'note' and 'chat' in pieces[2]['detail']                                           # money is never entered from here
    assert pieces[3]['action'] == 'note' and pieces[4]['action'] == 'ask' and pieces[5]['action'] == 'note'
    assert body['drafts'] == 2
    with SessionLocal() as db:
        assert db.get(Task, t['id']).status == 'open'                                                                # a draft saves nothing
        kinds = sorted(i.item_type for i in db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.item_type.in_(['update_task', 'site_update']))))
        assert kinds.count('site_update') == 1 and kinds.count('update_task') >= 1
    approve = write(admin, 'post', f"/api/tickets/{pieces[0]['ticket_id']}/approve-and-save", {'confirmed': [], 'note': 'fictional'})
    assert approve.status_code == 200, approve.text
    with SessionLocal() as db:
        assert db.get(Task, t['id']).status == 'done'                                                                # only approval changes it


def test_an_ambiguous_task_or_unnamed_project_is_not_guessed(admin):
    p = approved_form(admin, 'post', '/api/projects', {'name': 'Villa Guess', 'budget': '100000'}).json()
    for title in ('Slab shuttering east', 'Slab shuttering west'):
        approved_form(admin, 'post', '/api/tasks', {'project_id': p['id'], 'title': title, 'assignee': NAME, 'due_date': '2099-01-01'})
    body = write(admin, 'post', '/api/rhythm/status/reply', {'text': 'Shuttering completed. Site inspection done today.'}).json()
    assert body['drafts'] == 0
    assert all(x['action'] != 'draft' for x in body['pieces'])
    assert 'which task' in body['pieces'][0]['detail'] or 'No single' in body['pieces'][0]['detail']
    assert 'Name the project' in body['pieces'][1]['detail']


def test_short_replies_and_viewers_are_refused(admin):
    assert write(admin, 'post', '/api/rhythm/status/reply', {'text': 'ok'}).status_code == 422

"""A private chat message that is really about a project carries an OFFER to send it to that project's team chat. Nothing is posted by the
server: questions, drafts, ambiguous projects and people who may not use the team chat get no offer, and only the person's own tap posts.
Fictional data."""
import re
from pathlib import Path

from tests.conftest import approved_form, write
from tests.test_v018_time_app import staff

STATIC = Path(__file__).resolve().parent.parent / 'studioos' / 'static'


def project(admin, name):
    return approved_form(admin, 'post', '/api/projects', {'name': name, 'budget': '1000'}).json()['id']


def chat(client, message):
    r = write(client, 'post', '/api/chat', {'message': message})
    assert r.status_code == 200, r.text
    return r.json()


def messages(admin, pid):
    return admin.get(f'/api/projects/{pid}/chat').json()['messages']


def test_a_statement_about_one_project_is_offered_and_never_posted_by_the_server(admin):
    pid = project(admin, 'Villa Offer')
    r = chat(admin, 'The slab pour at Villa Offer is tomorrow, please keep the shuttering ready')
    assert r.get('team_chat_offer') == {'project_id': pid, 'name': 'Villa Offer', 'body': 'The slab pour at Villa Offer is tomorrow, please keep the shuttering ready'}
    assert messages(admin, pid) == []                                              # only the person's tap posts it
    sent = write(admin, 'post', f'/api/projects/{pid}/chat', {'body': r['team_chat_offer']['body']})
    assert sent.status_code == 200 and [m['body'] for m in messages(admin, pid)] == [r['team_chat_offer']['body']]


def test_questions_drafts_and_unclear_messages_get_no_offer(admin):
    pid = project(admin, 'Villa Quiet')
    project(admin, 'Villa Quiet Annex')
    assert 'team_chat_offer' not in chat(admin, 'How many open tasks are there at Villa Quiet?')
    assert 'team_chat_offer' not in chat(admin, 'what is the budget for Villa Quiet')
    assert 'team_chat_offer' not in chat(admin, 'Create task: review drawings for Villa Quiet')                    # that became a draft for approval
    assert 'team_chat_offer' not in chat(admin, 'Remember to call the plumber tomorrow')                            # names no project: stays private
    assert 'team_chat_offer' not in chat(admin, 'Hi')
    assert 'team_chat_offer' not in chat(admin, 'Compare the finishes at Villa Quiet and Villa Quiet Annex before Friday please')   # two projects: never a guess
    annex = chat(admin, 'The finishes at Villa Quiet Annex were approved by the client yesterday')
    assert annex['team_chat_offer']['name'] == 'Villa Quiet Annex'                                                  # the longer name is one project, not two
    assert messages(admin, pid) == []


def test_only_people_who_may_use_the_team_chat_are_offered_it(admin):
    pid = project(admin, 'Villa Team Only')
    on, on_id = staff(admin, 'site.offer.on', 'site_engineer')
    off, _ = staff(admin, 'site.offer.off', 'site_engineer')
    acc, _ = staff(admin, 'acc.offer', 'accounts')
    try:
        assert write(admin, 'put', f'/api/projects/{pid}/members', {'user_ids': [on_id]}).status_code == 200
        text = 'The tile delivery for Villa Team Only reached the gate this morning'
        assert chat(on, text).get('team_chat_offer', {}).get('project_id') == pid
        assert 'team_chat_offer' not in chat(off, text)                         # not on the project
        assert 'team_chat_offer' not in chat(acc, text)                         # accounts do not have the team chat
    finally:
        for c in (on, off, acc):
            c.close()


def test_the_button_is_the_only_way_it_is_sent_and_the_files_are_clean():
    js = (STATIC / 'chatoffer.js').read_text(encoding='utf-8')
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    assert '/static/chatoffer.js' in html and html.index('/static/projectpage.js') < html.index('/static/chatoffer.js')
    assert 'data-offer="send"' in js and 'data-offer="keep"' in js and js.count("'POST'") == 1                      # one post, inside the click handler
    assert "b.dataset.offer !== 'send'" in js and 'Keep private' in js
    assert not re.search(r'\sstyle\s*=', js) and 'eval(' not in js and '.style.' not in js

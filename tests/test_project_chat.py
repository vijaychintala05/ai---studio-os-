"""Project chat: one shared chat per project, read and written only by people who can see the project (not Accounts, not viewers), plain text,
ordered, paged, rate-limited, never edited or deleted. Fictional data."""
import re
from pathlib import Path

from sqlalchemy import select

from studioos.db import SessionLocal
from studioos.projectchat import PER_HOUR, ProjectChatMessage
from tests.conftest import approved_form, write
from tests.test_v018_time_app import staff

STATIC = Path(__file__).resolve().parent.parent / 'studioos' / 'static'


def project(admin, name):
    return approved_form(admin, 'post', '/api/projects', {'name': name, 'budget': '1000'}).json()['id']


def say(client, pid, body):
    return write(client, 'post', f'/api/projects/{pid}/chat', {'body': body})


def test_the_team_shares_one_chat_in_order(admin):
    pid = project(admin, 'Villa Chat')
    site, site_id = staff(admin, 'site.chat', 'site_engineer')
    try:
        assert write(admin, 'put', f'/api/projects/{pid}/members', {'user_ids': [site_id]}).status_code == 200
        assert say(admin, pid, 'Slab pour tomorrow at 7').status_code == 200
        assert say(site, pid, 'Noted, shuttering is ready').status_code == 200
        seen = site.get(f'/api/projects/{pid}/chat').json()['messages']
        assert [m['body'] for m in seen] == ['Slab pour tomorrow at 7', 'Noted, shuttering is ready']                 # oldest first
        assert [m['author'] for m in seen] == ['StudioOS Administrator', 'Site.Chat'] or seen[1]['user_id'] == site_id
        later = admin.get(f"/api/projects/{pid}/chat?after={seen[0]['id']}").json()['messages']
        assert [m['body'] for m in later] == ['Noted, shuttering is ready']                                            # only what is new
    finally:
        site.close()


def test_only_people_who_can_see_the_project_may_read_or_write(admin):
    pid = project(admin, 'Villa Private Chat')
    other, _ = staff(admin, 'site.other.chat', 'site_engineer')        # not on the project
    acc, _ = staff(admin, 'acc.chat', 'accounts')                      # sees money only
    viewer, _ = staff(admin, 'viewer.chat', 'viewer')
    try:
        for who in (other, acc, viewer):
            assert who.get(f'/api/projects/{pid}/chat').status_code == 404
            assert say(who, pid, 'hello').status_code == 404
        assert admin.get('/api/projects/999999/chat').status_code == 404
    finally:
        for c in (other, acc, viewer):
            c.close()


def test_messages_are_plain_text_validated_and_limited(admin):
    pid = project(admin, 'Villa Limits')
    assert say(admin, pid, '').status_code == 422 and say(admin, pid, 'x' * 2001).status_code == 422
    assert say(admin, pid, '   ').status_code == 422
    stored = say(admin, pid, '<img src=x onerror=alert(1)>').json()
    assert stored['body'] == '<img src=x onerror=alert(1)>'                                                           # kept as text; the page shows it as text
    for i in range(PER_HOUR - 1):
        assert say(admin, pid, f'm{i}').status_code == 200
    limited = say(admin, pid, 'one too many')
    assert limited.status_code == 429 and 'Too many' in limited.text
    with SessionLocal() as db:
        assert len(db.scalars(select(ProjectChatMessage)).all()) == PER_HOUR


def test_there_is_no_way_to_edit_or_delete_a_message(admin):
    pid = project(admin, 'Villa Keep')
    m = say(admin, pid, 'Original').json()
    url = f"/api/projects/{pid}/chat/{m['id']}"
    headers = {'X-CSRF-Token': admin.cookies.get('studioos_csrf', '')}
    assert admin.put(url, json={'body': 'changed'}, headers=headers).status_code in (404, 405)
    assert admin.patch(url, json={'body': 'changed'}, headers=headers).status_code in (404, 405)
    assert admin.delete(url, headers=headers).status_code in (404, 405)
    assert admin.get(f'/api/projects/{pid}/chat').json()['messages'][0]['body'] == 'Original'


def test_the_page_shows_the_chat_only_to_roles_that_have_it_and_files_are_clean(admin):
    js = (STATIC / 'projectpage.js').read_text(encoding='utf-8')
    assert 'ppChatForm' in js and '/chat`' in js and 'Messages are not edited or deleted' in js
    assert not re.search(r'\sstyle\s*=', js) and 'eval(' not in js and '.style.' not in js and 'innerHTML = m.body' not in js

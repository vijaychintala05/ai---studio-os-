"""AI-client view tools (UI-3): read tools work on a read key; draft tools need a read-and-draft key and only ever open a draft ticket;
bad specs, stale versions and floods are refused; nothing goes live without a person approving. Fictional data."""
from sqlalchemy import select

from studioos.db import ApprovalTicketItem, SessionLocal
from studioos.viewspec_models import ViewSpecRow
from tests.conftest import write
from tests.test_v093_mcp_app import call, key, on, rpc


def spec(view_id='ai.open_tasks', name='Open tasks'):
    return {'spec_version': 1, 'id': view_id, 'name': name, 'primitive': 'table',
            'source': {'items': [{'record_type': 'system.task', 'fields': [{'field': 'title'}, {'field': 'due_date'}],
                                  'filter': {'and': [{'field': 'status', 'op': 'neq', 'value': 'done'}]}}]}}


def approve(admin, ticket):
    r = write(admin, 'post', f'/api/tickets/{ticket}/approve-and-save', {'confirmed': [], 'note': 'fictional'})
    assert r.status_code == 200, r.text


def test_read_key_sees_the_catalogue_but_cannot_draft(admin, monkeypatch):
    on(monkeypatch)
    t = key(admin).json()['token']
    names = [x['name'] for x in rpc(admin, t, 'tools/list').json()['result']['tools']]
    assert {'list_view_primitives', 'list_views', 'get_view', 'validate_view_spec'} <= set(names)
    assert not ({'draft_view', 'draft_view_change', 'draft_view_rollback'} & set(names))
    cat = call(admin, t, 'list_view_primitives')
    assert cat['isError'] is False and 'board' in cat['structuredContent']['primitives'] and 'regex' not in str(cat['structuredContent']['operators_by_kind'])
    ok = call(admin, t, 'validate_view_spec', {'spec': spec()})
    assert ok['structuredContent']['valid'] is True and ok['structuredContent']['base_version'] is None
    bad = call(admin, t, 'validate_view_spec', {'spec': {**spec(), 'primitive': 'map'}})
    assert bad['structuredContent']['valid'] is False and 'primitive' in bad['content'][0]['text']
    refused = rpc(admin, t, 'tools/call', {'name': 'draft_view', 'arguments': {'spec': spec()}}).json()
    assert 'error' in refused or refused['result']['isError']
    with SessionLocal() as db:
        assert db.scalars(select(ViewSpecRow)).all() == []                              # a dry run stores nothing


def test_draft_tools_open_tickets_and_nothing_goes_live_until_approved(admin, monkeypatch):
    on(monkeypatch)
    t = key(admin, scope='read_draft').json()['token']
    drafted = call(admin, t, 'draft_view', {'spec': spec(), 'scope': 'system'})
    assert drafted['isError'] is False and drafted['structuredContent']['saved'] is False
    ticket = drafted['structuredContent']['ticket']
    assert call(admin, t, 'list_views')['structuredContent']['views'] == []             # still not live
    approve(admin, ticket)
    got = call(admin, t, 'get_view', {'key': 'ai.open_tasks'})['structuredContent']
    assert got['version'] == 1 and got['versions'] == [1] and got['spec']['name'] == 'Open tasks'
    changed = call(admin, t, 'draft_view_change', {'key': 'ai.open_tasks', 'base_version': 1, 'spec': spec(name='Open tasks, v2')})
    approve(admin, changed['structuredContent']['ticket'])
    assert call(admin, t, 'get_view', {'key': 'ai.open_tasks'})['structuredContent']['version'] == 2
    stale = call(admin, t, 'draft_view_change', {'key': 'ai.open_tasks', 'base_version': 1, 'spec': spec(name='Stale')})
    assert stale['isError'] is True and 'moved on' in stale['content'][0]['text']
    back = call(admin, t, 'draft_view_rollback', {'key': 'ai.open_tasks', 'to_version': 1})
    approve(admin, back['structuredContent']['ticket'])
    final = call(admin, t, 'get_view', {'key': 'ai.open_tasks'})['structuredContent']
    assert final['version'] == 3 and final['spec']['name'] == 'Open tasks'
    diff = call(admin, t, 'validate_view_spec', {'spec': spec(name='Renamed again')})['structuredContent']
    assert diff['base_version'] == 3 and any('changed name' in d for d in diff['diff'])


def test_bad_specs_markup_and_unknown_views_are_refused(admin, monkeypatch):
    on(monkeypatch)
    t = key(admin, scope='read_draft').json()['token']
    for bad in ({**spec(), 'script': 'alert(1)'}, {**spec(), 'primitive': 'calendar'}, {**spec('ai.x'), 'source': {'items': [{'record_type': 'ghost', 'fields': [{'field': 'a'}]}]}}):
        r = call(admin, t, 'draft_view', {'spec': bad})
        assert r['isError'] is True
    html = spec('ai.html', '<img src=x onerror=alert(1)>')
    drafted = call(admin, t, 'draft_view', {'spec': html})
    approve(admin, drafted['structuredContent']['ticket'])                                # a label is data; the page renders it as text
    assert call(admin, t, 'get_view', {'key': 'ai.html'})['structuredContent']['spec']['name'] == '<img src=x onerror=alert(1)>'
    missing = call(admin, t, 'get_view', {'key': 'no.such.view'})
    assert missing['isError'] is True
    big = call(admin, t, 'validate_view_spec', {'spec': {**spec(), 'labels': {'en': 'x' * 40000}}})
    assert big['isError'] is True or big['structuredContent']['valid'] is False


def test_a_flood_of_drafts_is_stopped(admin, monkeypatch):
    on(monkeypatch)
    t = key(admin, scope='read_draft').json()['token']
    made = 0
    for i in range(33):
        r = call(admin, t, 'draft_view', {'spec': spec(f'ai.flood{i}')})
        if r['isError']:
            assert 'Too many' in r['content'][0]['text']
            break
        made += 1
    assert made == 30
    with SessionLocal() as db:
        assert len(db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.item_type == 'view_create')).all()) == 30

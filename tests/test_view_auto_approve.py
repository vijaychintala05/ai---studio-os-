"""Automatic approval of a person's own personal views (owner decision): only personal, plain views made in the app; never shared, role or
system views, never a client audience or a money field, never a draft opened by an AI client; the owner can switch it off; and the
shortcut does not leave a general way to approve other people's drafts. Fictional data."""
from sqlalchemy import select

from studioos import viewspec_rules as r
from studioos.db import ApprovalTicket, SessionLocal
from studioos.viewspec_models import ViewSpecRow
from tests.conftest import write
from tests.test_v018_time_app import staff
from tests.test_v093_mcp_app import call, key, on
from tests.test_viewspec_app import task_list


def propose(client, kind, data):
    return write(client, 'post', '/api/viewspecs/propose', {'kind': kind, 'data': data})


def view_id(key_):
    with SessionLocal() as db:
        return db.scalar(select(ViewSpecRow.id).where(ViewSpecRow.spec_key == key_))


def ticket_status(ticket_id):
    with SessionLocal() as db:
        return db.get(ApprovalTicket, ticket_id).status


def test_plain_means_no_client_and_no_money_field():
    base = task_list()
    assert r.spec_is_plain(base)
    assert not r.spec_is_plain({**base, 'audience': {'roles': ['manager', 'client']}})
    for field in ('cost_paise', 'amount', 'budget', 'unit_price', 'gst_rate', 'invoice_no', 'balance'):
        spec = task_list()
        spec['source']['items'][0]['fields'].append({'field': field})
        assert not r.spec_is_plain(spec), field
    spec = task_list()
    spec['source']['items'][0]['filter'] = {'and': [{'field': 'total_cost', 'op': 'gt', 'value': 1}]}
    assert not r.spec_is_plain(spec)                                                    # money in a filter counts too


def test_a_personal_view_is_approved_automatically_and_goes_live_at_once(admin):
    site, site_id = staff(admin, 'site.auto', 'site_engineer')
    try:
        made = propose(site, 'view_create', {'spec': task_list('auto.mine'), 'scope': 'user'}).json()
        assert made['auto_approved'] is True and made['reason'] is None and ticket_status(made['ticket_id']) == 'committed'
        assert [v['key'] for v in site.get('/api/viewspecs').json()] == ['auto.mine']
        vid = view_id('auto.mine')
        changed = propose(site, 'view_change', {'view_id': vid, 'base_version': 1, 'spec': task_list('auto.mine', 'Renamed')}).json()
        assert changed['auto_approved'] is True and site.get('/api/viewspecs/auto.mine').json()['version'] == 2
        back = propose(site, 'view_rollback', {'view_id': vid, 'to_version': 1}).json()
        assert back['auto_approved'] is True and site.get('/api/viewspecs/auto.mine').json()['version'] == 3
    finally:
        site.close()


def test_shared_money_and_client_views_still_wait_for_a_person(admin):
    shared = propose(admin, 'view_create', {'spec': task_list('auto.shared'), 'scope': 'system'}).json()
    assert shared['auto_approved'] is False and 'personal' in shared['reason'] and ticket_status(shared['ticket_id']) != 'committed'
    assert view_id('auto.shared') is None
    client_view = propose(admin, 'view_create', {'spec': {**task_list('auto.client'), 'audience': {'roles': ['client']}}, 'scope': 'user'}).json()
    assert client_view['auto_approved'] is False and 'client' in client_view['reason'] and view_id('auto.client') is None
    site, _ = staff(admin, 'site.auto2', 'site_engineer')
    try:
        mine = propose(site, 'view_create', {'spec': task_list('auto.site2'), 'scope': 'user'}).json()
        other = propose(admin, 'view_change', {'view_id': view_id('auto.site2'), 'base_version': 1, 'spec': task_list('auto.site2', 'By owner')}).json()
        assert mine['auto_approved'] is True and other['auto_approved'] is False        # the owner changing someone else's personal view is a normal ticket
    finally:
        site.close()


def test_the_owner_can_switch_it_off(admin):
    site, _ = staff(admin, 'site.auto3', 'site_engineer')
    try:
        assert propose(site, 'view_setting', {'key': r.AUTO_KEY, 'value': 'off'}).status_code == 400          # only the owner
        drafted = propose(admin, 'view_setting', {'key': r.AUTO_KEY, 'value': 'off'})
        assert drafted.status_code == 200, drafted.text
        assert write(admin, 'post', f"/api/tickets/{drafted.json()['ticket_id']}/approve-and-save", {'confirmed': [], 'note': 'fictional'}).status_code == 200
        held = propose(site, 'view_create', {'spec': task_list('auto.off'), 'scope': 'user'}).json()
        assert held['auto_approved'] is False and 'switched off' in held['reason'] and view_id('auto.off') is None
        assert propose(admin, 'view_setting', {'key': 'something_else', 'value': 'on'}).status_code == 400
        assert propose(admin, 'view_setting', {'key': r.AUTO_KEY, 'value': 'maybe'}).status_code == 400
    finally:
        site.close()


def test_a_draft_from_an_ai_client_is_never_approved_automatically(admin, monkeypatch):
    on(monkeypatch)
    t = key(admin, scope='read_draft').json()['token']
    drafted = call(admin, t, 'draft_view', {'spec': task_list('auto.ai'), 'scope': 'user'})
    assert drafted['isError'] is False and drafted['structuredContent']['saved'] is False
    assert ticket_status(drafted['structuredContent']['ticket']) != 'committed' and view_id('auto.ai') is None      # a person must approve it


def test_the_shortcut_is_not_a_general_way_to_approve_other_peoples_drafts(admin, monkeypatch):
    on(monkeypatch)
    t = key(admin, scope='read_draft').json()['token']
    pending = call(admin, t, 'draft_view', {'spec': task_list('auto.pending'), 'scope': 'user'})['structuredContent']['ticket']
    site, _ = staff(admin, 'site.auto4', 'site_engineer')
    try:
        refused = write(site, 'post', f'/api/tickets/{pending}/approve-and-save', {'confirmed': [], 'note': 'trying'})
        assert refused.status_code in (403, 404), refused.text                          # a site engineer cannot approve a draft by tapping
        assert view_id('auto.pending') is None
    finally:
        site.close()

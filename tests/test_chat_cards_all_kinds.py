"""The missing-details form saves several details at once for every kind of draft: one request per draft item. These API tests send exactly
what the form sends (the draft's values with several fields changed together) for an everyday entry, a built record type and a books entry,
and check the card then shows them as filled. Fictional data."""
from .conftest import write
from .test_v0100_one_graph import install, project as graph_project
from .test_v0914_chart_of_accounts import books, chat
from .test_v098_universal_accounting import propose


def card_items(admin, session_id):
    return admin.get('/api/chat/history/' + session_id).json()['card']['items']


def test_an_everyday_entry_takes_several_details_in_one_save(admin):
    books(admin)
    reply = chat(admin, 'Bought tiles from Kajaria Studio for Fictional Project A')                 # no amount: a plain expense with details missing
    item = next(i for i in reply['preview']['items'] if i['item_type'] == 'record_cost')
    missing = {f['key'] for f in item['fields'] if f['marker'] == 'missing'}
    assert 'amount_paise' in missing
    after = {**item['after'], 'amount_paise': 320000, 'vendor': 'Kajaria Studio'}
    saved = write(admin, 'patch', f"/api/tickets/items/{item['id']}", {'after': after, 'note': ''})
    assert saved.status_code == 200, saved.text
    now = next(i for i in card_items(admin, reply['session_id']) if i['id'] == item['id'])
    markers = {f['key']: f['marker'] for f in now['fields']}
    assert markers['amount_paise'] != 'missing' and now['after']['amount_paise'] == 320000


def test_a_built_record_type_takes_several_details_in_one_save(admin):
    install(admin, 'work')
    pid = graph_project(admin)
    me = admin.get('/api/auth/me').json()['user']['id']
    made = propose(admin, 'metadata_record', {'type_key': 'work_issue', 'project_id': pid,
                                              'values': {'title': 'Glass delayed', 'owner': me, 'severity': 'High', 'issue_status': 'Open'}})
    item = admin.get(f"/api/tickets/{made['ticket_id']}").json()['items'][0]
    after = {**item['after'], 'values': {**item['after']['values'], 'title': 'Glass delayed by a week', 'severity': 'Low'}}
    saved = write(admin, 'patch', f"/api/tickets/items/{item['id']}", {'after': after, 'note': ''})
    assert saved.status_code == 200, saved.text
    values = admin.get(f"/api/tickets/{made['ticket_id']}").json()['items'][0]['after']['values']
    assert values['title'] == 'Glass delayed by a week' and values['severity'] == 'Low'


def test_a_books_entry_takes_several_details_in_one_save(admin):
    books(admin)
    reply = chat(admin, 'Bought tiles from Kajaria Studio 40,000 with GST for Fictional Project A')
    entry = next(i for i in reply['preview']['items'] if i['item_type'] == 'finance_text_entry')
    missing = {f['key'] for f in entry['fields'] if f['marker'] == 'missing'}
    assert {'slots.gst_rate', 'slots.settlement'} <= missing                                   # what the form would ask for
    slots = {**entry['after']['slots'], 'gst_mode': 'extra', 'gst_rate': 18, 'settlement': 'credit'}
    saved = write(admin, 'patch', f"/api/tickets/items/{entry['id']}", {'after': {**entry['after'], 'slots': slots}, 'note': ''})
    assert saved.status_code == 200, saved.text
    now = next(i for i in card_items(admin, reply['session_id']) if i['item_type'] == 'finance_text_entry')
    still = {f['key'] for f in now['fields'] if f['marker'] == 'missing'}
    assert not {'slots.gst_rate', 'slots.settlement'} & still                                  # both are filled by the one save
    assert any(line['account'] for line in now['journal'])                                     # and the books lines are worked out again

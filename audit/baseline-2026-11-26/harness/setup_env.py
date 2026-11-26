"""Seed a DISPOSABLE StudioOS copy with fictional data for the blind audit, and write accounts.json
(random fictional passwords; keep that file out of git). Run once against a fresh, empty database.

  python setup_env.py http://localhost:8770 <owner-username> <owner-password> accounts.json
"""
import json, secrets, sys
import requests

B, OWNER, OWNER_PW, OUT = sys.argv[1].rstrip('/'), sys.argv[2], sys.argv[3], sys.argv[4]


def sess(user, pw):
    s = requests.Session()
    r = s.post(B + '/api/auth/login', json={'username': user, 'password': pw})
    assert r.status_code == 200, (user, r.text)
    return s


def w(s, method, url, data=None):
    return getattr(s, method)(B + url, json=data or {}, headers={'X-CSRF-Token': s.cookies.get('studioos_csrf', '')})


o = sess(OWNER, OWNER_PW)


def approve(ticket):
    x = w(o, 'post', f'/api/tickets/{ticket}/approve-and-save', {'confirmed': ['duplicate', 'amount'], 'note': 'Audit fixture'})
    assert x.status_code == 200, x.text
    return x.json()['committed_records'][0]


def approve_req(r):
    assert r.status_code == 200, r.text
    return approve(r.json()['ticket_id'])


def prop(kind, data, s=o):
    r = w(s, 'post', '/api/universal/proposals', {'kind': kind, 'data': data, 'evidence': 'Audit fixture'})
    assert r.status_code == 200, (kind, r.text)
    return r


accounts = {'owner': {'username': OWNER, 'password': OWNER_PW}}
ids = {}
NAMES = {'manager': 'Meera Manager', 'architect': 'Arjun Architect', 'site_engineer': 'Sanjay Site',
         'accounts': 'Anita Accounts', 'viewer': 'Vikram Viewer'}
for role, name in NAMES.items():
    pw = 'Fx-' + secrets.token_urlsafe(12)
    r = w(o, 'post', '/api/users', {'username': role + '.audit', 'display_name': name, 'role': role, 'password': pw})
    assert r.status_code == 200, r.text
    ids[role] = r.json()['id']
    accounts[role] = {'username': role + '.audit', 'password': pw}

p1 = approve_req(w(o, 'post', '/api/projects', {'name': 'Kapoor Villa (Audit)', 'client': 'Kapoor Family', 'location': 'Pune', 'budget': '2500000'}))
p2 = approve_req(w(o, 'post', '/api/projects', {'name': 'Mehta Office Fitout (Audit)', 'client': 'Mehta Traders', 'location': 'Mumbai', 'budget': '1800000'}))
r = w(o, 'put', f'/api/projects/{p1["id"]}/members', {'user_ids': [ids['architect'], ids['site_engineer'], ids['viewer'], ids['manager']]})
assert r.status_code == 200, r.text
for title, who in (('Order tiles for master bath', 'Arjun Architect'), ('Pour first-floor slab', 'Sanjay Site')):
    approve_req(w(o, 'post', '/api/tasks', {'project_id': p1['id'], 'title': title, 'assignee': who, 'due_date': '2026-12-05'}))

entity = approve_req(prop('finance_setup', {'entity_name': 'Audit Constructions Pvt Ltd', 'expense_code': '5000', 'ap_code': '2100',
                                            'bank_code': '1000', 'bank_name': 'HDFC Current - Audit', 'bank_masked': '****4321'}))['id']
approve_req(prop('finance_open_petty_cash', {'entity_id': entity, 'user_id': ids['site_engineer']}))
approve_req(prop('finance_install_chart', {'entity_id': entity, 'standard': 'india_interiors'}))   # so sales and tax accounts exist

a = sess(accounts['accounts']['username'], accounts['accounts']['password'])
vendor = approve_req(w(a, 'post', '/api/books/vendors', {'name': 'Shree Tiles Pvt Ltd', 'gst_treatment': 'registered_regular', 'gstin': '27ABCDE1234F1Z5',
                                                         'pan': 'ABCDE1234F', 'default_tds_section': '194C', 'payment_terms_days': 30}))
client = approve_req(w(a, 'post', '/api/books/clients', {'name': 'Rao Family', 'gst_treatment': 'unregistered',
                                                         'billing_address': '12 Gandhi Road, Nashik', 'payment_terms_days': 15}))
opts = w(a, 'get', '/api/books/bill-options').json()
expense = next(x for x in opts['accounts'] if x['kind'] == 'expense')['id']
for inv, bill_date, due, amt in (('SH-1001', '2026-11-02', '2026-11-12', 5000000), ('SH-1002', '2026-11-20', '2026-11-30', 3000000)):
    approve_req(w(a, 'post', '/api/books/bills', {'entity_id': entity, 'supplier_id': vendor['id'], 'invoice_number': inv, 'bill_date': bill_date,
                                                  'due_date': due, 'payment_terms_days': 10 if inv == 'SH-1002' else 10, 'amount_paise': amt,
                                                  'lines': [{'account_id': expense, 'project_id': p1['id'], 'description': 'Tiles', 'amount_paise': amt}]}))
ar = sess(accounts['architect']['username'], accounts['architect']['password'])
for t in ('Review window schedule', 'Confirm lift core drawings'):          # left pending for the approval cases
    assert w(ar, 'post', '/api/tasks', {'project_id': p1['id'], 'title': t, 'assignee': 'Arjun Architect', 'due_date': '2026-12-12'}).status_code == 200

json.dump({'accounts': accounts, 'project_ids': [p1['id'], p2['id']], 'entity_id': entity}, open(OUT, 'w'), indent=1)
print('seeded; wrote', OUT)

"""v0.9.14: chart of accounts in groups, account search, approved new-account suggestions
and text entries posted through the protected ledger. Fictional data, disposable DB.
Runs in CI on SQLite and PostgreSQL 16 (STUDIOOS_TEST_DATABASE_URL)."""
import pytest
from sqlalchemy import select, func, text
from .conftest import write
from .test_v098_universal_accounting import propose, save, project, vendor, finance_setup
from studioos.db import (SessionLocal, engine, GLAccount, GLJournal, GLLine, GLAccountProfile, FinanceTextEntry,
                         GLPostingRecipe, ApprovalTicketItem)

CEMENT = 'Bought 50 bags of cement from Sri Ram Traders for Fictional Project A, ₹21,000 plus 18% GST, on credit'


def books(admin):
    pid = project(admin)
    entity = finance_setup(admin)
    save(admin, propose(admin, 'finance_install_chart', {'entity_id': entity, 'standard': 'india_interiors'}))
    return pid, entity


def chat(admin, message, session_id=None):
    r = write(admin, 'post', '/api/chat', {'message': message, **({'session_id': session_id} if session_id else {})})
    assert r.status_code == 200, r.text
    return r.json()


def approve(admin, reply, confirmed=()):
    path = f'/api/tickets/{reply["ticket_id"]}'
    reviewed = reply.get('preview') or admin.get(path).json()
    fingerprints = {i['id']: i['review_fingerprint'] for i in reviewed['items']}
    return write(admin, 'post', path + '/approve-and-save',
                 {'confirmed': list(confirmed), 'review_fingerprints': fingerprints})


def account(entity, name):
    with SessionLocal() as db:
        return db.scalar(select(GLAccount).where(GLAccount.entity_id == entity, GLAccount.name == name))


def lines_of(journal_id):
    with SessionLocal() as db:
        return sorted((db.get(GLAccount, l.account_id).name, l.side, l.amount_paise)
                      for l in db.scalars(select(GLLine).where(GLLine.journal_id == journal_id)).all())


def test_install_adds_groups_places_setup_accounts_and_is_not_repeated(admin):
    pid, entity = books(admin)
    standards = admin.get(f'/api/finance-ledger/standards/{entity}').json()
    assert standards[0]['key'] == 'india_interiors' and standards[0]['state'] == 'installed'
    chart = admin.get(f'/api/finance-ledger/chart/{entity}').json()
    by_code = {a['code']: a for a in chart['accounts']}
    assert by_code['SUNDRY_CREDITORS']['is_group'] and not by_code['SUNDRY_CREDITORS']['postable']
    assert by_code['1000']['parent'] == by_code['BANK_ACCOUNTS']['id']             # the approved ICICI bank account, placed
    assert by_code['2100']['parent'] == by_code['CURRENT_LIABILITIES']['id']        # the AP control account, placed
    assert chart['balanced'] and chart['standard'] == {'key': 'india_interiors', 'version': 1}
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(GLPostingRecipe)) == 5
    again = write(admin, 'post', '/api/universal/proposals', {'kind': 'finance_install_chart', 'data': {'entity_id': entity, 'standard': 'india_interiors'},
                                                             'evidence': 'second install'})
    assert again.status_code == 422 and 'already installed' in again.text


def test_cement_sentence_suggests_supplier_account_and_posts_balanced_gst_journal(admin):
    pid, entity = books(admin)
    reply = chat(admin, CEMENT)
    items = reply['preview']['items']
    assert [i['item_type'] for i in items] == ['finance_open_account', 'finance_text_entry']
    entry = items[1]
    assert [(j['side'], j['account'], j['amount']) for j in entry['journal']] == [
        ('Dr', 'Cement', '₹21,000'), ('Dr', 'Input CGST', '₹1,890'), ('Dr', 'Input SGST', '₹1,890'), ('Cr', 'Sri Ram Traders', '₹24,780')]
    assert items[0]['after']['name'] == 'Sri Ram Traders' and 'Sundry Creditors' in items[0]['line']
    assert 'no account for "Sri Ram Traders"' in reply['reply'].lower() or 'suggested' in reply['reply']
    saved = approve(admin, reply)
    assert saved.status_code == 200, saved.text
    records = saved.json()['committed_records']
    assert [r['type'] for r in records] == ['gl_account', 'finance_text_entry']     # account opened before the entry
    journal = records[1]['journal_id']
    assert lines_of(journal) == sorted([('Cement', 'debit', 2_100_000), ('Input CGST', 'debit', 189_000), ('Input SGST', 'debit', 189_000),
                                        ('Sri Ram Traders', 'credit', 2_478_000)])
    supplier = account(entity, 'Sri Ram Traders')
    with SessionLocal() as db:
        profile = db.scalar(select(GLAccountProfile).where(GLAccountProfile.account_id == supplier.id))
        assert db.get(GLAccount, profile.parent_id).code == 'SUNDRY_CREDITORS' and supplier.kind == 'creditor'
        assert db.get(GLJournal, journal).source_event == 'TEXT_ENTRY_POSTED'
    integrity = admin.get(f'/api/finance-ledger/integrity/{entity}').json()
    assert integrity['passed'], integrity['findings']                            # AP control still agrees with supplier bills
    chart = admin.get(f'/api/finance-ledger/chart/{entity}').json()
    by_code = {a['code']: a for a in chart['accounts']}
    assert chart['balanced'] and chart['expense_paise'] == 2_100_000
    assert by_code['DIRECT_COSTS']['debit_paise'] == 2_100_000                   # rolled up through Direct Material
    assert by_code['SUNDRY_CREDITORS']['balance_paise'] == 2_478_000 and by_code['SUNDRY_CREDITORS']['side'] == 'Cr'
    costs = admin.get(f'/api/finance-ledger/project-costs/{pid}').json()
    assert costs['posted_material_expense_net_paise'] == 2_100_000


def test_second_entry_finds_the_new_account_and_duplicate_needs_confirmation(admin):
    pid, entity = books(admin)
    assert approve(admin, chat(admin, CEMENT)).status_code == 200
    again = chat(admin, CEMENT)
    assert [i['item_type'] for i in again['preview']['items']] == ['finance_text_entry']   # found, not suggested again
    blocked = approve(admin, again)
    assert blocked.status_code == 409 and blocked.json()['needs_confirmation'] == 'duplicate'
    assert approve(admin, again, ['duplicate']).status_code == 200
    pay = chat(admin, 'Paid 24,780 to Sri Ram Traders by bank transfer')
    assert [(j['side'], j['account']) for j in pay['preview']['items'][0]['journal']] == [('Dr', 'Sri Ram Traders'), ('Cr', 'ICICI Current - Fictional')]
    assert approve(admin, pay).status_code == 200
    chart = {a['code']: a for a in admin.get(f'/api/finance-ledger/chart/{entity}').json()['accounts']}
    assert chart['SUNDRY_CREDITORS']['balance_paise'] == 2_478_000                   # two bills, one paid


def test_answers_and_edits_rework_the_draft_from_the_recipe(admin):
    pid, entity = books(admin)
    reply = chat(admin, 'Bought tiles from Kajaria Studio 40,000 with GST for Fictional Project A')
    entry = next(i for i in reply['preview']['items'] if i['item_type'] == 'finance_text_entry')
    assert any(a['field'] == 'slots.gst_mode' for a in reply['ask'])
    assert approve(admin, reply).status_code == 422                               # cannot post with GST unclear
    for field, value in (('slots.gst_mode', 'extra'), ('slots.gst_rate', 18), ('slots.amount', '40000')):
        r = write(admin, 'post', '/api/chat/answer', {'session_id': reply['session_id'], 'item_id': entry['id'], 'field': field, 'value': value})
        assert r.status_code == 200, r.text
    card = r.json()['preview']['items']
    entry = next(i for i in card if i['item_type'] == 'finance_text_entry')
    assert [(j['side'], j['account'], j['amount']) for j in entry['journal']][:3] == [
        ('Dr', 'Tiles and Stone', '₹40,000'), ('Dr', 'Input CGST', '₹3,600'), ('Dr', 'Input SGST', '₹3,600')]
    # choose another account for the item: only accounts in the recipe's groups are offered
    choice = next(f for f in entry['fields'] if f['key'] == 'accounts.item')
    names = {c['label'] for c in choice['choices']}
    assert 'Plywood and Boards' in names and 'ICICI Current - Fictional' not in names and 'Owner\'s Capital' not in names
    plywood = next(c['value'] for c in choice['choices'] if c['label'] == 'Plywood and Boards')
    r = write(admin, 'post', '/api/chat/answer', {'session_id': reply['session_id'], 'item_id': entry['id'], 'field': 'accounts.item', 'value': plywood})
    assert r.status_code == 200
    capital = account(entity, "Owner's Capital").id
    bad = write(admin, 'post', '/api/chat/answer', {'session_id': reply['session_id'], 'item_id': entry['id'], 'field': 'accounts.item', 'value': capital})
    assert bad.status_code == 422
    saved = approve(admin, r.json())
    assert saved.status_code == 200, saved.text
    journal = [x for x in saved.json()['committed_records'] if x['type'] == 'finance_text_entry'][0]['journal_id']
    assert ('Plywood and Boards', 'debit', 4_000_000) in lines_of(journal)


def test_rejected_suggestion_means_the_entry_cannot_post(admin):
    pid, entity = books(admin)
    reply = chat(admin, 'Bought acoustic panels from Soundcraft 45,000 no GST for Fictional Project A')
    suggestions = [i for i in reply['preview']['items'] if i['item_type'] == 'finance_open_account']
    assert {s['after']['name'] for s in suggestions} == {'Acoustic Panels', 'Soundcraft'}
    r = write(admin, 'post', f'/api/tickets/items/{suggestions[0]["id"]}/reject', {'note': 'use an existing account'})
    assert r.status_code == 200
    blocked = approve(admin, reply)
    assert blocked.status_code in (409, 422)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(FinanceTextEntry)) == 0
        assert db.scalar(select(func.count()).select_from(GLJournal)) == 0


def test_forged_entry_with_an_account_outside_the_recipe_is_refused(admin):
    pid, entity = books(admin)
    bank = account(entity, 'ICICI Current - Fictional').id
    creditor_group = account(entity, 'Sundry Creditors (Vendors)').id
    forged = write(admin, 'post', '/api/finance-ledger/proposals', {'kind': 'finance_text_entry', 'evidence': 'forged',
        'data': {'entity_id': entity, 'recipe': 'purchase', 'slots': {'amount': 100_000, 'item': 'cement', 'from_party': 'X', 'gst_mode': 'none'},
                 'accounts': {'item': bank, 'party': creditor_group}, 'project_id': pid, 'idempotency_key': 'forged-entry-0001'}})
    assert forged.status_code == 422
    lines = write(admin, 'post', '/api/finance-ledger/proposals', {'kind': 'finance_text_entry', 'evidence': 'forged',
        'data': {'entity_id': entity, 'recipe': 'purchase', 'slots': {'amount': 100_000}, 'accounts': {}, 'idempotency_key': 'forged-entry-0002',
                 'lines': [{'account': bank, 'side': 'debit', 'amount': 1}]}})
    assert lines.status_code == 422                                              # lines are never accepted from outside


def test_reversal_posts_a_linked_opposite_journal_and_undo_is_refused(admin):
    pid, entity = books(admin)
    saved = approve(admin, chat(admin, 'Paid 2,000 cash for office electricity'))
    assert saved.status_code == 200
    record = saved.json()['committed_records'][0]
    undo = write(admin, 'post', f'/api/tickets/{saved.json()["ticket_id"]}/reverse', {'reason': 'try to hide it'})
    assert undo.status_code == 409 and 'reversing entry' in undo.text
    reverse = save(admin, propose(admin, 'finance_reverse_text_entry', {'entry_id': record['id'], 'reason': 'Entered by mistake'}))
    assert sorted(lines_of(reverse['journal_id'])) == sorted([('Electricity (office)', 'credit', 200_000), ('Cash in Hand', 'debit', 200_000)])
    chart = admin.get(f'/api/finance-ledger/chart/{entity}').json()
    assert chart['expense_paise'] == 0 and chart['balanced']
    entries = admin.get(f'/api/finance-ledger/text-entries/{entity}').json()['entries']
    assert entries[0]['reversed'] is True
    twice = write(admin, 'post', '/api/finance-ledger/proposals', {'kind': 'finance_reverse_text_entry', 'evidence': 'again',
                                                                 'data': {'entry_id': record['id'], 'reason': 'again'}})
    assert twice.status_code == 422


def test_client_invoice_and_receipt_track_receivable_and_revenue(admin):
    pid, entity = books(admin)
    # This large, independently asserted fixture now requires the actual amount review.
    assert approve(admin, chat(admin, 'Invoiced Mr Mehta 2,50,000 plus 18% GST for design fees'), confirmed=('amount',)).status_code == 200
    assert approve(admin, chat(admin, 'Received 1,00,000 from Mr Mehta by NEFT')).status_code == 200
    chart = admin.get(f'/api/finance-ledger/chart/{entity}').json()
    by_code = {a['code']: a for a in chart['accounts']}
    assert chart['income_paise'] == 25_000_000 and chart['profit_paise'] == 25_000_000
    assert by_code['SUNDRY_DEBTORS']['balance_paise'] == 19_500_000 and by_code['SUNDRY_DEBTORS']['side'] == 'Dr'
    assert by_code['DUTIES_TAXES']['balance_paise'] == 4_500_000 and by_code['DUTIES_TAXES']['side'] == 'Cr'


def test_people_without_an_accounts_role_are_not_drafted_entries(admin):
    pid, entity = books(admin)
    r = write(admin, 'post', '/api/users', {'username': 'site.fictional', 'display_name': 'Site Fictional', 'role': 'site_engineer',
                                           'password': 'fictional-site-password-123'})
    assert r.status_code == 200, r.text
    from fastapi.testclient import TestClient
    from studioos.main import app
    with TestClient(app) as other:
        assert other.post('/api/auth/login', json={'username': 'site.fictional', 'password': 'fictional-site-password-123'}).status_code == 200
        reply = write(other, 'post', '/api/chat', {'message': CEMENT})
        assert reply.status_code in (200, 403)
        if reply.status_code == 200:
            assert all(not i['item_type'].startswith('finance_') for i in (reply.json().get('preview') or {}).get('items', []))
        assert other.get(f'/api/finance-ledger/chart/{entity}').status_code == 403


def test_chart_tables_reject_direct_changes(admin):
    pid, entity = books(admin)
    from sqlalchemy.exc import DBAPIError
    with pytest.raises(DBAPIError):
        with engine.begin() as connection:
            connection.execute(text('UPDATE gl_account_profiles SET parent_id = NULL'))
    with pytest.raises(DBAPIError):
        with engine.begin() as connection:
            connection.execute(text('DELETE FROM gl_posting_recipes'))

"""Site expense privacy and posting with fictional projects and vendors."""
from pathlib import Path

from studioos.db import Document, FinanceExpense, IntakeItem, Party, SessionLocal
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.schema import CreateTable
from studioos.migrations import LATEST_VERSION, apply_migrations

from .conftest import write
from .test_intake_document_files import PNG
from .test_v0140_intake_app import _up
from .test_money_document_dates import draft
from .test_v025_site_expense_flow import site
from .test_v098_universal_accounting import finance_setup, propose, save, vendor


def test_site_form_does_not_fall_back_to_tracker_when_options_fail():
    from pathlib import Path

    script = Path('studioos/static/app.js').read_text(encoding='utf-8')
    handler = script.split('async function loadSiteExpenseOptions', 1)[1].split('function modal(type)', 1)[0]
    assert "fields.replaceChildren" in handler
    assert "Paid to (optional)" not in handler


def test_site_category_selects_only_an_approved_company_account(admin, site):
    mine, other, engineer, _, _ = site
    entity = finance_setup(admin)
    save(admin, propose(admin, 'finance_install_chart', {'entity_id': entity, 'standard': 'india_interiors'}))
    chart = {row['code']: row for row in admin.get(f'/api/finance-ledger/chart/{entity}').json()['accounts']}
    expense = chart['TRANSPORT']['id']
    setup = {'entity_id': entity, 'name': 'Site travel', 'expense_account_id': expense}
    assert draft(engineer, 'finance_expense_category', setup).status_code == 403
    proposal = draft(admin, 'finance_expense_category', setup)
    assert proposal.status_code == 200, proposal.text
    options = '/api/site-expenses/options'
    assert engineer.get(options).json()['categories'] == []
    category = save(admin, proposal.json())
    assert engineer.get(options).json()['categories'] == [{'id': category['id'], 'name': 'Site travel'}]
    assert engineer.get(f'{options}?project_id={other}').status_code == 404
    data = {'project_id': mine, 'category_id': category['id'], 'personal_payment': True,
            'no_vendor': True, 'no_vendor_name': 'Fictional bus driver', 'title': 'Fictional site trip',
            'amount': '150.25', 'request_key': 'fictional-site-category-trip'}
    result = write(engineer, 'post', '/api/site-expenses', data)
    assert result.status_code == 200, result.text
    posted = save(admin, result.json())
    journal = next(row for row in admin.get(f'/api/finance-ledger/journals/{entity}').json()
                   if row['id'] == posted['journal_id'])
    assert next(line for line in journal['lines'] if line['side'] == 'debit')['account_id'] == expense
    trial = admin.get(f'/api/finance-ledger/trial-balance/{entity}').json()
    assert trial['total_debit_paise'] == trial['total_credit_paise'] == 15_025
    pending = write(engineer, 'post', '/api/site-expenses', {**data, 'request_key': 'fictional-category-stale-trip'})
    assert pending.status_code == 200, pending.text
    replacement = draft(admin, 'finance_expense_category', {**setup, 'expense_account_id': chart['5000']['id']})
    assert replacement.status_code == 200, replacement.text
    updated = save(admin, replacement.json())
    assert engineer.get(options).json()['categories'] == [{'id': updated['id'], 'name': 'Site travel'}]
    stale = write(admin, 'post', f'/api/tickets/{pending.json()["ticket_id"]}/approve-and-save', {})
    assert stale.status_code in (409, 422) and 'category changed' in stale.text.lower()
    with SessionLocal() as db:
        assert db.get(FinanceExpense, posted['id']).category_id == category['id']

    from .test_v0914_chart_of_accounts import chat
    reply = chat(admin, 'Record expense Rs 120 for Site travel by cash; No vendor: Fictional street taxi')
    assert reply.get('ticket_id'), reply
    entry = admin.get(f'/api/tickets/{reply["ticket_id"]}').json()['items'][0]['after']
    assert entry['category_id'] == updated['id'] and entry['expense_account_id'] == chart['5000']['id']


def test_expense_category_schema_matches_v49_upgrade(monkeypatch):
    table = 'finance_expense_categories'
    monkeypatch.setattr('studioos.migrations.before_schema_migration', lambda *_: None)
    old, fresh = create_engine('sqlite://'), create_engine('sqlite://')
    try:
        apply_migrations(old)
        with old.begin() as conn:
            ddl = str(CreateTable(FinanceExpense.__table__).compile(dialect=old.dialect))
            old_ddl = '\n'.join(line for line in ddl.splitlines() if 'category_id' not in line)
            old_ddl = old_ddl.rstrip().removesuffix(')').rstrip().removesuffix(',') + '\n)'
            conn.execute(text('DROP TABLE finance_expenses'))
            conn.execute(text(f'DROP TABLE {table}'))
            conn.execute(text(old_ddl))
            conn.execute(text('DELETE FROM schema_migrations WHERE version > 49'))
        apply_migrations(old)
        apply_migrations(fresh)
        with old.connect() as conn:
            assert conn.scalar(text('SELECT MAX(version) FROM schema_migrations')) == LATEST_VERSION
        upgraded, current = inspect(old), inspect(fresh)
        for shape in ('get_indexes', 'get_foreign_keys', 'get_unique_constraints'):
            assert getattr(upgraded, shape)(table) == getattr(current, shape)(table)
        for schema in (upgraded, current):
            column = next(c for c in schema.get_columns('finance_expenses') if c['name'] == 'category_id')
            assert column['nullable'] and str(column['type']) == 'INTEGER'
            assert any(fk['constrained_columns'] == ['category_id'] and fk['referred_table'] == table
                       for fk in schema.get_foreign_keys('finance_expenses'))
    finally:
        old.dispose()
        fresh.dispose()


def test_site_expense_uses_books_after_setup_even_without_ledger_switch(admin, site):
    mine, _, engineer, _, _ = site
    endpoint = '/api/site-expenses'
    old = {'project_id': mine, 'title': 'Fictional site supplies', 'vendor': 'Fictional Trader',
           'amount': '120.75', 'request_key': 'fictional-post-setup-old'}
    pending = write(engineer, 'post', endpoint, old)
    assert pending.status_code == 200, pending.text
    company = finance_setup(admin)
    stale = write(admin, 'post', f'/api/tickets/{pending.json()["ticket_id"]}/approve-and-save', {})
    assert stale.status_code in (409, 422) and 'Site expense' in stale.text
    refused = write(engineer, 'post', endpoint, old)
    assert refused.status_code in (400, 422) and 'Site expense' in refused.text
    posted = write(engineer, 'post', endpoint, {
        **old, 'vendor': '', 'personal_payment': True, 'no_vendor': True, 'no_vendor_name': 'Fictional site stall',
        'request_key': 'fictional-post-setup-books',
    })
    assert posted.status_code == 200, posted.text
    result = save(admin, posted.json())
    assert result['type'] == 'finance_expense'
    assert admin.get('/api/costs').json() == []
    trial = admin.get(f'/api/finance-ledger/trial-balance/{company}').json()
    assert trial['total_debit_paise'] == trial['total_credit_paise'] == 12_075


def test_site_expense_uses_only_the_approved_project_company(admin, site):
    mine, _, engineer, _, _ = site
    first = finance_setup(admin)
    chosen = save(admin, propose(admin, 'finance_setup', {
        'entity_name': 'Fictional Second Company', 'expense_code': '5000', 'ap_code': '2100',
        'bank_code': '1000', 'bank_name': 'Fictional Second Bank', 'bank_masked': '****1357',
    }))['id']
    data = {'project_id': mine, 'entity_id': chosen}
    assert draft(engineer, 'finance_project_company', data).status_code == 403
    retired = draft(admin, 'finance_project_company', data)
    assert retired.status_code == 422 and 'Set the company on the project' in retired.text

    def change_company(actor, target):
        return write(actor, 'post', '/api/tickets/proposals', {'kind': 'update_project',
                     'data': {'id': mine, 'company_id': target}, 'evidence': 'Fictional company change'})

    assert change_company(engineer, chosen).status_code == 403
    change = change_company(admin, chosen)
    assert change.status_code == 200, change.text
    assert admin.get('/api/projects').json()[0]['company_id'] == first

    claim_data = {
        'ledger': True, 'personal_payment': True, 'no_vendor': True, 'no_vendor_name': 'Fictional delivery driver',
        'amount': '100.01', 'title': 'Fictional site delivery', 'request_key': 'fictional-site-company-001',
    }
    pending = write(engineer, 'post', '/api/site-expenses', claim_data)
    assert pending.status_code == 200, pending.text
    save(admin, change.json())

    stale = write(admin, 'post', f'/api/tickets/{pending.json()["ticket_id"]}/approve-and-save', {})
    assert stale.status_code in (400, 409, 422)
    options = engineer.get('/api/site-expenses/options').json()
    assert options['project_id'] == mine and 'entity_id' not in options

    retry = write(engineer, 'post', '/api/site-expenses', claim_data)
    assert retry.json()['ticket_id'] == pending.json()['ticket_id']
    claim = write(engineer, 'post', '/api/site-expenses', {**claim_data, 'request_key': 'fictional-site-company-002'})
    assert claim.status_code == 200, claim.text
    save(admin, claim.json())
    assert change_company(admin, first).status_code == 422
    assert admin.get(f'/api/finance-ledger/journals/{first}').json() == []
    trial = admin.get(f'/api/finance-ledger/trial-balance/{chosen}').json()
    assert trial['total_debit_paise'] == trial['total_credit_paise'] == 10_001


def test_site_company_schema_matches_upgrade(monkeypatch):
    table = 'finance_project_companies'
    monkeypatch.setattr('studioos.migrations.before_schema_migration', lambda *_: None)
    old, fresh = create_engine('sqlite://'), create_engine('sqlite://')
    try:
        apply_migrations(old)
        with old.begin() as conn:
            conn.execute(text(f'DROP TABLE {table}'))
            conn.execute(text('DELETE FROM schema_migrations WHERE version > 45'))
        apply_migrations(old)
        apply_migrations(fresh)
        with old.connect() as conn:
            assert conn.scalar(text('SELECT MAX(version) FROM schema_migrations')) == LATEST_VERSION
            assert conn.scalar(text('SELECT version FROM schema_migrations WHERE version = 46')) == 46
        upgraded, current = inspect(old), inspect(fresh)
        for shape in ('get_foreign_keys', 'get_indexes'):
            assert getattr(upgraded, shape)(table) == getattr(current, shape)(table)
        columns = [[(c['name'], str(c['type']), c['nullable']) for c in schema.get_columns(table)]
                   for schema in (upgraded, current)]
        assert columns[0] == columns[1]
    finally:
        old.dispose()
        fresh.dispose()


def test_site_photo_is_filed_with_approved_expense(admin, site, tmp_path, monkeypatch):
    monkeypatch.setenv('STUDIOOS_INTAKE_DIR', str(tmp_path / 'intake'))
    mine, _, engineer, _, _ = site
    finance_setup(admin)
    private = _up(admin, 'fictional-private.png', PNG).json()
    photo = _up(engineer, 'fictional-receipt.png', PNG).json()
    body = {'ledger': True, 'personal_payment': True, 'amount': '123.45',
            'title': 'Fictional paper supplies', 'no_vendor': True, 'no_vendor_name': 'Fictional paper shop',
            'request_key': 'fictional-site-with-receipt'}
    endpoint = '/api/site-expenses'
    blocked = write(engineer, 'post', endpoint, {**body, 'receipt_intake_id': private['id']})
    assert blocked.status_code in (400, 422), blocked.text
    proposal = write(engineer, 'post', endpoint, {**body, 'receipt_intake_id': photo['id']})
    assert proposal.status_code == 200, proposal.text
    assert engineer.get('/api/site-expenses/options').json()['receipts'] == []
    with SessionLocal() as db:
        path = Path(db.get(IntakeItem, photo['id']).stored_path)
    path.chmod(0o600)
    path.write_bytes(PNG[:-1] + bytes([PNG[-1] ^ 1]))
    ticket_url = f'/api/tickets/{proposal.json()["ticket_id"]}/approve-and-save'
    refused = write(admin, 'post', ticket_url, {})
    assert refused.status_code in (409, 422) and 'changed after approval' in refused.text
    assert engineer.get('/api/site-expenses/options').json()['receipts'] == []
    path.write_bytes(PNG)
    saved = save(admin, proposal.json())
    with SessionLocal() as db:
        doc = db.get(Document, db.get(FinanceExpense, saved['id']).receipt_id)
        assert doc.project_id == mine
        doc_id = doc.id
    download = engineer.get(f'/api/documents/{doc_id}/file')
    assert download.status_code == 200 and download.content == PNG
    repeated = write(engineer, 'post', endpoint, {**body, 'receipt_intake_id': photo['id']})
    assert repeated.json()['ticket_id'] == proposal.json()['ticket_id']


def test_site_vendor_suggestion_posts_only_with_expense_approval(admin, site):
    mine, other, engineer, _, _ = site
    company = finance_setup(admin)
    name = 'Fictional Site Paint Shop'
    body = {'ledger': True, 'personal_payment': True, 'amount': '2545.67',
            'title': 'Fictional paint supplies', 'suggested_vendor_name': name,
            'request_key': 'fictional-site-new-vendor-001'}
    endpoint = '/api/site-expenses'
    assert write(engineer, 'post', endpoint, {**body, 'project_id': other}).status_code == 404
    assert write(engineer, 'post', endpoint, {**body, 'no_vendor': True}).status_code in (400, 422)
    proposal = write(engineer, 'post', endpoint, body)
    assert proposal.status_code == 200, proposal.text
    ticket = proposal.json()
    ticket_url = f'/api/tickets/{ticket["ticket_id"]}'
    card = admin.get(ticket_url).json()['items'][0]
    assert card['after']['suggested_vendor_name'] == name
    assert write(engineer, 'post', endpoint, body).json()['ticket_id'] == ticket['ticket_id']
    assert write(engineer, 'post', endpoint, {**body, 'suggested_vendor_name': 'Fictional Different Shop'}).status_code == 409
    assert write(engineer, 'post', ticket_url + '/approve-and-save', {}).status_code == 403
    with SessionLocal() as db:
        assert db.scalar(select(Party.id).where(Party.name == name)) is None
    assert admin.get(f'/api/finance-ledger/journals/{company}').json() == []
    save(admin, ticket)
    vendors = engineer.get('/api/site-expenses/options').json()['vendors']
    assert len(vendors) == 1 and vendors[0]['name'] == name
    trial = admin.get(f'/api/finance-ledger/trial-balance/{company}').json()
    assert trial['total_debit_paise'] == trial['total_credit_paise'] == 254_567
    second = write(engineer, 'post', endpoint, {
        **body, 'suggested_vendor_name': name.upper(),
        'request_key': 'fictional-site-new-vendor-002',
    })
    assert second.status_code == 200, second.text
    second_card = admin.get(f'/api/tickets/{second.json()["ticket_id"]}').json()['items'][0]
    assert any('split expense' in flag.lower() for flag in second_card['flags'])
    save(admin, second.json())
    assert engineer.get('/api/site-expenses/options').json()['vendors'] == vendors


def test_site_expense_options_and_approved_posting_are_scoped(admin, site):
    mine, other, engineer, _, _ = site
    company = finance_setup(admin)
    vendor_a = vendor(admin)
    with SessionLocal() as db:
        private_vendor = Party(kind='vendor', name='Fictional other vendor', gstin='00FICTIONAL000X')
        db.add(private_vendor)
        db.commit()
        vendor_b = private_vendor.id
    engineer_id = next(row['id'] for row in admin.get('/api/users').json() if row['username'] == 'se_eng')
    petty = save(admin, draft(admin, 'finance_open_petty_cash', {'entity_id': company, 'user_id': engineer_id}).json())
    for pid, supplier in ((mine, vendor_a), (other, vendor_b)):
        order = draft(admin, 'finance_po', {
            'entity_id': company, 'supplier_id': supplier, 'project_id': pid,
            'po_number': f'FICT-SITE-{pid}', 'amount_paise': 1_000_000,
        })
        assert order.status_code == 200, order.text
        save(admin, order.json())

    options = engineer.get('/api/site-expenses/options')
    assert options.status_code == 200, options.text
    choices = options.json()
    assert choices['project_id'] == mine
    assert choices['paid_through'] == {'id': petty['id'], 'name': 'Your petty cash'}
    assert [item['id'] for item in choices['vendors']] == [vendor_a]
    assert set(choices['vendors'][0]) == {'id', 'name'}
    assert engineer.get(f'/api/site-expenses/options?project_id={other}').status_code == 404
    assert engineer.get(f'/api/finance-ledger/trial-balance/{company}').status_code == 403

    body = {'ledger': True, 'vendor_id': vendor_a, 'amount': '250.50', 'title': 'Fictional site tea',
            'request_key': 'fictional-site-ledger-001'}
    assert write(engineer, 'post', '/api/site-expenses', {**body, 'vendor_id': vendor_b}).status_code in (400, 422)
    assert write(engineer, 'post', '/api/site-expenses', {**body, 'amount': '5001'}).status_code == 400
    proposed = write(engineer, 'post', '/api/site-expenses', body)
    assert proposed.status_code == 200, proposed.text
    card = admin.get(f'/api/tickets/{proposed.json()["ticket_id"]}').json()['items'][0]
    assert card['item_type'] == 'finance_expense'
    assert card['after']['paid_through_id'] == petty['id']
    assert any('below zero' in flag for flag in card['flags'])
    assert write(engineer, 'post', '/api/site-expenses', body).json()['ticket_id'] == proposed.json()['ticket_id']
    changed = write(engineer, 'post', '/api/site-expenses', {**body, 'amount': '251.50'})
    assert changed.status_code == 409
    assert 'different' in changed.text.lower()
    assert admin.get(f'/api/finance-ledger/journals/{company}').json() == []
    save(admin, proposed.json())
    trial = admin.get(f'/api/finance-ledger/trial-balance/{company}').json()
    assert trial['total_debit_paise'] == trial['total_credit_paise'] == 25_050
    assert admin.get('/api/costs').json() == []

    next_expense = write(engineer, 'post', '/api/site-expenses', {
        **body, 'expense_date': '2026-08-31', 'request_key': 'fictional-site-ledger-002',
    })
    assert next_expense.status_code == 200, next_expense.text
    assert write(admin, 'put', f'/api/projects/{mine}/members', {'user_ids': []}).status_code == 200
    refused = write(admin, 'post', f'/api/tickets/{next_expense.json()["ticket_id"]}/approve-and-save', {})
    assert refused.status_code in (409, 422) and 'project you can access' in refused.text

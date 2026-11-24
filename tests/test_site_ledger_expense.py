"""Site expense privacy and posting with fictional projects and vendors."""
from studioos.db import Party, SessionLocal

from .conftest import write
from .test_money_document_dates import draft
from .test_v025_site_expense_flow import site
from .test_v098_universal_accounting import finance_setup, save, vendor


def test_site_form_does_not_fall_back_to_tracker_when_options_fail():
    from pathlib import Path

    script = Path('studioos/static/app.js').read_text(encoding='utf-8')
    handler = script.split('async function loadSiteExpenseOptions', 1)[1].split('function modal(type)', 1)[0]
    assert "fields.replaceChildren" in handler
    assert "Paid to (optional)" not in handler


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

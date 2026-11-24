"""Site expense privacy and posting with fictional projects and vendors."""
from pathlib import Path

from studioos.db import Document, FinanceExpense, IntakeItem, Party, SessionLocal
from sqlalchemy import select

from .conftest import write
from .test_intake_document_files import PNG
from .test_v0140_intake_app import _up
from .test_money_document_dates import draft
from .test_v025_site_expense_flow import site
from .test_v098_universal_accounting import finance_setup, save, vendor


def test_site_form_does_not_fall_back_to_tracker_when_options_fail():
    from pathlib import Path

    script = Path('studioos/static/app.js').read_text(encoding='utf-8')
    handler = script.split('async function loadSiteExpenseOptions', 1)[1].split('function modal(type)', 1)[0]
    assert "fields.replaceChildren" in handler
    assert "Paid to (optional)" not in handler


def test_site_photo_is_filed_with_approved_expense(admin, site, tmp_path, monkeypatch):
    monkeypatch.setenv('STUDIOOS_INTAKE_DIR', str(tmp_path / 'intake'))
    mine, _, engineer, _, _ = site
    finance_setup(admin)
    private = _up(admin, 'fictional-private.png', PNG).json()
    photo = _up(engineer, 'fictional-receipt.png', PNG).json()
    body = {'ledger': True, 'personal_payment': True, 'amount': '123.45',
            'title': 'Fictional paper supplies', 'no_vendor': True,
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

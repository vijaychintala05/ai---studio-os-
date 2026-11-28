"""Receipt uploads and links use only fictional files and disposable storage."""
from studioos import intake_core, intake_wiring
from sqlalchemy import MetaData, select
from studioos.db import Base, RecordAttachment, SessionLocal
from studioos.migrations import apply_migrations

from .conftest import write
from .test_m2_bill_form import _setup_company_and_vendor
from .test_snag_photos import b64, png
from .test_v0100_one_graph import add_user, client_for
from .test_v0914_chart_of_accounts import books
from .test_v68_form_schema import isolated_engine, table_shape


def test_receipt_upload_checks_file_bytes_and_keeps_the_staged_file_private(admin, tmp_path, monkeypatch):
    monkeypatch.setenv('STUDIOOS_INTAKE_DIR', str(tmp_path))
    monkeypatch.setattr(intake_wiring, 'SCANNER', intake_core.FakeScanner())
    receipt = png()
    response = write(admin, 'post', '/api/expense-images', {
        'filename': 'fictional-receipt.png', 'base64': b64(receipt),
    })
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['media_type'] == 'image/png'
    url = f"/api/expense-images/{data['id']}"
    assert not admin.get('/api/intake/items').json()['items']
    assert admin.get(f"/api/intake/items/{data['id']}/file").status_code == 404
    source = admin.get(url)
    assert source.content == receipt
    assert 'no-store' in source.headers['cache-control']
    assert source.headers['x-content-type-options'] == 'nosniff'

    add_user(admin, 'fictional.receipt.accounts', 'accounts')
    other = client_for('fictional.receipt.accounts')
    try:
        assert other.get(url).status_code == 404
    finally:
        other.close()
    refused = write(admin, 'post', '/api/expense-images', {
        'filename': 'fictional-not-a-photo.jpg', 'base64': b64(b'plain text'),
    })
    assert refused.status_code == 422


def test_receipt_staging_refuses_a_failed_safety_scan(admin, tmp_path, monkeypatch):
    monkeypatch.setenv('STUDIOOS_INTAKE_DIR', str(tmp_path))
    monkeypatch.setattr(intake_wiring, 'SCANNER', intake_core.FakeScanner('scan_error'))
    refused = write(admin, 'post', '/api/expense-images', {
        'filename': 'fictional-receipt.png', 'base64': b64(png(2)),
    })
    assert refused.status_code == 422
    assert 'safety scan' in refused.text


def test_supplier_bill_links_the_receipt_only_when_saved(admin, tmp_path, monkeypatch):
    monkeypatch.setenv('STUDIOOS_INTAKE_DIR', str(tmp_path))
    monkeypatch.setattr(intake_wiring, 'SCANNER', intake_core.FakeScanner())
    entity, vendor, account, _, project = _setup_company_and_vendor(admin)
    add_user(admin, 'fictional.bill.accounts', 'accounts')
    accounts = client_for('fictional.bill.accounts')
    try:
        receipt = write(accounts, 'post', '/api/expense-images', {'filename': 'fictional-bill.png', 'base64': b64(png())})
        assert receipt.status_code == 200, receipt.text
        receipt_id = receipt.json()['id']
        url = f'/api/expense-images/{receipt_id}'
        assert admin.get(url).status_code == 404
        data = {
            'entity_id': entity, 'supplier_id': vendor, 'invoice_number': 'FICT-RECEIPT',
            'bill_date': '2026-11-10', 'due_date': '2026-12-10', 'payment_terms_days': 30,
            'amount_paise': 4200, 'receipt_ids': [receipt_id],
            'lines': [{'account_id': account, 'project_id': project, 'amount_paise': 4200}],
        }
        forged = write(admin, 'post', '/api/books/bills', data)
        assert forged.status_code == 422, forged.text
        bill = write(accounts, 'post', '/api/books/bills', data)
        assert bill.status_code == 200, bill.text
    finally:
        accounts.close()
    ticket_id = bill.json()['ticket_id']
    assert admin.get(f'{url}?ticket_id={ticket_id}').content == png()
    with SessionLocal() as db:
        assert db.scalar(select(RecordAttachment)) is None
    reviewed = write(admin, 'post', f'/api/tickets/{ticket_id}/approve-and-save')
    assert reviewed.status_code == 200, reviewed.text
    with SessionLocal() as db:
        linked = db.scalar(select(RecordAttachment))
        assert linked is not None and linked.intake_item_id == receipt_id and linked.kind == 'direct_bill'
    party = admin.get(f'/api/books/parties/{vendor}').json()
    assert party['bills'][0]['attachments'][0]['id'] == receipt_id
    assert admin.get(url).content == png()


def test_chat_receipt_attaches_to_a_books_expense_draft(admin, tmp_path, monkeypatch):
    monkeypatch.setenv('STUDIOOS_INTAKE_DIR', str(tmp_path))
    monkeypatch.setattr(intake_wiring, 'SCANNER', intake_core.FakeScanner())
    books(admin)
    receipt = write(admin, 'post', '/api/expense-images', {'filename': 'fictional-taxi.png', 'base64': b64(png())})
    assert receipt.status_code == 200, receipt.text
    receipt_id = receipt.json()['id']
    reply = write(admin, 'post', '/api/chat', {
        'message': 'Record expense Rs 120 for transport by cash; No vendor: Fictional street taxi',
        'attachment_ids': [receipt_id],
    })
    assert reply.status_code == 200, reply.text
    item = reply.json()['preview']['items'][0]
    assert item['item_type'] == 'finance_expense'
    assert item['after']['receipt_ids'] == [receipt_id]
    assert item['attachments'][0]['id'] == receipt_id
    saved = write(admin, 'post', f"/api/tickets/{reply.json()['ticket_id']}/approve-and-save")
    assert saved.status_code == 200, saved.text
    with SessionLocal() as db:
        linked = db.scalar(select(RecordAttachment))
        assert linked is not None and linked.intake_item_id == receipt_id and linked.kind == 'expense'


def test_receipt_link_schema_matches_a_fresh_database(tmp_path, monkeypatch):
    monkeypatch.setattr('studioos.migrations.before_schema_migration', lambda *_: None)
    with isolated_engine(tmp_path, 'old-receipts') as old, isolated_engine(tmp_path, 'fresh-receipts') as fresh:
        metadata = MetaData()
        for table in Base.metadata.sorted_tables:
            if table.name != 'record_attachments':
                table.to_metadata(metadata)
        metadata.create_all(old)
        versions = metadata.tables['schema_migrations']
        with old.begin() as conn:
            conn.execute(versions.insert().values(version=68, description='Fictional v68 baseline'))
        apply_migrations(old)
        apply_migrations(fresh)
        with old.connect() as upgraded, fresh.connect() as clean:
            assert upgraded.scalar(select(versions.c.version).order_by(versions.c.version.desc()).limit(1)) >= 69
            assert table_shape(upgraded, 'record_attachments') == table_shape(clean, 'record_attachments')

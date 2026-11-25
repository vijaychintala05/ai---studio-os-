"""M2-6 (claude/attachments-everywhere): Append-only document attachments across
money entries with SHA-256 duplicate receipt warning, outsider 403, and v55 schema parity.
Fictional data only.
"""
from sqlalchemy import create_engine, inspect, text

from studioos.db import Base, Document, FinanceDirectBill, SessionLocal
from studioos.migrations import LATEST_VERSION, apply_migrations
from tests.conftest import write
from tests.test_m2_bill_form import _setup_company_and_vendor
from tests.test_v018_time_app import staff


def test_attachments_and_duplicate_sha256_warning(admin, tmp_path):
    entity_id, vendor_id, acc1, _, proj_id = _setup_company_and_vendor(admin)

    # Create two approved direct bills
    for inv in ('FICT-ATT-1', 'FICT-ATT-2'):
        r = write(admin, 'post', '/api/books/bills', {
            'entity_id': entity_id, 'supplier_id': vendor_id, 'invoice_number': inv,
            'bill_date': '2026-11-10', 'due_date': '2026-12-10', 'payment_terms_days': 30,
            'amount_paise': 20_000,
            'lines': [{'account_id': acc1, 'project_id': proj_id, 'description': 'Fictional item', 'amount_paise': 20_000}],
        })
        assert r.status_code == 200, r.text
        assert write(admin, 'post', f'/api/tickets/{r.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200

    # Create a fictional receipt file
    f1 = tmp_path / 'fictional_receipt.pdf'
    f1.write_bytes(b'%PDF-1.4 fictional receipt bytes')
    with SessionLocal() as db:
        bills = db.query(FinanceDirectBill).order_by(FinanceDirectBill.id).all()
        b1_id, b2_id = bills[0].id, bills[1].id
        doc = Document(project_id=proj_id, name='fictional_receipt.pdf', relative_path=str(f1), doc_type='pdf')
        db.add(doc)
        db.commit()
        doc_id = doc.id

    # Attach to bill 1 -> no duplicate warning
    a1 = write(admin, 'post', '/api/books/attachments', {
        'entity_id': entity_id, 'target_kind': 'direct_bill', 'target_id': b1_id,
        'document_id': doc_id, 'note': 'Original vendor bill PDF',
    })
    assert a1.status_code == 200, a1.text
    assert a1.json()['duplicate_warning'] is False
    assert write(admin, 'post', f'/api/tickets/{a1.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200

    listed = admin.get(f'/api/books/attachments?target_kind=direct_bill&target_id={b1_id}').json()
    assert len(listed['attachments']) == 1 and listed['attachments'][0]['document_name'] == 'fictional_receipt.pdf'

    # Attaching the same file to bill 2 triggers duplicate_warning=True
    a2 = write(admin, 'post', '/api/books/attachments', {
        'entity_id': entity_id, 'target_kind': 'direct_bill', 'target_id': b2_id,
        'document_id': doc_id, 'note': 'Same file attached again',
    })
    assert a2.status_code == 200, a2.text
    assert a2.json()['duplicate_warning'] is True
    assert len(a2.json()['existing_targets']) == 1

    # Invalid target_kind refused
    bad = write(admin, 'post', '/api/books/attachments', {
        'entity_id': entity_id, 'target_kind': 'invalid_kind', 'target_id': 1, 'document_id': doc_id,
    })
    assert bad.status_code == 422


def test_outsider_cannot_view_or_attach_finance_documents(admin):
    site, _ = staff(admin, 'site.attcheck', 'site_engineer')
    try:
        assert site.get('/api/books/attachments?target_kind=direct_bill&target_id=1').status_code == 403
        assert write(site, 'post', '/api/books/attachments', {}).status_code in (403, 422)
    finally:
        site.close()


def test_v55_upgraded_schema_matches_fresh_schema(tmp_path):
    fresh = create_engine(f'sqlite:///{tmp_path / "fresh.db"}')
    upgraded = create_engine(f'sqlite:///{tmp_path / "upgraded.db"}')
    try:
        Base.metadata.create_all(fresh)
        apply_migrations(upgraded)
        with upgraded.connect() as conn:
            assert conn.scalar(text('SELECT MAX(version) FROM schema_migrations')) == LATEST_VERSION
        fresh_insp, upg_insp = inspect(fresh), inspect(upgraded)
        assert 'finance_attachments' in upg_insp.get_table_names()
        assert ({c['name'] for c in fresh_insp.get_columns('finance_attachments')}
                == {c['name'] for c in upg_insp.get_columns('finance_attachments')})
    finally:
        fresh.dispose()
        upgraded.dispose()

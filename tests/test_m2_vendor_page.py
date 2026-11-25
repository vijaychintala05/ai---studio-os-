"""M2-4 (claude/vendor-page): Enhanced Vendor page (direct bill payments, unallocated advances)
and ReportLab Vendor Statement PDF scoped to AMOUNT_ROLES. Fictional data only.
"""
from tests.conftest import write
from tests.test_m2_bill_form import _setup_company_and_vendor
from tests.test_v018_time_app import staff


def test_vendor_page_direct_bill_payment_and_statement_pdf(admin):
    entity_id, vendor_id, acc1, _, proj_id = _setup_company_and_vendor(admin)

    # Create and approve a direct bill
    r = write(admin, 'post', '/api/books/bills', {
        'entity_id': entity_id, 'supplier_id': vendor_id, 'invoice_number': 'FICT-STMT-01',
        'bill_date': '2026-11-05', 'due_date': '2026-12-05', 'payment_terms_days': 30,
        'amount_paise': 90_000,
        'lines': [{'account_id': acc1, 'project_id': proj_id, 'description': 'Fictional veneer', 'amount_paise': 90_000}],
    })
    assert r.status_code == 200, r.text
    tid = r.json()['ticket_id']
    assert write(admin, 'post', f'/api/tickets/{tid}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200

    # Partially pay the bill via Pay selected
    due = admin.get('/api/books/bills-due').json()
    bill_id = (due['overdue'] + due['due_this_week'] + due['due_later'])[0]['bill_id']
    bank_acc = due['paying_accounts'][str(entity_id)][0]['id']
    pay = write(admin, 'post', '/api/books/pay-selected', {
        'entity_id': entity_id, 'paid_through_id': bank_acc,
        'payment_date': '2026-11-10', 'payment_reference': 'UTR-STMT-1',
        'items': [{'kind': 'direct_bill', 'bill_id': bill_id, 'amount_paise': 40_000}],
    })
    assert pay.status_code == 200, pay.text
    ptid = pay.json()['ticket_id']
    assert write(admin, 'post', f'/api/tickets/{ptid}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200

    # Vendor page reflects remaining balance and direct bill payment
    party = admin.get(f'/api/books/parties/{vendor_id}').json()
    assert party['owed_paise'] == 50_000
    assert any(p['reference'] == 'UTR-STMT-1' and p['amount_paise'] == 40_000 for p in party['payments'])
    assert party['unallocated_advance_paise'] == 0

    # Statement PDF renders cleanly for admin
    pdf = admin.get(f'/api/books/parties/{vendor_id}/statement.pdf')
    assert pdf.status_code == 200
    assert pdf.headers['content-type'].startswith('application/pdf')
    assert pdf.content.startswith(b'%PDF')

    # Outsider roles cannot download statement PDF
    arch, _ = staff(admin, 'arch.stmt', 'architect')
    site, _ = staff(admin, 'site.stmt', 'site_engineer')
    try:
        assert arch.get(f'/api/books/parties/{vendor_id}/statement.pdf').status_code == 403
        assert site.get(f'/api/books/parties/{vendor_id}/statement.pdf').status_code == 403
    finally:
        arch.close()
        site.close()

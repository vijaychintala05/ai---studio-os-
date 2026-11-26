"""End-to-end tests for Zoho-style Chart of Accounts, Purchases (GST/TDS, partial PO billing,
vendor credit & advance allocation), Sales/AR credit notes & ageing, flexible Indian bank CSV
+ BRS, GSTR-1/3B & TDS registers, hierarchical P&L/BS, Trial Balance, Project Profitability,
and CSV export. Fictional data only.
"""
from __future__ import annotations

from sqlalchemy import inspect, select

from studioos.bank_feed import parse_bank_csv
from studioos.db import (
    FinanceDirectBill,
    FinanceVendorCredit,
    GLAccount,
    GLJournal,
    GLLine,
    RegisteredBank,
    SalesInvoice,
    SessionLocal,
    engine,
)
from studioos.direct_bills import direct_bill_outstanding
from studioos.migrations import LATEST_VERSION
from studioos.sales_receipts import invoice_outstanding

from .conftest import write
from .test_v098_universal_accounting import finance_setup, project, propose, save, vendor


def _setup_with_chart(admin):
    entity = finance_setup(admin)
    save(admin, propose(admin, 'finance_install_chart', {'entity_id': entity, 'standard': 'india_interiors'}))
    pid = project(admin)
    vid = vendor(admin)
    return entity, pid, vid


def _approve_ticket(admin, ticket_id: int):
    r = write(admin, 'post', f'/api/tickets/{ticket_id}/approve-and-save', {})
    assert r.status_code == 200, r.text
    return r.json()


def _client(admin, name='Fictional Client Studio', gstin='29ABCDE1234F1Z5'):
    r = write(admin, 'post', '/api/chat', {'message': f'Add client {name}'})
    if r.status_code == 200 and r.json().get('ticket_id'):
        _approve_ticket(admin, r.json()['ticket_id'])
    from studioos.db import Party
    with SessionLocal() as db:
        p = db.scalar(select(Party).where(Party.kind == 'client', Party.name == name))
        if p is None:
            p = Party(kind='client', name=name, gstin=gstin)
            db.add(p)
            db.commit()
            db.refresh(p)
        elif gstin and not p.gstin:
            p.gstin = gstin
            db.commit()
        return p.id


def _acc_by_code(entity_id: int, code: str) -> GLAccount:
    with SessionLocal() as db:
        acc = db.scalar(select(GLAccount).where(GLAccount.entity_id == entity_id, GLAccount.code == code))
        assert acc is not None, f'Missing account {code}'
        return acc


def test_schema_v64_columns_and_tables_present(admin):
    insp = inspect(engine)
    assert 'finance_direct_bill_allocations' in insp.get_table_names()
    assert 'entry_date' in {c['name'] for c in insp.get_columns('gl_journals')}
    assert 'party_id' in {c['name'] for c in insp.get_columns('gl_lines')}
    assert {'account_type', 'description', 'is_active'} <= {c['name'] for c in insp.get_columns('gl_account_profiles')}
    assert {'taxable_paise', 'cgst_paise', 'sgst_paise', 'igst_paise', 'tds_section', 'tds_paise', 'po_id'} <= {
        c['name'] for c in insp.get_columns('finance_direct_bills')
    }
    assert 'bill_id' in {c['name'] for c in insp.get_columns('finance_vendor_credits')}
    assert LATEST_VERSION >= 64


def test_zoho_coa_subaccounts_banks_credit_card_and_reparent(admin):
    entity, pid, vid = _setup_with_chart(admin)
    travel = _acc_by_code(entity, 'TRAVEL')

    # 1. Open a sub-account directly under a regular posting account (Travel -> Flights)
    r = write(admin, 'post', '/api/books/accounts', {
        'entity_id': entity, 'name': 'Flights', 'account_type': 'expense',
        'parent_id': travel.id, 'description': 'Domestic flights for site visits',
    })
    assert r.status_code == 200, r.text
    _approve_ticket(admin, r.json()['ticket_id'])

    # 2. Open a second bank account via Zoho CoA endpoint
    rb = write(admin, 'post', '/api/books/accounts', {
        'entity_id': entity, 'name': 'HDFC Current Fictional', 'account_type': 'bank',
        'masked_identifier': 'XXXX9876', 'code': 'HDFC_CUR',
    })
    assert rb.status_code == 200, rb.text
    _approve_ticket(admin, rb.json()['ticket_id'])
    with SessionLocal() as db:
        bank = db.scalar(select(RegisteredBank).where(RegisteredBank.entity_id == entity, RegisteredBank.display_name == 'HDFC Current Fictional'))
        assert bank is not None and bank.masked_identifier == 'XXXX9876'

    # 3. Open a Credit Card account and verify it appears as a paying account
    rc = write(admin, 'post', '/api/books/accounts', {
        'entity_id': entity, 'name': 'Amex Corporate Fictional', 'account_type': 'credit_card',
        'code': 'AMEX_CC',
    })
    assert rc.status_code == 200, rc.text
    _approve_ticket(admin, rc.json()['ticket_id'])

    # 4. Verify chart report exposes Zoho account_types, sub-account parent_id, and COGS inference
    chart = admin.get(f'/api/finance-ledger/chart/{entity}').json()
    by_name = {a['name']: a for a in chart['accounts']}
    assert by_name['Flights']['parent'] == travel.id
    assert by_name['Flights']['account_type'] == 'expense'
    assert by_name['Cement']['account_type'] == 'cost_of_goods_sold'
    assert by_name['Amex Corporate Fictional']['account_type'] == 'credit_card'
    assert by_name['HDFC Current Fictional']['account_type'] == 'bank'

    # 5. Cycle prevention: cannot move Travel under its own sub-account Flights
    bad = write(admin, 'post', '/api/books/accounts/update', {
        'entity_id': entity, 'account_id': travel.id, 'parent_id': by_name['Flights']['id'],
    })
    assert bad.status_code == 422
    assert 'sub-account' in bad.text.lower()

    # 6. Archive Flights cleanly
    arch = write(admin, 'post', '/api/books/accounts/update', {
        'entity_id': entity, 'account_id': by_name['Flights']['id'], 'is_active': False, 'why': 'No longer used',
    })
    assert arch.status_code == 200, arch.text
    _approve_ticket(admin, arch.json()['ticket_id'])
    chart2 = admin.get(f'/api/finance-ledger/chart/{entity}').json()
    flights2 = next(a for a in chart2['accounts'] if a['name'] == 'Flights')
    assert flights2['active'] is False and flights2['postable'] is False


def test_direct_bill_gst_tds_partial_po_and_credit_allocation(admin):
    entity, pid, vid = _setup_with_chart(admin)
    cement = _acc_by_code(entity, 'CEMENT')
    office_eq = _acc_by_code(entity, 'OFFICE_EQUIPMENT')
    ap = _acc_by_code(entity, '2100')
    amex = write(admin, 'post', '/api/books/accounts', {
        'entity_id': entity, 'name': 'Visa Biz Fictional', 'account_type': 'credit_card', 'code': 'VISA_CC',
    })
    _approve_ticket(admin, amex.json()['ticket_id'])
    cc_acc = _acc_by_code(entity, 'VISA_CC')

    # 1. Create an approved PO for ₹1,00,000
    from studioos.db import FinancePurchaseOrder
    save(admin, propose(admin, 'finance_po', {
        'entity_id': entity, 'supplier_id': vid, 'project_id': pid,
        'po_number': 'PO-PART-001', 'amount_paise': 10_000_000,
    }))
    with SessionLocal() as db:
        po_id = db.scalar(select(FinancePurchaseOrder.id).where(FinancePurchaseOrder.po_number == 'PO-PART-001'))
        assert po_id is not None

    # 2. Post Partial Bill #1 against PO: ₹40,000 taxable + 18% GST (₹7,200) - 1% TDS 194C (₹400) = ₹46,800 payable
    b1 = write(admin, 'post', '/api/books/bills', {
        'entity_id': entity, 'supplier_id': vid, 'invoice_number': 'SUP-GST-001',
        'bill_date': '2026-04-10', 'due_date': '2026-05-10', 'payment_terms_days': 30,
        'supply_type': 'intra', 'tds_section': '194C', 'tds_paise': 40_000, 'po_id': po_id,
        'amount_paise': 4_680_000,
        'lines': [
            {'account_id': cement.id, 'project_id': pid, 'description': 'Cement batch 1',
             'quantity': 100, 'unit_rate_paise': 40_000, 'amount_paise': 4_000_000, 'tax_rate_bps': 1800},
        ],
    })
    assert b1.status_code == 200, b1.text
    b1_done = _approve_ticket(admin, b1.json()['ticket_id'])
    bill1_id = b1_done['committed_records'][0]['id']

    with SessionLocal() as db:
        bill1 = db.get(FinanceDirectBill, bill1_id)
        assert bill1.cgst_paise == 360_000 and bill1.sgst_paise == 360_000 and bill1.tds_paise == 40_000
        j = db.get(GLJournal, bill1.journal_id)
        assert j.entry_date == '2026-04-10'
        assert direct_bill_outstanding(db, bill1_id) == 4_680_000

    # 3. Post Partial Bill #2 against same PO for Fixed Asset + Cement (₹60,000) -> hits exact PO cap
    b2 = write(admin, 'post', '/api/books/bills', {
        'entity_id': entity, 'supplier_id': vid, 'invoice_number': 'SUP-GST-002',
        'bill_date': '2026-04-15', 'due_date': '2026-05-15', 'payment_terms_days': 30,
        'po_id': po_id, 'amount_paise': 6_000_000,
        'lines': [
            {'account_id': office_eq.id, 'project_id': pid, 'description': 'Laser measure', 'amount_paise': 2_000_000},
            {'account_id': cement.id, 'project_id': pid, 'description': 'Cement batch 2', 'amount_paise': 4_000_000},
        ],
    })
    assert b2.status_code == 200, b2.text
    _approve_ticket(admin, b2.json()['ticket_id'])

    # 4. Partial Bill #3 exceeding PO cap must be rejected
    b3 = write(admin, 'post', '/api/books/bills', {
        'entity_id': entity, 'supplier_id': vid, 'invoice_number': 'SUP-GST-003',
        'bill_date': '2026-04-20', 'due_date': '2026-05-20', 'payment_terms_days': 30,
        'po_id': po_id, 'amount_paise': 100_000,
        'lines': [{'account_id': cement.id, 'project_id': pid, 'description': 'Over PO', 'amount_paise': 100_000}],
    })
    assert b3.status_code == 422 and 'po value' in b3.text.lower()

    # 5. Vendor credit linked to bill1 reduces direct_bill_outstanding
    save(admin, propose(admin, 'finance_vendor_credit', {
        'entity_id': entity, 'supplier_id': vid, 'bill_id': bill1_id, 'project_id': pid,
        'note_number': 'DN-001', 'note_date': '2026-04-12',
        'ap_account_id': ap.id, 'expense_account_id': cement.id,
        'taxable_paise': 680_000, 'tax_paise': 0, 'reason': 'Damaged bags returned',
    }))
    with SessionLocal() as db:
        assert direct_bill_outstanding(db, bill1_id) == 4_000_000

    # 6. Pay remaining balance of bill1 using Credit Card!
    save(admin, propose(admin, 'finance_direct_bill_payment', {
        'bill_id': bill1_id, 'paid_through_id': cc_acc.id, 'amount_paise': 4_000_000,
        'payment_reference': 'CC-TXN-001', 'payment_date': '2026-04-25', 'idempotency_key': 'cc-pay-1',
    }))
    with SessionLocal() as db:
        assert direct_bill_outstanding(db, bill1_id) == 0

    # 7. Check TDS Register, GSTR-3B, Balance Sheet, P&L (COGS), Trial Balance, Project Profitability & CSV export
    tds = admin.get(f'/api/books/reports/tds-register?entity_id={entity}').json()
    assert tds['total_tds_paise'] == 40_000 and tds['by_section_paise']['194C'] == 40_000

    g3b = admin.get(f'/api/books/reports/gstr3b?entity_id={entity}').json()
    assert g3b['eligible_itc']['cgst_paise'] == 360_000
    assert g3b['eligible_itc']['sgst_paise'] == 360_000
    assert g3b['itc_carry_forward_paise'] == 720_000

    bs = admin.get(f'/api/books/reports/balance-sheet?entity_id={entity}').json()
    assert bs['balanced'] is True and bs['difference_paise'] == 0
    assert any(g['account_type'] == 'credit_card' for g in bs['liabilities_grouped'])
    assert any(g['account_type'] == 'input_tax' for g in bs['assets_grouped'])

    pnl = admin.get(f'/api/books/reports/pnl?entity_id={entity}').json()
    assert pnl['total_cogs_paise'] == 7_320_000  # 40k + 40k - 6.8k vendor credit = 73.2k
    assert pnl['gross_profit_paise'] == -7_320_000

    tb = admin.get(f'/api/books/reports/trial-balance?entity_id={entity}&date_from=2026-04-12&date_to=2026-04-30').json()
    assert tb['balanced'] is True
    assert tb['totals']['opening_debit_paise'] == tb['totals']['opening_credit_paise'] > 0

    proj = admin.get(f'/api/books/reports/project-profitability?entity_id={entity}').json()
    assert any(r['project_id'] == pid and r['cogs_paise'] == 7_320_000 for r in proj['rows'])

    csv_resp = admin.get(f'/api/books/reports/export.csv?entity_id={entity}&kind=trial-balance')
    assert csv_resp.status_code == 200 and 'Opening Dr' in csv_resp.text


def test_sales_credit_note_ar_ageing_gstr1_and_indian_bank_csv_brs(admin):
    entity, pid, _ = _setup_with_chart(admin)
    cid = _client(admin)
    ar = _acc_by_code(entity, 'TDS_RECEIVABLE')  # asset account for AR posting
    rev = _acc_by_code(entity, 'TURNKEY_REVENUE')
    cgst = _acc_by_code(entity, 'OUTPUT_CGST')
    sgst = _acc_by_code(entity, 'OUTPUT_SGST')
    rnd = _acc_by_code(entity, 'MISC_EXPENSES')

    save(admin, propose(admin, 'sales_invoice', {
        'entity_id': entity, 'client_id': cid, 'project_id': pid,
        'invoice_number': 'INV-ZOHO-001', 'invoice_date': '2026-03-01', 'due_date': '2026-03-15',
        'place_of_supply': 'Karnataka (29)', 'supply_type': 'intra',
        'ar_account_id': ar.id, 'cgst_account_id': cgst.id, 'sgst_account_id': sgst.id,
        'rounding_account_id': rnd.id,
        'lines': [{'income_account_id': rev.id, 'description': 'Turnkey milestone 1', 'quantity': 1, 'rate_paise': 10_000_000, 'tax_rate_bps': 1800}],
    }))
    with SessionLocal() as db:
        inv_id = db.scalar(select(SalesInvoice.id).where(SalesInvoice.invoice_number == 'INV-ZOHO-001'))
        assert inv_id is not None

    # Post Sales Credit Note linked to invoice -> reduces invoice_outstanding
    save(admin, propose(admin, 'sales_credit_note', {
        'entity_id': entity, 'client_id': cid, 'invoice_id': inv_id, 'project_id': pid,
        'note_number': 'CN-001', 'note_date': '2026-03-20',
        'ar_account_id': ar.id, 'income_account_id': rev.id, 'tax_account_id': cgst.id,
        'taxable_paise': 1_000_000, 'tax_paise': 180_000, 'reason': 'Scope reduction',
    }))
    with SessionLocal() as db:
        assert invoice_outstanding(db, inv_id) == 11_800_000 - 1_180_000

    ar_rep = admin.get(f'/api/books/reports/ar-ageing?entity_id={entity}&as_of=2026-05-01').json()
    assert ar_rep['total_receivable_paise'] == 10_620_000
    assert ar_rep['ageing']['days_31_60'] == 10_620_000

    g1 = admin.get(f'/api/books/reports/gstr1?entity_id={entity}').json()
    assert len(g1['b2b']) == 1 and len(g1['credit_notes']) == 1
    assert g1['totals']['cgst_paise'] == 900_000

    # Flexible Indian bank CSV parser (preface lines + DD/MM/YYYY + DD-MMM-YYYY)
    csv_sample = (
        'HDFC Bank Statement\n'
        'Account: XXXX1234\n'
        'Txn Date,Particulars,Withdrawal,Deposit\n'
        '15/04/2026,NEFT-VENDOR-1,25000.00,\n'
        '18-Apr-2026,IMPS-CLIENT-1,,50000.50\n'
    )
    parsed = parse_bank_csv(csv_sample)
    assert parsed[0]['booking_date'] == '2026-04-15' and parsed[0]['signed_amount_paise'] == -2_500_000
    assert parsed[1]['booking_date'] == '2026-04-18' and parsed[1]['signed_amount_paise'] == 5_000_050

    # BRS endpoint
    with SessionLocal() as db:
        bank_id = db.scalar(select(RegisteredBank.id).where(RegisteredBank.entity_id == entity))
    brs = admin.get(f'/api/books/banks/{bank_id}/brs').json()
    assert brs['reconciled'] is True and brs['difference_paise'] == 0


def test_zoho_vendor_client_mandatory_fields_pdfs_and_project_accounting(admin):
    entity, pid, vid = _setup_with_chart(admin)
    cement = _acc_by_code(entity, 'CEMENT')

    # 1. Registered vendor without GSTIN must be refused (mandatory field check)
    bad_v = write(admin, 'post', '/api/books/vendors', {
        'name': 'Fictional Stone Co', 'gst_treatment': 'registered_regular', 'gstin': '',
    })
    assert bad_v.status_code == 422 and 'gstin' in bad_v.text.lower()

    # 2. Invalid PAN refused
    bad_pan = write(admin, 'post', '/api/books/vendors', {
        'name': 'Fictional Stone Co', 'gst_treatment': 'unregistered', 'pan': 'BADPAN',
    })
    assert bad_pan.status_code == 422 and 'pan' in bad_pan.text.lower()

    # 3. Full Zoho vendor creation succeeds via approval ticket
    good_v = write(admin, 'post', '/api/books/vendors', {
        'name': 'Fictional Stone Co', 'gst_treatment': 'registered_regular',
        'gstin': '29ABCDE1234F1Z5', 'pan': 'ABCDE1234F', 'phone': '9876543210',
        'email': 'billing@fictionalstone.example', 'payment_terms_days': 45,
        'default_tds_section': '194C', 'billing_address': '42 Fictional Road, Bengaluru',
        'bank_ifsc': 'HDFC0001234', 'bank_masked_number': 'XXXX4321', 'trade': 'Stone',
    })
    assert good_v.status_code == 200, good_v.text
    _approve_ticket(admin, good_v.json()['ticket_id'])

    # 4. Full Zoho client creation succeeds via approval ticket
    good_c = write(admin, 'post', '/api/books/clients', {
        'name': 'Fictional Villa Client', 'gst_treatment': 'consumer',
        'phone': '9876501234', 'email': 'owner@fictionalvilla.example',
        'billing_address': '10 Palm Grove, Bengaluru', 'payment_terms_days': 15,
    })
    assert good_c.status_code == 200, good_c.text
    _approve_ticket(admin, good_c.json()['ticket_id'])

    # 5. Create PO, Direct Bill with GST/TDS, and Payment -> download all 3 PDFs!
    from studioos.db import FinanceDirectBillPayment, FinancePurchaseOrder
    save(admin, propose(admin, 'finance_po', {
        'entity_id': entity, 'supplier_id': vid, 'project_id': pid,
        'po_number': 'PO-PDF-001', 'amount_paise': 5_000_000,
        'lines': [{'item': 'Italian Marble', 'qty': 10, 'unit_rate_paise': 500_000}],
    }))
    with SessionLocal() as db:
        po_id = db.scalar(select(FinancePurchaseOrder.id).where(FinancePurchaseOrder.po_number == 'PO-PDF-001'))
    po_pdf = admin.get(f'/api/books/purchase-orders/{po_id}/pdf')
    assert po_pdf.status_code == 200 and po_pdf.content.startswith(b'%PDF')

    b = write(admin, 'post', '/api/books/bills', {
        'entity_id': entity, 'supplier_id': vid, 'po_id': po_id, 'invoice_number': 'BILL-PDF-001',
        'bill_date': '2026-04-10', 'due_date': '2026-05-10', 'payment_terms_days': 30,
        'supply_type': 'intra', 'tds_section': '194C', 'tds_paise': 20_000, 'amount_paise': 2_340_000,
        'lines': [{'account_id': cement.id, 'project_id': pid, 'description': 'Marble supply', 'amount_paise': 2_000_000, 'tax_rate_bps': 1800}],
    })
    _approve_ticket(admin, b.json()['ticket_id'])
    with SessionLocal() as db:
        bill_id = db.scalar(select(FinanceDirectBill.id).where(FinanceDirectBill.invoice_number == 'BILL-PDF-001'))
    bill_pdf = admin.get(f'/api/books/bills/{bill_id}/pdf')
    assert bill_pdf.status_code == 200 and bill_pdf.content.startswith(b'%PDF')

    bank_acc = _acc_by_code(entity, '1000')
    save(admin, propose(admin, 'finance_direct_bill_payment', {
        'bill_id': bill_id, 'paid_through_id': bank_acc.id, 'amount_paise': 1_000_000,
        'payment_reference': 'UTR-PDF-001', 'payment_date': '2026-04-15', 'idempotency_key': 'pay-pdf-1',
    }))
    with SessionLocal() as db:
        pay_id = db.scalar(select(FinanceDirectBillPayment.id).where(FinanceDirectBillPayment.payment_reference == 'UTR-PDF-001'))
    pay_pdf = admin.get(f'/api/books/payments/{pay_id}/pdf?kind=direct')
    assert pay_pdf.status_code == 200 and pay_pdf.content.startswith(b'%PDF')

    # 6. Project accounting summary reflects PO commitment, billed, remaining, and direct bill
    pa = admin.get(f'/api/books/projects/{pid}/accounting')
    assert pa.status_code == 200, pa.text
    pad = pa.json()
    assert pad['po_committed_paise'] == 5_000_000
    assert pad['po_billed_paise'] == 2_000_000
    assert pad['po_remaining_paise'] == 3_000_000
    assert pad['bills_total_paise'] == 2_340_000
    assert pad['bills_owed_paise'] == 1_340_000


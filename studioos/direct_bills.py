"""M2-1: Approved multi-line supplier bills entered directly without a purchase order.
Every bill carries a vendor, invoice number, bill date, due date, payment terms, and one or more
expense lines whose amounts sum to the bill total. Nothing posts until approved on a ticket.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .access import can_access_project
from .db import (
    AccountingEntity, ApprovalTicket, Document, FinanceDirectBill, FinanceDirectBillAllocation,
    FinanceDirectBillLine, FinanceDirectBillPayment, FinancePurchaseOrder, FinanceReversal,
    FinanceSupplierAdvance, FinanceSupplierBill, FinanceSupplierCashAdvance, FinanceVendorCredit,
    GLAccount, Party, Project, User, add_audit,
)
from .security import FINANCE_WRITE

DIRECT_BILL_TYPES = {
    'finance_direct_bill', 'finance_reverse_direct_bill',
    'finance_direct_bill_payment', 'finance_reverse_direct_bill_payment',
    'finance_allocate_direct_bill',
}
DIRECT_BILL_FIELDS = {
    'finance_direct_bill': {
        'entity_id', 'supplier_id', 'invoice_number', 'bill_date', 'due_date',
        'payment_terms_days', 'amount_paise', 'lines', 'note', 'attachment_id', 'request_key',
        'supply_type', 'tds_section', 'tds_paise', 'tds_account_id',
        'cgst_account_id', 'sgst_account_id', 'igst_account_id', 'po_id',
    },
    'finance_reverse_direct_bill': {'bill_id', 'reason'},
    'finance_direct_bill_payment': {
        'bill_id', 'paid_through_id', 'amount_paise', 'payment_reference', 'payment_date', 'idempotency_key',
    },
    'finance_reverse_direct_bill_payment': {'payment_id', 'reason'},
    'finance_allocate_direct_bill': {
        'bill_id', 'source_kind', 'source_id', 'amount_paise', 'allocation_date', 'idempotency_key',
    },
}
DIRECT_BILL_EVENT = 'DIRECT_BILL_POSTED'
DIRECT_BILL_PAYMENT_EVENT = 'DIRECT_BILL_PAYMENT_POSTED'
DIRECT_BILL_ALLOCATION_EVENT = 'DIRECT_BILL_ADVANCE_ALLOCATED'
MAX_BILL_LINES = 50
ALLOWED_BILL_LINE_KINDS = frozenset({'expense', 'asset', 'inventory'})


def _unreversed(journal_col):
    return ~select(FinanceReversal.id).where(FinanceReversal.original_journal_id == journal_col).exists()


def direct_bill_outstanding(db: Session, bill_id: int) -> int:
    """Remaining unpaid balance in paise for a direct supplier bill (0 if reversed)."""
    bill = db.get(FinanceDirectBill, bill_id)
    if bill is None or not bill.journal_id:
        return 0
    rev_exists = select(FinanceReversal.id).where(FinanceReversal.original_journal_id == bill.journal_id).exists()
    if db.scalar(select(rev_exists)):
        return 0
    paid = db.scalar(
        select(func.coalesce(func.sum(FinanceDirectBillPayment.amount_paise), 0)).where(
            FinanceDirectBillPayment.bill_id == bill.id,
            _unreversed(FinanceDirectBillPayment.journal_id),
        )
    ) or 0
    vc_direct = db.scalar(
        select(func.coalesce(func.sum(FinanceVendorCredit.total_paise), 0)).where(
            FinanceVendorCredit.bill_id == bill.id,
            FinanceVendorCredit.journal_id.is_not(None),
            _unreversed(FinanceVendorCredit.journal_id),
        )
    ) or 0
    allocs = db.scalar(
        select(func.coalesce(func.sum(FinanceDirectBillAllocation.amount_paise), 0)).where(
            FinanceDirectBillAllocation.bill_id == bill.id,
            (FinanceDirectBillAllocation.journal_id.is_(None)) | _unreversed(FinanceDirectBillAllocation.journal_id),
        )
    ) or 0
    return max(0, bill.amount_paise - int(paid) - int(vc_direct) - int(allocs))


def vendor_credit_remaining(db: Session, vc_id: int) -> int:
    """Unallocated remaining amount on a posted vendor credit."""
    vc = db.get(FinanceVendorCredit, vc_id)
    if vc is None or not vc.journal_id:
        return 0
    if db.scalar(select(FinanceReversal.id).where(FinanceReversal.original_journal_id == vc.journal_id)):
        return 0
    if vc.bill_id is not None:
        return 0  # Already directly linked to a bill
    used = db.scalar(
        select(func.coalesce(func.sum(FinanceDirectBillAllocation.amount_paise), 0)).where(
            FinanceDirectBillAllocation.source_kind == 'vendor_credit',
            FinanceDirectBillAllocation.source_id == vc.id,
        )
    ) or 0
    return max(0, vc.total_paise - int(used))


def po_billed_paise(db: Session, po_id: int) -> int:
    """Total taxable value already billed against a PO (across PO bills and partial direct bills)."""
    po_bills = db.scalar(
        select(func.coalesce(func.sum(FinanceSupplierBill.amount_paise), 0)).where(
            FinanceSupplierBill.po_id == po_id,
            FinanceSupplierBill.journal_id.is_not(None),
            _unreversed(FinanceSupplierBill.journal_id),
        )
    ) or 0
    partial_bills = db.scalar(
        select(func.coalesce(func.sum(func.coalesce(FinanceDirectBill.taxable_paise, FinanceDirectBill.amount_paise)), 0)).where(
            FinanceDirectBill.po_id == po_id,
            FinanceDirectBill.journal_id.is_not(None),
            _unreversed(FinanceDirectBill.journal_id),
        )
    ) or 0
    return int(po_bills) + int(partial_bills)


def submitter(db: Session, item):
    ticket = db.get(ApprovalTicket, item.ticket_id)
    actor = db.get(User, ticket.submitter_id) if ticket and ticket.submitter_id else None
    if actor is None or not actor.active or actor.role not in FINANCE_WRITE:
        raise ValueError('An active member of the money team must submit this bill.')
    return actor


def display_values(db: Session, data: dict) -> dict:
    out = {}
    for field, model in (('entity_id', AccountingEntity), ('supplier_id', Party), ('attachment_id', Document)):
        ident = data.get(field)
        row = db.get(model, ident) if type(ident) is int else None
        if row is not None:
            out[field] = row.name
    return out


def _clean_lines(db: Session, entity_id: int, lines, actor):
    from .accounting_kernel import positive_minor
    if not isinstance(lines, list) or not (1 <= len(lines) <= MAX_BILL_LINES):
        raise ValueError(f'Add between 1 and {MAX_BILL_LINES} bill lines.')
    cleaned = []
    for idx, raw in enumerate(lines, 1):
        if not isinstance(raw, dict):
            raise ValueError(f'Bill line {idx} is not valid.')
        unknown = set(raw) - {'account_id', 'project_id', 'description', 'amount_paise', 'tax_rate_bps', 'quantity', 'unit_rate_paise'}
        if unknown:
            raise ValueError(f'Bill line {idx} has unexpected fields.')
        acc_id = raw.get('account_id')
        acc = db.get(GLAccount, acc_id) if type(acc_id) is int else None
        if acc is None or acc.entity_id != entity_id or acc.kind not in ALLOWED_BILL_LINE_KINDS or not acc.active or not acc.posting_allowed:
            raise ValueError(f'Bill line {idx}: choose an active expense, COGS, asset, or inventory account for this company.')
        qty = raw.get('quantity')
        unit_rate = raw.get('unit_rate_paise')
        if (qty is None) != (unit_rate is None):
            raise ValueError(f'Bill line {idx}: provide both quantity and unit rate, or neither.')
        if qty is not None:
            if type(qty) is not int or qty <= 0 or type(unit_rate) is not int or unit_rate <= 0:
                raise ValueError(f'Bill line {idx}: quantity and unit rate must be positive whole numbers.')
        amount = raw.get('amount_paise')
        positive_minor(amount)
        if qty is not None and qty * unit_rate != amount:
            raise ValueError(f'Bill line {idx}: amount must equal quantity times unit rate.')
        bps = raw.get('tax_rate_bps', 0)
        if type(bps) is not int or not (0 <= bps <= 2800):
            raise ValueError(f'Bill line {idx}: GST rate must be between 0% and 28%.')
        tax_paise = (amount * bps + 5000) // 10000 if bps else 0
        pid = raw.get('project_id')
        if pid is not None:
            proj = db.get(Project, pid) if type(pid) is int else None
            if proj is None or proj.deleted_at:
                raise ValueError(f'Bill line {idx}: project not found.')
            if actor is not None and not can_access_project(db, actor, proj.id):
                raise ValueError(f'Bill line {idx}: you do not have access to that project.')
            from .project_links import require_project_company
            require_project_company(db, proj, entity_id)
        desc = raw.get('description') or ''
        if not isinstance(desc, str) or len(desc.strip()) > 250:
            raise ValueError(f'Bill line {idx}: description must be 250 characters or fewer.')
        cleaned.append({'account': acc, 'account_id': acc.id, 'project_id': pid,
                        'description': desc.strip(), 'amount_paise': amount,
                        'tax_rate_bps': bps, 'tax_paise': tax_paise,
                        'quantity': qty, 'unit_rate_paise': unit_rate})
    return cleaned


def _resolve_bill_account(db: Session, entity_id: int, explicit_id, *, code: str, kind: str, label: str) -> GLAccount:
    if explicit_id is not None:
        acc = db.get(GLAccount, explicit_id) if type(explicit_id) is int else None
    else:
        acc = db.scalar(select(GLAccount).where(
            GLAccount.entity_id == entity_id, GLAccount.code == code,
            GLAccount.active.is_(True), GLAccount.posting_allowed.is_(True),
        ))
    if acc is None or acc.entity_id != entity_id or not acc.active or not acc.posting_allowed:
        raise ValueError(f'Choose or install an active {label} account ({code}) for this company.')
    return acc


def validate(db: Session, kind: str, data: dict, actor=None):
    from .accounting_kernel import (
        _calendar_date, _check_bill_dates, _check_dated_posting, _is_reversed, _policy,
        _supplier_payment_source, positive_minor, require_three_links, required_text,
    )
    if not isinstance(data, dict) or set(data) - DIRECT_BILL_FIELDS[kind]:
        raise ValueError('Unrecognized bill details.')
    if kind == 'finance_reverse_direct_bill':
        from .bill_payment_drafts import check_bill_reversal

        if set(data) != {'bill_id', 'reason'}:
            raise ValueError('Choose a posted bill and give a reason to reverse it.')
        bill_id = data.get('bill_id')
        bill = db.get(FinanceDirectBill, bill_id) if type(bill_id) is int else None
        if bill is None or not bill.journal_id or _is_reversed(db, bill.journal_id):
            raise ValueError('Posted supplier bill required.')
        check_bill_reversal(db, 'finance_direct_bill_payment', bill.id)
        if direct_bill_outstanding(db, bill.id) < bill.amount_paise:
            raise ValueError('Reverse every payment before reversing the bill.')
        required_text(data.get('reason'), 'Reversal reason', 400)
        return bill
    if kind == 'finance_reverse_direct_bill_payment':
        if set(data) != {'payment_id', 'reason'}:
            raise ValueError('Choose a posted payment and give a reason to reverse it.')
        pid = data.get('payment_id')
        pay = db.get(FinanceDirectBillPayment, pid) if type(pid) is int else None
        if pay is None or not pay.journal_id or _is_reversed(db, pay.journal_id):
            raise ValueError('Posted bill payment required.')
        required_text(data.get('reason'), 'Reversal reason', 400)
        return pay
    if kind == 'finance_direct_bill_payment':
        required = {'bill_id', 'paid_through_id', 'amount_paise', 'payment_reference', 'payment_date', 'idempotency_key'}
        if not required <= set(data):
            raise ValueError('Choose a bill, paying account, amount, payment date and reference.')
        bill_id = data.get('bill_id')
        bill = db.get(FinanceDirectBill, bill_id) if type(bill_id) is int else None
        if bill is None or not bill.journal_id or _is_reversed(db, bill.journal_id):
            raise ValueError('Posted supplier bill required.')
        owed = direct_bill_outstanding(db, bill.id)
        amount = data.get('amount_paise')
        positive_minor(amount)
        if amount > owed:
            raise ValueError(f'This is more than what is still owed (₹{owed / 100:,.2f}).')
        pdate = _calendar_date(data.get('payment_date'), 'Payment date')
        source, bank = _supplier_payment_source(db, bill.entity_id, {'paid_through_id': data.get('paid_through_id')}, actor)
        _check_dated_posting(db, bill.entity_id, 'bank' if bank else 'purchases', pdate, 'Payment date')
        ref = required_text(data.get('payment_reference'), 'Payment reference', 120)
        ikey = required_text(data.get('idempotency_key'), 'Idempotency key', 120)
        if db.scalar(select(FinanceDirectBillPayment.id).where(FinanceDirectBillPayment.idempotency_key == ikey)):
            raise ValueError('This payment was already posted.')
        _, policy, _, payable = _policy(db, bill.entity_id)
        supplier = db.get(Party, bill.supplier_id)
        require_three_links('finance_direct_bill_payment', entity_id=bill.entity_id, party=supplier,
                            source=source, account=payable)
        return bill, policy, payable, supplier, source, bank, pdate, ref, ikey

    if kind == 'finance_allocate_direct_bill':
        from .accounting_kernel import _advance_policy, advance_remaining
        required = {'bill_id', 'source_kind', 'source_id', 'amount_paise', 'allocation_date', 'idempotency_key'}
        if not required <= set(data):
            raise ValueError('Choose a bill, advance or vendor credit, amount, date and reference.')
        bill = db.get(FinanceDirectBill, data.get('bill_id')) if type(data.get('bill_id')) is int else None
        if bill is None or not bill.journal_id or _is_reversed(db, bill.journal_id):
            raise ValueError('Posted supplier bill required.')
        skind = str(data.get('source_kind') or '').strip().lower()
        if skind not in ('advance', 'cash_advance', 'vendor_credit'):
            raise ValueError('Source must be advance, cash_advance, or vendor_credit.')
        sid = data.get('source_id')
        if type(sid) is not int:
            raise ValueError('Choose a valid advance or vendor credit.')
        amount = data.get('amount_paise')
        positive_minor(amount)
        owed = direct_bill_outstanding(db, bill.id)
        if amount > owed:
            raise ValueError(f'Allocation exceeds bill balance owed (₹{owed / 100:,.2f}).')
        adate = _calendar_date(data.get('allocation_date'), 'Allocation date')
        _check_dated_posting(db, bill.entity_id, 'purchases', adate, 'Allocation date')
        ikey = required_text(data.get('idempotency_key'), 'Idempotency key', 120)
        if db.scalar(select(FinanceDirectBillAllocation.id).where(FinanceDirectBillAllocation.idempotency_key == ikey)):
            raise ValueError('This allocation was already posted.')
        _, policy, _, payable = _policy(db, bill.entity_id)
        adv_acc = None
        if skind == 'vendor_credit':
            vc = db.get(FinanceVendorCredit, sid)
            if vc is None or not vc.journal_id or vc.entity_id != bill.entity_id or vc.supplier_id != bill.supplier_id:
                raise ValueError('Choose a posted vendor credit for the same company and vendor.')
            rem = vendor_credit_remaining(db, vc.id)
            if amount > rem:
                raise ValueError(f'Allocation exceeds remaining vendor credit (₹{rem / 100:,.2f}).')
        else:
            is_cash = skind == 'cash_advance'
            model = FinanceSupplierCashAdvance if is_cash else FinanceSupplierAdvance
            adv = db.get(model, sid)
            if adv is None or not adv.journal_id or adv.entity_id != bill.entity_id or adv.supplier_id != bill.supplier_id:
                raise ValueError('Choose a posted supplier advance for the same company and vendor.')
            rem = advance_remaining(db, adv.id, cash=is_cash)
            if rem is None or amount > rem:
                raise ValueError(f'Allocation exceeds remaining supplier advance (₹{(rem or 0) / 100:,.2f}).')
            _, adv_acc = _advance_policy(db, bill.entity_id)
        return bill, policy, payable, adv_acc, skind, sid, adate.isoformat(), ikey

    required = {'entity_id', 'supplier_id', 'invoice_number', 'bill_date', 'due_date', 'payment_terms_days', 'amount_paise', 'lines'}
    if not required <= set(data):
        raise ValueError('Bill requires company, vendor, invoice number, bill date, due date, payment terms, total and lines.')
    ent_id = data.get('entity_id')
    ent = db.get(AccountingEntity, ent_id) if type(ent_id) is int else None
    if ent is None:
        raise ValueError('Choose an existing company.')
    _, policy, _, payable = _policy(db, ent.id)

    sup_id = data.get('supplier_id')
    supplier = db.get(Party, sup_id) if type(sup_id) is int else None
    if supplier is None or supplier.kind != 'vendor' or supplier.deleted_at:
        raise ValueError('Choose an active vendor for this bill.')

    inv = required_text(data.get('invoice_number'), 'Supplier invoice number', 120)
    _check_bill_dates(db, ent.id, data)
    positive_minor(data.get('amount_paise'))

    # Enforce duplicate invoice number per vendor across BOTH PO bills and direct bills.
    if (db.scalar(select(FinanceDirectBill.id).where(
            FinanceDirectBill.entity_id == ent.id,
            FinanceDirectBill.supplier_id == supplier.id,
            FinanceDirectBill.invoice_number == inv))
        or db.scalar(select(FinanceSupplierBill.id).where(
            FinanceSupplierBill.entity_id == ent.id,
            FinanceSupplierBill.supplier_id == supplier.id,
            FinanceSupplierBill.invoice_number == inv))):
        raise ValueError('Duplicate supplier invoice')

    lines = _clean_lines(db, ent.id, data.get('lines'), actor)
    taxable_total = sum(ln['amount_paise'] for ln in lines)
    tax_total = sum(ln['tax_paise'] for ln in lines)
    supply_type = str(data.get('supply_type') or 'intra').strip().lower()
    if supply_type not in ('intra', 'inter'):
        raise ValueError('Supply type must be intra or inter.')
    if supply_type == 'intra':
        cgst_paise = tax_total // 2
        sgst_paise = tax_total - cgst_paise
        igst_paise = 0
    else:
        cgst_paise = sgst_paise = 0
        igst_paise = tax_total
    tds_paise = data.get('tds_paise') or 0
    if type(tds_paise) is not int or tds_paise < 0 or tds_paise >= taxable_total + tax_total:
        raise ValueError('TDS amount must be a non-negative integer less than the gross bill total.')
    tds_section = str(data.get('tds_section') or '').strip().upper()[:16]
    if tds_paise > 0 and not tds_section:
        tds_section = '194C'
    expected_payable = taxable_total + tax_total - tds_paise
    if expected_payable != data['amount_paise']:
        raise ValueError('Bill lines (plus GST minus TDS) must add up to the total bill amount.')

    tax_accs = {}
    if cgst_paise > 0:
        tax_accs['cgst'] = _resolve_bill_account(db, ent.id, data.get('cgst_account_id'), code='INPUT_CGST', kind='input_tax', label='Input CGST')
    if sgst_paise > 0:
        tax_accs['sgst'] = _resolve_bill_account(db, ent.id, data.get('sgst_account_id'), code='INPUT_SGST', kind='input_tax', label='Input SGST')
    if igst_paise > 0:
        tax_accs['igst'] = _resolve_bill_account(db, ent.id, data.get('igst_account_id'), code='INPUT_IGST', kind='input_tax', label='Input IGST')
    if tds_paise > 0:
        tax_accs['tds'] = _resolve_bill_account(db, ent.id, data.get('tds_account_id'), code='TDS_PAYABLE', kind='liability', label='TDS Payable')

    po_id = data.get('po_id')
    if po_id is not None:
        po = db.get(FinancePurchaseOrder, po_id) if type(po_id) is int else None
        if po is None or po.status != 'approved' or po.entity_id != ent.id or po.supplier_id != supplier.id:
            raise ValueError('Choose an approved purchase order for this company and vendor.')
        already = po_billed_paise(db, po.id)
        if already + taxable_total > po.amount_paise:
            rem = max(0, po.amount_paise - already)
            raise ValueError(f'Bill exceeds remaining unbilled PO value (₹{rem / 100:,.2f}).')

    note = data.get('note') or ''
    if not isinstance(note, str) or len(note) > 500:
        raise ValueError('Note must be 500 characters or fewer.')

    att_id = data.get('attachment_id')
    if att_id is not None:
        doc = db.get(Document, att_id) if type(att_id) is int else None
        if doc is None:
            raise ValueError('Attached file was not found.')

    require_three_links('finance_direct_bill', entity_id=ent.id, party=supplier,
                        source=payable, account=lines[0]['account'])
    tax_meta = {
        'taxable_paise': taxable_total, 'cgst_paise': cgst_paise, 'sgst_paise': sgst_paise,
        'igst_paise': igst_paise, 'tds_section': tds_section, 'tds_paise': tds_paise,
        'supply_type': supply_type, 'tax_accs': tax_accs, 'po_id': po_id,
    }
    return ent, policy, payable, supplier, inv, lines, note.strip(), att_id, tax_meta


def preview(db: Session, kind: str, data: dict, actor=None) -> dict:
    if kind == 'finance_reverse_direct_bill':
        bill = validate(db, kind, data, actor)
        return {'type': kind, 'bill_id': bill.id, 'invoice_number': bill.invoice_number,
                'amount_paise': bill.amount_paise, 'reason': data['reason']}
    if kind == 'finance_reverse_direct_bill_payment':
        pay = validate(db, kind, data, actor)
        return {'type': kind, 'payment_id': pay.id, 'amount_paise': pay.amount_paise, 'reason': data['reason']}
    if kind == 'finance_direct_bill_payment':
        bill, _, payable, supplier, source, _, pdate, ref, _ = validate(db, kind, data, actor)
        return {'type': kind, 'bill_id': bill.id, 'invoice_number': bill.invoice_number,
                'supplier': supplier.name, 'payment_date': pdate, 'reference': ref,
                'amount_paise': data['amount_paise'],
                'lines': [{'side': 'debit', 'account': payable.name, 'amount_paise': data['amount_paise']},
                          {'side': 'credit', 'account': source.name, 'amount_paise': data['amount_paise']}]}
    if kind == 'finance_allocate_direct_bill':
        bill, _, payable, adv_acc, skind, sid, adate, _ = validate(db, kind, data, actor)
        jlines = ([{'side': 'debit', 'account': payable.name, 'amount_paise': data['amount_paise']},
                   {'side': 'credit', 'account': adv_acc.name, 'amount_paise': data['amount_paise']}]
                  if adv_acc is not None else [])
        return {'type': kind, 'bill_id': bill.id, 'invoice_number': bill.invoice_number,
                'source_kind': skind, 'source_id': sid, 'allocation_date': adate,
                'amount_paise': data['amount_paise'], 'lines': jlines}
    ent, _, payable, supplier, inv, lines, _, _, tax_meta = validate(db, kind, data, actor)
    jlines = [{'side': 'debit', 'account': ln['account'].name, 'amount_paise': ln['amount_paise'], 'project_id': ln['project_id']}
              for ln in lines]
    if tax_meta['cgst_paise'] > 0:
        jlines.append({'side': 'debit', 'account': tax_meta['tax_accs']['cgst'].name, 'amount_paise': tax_meta['cgst_paise']})
    if tax_meta['sgst_paise'] > 0:
        jlines.append({'side': 'debit', 'account': tax_meta['tax_accs']['sgst'].name, 'amount_paise': tax_meta['sgst_paise']})
    if tax_meta['igst_paise'] > 0:
        jlines.append({'side': 'debit', 'account': tax_meta['tax_accs']['igst'].name, 'amount_paise': tax_meta['igst_paise']})
    if tax_meta['tds_paise'] > 0:
        jlines.append({'side': 'credit', 'account': tax_meta['tax_accs']['tds'].name, 'amount_paise': tax_meta['tds_paise']})
    jlines.append({'side': 'credit', 'account': payable.name, 'amount_paise': data['amount_paise'], 'supplier': supplier.name})
    return {'type': kind, 'entity_id': ent.id, 'supplier': supplier.name, 'invoice_number': inv,
            'bill_date': data['bill_date'], 'due_date': data['due_date'],
            'amount_paise': data['amount_paise'], 'lines': jlines}


def apply(db: Session, item, actor: str) -> dict:
    from .accounting_kernel import _post_lines, _reverse_posted
    kind, data = item.item_type, item.after_data or {}
    if kind == 'finance_reverse_direct_bill':
        bill_ref = db.get(FinanceDirectBill, data.get('bill_id')) if type(data.get('bill_id')) is int else None
        if bill_ref is None:
            raise ValueError('Posted supplier bill required.')
        db.scalar(select(AccountingEntity).where(AccountingEntity.id == bill_ref.entity_id).with_for_update())
        bill = db.scalar(select(FinanceDirectBill).where(FinanceDirectBill.id == bill_ref.id).with_for_update())
        db.info.pop('_period_locks', None)
        validate(db, kind, data)
        rev = _reverse_posted(db, bill.journal_id, data['reason'], item.ticket_id)
        add_audit(db, 'finance_reverse_direct_bill', 'direct_bill', bill.id,
                  f'Reversed direct bill {bill.invoice_number} (journal #{rev.id})', actor=actor)
        return {'type': 'reversing_journal', 'id': rev.id, 'item_id': item.id}

    if kind == 'finance_reverse_direct_bill_payment':
        pay_ref = db.get(FinanceDirectBillPayment, data.get('payment_id')) if type(data.get('payment_id')) is int else None
        if pay_ref is None:
            raise ValueError('Posted bill payment required.')
        bill_ref = db.get(FinanceDirectBill, pay_ref.bill_id)
        db.scalar(select(AccountingEntity).where(AccountingEntity.id == bill_ref.entity_id).with_for_update())
        pay = db.scalar(select(FinanceDirectBillPayment).where(FinanceDirectBillPayment.id == pay_ref.id).with_for_update())
        db.info.pop('_period_locks', None)
        validate(db, kind, data)
        rev = _reverse_posted(db, pay.journal_id, data['reason'], item.ticket_id)
        add_audit(db, 'finance_reverse_direct_bill_payment', 'direct_bill_payment', pay.id,
                  f'Reversed direct bill payment {pay.payment_reference} (journal #{rev.id})', actor=actor)
        return {'type': 'reversing_journal', 'id': rev.id, 'item_id': item.id}
    if kind == 'finance_direct_bill_payment':
        bill_ref = db.get(FinanceDirectBill, data.get('bill_id')) if type(data.get('bill_id')) is int else None
        if bill_ref is None:
            raise ValueError('Posted supplier bill required.')
        db.scalar(select(AccountingEntity).where(AccountingEntity.id == bill_ref.entity_id).with_for_update())
        bill_locked = db.scalar(select(FinanceDirectBill).where(FinanceDirectBill.id == bill_ref.id).with_for_update())
        db.info.pop('_period_locks', None)
        requester = submitter(db, item)
        bill, policy, payable, supplier, source, bank, pdate, ref, ikey = validate(db, kind, data, requester)
        pay = FinanceDirectBillPayment(
            bill_id=bill_locked.id, paid_through_id=source.id, bank_id=bank.id if bank else None,
            amount_paise=data['amount_paise'], payment_reference=ref, payment_date=pdate,
            idempotency_key=ikey, ticket_id=item.ticket_id,
        )
        db.add(pay)
        db.flush()
        journal = _post_lines(
            db, entity_id=bill.entity_id, event_kind=DIRECT_BILL_PAYMENT_EVENT,
            event_key=f'direct_bill_payment:{pay.id}', source_id=pay.id,
            lines=[
                (payable.id, 'debit', pay.amount_paise, None),
                (source.id, 'credit', pay.amount_paise, None),
            ],
            ticket_id=item.ticket_id, policy_version=policy.policy_version, supplier_id=supplier.id,
            entry_date=pay.payment_date,
        )
        pay.journal_id = journal.id
        add_audit(db, 'finance_direct_bill_payment', 'direct_bill_payment', pay.id,
                  f'Paid ₹{pay.amount_paise / 100:,.2f} against bill {bill.invoice_number} ({ref})', actor=actor)
        db.flush()
        return {'type': 'direct_bill_payment', 'id': pay.id, 'item_id': item.id}

    if kind == 'finance_allocate_direct_bill':
        bill_ref = db.get(FinanceDirectBill, data.get('bill_id')) if type(data.get('bill_id')) is int else None
        if bill_ref is None:
            raise ValueError('Posted supplier bill required.')
        db.scalar(select(AccountingEntity).where(AccountingEntity.id == bill_ref.entity_id).with_for_update())
        db.scalar(select(FinanceDirectBill).where(FinanceDirectBill.id == bill_ref.id).with_for_update())
        db.info.pop('_period_locks', None)
        requester = submitter(db, item)
        bill, policy, payable, adv_acc, skind, sid, adate, ikey = validate(db, kind, data, requester)
        jid = None
        if adv_acc is not None:
            journal = _post_lines(
                db, entity_id=bill.entity_id, event_kind=DIRECT_BILL_ALLOCATION_EVENT,
                event_key=f'direct_bill_alloc:{ikey}', source_id=bill.id,
                lines=[
                    (payable.id, 'debit', data['amount_paise'], None),
                    (adv_acc.id, 'credit', data['amount_paise'], None),
                ],
                ticket_id=item.ticket_id, policy_version=policy.policy_version,
                supplier_id=bill.supplier_id, entry_date=adate,
            )
            jid = journal.id
        alloc = FinanceDirectBillAllocation(
            entity_id=bill.entity_id, bill_id=bill.id, source_kind=skind, source_id=sid,
            amount_paise=data['amount_paise'], allocation_date=adate,
            idempotency_key=ikey, journal_id=jid, ticket_id=item.ticket_id,
        )
        db.add(alloc)
        db.flush()
        add_audit(db, 'finance_allocate_direct_bill', 'direct_bill_allocation', alloc.id,
                  f'Allocated ₹{alloc.amount_paise / 100:,.2f} ({skind} #{sid}) to bill {bill.invoice_number}', actor=actor)
        return {'type': 'direct_bill_allocation', 'id': alloc.id, 'item_id': item.id, 'journal_id': jid}

    ent_id = data.get('entity_id')
    if type(ent_id) is not int or db.get(AccountingEntity, ent_id) is None:
        raise ValueError('Choose an existing company.')
    db.scalar(select(AccountingEntity).where(AccountingEntity.id == ent_id).with_for_update())
    db.info.pop('_period_locks', None)
    requester = submitter(db, item)
    ent, policy, payable, supplier, inv, lines, note, att_id, tax_meta = validate(db, kind, data, requester)
    bill = FinanceDirectBill(
        entity_id=ent.id, supplier_id=supplier.id, invoice_number=inv,
        bill_date=data['bill_date'], due_date=data['due_date'],
        payment_terms_days=data['payment_terms_days'], amount_paise=data['amount_paise'],
        taxable_paise=tax_meta['taxable_paise'], cgst_paise=tax_meta['cgst_paise'],
        sgst_paise=tax_meta['sgst_paise'], igst_paise=tax_meta['igst_paise'],
        tds_section=tax_meta['tds_section'], tds_paise=tax_meta['tds_paise'],
        supply_type=tax_meta['supply_type'], po_id=tax_meta['po_id'],
        note=note, attachment_id=att_id, ticket_id=item.ticket_id,
    )
    db.add(bill)
    db.flush()
    for ln in lines:
        db.add(FinanceDirectBillLine(
            bill_id=bill.id, account_id=ln['account_id'], project_id=ln['project_id'],
            description=ln['description'], amount_paise=ln['amount_paise'],
            tax_rate_bps=ln['tax_rate_bps'], tax_paise=ln['tax_paise'],
            quantity=ln['quantity'], unit_rate_paise=ln['unit_rate_paise'],
        ))
    db.flush()
    # Aggregate debits per account_id so _post_lines one-account-per-side invariant holds.
    debit_map: dict[int, tuple[int, int | None]] = {}
    for ln in lines:
        prev_amt, prev_proj = debit_map.get(ln['account_id'], (0, ln['project_id']))
        debit_map[ln['account_id']] = (prev_amt + ln['amount_paise'], prev_proj if prev_proj == ln['project_id'] else None)
    journal_lines = [(acc_id, 'debit', amt, proj) for acc_id, (amt, proj) in debit_map.items()]
    if tax_meta['cgst_paise'] > 0:
        journal_lines.append((tax_meta['tax_accs']['cgst'].id, 'debit', tax_meta['cgst_paise'], None))
    if tax_meta['sgst_paise'] > 0:
        journal_lines.append((tax_meta['tax_accs']['sgst'].id, 'debit', tax_meta['sgst_paise'], None))
    if tax_meta['igst_paise'] > 0:
        journal_lines.append((tax_meta['tax_accs']['igst'].id, 'debit', tax_meta['igst_paise'], None))
    if tax_meta['tds_paise'] > 0:
        journal_lines.append((tax_meta['tax_accs']['tds'].id, 'credit', tax_meta['tds_paise'], None))
    journal_lines.append((payable.id, 'credit', bill.amount_paise, None))
    journal = _post_lines(
        db, entity_id=ent.id, event_kind=DIRECT_BILL_EVENT, event_key=f'direct_bill:{bill.id}',
        source_id=bill.id, lines=journal_lines, ticket_id=item.ticket_id,
        policy_version=policy.policy_version, supplier_id=supplier.id,
        entry_date=bill.bill_date,
    )
    bill.journal_id = journal.id
    from .project_parties import link_vendor

    for project_id in sorted({line['project_id'] for line in lines if line['project_id'] is not None}):
        link_vendor(db, project_id, supplier.id, item.ticket_id, actor)
    add_audit(db, 'finance_direct_bill', 'direct_bill', bill.id,
              f'Posted supplier bill {bill.invoice_number} for {supplier.name} (₹{bill.amount_paise / 100:,.2f})', actor=actor)
    db.flush()
    return {'type': 'direct_bill', 'id': bill.id, 'item_id': item.id}

"""M2-1: Approved multi-line supplier bills entered directly without a purchase order.
Every bill carries a vendor, invoice number, bill date, due date, payment terms, and one or more
expense lines whose amounts sum to the bill total. Nothing posts until approved on a ticket.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .access import can_access_project
from .db import (
    AccountingEntity, ApprovalTicket, Document, FinanceDirectBill, FinanceDirectBillLine,
    FinanceDirectBillPayment, FinanceReversal, FinanceSupplierBill, GLAccount, Party, Project, User, add_audit,
)
from .security import FINANCE_WRITE

DIRECT_BILL_TYPES = {
    'finance_direct_bill', 'finance_reverse_direct_bill',
    'finance_direct_bill_payment', 'finance_reverse_direct_bill_payment',
}
DIRECT_BILL_FIELDS = {
    'finance_direct_bill': {
        'entity_id', 'supplier_id', 'invoice_number', 'bill_date', 'due_date',
        'payment_terms_days', 'amount_paise', 'lines', 'note', 'attachment_id', 'request_key',
    },
    'finance_reverse_direct_bill': {'bill_id', 'reason'},
    'finance_direct_bill_payment': {
        'bill_id', 'paid_through_id', 'amount_paise', 'payment_reference', 'payment_date', 'idempotency_key',
    },
    'finance_reverse_direct_bill_payment': {'payment_id', 'reason'},
}
DIRECT_BILL_EVENT = 'DIRECT_BILL_POSTED'
DIRECT_BILL_PAYMENT_EVENT = 'DIRECT_BILL_PAYMENT_POSTED'
MAX_BILL_LINES = 50


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
            ~select(FinanceReversal.id).where(
                FinanceReversal.original_journal_id == FinanceDirectBillPayment.journal_id
            ).exists(),
        )
    ) or 0
    return max(0, bill.amount_paise - int(paid))


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
        unknown = set(raw) - {'account_id', 'project_id', 'description', 'amount_paise'}
        if unknown:
            raise ValueError(f'Bill line {idx} has unexpected fields.')
        acc_id = raw.get('account_id')
        acc = db.get(GLAccount, acc_id) if type(acc_id) is int else None
        if acc is None or acc.entity_id != entity_id or acc.kind != 'expense' or not acc.active or not acc.posting_allowed:
            raise ValueError(f'Bill line {idx}: choose an active expense account for this company.')
        amount = raw.get('amount_paise')
        positive_minor(amount)
        pid = raw.get('project_id')
        if pid is not None:
            proj = db.get(Project, pid) if type(pid) is int else None
            if proj is None or proj.deleted_at:
                raise ValueError(f'Bill line {idx}: project not found.')
            if actor is not None and not can_access_project(db, actor, proj.id):
                raise ValueError(f'Bill line {idx}: you do not have access to that project.')
        desc = raw.get('description') or ''
        if not isinstance(desc, str) or len(desc.strip()) > 250:
            raise ValueError(f'Bill line {idx}: description must be 250 characters or fewer.')
        cleaned.append({'account': acc, 'account_id': acc.id, 'project_id': pid,
                        'description': desc.strip(), 'amount_paise': amount})
    return cleaned


def validate(db: Session, kind: str, data: dict, actor=None):
    from .accounting_kernel import (
        _calendar_date, _check_bill_dates, _check_dated_posting, _is_reversed, _policy,
        _supplier_payment_source, positive_minor, require_three_links, required_text,
    )
    if not isinstance(data, dict) or set(data) - DIRECT_BILL_FIELDS[kind]:
        raise ValueError('Unrecognized bill details.')
    if kind == 'finance_reverse_direct_bill':
        if set(data) != {'bill_id', 'reason'}:
            raise ValueError('Choose a posted bill and give a reason to reverse it.')
        bill_id = data.get('bill_id')
        bill = db.get(FinanceDirectBill, bill_id) if type(bill_id) is int else None
        if bill is None or not bill.journal_id or _is_reversed(db, bill.journal_id):
            raise ValueError('Posted supplier bill required.')
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
    if sum(ln['amount_paise'] for ln in lines) != data['amount_paise']:
        raise ValueError('Bill lines must add up to the total bill amount.')

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
    return ent, policy, payable, supplier, inv, lines, note.strip(), att_id


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
    ent, _, payable, supplier, inv, lines, _, _ = validate(db, kind, data, actor)
    jlines = [{'side': 'debit', 'account': ln['account'].name, 'amount_paise': ln['amount_paise'], 'project_id': ln['project_id']}
              for ln in lines]
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
        )
        pay.journal_id = journal.id
        add_audit(db, 'finance_direct_bill_payment', 'direct_bill_payment', pay.id,
                  f'Paid ₹{pay.amount_paise / 100:,.2f} against bill {bill.invoice_number} ({ref})', actor=actor)
        db.flush()
        return {'type': 'direct_bill_payment', 'id': pay.id, 'item_id': item.id}

    ent_id = data.get('entity_id')
    if type(ent_id) is not int or db.get(AccountingEntity, ent_id) is None:
        raise ValueError('Choose an existing company.')
    db.scalar(select(AccountingEntity).where(AccountingEntity.id == ent_id).with_for_update())
    db.info.pop('_period_locks', None)
    requester = submitter(db, item)
    ent, policy, payable, supplier, inv, lines, note, att_id = validate(db, kind, data, requester)
    bill = FinanceDirectBill(
        entity_id=ent.id, supplier_id=supplier.id, invoice_number=inv,
        bill_date=data['bill_date'], due_date=data['due_date'],
        payment_terms_days=data['payment_terms_days'], amount_paise=data['amount_paise'],
        note=note, attachment_id=att_id, ticket_id=item.ticket_id,
    )
    db.add(bill)
    db.flush()
    for ln in lines:
        db.add(FinanceDirectBillLine(
            bill_id=bill.id, account_id=ln['account_id'], project_id=ln['project_id'],
            description=ln['description'], amount_paise=ln['amount_paise'],
        ))
    db.flush()
    journal_lines = [
        (ln['account_id'], 'debit', ln['amount_paise'], ln['project_id'])
        for ln in lines
    ] + [
        (payable.id, 'credit', bill.amount_paise, None)
    ]
    journal = _post_lines(
        db, entity_id=ent.id, event_kind=DIRECT_BILL_EVENT, event_key=f'direct_bill:{bill.id}',
        source_id=bill.id, lines=journal_lines, ticket_id=item.ticket_id,
        policy_version=policy.policy_version, supplier_id=supplier.id,
    )
    bill.journal_id = journal.id
    add_audit(db, 'finance_direct_bill', 'direct_bill', bill.id,
              f'Posted supplier bill {bill.invoice_number} for {supplier.name} (₹{bill.amount_paise / 100:,.2f})', actor=actor)
    db.flush()
    return {'type': 'direct_bill', 'id': bill.id, 'item_id': item.id}

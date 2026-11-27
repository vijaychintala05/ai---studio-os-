"""Pending Books payment commitments, separate from posted supplier balances."""
from collections import defaultdict

from sqlalchemy import select

from .db import ApprovalTicket, ApprovalTicketItem
from .finance_helpers import BOOKS_BILL_PAYMENT_KINDS


def complete(data):
    return (type(data.get('bill_id')) is int and type(data.get('amount_paise')) is int
            and data['amount_paise'] > 0 and type(data.get('paid_through_id', data.get('bank_id'))) is int
            and all(isinstance(data.get(field), str) and data[field].strip()
                    for field in ('payment_date', 'payment_reference', 'idempotency_key')))


def pending_payment_totals(db, *, skip_item_id=None):
    query = select(ApprovalTicketItem.item_type, ApprovalTicketItem.after_data).join(ApprovalTicket).where(
        ApprovalTicketItem.item_type.in_(BOOKS_BILL_PAYMENT_KINDS),
        ApprovalTicketItem.status.in_(('pending', 'approved')),
        ApprovalTicket.status.in_(('draft', 'in_review')),
    )
    if skip_item_id is not None:
        query = query.where(ApprovalTicketItem.id != skip_item_id)
    amounts = defaultdict(int)
    for kind, data in db.execute(query):
        if complete(data):
            amounts[kind, data['bill_id']] += data['amount_paise']
    return amounts


def payment_availability(row, pending):
    kind = 'finance_direct_bill_payment' if row.get('direct_bill') else 'finance_payment'
    reserved = pending.get((kind, row['id']), 0) if row['owed_paise'] > 0 else 0
    return {'pending_payment_paise': reserved, 'available_payment_paise': max(0, row['owed_paise'] - reserved)}


def check_reservation(db, kind, data, *, skip_item_id=None):
    if not complete(data):
        return
    pending = pending_payment_totals(db, skip_item_id=skip_item_id).get((kind, data['bill_id']), 0)
    if pending == 0:
        return
    if kind == 'finance_direct_bill_payment':
        from .direct_bills import direct_bill_outstanding

        owed = direct_bill_outstanding(db, data['bill_id'])
    else:
        from .accounting_kernel import outstanding

        owed = outstanding(db, data['bill_id'])
    if owed is not None and pending + data['amount_paise'] > owed:
        raise ValueError('Part of this bill already has a payment awaiting approval. Check its available balance in Books.')


def check_bill_reversal(db, payment_kind, bill_id):
    if pending_payment_totals(db).get((payment_kind, bill_id), 0):
        raise ValueError('Decide the payment awaiting approval before reversing this bill.')

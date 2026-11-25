"""M3-2: Client receipts (partial/full + optional client TDS deduction), client advances/retainers,
and advance allocations to invoices. Every entry posts a balanced GL journal through an approval ticket.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import (AccountingEntity, FinanceReversal, GLAccount, GLJournal, GLLine,
                 Party, Project, SalesAdvance, SalesAdvanceAllocation, SalesInvoice,
                 SalesReceipt, add_audit)
from .sales_invoices import assert_period_open

SALES_RECEIPT_TYPES = frozenset({'sales_receipt', 'sales_reverse_receipt', 'sales_advance', 'sales_allocate_advance'})
SALES_RECEIPT_FIELDS = {
    'sales_receipt': {'invoice_id', 'deposit_account_id', 'tds_account_id', 'amount_paise',
                      'tds_paise', 'receipt_date', 'reference', 'idempotency_key'},
    'sales_reverse_receipt': {'receipt_id', 'reason'},
    'sales_advance': {'entity_id', 'client_id', 'project_id', 'deposit_account_id',
                      'advance_account_id', 'amount_paise', 'receipt_date', 'reference', 'idempotency_key'},
    'sales_allocate_advance': {'advance_id', 'invoice_id', 'amount_paise', 'allocation_date', 'idempotency_key'},
}


def _iso(val: str, label: str) -> str:
    s = str(val or '').strip()
    if len(s) != 10:
        raise ValueError(f'{label} must be YYYY-MM-DD.')
    date.fromisoformat(s)
    return s


def _reversed_subq(journal_col):
    return select(FinanceReversal.id).where(FinanceReversal.original_journal_id == journal_col).exists()


def invoice_outstanding(db: Session, invoice_id: int) -> int:
    inv = db.get(SalesInvoice, invoice_id)
    if not inv or not inv.journal_id:
        return 0
    if db.scalar(select(FinanceReversal.id).where(FinanceReversal.original_journal_id == inv.journal_id)):
        return 0
    rec_sum = int(db.scalar(select(func.coalesce(func.sum(SalesReceipt.amount_paise + SalesReceipt.tds_paise), 0)).where(
        SalesReceipt.invoice_id == inv.id, ~_reversed_subq(SalesReceipt.journal_id))) or 0)
    alloc_sum = int(db.scalar(select(func.coalesce(func.sum(SalesAdvanceAllocation.amount_paise), 0)).where(
        SalesAdvanceAllocation.invoice_id == inv.id, ~_reversed_subq(SalesAdvanceAllocation.journal_id))) or 0)
    return max(0, inv.total_paise - rec_sum - alloc_sum)


def advance_remaining(db: Session, advance_id: int) -> int:
    adv = db.get(SalesAdvance, advance_id)
    if not adv or not adv.journal_id:
        return 0
    if db.scalar(select(FinanceReversal.id).where(FinanceReversal.original_journal_id == adv.journal_id)):
        return 0
    used = int(db.scalar(select(func.coalesce(func.sum(SalesAdvanceAllocation.amount_paise), 0)).where(
        SalesAdvanceAllocation.advance_id == adv.id, ~_reversed_subq(SalesAdvanceAllocation.journal_id))) or 0)
    return max(0, adv.amount_paise - used)


def validate(db: Session, typ: str, d: dict, actor=None) -> dict:
    if typ == 'sales_receipt':
        inv_id = int(d.get('invoice_id') or 0)
        inv = db.get(SalesInvoice, inv_id)
        if not inv or not inv.journal_id:
            raise ValueError('Posted sales invoice not found.')
        dep = db.get(GLAccount, int(d.get('deposit_account_id') or 0))
        if not dep or dep.entity_id != inv.entity_id or dep.kind not in ('bank', 'cash') or not dep.active:
            raise ValueError('Choose an active bank or cash account in this company.')
        amt = int(d.get('amount_paise') or 0)
        tds = int(d.get('tds_paise') or 0)
        if amt <= 0 or tds < 0:
            raise ValueError('Receipt amount must be positive and TDS cannot be negative.')
        tds_acc_id = None
        if tds > 0:
            tacc = db.get(GLAccount, int(d.get('tds_account_id') or 0))
            if not tacc or tacc.entity_id != inv.entity_id or not tacc.active or not tacc.posting_allowed:
                raise ValueError('Choose an active TDS Receivable account when TDS is deducted.')
            tds_acc_id = tacc.id
        owed = invoice_outstanding(db, inv.id)
        if amt + tds > owed:
            raise ValueError(f'Receipt plus TDS exceeds what is still owed on invoice {inv.invoice_number} (₹{owed / 100:,.2f}).')
        rdate = _iso(d.get('receipt_date'), 'Receipt date')
        assert_period_open(db, inv.entity_id, rdate[:7])
        ref = str(d.get('reference') or '').strip()
        if not ref:
            raise ValueError('Payment reference is required.')
        idem = str(d.get('idempotency_key') or '').strip()
        if not idem:
            raise ValueError('Idempotency key is required.')
        if db.scalar(select(SalesReceipt.id).where(SalesReceipt.idempotency_key == idem)):
            raise ValueError('This receipt has already been posted.')
        return {
            'invoice_id': inv.id, 'deposit_account_id': dep.id, 'tds_account_id': tds_acc_id,
            'amount_paise': amt, 'tds_paise': tds, 'receipt_date': rdate,
            'reference': ref[:120], 'idempotency_key': idem[:120],
        }

    if typ == 'sales_reverse_receipt':
        rid = int(d.get('receipt_id') or 0)
        rec = db.get(SalesReceipt, rid)
        if not rec or not rec.journal_id:
            raise ValueError('Posted receipt not found.')
        if db.scalar(select(FinanceReversal.id).where(FinanceReversal.original_journal_id == rec.journal_id)):
            raise ValueError('This receipt has already been reversed.')
        reason = str(d.get('reason') or '').strip()
        if len(reason) < 5:
            raise ValueError('Give a short reason (at least 5 characters) for reversing the receipt.')
        inv = db.get(SalesInvoice, rec.invoice_id)
        assert_period_open(db, inv.entity_id, rec.receipt_date[:7])
        return {'receipt_id': rec.id, 'reason': reason[:300]}

    if typ == 'sales_advance':
        ent_id = int(d.get('entity_id') or 0)
        if not db.get(AccountingEntity, ent_id):
            raise ValueError('Choose a valid company.')
        client = db.get(Party, int(d.get('client_id') or 0))
        if not client or client.deleted_at or client.kind != 'client':
            raise ValueError('Choose an active client.')
        proj_id = d.get('project_id')
        if proj_id is not None:
            p = db.get(Project, int(proj_id))
            if not p or p.deleted_at:
                raise ValueError('Choose an active project.')
            proj_id = p.id
        dep = db.get(GLAccount, int(d.get('deposit_account_id') or 0))
        if not dep or dep.entity_id != ent_id or dep.kind not in ('bank', 'cash') or not dep.active:
            raise ValueError('Choose an active bank or cash account.')
        adv_acc = db.get(GLAccount, int(d.get('advance_account_id') or 0))
        if not adv_acc or adv_acc.entity_id != ent_id or not adv_acc.active or not adv_acc.posting_allowed:
            raise ValueError('Choose an active Client Advances liability account.')
        amt = int(d.get('amount_paise') or 0)
        if amt <= 0:
            raise ValueError('Advance amount must be positive.')
        rdate = _iso(d.get('receipt_date'), 'Receipt date')
        assert_period_open(db, ent_id, rdate[:7])
        ref = str(d.get('reference') or '').strip()
        if not ref:
            raise ValueError('Payment reference is required.')
        idem = str(d.get('idempotency_key') or '').strip()
        if not idem:
            raise ValueError('Idempotency key is required.')
        if db.scalar(select(SalesAdvance.id).where(SalesAdvance.idempotency_key == idem)):
            raise ValueError('This client advance has already been posted.')
        return {
            'entity_id': ent_id, 'client_id': client.id, 'project_id': proj_id,
            'deposit_account_id': dep.id, 'advance_account_id': adv_acc.id,
            'amount_paise': amt, 'receipt_date': rdate, 'reference': ref[:120],
            'idempotency_key': idem[:120],
        }

    if typ == 'sales_allocate_advance':
        adv = db.get(SalesAdvance, int(d.get('advance_id') or 0))
        inv = db.get(SalesInvoice, int(d.get('invoice_id') or 0))
        if not adv or not adv.journal_id or not inv or not inv.journal_id:
            raise ValueError('Choose a posted client advance and posted sales invoice.')
        if adv.entity_id != inv.entity_id or adv.client_id != inv.client_id:
            raise ValueError('Advance and invoice must belong to the same company and client.')
        amt = int(d.get('amount_paise') or 0)
        if amt <= 0:
            raise ValueError('Allocation amount must be positive.')
        rem = advance_remaining(db, adv.id)
        if amt > rem:
            raise ValueError(f'Allocation exceeds remaining client advance (₹{rem / 100:,.2f}).')
        owed = invoice_outstanding(db, inv.id)
        if amt > owed:
            raise ValueError(f'Allocation exceeds remaining invoice balance (₹{owed / 100:,.2f}).')
        adate = _iso(d.get('allocation_date'), 'Allocation date')
        assert_period_open(db, inv.entity_id, adate[:7])
        idem = str(d.get('idempotency_key') or '').strip()
        if not idem or db.scalar(select(SalesAdvanceAllocation.id).where(SalesAdvanceAllocation.idempotency_key == idem)):
            raise ValueError('Unique idempotency key is required.')
        return {'advance_id': adv.id, 'invoice_id': inv.id, 'amount_paise': amt,
                'allocation_date': adate, 'idempotency_key': idem[:120]}

    raise ValueError(f'Unknown sales receipt item type: {typ}')


def preview(db: Session, typ: str, d: dict, actor=None) -> dict:
    clean = validate(db, typ, d, actor)
    if typ == 'sales_receipt':
        return {'summary': f"Client receipt ₹{clean['amount_paise'] / 100:,.2f} (TDS ₹{clean['tds_paise'] / 100:,.2f}) against invoice #{clean['invoice_id']}", 'lines': []}
    if typ == 'sales_reverse_receipt':
        return {'summary': f"Reverse receipt #{clean['receipt_id']} ({clean['reason']})", 'lines': []}
    if typ == 'sales_advance':
        return {'summary': f"Client advance / retainer ₹{clean['amount_paise'] / 100:,.2f} (ref {clean['reference']})", 'lines': []}
    return {'summary': f"Allocate ₹{clean['amount_paise'] / 100:,.2f} from advance #{clean['advance_id']} to invoice #{clean['invoice_id']}", 'lines': []}


def apply(db: Session, item, actor) -> dict:
    typ = item.item_type
    clean = validate(db, typ, item.after_data, actor)
    if typ == 'sales_receipt':
        inv = db.get(SalesInvoice, clean['invoice_id'])
        rec = SalesReceipt(**clean, ticket_id=item.ticket_id)
        db.add(rec)
        db.flush()
        j = GLJournal(entity_id=inv.entity_id, source_event='SALES_RECEIPT_POSTED',
                      event_key=f'sales_receipt:{rec.id}', source_id=rec.id,
                      ticket_id=item.ticket_id, status='posted')
        db.add(j)
        db.flush()
        lines = [
            GLLine(journal_id=j.id, account_id=clean['deposit_account_id'], side='debit',
                   amount_paise=clean['amount_paise'], project_id=inv.project_id),
            GLLine(journal_id=j.id, account_id=inv.ar_account_id, side='credit',
                   amount_paise=clean['amount_paise'] + clean['tds_paise'], project_id=inv.project_id),
        ]
        if clean['tds_paise'] > 0:
            lines.append(GLLine(journal_id=j.id, account_id=clean['tds_account_id'], side='debit',
                                amount_paise=clean['tds_paise'], project_id=inv.project_id))
        db.add_all(lines)
        rec.journal_id = j.id
        db.flush()
        actor_name = actor if isinstance(actor, str) else getattr(actor, 'username', 'system')
        add_audit(db, 'sales_receipt', 'sales_receipt', rec.id,
                  f'Posted client receipt {rec.reference} (journal #{j.id})', actor=actor_name)
        return {'record_type': 'sales_receipt', 'id': rec.id, 'journal_id': j.id}

    if typ == 'sales_reverse_receipt':
        from .accounting_kernel import _reverse_posted
        rec = db.get(SalesReceipt, clean['receipt_id'])
        rj = _reverse_posted(db, rec.journal_id, clean['reason'], item.ticket_id)
        db.flush()
        return {'record_type': 'sales_reverse_receipt', 'id': rec.id, 'journal_id': rj.id}

    if typ == 'sales_advance':
        adv = SalesAdvance(**clean, ticket_id=item.ticket_id)
        db.add(adv)
        db.flush()
        j = GLJournal(entity_id=clean['entity_id'], source_event='SALES_ADVANCE_POSTED',
                      event_key=f'sales_advance:{adv.id}', source_id=adv.id, ticket_id=item.ticket_id, status='posted')
        db.add(j)
        db.flush()
        db.add_all([
            GLLine(journal_id=j.id, account_id=clean['deposit_account_id'], side='debit',
                   amount_paise=clean['amount_paise'], project_id=clean['project_id']),
            GLLine(journal_id=j.id, account_id=clean['advance_account_id'], side='credit',
                   amount_paise=clean['amount_paise'], project_id=clean['project_id']),
        ])
        adv.journal_id = j.id
        db.flush()
        return {'record_type': 'sales_advance', 'id': adv.id, 'journal_id': j.id}

    if typ == 'sales_allocate_advance':
        adv = db.get(SalesAdvance, clean['advance_id'])
        inv = db.get(SalesInvoice, clean['invoice_id'])
        alloc = SalesAdvanceAllocation(**clean, ticket_id=item.ticket_id)
        db.add(alloc)
        db.flush()
        j = GLJournal(entity_id=inv.entity_id, source_event='SALES_ADVANCE_ALLOCATED',
                      event_key=f'sales_advance_alloc:{alloc.id}', source_id=alloc.id,
                      ticket_id=item.ticket_id, status='posted')
        db.add(j)
        db.flush()
        db.add_all([
            GLLine(journal_id=j.id, account_id=adv.advance_account_id, side='debit',
                   amount_paise=clean['amount_paise'], project_id=inv.project_id),
            GLLine(journal_id=j.id, account_id=inv.ar_account_id, side='credit',
                   amount_paise=clean['amount_paise'], project_id=inv.project_id),
        ])
        alloc.journal_id = j.id
        db.flush()
        return {'record_type': 'sales_allocate_advance', 'id': alloc.id, 'journal_id': j.id}

    raise ValueError(f'Unknown sales receipt item type: {typ}')


def customer_statement(db: Session, client_id: int, entity_id: int | None = None) -> dict:
    client = db.get(Party, client_id)
    if not client or client.deleted_at:
        raise ValueError('Client not found.')
    inv_stmt = select(SalesInvoice).where(SalesInvoice.client_id == client_id).order_by(SalesInvoice.id)
    adv_stmt = select(SalesAdvance).where(SalesAdvance.client_id == client_id).order_by(SalesAdvance.id)
    if entity_id is not None:
        inv_stmt = inv_stmt.where(SalesInvoice.entity_id == entity_id)
        adv_stmt = adv_stmt.where(SalesAdvance.entity_id == entity_id)
    invoices = []
    total_receivable = 0
    for inv in db.scalars(inv_stmt).all():
        owed = invoice_outstanding(db, inv.id)
        total_receivable += owed
        invoices.append({
            'id': inv.id, 'invoice_number': inv.invoice_number, 'invoice_date': inv.invoice_date,
            'due_date': inv.due_date, 'total_paise': inv.total_paise, 'owed_paise': owed,
        })
    advances = []
    unallocated_total = 0
    for adv in db.scalars(adv_stmt).all():
        rem = advance_remaining(db, adv.id)
        unallocated_total += rem
        advances.append({
            'id': adv.id, 'reference': adv.reference, 'receipt_date': adv.receipt_date,
            'amount_paise': adv.amount_paise, 'remaining_paise': rem,
        })
    return {
        'client': {'id': client.id, 'name': client.name, 'gstin': client.gstin},
        'invoices': invoices,
        'advances': advances,
        'receivable_paise': total_receivable,
        'unallocated_advance_paise': unallocated_total,
    }

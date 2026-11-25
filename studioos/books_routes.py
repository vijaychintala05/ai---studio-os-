"""Books home and the Party page (App Flows map). Read-only views of what the books hold.
- Books home (owner and accounts): per company, what is owed to suppliers, how old the unpaid bills are, the bank accounts and their
  balances from the ledger, the months already closed and the supplier payments not yet matched to the bank statement.
- Party page: one vendor or client. Contact details for roles that may see contacts; amounts (bills, payments, what is owed) only for
  owner, accounts and manager. Architects see the contact and the projects only, site staff see nothing.
Bill ageing uses the ledger posting date. Older bills and payments may have an unknown document date. Money is whole paise."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from .access import visible_project_ids
from .accounting_kernel import BILL_DATE_FIELDS
from .db import (AccountingEntity, ApprovalTicket, ChatMessage, ChatSession, ClosedAccountingPeriod, Document,
                 FinanceAdvanceAllocation, FinanceBankReconciliation, FinanceCashAdvanceAllocation,
                 FinanceDirectBill, FinanceDirectBillLine, FinanceDirectBillPayment, GLAccount,
                 FinancePurchaseOrder, FinanceReversal, FinanceSupplierAdvance, FinanceSupplierBill,
                 FinanceSupplierCashAdvance, FinanceSupplierCashPayment, FinanceSupplierPayment,
                 GLJournal, GLLine, Party, Project, RegisteredBank, User)
from .deps import get_db
from .legacy_payables import PAYMENT_EVENT, open_legacy_payables, posted_legacy_payments
from .operating_totals import company_expense_totals
from .party_access import visible_party_ids
from .security import FINANCE_WRITE, current_user, permit

router = APIRouter(prefix='/api/books', tags=['Books'])

BOOKS_ROLES = ('admin', 'accounts')
AMOUNT_ROLES = ('admin', 'accounts', 'manager')
CONTACT_ROLES = ('admin', 'accounts', 'manager', 'architect')
AGEING = (('current', 0, 30), ('days_31_60', 31, 60), ('days_61_90', 61, 90), ('over_90', 91, 10 ** 6))


def _today():
    from . import universal_engine as u
    return u._today()


def bank_balance_rows(db):
    bank = RegisteredBank
    net = case((GLJournal.id.is_(None), 0), (GLLine.side == 'debit', GLLine.amount_paise),
               else_=-GLLine.amount_paise)
    query = (select(bank.entity_id, bank.id, bank.display_name, bank.masked_identifier,
                    func.coalesce(func.sum(net), 0).label('balance_paise'))
             .select_from(bank).outerjoin(GLLine, GLLine.account_id == bank.gl_account_id)
             .outerjoin(GLJournal, and_(GLJournal.id == GLLine.journal_id, GLJournal.entity_id == bank.entity_id,
                                        GLJournal.status == 'posted'))
             .group_by(bank.entity_id, bank.id, bank.display_name, bank.masked_identifier)
             .order_by(bank.entity_id, bank.id))
    return db.execute(query)


def _reversed(journal_id):
    return select(FinanceReversal.id).where(FinanceReversal.original_journal_id == journal_id).exists()


def _matched(journal_id=FinanceSupplierPayment.journal_id):
    return select(FinanceBankReconciliation.id).where(
        FinanceBankReconciliation.journal_id == journal_id
    ).exists()


def unmatched_payment_totals(db, entity_id=None):
    payment = FinanceSupplierPayment
    bills = select(payment.amount_paise.label('amount')).where(
        payment.journal_id.is_not(None), ~_reversed(payment.journal_id), ~_matched())
    historical = (select(GLLine.amount_paise.label('amount')).select_from(GLJournal)
                  .join(GLLine, GLLine.journal_id == GLJournal.id)
                  .join(GLAccount, GLAccount.id == GLLine.account_id)
                  .where(GLJournal.source_event == PAYMENT_EVENT, GLJournal.status == 'posted',
                         GLLine.side == 'credit', GLAccount.kind == 'bank',
                         ~_reversed(GLJournal.id), ~_matched(GLJournal.id)))
    if entity_id is not None:
        bills = bills.join(FinanceSupplierBill).where(FinanceSupplierBill.entity_id == entity_id)
        historical = historical.where(GLJournal.entity_id == entity_id)
    combined = bills.union_all(historical).subquery()
    count, amount = db.execute(select(func.count(), func.coalesce(func.sum(combined.c.amount), 0))).one()
    return {'count': count, 'paise': int(amount)}


def bill_rows(db, today, entity_id=None, supplier_id=None, allowed_projects=None):
    """Every bill with what has been paid and what is still owed, and how old it is."""
    bill, payment, advance = FinanceSupplierBill, FinanceSupplierPayment, FinanceAdvanceAllocation
    def paid_from(model):
        return select(func.coalesce(func.sum(model.amount_paise), 0)).where(
            model.bill_id == bill.id, ~_reversed(model.journal_id)
        ).scalar_subquery()

    paid = paid_from(payment) + paid_from(FinanceSupplierCashPayment)
    def allocated_from(model):
        return select(func.coalesce(func.sum(model.amount_paise), 0)).where(
            model.bill_id == bill.id, ~_reversed(model.journal_id),
        ).scalar_subquery()

    allocated = allocated_from(advance) + allocated_from(FinanceCashAdvanceAllocation)
    stmt = select(bill, GLJournal.posted_at, paid, allocated, _reversed(bill.journal_id)).outerjoin(
        GLJournal, GLJournal.id == bill.journal_id
    ).order_by(bill.id)
    if entity_id is not None:
        stmt = stmt.where(FinanceSupplierBill.entity_id == entity_id)
    if supplier_id is not None:
        stmt = stmt.where(FinanceSupplierBill.supplier_id == supplier_id)
    if allowed_projects is not None:
        stmt = stmt.where(bill.po_id.in_(select(FinancePurchaseOrder.id).where(
            FinancePurchaseOrder.project_id.in_(allowed_projects))))
    out = []
    for b, posted_at, paid_paise, allocated_paise, reversed_bill in db.execute(stmt):
        owed = 0 if reversed_bill else b.amount_paise - int(paid_paise) - int(allocated_paise)
        age = max(0, (today - posted_at.date()).days) if posted_at else 0
        out.append({'id': b.id, 'entity_id': b.entity_id, 'supplier_id': b.supplier_id, 'po_id': b.po_id, 'invoice_number': b.invoice_number,
                    **{field: getattr(b, field) for field in BILL_DATE_FIELDS},
                    'amount_paise': b.amount_paise, 'paid_paise': int(paid_paise), 'owed_paise': owed, 'age_days': age})
    # Include posted direct multi-line bills (M2-1) and their payments (M2-2).
    dpaid = select(func.coalesce(func.sum(FinanceDirectBillPayment.amount_paise), 0)).where(
        FinanceDirectBillPayment.bill_id == FinanceDirectBill.id,
        ~_reversed(FinanceDirectBillPayment.journal_id),
    ).scalar_subquery()
    dstmt = select(FinanceDirectBill, GLJournal.posted_at, dpaid, _reversed(FinanceDirectBill.journal_id)).outerjoin(
        GLJournal, GLJournal.id == FinanceDirectBill.journal_id
    ).order_by(FinanceDirectBill.id)
    if entity_id is not None:
        dstmt = dstmt.where(FinanceDirectBill.entity_id == entity_id)
    if supplier_id is not None:
        dstmt = dstmt.where(FinanceDirectBill.supplier_id == supplier_id)
    if allowed_projects is not None:
        dstmt = dstmt.where(FinanceDirectBill.id.in_(select(FinanceDirectBillLine.bill_id).where(
            FinanceDirectBillLine.project_id.in_(allowed_projects))))
    for b, posted_at, paid_paise, reversed_bill in db.execute(dstmt):
        owed = 0 if reversed_bill else max(0, b.amount_paise - int(paid_paise))
        age = max(0, (today - posted_at.date()).days) if posted_at else 0
        out.append({'id': b.id, 'direct_bill': True, 'entity_id': b.entity_id, 'supplier_id': b.supplier_id,
                    'po_id': None, 'invoice_number': b.invoice_number,
                    **{field: getattr(b, field) for field in BILL_DATE_FIELDS},
                    'amount_paise': b.amount_paise, 'paid_paise': int(paid_paise), 'owed_paise': owed, 'age_days': age})
    return out


def ageing(rows):
    out = {k: 0 for k, _, _ in AGEING}
    for r in rows:
        if r['owed_paise'] > 0:
            for k, lo, hi in AGEING:
                if lo <= r['age_days'] <= hi:
                    out[k] += r['owed_paise']
                    break
    return out


def legacy_payable_rows(db, today, **scope):
    return [{**row, 'owed_paise': row['outstanding_paise'],
             'age_days': max(0, (today - date.fromisoformat(row['posted_date'])).days)}
            for row in open_legacy_payables(db, **scope)]


@router.get('/home')
def books_home(user: User = Depends(permit(*BOOKS_ROLES)), db: Session = Depends(get_db)):
    today = _today()
    expenses = company_expense_totals(db)
    banks = defaultdict(list)
    for entity_id, bank_id, name, masked, balance in bank_balance_rows(db):
        banks[entity_id].append({'id': bank_id, 'name': name, 'masked': masked, 'balance_paise': int(balance)})
    companies = []
    for ent in db.scalars(select(AccountingEntity).order_by(AccountingEntity.id)):
        bills = bill_rows(db, today, ent.id)
        historical = legacy_payable_rows(db, today, entity_id=ent.id)
        rows = bills + historical
        closed = db.scalars(select(ClosedAccountingPeriod.year_month).where(ClosedAccountingPeriod.entity_id == ent.id).order_by(ClosedAccountingPeriod.year_month.desc()).limit(6)).all()
        by_supplier = {}
        for r in rows:
            if r['owed_paise'] > 0:
                by_supplier[r['supplier_id']] = by_supplier.get(r['supplier_id'], 0) + r['owed_paise']
        names = {p.id: p.name for p in db.scalars(select(Party).where(Party.id.in_(list(by_supplier) or [-1])))}
        companies.append({'entity_id': ent.id, 'name': ent.name, 'payable_paise': sum(r['owed_paise'] for r in rows), 'open_bills': sum(1 for r in bills if r['owed_paise'] > 0),
                          'posted_expense_paise': expenses.get(ent.id, 0),
                          'open_legacy_payables': len(historical),
                          'ageing': ageing(rows), 'banks': banks[ent.id], 'closed_months': list(closed),
                          'unmatched_payments': unmatched_payment_totals(db, ent.id),
                          'owed_by_supplier': sorted(({'party_id': k, 'name': names.get(k, ''), 'owed_paise': v} for k, v in by_supplier.items()), key=lambda x: -x['owed_paise'])[:10]})
    return {'date': today.isoformat(), 'companies': companies, 'note': 'Balances are aged from the day they were posted to the ledger.'}


@router.get('/parties/{party_id}')
def party_page(party_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role not in CONTACT_ROLES:
        raise HTTPException(404, 'Contact not found')
    party = db.get(Party, party_id)
    allowed = visible_project_ids(db, user)
    permitted = visible_party_ids(db, user, allowed)
    if not party or party.deleted_at or (permitted is not None and party_id not in permitted):
        raise HTTPException(404, 'Contact not found')
    today = _today()
    pos = db.scalars(select(FinancePurchaseOrder).where(FinancePurchaseOrder.supplier_id == party_id)).all()
    project_ids = {p.project_id for p in pos}
    if party.kind == 'client':
        project_ids |= set(db.scalars(select(Project.id).where(Project.client == party.name, Project.deleted_at.is_(None))))
    names = {p.id: p.name for p in db.scalars(select(Project).where(Project.id.in_(list(project_ids) or [-1])))}
    if allowed is not None:
        project_ids &= allowed
    out = {'party': {'id': party.id, 'name': party.name, 'kind': party.kind, 'phone': party.phone, 'trade': party.trade, 'gstin': party.gstin},
           'projects': [{'id': i, 'name': names.get(i, '')} for i in sorted(project_ids)], 'amounts': user.role in AMOUNT_ROLES}
    if user.role in AMOUNT_ROLES:
        rows = bill_rows(db, today, supplier_id=party_id, allowed_projects=allowed)
        historical = legacy_payable_rows(db, today, supplier_id=party_id, allowed_projects=allowed)
        balances = rows + historical
        bill_ids = [bill['id'] for bill in rows if not bill.get('direct_bill')]
        direct_bill_ids = [bill['id'] for bill in rows if bill.get('direct_bill')]
        payment = FinanceSupplierPayment
        cash = FinanceSupplierCashPayment
        bank_payments = db.execute(select(payment, _matched()).where(
            payment.bill_id.in_(bill_ids or [-1]), ~_reversed(payment.journal_id)
        ).order_by(payment.journal_id.desc()).limit(20)).all()
        cash_payments = db.scalars(select(cash).where(
            cash.bill_id.in_(bill_ids or [-1]), ~_reversed(cash.journal_id)
        ).order_by(cash.journal_id.desc()).limit(20)).all()
        direct_payments = db.scalars(select(FinanceDirectBillPayment).where(
            FinanceDirectBillPayment.bill_id.in_(direct_bill_ids or [-1]),
            ~_reversed(FinanceDirectBillPayment.journal_id),
        ).order_by(FinanceDirectBillPayment.journal_id.desc()).limit(20)).all()
        pay = [(p, matched, 'bank') for p, matched in bank_payments]
        pay.extend((p, False, 'cash') for p in cash_payments)
        pay.extend((p, False, 'bank' if p.bank_id else 'cash') for p in direct_payments)
        pay.sort(key=lambda row: row[0].journal_id or 0, reverse=True)
        # Unallocated supplier advances (bank + cash, M2-4).
        unallocated = []
        for adv in db.scalars(select(FinanceSupplierAdvance).where(
                FinanceSupplierAdvance.supplier_id == party_id, ~_reversed(FinanceSupplierAdvance.journal_id))):
            if allowed is not None and adv.project_id not in allowed:
                continue
            used = int(db.scalar(select(func.coalesce(func.sum(FinanceAdvanceAllocation.amount_paise), 0)).where(
                FinanceAdvanceAllocation.advance_id == adv.id, ~_reversed(FinanceAdvanceAllocation.journal_id))) or 0)
            if adv.amount_paise > used:
                unallocated.append({'id': adv.id, 'kind': 'bank', 'reference': adv.payment_reference,
                                    'payment_date': adv.payment_date, 'remaining_paise': adv.amount_paise - used})
        for cadv in db.scalars(select(FinanceSupplierCashAdvance).where(
                FinanceSupplierCashAdvance.supplier_id == party_id, ~_reversed(FinanceSupplierCashAdvance.journal_id))):
            if allowed is not None and cadv.project_id not in allowed:
                continue
            used = int(db.scalar(select(func.coalesce(func.sum(FinanceCashAdvanceAllocation.amount_paise), 0)).where(
                FinanceCashAdvanceAllocation.advance_id == cadv.id, ~_reversed(FinanceCashAdvanceAllocation.journal_id))) or 0)
            if cadv.amount_paise > used:
                unallocated.append({'id': cadv.id, 'kind': 'cash', 'reference': cadv.payment_reference,
                                    'payment_date': cadv.payment_date, 'remaining_paise': cadv.amount_paise - used})
        pos = [p for p in pos if allowed is None or p.project_id in allowed]
        out.update({'bills': [{k: r[k] for k in ('id', 'invoice_number', 'amount_paise', 'paid_paise', 'owed_paise', 'age_days', *BILL_DATE_FIELDS)} for r in rows],
                    'payments': [{'id': p.id, 'bill_id': p.bill_id, 'amount_paise': p.amount_paise, 'reference': p.payment_reference, 'payment_date': p.payment_date, 'matched': matched, 'kind': kind} for p, matched, kind in pay[:20]],
                    'unallocated_advances': unallocated,
                    'unallocated_advance_paise': sum(a['remaining_paise'] for a in unallocated),
                    'legacy_payables': historical, 'owed_paise': sum(r['owed_paise'] for r in balances),
                    'legacy_payments': posted_legacy_payments(db, supplier_id=party_id, allowed_projects=allowed),
                    'ageing': ageing(balances), 'orders': [{'id': p.id, 'po_number': p.po_number, 'amount_paise': p.amount_paise} for p in pos[-10:]]})
    return out


class DirectBillLineIn(BaseModel):
    account_id: int
    project_id: int | None = None
    description: str = Field(default='', max_length=250)
    amount_paise: int


class DirectBillIn(BaseModel):
    entity_id: int
    supplier_id: int
    invoice_number: str = Field(min_length=1, max_length=120)
    bill_date: str = Field(min_length=10, max_length=10)
    due_date: str = Field(min_length=10, max_length=10)
    payment_terms_days: int = Field(ge=0, le=365)
    amount_paise: int
    lines: list[DirectBillLineIn] = Field(min_length=1, max_length=50)
    note: str = Field(default='', max_length=500)
    attachment_id: int | None = None
    request_key: str | None = Field(default=None, max_length=120)


@router.get('/bill-options')
def bill_options(user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """Options for the New supplier bill form: companies, vendors, expense accounts, projects, and recent files."""
    allowed = visible_project_ids(db, user)
    companies = [{'id': e.id, 'name': e.name} for e in db.scalars(select(AccountingEntity).order_by(AccountingEntity.id))]
    vendors = [{'id': p.id, 'name': p.name, 'gstin': p.gstin}
               for p in db.scalars(select(Party).where(Party.kind == 'vendor', Party.deleted_at.is_(None)).order_by(Party.name))]
    accounts = [{'id': a.id, 'entity_id': a.entity_id, 'code': a.code, 'name': a.name}
                for a in db.scalars(select(GLAccount).where(
                    GLAccount.kind == 'expense', GLAccount.active.is_(True), GLAccount.posting_allowed.is_(True)
                ).order_by(GLAccount.code))]
    proj_stmt = select(Project).where(Project.deleted_at.is_(None)).order_by(Project.name)
    if allowed is not None:
        proj_stmt = proj_stmt.where(Project.id.in_(allowed or [-1]))
    projects = [{'id': p.id, 'name': p.name} for p in db.scalars(proj_stmt)]
    doc_stmt = select(Document).order_by(Document.id.desc()).limit(50)
    docs = [{'id': d.id, 'name': d.name} for d in db.scalars(doc_stmt)
            if allowed is None or d.project_id is None or d.project_id in allowed]
    return {'companies': companies, 'vendors': vendors, 'accounts': accounts,
            'projects': projects, 'documents': docs, 'today': _today().isoformat()}


@router.post('/bills')
def create_bill_draft(v: DirectBillIn, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """Submit a multi-line supplier bill as an approval ticket draft (never posts directly)."""
    from .main import _manual_draft
    payload = v.model_dump()
    request_key = payload.pop('request_key', None)
    try:
        return _manual_draft(db, user, 'finance_direct_bill', payload,
                             evidence='Supplier bill drafted in Books', request_key=request_key)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


class PaySelectedLineIn(BaseModel):
    kind: str = Field(pattern='^(po_bill|direct_bill)$')
    bill_id: int
    amount_paise: int


class PaySelectedIn(BaseModel):
    entity_id: int
    paid_through_id: int
    payment_date: str = Field(min_length=10, max_length=10)
    payment_reference: str = Field(min_length=1, max_length=120)
    items: list[PaySelectedLineIn] = Field(min_length=1, max_length=50)
    request_key: str | None = Field(default=None, max_length=120)


@router.get('/bills-due')
def bills_due(user: User = Depends(permit(*BOOKS_ROLES)), db: Session = Depends(get_db)):
    """M2-2: Unpaid supplier bills grouped into overdue, due this week, and due later."""
    from .paid_through import list_accounts
    today = _today()
    week_end = today + timedelta(days=7)
    rows = [r for r in bill_rows(db, today) if r['owed_paise'] > 0]
    vendor_ids = {r['supplier_id'] for r in rows}
    vnames = {p.id: p.name for p in db.scalars(select(Party).where(Party.id.in_(list(vendor_ids) or [-1])))}
    overdue, due_week, due_later = [], [], []
    for r in rows:
        item = {
            'kind': 'direct_bill' if r.get('direct_bill') else 'po_bill',
            'bill_id': r['id'], 'entity_id': r['entity_id'],
            'supplier_id': r['supplier_id'], 'supplier_name': vnames.get(r['supplier_id'], ''),
            'invoice_number': r['invoice_number'], 'bill_date': r['bill_date'], 'due_date': r['due_date'],
            'amount_paise': r['amount_paise'], 'paid_paise': r['paid_paise'], 'owed_paise': r['owed_paise'],
            'days_late': 0,
        }
        due_str = r.get('due_date')
        if due_str:
            due_d = date.fromisoformat(due_str)
            if due_d < today:
                item['days_late'] = (today - due_d).days
                overdue.append(item)
            elif due_d <= week_end:
                due_week.append(item)
            else:
                due_later.append(item)
        else:
            due_later.append(item)
    overdue.sort(key=lambda x: -x['days_late'])
    due_week.sort(key=lambda x: x['due_date'] or '')
    due_later.sort(key=lambda x: x['due_date'] or '9999-12-31')
    paying = {}
    for ent in db.scalars(select(AccountingEntity).order_by(AccountingEntity.id)):
        paying[ent.id] = [a for a in list_accounts(db, ent.id, user) if a.get('kind') in ('bank', 'cash')]
    return {'today': today.isoformat(), 'overdue': overdue, 'due_this_week': due_week,
            'due_later': due_later, 'paying_accounts': paying}


@router.post('/pay-selected')
def pay_selected_bills(v: PaySelectedIn, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """M2-2: Create one multi-item approval ticket to pay selected supplier bills from one bank or cash source."""
    import json
    from .tickets import add_proposal, validate_item
    seen = set()
    for ln in v.items:
        key = (ln.kind, ln.bill_id)
        if key in seen:
            raise HTTPException(422, 'Each bill can appear only once in a batch payment.')
        seen.add(key)
    base_key = (v.request_key or uuid.uuid4().hex)[:90]
    sid = f'pay-batch-{user.id}-{base_key}'[:120]
    existing = db.scalar(select(ApprovalTicket).where(ApprovalTicket.session_id == sid))
    if existing:
        return {'ticket_id': existing.id, 'item_count': len(v.items),
                'total_paise': sum(i.amount_paise for i in v.items), 'state': 'pending', 'repeat': True}
    session = ChatSession(id=sid, user_id=user.id, pending=None)
    db.add(session)
    db.flush()
    source_msg = ChatMessage(session_id=sid, user_id=user.id, speaker='user',
                             content='Bulk supplier bill payment drafted in Books\n' + json.dumps(v.model_dump(), sort_keys=True))
    db.add(source_msg)
    db.flush()
    ticket = None
    try:
        for idx, ln in enumerate(v.items, 1):
            item_type = 'finance_direct_bill_payment' if ln.kind == 'direct_bill' else 'finance_payment'
            if ln.kind == 'direct_bill':
                bill = db.get(FinanceDirectBill, ln.bill_id)
            else:
                bill = db.get(FinanceSupplierBill, ln.bill_id)
            if bill is None or bill.entity_id != v.entity_id:
                raise ValueError(f'Selected bill #{ln.bill_id} does not belong to this company.')
            item_data = {
                'bill_id': ln.bill_id,
                'paid_through_id': v.paid_through_id,
                'amount_paise': ln.amount_paise,
                'payment_reference': v.payment_reference.strip(),
                'payment_date': v.payment_date,
                'idempotency_key': f'{base_key}:{ln.kind}:{ln.bill_id}:{idx}',
            }
            ticket, item = add_proposal(db, session, item_type, item_data, source_msg.id, provider='form')
            validate_item(db, item)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc))
    return {'ticket_id': ticket.id, 'item_count': len(v.items),
            'total_paise': sum(i.amount_paise for i in v.items), 'state': 'pending', 'changed': False}


class TransferIn(BaseModel):
    entity_id: int
    from_account_id: int
    to_account_id: int
    amount_paise: int
    transfer_date: str = Field(min_length=10, max_length=10)
    reference: str = Field(default='', max_length=120)
    note: str = Field(default='', max_length=400)
    request_key: str | None = Field(default=None, max_length=120)


class ManualJournalLineIn(BaseModel):
    account_id: int
    side: str = Field(pattern='^(debit|credit)$')
    amount_paise: int
    project_id: int | None = None
    supplier_id: int | None = None


class ManualJournalIn(BaseModel):
    entity_id: int
    entry_date: str = Field(min_length=10, max_length=10)
    reference: str = Field(default='', max_length=120)
    narration: str = Field(min_length=2, max_length=400)
    lines: list[ManualJournalLineIn] = Field(min_length=2, max_length=50)
    request_key: str | None = Field(default=None, max_length=120)


@router.get('/journal-options')
def journal_options(user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """M2-3: Active posting accounts and bank/cash accounts for transfers and manual journals."""
    companies = [{'id': e.id, 'name': e.name} for e in db.scalars(select(AccountingEntity).order_by(AccountingEntity.id))]
    accounts = [{'id': a.id, 'entity_id': a.entity_id, 'code': a.code, 'name': a.name, 'kind': a.kind}
                for a in db.scalars(select(GLAccount).where(
                    GLAccount.active.is_(True), GLAccount.posting_allowed.is_(True)
                ).order_by(GLAccount.code))]
    return {'companies': companies, 'accounts': accounts, 'today': _today().isoformat()}


@router.post('/transfers')
def create_transfer_draft(v: TransferIn, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """M2-3: Draft an internal bank/cash transfer as an approval ticket."""
    from .main import _manual_draft
    key = v.request_key or uuid.uuid4().hex
    payload = v.model_dump(exclude={'request_key'})
    payload['idempotency_key'] = f'transfer:{user.id}:{key}'[:120]
    try:
        return _manual_draft(db, user, 'finance_transfer', payload,
                             evidence='Bank or cash transfer drafted in Books', request_key=key)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post('/manual-journals')
def create_manual_journal_draft(v: ManualJournalIn, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """M2-3: Draft a balanced multi-line manual journal entry as an approval ticket."""
    from .main import _manual_draft
    key = v.request_key or uuid.uuid4().hex
    payload = v.model_dump(exclude={'request_key'})
    payload['idempotency_key'] = f'journal:{user.id}:{key}'[:120]
    try:
        return _manual_draft(db, user, 'finance_manual_journal', payload,
                             evidence='Manual journal drafted in Books', request_key=key)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get('/parties/{party_id}/statement.pdf')
def party_statement_pdf(party_id: int, user: User = Depends(permit(*AMOUNT_ROLES)), db: Session = Depends(get_db)):
    """M2-4: Download a plain-English Vendor Statement PDF (owner, accounts, manager only)."""
    from .vendor_statement import render_vendor_statement_pdf
    data = party_page(party_id, user=user, db=db)
    pdf_bytes = render_vendor_statement_pdf(data)
    safe_name = ''.join(ch if ch.isalnum() or ch in ('-', '_') else '_' for ch in data['party']['name'])[:40] or 'vendor'
    return Response(
        content=pdf_bytes,
        media_type='application/pdf',
        headers={'Content-Disposition': f'inline; filename="statement_{safe_name}.pdf"'},
    )


class BankCsvImportIn(BaseModel):
    csv_text: str = Field(min_length=5, max_length=200_000)
    evidence_document_id: int
    request_key: str | None = Field(default=None, max_length=120)


class BankRuleIn(BaseModel):
    entity_id: int
    bank_id: int | None = None
    match_text: str = Field(min_length=2, max_length=120)
    direction: str = Field(default='any', max_length=10)
    suggested_account_id: int
    suggested_party_id: int | None = None
    note: str = Field(default='', max_length=300)
    request_key: str | None = Field(default=None, max_length=120)


class BankUnreconcileIn(BaseModel):
    reconciliation_id: int
    reason: str = Field(min_length=5, max_length=300)
    request_key: str | None = Field(default=None, max_length=120)


@router.get('/bank-feed/{bank_id}')
def get_bank_feed(bank_id: int, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """M2-5: Uncategorised bank statement lines, match suggestions, and suggest-only rules."""
    from .bank_feed import bank_feed_for_bank
    try:
        return bank_feed_for_bank(db, bank_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.post('/bank-feed/{bank_id}/import-csv')
def import_bank_csv(bank_id: int, v: BankCsvImportIn, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """M2-5: Parse a bank statement CSV and create one multi-item draft ticket for approval."""
    from .bank_feed import parse_bank_csv
    from .db import FinanceBankStatementLine
    from .tickets import add_proposal, validate_item
    bank = db.get(RegisteredBank, bank_id)
    if not bank:
        raise HTTPException(404, 'Bank account not found.')
    try:
        parsed = parse_bank_csv(v.csv_text)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    existing_refs = set(db.scalars(select(FinanceBankStatementLine.statement_reference).where(
        FinanceBankStatementLine.bank_id == bank_id)).all())
    items, skipped = [], 0
    for row in parsed:
        if row['statement_reference'] in existing_refs:
            skipped += 1
            continue
        existing_refs.add(row['statement_reference'])
        items.append({
            'item_type': 'finance_bank_statement_line',
            'after_data': {
                'bank_id': bank_id,
                'booking_date': row['booking_date'],
                'statement_reference': row['statement_reference'],
                'signed_amount_paise': row['signed_amount_paise'],
                'evidence_document_id': v.evidence_document_id,
            },
            'evidence': f"CSV bank line {row['statement_reference']} ({row['booking_date']})",
            'confidence': 1.0,
        })
    if not items:
        raise HTTPException(422, 'All CSV rows are already imported for this bank account.')
    sess = ChatSession(user_id=user.id, title=f'Bank CSV import ({bank.display_name})'[:120])
    db.add(sess)
    db.flush()
    msg = ChatMessage(session_id=sess.id, sender='user', text=f'Bank CSV import: {len(items)} new lines')
    db.add(msg)
    db.flush()
    try:
        ticket = None
        for row in items:
            ticket, item = add_proposal(db, sess, row['item_type'], row['after_data'], msg.id, provider='form')
            validate_item(db, item)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc))
    db.commit()
    return {'ticket_id': ticket.id, 'imported_count': len(items), 'skipped_count': skipped, 'status': ticket.status}


@router.post('/bank-rules')
def create_bank_rule_draft(v: BankRuleIn, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """M2-5: Draft a suggest-only bank matching rule for approval (never auto-posts)."""
    from .main import _manual_draft
    payload = v.model_dump(exclude={'request_key'})
    try:
        return _manual_draft(db, user, 'finance_bank_rule', payload,
                             evidence='Bank feed rule drafted in Books', request_key=v.request_key)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post('/bank-unreconcile')
def create_bank_unreconcile_draft(v: BankUnreconcileIn, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """M2-5: Draft an append-only bank unreconciliation with a required reason."""
    from .main import _manual_draft
    payload = v.model_dump(exclude={'request_key'})
    try:
        return _manual_draft(db, user, 'finance_unreconcile_bank', payload,
                             evidence='Bank match un-matched in Books', request_key=v.request_key)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


class FinanceAttachmentIn(BaseModel):
    entity_id: int
    target_kind: str = Field(min_length=2, max_length=40)
    target_id: int
    document_id: int
    note: str = Field(default='', max_length=250)
    request_key: str | None = Field(default=None, max_length=120)


@router.get('/attachments')
def get_finance_attachments(target_kind: str, target_id: int, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """M2-6: List approved document attachments for a money entry."""
    from .finance_attachments import TARGET_MODELS, list_attachments
    if target_kind not in TARGET_MODELS:
        raise HTTPException(422, f'Unsupported target_kind: {target_kind}')
    return {'target_kind': target_kind, 'target_id': target_id,
            'attachments': list_attachments(db, target_kind, target_id)}


@router.post('/attachments')
def create_finance_attachment_draft(v: FinanceAttachmentIn, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """M2-6: Draft attaching a stored document to a money entry, with duplicate SHA-256 warning."""
    from .finance_attachments import preview as att_preview
    from .main import _manual_draft
    payload = v.model_dump(exclude={'request_key'})
    try:
        info = att_preview(db, 'finance_attach_document', payload, user)
        draft = _manual_draft(db, user, 'finance_attach_document', payload,
                              evidence='Document attached to money entry in Books', request_key=v.request_key)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {**draft, 'duplicate_warning': info['duplicate_warning'], 'existing_targets': info['existing_targets']}


class TaxPreviewIn(BaseModel):
    firm_state_code: str = Field(default='29', min_length=2, max_length=2)
    counterparty_state_code: str = Field(default='29', min_length=2, max_length=2)
    site_state_code: str | None = Field(default=None, min_length=2, max_length=2)
    sac_hsn: str = Field(default='', max_length=20)
    taxable_paise: int = Field(ge=0)
    gst_rate_bps: int = Field(default=1800, ge=0, le=2800)
    itc_category: str | None = None
    gstr2b_matched: bool = True
    days_unpaid: int = 0
    for_turnkey_resupply: bool = False
    rcm_kind: str | None = None
    tds_section: str | None = None
    tds_deductor_active: bool = True
    payee_entity_type: str = 'individual'
    vendor_has_pan: bool = True
    fy_cumulative_paise: int = 0


class TaxSettingIn(BaseModel):
    entity_id: int
    gstin: str = Field(default='', max_length=15)
    state_code: str = Field(min_length=2, max_length=2)
    tds_deductor_active: bool = False
    composition_scheme: bool = False
    request_key: str | None = Field(default=None, max_length=120)


@router.post('/tax/preview')
def tax_preview(v: TaxPreviewIn, user: User = Depends(permit(*FINANCE_WRITE))):
    """M3-4: Pure deterministic Indian GST + TDS calculation preview (no writes)."""
    from .tax_engine import preview_tax_calculation
    try:
        return preview_tax_calculation(v.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post('/tax/settings')
def create_tax_setting_draft(v: TaxSettingIn, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """M3-4: Draft company GST/TDS settings for owner approval."""
    from .main import _manual_draft
    payload = v.model_dump(exclude={'request_key'})
    try:
        return _manual_draft(db, user, 'finance_tax_setting', payload,
                             evidence='Company GST/TDS settings drafted in Books', request_key=v.request_key)
    except ValueError as exc:
        raise HTTPException(422, str(exc))

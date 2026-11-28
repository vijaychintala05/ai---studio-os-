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

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, StrictInt
from sqlalchemy import and_, case, func, or_, select
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
from .operating_totals import company_expense_totals, portfolio_totals
from .project_parties import contact_projects
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
    direct_payment = FinanceDirectBillPayment
    direct = select(direct_payment.amount_paise.label('amount')).where(
        direct_payment.bank_id.is_not(None), direct_payment.journal_id.is_not(None),
        ~_reversed(direct_payment.journal_id), ~_matched(direct_payment.journal_id),
    )
    if entity_id is not None:
        bills = bills.join(FinanceSupplierBill).where(FinanceSupplierBill.entity_id == entity_id)
        direct = direct.join(FinanceDirectBill).where(FinanceDirectBill.entity_id == entity_id)
    combined = bills.union_all(direct).subquery()
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
    stmt = select(bill, FinancePurchaseOrder.project_id, GLJournal.posted_at, paid, allocated,
                  _reversed(bill.journal_id)).join(FinancePurchaseOrder, FinancePurchaseOrder.id == bill.po_id).join(
        GLJournal, GLJournal.id == bill.journal_id
    ).where(GLJournal.status == 'posted').order_by(bill.id)
    if entity_id is not None:
        stmt = stmt.where(FinanceSupplierBill.entity_id == entity_id)
    if supplier_id is not None:
        stmt = stmt.where(FinanceSupplierBill.supplier_id == supplier_id)
    if allowed_projects is not None:
        stmt = stmt.where(bill.po_id.in_(select(FinancePurchaseOrder.id).where(
            FinancePurchaseOrder.project_id.in_(allowed_projects))))
    out = []
    for b, project_id, posted_at, paid_paise, allocated_paise, reversed_bill in db.execute(stmt):
        owed = 0 if reversed_bill else b.amount_paise - int(paid_paise) - int(allocated_paise)
        age = max(0, (today - posted_at.date()).days) if posted_at else 0
        out.append({'id': b.id, 'entity_id': b.entity_id, 'supplier_id': b.supplier_id, 'po_id': b.po_id, 'invoice_number': b.invoice_number,
                    'project_id': project_id, 'journal_id': b.journal_id, 'reversed': bool(reversed_bill),
                    **{field: getattr(b, field) for field in BILL_DATE_FIELDS},
                    'amount_paise': b.amount_paise, 'paid_paise': int(paid_paise), 'owed_paise': owed, 'age_days': age})
    # Include posted direct multi-line bills (M2-1) and their payments (M2-2).
    dpaid = select(func.coalesce(func.sum(FinanceDirectBillPayment.amount_paise), 0)).where(
        FinanceDirectBillPayment.bill_id == FinanceDirectBill.id,
        ~_reversed(FinanceDirectBillPayment.journal_id),
    ).scalar_subquery()
    dstmt = select(FinanceDirectBill, GLJournal.posted_at, dpaid, _reversed(FinanceDirectBill.journal_id)).join(
        GLJournal, GLJournal.id == FinanceDirectBill.journal_id
    ).where(GLJournal.status == 'posted').order_by(FinanceDirectBill.id)
    if entity_id is not None:
        dstmt = dstmt.where(FinanceDirectBill.entity_id == entity_id)
    if supplier_id is not None:
        dstmt = dstmt.where(FinanceDirectBill.supplier_id == supplier_id)
    if allowed_projects is not None:
        hidden_line = select(FinanceDirectBillLine.id).where(
            FinanceDirectBillLine.bill_id == FinanceDirectBill.id,
            or_(FinanceDirectBillLine.project_id.is_(None), FinanceDirectBillLine.project_id.not_in(allowed_projects)),
        ).exists()
        dstmt = dstmt.where(~hidden_line)
    for b, posted_at, paid_paise, reversed_bill in db.execute(dstmt):
        owed = 0 if reversed_bill else max(0, b.amount_paise - int(paid_paise))
        age = max(0, (today - posted_at.date()).days) if posted_at else 0
        out.append({'id': b.id, 'direct_bill': True, 'entity_id': b.entity_id, 'supplier_id': b.supplier_id,
                    'po_id': None, 'invoice_number': b.invoice_number,
                    'journal_id': b.journal_id, 'reversed': bool(reversed_bill),
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


@router.get('/home')
def books_home(user: User = Depends(permit(*BOOKS_ROLES)), db: Session = Depends(get_db)):
    today = _today()
    expenses = company_expense_totals(db)
    totals, _ = portfolio_totals(db)
    projects = defaultdict(list)
    for project in db.scalars(select(Project).where(Project.deleted_at.is_(None)).order_by(Project.name)):
        projects[project.company_id].append({
            'id': project.id, 'name': project.name, 'budget_paise': project.budget_paise,
            'cost_to_date_paise': totals.get(project.id, {}).get('actual_paise', 0),
        })
    banks = defaultdict(list)
    for entity_id, bank_id, name, masked, balance in bank_balance_rows(db):
        banks[entity_id].append({'id': bank_id, 'name': name, 'masked': masked, 'balance_paise': int(balance)})
    companies = []
    for ent in db.scalars(select(AccountingEntity).order_by(AccountingEntity.id)):
        rows = bill_rows(db, today, ent.id)
        closed = db.scalars(select(ClosedAccountingPeriod.year_month).where(ClosedAccountingPeriod.entity_id == ent.id).order_by(ClosedAccountingPeriod.year_month.desc()).limit(6)).all()
        by_supplier = {}
        for r in rows:
            if r['owed_paise'] > 0:
                by_supplier[r['supplier_id']] = by_supplier.get(r['supplier_id'], 0) + r['owed_paise']
        names = {p.id: p.name for p in db.scalars(select(Party).where(Party.id.in_(list(by_supplier) or [-1])))}
        companies.append({'entity_id': ent.id, 'name': ent.name, 'payable_paise': sum(r['owed_paise'] for r in rows), 'open_bills': sum(1 for r in rows if r['owed_paise'] > 0),
                          'posted_expense_paise': expenses.get(ent.id, 0), 'projects': projects[ent.id],
                          'ageing': ageing(rows), 'banks': banks[ent.id], 'closed_months': list(closed),
                          'unmatched_payments': unmatched_payment_totals(db, ent.id),
                          'owed_by_supplier': sorted(({'party_id': k, 'name': names.get(k, ''), 'owed_paise': v} for k, v in by_supplier.items()), key=lambda x: -x['owed_paise'])[:10]})
    return {'date': today.isoformat(), 'companies': companies, 'projects_without_company': projects[None], 'note': 'Balances are aged from the day they were posted to the ledger.'}


@router.get('/parties/{party_id}')
def party_page(party_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role not in CONTACT_ROLES:
        raise HTTPException(404, 'Contact not found')
    party = db.get(Party, party_id)
    allowed = visible_project_ids(db, user)
    if not party or party.deleted_at:
        raise HTTPException(404, 'Contact not found')
    today = _today()
    amounts = user.role in AMOUNT_ROLES
    projects = contact_projects(db, party.id, allowed, amounts=amounts)
    if allowed is not None and not projects:
        raise HTTPException(404, 'Contact not found')
    out = {'party': {'id': party.id, 'name': party.name, 'kind': party.kind, 'phone': party.phone, 'trade': party.trade, 'gstin': party.gstin},
           'projects': projects, 'amounts': amounts}
    if user.role in AMOUNT_ROLES:
        rows = bill_rows(db, today, supplier_id=party_id, allowed_projects=allowed)
        from .expense_images import for_record

        public_bills = []
        for row in rows:
            bill = {key: row[key] for key in ('id', 'invoice_number', 'amount_paise', 'paid_paise',
                                             'owed_paise', 'age_days', *BILL_DATE_FIELDS)}
            if row.get('direct_bill') and (receipts := for_record(db, 'direct_bill', row['id'])):
                bill['attachments'] = receipts
            public_bills.append(bill)
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
        direct_payments = db.execute(select(FinanceDirectBillPayment, _matched(FinanceDirectBillPayment.journal_id)).where(
            FinanceDirectBillPayment.bill_id.in_(direct_bill_ids or [-1]),
            ~_reversed(FinanceDirectBillPayment.journal_id),
        ).order_by(FinanceDirectBillPayment.journal_id.desc()).limit(20)).all()
        pay = [(p, matched, 'bank') for p, matched in bank_payments]
        pay.extend((p, False, 'cash') for p in cash_payments)
        pay.extend((p, matched, 'bank' if p.bank_id else 'cash') for p, matched in direct_payments)
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
        orders = db.scalars(select(FinancePurchaseOrder).where(
            FinancePurchaseOrder.supplier_id == party_id,
            FinancePurchaseOrder.project_id.in_([project['id'] for project in projects]),
        ).order_by(FinancePurchaseOrder.id.desc()).limit(10)).all()
        out.update({'bills': public_bills,
                    'payments': [{'id': p.id, 'bill_id': p.bill_id, 'amount_paise': p.amount_paise, 'reference': p.payment_reference, 'payment_date': p.payment_date, 'matched': matched, 'kind': kind,
                                  'direct': isinstance(p, FinanceDirectBillPayment)} for p, matched, kind in pay[:20]],
                    'unallocated_advances': unallocated,
                    'unallocated_advance_paise': sum(a['remaining_paise'] for a in unallocated),
                    'owed_paise': sum(r['owed_paise'] for r in rows),
                    'ageing': ageing(rows), 'orders': [{'id': p.id, 'po_number': p.po_number, 'amount_paise': p.amount_paise} for p in reversed(orders)]})
    return out


class DirectBillLineIn(BaseModel):
    account_id: int
    project_id: int | None = None
    description: str = Field(default='', max_length=250)
    amount_paise: int
    tax_rate_bps: int = Field(default=0, ge=0, le=2800)
    quantity: int | None = None
    unit_rate_paise: int | None = None


class DirectBillIn(BaseModel):
    entity_id: int
    supplier_id: int
    invoice_number: str = Field(min_length=1, max_length=120)
    bill_date: str = Field(min_length=10, max_length=10)
    due_date: str = Field(min_length=10, max_length=10)
    payment_terms_days: int = Field(ge=0, le=365)
    amount_paise: int
    lines: list[DirectBillLineIn] = Field(min_length=1, max_length=50)
    supply_type: str = Field(default='intra', max_length=10)
    tds_section: str = Field(default='', max_length=16)
    tds_paise: int = Field(default=0, ge=0)
    tds_account_id: int | None = None
    cgst_account_id: int | None = None
    sgst_account_id: int | None = None
    igst_account_id: int | None = None
    po_id: int | None = None
    note: str = Field(default='', max_length=500)
    attachment_id: int | None = None
    receipt_ids: list[StrictInt] = Field(default_factory=list, max_length=5)
    request_key: str | None = Field(default=None, max_length=120)


@router.get('/bill-options')
def bill_options(user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """Options for the New supplier bill form: companies, vendors, expense/asset/inventory accounts, POs, projects, and recent files."""
    from .direct_bills import ALLOWED_BILL_LINE_KINDS, po_billed_paise
    allowed = visible_project_ids(db, user)
    companies = [{'id': e.id, 'name': e.name} for e in db.scalars(select(AccountingEntity).order_by(AccountingEntity.id))]
    vendors = [{'id': p.id, 'name': p.name, 'gstin': p.gstin, 'pan': p.pan,
                'gst_treatment': p.gst_treatment, 'state_code': p.state_code,
                'payment_terms_days': p.payment_terms_days, 'default_tds_section': p.default_tds_section}
               for p in db.scalars(select(Party).where(Party.kind == 'vendor', Party.deleted_at.is_(None)).order_by(Party.name))]
    accounts = [{'id': a.id, 'entity_id': a.entity_id, 'code': a.code, 'name': a.name, 'kind': a.kind}
                for a in db.scalars(select(GLAccount).where(
                    GLAccount.kind.in_(ALLOWED_BILL_LINE_KINDS), GLAccount.active.is_(True), GLAccount.posting_allowed.is_(True)
                ).order_by(GLAccount.code))]
    proj_stmt = select(Project).where(Project.deleted_at.is_(None)).order_by(Project.name)
    if allowed is not None:
        proj_stmt = proj_stmt.where(Project.id.in_(allowed or [-1]))
    projects = [{'id': p.id, 'name': p.name, 'company_id': p.company_id} for p in db.scalars(proj_stmt)]
    doc_stmt = select(Document).order_by(Document.id.desc()).limit(50)
    docs = [{'id': d.id, 'name': d.name} for d in db.scalars(doc_stmt)
            if allowed is None or d.project_id is None or d.project_id in allowed]
    pos = []
    for po in db.scalars(select(FinancePurchaseOrder).where(FinancePurchaseOrder.status == 'approved').order_by(FinancePurchaseOrder.id.desc()).limit(100)):
        if allowed is not None and po.project_id not in allowed:
            continue
        rem = max(0, po.amount_paise - po_billed_paise(db, po.id))
        if rem > 0:
            pos.append({'id': po.id, 'entity_id': po.entity_id, 'supplier_id': po.supplier_id,
                        'po_number': po.po_number, 'amount_paise': po.amount_paise, 'remaining_paise': rem})
    return {'companies': companies, 'vendors': vendors, 'accounts': accounts,
            'projects': projects, 'documents': docs, 'purchase_orders': pos, 'today': _today().isoformat()}


@router.post('/bills')
def create_bill_draft(v: DirectBillIn, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """Submit a multi-line supplier bill as an approval ticket draft (never posts directly)."""
    from .main import _manual_draft
    payload = v.model_dump()
    if not payload['receipt_ids']:
        payload.pop('receipt_ids')
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
    from .bill_payment_drafts import payment_availability, pending_payment_totals
    today = _today()
    week_end = today + timedelta(days=7)
    rows = [r for r in bill_rows(db, today) if r['owed_paise'] > 0]
    pending = pending_payment_totals(db)
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
            **payment_availability(r, pending),
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
    from .main import _form_session_id, _lock_ticket_changes
    from .tickets import add_proposal, validate_item
    seen = set()
    for ln in v.items:
        key = (ln.kind, ln.bill_id)
        if key in seen:
            raise HTTPException(422, 'Each bill can appear only once in a batch payment.')
        seen.add(key)
    base_key = (v.request_key or uuid.uuid4().hex)[:90]
    sid = f'pay-batch-{user.id}-{base_key}'
    if len(sid) > 70:
        sid = _form_session_id(user, 'bill-payment-batch', base_key)
    payload = json.dumps(v.model_dump(), sort_keys=True)
    _lock_ticket_changes(db)
    existing = db.scalar(select(ApprovalTicket).where(ApprovalTicket.session_id == sid))
    if existing:
        original = db.scalar(select(ChatMessage.content).where(ChatMessage.session_id == sid).order_by(ChatMessage.id).limit(1))
        if not original or original.rsplit('\n', 1)[-1] != payload:
            raise HTTPException(409, 'This request reference was already used for a different payment batch.')
        return {'ticket_id': existing.id, 'item_count': len(v.items),
                'total_paise': sum(i.amount_paise for i in v.items), 'state': 'pending', 'repeat': True}
    session = ChatSession(id=sid, user_id=user.id, pending=None)
    db.add(session)
    db.flush()
    source_msg = ChatMessage(session_id=sid, user_id=user.id, speaker='user',
                             content='Bulk supplier bill payment drafted in Books\n' + payload)
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
    projects = [{'id': row.id, 'name': row.name, 'company_id': row.company_id}
                for row in db.scalars(select(Project).where(Project.deleted_at.is_(None)).order_by(Project.name))]
    return {'companies': companies, 'accounts': accounts, 'projects': projects, 'today': _today().isoformat()}


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
    evidence_document_id: int | None = Field(default=None, gt=0)
    inspect_only: bool = False
    columns: dict[str, str] | None = Field(default=None, max_length=6)
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
    from .bank_feed import inspect_bank_csv, parse_bank_csv
    from .db import FinanceBankStatementLine
    from .tickets import add_proposal, validate_item
    bank = db.get(RegisteredBank, bank_id)
    if not bank:
        raise HTTPException(404, 'Bank account not found.')
    try:
        if v.inspect_only:
            return inspect_bank_csv(v.csv_text)
        if not v.evidence_document_id:
            raise ValueError('Choose the proof document for this bank statement.')
        parsed = parse_bank_csv(v.csv_text, v.columns)
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
    sess = ChatSession(id=str(uuid.uuid4()), user_id=user.id, pending=None)
    db.add(sess)
    db.flush()
    msg = ChatMessage(session_id=sess.id, user_id=user.id, speaker='user',
                      content=f'Bank CSV import for {bank.display_name}: {len(items)} new lines')
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
    from .expense_images import for_record
    if target_kind not in TARGET_MODELS:
        raise HTTPException(422, f'Unsupported target_kind: {target_kind}')
    return {'target_kind': target_kind, 'target_id': target_id,
            'attachments': list_attachments(db, target_kind, target_id),
            'receipts': for_record(db, target_kind, target_id)}


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


@router.get('/reports/pnl')
def report_pnl(entity_id: int, project_id: int | None = None, date_from: str | None = None,
               date_to: str | None = None, user: User = Depends(permit(*BOOKS_ROLES)), db: Session = Depends(get_db)):
    """M3-5: Profit & Loss statement from posted GL lines (owner & accounts only)."""
    from .financial_statements import profit_and_loss
    try:
        return profit_and_loss(db, entity_id, project_id=project_id, date_from=date_from, date_to=date_to)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.get('/reports/balance-sheet')
def report_balance_sheet(entity_id: int, as_of: str | None = None,
                         user: User = Depends(permit(*BOOKS_ROLES)), db: Session = Depends(get_db)):
    """M3-5: Balance Sheet from posted GL lines (owner & accounts only)."""
    from .financial_statements import balance_sheet
    try:
        return balance_sheet(db, entity_id, as_of=as_of)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.get('/reports/cash-flow')
def report_cash_flow(entity_id: int, date_from: str | None = None, date_to: str | None = None,
                     user: User = Depends(permit(*BOOKS_ROLES)), db: Session = Depends(get_db)):
    """M3-5: Cash Flow statement from posted bank and cash GL lines (owner & accounts only)."""
    from .financial_statements import cash_flow_statement
    try:
        return cash_flow_statement(db, entity_id, date_from=date_from, date_to=date_to)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


class RecurringEntryIn(BaseModel):
    entity_id: int
    entry_kind: str = Field(min_length=3, max_length=30)
    title: str = Field(min_length=2, max_length=120)
    cadence: str = Field(default='monthly', max_length=20)
    next_run_date: str = Field(min_length=10, max_length=10)
    payload_json: dict
    request_key: str | None = Field(default=None, max_length=120)


class AccountBudgetIn(BaseModel):
    entity_id: int
    account_id: int
    fiscal_year: str = Field(min_length=4, max_length=12)
    year_month: str = Field(min_length=7, max_length=7)
    budget_paise: int = Field(gt=0)
    note: str = Field(default='', max_length=250)
    request_key: str | None = Field(default=None, max_length=120)


@router.get('/recurring')
def list_recurring_entries(entity_id: int | None = None, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """M3-6: List approved recurring entry templates."""
    from .db import FinanceRecurringEntry
    stmt = select(FinanceRecurringEntry).where(FinanceRecurringEntry.active.is_(True)).order_by(FinanceRecurringEntry.id.desc())
    if entity_id is not None:
        stmt = stmt.where(FinanceRecurringEntry.entity_id == entity_id)
    return {'entries': [
        {'id': e.id, 'entity_id': e.entity_id, 'entry_kind': e.entry_kind, 'title': e.title,
         'cadence': e.cadence, 'next_run_date': e.next_run_date, 'payload_json': e.payload_json}
        for e in db.scalars(stmt).all()
    ]}


@router.post('/recurring')
def create_recurring_entry_draft(v: RecurringEntryIn, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """M3-6: Draft a recurring entry template for approval (never auto-posts)."""
    from .main import _manual_draft
    payload = v.model_dump(exclude={'request_key'})
    try:
        return _manual_draft(db, user, 'finance_recurring_entry', payload,
                             evidence='Recurring template drafted in Books', request_key=v.request_key)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post('/recurring/{entry_id}/generate-draft')
def generate_recurring_draft(entry_id: int, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """M3-6: Generate a DRAFT approval ticket from an approved recurring template (never posts directly)."""
    from .db import FinanceRecurringEntry
    from .main import _manual_draft
    from .recurring_budgets import ENTRY_KIND_TO_ITEM
    entry = db.get(FinanceRecurringEntry, entry_id)
    if not entry or not entry.active:
        raise HTTPException(404, 'Recurring entry not found.')
    item_type = ENTRY_KIND_TO_ITEM[entry.entry_kind]
    payload = dict(entry.payload_json or {})
    if item_type == 'finance_manual_journal' and 'idempotency_key' not in payload:
        payload['idempotency_key'] = f'rec:{entry.id}:{uuid.uuid4().hex[:12]}'
    try:
        return _manual_draft(db, user, item_type, payload,
                             evidence=f'Generated draft from recurring template: {entry.title}')
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post('/account-budgets')
def create_account_budget_draft(v: AccountBudgetIn, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """M3-6: Draft a monthly account-level budget for approval."""
    from .main import _manual_draft
    payload = v.model_dump(exclude={'request_key'})
    try:
        return _manual_draft(db, user, 'finance_account_budget', payload,
                             evidence='Monthly account budget drafted in Books', request_key=v.request_key)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get('/reports/budget-vs-actual')
def report_budget_vs_actual(entity_id: int, year_month: str,
                            user: User = Depends(permit(*BOOKS_ROLES)), db: Session = Depends(get_db)):
    """M3-6: Account-level Budget vs. Actual report from posted GL lines."""
    from .recurring_budgets import budget_vs_actual
    try:
        return budget_vs_actual(db, entity_id, year_month)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.get('/reports/trial-balance')
def report_trial_balance(entity_id: int, date_from: str | None = None, date_to: str | None = None,
                         user: User = Depends(permit(*BOOKS_ROLES)), db: Session = Depends(get_db)):
    """Trial Balance with Opening, Period, and Closing Dr/Cr from posted GL lines."""
    from .financial_statements import trial_balance_report
    try:
        return trial_balance_report(db, entity_id, date_from=date_from, date_to=date_to)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.get('/reports/project-profitability')
def report_project_profitability(entity_id: int, date_from: str | None = None, date_to: str | None = None,
                                 user: User = Depends(permit(*BOOKS_ROLES)), db: Session = Depends(get_db)):
    """Job-costing report: Revenue, COGS, Gross Profit, Operating Expenses, and Net Margin per project."""
    from .financial_statements import project_profitability
    try:
        return project_profitability(db, entity_id, date_from=date_from, date_to=date_to)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.get('/reports/ar-ageing')
def report_ar_ageing(entity_id: int, as_of: str | None = None,
                     user: User = Depends(permit(*BOOKS_ROLES)), db: Session = Depends(get_db)):
    """Accounts Receivable ageing across open client invoices."""
    from .sales_receipts import ar_ageing
    try:
        return ar_ageing(db, entity_id, as_of=as_of)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.get('/reports/gstr1')
def report_gstr1(entity_id: int, date_from: str | None = None, date_to: str | None = None,
                 user: User = Depends(permit(*BOOKS_ROLES)), db: Session = Depends(get_db)):
    """GSTR-1 outward supplies summary (B2B, B2C, Credit Notes)."""
    from .tax_engine import gstr1_summary
    try:
        return gstr1_summary(db, entity_id, date_from=date_from, date_to=date_to)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.get('/reports/gstr3b')
def report_gstr3b(entity_id: int, date_from: str | None = None, date_to: str | None = None,
                  user: User = Depends(permit(*BOOKS_ROLES)), db: Session = Depends(get_db)):
    """GSTR-3B output tax vs eligible ITC summary."""
    from .tax_engine import gstr3b_summary
    try:
        return gstr3b_summary(db, entity_id, date_from=date_from, date_to=date_to)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.get('/reports/tds-register')
def report_tds_register(entity_id: int, date_from: str | None = None, date_to: str | None = None,
                        user: User = Depends(permit(*BOOKS_ROLES)), db: Session = Depends(get_db)):
    """Section-wise and vendor-wise TDS Payable register."""
    from .tax_engine import tds_payable_register
    try:
        return tds_payable_register(db, entity_id, date_from=date_from, date_to=date_to)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.get('/reports/export.csv')
def report_export_csv(entity_id: int, kind: str, date_from: str | None = None, date_to: str | None = None,
                      as_of: str | None = None, project_id: int | None = None,
                      year_month: str | None = Query(default=None, pattern=r'^[0-9]{4}-(0[1-9]|1[0-2])$'),
                      user: User = Depends(permit(*BOOKS_ROLES)), db: Session = Depends(get_db)):
    """Export financial or tax reports as CSV for the accountant/CA."""
    from .financial_statements import (balance_sheet, cash_flow_statement, profit_and_loss, project_profitability,
                                       report_to_csv, trial_balance_report)
    from .recurring_budgets import budget_vs_actual
    from .sales_receipts import ar_ageing
    from .tax_engine import gstr1_summary, gstr3b_summary, tds_payable_register

    by_date_range = {
        'trial-balance': trial_balance_report, 'project-profitability': project_profitability,
        'cash-flow': cash_flow_statement, 'gstr1': gstr1_summary, 'gstr3b': gstr3b_summary,
        'tds': tds_payable_register, 'tds-register': tds_payable_register,
    }
    try:
        if kind == 'pnl':
            data = profit_and_loss(db, entity_id, project_id=project_id, date_from=date_from, date_to=date_to)
        elif kind == 'balance-sheet':
            data = balance_sheet(db, entity_id, as_of=as_of or date_to)
        elif kind == 'ar-ageing':
            data = ar_ageing(db, entity_id, as_of=as_of or date_to)
        elif kind == 'budget-vs-actual':
            if not year_month:
                raise HTTPException(422, 'Choose a budget month to export.')
            data = budget_vs_actual(db, entity_id, year_month)
        elif kind in by_date_range:
            data = by_date_range[kind](db, entity_id, date_from=date_from, date_to=date_to)
        else:
            raise HTTPException(422, f'Unsupported CSV export kind: {kind}')
        body = report_to_csv(kind, data)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return Response(content=body, media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="studioos-{kind}-{entity_id}.csv"'})


@router.get('/banks/{bank_id}/brs')
def bank_brs(bank_id: int, as_of: str | None = None,
             user: User = Depends(permit(*BOOKS_ROLES)), db: Session = Depends(get_db)):
    """Formal Bank Reconciliation Statement (Book Balance vs Statement Balance)."""
    from .bank_feed import bank_reconciliation_statement
    try:
        return bank_reconciliation_statement(db, bank_id, as_of=as_of)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


class DirectBillAllocateIn(BaseModel):
    bill_id: int
    source_kind: str = Field(min_length=3, max_length=20)
    source_id: int
    amount_paise: int = Field(gt=0)
    allocation_date: str = Field(min_length=10, max_length=10)
    idempotency_key: str | None = Field(default=None, max_length=120)
    request_key: str | None = Field(default=None, max_length=120)


@router.post('/bills/allocate')
def allocate_direct_bill_draft(v: DirectBillAllocateIn, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """Draft an allocation of a supplier advance or vendor credit against a direct bill."""
    from .main import _manual_draft
    payload = v.model_dump(exclude={'request_key'})
    if not payload.get('idempotency_key'):
        payload['idempotency_key'] = f'alloc:{v.bill_id}:{v.source_kind}:{v.source_id}:{uuid.uuid4().hex[:8]}'
    try:
        return _manual_draft(db, user, 'finance_allocate_direct_bill', payload,
                             evidence=f'Allocate {v.source_kind} #{v.source_id} to bill #{v.bill_id}', request_key=v.request_key)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


class OpenAccountIn(BaseModel):
    entity_id: int
    name: str = Field(min_length=2, max_length=180)
    account_type: str = Field(default='', max_length=32)
    parent_id: int | None = None
    code: str | None = Field(default=None, max_length=30)
    description: str = Field(default='', max_length=300)
    is_group: bool = False
    masked_identifier: str | None = Field(default=None, max_length=40)
    request_key: str | None = Field(default=None, max_length=120)


class UpdateAccountIn(BaseModel):
    entity_id: int
    account_id: int
    parent_id: int | None = None
    account_type: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=300)
    is_active: bool | None = None
    why: str = Field(default='', max_length=400)
    request_key: str | None = Field(default=None, max_length=120)


@router.post('/accounts')
def open_account_draft(v: OpenAccountIn, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """Draft a new Zoho-style account, sub-account, group, bank account, or credit card."""
    from .main import _manual_draft
    try:
        if v.account_type == 'bank' and not v.is_group:
            payload = {
                'entity_id': v.entity_id, 'name': v.name,
                'masked_identifier': v.masked_identifier or '',
                'code': v.code, 'parent_id': v.parent_id, 'description': v.description,
            }
            payload = {k: val for k, val in payload.items() if val is not None}
            return _manual_draft(db, user, 'finance_open_bank_account', payload,
                                 evidence=f'Open bank account {v.name}', request_key=v.request_key)
        payload = {
            'entity_id': v.entity_id, 'name': v.name, 'account_type': v.account_type,
            'parent_id': v.parent_id, 'code': v.code, 'description': v.description, 'is_group': v.is_group,
        }
        payload = {k: val for k, val in payload.items() if val is not None}
        return _manual_draft(db, user, 'finance_open_account', payload,
                             evidence=f'Open account {v.name} ({v.account_type or "sub-account"})', request_key=v.request_key)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post('/accounts/update')
def update_account_draft(v: UpdateAccountIn, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """Draft an account update (reparent, change account type, edit description, or archive)."""
    from .main import _manual_draft
    payload = v.model_dump(exclude={'request_key'}, exclude_unset=True)
    try:
        return _manual_draft(db, user, 'finance_update_account', payload,
                             evidence=f'Update account #{v.account_id}', request_key=v.request_key)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


class ZohoPartyIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    phone: str = Field(default='', max_length=20)
    email: str = Field(default='', max_length=120)
    gst_treatment: str = Field(default='unregistered', max_length=30)
    gstin: str = Field(default='', max_length=15)
    pan: str = Field(default='', max_length=10)
    state_code: str = Field(default='', max_length=2)
    billing_address: str = Field(default='', max_length=300)
    shipping_address: str = Field(default='', max_length=300)
    payment_terms_days: int = Field(default=30, ge=0, le=365)
    default_tds_section: str = Field(default='', max_length=16)
    bank_account_name: str = Field(default='', max_length=120)
    bank_ifsc: str = Field(default='', max_length=11)
    bank_masked_number: str = Field(default='', max_length=40)
    trade: str = Field(default='', max_length=120)
    request_key: str | None = Field(default=None, max_length=120)


@router.post('/vendors')
def create_vendor_draft(v: ZohoPartyIn, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """Draft a new Zoho-style vendor profile with GST treatment, PAN, TDS section, and bank details."""
    from .main import _manual_draft
    payload = v.model_dump(exclude={'request_key'})
    try:
        return _manual_draft(db, user, 'create_vendor', payload,
                             evidence=f'New vendor {v.name} drafted in Books', request_key=v.request_key)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post('/clients')
def create_client_draft(v: ZohoPartyIn, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """Draft a new Zoho-style client profile with GST treatment, PAN, billing address, and payment terms."""
    from .main import _manual_draft
    payload = v.model_dump(exclude={'request_key', 'default_tds_section', 'bank_account_name', 'bank_ifsc', 'bank_masked_number'})
    try:
        return _manual_draft(db, user, 'create_client', payload,
                             evidence=f'New client {v.name} drafted in Books', request_key=v.request_key)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get('/purchase-orders/{po_id}/pdf')
def purchase_order_pdf(po_id: int, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """Download an A4 Purchase Order PDF for an approved PO."""
    import re
    from .access import require_project_access
    from .purchase_pdfs import render_purchase_order_pdf
    po = db.get(FinancePurchaseOrder, po_id)
    if po is None:
        raise HTTPException(404, 'Purchase order not found.')
    require_project_access(db, user, po.project_id)
    try:
        pdf = render_purchase_order_pdf(db, po_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    safe_no = re.sub(r'[^A-Za-z0-9._-]+', '_', po.po_number or str(po.id))[:80]
    return Response(content=pdf, media_type='application/pdf',
                    headers={'Content-Disposition': f'inline; filename="po-{safe_no}.pdf"'})


@router.get('/bills/{bill_id}/pdf')
def supplier_bill_pdf(bill_id: int, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """Download an A4 Supplier Bill PDF with GST and TDS breakdown."""
    import re
    from .purchase_pdfs import render_supplier_bill_pdf
    bill = db.get(FinanceDirectBill, bill_id)
    if bill is None or not bill.journal_id:
        raise HTTPException(404, 'Posted supplier bill not found.')
    allowed = visible_project_ids(db, user)
    if allowed is not None:
        pids = [p for p in db.scalars(select(FinanceDirectBillLine.project_id).where(FinanceDirectBillLine.bill_id == bill.id)).all() if p is not None]
        if any(p not in allowed for p in pids):
            raise HTTPException(403, 'You do not have access to a project on this bill.')
    try:
        pdf = render_supplier_bill_pdf(db, bill_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    safe_no = re.sub(r'[^A-Za-z0-9._-]+', '_', bill.invoice_number or str(bill.id))[:80]
    return Response(content=pdf, media_type='application/pdf',
                    headers={'Content-Disposition': f'inline; filename="bill-{safe_no}.pdf"'})


@router.get('/payments/{payment_id}/pdf')
def payment_voucher_pdf(payment_id: int, kind: str = 'direct',
                        user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """Download an A4 Payment Voucher / Remittance Advice PDF."""
    from .purchase_pdfs import render_payment_voucher_pdf
    if kind not in ('direct', 'po'):
        raise HTTPException(422, 'Payment kind must be direct or po.')
    allowed = visible_project_ids(db, user)
    if allowed is not None:
        if kind == 'direct':
            pay = db.get(FinanceDirectBillPayment, payment_id)
            if pay is None or not pay.journal_id:
                raise HTTPException(404, 'Posted direct bill payment not found.')
            pids = [p for p in db.scalars(select(FinanceDirectBillLine.project_id).where(FinanceDirectBillLine.bill_id == pay.bill_id)).all() if p is not None]
            if any(p not in allowed for p in pids):
                raise HTTPException(403, 'You do not have access to a project on this payment.')
        else:
            pay = db.get(FinanceSupplierPayment, payment_id) or db.get(FinanceSupplierCashPayment, payment_id)
            if pay is None or not pay.journal_id:
                raise HTTPException(404, 'Posted supplier payment not found.')
            bill = db.get(FinanceSupplierBill, pay.bill_id)
            po = db.get(FinancePurchaseOrder, bill.po_id) if bill else None
            if po and po.project_id not in allowed:
                raise HTTPException(403, 'You do not have access to the project on this payment.')
    try:
        pdf = render_payment_voucher_pdf(db, payment_id, kind=kind)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return Response(content=pdf, media_type='application/pdf',
                    headers={'Content-Disposition': f'inline; filename="payment-voucher-{payment_id}.pdf"'})


@router.get('/projects/{project_id}/accounting')
def project_accounting(project_id: int, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """Relational project accounting view: linked company/client, budget vs actuals, POs, bills, invoices, and P&L."""
    from .access import require_project_access
    from .financial_statements import project_accounting_summary
    proj = db.get(Project, project_id)
    if proj is None or proj.deleted_at:
        raise HTTPException(404, 'Project not found.')
    require_project_access(db, user, proj.id)
    try:
        return project_accounting_summary(db, proj.id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))

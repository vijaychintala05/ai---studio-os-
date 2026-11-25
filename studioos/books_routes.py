"""Books home and the Party page (App Flows map). Read-only views of what the books hold.
- Books home (owner and accounts): per company, what is owed to suppliers, how old the unpaid bills are, the bank accounts and their
  balances from the ledger, the months already closed and the supplier payments not yet matched to the bank statement.
- Party page: one vendor or client. Contact details for roles that may see contacts; amounts (bills, payments, what is owed) only for
  owner, accounts and manager. Architects see the contact and the projects only, site staff see nothing.
Bill ageing uses the ledger posting date. Older bills and payments may have an unknown document date. Money is whole paise."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from .access import visible_project_ids
from .accounting_kernel import BILL_DATE_FIELDS
from .db import (AccountingEntity, ClosedAccountingPeriod, Document, FinanceAdvanceAllocation, FinanceBankReconciliation,
                 FinanceCashAdvanceAllocation, FinanceDirectBill, FinanceDirectBillLine, GLAccount,
                 FinancePurchaseOrder, FinanceReversal, FinanceSupplierBill, FinanceSupplierCashPayment, FinanceSupplierPayment,
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
    # Include posted direct multi-line bills (M2-1).
    dstmt = select(FinanceDirectBill, GLJournal.posted_at, _reversed(FinanceDirectBill.journal_id)).outerjoin(
        GLJournal, GLJournal.id == FinanceDirectBill.journal_id
    ).order_by(FinanceDirectBill.id)
    if entity_id is not None:
        dstmt = dstmt.where(FinanceDirectBill.entity_id == entity_id)
    if supplier_id is not None:
        dstmt = dstmt.where(FinanceDirectBill.supplier_id == supplier_id)
    if allowed_projects is not None:
        dstmt = dstmt.where(FinanceDirectBill.id.in_(select(FinanceDirectBillLine.bill_id).where(
            FinanceDirectBillLine.project_id.in_(allowed_projects))))
    for b, posted_at, reversed_bill in db.execute(dstmt):
        owed = 0 if reversed_bill else b.amount_paise
        age = max(0, (today - posted_at.date()).days) if posted_at else 0
        out.append({'id': b.id, 'direct_bill': True, 'entity_id': b.entity_id, 'supplier_id': b.supplier_id,
                    'po_id': None, 'invoice_number': b.invoice_number,
                    **{field: getattr(b, field) for field in BILL_DATE_FIELDS},
                    'amount_paise': b.amount_paise, 'paid_paise': 0, 'owed_paise': owed, 'age_days': age})
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
        payment = FinanceSupplierPayment
        cash = FinanceSupplierCashPayment
        bank_payments = db.execute(select(payment, _matched()).where(
            payment.bill_id.in_(bill_ids), ~_reversed(payment.journal_id)
        ).order_by(payment.journal_id.desc()).limit(20)).all()
        cash_payments = db.scalars(select(cash).where(
            cash.bill_id.in_(bill_ids), ~_reversed(cash.journal_id)
        ).order_by(cash.journal_id.desc()).limit(20)).all()
        pay = [(p, matched, 'bank') for p, matched in bank_payments]
        pay.extend((p, False, 'cash') for p in cash_payments)
        pay.sort(key=lambda row: row[0].journal_id or 0, reverse=True)
        pos = [p for p in pos if allowed is None or p.project_id in allowed]
        out.update({'bills': [{k: r[k] for k in ('id', 'invoice_number', 'amount_paise', 'paid_paise', 'owed_paise', 'age_days', *BILL_DATE_FIELDS)} for r in rows],
                    'payments': [{'id': p.id, 'bill_id': p.bill_id, 'amount_paise': p.amount_paise, 'reference': p.payment_reference, 'payment_date': p.payment_date, 'matched': matched, 'kind': kind} for p, matched, kind in pay[:20]],
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

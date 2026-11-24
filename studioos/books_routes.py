"""Books home and the Party page (App Flows map). Read-only views of what the books hold.
- Books home (owner and accounts): per company, what is owed to suppliers, how old the unpaid bills are, the bank accounts and their
  balances from the ledger, the months already closed and the supplier payments not yet matched to the bank statement.
- Party page: one vendor or client. Contact details for roles that may see contacts; amounts (bills, payments, what is owed) only for
  owner, accounts and manager. Architects see the contact and the projects only, site staff see nothing.
Bill ageing uses the ledger posting date. Older bills and payments may have an unknown document date. Money is whole paise."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .access import visible_project_ids
from .accounting_kernel import BILL_DATE_FIELDS
from .db import (AccountingEntity, ClosedAccountingPeriod, FinanceAdvanceAllocation, FinanceBankReconciliation, FinanceCashAdvanceAllocation,
                 FinancePurchaseOrder, FinanceReversal, FinanceSupplierBill, FinanceSupplierCashPayment, FinanceSupplierPayment,
                 GLJournal, GLLine, Party, Project, RegisteredBank, User)
from .deps import get_db
from .legacy_payables import open_legacy_payables
from .party_access import visible_party_ids
from .security import current_user, permit

router = APIRouter(prefix='/api/books', tags=['Books'])

BOOKS_ROLES = ('admin', 'accounts')
AMOUNT_ROLES = ('admin', 'accounts', 'manager')
CONTACT_ROLES = ('admin', 'accounts', 'manager', 'architect')
AGEING = (('current', 0, 30), ('days_31_60', 31, 60), ('days_61_90', 61, 90), ('over_90', 91, 10 ** 6))


def _today():
    from . import universal_engine as u
    return u._today()


def _reversed(journal_id):
    return select(FinanceReversal.id).where(FinanceReversal.original_journal_id == journal_id).exists()


def _matched():
    return select(FinanceBankReconciliation.id).where(
        FinanceBankReconciliation.journal_id == FinanceSupplierPayment.journal_id
    ).exists()


def unmatched_payments(entity_id=None):
    payment = FinanceSupplierPayment
    stmt = select(payment).where(payment.journal_id.is_not(None), ~_reversed(payment.journal_id), ~_matched())
    if entity_id is not None:
        stmt = stmt.join(FinanceSupplierBill).where(FinanceSupplierBill.entity_id == entity_id)
    return stmt


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


def _legacy_rows(db, today, **scope):
    return [{**row, 'owed_paise': row['outstanding_paise'],
             'age_days': max(0, (today - date.fromisoformat(row['posted_date'])).days)}
            for row in open_legacy_payables(db, **scope)]


@router.get('/home')
def books_home(user: User = Depends(permit(*BOOKS_ROLES)), db: Session = Depends(get_db)):
    today = _today()
    companies = []
    for ent in db.scalars(select(AccountingEntity).order_by(AccountingEntity.id)):
        bills = bill_rows(db, today, ent.id)
        historical = _legacy_rows(db, today, entity_id=ent.id)
        rows = bills + historical
        banks = []
        for b in db.scalars(select(RegisteredBank).where(RegisteredBank.entity_id == ent.id).order_by(RegisteredBank.id)):
            lines = db.scalars(select(GLLine).join(GLJournal, GLJournal.id == GLLine.journal_id).where(GLLine.account_id == b.gl_account_id, GLJournal.status == 'posted')).all()
            banks.append({'id': b.id, 'name': b.display_name, 'masked': b.masked_identifier,
                          'balance_paise': sum(l.amount_paise if l.side == 'debit' else -l.amount_paise for l in lines)})
        closed = db.scalars(select(ClosedAccountingPeriod.year_month).where(ClosedAccountingPeriod.entity_id == ent.id).order_by(ClosedAccountingPeriod.year_month.desc()).limit(6)).all()
        unmatched = db.scalars(unmatched_payments(ent.id)).all()
        by_supplier = {}
        for r in rows:
            if r['owed_paise'] > 0:
                by_supplier[r['supplier_id']] = by_supplier.get(r['supplier_id'], 0) + r['owed_paise']
        names = {p.id: p.name for p in db.scalars(select(Party).where(Party.id.in_(list(by_supplier) or [-1])))}
        companies.append({'entity_id': ent.id, 'name': ent.name, 'payable_paise': sum(r['owed_paise'] for r in rows), 'open_bills': sum(1 for r in bills if r['owed_paise'] > 0),
                          'open_legacy_payables': len(historical),
                          'ageing': ageing(rows), 'banks': banks, 'closed_months': list(closed),
                          'unmatched_payments': {'count': len(unmatched), 'paise': sum(p.amount_paise for p in unmatched)},
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
        historical = _legacy_rows(db, today, supplier_id=party_id, allowed_projects=allowed)
        balances = rows + historical
        bill_ids = [bill['id'] for bill in rows]
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
                    'ageing': ageing(balances), 'orders': [{'id': p.id, 'po_number': p.po_number, 'amount_paise': p.amount_paise} for p in pos[-10:]]})
    return out

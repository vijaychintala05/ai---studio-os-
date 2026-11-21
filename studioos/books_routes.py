"""Books home and the Party page (App Flows map). Read-only views of what the books hold.
- Books home (owner and accounts): per company, what is owed to suppliers, how old the unpaid bills are, the bank accounts and their
  balances from the ledger, the months already closed and the supplier payments not yet matched to the bank statement.
- Party page: one vendor or client. Contact details for roles that may see contacts; amounts (bills, payments, what is owed) only for
  owner, accounts and manager. Architects see the contact and the projects only, site staff see nothing.
Bills carry no date of their own, so a bill's age is counted from when it was posted to the ledger. Money is whole paise."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import visible_project_ids
from .db import (AccountingEntity, ClosedAccountingPeriod, FinancePurchaseOrder, FinanceSupplierBill, FinanceSupplierPayment, GLAccount,
                 GLJournal, GLLine, Party, Project, RegisteredBank, User)
from .deps import get_db
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


def _age_days(db, journal_id, today):
    j = db.get(GLJournal, journal_id) if journal_id else None
    if not j or not j.posted_at:
        return 0
    return max(0, (today - j.posted_at.date()).days)


def bill_rows(db, today, entity_id=None, supplier_id=None):
    """Every bill with what has been paid and what is still owed, and how old it is."""
    stmt = select(FinanceSupplierBill).order_by(FinanceSupplierBill.id)
    if entity_id is not None:
        stmt = stmt.where(FinanceSupplierBill.entity_id == entity_id)
    if supplier_id is not None:
        stmt = stmt.where(FinanceSupplierBill.supplier_id == supplier_id)
    paid = {}
    for p in db.scalars(select(FinanceSupplierPayment)):
        paid[p.bill_id] = paid.get(p.bill_id, 0) + p.amount_paise
    out = []
    for b in db.scalars(stmt):
        owed = b.amount_paise - paid.get(b.id, 0)
        out.append({'id': b.id, 'entity_id': b.entity_id, 'supplier_id': b.supplier_id, 'po_id': b.po_id, 'invoice_number': b.invoice_number,
                    'amount_paise': b.amount_paise, 'paid_paise': paid.get(b.id, 0), 'owed_paise': owed, 'age_days': _age_days(db, b.journal_id, today)})
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
    companies = []
    for ent in db.scalars(select(AccountingEntity).order_by(AccountingEntity.id)):
        rows = bill_rows(db, today, ent.id)
        banks = []
        for b in db.scalars(select(RegisteredBank).where(RegisteredBank.entity_id == ent.id).order_by(RegisteredBank.id)):
            lines = db.scalars(select(GLLine).join(GLJournal, GLJournal.id == GLLine.journal_id).where(GLLine.account_id == b.gl_account_id, GLJournal.status == 'posted')).all()
            banks.append({'id': b.id, 'name': b.display_name, 'masked': b.masked_identifier,
                          'balance_paise': sum(l.amount_paise if l.side == 'debit' else -l.amount_paise for l in lines)})
        closed = db.scalars(select(ClosedAccountingPeriod.year_month).where(ClosedAccountingPeriod.entity_id == ent.id).order_by(ClosedAccountingPeriod.year_month.desc()).limit(6)).all()
        unmatched = db.scalars(select(FinanceSupplierPayment).join(FinanceSupplierBill, FinanceSupplierBill.id == FinanceSupplierPayment.bill_id)
                               .where(FinanceSupplierBill.entity_id == ent.id, FinanceSupplierPayment.bank_reconciled.is_(False))).all()
        by_supplier = {}
        for r in rows:
            if r['owed_paise'] > 0:
                by_supplier[r['supplier_id']] = by_supplier.get(r['supplier_id'], 0) + r['owed_paise']
        names = {p.id: p.name for p in db.scalars(select(Party).where(Party.id.in_(list(by_supplier) or [-1])))}
        companies.append({'entity_id': ent.id, 'name': ent.name, 'payable_paise': sum(r['owed_paise'] for r in rows), 'open_bills': sum(1 for r in rows if r['owed_paise'] > 0),
                          'ageing': ageing(rows), 'banks': banks, 'closed_months': list(closed),
                          'unmatched_payments': {'count': len(unmatched), 'paise': sum(p.amount_paise for p in unmatched)},
                          'owed_by_supplier': sorted(({'party_id': k, 'name': names.get(k, ''), 'owed_paise': v} for k, v in by_supplier.items()), key=lambda x: -x['owed_paise'])[:10]})
    return {'date': today.isoformat(), 'companies': companies, 'note': 'A bill is aged from the day it was posted to the ledger.'}


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
        rows = bill_rows(db, today, supplier_id=party_id)
        pay = [p for p in db.scalars(select(FinanceSupplierPayment).order_by(FinanceSupplierPayment.id.desc())) if p.bill_id in {r['id'] for r in rows}]
        out.update({'bills': [{k: r[k] for k in ('id', 'invoice_number', 'amount_paise', 'paid_paise', 'owed_paise', 'age_days')} for r in rows],
                    'payments': [{'id': p.id, 'bill_id': p.bill_id, 'amount_paise': p.amount_paise, 'reference': p.payment_reference, 'matched': p.bank_reconciled} for p in pay[:20]],
                    'owed_paise': sum(r['owed_paise'] for r in rows), 'ageing': ageing(rows), 'orders': [{'id': p.id, 'po_number': p.po_number, 'amount_paise': p.amount_paise} for p in pos[-10:]]})
    return out

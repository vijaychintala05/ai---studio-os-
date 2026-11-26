"""Read-only Phase-6 financial assurance for the existing protected StudioOS ledger.

The posted journal lines remain the single source of financial truth.  This module
neither posts entries nor attempts to infer missing COA/accounting policies.  All
money is integer INR paise; all findings cite immutable journal/source IDs.

This is an assurance and reporting layer, NOT a substitute for PostgreSQL
concurrency tests, independent accounting review, or immutable DB-level gates.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import case,func,or_,select
from sqlalchemy.orm import Session

from .db import (AccountingEntity, AccountingPolicy, FinanceAdvanceAllocation, FinanceDirectBill,
                 FinanceSupplierBill, FinanceSupplierPayment, FinanceReversal,
                 GLAccount, GLJournal, GLLine, FinanceSupplierAdvance,
                 FinanceGoodsReceipt, FinanceMaterialIssue, FinancePurchaseOrder,
                 FinanceInventoryPolicy, RegisteredBank, FinanceBankReconciliation,
                 FinanceBankStatementLine, ApprovalTicket)

MAX_AUDIT_JOURNALS = 10_000
MAX_AUDIT_LINES = 25_000
MAX_GL_ROWS = 5_000


def _entity(db: Session, entity_id: int) -> AccountingEntity:
    entity = db.get(AccountingEntity, entity_id)
    if not entity:
        raise ValueError('Accounting legal entity not found')
    if entity.base_currency != 'INR':
        raise ValueError('Only explicit INR base-currency financial assurance is supported')
    return entity


def _date(value: str | None, label: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError(f'{label} must be YYYY-MM-DD')
    try:
        day = date.fromisoformat(value)
        if day.isoformat() != value:
            raise ValueError()
        return day
    except ValueError:
        raise ValueError(f'{label} must be a valid YYYY-MM-DD date') from None


def _date_window(start_date: str | None, end_date: str | None):
    first = _date(start_date, 'start_date')
    last = _date(end_date, 'end_date')
    if first and last and first > last:
        raise ValueError('start_date cannot be after end_date')
    if first and last and (last-first).days > 3660:
        raise ValueError('Maximum report period is 10 years')
    return first, last


def _day(posted_at):
    # SQLite may return a naive datetime for a SQLAlchemy timezone-aware column.
    # Legacy records were written as UTC; do not apply a machine-local offset.
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=timezone.utc)
    return posted_at.astimezone(timezone.utc).date()


def assert_posted_journal_balances(db: Session, entity_id: int) -> None:
    """Posting/period-close fail-closed guard against already corrupt GL history.

    This checks existing posted history, not a partially constructed new bill.
    It does NOT replace the database-level transactional/concurrency release gate.
    """
    if not db.get(AccountingEntity, entity_id):
        raise ValueError('Accounting legal entity not found')
    bounded=select(GLJournal.id).where(GLJournal.entity_id==entity_id,
              GLJournal.status=='posted').limit(MAX_AUDIT_JOURNALS+1).subquery()
    count=db.scalar(select(func.count()).select_from(bounded))
    if count>MAX_AUDIT_JOURNALS:
        raise ValueError('Posting blocked: historical journal count exceeds safety cap')
    if not count:
        return
    # Evaluate EVERY posted journal, but return only a violation. Transferring
    # every healthy journal/side to Python for every new entry grows with history.
    debit=func.coalesce(func.sum(case((GLLine.side=='debit',GLLine.amount_paise),else_=0)),0)
    credit=func.coalesce(func.sum(case((GLLine.side=='credit',GLLine.amount_paise),else_=0)),0)
    invalid=func.sum(case((or_(GLLine.side.is_(None),GLLine.side.not_in(('debit','credit'))),1),else_=0))
    broken=db.execute(select(GLJournal.id,invalid.label('invalid_sides'))
        .outerjoin(GLLine,GLLine.journal_id==GLJournal.id)
        .where(GLJournal.entity_id==entity_id,GLJournal.status=='posted')
        .group_by(GLJournal.id)
        .having(or_(invalid>0,func.count(GLLine.id)<2,debit<=0,debit!=credit))
        .order_by(invalid.desc(),GLJournal.id).limit(1)).first()
    if broken:
        journal_id,invalid_sides=broken
        if invalid_sides:
            raise ValueError(f'Posting blocked: invalid journal line side in journal {journal_id}')
        raise ValueError(f'Posting blocked: existing journal {journal_id} is unbalanced or incomplete')


def general_ledger(db: Session, entity_id: int, account_id: int,
                   start_date: str | None = None, end_date: str | None = None) -> dict:
    """Journal-line-level trace with exact opening, period, and closing balances.

    Fail closed rather than silently truncate or display an incorrect opening
    balance. A paginated index-based GL is a future extension for larger books.
    """
    _entity(db, entity_id)
    account = db.get(GLAccount, account_id)
    if not account or account.entity_id != entity_id:
        raise ValueError('GL account not found in this legal entity')
    first, last = _date_window(start_date, end_date)
    stmt = (select(GLLine, GLJournal)
            .join(GLJournal, GLLine.journal_id == GLJournal.id)
            .where(GLJournal.entity_id == entity_id, GLJournal.status == 'posted',
                   GLLine.account_id == account_id)
            .order_by(GLJournal.posted_at, GLJournal.id, GLLine.id)
            .limit(MAX_GL_ROWS+1))
    rows = db.execute(stmt).all()
    if len(rows) > MAX_GL_ROWS:
        raise ValueError('Ledger exceeds bounded report size; use an approved indexed export')
    opening = 0
    period_debit = 0
    period_credit = 0
    entries = []
    running = 0
    for line, journal in rows:
        if type(line.amount_paise) is not int or line.amount_paise <= 0 or line.side not in ('debit','credit'):
            raise ValueError(f'Corrupt amount/side in posted journal {journal.id}; report blocked')
        impact = line.amount_paise if line.side == 'debit' else -line.amount_paise
        day = _day(journal.posted_at)
        if first and day < first:
            opening += impact
            continue
        if last and day > last:
            continue
        if line.side == 'debit':
            period_debit += line.amount_paise
        else:
            period_credit += line.amount_paise
        running += impact
        entries.append({'journal_id':journal.id,'line_id':line.id,
            'posted_date_utc':day.isoformat(),'event_key':journal.event_key,
            'source_event':journal.source_event,'source_id':journal.source_id,
            'ticket_id':journal.ticket_id,'policy_version':journal.policy_version,
            'project_id':line.project_id,'supplier_id':line.supplier_id,
            'side':line.side,'amount_paise':line.amount_paise,
            'running_balance_paise':opening + running})
    return {'entity_id':entity_id,'account_id':account.id,'account_code':account.code,
        'account_name':account.name,'account_kind':account.kind,'currency':'INR',
        'start_date':start_date,'end_date':end_date,
        'opening_signed_debit_paise':opening,'debit_paise':period_debit,
        'credit_paise':period_credit,
        'closing_signed_debit_paise':opening+period_debit-period_credit,
        'entries':entries,'truncated':False,
        'basis':'Posted GL lines only, UTC accounting/posting date, exact integer paise; positive balance means debit. Not a bank statement.'}


def ledger_integrity(db: Session, entity_id: int) -> dict:
    """Fail-closed journal/subledger diagnostic, with exact affected IDs.

    This MUST NOT return PASS on partial datasets. Direct SQL insertion by a DB
    superuser is outside the application approval boundary; this check detects
    certain kinds of tampering but cannot make privileged DB writes impossible.
    """
    _entity(db, entity_id)
    journals = db.scalars(select(GLJournal).where(GLJournal.entity_id==entity_id)
                          .order_by(GLJournal.id).limit(MAX_AUDIT_JOURNALS+1)).all()
    if len(journals)>MAX_AUDIT_JOURNALS:
        raise ValueError('Audit journal volume exceeds bounded scope; cannot certify completeness')
    lines = db.execute(select(GLLine,GLAccount,GLJournal)
        .join(GLJournal, GLLine.journal_id==GLJournal.id)
        .outerjoin(GLAccount, GLLine.account_id==GLAccount.id)
        .where(GLJournal.entity_id==entity_id)
        .order_by(GLLine.id).limit(MAX_AUDIT_LINES+1)).all()
    if len(lines)>MAX_AUDIT_LINES:
        raise ValueError('Audit line volume exceeds bounded scope; cannot certify completeness')
    problems=[]
    def problem(code, message, **refs):
        problems.append({'code':code,'message':message,**refs})
    by_journal=defaultdict(list)
    account_net=defaultdict(int)
    for line, account, journal in lines:
        by_journal[journal.id].append(line)
        if account is None or account.entity_id != entity_id:
            problem('CROSS_ENTITY_OR_MISSING_ACCOUNT','Line does not reference an account in the legal entity',journal_id=journal.id,line_id=line.id)
        if line.side not in ('debit','credit') or type(line.amount_paise) is not int or line.amount_paise<=0:
            problem('INVALID_JOURNAL_LINE','Posted line has an invalid side or exact-positive amount',journal_id=journal.id,line_id=line.id)
            continue
        account_net[line.account_id]+=(line.amount_paise if line.side=='debit' else -line.amount_paise)
    for journal in journals:
        group=by_journal.get(journal.id,[])
        debit=sum(x.amount_paise for x in group if x.side=='debit' and type(x.amount_paise) is int)
        credit=sum(x.amount_paise for x in group if x.side=='credit' and type(x.amount_paise) is int)
        if journal.status!='posted':
            problem('UNKNOWN_JOURNAL_STATUS','Journal is not in supported posted state',journal_id=journal.id)
        if len(group)<2 or debit<=0 or debit!=credit:
            problem('UNBALANCED_JOURNAL','Journal missing lines or debits differ from credits',journal_id=journal.id,debit_paise=debit,credit_paise=credit)
        if not journal.ticket_id or not db.get(ApprovalTicket,journal.ticket_id):
            problem('MISSING_APPROVAL_PROVENANCE','Posted journal has no valid approval ticket',journal_id=journal.id)
        if not journal.event_key or not journal.source_event or journal.source_id is None or (not isinstance(journal.policy_version,int) or journal.policy_version<1):
            problem('MISSING_SOURCE_PROVENANCE','Journal is missing source event, key, ID or policy version',journal_id=journal.id)
    policy=db.scalar(select(AccountingPolicy).where(AccountingPolicy.entity_id==entity_id))
    ap_balance=None
    ap_expected=None
    if policy is None:
        if journals:
            problem('MISSING_ACCOUNTING_POLICY','Posted journals exist without an approved accounting policy')
    else:
        ap=db.get(GLAccount,policy.payable_account_id)
        if ap is None or ap.entity_id!=entity_id or ap.kind!='payable':
            problem('INVALID_PAYABLE_CONTROL','AP control account is missing or cross-entity')
        else:
            ap_balance=-account_net[ap.id]
            bills=db.scalars(select(FinanceSupplierBill).where(FinanceSupplierBill.entity_id==entity_id)).all()
            from .accounting_kernel import outstanding
            from .direct_bills import direct_bill_outstanding
            direct_ids = db.scalars(select(FinanceDirectBill.id).where(FinanceDirectBill.entity_id == entity_id))
            ap_expected=(sum(outstanding(db,b.id) for b in bills)
                         + sum(direct_bill_outstanding(db, bill_id) for bill_id in direct_ids))
            if ap_expected!=ap_balance:
                problem('AP_CONTROL_MISMATCH','Supplier open balances do not reconcile to posted AP control account',
                        gl_credit_balance_paise=ap_balance,supplier_outstanding_paise=ap_expected)
    # Bank-book balances must derive from journal lines, not statement imports.
    banks=[]
    for bank in db.scalars(select(RegisteredBank).where(RegisteredBank.entity_id==entity_id).order_by(RegisteredBank.id)):
        gl=db.get(GLAccount,bank.gl_account_id)
        if gl is None or gl.entity_id!=entity_id or gl.kind!='bank':
            problem('INVALID_BANK_MAPPING','Bank mapping is not an eligible same-entity bank GL account',bank_id=bank.id)
        banks.append({'bank_id':bank.id,'masked_identifier':bank.masked_identifier,
                      'bank_book_signed_debit_paise':account_net[bank.gl_account_id],
                      'statement_reconciliation_is_separate':True})
    total_debit=sum(l.amount_paise for l,a,j in lines if l.side=='debit' and type(l.amount_paise) is int)
    total_credit=sum(l.amount_paise for l,a,j in lines if l.side=='credit' and type(l.amount_paise) is int)
    if total_debit!=total_credit:
        problem('ENTITY_UNBALANCED','Legal entity posted journal lines are not balanced',
                total_debit_paise=total_debit,total_credit_paise=total_credit)
    return {'entity_id':entity_id,'currency':'INR','passed':not problems,'status':'PASS' if not problems else 'FAIL',
            'journal_count':len(journals),'line_count':len(lines),
            'total_debit_paise':total_debit,'total_credit_paise':total_credit,
            'ap_control_credit_paise':ap_balance,'supplier_outstanding_paise':ap_expected,
            'banks':banks,'findings':problems,'truncated':False,
            'scope':'Integrity of bounded existing INR posted GL and supplier AP; not an audit opinion, not a GST compliance certificate, not a PostgreSQL concurrency guarantee.',
            'unsupported':['AR/customer subledgers','revenue/equity','full P&L/balance sheet',
                           'cross-currency','statutory GST/TDS']}

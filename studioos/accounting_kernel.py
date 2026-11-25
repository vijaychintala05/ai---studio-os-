"""Protected INR-only deterministic invoice-led GL.

POs are commitments only. An approved full-match supplier bill posts Dr Expense/Cr AP;
an approved payment posts Dr AP/Cr Bank or Cash. This deliberately refuses advanced,
inventory, tax, FX, GRNI and partial-bill flows until safe implementations exist.
No LLM creates journal lines, mapping, postings or approvals.
"""
from __future__ import annotations
from datetime import datetime, timezone, date
import re
import os
import hashlib
from pathlib import Path
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from .db import (AccountingEntity, GLAccount, AccountingPolicy, RegisteredBank,
    FinancePettyCashAccount, FinanceExpense, FinanceProjectCompany, FinanceStaffReimbursement, User,
    FinancePurchaseOrder, FinanceSupplierBill, FinanceSupplierCashPayment, FinanceSupplierPayment, GLJournal,
    GLLine, ClosedAccountingPeriod, FinanceReversal, FinanceAdvancePolicy,
    FinanceSupplierAdvance, FinanceSupplierCashAdvance, FinanceAdvanceAllocation, FinanceCashAdvanceAllocation,
    FinanceInventoryPolicy, FinanceGoodsReceipt, FinanceMaterialIssue, FinanceBankStatementLine, FinanceBankReconciliation, Document, Project, Party, add_audit, now)
from .paid_through import CASH_CODE, CASH_NAME, expense_source, petty_cash_custodian
from .expense_entry import EXPENSE_EVENT
from .staff_reimbursements import PAYMENT_EVENT as STAFF_PAYMENT_EVENT
from .legacy_payables import (PAYMENT_EVENT as LEGACY_BALANCE_PAYMENT_EVENT, PAYMENT_FIELDS as LEGACY_BALANCE_PAYMENT_FIELDS,
                              reference_used as legacy_reference_used)

_BANK_REVIEW_TYPES={'finance_bank_statement_line','finance_reconcile_bank'}
BILL_DATE_FIELDS = ('bill_date', 'due_date', 'payment_terms_days')
PAYMENT_DATE_FIELDS = ('payment_date',)
SUPPLIER_CASH_PAYMENT_EVENT = 'SUPPLIER_CASH_PAYMENT_POSTED'
SUPPLIER_CASH_ADVANCE_EVENT = 'SUPPLIER_CASH_ADVANCE_PAID'
ADVANCE_ALLOCATIONS = (FinanceAdvanceAllocation, FinanceCashAdvanceAllocation)

# Entries resolve IDs through their normal approval or policy before this check.
_MONEY_LINK_KINDS = {
    'finance_bill': (('payable',), ('expense',)),
    'finance_direct_bill': (('payable',), ('expense',)),
    'finance_direct_bill_payment': (('bank', 'cash'), ('payable',)),
    'finance_inventory_bill': (('payable',), ('grni',)),
    'finance_payment': (('bank', 'cash'), ('payable',)),
    'finance_expense': (('bank', 'cash'), ('expense',)),
    'finance_staff_claim': (('liability',), ('expense',)),
    'finance_reimburse_staff': (('bank', 'cash'), ('liability',)),
    'finance_petty_cash_topup': (('cash',), ('cash',)),
    'finance_advance': (('bank', 'cash'), ('advance',)),
    'finance_allocate_advance': (('advance',), ('payable',)),
    'typed_purchase': (('bank', 'cash', 'creditor'), ('expense',)),
    'typed_vendor_payment': (('bank', 'cash'), ('creditor',)),
    'typed_expense': (('bank', 'cash'), ('expense',)),
    'typed_client_invoice': (('debtor',), ('income',)),
    'typed_client_receipt': (('bank', 'cash'), ('debtor',)),
}


def require_three_links(kind, *, entity_id, party, source, account, no_vendor=False):
    source_kinds, account_kinds = _MONEY_LINK_KINDS[kind]
    if kind in ('finance_reimburse_staff', 'finance_petty_cash_topup'):
        if not isinstance(party, User):
            raise ValueError('Choose a transaction linked to a staff member.')
    elif party is None:
        if kind not in ('finance_expense', 'finance_staff_claim', 'typed_expense') or not no_vendor:
            raise ValueError('Choose the vendor for this entry.')
    else:
        expected = 'client' if kind in ('typed_client_invoice', 'typed_client_receipt') else 'vendor'
        if party.kind != expected:
            raise ValueError(f'Choose an active {expected} for this entry.')
    for linked, allowed, message in (
        (source, source_kinds, 'Choose an active paying account or approved balance for this company.'),
        (account, account_kinds, 'Choose an active ledger account for this company.'),
    ):
        if (linked is None or linked.kind not in allowed or linked.entity_id != entity_id
                or not linked.active or not linked.posting_allowed):
            raise ValueError(message)


def prepare_bank_review(db,items,actor):
    """Pin read-locked bank rows under the company/history locks for one review.

    Validators still run for every item, including fresh duplicate/reversal and
    exact file-byte checks. This only removes repeated identity-map reloads.
    """
    operation=db.info.get('_financial_evidence_operation')
    active=[i for i in items if i.status in ('pending','approved')]
    if operation is None or not active or any(i.item_type not in _BANK_REVIEW_TYPES for i in active):return
    if actor.role!='admin':return  # Original bank-review policy; normal refusal still follows.
    key=(actor.id,tuple(sorted(i.id for i in active)))
    from .db import User,lock_history_chain,current_lock_transaction
    current=operation.get('bank_review')
    token=current_lock_transaction(db)
    if token is not None and current and current['key']==key and current['transaction'] is token:return
    expected_role=actor.role
    lock_history_chain(db)  # Same order as every ticket commit: history, then domain rows.
    def rows(model,identifiers,lock=None):
        identifiers=sorted({value for value in identifiers if type(value)is int})
        answer=[]
        for offset in range(0,len(identifiers),500):
            query=select(model).where(model.id.in_(identifiers[offset:offset+500])).order_by(model.id)
            if lock is not None:query=query.with_for_update(read=lock=='read')
            answer.extend(db.scalars(query.execution_options(populate_existing=True)).all())
        return answer
    # Account-security operations can update their row before appending audit.
    # Do not take an auth-row lock while holding the history lock. Keep normal
    # fresh reviewer checks; only bank-domain rows are retained below.
    fresh=db.scalar(select(User).where(User.id==actor.id).execution_options(populate_existing=True))
    if fresh is None or not fresh.active or fresh.role!=expected_role:
        raise PermissionError('Your account changed; sign in again before approving')
    statement_ids=[i.after_data.get('statement_line_id')for i in active if i.item_type=='finance_reconcile_bank']
    statements=rows(FinanceBankStatementLine,statement_ids)
    bank_ids=[i.after_data.get('bank_id')for i in active if i.item_type=='finance_bank_statement_line']+[r.bank_id for r in statements]
    banks=rows(RegisteredBank,bank_ids)
    entities=rows(AccountingEntity,[b.entity_id for b in banks],lock='write')
    entity_map={e.id:e for e in entities}
    banks=rows(RegisteredBank,bank_ids,lock='read')
    if any(b.entity_id not in entity_map for b in banks):raise ValueError('Bank company changed; refresh the draft')
    bank_map={b.id:b for b in banks}
    statements=rows(FinanceBankStatementLine,statement_ids,lock='read')
    if any(r.bank_id not in bank_map for r in statements):raise ValueError('Statement bank changed; refresh the draft')
    journals=rows(GLJournal,[i.after_data.get('journal_id')for i in active if i.item_type=='finance_reconcile_bank'],lock='read')
    operation['bank_review']={'key':key,'transaction':current_lock_transaction(db),'entities':entity_map,
                              'rows':tuple(banks+statements+journals)}


def _bank_entity_lock(db,entity_id):
    operation=db.info.get('_financial_evidence_operation')or{}
    context=operation.get('bank_review')
    from .db import current_lock_transaction
    token=current_lock_transaction(db)
    if token is not None and context and context['transaction'] is token and entity_id in context['entities']:
        return context['entities'][entity_id]  # FOR UPDATE already held until this transaction ends.
    return db.scalar(select(AccountingEntity).where(AccountingEntity.id==entity_id).with_for_update())


MAX_AMOUNT=10**14

def positive_minor(n):
    if type(n) is not int or not 0<n<MAX_AMOUNT:raise ValueError('Positive exact amount_paise integer required')
    return n

def required_text(x,label,maxlen=120):
    if not isinstance(x,str) or not 1<=len(x.strip())<=maxlen:
        raise ValueError(f'{label} is required (maximum {maxlen} characters)')
    return x.strip()

def setup_input(db:Session,d:dict):
    keys={'entity_name','expense_code','ap_code','bank_code','bank_name','bank_masked'}
    if set(d)!=keys:raise ValueError('Explicit company, account codes and bank mapping required')
    name=required_text(d['entity_name'],'Legal entity',180)
    if db.scalar(select(AccountingEntity.id).where(AccountingEntity.name==name)):
        raise ValueError('Entity already has accounting setup; no silent policy changes')
    codes=[required_text(d[k],k,30) for k in ('expense_code','ap_code','bank_code')]
    if len(set(codes))!=3:raise ValueError('Chart account codes must be distinct')
    if CASH_CODE in codes:raise ValueError('Choose a different account code. CASH is reserved for Cash in Hand.')
    required_text(d['bank_name'],'Bank display name',150)
    mask=required_text(d['bank_masked'],'Masked bank identifier',40)
    if len(mask)>4 and mask.isdigit():raise ValueError('Do not store actual bank account numbers')

def _check_open(db,entity_id,document_date=None):
    from .chart_of_accounts import local_today

    month = document_date[:7] if document_date else local_today().strftime('%Y-%m')
    if db.scalar(select(ClosedAccountingPeriod.id).where(ClosedAccountingPeriod.entity_id==entity_id,
                                                             ClosedAccountingPeriod.year_month==month)):
        if document_date:
            raise ValueError(f'The accounting period for {month} is closed')
        raise ValueError('Current accounting period is closed')


def _calendar_date(value, label):
    try:
        day = date.fromisoformat(value)
    except (TypeError, ValueError):
        day = None
    if day is None or day.isoformat() != value:
        raise ValueError(f'{label} is required. Enter a date like 2026-03-31.')
    return day


def _check_dated_posting(db, entity_id, area, day, label):
    from .chart_of_accounts import local_today
    from .period_rules import check_document_date

    if day > local_today():
        raise ValueError(f'{label} cannot be in the future.')
    iso = day.isoformat()
    check_document_date(db, entity_id, area, iso)
    _check_open(db, entity_id, iso)


def _check_bill_dates(db, entity_id, data):
    bill_date = _calendar_date(data.get('bill_date'), 'Bill date')
    due_date = _calendar_date(data.get('due_date'), 'Due date')
    terms = data.get('payment_terms_days')
    if type(terms) is not int or terms < 0:
        raise ValueError('Enter the payment terms as a whole number of days. Use 0 when due on the bill date.')
    if due_date < bill_date:
        raise ValueError('Due date cannot be before the bill date.')
    if (due_date - bill_date).days != terms:
        raise ValueError('Due date must match the bill date plus the payment terms.')
    _check_dated_posting(db, entity_id, 'purchases', bill_date, 'Bill date')

def _policy(db,entity_id):
    entity=db.get(AccountingEntity,entity_id)
    policy=db.scalar(select(AccountingPolicy).where(AccountingPolicy.entity_id==entity_id))
    if not entity or entity.base_currency!='INR' or not policy:raise ValueError('An approved INR accounting policy is required')
    debit=db.get(GLAccount,policy.expense_account_id)
    payable=db.get(GLAccount,policy.payable_account_id)
    for account,kind in ((debit,'expense'),(payable,'payable')):
        if not account or not account.active or not account.posting_allowed or account.entity_id!=entity_id or account.kind!=kind:
            raise ValueError('Inactive, unmapped or wrong-type account')
    _check_open(db,entity_id)
    return entity,policy,debit,payable

def _po(db,d):
    po=db.get(FinancePurchaseOrder,d.get('po_id')) if type(d.get('po_id')) is int else None
    if not po or po.status!='approved':raise ValueError('Approved purchase order required')
    return po

def _bill(db,d):
    bill=db.get(FinanceSupplierBill,d.get('bill_id')) if type(d.get('bill_id')) is int else None
    if not bill or not bill.journal_id or _is_reversed(db,bill.journal_id):raise ValueError('Active posted supplier bill required')
    return bill

def _is_reversed(db:Session,journal_id):
    return bool(journal_id and db.scalar(select(FinanceReversal.id)
              .where(FinanceReversal.original_journal_id==journal_id)))


def outstanding(db,bill_id):
    bill=db.get(FinanceSupplierBill,bill_id)
    if not bill:return None
    if _is_reversed(db,bill.journal_id):return 0
    paid=sum(p.amount_paise for p in supplier_payments(db,bill_id) if not _is_reversed(db,p.journal_id))
    allocations = sum(db.scalar(select(func.coalesce(func.sum(model.amount_paise), 0))
                      .where(model.bill_id == bill_id)) for model in ADVANCE_ALLOCATIONS)
    return bill.amount_paise-paid-int(allocations)


def supplier_payments(db, bill_id):
    for model in (FinanceSupplierPayment, FinanceSupplierCashPayment):
        yield from db.scalars(select(model).where(model.bill_id == bill_id))


def _supplier_payment_source(db, entity_id, data, actor=None):
    if ('bank_id' in data) == ('paid_through_id' in data):
        raise ValueError('Choose one account under Paid through.')
    if 'bank_id' in data:
        bank = db.get(RegisteredBank, data['bank_id']) if type(data['bank_id']) is int else None
        if bank is None or bank.entity_id != entity_id:
            raise ValueError('Bank must belong to the same legal entity')
        account = db.get(GLAccount, bank.gl_account_id)
        if account is None or account.kind != 'bank':
            raise ValueError('Choose an active bank account.')
        return account, bank
    ident = data['paid_through_id']
    account = db.get(GLAccount, ident) if type(ident) is int else None
    if account is None or account.entity_id != entity_id:
        raise ValueError('Choose a paying account for this company.')
    if actor is not None:
        expense_source(db, ident, actor)
    if account.kind == 'cash' and (account.code == CASH_CODE or db.get(FinancePettyCashAccount, ident)):
        return account, None
    bank = db.scalar(select(RegisteredBank).where(
        RegisteredBank.entity_id == entity_id, RegisteredBank.gl_account_id == ident,
    )) if account.kind == 'bank' else None
    if bank is None:
        raise ValueError('Choose a bank or cash account under Paid through.')
    return account, bank


def _payment_to_reverse(db, data):
    if set(data) == {'cash_payment_id', 'reason'}:
        model, key = FinanceSupplierCashPayment, 'cash_payment_id'
    elif set(data) == {'payment_id', 'reason'}:
        model, key = FinanceSupplierPayment, 'payment_id'
    else:
        raise ValueError('Payment reversal needs payment ID and documented reason')
    payment = db.get(model, data[key]) if type(data[key]) is int else None
    if not payment or not payment.journal_id or _is_reversed(db, payment.journal_id):
        raise ValueError('Only a posted, unreversed payment can be reversed')
    return payment


def supplier_payment_warnings(db, data, *, advance=False):
    from .paid_through import cash_warnings

    try:
        if advance:
            entity_id, vendor_id = data.get('entity_id'), data.get('supplier_id')
        else:
            bill = _bill(db, data)
            entity_id, vendor_id = bill.entity_id, bill.supplier_id
        source, bank = _supplier_payment_source(db, entity_id, data)
    except ValueError:
        return []
    amount = data.get('amount_paise')
    if bank or type(amount) is not int or amount <= 0:
        return []
    return cash_warnings(db, source, vendor_id, data.get('payment_date'), amount)


def _advance_policy(db:Session,entity_id:int):
    policy=db.scalar(select(FinanceAdvancePolicy).where(FinanceAdvancePolicy.entity_id==entity_id))
    account=db.get(GLAccount,policy.advances_gl_account_id) if policy else None
    if not policy or not account or account.entity_id!=entity_id or account.kind!='advance' or not account.active or not account.posting_allowed:
        raise ValueError('An Admin-approved active supplier advances GL mapping is required')
    return policy,account


def advance_remaining(db:Session,advance_id:int,*,cash=False):
    model = FinanceSupplierCashAdvance if cash else FinanceSupplierAdvance
    allocation = FinanceCashAdvanceAllocation if cash else FinanceAdvanceAllocation
    advance=db.get(model,advance_id)
    if not advance:return None
    used=db.scalar(select(func.coalesce(func.sum(allocation.amount_paise),0))
        .where(allocation.advance_id==advance_id)) or 0
    return advance.amount_paise-int(used)


def _advance_for_allocation(db, data):
    cash = 'cash_advance_id' in data
    if cash == ('advance_id' in data):
        raise ValueError('Choose one supplier advance to allocate.')
    ident = data['cash_advance_id' if cash else 'advance_id']
    model = FinanceSupplierCashAdvance if cash else FinanceSupplierAdvance
    advance = db.get(model, ident) if type(ident) is int else None
    if advance is None or not advance.journal_id:
        raise ValueError('Choose a posted supplier advance.')
    return advance, cash


def _has_advance_allocations(db, bill_id):
    return any(db.scalar(select(model.id).where(model.bill_id == bill_id).limit(1))
               for model in ADVANCE_ALLOCATIONS)


def _cash_reference_used(db, account_id, reference):
    return any(db.scalar(select(model.id).where(
        model.paid_through_id == account_id, model.payment_reference == reference,
    )) for model in (FinanceSupplierCashPayment, FinanceSupplierCashAdvance))


def _bank_reference_used(db:Session,bank_id:int,reference:str,idem:str|None):
    if db.scalar(select(FinanceSupplierPayment.id).where(
           (FinanceSupplierPayment.bank_id==bank_id)&(FinanceSupplierPayment.payment_reference==reference))):return True
    if db.scalar(select(FinanceSupplierAdvance.id).where(
           (FinanceSupplierAdvance.bank_id==bank_id)&(FinanceSupplierAdvance.payment_reference==reference))):return True
    if idem is None:return False
    if db.scalar(select(FinanceSupplierPayment.id).where(FinanceSupplierPayment.idempotency_key==idem)):
        return True
    if db.scalar(select(FinanceSupplierCashPayment.id).where(FinanceSupplierCashPayment.idempotency_key==idem)):
        return True
    if db.scalar(select(FinanceSupplierAdvance.id).where(FinanceSupplierAdvance.idempotency_key==idem)):
        return True
    if db.scalar(select(FinanceSupplierCashAdvance.id).where(FinanceSupplierCashAdvance.idempotency_key==idem)):
        return True
    return False


def _inventory_policy(db:Session,entity_id:int):
    policy=db.scalar(select(FinanceInventoryPolicy).where(FinanceInventoryPolicy.entity_id==entity_id))
    if not policy:raise ValueError('Admin-approved inventory/GRNI policy is required')
    inv=db.get(GLAccount,policy.inventory_account_id)
    grni=db.get(GLAccount,policy.grni_account_id)
    for account,kind in ((inv,'inventory'),(grni,'grni')):
        if not account or account.entity_id!=entity_id or account.kind!=kind or not account.active or not account.posting_allowed:
            raise ValueError('Inactive or invalid approved inventory/GRNI account')
    return policy,inv,grni


def _received(db:Session,po_id:int):
    return db.scalars(select(FinanceGoodsReceipt).where(FinanceGoodsReceipt.po_id==po_id)).all()


def _issued(db:Session,po_id:int):
    return db.scalars(select(FinanceMaterialIssue).where(FinanceMaterialIssue.po_id==po_id)).all()


def _stock(db:Session,po_id:int):
    receipts=_received(db,po_id);issues=_issued(db,po_id)
    units=sum(r.quantity for r in receipts)-sum(i.quantity for i in issues)
    rate=receipts[0].unit_cost_paise if receipts else None
    return {'received_quantity':sum(r.quantity for r in receipts),
            'issued_quantity':sum(i.quantity for i in issues),
            'available_quantity':units,'unit_cost_paise':rate,
            'received_value_paise':sum(r.total_paise for r in receipts),
            'available_value_paise':units*(rate or 0)}


def _bank_movement(db:Session,bank_id:int,journal_id:int):
    bank=db.get(RegisteredBank,bank_id)
    journal=db.get(GLJournal,journal_id)
    if not bank or not journal or journal.entity_id!=bank.entity_id or journal.status!='posted':
        raise ValueError('Posted same-company bank journal required')
    if journal.source_event not in ('SUPPLIER_PAYMENT_POSTED','SUPPLIER_ADVANCE_PAID','TEXT_ENTRY_POSTED','OPENING_BALANCES',EXPENSE_EVENT,STAFF_PAYMENT_EVENT,LEGACY_BALANCE_PAYMENT_EVENT,'DIRECT_BILL_PAYMENT_POSTED','INTERNAL_TRANSFER_POSTED','SALES_RECEIPT_POSTED','SALES_ADVANCE_POSTED'):
        raise ValueError('Choose a posted bank movement such as supplier payments, advances, direct expenses or reimbursements.')
    if _is_reversed(db,journal.id):raise ValueError('A reversed journal cannot be reconciled')
    lines=db.scalars(select(GLLine).where(GLLine.journal_id==journal_id, GLLine.account_id==bank.gl_account_id)).all()
    if len(lines)!=1:raise ValueError('Journal must have exactly one bank GL movement')
    line=lines[0]
    return line.amount_paise if line.side=='debit' else -line.amount_paise


def _reconciled(db:Session,journal_id:int):
    return bool(db.scalar(select(FinanceBankReconciliation.id).where(FinanceBankReconciliation.journal_id==journal_id)))


def _statement_evidence_hash(doc:Document):
    """Read-only NAS evidence: never trust an indexed path without checking the bytes.

    An operator still needs to attest this file is an authentic bank statement.
    This hash proves continuity of the uploaded evidence, not bank authenticity.
    """
    if not doc or doc.doc_type.lower() not in ('pdf','csv','xlsx','bank_statement'):
        raise ValueError('Indexed PDF/CSV/XLSX bank-statement evidence is required')
    if str(doc.relative_path or '').startswith('intake/'):
        from .intake_documents import approved_source
        # The caller's transaction owns the approved document; resolving the file
        # uses the same Session so source authorization cannot race a new commit.
        from sqlalchemy.orm import object_session
        db=object_session(doc)
        if db is None:raise ValueError('Bank evidence needs its approved database context')
        _,_,digest=approved_source(db,doc)
        return digest
    root=os.getenv('STUDIOOS_NAS_ROOT','').strip()
    if not root:raise ValueError('Bank statement verification requires configured read-only NAS evidence directory')
    base=Path(root).resolve()
    path=(base/doc.relative_path).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise ValueError('Bank statement source file missing or unsafe path; cannot reconcile from metadata alone')
    size=path.stat().st_size
    if size<=0 or size>20*1024*1024:
        raise ValueError('Bank statement file must be nonempty and no larger than 20 MiB')
    if doc.size_bytes and doc.size_bytes!=size:
        raise ValueError('Bank statement file size differs from indexed evidence')
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(1024*1024):h.update(chunk)
    return h.hexdigest()


def _validate_reconciliation_items(db:Session,typ:str,d:dict,actor=None):
    if typ=='finance_enable_inventory':
        if set(d)!={'entity_id','inventory_code','grni_code'}:
            raise ValueError('Inventory policy requires entity and two distinct GL codes')
        entity=db.get(AccountingEntity,d.get('entity_id')) if type(d.get('entity_id')) is int else None
        if not entity:raise ValueError('Approved legal entity required')
        inv=required_text(d['inventory_code'],'Inventory account',30)
        grni=required_text(d['grni_code'],'GRNI account',30)
        if inv==grni:raise ValueError('Inventory and GRNI GL accounts must differ')
        if db.scalar(select(FinanceInventoryPolicy.id).where(FinanceInventoryPolicy.entity_id==entity.id)):
            raise ValueError('Inventory policy already active')
        if db.scalar(select(GLAccount.id).where(GLAccount.entity_id==entity.id,GLAccount.code.in_([inv,grni]))):
            raise ValueError('GL account code already used')
        _policy(db,entity.id)
        return
    if typ=='finance_goods_receipt':
        if set(d)!={'po_id','quantity','unit_cost_paise','receipt_reference','idempotency_key'}:
            raise ValueError('Goods receipt needs PO, quantity, unit cost, references')
        po=_po(db,d)
        if actor:
            from .access import require_project_access
            require_project_access(db,actor,po.project_id)
        _policy(db,po.entity_id);_inventory_policy(db,po.entity_id)
        qty=positive_minor(d.get('quantity'))
        rate=positive_minor(d.get('unit_cost_paise'))
        if qty*rate>=MAX_AMOUNT:raise ValueError('Goods receipt value exceeds financial limit')
        ref=required_text(d['receipt_reference'],'Goods receipt reference')
        idem=required_text(d['idempotency_key'],'Goods receipt idempotency key')
        if db.scalar(select(FinanceGoodsReceipt.id).where(FinanceGoodsReceipt.idempotency_key==idem)) or db.scalar(select(FinanceGoodsReceipt.id).where(FinanceGoodsReceipt.po_id==po.id,FinanceGoodsReceipt.receipt_reference==ref)):
            raise ValueError('Duplicate goods receipt')
        receipts=_received(db,po.id)
        if receipts and any(r.unit_cost_paise!=rate for r in receipts):
            raise ValueError('Mixed unit costs require a dedicated valuation policy; cannot guess')
        if sum(r.total_paise for r in receipts)+qty*rate>po.amount_paise:
            raise ValueError('Goods receipts exceed purchase order commitment')
        if db.scalar(select(FinanceSupplierBill.id).where(FinanceSupplierBill.po_id==po.id)):
            raise ValueError('Cannot add receipt after supplier invoice was posted')
        return
    if typ=='finance_inventory_bill':
        required = {'po_id','invoice_number','amount_paise'}
        if not required <= d.keys() or d.keys() - required - set(BILL_DATE_FIELDS):
            raise ValueError('Inventory bill needs approved PO, invoice number and amount')
        po=_po(db,d)
        if actor:
            from .access import require_project_access
            require_project_access(db,actor,po.project_id)
        _check_bill_dates(db, po.entity_id, d)
        _, _, _, payable = _policy(db, po.entity_id)
        _, _, grni = _inventory_policy(db, po.entity_id)
        require_three_links(typ, entity_id=po.entity_id, party=db.get(Party, po.supplier_id),
                            source=payable, account=grni)
        required_text(d['invoice_number'],'Invoice number')
        positive_minor(d.get('amount_paise'))
        if d['amount_paise']!=po.amount_paise or _stock(db,po.id)['received_value_paise']!=d['amount_paise']:
            raise ValueError('Only fully matched GRNI invoices supported; partial bills and discrepancies are blocked')
        if db.scalar(select(FinanceSupplierBill.id).where(FinanceSupplierBill.po_id==po.id)):
            raise ValueError('PO already invoiced')
        if db.scalar(select(FinanceSupplierBill.id).where(FinanceSupplierBill.entity_id==po.entity_id,
                      FinanceSupplierBill.supplier_id==po.supplier_id, FinanceSupplierBill.invoice_number==d['invoice_number'])):
            raise ValueError('Duplicate supplier invoice')
        return
    if typ=='finance_material_issue':
        if set(d)!={'po_id','quantity','issue_reference','idempotency_key'}:
            raise ValueError('Material issue needs PO, quantity and unique references')
        po=_po(db,d)
        if actor:
            from .access import require_project_access
            require_project_access(db,actor,po.project_id)
        _policy(db,po.entity_id);_inventory_policy(db,po.entity_id)
        qty=positive_minor(d.get('quantity'))
        ref=required_text(d['issue_reference'],'Stock issue reference')
        idem=required_text(d['idempotency_key'],'Stock issue idempotency key')
        if db.scalar(select(FinanceMaterialIssue.id).where(FinanceMaterialIssue.idempotency_key==idem)) or db.scalar(select(FinanceMaterialIssue.id).where(FinanceMaterialIssue.po_id==po.id,FinanceMaterialIssue.issue_reference==ref)):
            raise ValueError('Duplicate material issue')
        if qty>_stock(db,po.id)['available_quantity']:
            raise ValueError('Cannot issue more material than received stock')
        return
    if typ=='finance_bank_statement_line':
        if set(d)!={'bank_id','booking_date','statement_reference','signed_amount_paise','evidence_document_id'}:
            raise ValueError('Bank statement line needs bank, date, reference, amount, source document')
        bank=db.get(RegisteredBank,d.get('bank_id')) if type(d.get('bank_id')) is int else None
        if not bank:raise ValueError('Registered company bank required')
        amount=d.get('signed_amount_paise')
        if type(amount) is not int or not 0<abs(amount)<MAX_AMOUNT:
            raise ValueError('Exact signed paise amount required (outflow negative)')
        try:
            if not isinstance(d.get('booking_date'),str) or date.fromisoformat(d['booking_date']).isoformat()!=d['booking_date']:
                raise ValueError('Invalid bank booking date')
        except (TypeError,ValueError):raise ValueError('Bank booking date must be YYYY-MM-DD')
        ref=required_text(d['statement_reference'],'Unique bank statement transaction reference')
        doc=db.get(Document,d.get('evidence_document_id')) if type(d.get('evidence_document_id')) is int else None
        _statement_evidence_hash(doc) # File must actually exist in the authorized NAS tree.
        if actor and doc.project_id is not None:
            from .access import require_project_access
            require_project_access(db,actor,doc.project_id)
        if db.scalar(select(FinanceBankStatementLine.id).where(FinanceBankStatementLine.bank_id==bank.id,FinanceBankStatementLine.statement_reference==ref)):
            raise ValueError('Duplicate bank statement reference')
        return
    if typ=='finance_reconcile_bank':
        if set(d)!={'statement_line_id','journal_id'}:raise ValueError('Reconciliation needs bank statement line and posted journal')
        stmt=db.get(FinanceBankStatementLine,d.get('statement_line_id')) if type(d.get('statement_line_id')) is int else None
        if not stmt:raise ValueError('Imported bank statement evidence required')
        if stmt.evidence_sha256!=_statement_evidence_hash(db.get(Document,stmt.evidence_document_id)):
            raise ValueError('Bank statement evidence was changed after approval; matching blocked')
        if type(d.get('journal_id')) is not int:raise ValueError('Posted bank journal ID required')
        amount=_bank_movement(db,stmt.bank_id,d['journal_id'])
        if amount!=stmt.signed_amount_paise:raise ValueError('Statement amount/direction does not match bank GL; no partial matches')
        if db.scalar(select(FinanceBankReconciliation.id).where((FinanceBankReconciliation.statement_line_id==stmt.id)|(FinanceBankReconciliation.journal_id==d['journal_id']))):
            raise ValueError('Statement line or journal already reconciled')
        journal=db.get(GLJournal,d['journal_id'])
        if actor and journal.source_event=='SUPPLIER_PAYMENT_POSTED':
            payment=db.get(FinanceSupplierPayment,journal.source_id)
            if not payment:raise ValueError('Source payment missing')
            bill=db.get(FinanceSupplierBill,payment.bill_id);po=db.get(FinancePurchaseOrder,bill.po_id)
            from .access import require_project_access
            require_project_access(db,actor,po.project_id)
        elif actor and journal.source_event=='TEXT_ENTRY_POSTED':
            from .db import FinanceTextEntry
            entry=db.get(FinanceTextEntry,journal.source_id)
            if not entry or entry.journal_id!=journal.id or entry.entity_id!=journal.entity_id:raise ValueError('Posted text source missing')
            if entry.project_id is not None:
                from .access import require_project_access
                require_project_access(db,actor,entry.project_id)
        elif actor and journal.source_event == EXPENSE_EVENT:
            from .access import require_project_access
            from .db import FinanceExpense

            entry = db.get(FinanceExpense, journal.source_id)
            if not entry or entry.journal_id != journal.id or entry.entity_id != journal.entity_id:
                raise ValueError('Posted expense source missing')
            require_project_access(db, actor, entry.project_id)
        elif actor and journal.source_event == STAFF_PAYMENT_EVENT:
            from .access import require_project_access

            payment = db.get(FinanceStaffReimbursement, journal.source_id)
            claim = db.get(FinanceExpense, payment.claim_id) if payment else None
            if claim is None or payment.journal_id != journal.id or claim.entity_id != journal.entity_id:
                raise ValueError('Posted reimbursement source missing')
            require_project_access(db, actor, claim.project_id)
        elif actor and journal.source_event=='SUPPLIER_ADVANCE_PAID':
            advance=db.get(FinanceSupplierAdvance,journal.source_id)
            if not advance:raise ValueError('Source advance missing')
            from .access import require_project_access
            require_project_access(db,actor,advance.project_id)
        elif actor and journal.source_event == LEGACY_BALANCE_PAYMENT_EVENT:
            from .access import require_project_access

            project_id = db.scalar(select(GLLine.project_id).where(GLLine.journal_id == journal.id, GLLine.side == 'debit'))
            require_project_access(db, actor, project_id)
        return
    raise ValueError('Unsupported advanced finance event')


def _require_owner_for_po(db,item,d):
    """Owner rule (see po_rules_core): a PO with a new vendor, a rate above the last rate, a quantity above the estimate, or no
    line detail must be approved by the owner (Admin); otherwise any ticket approver the policy allows may approve it."""
    from .db import User
    from .po_rules import reasons_for
    reasons=reasons_for(db,d)
    if not reasons:return
    decider=db.get(User,item.decided_by) if getattr(item,'decided_by',None) else None
    if decider is None or decider.role!='admin':
        raise ValueError('This purchase order must be approved by the owner: '+'; '.join(reasons))


def validate_finance_item(db:Session,typ:str,d:dict,actor=None):
    if not isinstance(d,dict):raise ValueError('Financial proposal must be an object')
    if typ in ('finance_transfer', 'finance_reverse_transfer', 'finance_manual_journal', 'finance_reverse_manual_journal'):
        from .transfers_journals import validate
        return validate(db, typ, d, actor)
    if typ in ('finance_bank_rule', 'finance_unreconcile_bank'):
        from .bank_feed import validate as bf_validate
        return bf_validate(db, typ, d, actor)
    if typ == 'finance_attach_document':
        from .finance_attachments import validate as att_validate
        return att_validate(db, typ, d, actor)
    if typ in ('sales_quote', 'sales_accept_quote'):
        from .sales_quotes import validate as sq_validate
        return sq_validate(db, typ, d, actor)
    if typ in ('sales_invoice', 'sales_reverse_invoice'):
        from .sales_invoices import validate as si_validate
        return si_validate(db, typ, d, actor)
    if typ in ('sales_receipt', 'sales_reverse_receipt', 'sales_advance', 'sales_allocate_advance'):
        from .sales_receipts import validate as sr_validate
        return sr_validate(db, typ, d, actor)
    if typ in ('finance_direct_bill', 'finance_reverse_direct_bill', 'finance_direct_bill_payment', 'finance_reverse_direct_bill_payment'):
        from .direct_bills import validate
        return validate(db, typ, d, actor)
    if typ == 'finance_expense_category':
        from .expense_categories import validate

        return validate(db, d)
    if typ == 'finance_petty_cash_topup':
        from .petty_cash import validate

        return validate(db, d, actor)
    if typ == 'finance_reverse_petty_cash_topup':
        from .petty_cash import validate_reverse

        return validate_reverse(db, d)
    if typ in ('finance_migrate_expenses', 'finance_reverse_expense_migration') or typ in LEGACY_BALANCE_PAYMENT_FIELDS:
        from .legacy_expense_migration import validate

        return validate(db, typ, d, actor)
    if typ == 'finance_expense':
        from .expense_entry import validate
        if actor is None:
            raise ValueError('An active submitter is required to record this expense.')
        validate(db, d, actor)
        return
    if typ == 'finance_reimburse_staff':
        from .staff_reimbursements import validate_payment
        validate_payment(db, d, actor)
        return
    if typ == 'finance_reverse_staff_payment':
        from .staff_reimbursements import payment_to_reverse
        payment_to_reverse(db, d)
        return
    if typ in ('finance_enable_inventory','finance_goods_receipt','finance_inventory_bill',
               'finance_material_issue','finance_bank_statement_line','finance_reconcile_bank'):
        return _validate_reconciliation_items(db,typ,d,actor)
    if typ=='finance_setup':return setup_input(db,d)
    if typ=='finance_project_company':
        from .site_expense import validate_project_company

        validate_project_company(db,d,actor)
        return
    if typ=='finance_enable_cash':
        if set(d)!={'entity_id'} or type(d.get('entity_id')) is not int or not db.get(AccountingEntity,d['entity_id']):
            raise ValueError('Choose an existing company.')
        if db.scalar(select(GLAccount.id).where(GLAccount.entity_id==d['entity_id'],GLAccount.code==CASH_CODE)):
            raise ValueError('This company already has an account with the Cash in Hand code. Please review its chart of accounts.')
        return
    if typ == 'finance_reverse_expense':
        from .expense_entry import reversal_source
        reversal_source(db, d)
        return
    if typ=='finance_open_petty_cash':
        petty_cash_custodian(db,d)
        return
    if typ=='finance_po':
        base={'entity_id','supplier_id','project_id','po_number','amount_paise'}
        if not base<=set(d) or set(d)-base-{'lines'}:raise ValueError('PO needs explicit approved company, supplier, project, number and value')
        ent=db.get(AccountingEntity,d['entity_id']) if type(d.get('entity_id')) is int else None
        supplier=db.get(Party,d.get('supplier_id')) if type(d.get('supplier_id')) is int else None
        project=db.get(Project,d.get('project_id')) if type(d.get('project_id')) is int else None
        if not ent or not supplier or supplier.kind!='vendor' or supplier.deleted_at or not project or project.deleted_at:
            raise ValueError('Valid company, supplier and project required')
        if actor:
            from .access import require_project_access
            require_project_access(db,actor,project.id)
        required_text(d['po_number'],'PO number')
        positive_minor(d['amount_paise'])
        if 'lines' in d:
            from .po_rules_core import validate_lines
            validate_lines(d['lines'],d['amount_paise'])
        if db.scalar(select(FinancePurchaseOrder.id).where(FinancePurchaseOrder.entity_id==ent.id,
                    FinancePurchaseOrder.po_number==d['po_number'])):raise ValueError('Duplicate PO')
        return
    if typ=='finance_bill':
        required = {'po_id','invoice_number','amount_paise'}
        if not required <= d.keys() or d.keys() - required - set(BILL_DATE_FIELDS):
            raise ValueError('Bill requires PO, unique invoice number and amount')
        po=_po(db,d)
        if actor:
            from .access import require_project_access
            require_project_access(db,actor,po.project_id)
        _check_bill_dates(db, po.entity_id, d)
        required_text(d['invoice_number'],'Supplier invoice number')
        positive_minor(d['amount_paise'])
        if _received(db,po.id):raise ValueError('Inventory receipt exists; use the GRNI-matched inventory invoice type')
        if d['amount_paise']!=po.amount_paise:
            raise ValueError('Partial invoices, mismatches, taxes or inventory require the future matching engine; cannot post')
        if db.scalar(select(FinanceSupplierBill.id).where(FinanceSupplierBill.po_id==po.id)):
            raise ValueError('This PO is already fully invoiced; partial bills not enabled')
        if db.scalar(select(FinanceSupplierBill.id).where(FinanceSupplierBill.entity_id==po.entity_id,
                      FinanceSupplierBill.supplier_id==po.supplier_id,FinanceSupplierBill.invoice_number==d['invoice_number'])):
            raise ValueError('Duplicate supplier invoice')
        _, _, expense, payable = _policy(db, po.entity_id)
        require_three_links(typ, entity_id=po.entity_id, party=db.get(Party, po.supplier_id),
                            source=payable, account=expense)
        return
    if typ=='finance_payment':
        required = {'bill_id','amount_paise','idempotency_key','payment_reference'}
        if not required <= d.keys() or d.keys() - required - {*PAYMENT_DATE_FIELDS, 'bank_id', 'paid_through_id'}:
            raise ValueError('Choose a bill, a paying account, an amount and a payment reference.')
        bill=_bill(db,d)
        po=db.get(FinancePurchaseOrder,bill.po_id)
        if actor:
            from .access import require_project_access
            require_project_access(db,actor,po.project_id)
        payment_date = _calendar_date(d.get('payment_date'), 'Payment date')
        gl, bank = _supplier_payment_source(db, bill.entity_id, d, actor)
        _check_dated_posting(db, bill.entity_id, 'bank' if bank else 'purchases', payment_date, 'Payment date')
        _, _, _, payable = _policy(db, bill.entity_id)
        require_three_links(typ, entity_id=bill.entity_id, party=db.get(Party, bill.supplier_id),
                            source=gl, account=payable)
        positive_minor(d['amount_paise'])
        required_text(d['idempotency_key'],'Idempotency key')
        reference = required_text(d['payment_reference'],'Payment reference')
        if db.scalar(select(FinanceSupplierPayment.id).where(FinanceSupplierPayment.idempotency_key==d['idempotency_key'])):
            raise ValueError('Payment idempotency key already posted')
        if bank and db.scalar(select(FinanceSupplierPayment.id).where(FinanceSupplierPayment.bank_id==bank.id,
                      FinanceSupplierPayment.payment_reference==d['payment_reference'])):
            raise ValueError('This bank payment reference already exists')
        if _bank_reference_used(db,bank.id if bank else None,d['payment_reference'],d['idempotency_key']):
            raise ValueError('Duplicate payment/advance bank reference or idempotency key')
        if legacy_reference_used(db, gl.id, reference) or (not bank and _cash_reference_used(db, gl.id, d['payment_reference'])):
            raise ValueError('This payment reference already exists for that account.')
        if d['amount_paise']>outstanding(db,bill.id):raise ValueError('Payment exceeds supplier bill outstanding')
        return
    if typ=='finance_enable_advances':
        if set(d)!={'entity_id','advance_code'}:raise ValueError('Advance setup requires company and unique GL account code')
        entity=db.get(AccountingEntity,d.get('entity_id')) if type(d.get('entity_id')) is int else None
        if not entity:raise ValueError('Legal entity required')
        code=required_text(d['advance_code'],'Supplier advances asset code',30)
        if db.scalar(select(FinanceAdvancePolicy.id).where(FinanceAdvancePolicy.entity_id==entity.id)):
            raise ValueError('Supplier advances policy already enabled')
        if db.scalar(select(GLAccount.id).where(GLAccount.entity_id==entity.id,GLAccount.code==code)):
            raise ValueError('GL account code already exists')
        _policy(db,entity.id)
        return
    if typ=='finance_advance':
        required = {'entity_id','supplier_id','project_id','amount_paise','payment_reference','idempotency_key'}
        if not required <= d.keys() or d.keys() - required - {'bank_id', 'paid_through_id', 'payment_date'}:
            raise ValueError('Choose a company, supplier, project and paying account, and enter the amount and reference.')
        entity_id=d.get('entity_id')
        if type(entity_id) is not int or not db.get(AccountingEntity,entity_id):raise ValueError('Legal entity required')
        supplier=db.get(Party,d.get('supplier_id')) if type(d.get('supplier_id')) is int else None
        project=db.get(Project,d.get('project_id')) if type(d.get('project_id')) is int else None
        if not supplier or supplier.kind!='vendor' or supplier.deleted_at or not project or project.deleted_at:
            raise ValueError('Valid active supplier and project required')
        if actor:
            from .access import require_project_access
            require_project_access(db,actor,project.id)
        gl, bank = _supplier_payment_source(db, entity_id, d, actor)
        _policy(db, entity_id)
        _, advances_account = _advance_policy(db, entity_id)
        require_three_links(typ, entity_id=entity_id, party=supplier,
                            source=gl, account=advances_account)
        if 'paid_through_id' in d or 'payment_date' in d:
            day = _calendar_date(d.get('payment_date'), 'Payment date')
            _check_dated_posting(db, entity_id, 'bank' if bank else 'purchases', day, 'Payment date')
        positive_minor(d['amount_paise'])
        ref=required_text(d['payment_reference'],'Payment reference')
        idem=required_text(d['idempotency_key'],'Idempotency key')
        if (_bank_reference_used(db,bank.id if bank else None,ref,idem) or legacy_reference_used(db, gl.id, ref)
                or (not bank and _cash_reference_used(db,gl.id,ref))):
            raise ValueError('Duplicate payment reference or idempotency key.')
        return
    if typ=='finance_allocate_advance':
        common = {'bill_id','amount_paise','idempotency_key'}
        if not common <= d.keys() or d.keys() - common - {'advance_id', 'cash_advance_id'}:
            raise ValueError('Allocation requires advance, bill, amount and unique key')
        advance, cash = _advance_for_allocation(db, d)
        bill=_bill(db,d)
        po=db.get(FinancePurchaseOrder,bill.po_id)
        if not advance or advance.entity_id!=bill.entity_id or advance.supplier_id!=bill.supplier_id or advance.project_id!=po.project_id:
            raise ValueError('Advance must belong to same company, supplier and project as bill')
        if actor:
            from .access import require_project_access
            require_project_access(db,actor,po.project_id)
        positive_minor(d['amount_paise'])
        idem=required_text(d['idempotency_key'],'Allocation idempotency key')
        if any(db.scalar(select(model.id).where(model.idempotency_key == idem)) for model in ADVANCE_ALLOCATIONS):
            raise ValueError('Allocation idempotency key already posted')
        if d['amount_paise']>advance_remaining(db,advance.id,cash=cash) or d['amount_paise']>outstanding(db,bill.id):
            raise ValueError('Allocation exceeds unallocated advance or open supplier payable')
        _, _, _, payable = _policy(db, bill.entity_id)
        _, advances_account = _advance_policy(db, bill.entity_id)
        require_three_links(typ, entity_id=bill.entity_id, party=db.get(Party, bill.supplier_id),
                            source=advances_account, account=payable)
        return
    if typ=='finance_reverse_payment':
        payment = _payment_to_reverse(db, d)
        if getattr(payment, 'bank_reconciled', False) or _reconciled(db,payment.journal_id):raise ValueError('Reconciled payments require separate bank adjustment review')
        bill=db.get(FinanceSupplierBill,payment.bill_id)
        po=db.get(FinancePurchaseOrder,bill.po_id)
        if actor:
            from .access import require_project_access
            require_project_access(db,actor,po.project_id)
        if _has_advance_allocations(db, bill.id):
            raise ValueError('Allocated supplier advance blocks bill reversal until controlled allocation reversal is implemented')
        required_text(d['reason'],'Documented correction reason',400)
        _policy(db,bill.entity_id)
        return
    if typ=='finance_reverse_bill':
        if set(d)!={'bill_id','reason'}:raise ValueError('Bill reversal needs bill ID and documented reason')
        bill=_bill(db,d)
        po=db.get(FinancePurchaseOrder,bill.po_id)
        if actor:
            from .access import require_project_access
            require_project_access(db,actor,po.project_id)
        if _received(db,po.id):raise ValueError('GRNI inventory bills require separately controlled reversal; cannot reverse through expense flow')
        for payment in supplier_payments(db, bill.id):
            if not _is_reversed(db,payment.journal_id):
                raise ValueError('Reverse every payment before reversing the bill')
        if _has_advance_allocations(db, bill.id):
            raise ValueError('Allocated supplier advance blocks bill reversal until controlled allocation reversal is implemented')
        required_text(d['reason'],'Documented correction reason',400)
        _policy(db,bill.entity_id)
        return
    if typ=='finance_close_period':
        if set(d)!={'entity_id','year_month','reason'}:raise ValueError('Period closure needs company, month, reason')
        entity=db.get(AccountingEntity,d.get('entity_id')) if type(d.get('entity_id')) is int else None
        if not entity:raise ValueError('Legal entity required')
        month=d['year_month']
        if not isinstance(month,str) or not re.fullmatch(r'20[0-9]{2}-(0[1-9]|1[012])',month):
            raise ValueError('Accounting period must be YYYY-MM')
        from .chart_of_accounts import local_today
        if month>local_today().strftime('%Y-%m'):
            raise ValueError('Cannot close a future accounting period')
        if db.scalar(select(ClosedAccountingPeriod.id).where(ClosedAccountingPeriod.entity_id==entity.id,
                 ClosedAccountingPeriod.year_month==month)):
            raise ValueError('Period already closed')
        required_text(d['reason'],'Period closure explanation',400)
        return
    raise ValueError('Unsupported financial event; advances, inventory, GST, FX and GRNI are not enabled')


def _post(db:Session,*,entity_id:int,event_kind:str,event_key:str,source_id:int,
          debit_account:int,credit_account:int,amount:int,project_id:int,
          supplier_id:int,ticket_id:int,policy_version:int):
    """Balanced, exact integer amounts; database commits journal and lines atomically."""
    positive_minor(amount)
    if debit_account==credit_account:raise ValueError('Debit and credit must differ')
    # Serialize posting against period closure on PostgreSQL (SQLite does not prove this).
    db.scalar(select(AccountingEntity).where(AccountingEntity.id==entity_id).with_for_update())
    from .finance_assurance import assert_posted_journal_balances
    assert_posted_journal_balances(db,entity_id)
    _check_open(db,entity_id)
    accounts=[db.get(GLAccount,a) for a in (debit_account,credit_account)]
    if any(not a or a.entity_id!=entity_id or not a.active or not a.posting_allowed for a in accounts):
        raise ValueError('Journal account inactive, nonpostable or cross-entity')
    if db.scalar(select(GLJournal.id).where(GLJournal.event_key==event_key)):
        raise ValueError('Business event already posted; cannot post twice')
    # Posting template has exactly two opposite, equal sides: no AI-supplied journal line.
    j=GLJournal(entity_id=entity_id,source_event=event_kind,event_key=event_key,
                source_id=source_id,policy_version=policy_version,ticket_id=ticket_id,status='posted')
    db.add(j);db.flush()
    lines=[GLLine(journal_id=j.id,account_id=debit_account,side='debit',amount_paise=amount,
                  project_id=project_id,supplier_id=supplier_id),
           GLLine(journal_id=j.id,account_id=credit_account,side='credit',amount_paise=amount,
                  project_id=project_id,supplier_id=supplier_id)]
    if sum(l.amount_paise for l in lines if l.side=='debit')!=sum(l.amount_paise for l in lines if l.side=='credit'):
        raise ValueError('UNBALANCED JOURNAL: posting cancelled')
    db.add_all(lines);db.flush()
    return j


def _post_lines(db:Session,*,entity_id:int,event_kind:str,event_key:str,source_id:int,
                lines:list,ticket_id:int,policy_version:int,supplier_id:int | None=None):
    """v0.9.14: the same checks as _post for an entry with more than two lines (a purchase
    with CGST and SGST, an invoice with output GST). lines = [(account_id, side, paise, project_id)].
    Lines come from an approved posting recipe, never from model output; on PostgreSQL the
    database refuses the commit again if they do not balance (ledger_guard)."""
    if not 2<=len(lines)<=20:raise ValueError('An entry has between 2 and 20 lines')
    for account_id,side,amount,_ in lines:
        positive_minor(amount)
        if side not in ('debit','credit') or type(account_id) is not int:raise ValueError('Invalid journal line')
    debit=sum(a for _,s,a,_ in lines if s=='debit');credit=sum(a for _,s,a,_ in lines if s=='credit')
    if debit!=credit or not debit:raise ValueError('UNBALANCED JOURNAL: posting cancelled')
    if len({(a,s) for a,s,_,_ in lines})!=len(lines) or {a for a,s,_,_ in lines if s=='debit'}&{a for a,s,_,_ in lines if s=='credit'}:
        raise ValueError('An account may appear once per side and not on both sides of one entry')
    db.scalar(select(AccountingEntity).where(AccountingEntity.id==entity_id).with_for_update())
    from .finance_assurance import assert_posted_journal_balances
    assert_posted_journal_balances(db,entity_id)
    _check_open(db,entity_id)
    for account_id,_,_,_ in lines:
        a=db.get(GLAccount,account_id)
        if not a or a.entity_id!=entity_id or not a.active or not a.posting_allowed:
            raise ValueError('Journal account inactive, nonpostable or cross-entity')
    if db.scalar(select(GLJournal.id).where(GLJournal.event_key==event_key)):
        raise ValueError('Business event already posted; cannot post twice')
    j=GLJournal(entity_id=entity_id,source_event=event_kind,event_key=event_key,source_id=source_id,
                policy_version=policy_version,ticket_id=ticket_id,status='posted')
    db.add(j);db.flush()
    db.add_all([GLLine(journal_id=j.id,account_id=a,side=s,amount_paise=n,project_id=p,supplier_id=supplier_id) for a,s,n,p in lines])
    db.flush()
    return j


def _reverse_posted(db:Session,original_id:int,reason:str,ticket_id:int):
    entity_id=db.scalar(select(GLJournal.entity_id).where(GLJournal.id==original_id))
    if entity_id is None:
        raise ValueError('Original journal missing or already reversed')
    db.scalar(select(AccountingEntity).where(AccountingEntity.id==entity_id).with_for_update())
    original=db.scalar(select(GLJournal).where(GLJournal.id==original_id).with_for_update())
    if not original or original.status!='posted' or _is_reversed(db,original.id):
        raise ValueError('Original journal missing or already reversed')
    _check_open(db,original.entity_id)
    lines=db.scalars(select(GLLine).where(GLLine.journal_id==original.id).order_by(GLLine.id)).all()
    if len(lines)<2 or sum(l.amount_paise for l in lines if l.side=='debit')!=sum(l.amount_paise for l in lines if l.side=='credit'):
        raise ValueError('Original journal does not meet balancing invariant')
    for line in lines:
        account=db.get(GLAccount,line.account_id)
        if not account or account.entity_id!=original.entity_id or not account.active or not account.posting_allowed:
            raise ValueError('Reversal account is inactive or invalid; manual controlled correction required')
    reversal=GLJournal(entity_id=original.entity_id,source_event='JOURNAL_REVERSAL',
         event_key=f'reversal:{original.id}',source_id=original.id,
         policy_version=original.policy_version,ticket_id=ticket_id,status='posted')
    db.add(reversal);db.flush()
    db.add_all([GLLine(journal_id=reversal.id,account_id=line.account_id,
           side='credit' if line.side=='debit' else 'debit',amount_paise=line.amount_paise,
           project_id=line.project_id,supplier_id=line.supplier_id) for line in lines])
    db.add(FinanceReversal(original_journal_id=original.id,reversal_journal_id=reversal.id,
           reason=reason,ticket_id=ticket_id))
    db.flush()
    return reversal


def preview(db:Session,typ:str,d:dict,actor=None):
    if typ in ('finance_transfer', 'finance_reverse_transfer', 'finance_manual_journal', 'finance_reverse_manual_journal'):
        from .transfers_journals import preview as tj_preview
        return tj_preview(db, typ, d, actor)
    if typ in ('finance_bank_rule', 'finance_unreconcile_bank'):
        from .bank_feed import preview as bf_preview
        return bf_preview(db, typ, d, actor)
    if typ == 'finance_attach_document':
        from .finance_attachments import preview as att_preview
        return att_preview(db, typ, d, actor)
    if typ in ('sales_quote', 'sales_accept_quote'):
        from .sales_quotes import preview as sq_preview
        return sq_preview(db, typ, d, actor)
    if typ in ('sales_invoice', 'sales_reverse_invoice'):
        from .sales_invoices import preview as si_preview
        return si_preview(db, typ, d, actor)
    if typ in ('sales_receipt', 'sales_reverse_receipt', 'sales_advance', 'sales_allocate_advance'):
        from .sales_receipts import preview as sr_preview
        return sr_preview(db, typ, d, actor)
    if typ in ('finance_direct_bill', 'finance_reverse_direct_bill', 'finance_direct_bill_payment', 'finance_reverse_direct_bill_payment'):
        from .direct_bills import preview as direct_bill_preview
        return direct_bill_preview(db, typ, d, actor)
    if typ == 'finance_expense_category':
        from .expense_categories import preview as category_preview

        return category_preview(db, d)
    if typ == 'finance_petty_cash_topup':
        from .petty_cash import preview as cash_preview

        return cash_preview(db, d, actor)
    if typ == 'finance_reverse_petty_cash_topup':
        from .petty_cash import preview_reverse

        return preview_reverse(db, d)
    if typ in ('finance_migrate_expenses', 'finance_reverse_expense_migration') or typ in LEGACY_BALANCE_PAYMENT_FIELDS:
        from .legacy_expense_migration import preview as migration_preview

        return migration_preview(db, typ, d, actor)
    validate_finance_item(db,typ,d,actor)
    if typ in ('finance_reverse_expense', 'finance_reverse_staff_payment'):
        from .expense_entry import reversal_source
        from .staff_reimbursements import payment_to_reverse
        source = reversal_source(db, d) if typ == 'finance_reverse_expense' else payment_to_reverse(db, d)[0]
        lines = db.scalars(select(GLLine).where(GLLine.journal_id == source.journal_id)).all()
        return {'event':'JOURNAL_REVERSAL','original_journal_id':source.journal_id,'requires_ticket_approval':True,
                'journal_lines':[{'side':'credit' if line.side == 'debit' else 'debit',
                                  'account_code':db.get(GLAccount, line.account_id).code,
                                  'amount_paise':line.amount_paise} for line in lines]}
    if typ in ('finance_enable_inventory','finance_bank_statement_line','finance_reconcile_bank'):
        return {'event':typ,'journal_lines':[],'gl_effect_paise':0,'requires_ticket_approval':True,
                'note':'Account mapping, statement import and reconciliation do not change the GL; evidence/approval required'}
    if typ in ('finance_goods_receipt','finance_inventory_bill','finance_material_issue'):
        po=_po(db,d)
        _,inv,grni=_inventory_policy(db,po.entity_id)
        _,policy,expense,ap=_policy(db,po.entity_id)
        if typ=='finance_goods_receipt':
            debit,credit=inv,grni
            amount=d['quantity']*d['unit_cost_paise']
            event='GOODS_RECEIPT_GRNI'
        elif typ=='finance_inventory_bill':
            debit,credit=grni,ap
            amount=d['amount_paise']
            event='SUPPLIER_INVENTORY_BILL'
        else:
            debit,credit=expense,inv
            amount=d['quantity']*_stock(db,po.id)['unit_cost_paise']
            event='MATERIAL_CONSUMED'
        return {'event':event,'currency':'INR','policy_version':policy.policy_version,
                **{field: d[field] for field in BILL_DATE_FIELDS if field in d},
                'requires_ticket_approval':True,'journal_lines':[
                    {'side':'debit','account_code':debit.code,'amount_paise':amount},
                    {'side':'credit','account_code':credit.code,'amount_paise':amount}],
                'balanced':True,'note':'Fixed per-PO cost, no GST/FX; financial posting only after approval'}
    if typ=='finance_open_petty_cash':
        return {'event':typ,'journal_lines':[],'gl_effect_paise':0,'requires_ticket_approval':True,
                'note':'Opens a petty cash account for the selected staff member. No money moves.'}
    if typ=='finance_enable_cash':
        return {'event':typ,'journal_lines':[],'gl_effect_paise':0,'requires_ticket_approval':True,
                'note':'Adds Cash in Hand to this company. No money moves.'}
    if typ=='finance_project_company':
        return {'event':typ,'journal_lines':[],'gl_effect_paise':0,'requires_ticket_approval':True,
                'note':'Sets the company for future site expenses. Existing entries stay in their original company.'}
    if typ in ('finance_setup','finance_po','finance_close_period','finance_enable_advances'):
        return {'event':typ,'journal_lines':[],'gl_effect_paise':0,'requires_ticket_approval':True,
                'note':'Setup, PO and period closure do not post general-ledger entries'}
    if typ in ('finance_advance','finance_allocate_advance'):
        if typ=='finance_advance':
            _,asset=_advance_policy(db,d['entity_id'])
            credit, bank = _supplier_payment_source(db, d['entity_id'], d, actor)
            debit = asset
            event = 'SUPPLIER_ADVANCE_PAID' if bank else SUPPLIER_CASH_ADVANCE_EVENT
        else:
            advance, _ = _advance_for_allocation(db, d)
            bill=db.get(FinanceSupplierBill,d['bill_id'])
            _,asset=_advance_policy(db,advance.entity_id)
            _,policy,expense,ap=_policy(db,bill.entity_id)
            debit,credit=ap,asset
            event='ADVANCE_ALLOCATED'
        amount=d['amount_paise']
        return {'event':event,'currency':'INR','requires_ticket_approval':True,
            'journal_lines':[{'side':'debit','account_code':debit.code,'amount_paise':amount},
                             {'side':'credit','account_code':credit.code,'amount_paise':amount}],
            'balanced':True,'bank_reconciled':False if event=='SUPPLIER_ADVANCE_PAID' else None,
            **({'warnings': supplier_payment_warnings(db, d, advance=True)} if event == SUPPLIER_CASH_ADVANCE_EVENT else {}),
            'note':'Supplier advance is an asset until allocated to an approved supplier bill'}
    if typ in ('finance_reverse_payment','finance_reverse_bill'):
        obj=_payment_to_reverse(db,d) if typ=='finance_reverse_payment' else db.get(FinanceSupplierBill,d['bill_id'])
        journal=db.get(GLJournal,obj.journal_id)
        entries=db.scalars(select(GLLine).where(GLLine.journal_id==journal.id)).all()
        return {'event':'JOURNAL_REVERSAL','original_journal_id':journal.id,'currency':'INR',
                'journal_lines':[{'side':'credit' if x.side=='debit' else 'debit',
                                  'account_code':db.get(GLAccount,x.account_id).code,'amount_paise':x.amount_paise}
                                 for x in entries],
                'requires_ticket_approval':True,'reason':d['reason'],
                'note':'Original immutable journal preserved; payment/bill marked reversed by a linked append-only event'}
    if typ=='finance_bill':
        po=_po(db,d);_,pol,expense,ap=_policy(db,po.entity_id)
        accounts=(expense,ap);event='SUPPLIER_BILL_ACCEPTED';amount=d['amount_paise']
    else:
        bill=_bill(db,d);_,pol,expense,ap=_policy(db,bill.entity_id)
        source, bank = _supplier_payment_source(db, bill.entity_id, d, actor)
        accounts = (ap, source)
        event = 'SUPPLIER_PAYMENT_POSTED' if bank else SUPPLIER_CASH_PAYMENT_EVENT
        amount=d['amount_paise']
    return {'event':event,'currency':'INR','policy_version':pol.policy_version,
            **{field: d[field] for field in (BILL_DATE_FIELDS if typ=='finance_bill' else PAYMENT_DATE_FIELDS)},
            'journal_lines':[{'side':'debit','account_code':accounts[0].code,'amount_paise':amount},
                             {'side':'credit','account_code':accounts[1].code,'amount_paise':amount}],
            'balanced':True,'requires_ticket_approval':True,
            **({'warnings': supplier_payment_warnings(db, d)} if event == SUPPLIER_CASH_PAYMENT_EVENT else {}),
            'bank_reconciled':False if event=='SUPPLIER_PAYMENT_POSTED' else None}


def apply_item(db:Session,item,actor):
    typ=item.item_type;d=item.after_data
    if typ in ('finance_transfer', 'finance_reverse_transfer', 'finance_manual_journal', 'finance_reverse_manual_journal'):
        from .transfers_journals import apply
        return apply(db, item, actor)
    if typ in ('finance_bank_rule', 'finance_unreconcile_bank'):
        from .bank_feed import apply as bf_apply
        return bf_apply(db, item, actor)
    if typ == 'finance_attach_document':
        from .finance_attachments import apply as att_apply
        return att_apply(db, item, actor)
    if typ in ('sales_quote', 'sales_accept_quote'):
        from .sales_quotes import apply as sq_apply
        return sq_apply(db, item, actor)
    if typ in ('sales_invoice', 'sales_reverse_invoice'):
        from .sales_invoices import apply as si_apply
        return si_apply(db, item, actor)
    if typ in ('sales_receipt', 'sales_reverse_receipt', 'sales_advance', 'sales_allocate_advance'):
        from .sales_receipts import apply as sr_apply
        return sr_apply(db, item, actor)
    if typ in ('finance_direct_bill', 'finance_reverse_direct_bill', 'finance_direct_bill_payment', 'finance_reverse_direct_bill_payment'):
        from .direct_bills import apply
        return apply(db, item, actor)
    if typ == 'finance_expense_category':
        from .expense_categories import apply

        return apply(db, item, actor)
    if typ == 'finance_petty_cash_topup':
        from .petty_cash import apply

        return apply(db, item, actor)
    if typ == 'finance_reverse_petty_cash_topup':
        from .petty_cash import apply_reverse

        return apply_reverse(db, item, actor)
    if typ in ('finance_migrate_expenses', 'finance_reverse_expense_migration') or typ in LEGACY_BALANCE_PAYMENT_FIELDS:
        from .legacy_expense_migration import apply

        return apply(db, item, actor)
    if typ == 'finance_expense':
        from .expense_entry import apply
        return apply(db, item, actor)
    if typ == 'finance_reimburse_staff':
        from .staff_reimbursements import pay
        return pay(db, item, actor)
    if typ == 'finance_reverse_staff_payment':
        from .staff_reimbursements import reverse_payment
        return reverse_payment(db, item, actor)
    if typ == 'finance_reverse_expense':
        from .expense_entry import reverse
        return reverse(db, item, actor)
    validate_finance_item(db,typ,d)
    if typ=='finance_project_company':
        from .site_expense import validate_project_company

        db.scalar(select(AccountingEntity.id).where(AccountingEntity.id==d['entity_id']).with_for_update())
        db.scalar(select(Project.id).where(Project.id==d['project_id']).with_for_update())
        validate_project_company(db,d)
        obj=FinanceProjectCompany(project_id=d['project_id'],entity_id=d['entity_id'],ticket_id=item.ticket_id)
        db.add(obj);db.flush();rid=obj.id;kind='finance_project_company'
    elif typ=='finance_enable_cash':
        db.scalar(select(AccountingEntity.id).where(AccountingEntity.id==d['entity_id']).with_for_update())
        validate_finance_item(db,typ,d)
        obj=GLAccount(entity_id=d['entity_id'],code=CASH_CODE,name=CASH_NAME,kind='cash')
        db.add(obj);db.flush();rid=obj.id;kind='gl_account'
    elif typ=='finance_enable_inventory':
        db.scalar(select(AccountingEntity).where(AccountingEntity.id==d['entity_id']).with_for_update())
        validate_finance_item(db,typ,d)
        accounts=[]
        for code,name,kind_name in ((d['inventory_code'],'Material Inventory','inventory'),
                                    (d['grni_code'],'Goods Received Not Invoiced','grni')):
            account=GLAccount(entity_id=d['entity_id'],code=code,name=name,kind=kind_name)
            db.add(account);db.flush();accounts.append(account)
        obj=FinanceInventoryPolicy(entity_id=d['entity_id'],inventory_account_id=accounts[0].id,
                  grni_account_id=accounts[1].id,ticket_id=item.ticket_id)
        db.add(obj);db.flush();rid=obj.id;kind='inventory_policy'
    elif typ=='finance_goods_receipt':
        po_ref=db.get(FinancePurchaseOrder,d['po_id'])
        if not po_ref:raise ValueError('Approved PO required')
        db.scalar(select(AccountingEntity).where(AccountingEntity.id==po_ref.entity_id).with_for_update())
        po=db.scalar(select(FinancePurchaseOrder).where(FinancePurchaseOrder.id==po_ref.id).with_for_update())
        validate_finance_item(db,typ,d)
        _,inventory,grni=_inventory_policy(db,po.entity_id)
        _,policy,expense,ap=_policy(db,po.entity_id)
        qty=d['quantity'];rate=d['unit_cost_paise'];value=qty*rate
        obj=FinanceGoodsReceipt(po_id=po.id,quantity=qty,unit_cost_paise=rate,total_paise=value,
            receipt_reference=d['receipt_reference'],idempotency_key=d['idempotency_key'],ticket_id=item.ticket_id)
        db.add(obj);db.flush()
        journal=_post(db,entity_id=po.entity_id,event_kind='GOODS_RECEIPT_GRNI',
            event_key=f'goods-receipt:{obj.id}',source_id=obj.id,debit_account=inventory.id,
            credit_account=grni.id,amount=value,project_id=po.project_id,supplier_id=po.supplier_id,
            ticket_id=item.ticket_id,policy_version=policy.policy_version)
        obj.journal_id=journal.id;rid=obj.id;kind='goods_receipt'
    elif typ=='finance_material_issue':
        po_ref=db.get(FinancePurchaseOrder,d['po_id'])
        if not po_ref:raise ValueError('Approved PO required')
        db.scalar(select(AccountingEntity).where(AccountingEntity.id==po_ref.entity_id).with_for_update())
        po=db.scalar(select(FinancePurchaseOrder).where(FinancePurchaseOrder.id==po_ref.id).with_for_update())
        validate_finance_item(db,typ,d)
        _,inventory,grni=_inventory_policy(db,po.entity_id)
        _,policy,expense,ap=_policy(db,po.entity_id)
        qty=d['quantity'];value=qty*_stock(db,po.id)['unit_cost_paise']
        obj=FinanceMaterialIssue(po_id=po.id,quantity=qty,amount_paise=value,
            issue_reference=d['issue_reference'],idempotency_key=d['idempotency_key'],ticket_id=item.ticket_id)
        db.add(obj);db.flush()
        journal=_post(db,entity_id=po.entity_id,event_kind='MATERIAL_CONSUMED',
            event_key=f'material-issue:{obj.id}',source_id=obj.id,debit_account=expense.id,
            credit_account=inventory.id,amount=value,project_id=po.project_id,supplier_id=po.supplier_id,
            ticket_id=item.ticket_id,policy_version=policy.policy_version)
        obj.journal_id=journal.id;rid=obj.id;kind='material_issue'
    elif typ=='finance_bank_statement_line':
        bank=db.get(RegisteredBank,d['bank_id'])
        _bank_entity_lock(db,bank.entity_id)
        validate_finance_item(db,typ,d)
        obj=FinanceBankStatementLine(bank_id=d['bank_id'],booking_date=d['booking_date'],
            signed_amount_paise=d['signed_amount_paise'],statement_reference=d['statement_reference'],
            evidence_document_id=d['evidence_document_id'],
            evidence_sha256=_statement_evidence_hash(db.get(Document,d['evidence_document_id'])),
            ticket_id=item.ticket_id)
        db.add(obj);db.flush();rid=obj.id;kind='bank_statement_line'
    elif typ=='finance_reconcile_bank':
        statement=db.get(FinanceBankStatementLine,d['statement_line_id'])
        if not statement:raise ValueError('Statement line required')
        bank=db.get(RegisteredBank,statement.bank_id)
        _bank_entity_lock(db,bank.entity_id)
        validate_finance_item(db,typ,d)
        obj=FinanceBankReconciliation(statement_line_id=statement.id,
            journal_id=d['journal_id'],ticket_id=item.ticket_id)
        db.add(obj);db.flush();rid=obj.id;kind='bank_reconciliation'
    elif typ=='finance_enable_advances':
        db.scalar(select(AccountingEntity).where(AccountingEntity.id==d['entity_id']).with_for_update())
        validate_finance_item(db,typ,d)
        a=GLAccount(entity_id=d['entity_id'],code=d['advance_code'],name='Supplier Advances - Asset',kind='advance')
        db.add(a);db.flush()
        obj=FinanceAdvancePolicy(entity_id=d['entity_id'],advances_gl_account_id=a.id,ticket_id=item.ticket_id)
        db.add(obj);db.flush();rid=obj.id;kind='supplier_advance_policy'
    elif typ=='finance_advance':
        db.scalar(select(AccountingEntity).where(AccountingEntity.id==d['entity_id']).with_for_update())
        from .expense_entry import submitter

        requester = submitter(db, item) if 'paid_through_id' in d else None
        db.info.pop('_period_locks', None)
        validate_finance_item(db,typ,d,requester)
        _,asset=_advance_policy(db,d['entity_id'])
        source, bank = _supplier_payment_source(db, d['entity_id'], d, requester)
        fields = dict(entity_id=d['entity_id'], supplier_id=d['supplier_id'], project_id=d['project_id'],
                      amount_paise=d['amount_paise'], payment_reference=d['payment_reference'],
                      idempotency_key=d['idempotency_key'], ticket_id=item.ticket_id, payment_date=d.get('payment_date'))
        if bank:
            obj = FinanceSupplierAdvance(bank_id=bank.id, **fields)
            kind, event, prefix = 'supplier_advance', 'SUPPLIER_ADVANCE_PAID', 'advance'
        else:
            obj = FinanceSupplierCashAdvance(paid_through_id=source.id, **fields)
            kind, event, prefix = 'supplier_cash_advance', SUPPLIER_CASH_ADVANCE_EVENT, 'cash-advance'
        db.add(obj);db.flush()
        policy=db.scalar(select(AccountingPolicy).where(AccountingPolicy.entity_id==obj.entity_id))
        j=_post(db,entity_id=obj.entity_id,event_kind=event,event_key=f'{prefix}:{obj.id}',
            source_id=obj.id,debit_account=asset.id,credit_account=source.id,amount=obj.amount_paise,
            project_id=obj.project_id,supplier_id=obj.supplier_id,ticket_id=item.ticket_id,
            policy_version=policy.policy_version)
        obj.journal_id=j.id;rid=obj.id
    elif typ=='finance_allocate_advance':
        advance, cash = _advance_for_allocation(db, d)
        db.scalar(select(AccountingEntity).where(AccountingEntity.id==advance.entity_id).with_for_update())
        model = type(advance)
        advance=db.scalar(select(model).where(model.id==advance.id).with_for_update())
        bill=db.scalar(select(FinanceSupplierBill).where(FinanceSupplierBill.id==d['bill_id']).with_for_update())
        validate_finance_item(db,typ,d)
        allocation = FinanceCashAdvanceAllocation if cash else FinanceAdvanceAllocation
        obj=allocation(advance_id=advance.id,bill_id=bill.id,amount_paise=d['amount_paise'],
            idempotency_key=d['idempotency_key'],ticket_id=item.ticket_id,journal_id=None)
        db.add(obj);db.flush()
        po=db.get(FinancePurchaseOrder,bill.po_id)
        _,asset=_advance_policy(db,bill.entity_id)
        _,policy,expense,ap=_policy(db,bill.entity_id)
        prefix = 'cash-advance-allocated' if cash else 'advance-allocated'
        event = 'CASH_ADVANCE_ALLOCATED' if cash else 'ADVANCE_ALLOCATED'
        j=_post(db,entity_id=bill.entity_id,event_kind=event,event_key=f'{prefix}:{obj.id}',
            source_id=obj.id,debit_account=ap.id,credit_account=asset.id,amount=obj.amount_paise,
            project_id=po.project_id,supplier_id=bill.supplier_id,ticket_id=item.ticket_id,
            policy_version=policy.policy_version)
        obj.journal_id=j.id;rid=obj.id;kind='supplier_cash_advance_allocation' if cash else 'supplier_advance_allocation'
    elif typ=='finance_close_period':
        db.scalar(select(AccountingEntity).where(AccountingEntity.id==d['entity_id']).with_for_update())
        validate_finance_item(db,typ,d)
        from .finance_assurance import ledger_integrity
        assurance=ledger_integrity(db,d['entity_id'])
        if not assurance['passed']:
            raise ValueError('Period closure blocked by financial integrity findings: '+
                             ', '.join(x['code'] for x in assurance['findings'][:5]))
        tb=trial_balance(db,d['entity_id'])
        if tb['total_debit_paise']!=tb['total_credit_paise']:
            raise ValueError('Unbalanced ledger prevents period closure')
        obj=ClosedAccountingPeriod(entity_id=d['entity_id'],year_month=d['year_month'],ticket_id=item.ticket_id)
        db.add(obj);db.flush();rid=obj.id;kind='closed_accounting_period'
    elif typ in ('finance_reverse_payment','finance_reverse_bill'):
        is_payment=typ=='finance_reverse_payment'
        if is_payment:
            payment = _payment_to_reverse(db, d)
            bill=db.get(FinanceSupplierBill,payment.bill_id)
            model, row_id = type(payment), payment.id
        else:
            bill=db.get(FinanceSupplierBill,d['bill_id'])
            model, row_id = FinanceSupplierBill, bill.id
        db.scalar(select(AccountingEntity).where(AccountingEntity.id==bill.entity_id).with_for_update())
        original_obj=db.scalar(select(model).where(model.id==row_id).with_for_update())
        validate_finance_item(db,typ,d)
        obj=_reverse_posted(db,original_obj.journal_id,d['reason'],item.ticket_id)
        rid=obj.id;kind='reversing_journal'
    elif typ=='finance_setup':
        obj=AccountingEntity(name=d['entity_name'],base_currency='INR',created_ticket_id=item.ticket_id)
        db.add(obj);db.flush()
        accounts={}
        for name,code,kind in (('Material Purchases / Project Expense',d['expense_code'],'expense'),
                               ('Accounts Payable — Suppliers',d['ap_code'],'payable'),
                               (d['bank_name'],d['bank_code'],'bank'),
                               (CASH_NAME,CASH_CODE,'cash')):
            a=GLAccount(entity_id=obj.id,code=code,name=name,kind=kind)
            db.add(a);db.flush();accounts[kind]=a
        db.add(AccountingPolicy(entity_id=obj.id,expense_account_id=accounts['expense'].id,
               payable_account_id=accounts['payable'].id,approval_ticket_id=item.ticket_id))
        db.add(RegisteredBank(entity_id=obj.id,display_name=d['bank_name'],masked_identifier=d['bank_masked'],
                               gl_account_id=accounts['bank'].id))
        rid=obj.id;kind='accounting_entity'
    elif typ=='finance_open_petty_cash':
        from .chart_of_accounts import _code_for

        entity_id = d['entity_id']
        db.scalar(select(AccountingEntity.id).where(AccountingEntity.id == entity_id).with_for_update())
        custodian = petty_cash_custodian(db, d)
        name = f'Petty cash for {custodian.display_name or custodian.username}'
        code = _code_for(db, entity_id, f'PETTY_CASH_{custodian.id}')
        account = GLAccount(entity_id=entity_id, code=code, name=name, kind='cash')
        db.add(account)
        db.flush()
        db.add(FinancePettyCashAccount(account_id=account.id, entity_id=entity_id,
                                     user_id=custodian.id, ticket_id=item.ticket_id))
        rid = account.id
        kind = 'gl_account'
    elif typ=='finance_po':
        _require_owner_for_po(db,item,d)
        obj=FinancePurchaseOrder(entity_id=d['entity_id'],supplier_id=d['supplier_id'],project_id=d['project_id'],
               po_number=d['po_number'],amount_paise=d['amount_paise'],ticket_id=item.ticket_id)
        db.add(obj);db.flush();rid=obj.id;kind='purchase_order'
        from .po_models import PoLine
        for ln in d.get('lines') or []:
            db.add(PoLine(po_id=obj.id,item=ln['item'].strip(),qty=ln['qty'],unit_rate_paise=ln['unit_rate_paise'],estimate_qty=ln.get('estimate_qty')))
        db.flush()
    elif typ in ('finance_bill','finance_inventory_bill'):
        po_ref=db.get(FinancePurchaseOrder,d['po_id'])
        db.scalar(select(AccountingEntity).where(AccountingEntity.id==po_ref.entity_id).with_for_update())
        po=db.scalar(select(FinancePurchaseOrder).where(FinancePurchaseOrder.id==d['po_id']).with_for_update())
        db.info.pop('_period_locks', None)
        validate_finance_item(db,typ,d)
        obj=FinanceSupplierBill(po_id=po.id,entity_id=po.entity_id,supplier_id=po.supplier_id,
                invoice_number=d['invoice_number'],amount_paise=d['amount_paise'],ticket_id=item.ticket_id,
                **{field: d[field] for field in BILL_DATE_FIELDS})
        db.add(obj);db.flush()
        _,policy,expense,ap=_policy(db,po.entity_id)
        debit=(_inventory_policy(db,po.entity_id)[2] if typ=='finance_inventory_bill' else expense)
        event_kind='SUPPLIER_INVENTORY_BILL' if typ=='finance_inventory_bill' else 'SUPPLIER_BILL_ACCEPTED'
        j=_post(db,entity_id=po.entity_id,event_kind=event_kind,event_key=f'bill:{obj.id}',
              source_id=obj.id,debit_account=debit.id,credit_account=ap.id,amount=obj.amount_paise,
              project_id=po.project_id,supplier_id=po.supplier_id,ticket_id=item.ticket_id,
              policy_version=policy.policy_version)
        obj.journal_id=j.id;rid=obj.id;kind='supplier_bill'
    elif typ=='finance_payment':
        # Same entity lock serializes bank references shared with the supplier advances subsystem.
        bill_ref=db.get(FinanceSupplierBill,d['bill_id'])
        if not bill_ref:raise ValueError('Posted supplier bill required')
        db.scalar(select(AccountingEntity).where(AccountingEntity.id==bill_ref.entity_id).with_for_update())
        bill=db.scalar(select(FinanceSupplierBill).where(FinanceSupplierBill.id==d['bill_id']).with_for_update())
        db.info.pop('_period_locks', None)
        from .expense_entry import submitter
        requester = submitter(db, item) if 'paid_through_id' in d else None
        validate_finance_item(db,typ,d,requester)
        po=db.get(FinancePurchaseOrder,bill.po_id)
        source, bank = _supplier_payment_source(db, bill.entity_id, d, requester)
        fields = dict(bill_id=bill.id, amount_paise=d['amount_paise'], payment_reference=d['payment_reference'],
                      idempotency_key=d['idempotency_key'], ticket_id=item.ticket_id, payment_date=d['payment_date'])
        if bank:
            obj = FinanceSupplierPayment(bank_id=bank.id, bank_reconciled=False, **fields)
            kind, event, prefix = 'supplier_payment', 'SUPPLIER_PAYMENT_POSTED', 'payment'
        else:
            obj = FinanceSupplierCashPayment(paid_through_id=source.id, **fields)
            kind, event, prefix = 'supplier_cash_payment', SUPPLIER_CASH_PAYMENT_EVENT, 'cash-payment'
        db.add(obj);db.flush()
        _,policy,expense,ap=_policy(db,bill.entity_id)
        j=_post(db,entity_id=bill.entity_id,event_kind=event,
                event_key=f'{prefix}:{obj.id}',source_id=obj.id,debit_account=ap.id,
                credit_account=source.id,amount=obj.amount_paise,project_id=po.project_id,
                supplier_id=bill.supplier_id,ticket_id=item.ticket_id,policy_version=policy.policy_version)
        obj.journal_id=j.id;rid=obj.id
    else:raise ValueError('Unsupported financial event')
    add_audit(db,'finance_'+typ,kind,rid,f'Approved ticket #{item.ticket_id}; {typ}; journal via deterministic engine',actor=actor)
    return {'type':kind,'id':rid,'item_id':item.id,
            'journal_id':obj.id if typ in ('finance_reverse_payment','finance_reverse_bill') else obj.journal_id if typ in ('finance_bill','finance_inventory_bill','finance_payment','finance_advance','finance_allocate_advance','finance_goods_receipt','finance_material_issue') else None}


def trial_balance(db:Session,entity_id:int):
    if not db.get(AccountingEntity,entity_id):raise ValueError('Entity not found')
    accounts=db.scalars(select(GLAccount).where(GLAccount.entity_id==entity_id).order_by(GLAccount.code)).all()
    rows=db.execute(select(GLLine.account_id,GLLine.side,func.sum(GLLine.amount_paise))
         .join(GLJournal,GLJournal.id==GLLine.journal_id)
         .where(GLJournal.entity_id==entity_id,GLJournal.status=='posted')
         .group_by(GLLine.account_id,GLLine.side))
    balances={(aid,side):int(amount) for aid,side,amount in rows}
    result=[]
    for a in accounts:
        net=balances.get((a.id,'debit'),0)-balances.get((a.id,'credit'),0)
        result.append({'code':a.code,'name':a.name,'kind':a.kind,
                       'debit_paise':max(0,net),'credit_paise':max(0,-net)})
    return {'entity_id':entity_id,'currency':'INR','accounts':result,
            'total_debit_paise':sum(x['debit_paise'] for x in result),
            'total_credit_paise':sum(x['credit_paise'] for x in result),
            'basis':'posted GL only; no legacy costs or payments included'}

"""Resolve Ask's purchase details to existing Books references for ticket review."""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy import select

from .access import can_access_project, visible_project_ids
from .chart_of_accounts import local_today
from .db import (
    AccountingPolicy, FinanceDirectBill, FinanceDirectBillLine, FinanceExpense, FinancePurchaseOrder, FinanceReversal,
    FinanceSupplierBill, Party, Project,
)
from .expense_entry import ASK_EXPENSE_REQUEST_PREFIX
from .finance_helpers import parse_amount, project_data, resolve_project
from .finance_text import read_entry
from .paid_through import list_accounts
from .party_access import visible_party_ids


PO_REFERENCE = re.compile(r'\b(?:PO|purchase order)\s*(?:number\s*|no\.?\s*|#\s*)?(?P<ref>(?=[\w-]*\d)[\w-]+)', re.I)
BILL_REFERENCE = re.compile(r'\b(?:bill|invoice)\s*(?:number\s*|no\.?\s*|#\s*)?(?P<ref>(?=[\w-]*\d)[\w-]+)', re.I)
PAYMENT_REFERENCE = re.compile(r'\b(?:ref(?:erence)?|transaction)\s*[:#]?\s*(?P<ref>(?=[\w-]*\d)[\w-]+)', re.I)
BILL_REQUEST = re.compile(r'^\s*(?:(?:record|log|add)\s+)?(?:supplier|vendor)\s+bill\b', re.I)
PAYMENT_REQUEST = re.compile(r'^\s*(?:paid|pay|settled)\s+(?:against\s+)?(?:(?:supplier|vendor)\s+)?bill\b', re.I)
ORDER_REQUEST = re.compile(r'^\s*(?:(?:record|log|add)\s+)?(?:PO|purchase order)\b', re.I)
DUE_DATE = re.compile(r'\bdue\s+(?:on\s+)?(\d{4}-\d{2}-\d{2})\b', re.I)
RUPEES = r'(?:₹\s*)?\d[\d,]*(?:\.\d{1,2})?'
CORRECTION_REQUEST = re.compile(rf'^\s*correction\s*:\s*.+?\bwas\s+({RUPEES})\s*,?\s+not\s+({RUPEES})(?![\d,]|\.\d)', re.I)


def _visible_vendors(db, user):
    allowed = visible_project_ids(db, user)
    permitted = visible_party_ids(db, user, allowed)
    query = select(Party).where(Party.kind == 'vendor', Party.deleted_at.is_(None))
    if permitted is not None:
        query = query.where(Party.id.in_(permitted))
    return db.scalars(query)


def _vendor(db, user, name):
    if not isinstance(name, str) or not name.strip():
        return None
    named = name.strip().casefold()
    matches = [party for party in _visible_vendors(db, user) if party.name.casefold() == named]
    return matches[0] if len(matches) == 1 else None


def _reference(pattern, message):
    match = pattern.search(message)
    return match.group('ref') if match else None


def _paying_account(db, user, entity_id, mode, message, *, for_expense=False):
    source_kind = {
        'cash': 'cash', 'petty_cash': 'petty_cash', 'upi': 'bank',
        'bank': 'bank', 'bank_transfer': 'bank', 'cheque': 'bank',
    }.get(mode)
    if entity_id is None or source_kind is None:
        return None
    sources = [source for source in list_accounts(db, entity_id, user, for_expense=for_expense)
               if source['kind'] == source_kind]
    if len(sources) > 1:
        sources = [source for source in sources if re.search(
            r'(?<!\w)' + re.escape(source['name']) + r'(?!\w)', message, re.I,
        )]
    return sources[0]['id'] if len(sources) == 1 else None


def purchase_draft(db, user, data, message, source_id, position):
    """Convert parsed language into a new Books draft, leaving unknown values unset."""
    project = resolve_project(db, data.get('project'))
    if project is not None and not can_access_project(db, user, project.id):
        project = None
    project_id = project.id if project else None
    entity_id = project.company_id if project else None
    supplier = _vendor(db, user, data.get('vendor'))
    vendor_id = supplier.id if supplier else None
    amount = data.get('amount_paise')
    questions = []
    if project is not None and entity_id is None:
        questions.append('Set up the company in Books first.')
    if data.get('kind') == 'commitment':
        if project is None:
            questions.append('project')
        if vendor_id is None:
            questions.append('vendor')
        reference = _reference(PO_REFERENCE, message)
        if reference is None:
            questions.append('What is the purchase order number?')
        return 'finance_po', {
            'entity_id': entity_id, 'project_id': project_id, 'supplier_id': vendor_id,
            'amount_paise': amount, 'po_number': reference,
        }, questions

    policy = db.scalar(select(AccountingPolicy).where(AccountingPolicy.entity_id == entity_id)) if entity_id else None
    paid_through = _paying_account(db, user, entity_id, data.get('payment_mode'), message, for_expense=True)
    expense_account_id = policy.expense_account_id if policy else None
    category_id = None
    raw_category = data.get('category')
    if entity_id is not None and isinstance(raw_category, str) and raw_category.strip():
        from .expense_categories import categories as active_expense_categories

        wanted = ' '.join(raw_category.split()).casefold()
        matched_cat = next(
            (row for row in active_expense_categories(db, entity_id) if row['name'].casefold() == wanted),
            None,
        )
        if matched_cat is not None:
            category_id = matched_cat['id']
            expense_account_id = matched_cat['expense_account_id']
    draft = {
        'project_id': project_id, 'vendor_id': vendor_id, 'amount_paise': amount,
        'paid_through_id': paid_through, 'expense_account_id': expense_account_id,
        'date': data.get('date') or local_today().isoformat(),
        'note': (data.get('title') if category_id is not None and data.get('title') else (data.get('category') or data.get('title') or ''))[:400],
        'request_key': f'{ASK_EXPENSE_REQUEST_PREFIX}{source_id}:{position}',
    }
    if category_id is not None:
        draft['category_id'] = category_id
    return 'finance_expense', draft, questions


def expense_card_fields(db, user, data):
    projects = select(Project).where(Project.deleted_at.is_(None), Project.company_id.is_not(None))
    allowed = visible_project_ids(db, user)
    if allowed is not None:
        projects = projects.where(Project.id.in_(allowed))
    rows = db.scalars(projects.order_by(Project.name, Project.id)).all()
    companies = {project.company_id for project in rows if data.get('project_id') in (None, project.id)}
    sources = [source for company in sorted(companies) for source in list_accounts(db, company, user, for_expense=True)]
    return {
        'project_id': [{'label': row.name, 'value': row.id} for row in rows if row.company_id in companies],
        'vendor_id': [{'label': row.name, 'value': row.id}
                      for row in sorted(_visible_vendors(db, user), key=lambda row: (row.name.casefold(), row.id))],
        'paid_through_id': [{'label': row['name'], 'value': row['id']} for row in sources],
    }


def is_ask_expense(data):
    return str(data.get('request_key', '')).startswith(ASK_EXPENSE_REQUEST_PREFIX)


def set_expense_account(db, actor, data):
    """Resolve the approved default account after the reviewer selects a project."""
    project_id = data.get('project_id')
    project = db.get(Project, project_id) if type(project_id) is int else None
    if project is None or project.deleted_at or not can_access_project(db, actor, project.id):
        raise ValueError('Choose a project you can access.')
    if not any(vendor.id == data.get('vendor_id') for vendor in _visible_vendors(db, actor)):
        raise ValueError('Choose an active vendor you can access.')
    policy = db.scalar(select(AccountingPolicy).where(AccountingPolicy.entity_id == project.company_id))
    if policy is None:
        raise ValueError('Set up the project company in Books first.')
    data['expense_account_id'] = policy.expense_account_id


def _order_by_number(db, user, number, project, supplier):
    query = select(FinancePurchaseOrder).where(FinancePurchaseOrder.po_number == number,
                                               FinancePurchaseOrder.status == 'approved')
    if project:
        query = query.where(FinancePurchaseOrder.project_id == project.id)
    if supplier:
        query = query.where(FinancePurchaseOrder.supplier_id == supplier.id)
    matches = [row for row in db.scalars(query) if can_access_project(db, user, row.project_id)]
    return matches[0] if len(matches) == 1 else None


def _payment_draft(db, user, message, source_id, slots, supplier, project):
    number = _reference(BILL_REFERENCE, message)
    reference = _reference(PAYMENT_REFERENCE, message)
    matches = []
    allowed = visible_project_ids(db, user)
    if number:
        for model in (FinanceSupplierBill, FinanceDirectBill):
            query = select(model).where(
                model.invoice_number == number, model.journal_id.is_not(None),
                ~select(FinanceReversal.id).where(FinanceReversal.original_journal_id == model.journal_id).exists(),
            )
            if supplier:
                query = query.where(model.supplier_id == supplier.id)
            if model is FinanceSupplierBill:
                query = query.join(FinancePurchaseOrder, FinanceSupplierBill.po_id == FinancePurchaseOrder.id)
                if project:
                    query = query.where(FinancePurchaseOrder.project_id == project.id)
                if allowed is not None:
                    query = query.where(FinancePurchaseOrder.project_id.in_(allowed))
            else:
                lines = select(FinanceDirectBillLine.id).where(FinanceDirectBillLine.bill_id == model.id)
                if project:
                    query = query.where(lines.where(FinanceDirectBillLine.project_id == project.id).exists())
                if allowed is not None:
                    query = query.where(~lines.where(~FinanceDirectBillLine.project_id.in_(allowed)).exists(),
                                        lines.where(FinanceDirectBillLine.project_id.in_(allowed)).exists())
            matches.extend(db.scalars(query))
    if len(matches) != 1:
        return None, None, ['Which posted bill does the payment belong to?']
    bill = matches[0]
    paying_account = _paying_account(db, user, bill.entity_id, slots.get('settlement'), message)
    data = {'bill_id': bill.id, 'amount_paise': slots.get('amount'), 'paid_through_id': paying_account,
            'payment_reference': reference, 'payment_date': slots.get('date') or local_today().isoformat(),
            'idempotency_key': f'ask-payment:{source_id}'}
    questions = [question for field, question in (
        ('amount_paise', 'What was the payment amount?'),
        ('paid_through_id', 'Which account paid the bill?'),
        ('payment_reference', 'What is the payment reference?'),
    ) if data[field] is None]
    kind = 'finance_direct_bill_payment' if isinstance(bill, FinanceDirectBill) else 'finance_payment'
    return kind, data, questions


def _correction_draft(db, user, message, match, supplier, project):
    if supplier is None:
        return None, None, ['Which supplier’s posted expense should be corrected?']
    try:
        new_amount, original_amount = map(parse_amount, match.groups())
    except ValueError as error:
        return None, None, [str(error)]
    query = select(FinanceExpense).where(
        FinanceExpense.vendor_id == supplier.id, FinanceExpense.amount_paise == original_amount,
        ~select(FinanceReversal.id).where(FinanceReversal.original_journal_id == FinanceExpense.journal_id).exists(),
    )
    if project:
        query = query.where(FinanceExpense.project_id == project.id)
    allowed = visible_project_ids(db, user)
    if allowed is not None:
        query = query.where(FinanceExpense.project_id.in_(allowed))
    matches = db.scalars(query.limit(2)).all()
    if len(matches) != 1:
        return None, None, ['I could not identify one posted expense. Open Books to choose it before correcting it.']
    return 'finance_correct_expense', {
        'expense_id': matches[0].id, 'before_amount_paise': original_amount,
        'amount_paise': new_amount, 'reason': message.strip()[:400], 'note': matches[0].note,
    }, []


def supplier_document_draft(db, user, message, source_id):
    """Keep explicit bill, payment and PO requests out of the generic chat parser."""
    payment = PAYMENT_REQUEST.match(message)
    bill = BILL_REQUEST.match(message)
    order = ORDER_REQUEST.match(message)
    correction = CORRECTION_REQUEST.match(message)
    if not (payment or bill or order or correction):
        return None
    from .security import FINANCE_WRITE

    if user.role not in FINANCE_WRITE:
        return None, None, ['Ask accounts to record this in Books.']
    projects = project_data(db, visible_project_ids(db, user), include_money=False)
    text_for_amount = message
    for pattern in (PO_REFERENCE, BILL_REFERENCE, PAYMENT_REFERENCE, DUE_DATE):
        text_for_amount = pattern.sub(' ', text_for_amount)
    slots = read_entry(text_for_amount, [project['name'] for project in projects], local_today())
    project = resolve_project(db, slots.get('project'))
    suppliers = [party for party in _visible_vendors(db, user) if re.search(
        r'(?<!\w)' + re.escape(party.name) + r'(?!\w)', message, re.I,
    )]
    supplier = suppliers[0] if len(suppliers) == 1 else None
    if correction:
        return _correction_draft(db, user, message, correction, supplier, project)
    if payment:
        return _payment_draft(db, user, message, source_id, slots, supplier, project)
    amount = slots.get('amount')
    if order:
        return purchase_draft(db, user, {
            'project': project.id if project else None, 'vendor': supplier.name if supplier else None,
            'kind': 'commitment', 'amount_paise': amount,
        }, message, source_id, 0)

    number = _reference(BILL_REFERENCE, message)
    due_match = DUE_DATE.search(message)
    bill_date = slots.get('date')
    try:
        due_date = date.fromisoformat(due_match.group(1)) if due_match else None
    except ValueError:
        due_date = None
    terms = (due_date - date.fromisoformat(bill_date)).days if due_date and bill_date else None
    due_date = due_date.isoformat() if due_date else None
    data = {'invoice_number': number, 'bill_date': bill_date, 'due_date': due_date,
            'payment_terms_days': terms, 'amount_paise': amount}
    questions = [question for field, question in (
        ('invoice_number', 'What is the supplier invoice number?'), ('bill_date', 'What is the bill date?'),
        ('due_date', 'When is the bill due?'), ('amount_paise', 'What is the bill total?'),
    ) if data[field] is None]
    order_number = _reference(PO_REFERENCE, message)
    if order_number:
        purchase_order = _order_by_number(db, user, order_number, project, supplier)
        if purchase_order is None:
            questions.append('Which approved purchase order does this bill belong to?')
        return 'finance_bill', {**data, 'po_id': purchase_order.id if purchase_order else None}, questions
    entity_id = project.company_id if project else None
    policy = db.scalar(select(AccountingPolicy).where(AccountingPolicy.entity_id == entity_id)) if entity_id else None
    if project is None:
        questions.append('Which project is this bill for?')
    if supplier is None:
        questions.append('Which supplier sent the bill?')
    return 'finance_direct_bill', {
        **data, 'entity_id': entity_id, 'supplier_id': supplier.id if supplier else None,
        'request_key': f'ask-direct-bill:{source_id}', 'lines': [{
            'project_id': project.id if project else None, 'account_id': policy.expense_account_id if policy else None,
            'amount_paise': amount,
        }],
    }, questions

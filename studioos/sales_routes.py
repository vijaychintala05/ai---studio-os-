"""Sales routes (M3): Quotes/Estimates, Client Invoices, Receipts & Retainers, Credit/Debit Notes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .access import visible_project_ids
from .chart_of_accounts import chart_rows
from .db import (AccountingEntity, AccountingPolicy, FinanceReversal, FinanceTaxSetting, GLAccount,
                 Party, Project, SalesAdvance, SalesInvoice, SalesInvoiceLine, SalesQuote,
                 SalesQuoteAcceptance, SalesQuoteLine, SalesReceipt, User)
from .deps import get_db
from .project_links import CLIENT_KINDS
from .security import FINANCE_READ, FINANCE_WRITE, permit
from .universal_engine import _today

router = APIRouter(prefix='/api/sales', tags=['Sales'])


def _named_account(accounts, kinds, codes, names):
    eligible = [account for account in accounts if account.kind in kinds]
    configured = [account.id for account in eligible if account.code.upper() in codes]
    matches = configured or [account.id for account in eligible if account.name.strip().casefold() in names]
    return matches[0] if len(matches) == 1 else None


def _choice(row):
    return {'id': row.id, 'name': row.name}


@router.get('/options')
def sales_options(user: User = Depends(permit(*FINANCE_READ)), db: Session = Depends(get_db)):
    """Return the minimum data needed to fill the Sales and Receipts forms."""
    allowed = visible_project_ids(db, user)
    projects = select(Project).where(Project.deleted_at.is_(None)).order_by(Project.name, Project.id)
    if allowed is not None:
        projects = projects.where(Project.id.in_(allowed))
    clients, vendors = [], []
    for party in db.scalars(select(Party).where(Party.deleted_at.is_(None),
            Party.kind.in_((*CLIENT_KINDS, 'vendor'))).order_by(Party.name, Party.id)):
        state_code = (party.gstin or '')[:2]
        choice = {**_choice(party), 'state_code': state_code if len(state_code) == 2 and state_code.isascii()
                  and state_code.isdecimal() else None}
        if party.kind in CLIENT_KINDS:
            clients.append(choice)
        if party.kind == 'vendor':
            vendors.append(choice)

    active_accounts = {}
    for account in db.scalars(select(GLAccount).where(GLAccount.active.is_(True),
            GLAccount.posting_allowed.is_(True)).order_by(GLAccount.name, GLAccount.id)):
        active_accounts.setdefault(account.entity_id, []).append(account)
    tax_states = dict(db.execute(select(FinanceTaxSetting.entity_id, FinanceTaxSetting.state_code)
                                 .order_by(FinanceTaxSetting.id)).all())
    policies = {row.entity_id: row for row in db.scalars(select(AccountingPolicy))}
    companies = []
    for entity in db.scalars(select(AccountingEntity).order_by(AccountingEntity.name, AccountingEntity.id)):
        accounts = active_accounts.get(entity.id, [])
        ids = {account.id for account in accounts}
        party_accounts = {}
        for account in chart_rows(db, entity.id).values():
            if account['postable'] and account['party_id'] and account['kind'] in ('debtor', 'creditor'):
                party_accounts.setdefault((account['kind'], account['party_id']), []).append(account['id'])
        policy = policies.get(entity.id)
        income = [account.id for account in accounts if account.kind == 'income']
        design = _named_account(accounts, ('income',), ('DESIGN_FEES',), ('design fees', 'design consultancy fees'))
        turnkey = _named_account(accounts, ('income',), ('TURNKEY_REVENUE',), ('turnkey revenue', 'turnkey project revenue'))
        tax_kinds = ('output_tax', 'liability')
        defaults = {
            'receivable': _named_account(accounts, ('asset', 'debtor'), ('ACCOUNTS_RECEIVABLE', 'AR_CONTROL'), ('accounts receivable',)),
            'design_income': design,
            'turnkey_income': turnkey,
            'income': income[0] if len(income) == 1 else None,
            'cgst': _named_account(accounts, tax_kinds, ('OUTPUT_CGST',), ('output cgst',)),
            'sgst': _named_account(accounts, tax_kinds, ('OUTPUT_SGST',), ('output sgst',)),
            'igst': _named_account(accounts, tax_kinds, ('OUTPUT_IGST',), ('output igst',)),
            'rounding': _named_account(accounts, ('expense', 'income'), ('ROUNDING_OFF',), ('rounding off',)),
            'tds_receivable': _named_account(accounts, ('asset',), ('TDS_RECEIVABLE',), ('tds receivable',)),
            'client_advance': _named_account(accounts, ('liability',), ('CLIENT_ADVANCES',), ('client advances', 'advances from clients')),
            'payable': policy.payable_account_id if policy and policy.payable_account_id in ids else None,
            'expense': policy.expense_account_id if policy and policy.expense_account_id in ids else None,
        }
        companies.append({**_choice(entity), 'state_code': tax_states.get(entity.id, '29'), 'accounts': defaults,
                          'client_accounts': {party: matches[0] for (kind, party), matches in party_accounts.items()
                                              if kind == 'debtor' and len(matches) == 1},
                          'vendor_accounts': {party: matches[0] for (kind, party), matches in party_accounts.items()
                                              if kind == 'creditor' and len(matches) == 1},
                          'deposit_accounts': [_choice(a) for a in accounts if a.kind in ('bank', 'cash')],
                          'input_tax_accounts': [_choice(a) for a in accounts if a.kind == 'input_tax'],
                          'output_tax_accounts': [_choice(a) for a in accounts if a.id in
                                                  (defaults['cgst'], defaults['sgst'], defaults['igst'])],
                          'income_accounts': [_choice(a) for a in accounts if a.kind == 'income']})
    return {'companies': companies, 'clients': clients, 'vendors': vendors,
            'projects': [{**_choice(project), 'company_id': project.company_id, 'client_id': project.client_id}
                         for project in db.scalars(projects)], 'today': _today().isoformat()}


@router.get('/summary')
def sales_summary(entity_id: int, user: User = Depends(permit(*FINANCE_READ)), db: Session = Depends(get_db)):
    from .sales_receipts import advance_remaining

    if db.get(AccountingEntity, entity_id) is None:
        raise HTTPException(404, 'Company not found.')
    month = _today().isoformat()[:7] + '-%'
    receipts = db.scalar(select(func.sum(SalesReceipt.amount_paise))
                         .join(SalesInvoice, SalesInvoice.id == SalesReceipt.invoice_id)
                         .where(SalesInvoice.entity_id == entity_id, SalesReceipt.receipt_date.like(month),
                                SalesReceipt.journal_id.is_not(None), ~select(FinanceReversal.id).where(
                                    FinanceReversal.original_journal_id == SalesReceipt.journal_id).exists()))
    advances = db.scalars(select(SalesAdvance).where(SalesAdvance.entity_id == entity_id,
        SalesAdvance.journal_id.is_not(None), ~select(FinanceReversal.id).where(
            FinanceReversal.original_journal_id == SalesAdvance.journal_id).exists())).all()
    return {'collected_paise': (receipts or 0) + sum(a.amount_paise for a in advances if a.receipt_date.startswith(month[:7])),
            'unallocated_advance_paise': sum(advance_remaining(db, a.id) for a in advances)}


class QuoteLineIn(BaseModel):
    description: str = Field(min_length=1, max_length=250)
    sac_hsn: str = Field(default='', max_length=20)
    quantity: int = Field(ge=1)
    rate_paise: int = Field(gt=0)
    tax_rate_bps: int = Field(default=1800, ge=0, le=2800)


class QuoteIn(BaseModel):
    entity_id: int
    client_id: int | None = None
    project_id: int | None = None
    quote_number: str = Field(min_length=1, max_length=80)
    quote_date: str = Field(min_length=10, max_length=10)
    valid_until: str = Field(min_length=10, max_length=10)
    lines: list[QuoteLineIn] = Field(min_length=1, max_length=100)
    note: str = Field(default='', max_length=400)
    request_key: str | None = Field(default=None, max_length=120)


class AcceptQuoteIn(BaseModel):
    accepted_date: str = Field(min_length=10, max_length=10)
    note: str = Field(default='', max_length=300)
    request_key: str | None = Field(default=None, max_length=120)


@router.get('/quotes')
def list_quotes(entity_id: int | None = None, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """M3-0: List all versioned quotes with acceptance status."""
    stmt = select(SalesQuote).order_by(SalesQuote.id.desc())
    if entity_id is not None:
        stmt = stmt.where(SalesQuote.entity_id == entity_id)
    quotes = db.scalars(stmt).all()
    acc_map = {a.quote_id: a for a in db.scalars(select(SalesQuoteAcceptance)).all()}
    out = []
    for q in quotes:
        lines = db.scalars(select(SalesQuoteLine).where(SalesQuoteLine.quote_id == q.id).order_by(SalesQuoteLine.id)).all()
        acc = acc_map.get(q.id)
        out.append({
            'id': q.id, 'entity_id': q.entity_id, 'client_id': q.client_id, 'project_id': q.project_id,
            'quote_number': q.quote_number, 'version': q.version,
            'quote_date': q.quote_date, 'valid_until': q.valid_until,
            'subtotal_paise': q.subtotal_paise, 'tax_paise': q.tax_paise, 'total_paise': q.total_paise,
            'accepted': acc is not None, 'accepted_date': acc.accepted_date if acc else None,
            'note': q.note,
            'lines': [{'description': l.description, 'sac_hsn': l.sac_hsn, 'quantity': l.quantity,
                       'rate_paise': l.rate_paise, 'tax_rate_bps': l.tax_rate_bps,
                       'line_total_paise': l.line_total_paise} for l in lines],
        })
    return {'quotes': out}


@router.post('/quotes')
def create_quote_draft(v: QuoteIn, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """M3-0: Draft a versioned quote for approval (never posts to the ledger)."""
    from .main import _manual_draft
    payload = v.model_dump(exclude={'request_key'})
    try:
        return _manual_draft(db, user, 'sales_quote', payload,
                             evidence='Client quote drafted in Sales', request_key=v.request_key)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post('/quotes/{quote_id}/accept')
def accept_quote_draft(quote_id: int, v: AcceptQuoteIn, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """M3-0: Draft accepting a quote version (locks further revisions; never posts to the ledger)."""
    from .main import _manual_draft
    payload = {'quote_id': quote_id, 'accepted_date': v.accepted_date, 'note': v.note}
    try:
        return _manual_draft(db, user, 'sales_accept_quote', payload,
                             evidence='Client quote acceptance drafted in Sales', request_key=v.request_key)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


class InvoiceLineIn(BaseModel):
    income_account_id: int
    description: str = Field(min_length=1, max_length=250)
    sac_hsn: str = Field(default='', max_length=20)
    quantity: int = Field(ge=1)
    rate_paise: int = Field(gt=0)
    tax_rate_bps: int = Field(default=1800, ge=0, le=2800)


class InvoiceIn(BaseModel):
    entity_id: int
    client_id: int | None = None
    project_id: int | None = None
    quote_id: int | None = None
    invoice_number: str = Field(min_length=1, max_length=80)
    invoice_date: str = Field(min_length=10, max_length=10)
    due_date: str = Field(min_length=10, max_length=10)
    place_of_supply: str = Field(default='Karnataka (29)', max_length=40)
    supply_type: str = Field(default='intra', max_length=10)
    ar_account_id: int
    cgst_account_id: int | None = None
    sgst_account_id: int | None = None
    igst_account_id: int | None = None
    rounding_account_id: int | None = None
    lines: list[InvoiceLineIn] = Field(min_length=1, max_length=100)
    note: str = Field(default='', max_length=400)
    request_key: str | None = Field(default=None, max_length=120)
    expense_ids: list[int] = Field(default_factory=list, max_length=100)


def _invoice_dict(db: Session, inv: SalesInvoice, reversed_ids: set[int]) -> dict:
    lines = db.scalars(select(SalesInvoiceLine).where(SalesInvoiceLine.invoice_id == inv.id).order_by(SalesInvoiceLine.id)).all()
    ent = db.get(AccountingEntity, inv.entity_id)
    client = db.get(Party, inv.client_id)
    return {
        'id': inv.id, 'entity_id': inv.entity_id, 'company_name': ent.name if ent else '',
        'client_id': inv.client_id, 'client_name': client.name if client else '',
        'client_gstin': client.gstin if client else None,
        'project_id': inv.project_id, 'quote_id': inv.quote_id,
        'invoice_number': inv.invoice_number, 'invoice_date': inv.invoice_date,
        'due_date': inv.due_date, 'place_of_supply': inv.place_of_supply,
        'supply_type': inv.supply_type, 'subtotal_paise': inv.subtotal_paise,
        'cgst_paise': inv.cgst_paise, 'sgst_paise': inv.sgst_paise, 'igst_paise': inv.igst_paise,
        'rounding_paise': inv.rounding_paise, 'total_paise': inv.total_paise,
        'reversed': inv.journal_id in reversed_ids, 'journal_id': inv.journal_id, 'note': inv.note,
        'lines': [{'income_account_id': l.income_account_id, 'description': l.description,
                   'sac_hsn': l.sac_hsn, 'quantity': l.quantity, 'rate_paise': l.rate_paise,
                   'taxable_paise': l.taxable_paise, 'tax_rate_bps': l.tax_rate_bps,
                   'cgst_paise': l.cgst_paise, 'sgst_paise': l.sgst_paise,
                   'igst_paise': l.igst_paise, 'line_total_paise': l.line_total_paise} for l in lines],
    }


@router.get('/invoices')
def list_invoices(entity_id: int | None = None, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """M3-1: List posted client sales invoices."""
    from .sales_receipts import invoice_outstanding

    stmt = select(SalesInvoice).order_by(SalesInvoice.id.desc())
    if entity_id is not None:
        stmt = stmt.where(SalesInvoice.entity_id == entity_id)
    rev_ids = set(db.scalars(select(FinanceReversal.original_journal_id)).all())
    return {'invoices': [{**_invoice_dict(db, inv, rev_ids), 'owed_paise': invoice_outstanding(db, inv.id)}
                         for inv in db.scalars(stmt).all()]}


@router.post('/invoices')
def create_invoice_draft(v: InvoiceIn, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """M3-1: Draft a client sales invoice for approval (posts balanced GL on approval)."""
    from .main import _manual_draft
    payload = v.model_dump(exclude={'request_key'})
    if not payload.get('expense_ids'):
        payload.pop('expense_ids', None)
    try:
        return _manual_draft(db, user, 'sales_invoice', payload,
                             evidence='Client sales invoice drafted in Sales', request_key=v.request_key)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get('/invoices/{invoice_id}/pdf')
def sales_invoice_pdf(invoice_id: int, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """M3-1: Download A4 GST Tax Invoice PDF."""
    from .sales_invoices import render_sales_invoice_pdf
    inv = db.get(SalesInvoice, invoice_id)
    if not inv:
        raise HTTPException(404, 'Invoice not found.')
    rev_ids = set(db.scalars(select(FinanceReversal.original_journal_id)).all())
    pdf = render_sales_invoice_pdf(_invoice_dict(db, inv, rev_ids))
    safe = ''.join(c if c.isalnum() or c in ('-', '_') else '_' for c in inv.invoice_number)[:40] or 'invoice'
    return Response(content=pdf, media_type='application/pdf',
                    headers={'Content-Disposition': f'inline; filename="invoice_{safe}.pdf"'})


class SalesReceiptIn(BaseModel):
    invoice_id: int
    deposit_account_id: int
    tds_account_id: int | None = None
    amount_paise: int = Field(gt=0)
    tds_paise: int = Field(default=0, ge=0)
    receipt_date: str = Field(min_length=10, max_length=10)
    reference: str = Field(min_length=1, max_length=120)
    request_key: str | None = Field(default=None, max_length=120)


class SalesAdvanceIn(BaseModel):
    entity_id: int
    client_id: int | None = None
    project_id: int | None = None
    deposit_account_id: int
    advance_account_id: int
    amount_paise: int = Field(gt=0)
    receipt_date: str = Field(min_length=10, max_length=10)
    reference: str = Field(min_length=1, max_length=120)
    request_key: str | None = Field(default=None, max_length=120)


class SalesAdvanceAllocateIn(BaseModel):
    advance_id: int
    invoice_id: int
    amount_paise: int = Field(gt=0)
    allocation_date: str = Field(min_length=10, max_length=10)
    request_key: str | None = Field(default=None, max_length=120)


@router.post('/receipts')
def create_sales_receipt_draft(v: SalesReceiptIn, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """M3-2: Draft a client receipt (with optional TDS) against a sales invoice."""
    import uuid
    from .main import _manual_draft
    key = v.request_key or uuid.uuid4().hex
    payload = v.model_dump(exclude={'request_key'})
    payload['idempotency_key'] = f'srec:{user.id}:{key}'[:120]
    try:
        return _manual_draft(db, user, 'sales_receipt', payload,
                             evidence='Client receipt drafted in Sales', request_key=key)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post('/advances')
def create_sales_advance_draft(v: SalesAdvanceIn, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """M3-2: Draft a client retainer / advance posted to Client Advances liability."""
    import uuid
    from .main import _manual_draft
    key = v.request_key or uuid.uuid4().hex
    payload = v.model_dump(exclude={'request_key'})
    payload['idempotency_key'] = f'sadv:{user.id}:{key}'[:120]
    try:
        return _manual_draft(db, user, 'sales_advance', payload,
                             evidence='Client advance drafted in Sales', request_key=key)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post('/advances/allocate')
def allocate_sales_advance_draft(v: SalesAdvanceAllocateIn, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """M3-2: Draft applying a client advance to a sales invoice."""
    import uuid
    from .main import _manual_draft
    key = v.request_key or uuid.uuid4().hex
    payload = v.model_dump(exclude={'request_key'})
    payload['idempotency_key'] = f'salloc:{user.id}:{key}'[:120]
    try:
        return _manual_draft(db, user, 'sales_allocate_advance', payload,
                             evidence='Client advance allocation drafted in Sales', request_key=key)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get('/clients/{client_id}/statement')
def get_customer_statement(client_id: int, entity_id: int | None = None, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """M3-2: Customer statement showing invoices, open receivable, and unallocated retainers."""
    from .sales_receipts import customer_statement
    try:
        return customer_statement(db, client_id, entity_id=entity_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


class VendorCreditIn(BaseModel):
    entity_id: int
    supplier_id: int
    project_id: int | None = None
    note_number: str = Field(min_length=1, max_length=80)
    note_date: str = Field(min_length=10, max_length=10)
    ap_account_id: int
    expense_account_id: int
    tax_account_id: int | None = None
    taxable_paise: int = Field(gt=0)
    tax_paise: int = Field(default=0, ge=0)
    reason: str = Field(min_length=3, max_length=300)
    request_key: str | None = Field(default=None, max_length=120)


class SalesCreditNoteIn(BaseModel):
    entity_id: int
    client_id: int | None = None
    invoice_id: int | None = None
    project_id: int | None = None
    note_number: str = Field(min_length=1, max_length=80)
    note_date: str = Field(min_length=10, max_length=10)
    ar_account_id: int
    income_account_id: int
    tax_account_id: int | None = None
    taxable_paise: int = Field(gt=0)
    tax_paise: int = Field(default=0, ge=0)
    reason: str = Field(min_length=3, max_length=300)
    request_key: str | None = Field(default=None, max_length=120)


@router.post('/vendor-credits')
def create_vendor_credit_draft(v: VendorCreditIn, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """M3-3: Draft a vendor credit / purchase return for approval."""
    from .main import _manual_draft
    payload = v.model_dump(exclude={'request_key'})
    try:
        return _manual_draft(db, user, 'finance_vendor_credit', payload,
                             evidence='Vendor credit drafted in Books/Sales', request_key=v.request_key)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post('/credit-notes')
def create_sales_credit_note_draft(v: SalesCreditNoteIn, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """M3-3: Draft a client credit note / sales return for approval."""
    from .main import _manual_draft
    payload = v.model_dump(exclude={'request_key'})
    try:
        return _manual_draft(db, user, 'sales_credit_note', payload,
                             evidence='Client credit note drafted in Sales', request_key=v.request_key)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get('/unbilled-expenses')
def unbilled_expenses(entity_id: int, client_id: int, user: User = Depends(permit(*FINANCE_WRITE)), db: Session = Depends(get_db)):
    """Billable Books expenses for this client that are not on an active invoice yet."""
    from .expense_billing import unbilled
    return {'expenses': unbilled(db, entity_id, client_id)}

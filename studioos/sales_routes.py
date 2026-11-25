"""Sales routes (M3): Quotes/Estimates, Client Invoices, Receipts & Retainers, Credit/Debit Notes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import SalesQuote, SalesQuoteAcceptance, SalesQuoteLine, User
from .deps import get_db
from .security import FINANCE_WRITE, permit

router = APIRouter(prefix='/api/sales', tags=['Sales'])


class QuoteLineIn(BaseModel):
    description: str = Field(min_length=1, max_length=250)
    sac_hsn: str = Field(default='', max_length=20)
    quantity: int = Field(ge=1)
    rate_paise: int = Field(gt=0)
    tax_rate_bps: int = Field(default=1800, ge=0, le=2800)


class QuoteIn(BaseModel):
    entity_id: int
    client_id: int
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

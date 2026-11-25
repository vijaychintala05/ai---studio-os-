"""M3-0: Versioned client quotes / estimates (append-only, never posts to the ledger).
Once a quote version is accepted via an approved `sales_accept_quote` event, no newer
revision can supersede it.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .project_links import project_client, project_for_company
from .db import (AccountingEntity, SalesQuote, SalesQuoteAcceptance,
                 SalesQuoteLine)

SALES_QUOTE_TYPES = frozenset({'sales_quote', 'sales_accept_quote'})
SALES_QUOTE_FIELDS = {
    'sales_quote': {'entity_id', 'client_id', 'project_id', 'quote_number', 'quote_date',
                    'valid_until', 'lines', 'note'},
    'sales_accept_quote': {'quote_id', 'accepted_date', 'note'},
}


def _iso(val: str, label: str) -> str:
    s = str(val or '').strip()
    if len(s) != 10:
        raise ValueError(f'{label} must be YYYY-MM-DD.')
    date.fromisoformat(s)
    return s


def validate(db: Session, typ: str, d: dict, actor=None) -> dict:
    if typ == 'sales_quote':
        ent_id = int(d.get('entity_id') or 0)
        if not db.get(AccountingEntity, ent_id):
            raise ValueError('Choose a valid company.')
        proj_id = d.get('project_id')
        project = project_for_company(db, proj_id, ent_id, actor)
        client = project_client(db, project, d.get('client_id'))
        qno = str(d.get('quote_number') or '').strip()
        if not qno or len(qno) > 80:
            raise ValueError('Quote number is required (up to 80 characters).')
        # Refuse creating a new revision if an earlier version of this quote_number was accepted
        existing_ids = list(db.scalars(select(SalesQuote.id).where(
            SalesQuote.entity_id == ent_id, SalesQuote.quote_number == qno)).all())
        if existing_ids:
            acc = db.scalar(select(SalesQuoteAcceptance.id).where(
                SalesQuoteAcceptance.quote_id.in_(existing_ids)))
            if acc:
                raise ValueError(f'Quote {qno} is already accepted and cannot be revised.')
        qdate = _iso(d.get('quote_date'), 'Quote date')
        valid_until = _iso(d.get('valid_until'), 'Valid until date')
        if valid_until < qdate:
            raise ValueError('Valid until date cannot be earlier than quote date.')
        raw_lines = d.get('lines') or []
        if not isinstance(raw_lines, list) or not raw_lines:
            raise ValueError('Add at least one line item to the quote.')
        lines = []
        subtotal = 0
        tax_total = 0
        for idx, ln in enumerate(raw_lines, start=1):
            desc = str(ln.get('description') or '').strip()
            if not desc:
                raise ValueError(f'Line {idx}: description is required.')
            qty = int(ln.get('quantity') or 0)
            rate = int(ln.get('rate_paise') or 0)
            bps = int(ln.get('tax_rate_bps') or 0)
            if qty <= 0 or rate <= 0:
                raise ValueError(f'Line {idx}: quantity and rate must be positive.')
            if not (0 <= bps <= 2800):
                raise ValueError(f'Line {idx}: tax rate must be between 0% and 28%.')
            base_amt = qty * rate
            tax_amt = (base_amt * bps + 5000) // 10000
            subtotal += base_amt
            tax_total += tax_amt
            lines.append({
                'description': desc[:250],
                'sac_hsn': str(ln.get('sac_hsn') or '').strip()[:20],
                'quantity': qty,
                'rate_paise': rate,
                'tax_rate_bps': bps,
                'line_total_paise': base_amt + tax_amt,
            })
        return {
            'entity_id': ent_id,
            'client_id': client.id,
            'project_id': proj_id,
            'quote_number': qno,
            'quote_date': qdate,
            'valid_until': valid_until,
            'lines': lines,
            'subtotal_paise': subtotal,
            'tax_paise': tax_total,
            'total_paise': subtotal + tax_total,
            'note': str(d.get('note') or '').strip()[:400],
        }

    if typ == 'sales_accept_quote':
        qid = int(d.get('quote_id') or 0)
        q = db.get(SalesQuote, qid)
        if not q:
            raise ValueError('Quote not found.')
        # Check neither this version nor any sibling version of same quote_number is already accepted
        sibling_ids = list(db.scalars(select(SalesQuote.id).where(
            SalesQuote.entity_id == q.entity_id, SalesQuote.quote_number == q.quote_number)).all())
        if db.scalar(select(SalesQuoteAcceptance.id).where(SalesQuoteAcceptance.quote_id.in_(sibling_ids))):
            raise ValueError(f'Quote {q.quote_number} is already accepted.')
        adate = _iso(d.get('accepted_date'), 'Accepted date')
        return {'quote_id': q.id, 'accepted_date': adate, 'note': str(d.get('note') or '').strip()[:300]}

    raise ValueError(f'Unknown sales quote item type: {typ}')


def preview(db: Session, typ: str, d: dict, actor=None) -> dict:
    clean = validate(db, typ, d, actor)
    if typ == 'sales_quote':
        return {'summary': f"Quote {clean['quote_number']} (total ₹{clean['total_paise'] / 100:,.2f}) — does not post to the ledger",
                'lines': []}
    return {'summary': f"Accept quote #{clean['quote_id']} on {clean['accepted_date']} — does not post to the ledger", 'lines': []}


def apply(db: Session, item, actor) -> dict:
    typ = item.item_type
    from .finance_helpers import finance_submitter

    clean = validate(db, typ, item.after_data, finance_submitter(db, item))
    if typ == 'sales_quote':
        max_ver = int(db.scalar(select(func.coalesce(func.max(SalesQuote.version), 0)).where(
            SalesQuote.entity_id == clean['entity_id'],
            SalesQuote.quote_number == clean['quote_number'],
        )) or 0)
        q = SalesQuote(
            entity_id=clean['entity_id'],
            client_id=clean['client_id'],
            project_id=clean['project_id'],
            quote_number=clean['quote_number'],
            version=max_ver + 1,
            quote_date=clean['quote_date'],
            valid_until=clean['valid_until'],
            subtotal_paise=clean['subtotal_paise'],
            tax_paise=clean['tax_paise'],
            total_paise=clean['total_paise'],
            note=clean['note'],
            ticket_id=item.ticket_id,
        )
        db.add(q)
        db.flush()
        for ln in clean['lines']:
            db.add(SalesQuoteLine(quote_id=q.id, **ln))
        db.flush()
        return {'record_type': 'sales_quote', 'id': q.id, 'version': q.version}

    if typ == 'sales_accept_quote':
        acc = SalesQuoteAcceptance(
            quote_id=clean['quote_id'],
            accepted_date=clean['accepted_date'],
            note=clean['note'],
            ticket_id=item.ticket_id,
        )
        db.add(acc)
        db.flush()
        return {'record_type': 'sales_quote_acceptance', 'id': acc.id}

    raise ValueError(f'Unknown sales quote item type: {typ}')

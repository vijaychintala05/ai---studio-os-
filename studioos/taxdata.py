"""v0.22 foundation on the ticket path: dated tax rule storage. Empty until the accountant supplies content; nothing in
StudioOS reads a rule to make a decision yet. Rules are added and retired by approved tickets, never edited in place."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, select
from sqlalchemy.orm import Mapped, mapped_column

from . import taxdata_core as core
from .db import JSON_TYPE, ApprovalTicket, Base, TicketRecordEvent, User, add_audit, now


class TaxRule(Base):
    __tablename__ = 'tax_rules'
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    key: Mapped[str] = mapped_column(String(60), index=True)
    scope: Mapped[str] = mapped_column(String(60), default='')
    value: Mapped[dict] = mapped_column(JSON_TYPE)
    effective_from: Mapped[str] = mapped_column(String(10))
    created_by: Mapped[str] = mapped_column(String(100), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_by: Mapped[str] = mapped_column(String(100), default='')


TAX_TYPES = {'tax_rule_add', 'tax_rule_retire'}
TAX_FIELDS = {'tax_rule_add': {'kind', 'key', 'scope', 'value', 'effective_from'}, 'tax_rule_retire': {'rule_id'}}
ROLES = ('admin', 'accounts')


def live_rules(db):
    return [{'id': r.id, 'kind': r.kind, 'key': r.key, 'scope': r.scope, 'value': r.value, 'effective_from': r.effective_from}
            for r in db.scalars(select(TaxRule).where(TaxRule.retired_at.is_(None)).order_by(TaxRule.kind, TaxRule.key, TaxRule.effective_from))]


def _actor(db, item):
    t = db.get(ApprovalTicket, item.ticket_id) if item.ticket_id else None
    u = db.get(User, t.submitter_id) if t and t.submitter_id else None
    if not u:
        raise ValueError('The person making this change is not known')
    return u


def validate(db, item):
    kind, d = item.item_type, item.after_data
    if kind not in TAX_TYPES:
        raise ValueError('Unsupported item type')
    if not isinstance(d, dict) or set(d) - TAX_FIELDS[kind]:
        raise ValueError('Unrecognized ticket data')
    if _actor(db, item).role not in ROLES:
        raise ValueError('Your role may not make this change')
    if kind == 'tax_rule_add':
        core.check_rule(d.get('kind'), d.get('key'), d.get('scope', ''), d.get('value'), d.get('effective_from'))
        if any(r['kind'] == d['kind'] and r['key'] == d['key'] and r['scope'] == d.get('scope', '')
               and r['effective_from'] == d['effective_from'] for r in live_rules(db)):
            raise ValueError('A rule with that kind, key, scope and start date already exists; use a later start date')
    else:
        row = db.get(TaxRule, d.get('rule_id')) if type(d.get('rule_id')) is int else None
        if not row or row.retired_at:
            raise ValueError('That rule does not exist or was already retired')


def apply(db, item, actor):
    validate(db, item)
    d = item.after_data
    if item.item_type == 'tax_rule_add':
        row = TaxRule(kind=d['kind'], key=d['key'], scope=d.get('scope', ''), value=d['value'], effective_from=d['effective_from'], created_by=actor)
        db.add(row)
        op = 'create'
    else:
        row = db.get(TaxRule, d['rule_id'])
        row.retired_at, row.retired_by = now(), actor
        op = 'update'
    db.flush()
    db.add(TicketRecordEvent(ticket_id=item.ticket_id, item_id=item.id, entity_type='tax_rule', entity_id=row.id, operation=op))
    add_audit(db, 'ticket_commit', 'tax_rule', row.id, f'Ticket #{item.ticket_id}, item #{item.id}: {item.item_type}', actor=actor)
    db.flush()
    return {'type': 'tax_rule', 'id': row.id, 'item_id': item.id}

"""M3-6: Recurring money templates (generate DRAFT approval tickets only, never auto-post)
and account-level monthly Budgets with Budget vs. Actual reporting from posted GL lines.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import (AccountingEntity, FinanceAccountBudget, FinanceRecurringEntry,
                 GLAccount, GLJournal, GLLine)

RECURRING_BUDGET_TYPES = frozenset({'finance_recurring_entry', 'finance_account_budget'})
RECURRING_BUDGET_FIELDS = {
    'finance_recurring_entry': {'entity_id', 'entry_kind', 'title', 'cadence', 'next_run_date', 'payload_json'},
    'finance_account_budget': {'entity_id', 'account_id', 'fiscal_year', 'year_month', 'budget_paise', 'note'},
}

ENTRY_KIND_TO_ITEM = {
    'direct_bill': 'finance_direct_bill',
    'sales_invoice': 'sales_invoice',
    'manual_journal': 'finance_manual_journal',
}
CADENCES = ('monthly', 'quarterly', 'yearly')


def validate(db: Session, typ: str, d: dict, actor=None) -> dict:
    if typ == 'finance_recurring_entry':
        ent_id = int(d.get('entity_id') or 0)
        if not db.get(AccountingEntity, ent_id):
            raise ValueError('Choose a valid company.')
        kind = str(d.get('entry_kind') or '').strip().lower()
        if kind not in ENTRY_KIND_TO_ITEM:
            raise ValueError('Entry kind must be direct_bill, sales_invoice, or manual_journal.')
        title = str(d.get('title') or '').strip()
        if len(title) < 2:
            raise ValueError('Title is required.')
        cadence = str(d.get('cadence') or 'monthly').strip().lower()
        if cadence not in CADENCES:
            raise ValueError('Cadence must be monthly, quarterly, or yearly.')
        nrd = str(d.get('next_run_date') or '').strip()
        if len(nrd) != 10:
            raise ValueError('Next run date must be YYYY-MM-DD.')
        date.fromisoformat(nrd)
        payload = d.get('payload_json')
        if not isinstance(payload, dict) or not payload:
            raise ValueError('Recurring template payload must be a non-empty object.')
        return {
            'entity_id': ent_id, 'entry_kind': kind, 'title': title[:120],
            'cadence': cadence, 'next_run_date': nrd, 'payload_json': payload,
        }

    if typ == 'finance_account_budget':
        ent_id = int(d.get('entity_id') or 0)
        if not db.get(AccountingEntity, ent_id):
            raise ValueError('Choose a valid company.')
        acc = db.get(GLAccount, int(d.get('account_id') or 0))
        if not acc or acc.entity_id != ent_id or not acc.active or not acc.posting_allowed:
            raise ValueError('Choose an active posting account in this company.')
        fy = str(d.get('fiscal_year') or '').strip()
        if len(fy) < 4 or len(fy) > 12:
            raise ValueError('Fiscal year is required (e.g. 2026-27).')
        ym = str(d.get('year_month') or '').strip()
        if len(ym) != 7 or ym[4] != '-':
            raise ValueError('Month must be YYYY-MM.')
        date.fromisoformat(f'{ym}-01')
        budget = int(d.get('budget_paise') or 0)
        if budget <= 0:
            raise ValueError('Budget amount must be positive.')
        return {
            'entity_id': ent_id, 'account_id': acc.id, 'fiscal_year': fy,
            'year_month': ym, 'budget_paise': budget,
            'note': str(d.get('note') or '').strip()[:250],
        }

    raise ValueError(f'Unknown recurring/budget item type: {typ}')


def preview(db: Session, typ: str, d: dict, actor=None) -> dict:
    clean = validate(db, typ, d, actor)
    if typ == 'finance_recurring_entry':
        return {'summary': f"Recurring {clean['cadence']} template '{clean['title']}' (generates drafts only, never auto-posts)", 'lines': []}
    return {'summary': f"Monthly budget ₹{clean['budget_paise'] / 100:,.2f} for account #{clean['account_id']} ({clean['year_month']})", 'lines': []}


def apply(db: Session, item, actor) -> dict:
    typ = item.item_type
    clean = validate(db, typ, item.after_data, actor)
    if typ == 'finance_recurring_entry':
        row = FinanceRecurringEntry(**clean, active=True, ticket_id=item.ticket_id)
        db.add(row)
        db.flush()
        return {'record_type': 'finance_recurring_entry', 'id': row.id}

    if typ == 'finance_account_budget':
        row = FinanceAccountBudget(**clean, ticket_id=item.ticket_id)
        db.add(row)
        db.flush()
        return {'record_type': 'finance_account_budget', 'id': row.id}

    raise ValueError(f'Unknown recurring/budget item type: {typ}')


def budget_vs_actual(db: Session, entity_id: int, year_month: str) -> dict:
    if not db.get(AccountingEntity, entity_id):
        raise ValueError('Company not found.')
    # Latest approved budget row per account for this month
    budgets = db.scalars(select(FinanceAccountBudget).where(
        FinanceAccountBudget.entity_id == entity_id,
        FinanceAccountBudget.year_month == year_month,
    ).order_by(FinanceAccountBudget.id)).all()
    latest = {}
    for b in budgets:
        latest[b.account_id] = b

    # Posted GL actuals for budgeted accounts in this month
    rows = db.execute(
        select(GLAccount.id, GLAccount.code, GLAccount.name, GLAccount.kind,
               GLJournal.posted_at, GLLine.side, GLLine.amount_paise)
        .join(GLLine, GLLine.account_id == GLAccount.id)
        .join(GLJournal, GLJournal.id == GLLine.journal_id)
        .where(GLJournal.entity_id == entity_id, GLJournal.status == 'posted',
               GLAccount.id.in_(list(latest) or [-1]))
    ).all()
    actuals = {aid: 0 for aid in latest}
    for r in rows:
        ym = r.posted_at.date().isoformat()[:7] if r.posted_at else ''
        if ym != year_month:
            continue
        if (r.kind or '').lower() in ('income', 'revenue'):
            actuals[r.id] += r.amount_paise if r.side == 'credit' else -r.amount_paise
        else:
            actuals[r.id] += r.amount_paise if r.side == 'debit' else -r.amount_paise

    items = []
    for aid, b in latest.items():
        acc = db.get(GLAccount, aid)
        act = actuals.get(aid, 0)
        var = b.budget_paise - act
        items.append({
            'account_id': aid, 'code': acc.code if acc else '', 'name': acc.name if acc else '',
            'kind': acc.kind if acc else '',
            'budget_paise': b.budget_paise, 'actual_paise': act,
            'variance_paise': var, 'over_budget': act > b.budget_paise,
        })
    items.sort(key=lambda x: x['code'])
    return {
        'entity_id': entity_id, 'year_month': year_month,
        'rows': items,
        'total_budget_paise': sum(x['budget_paise'] for x in items),
        'total_actual_paise': sum(x['actual_paise'] for x in items),
    }

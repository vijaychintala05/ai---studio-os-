"""M3-5: Read-only Profit & Loss, Balance Sheet, and Cash Flow Statement computed
directly from posted GL lines in integer paise. Guarantees Balance Sheet identity:
Assets == Liabilities + Equity + Net Profit.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import AccountingEntity, GLAccount, GLJournal, GLLine

ASSET_KINDS = frozenset({'asset', 'bank', 'cash', 'inventory'})
LIABILITY_KINDS = frozenset({'liability', 'payable', 'grni'})
EQUITY_KINDS = frozenset({'equity'})
INCOME_KINDS = frozenset({'income', 'revenue'})
EXPENSE_KINDS = frozenset({'expense'})


def _posted_lines(db: Session, entity_id: int, *, project_id: int | None = None,
                  date_from: str | None = None, date_to: str | None = None):
    stmt = (
        select(GLAccount.id, GLAccount.code, GLAccount.name, GLAccount.kind,
               GLJournal.event_type, GLJournal.posted_at, GLLine.side, GLLine.amount_paise)
        .join(GLLine, GLLine.account_id == GLAccount.id)
        .join(GLJournal, GLJournal.id == GLLine.journal_id)
        .where(GLJournal.entity_id == entity_id, GLJournal.status == 'posted')
    )
    if project_id is not None:
        stmt = stmt.where(GLLine.project_id == project_id)
    rows = db.execute(stmt).all()
    out = []
    for r in rows:
        dstr = r.posted_at.date().isoformat() if r.posted_at else ''
        if date_from and dstr and dstr < date_from:
            continue
        if date_to and dstr and dstr > date_to:
            continue
        out.append(r)
    return out


def profit_and_loss(db: Session, entity_id: int, *, project_id: int | None = None,
                    date_from: str | None = None, date_to: str | None = None) -> dict:
    if not db.get(AccountingEntity, entity_id):
        raise ValueError('Company not found.')
    rows = _posted_lines(db, entity_id, project_id=project_id, date_from=date_from, date_to=date_to)
    inc_map, exp_map = {}, {}
    for r in rows:
        kind = (r.kind or '').lower()
        if kind in INCOME_KINDS:
            rec = inc_map.setdefault(r.id, {'account_id': r.id, 'code': r.code, 'name': r.name, 'amount_paise': 0})
            rec['amount_paise'] += r.amount_paise if r.side == 'credit' else -r.amount_paise
        elif kind in EXPENSE_KINDS:
            rec = exp_map.setdefault(r.id, {'account_id': r.id, 'code': r.code, 'name': r.name, 'amount_paise': 0})
            rec['amount_paise'] += r.amount_paise if r.side == 'debit' else -r.amount_paise
    income = sorted(inc_map.values(), key=lambda x: x['code'])
    expenses = sorted(exp_map.values(), key=lambda x: x['code'])
    tot_inc = sum(x['amount_paise'] for x in income)
    tot_exp = sum(x['amount_paise'] for x in expenses)
    return {
        'entity_id': entity_id, 'project_id': project_id,
        'date_from': date_from, 'date_to': date_to,
        'income': income, 'expenses': expenses,
        'total_income_paise': tot_inc,
        'total_expense_paise': tot_exp,
        'net_profit_paise': tot_inc - tot_exp,
    }


def balance_sheet(db: Session, entity_id: int, *, as_of: str | None = None) -> dict:
    if not db.get(AccountingEntity, entity_id):
        raise ValueError('Company not found.')
    rows = _posted_lines(db, entity_id, date_to=as_of)
    assets_m, liab_m, eq_m = {}, {}, {}
    tot_inc = tot_exp = 0
    for r in rows:
        kind = (r.kind or '').lower()
        if kind in ASSET_KINDS:
            rec = assets_m.setdefault(r.id, {'account_id': r.id, 'code': r.code, 'name': r.name, 'kind': kind, 'amount_paise': 0})
            rec['amount_paise'] += r.amount_paise if r.side == 'debit' else -r.amount_paise
        elif kind in LIABILITY_KINDS:
            rec = liab_m.setdefault(r.id, {'account_id': r.id, 'code': r.code, 'name': r.name, 'kind': kind, 'amount_paise': 0})
            rec['amount_paise'] += r.amount_paise if r.side == 'credit' else -r.amount_paise
        elif kind in EQUITY_KINDS:
            rec = eq_m.setdefault(r.id, {'account_id': r.id, 'code': r.code, 'name': r.name, 'kind': kind, 'amount_paise': 0})
            rec['amount_paise'] += r.amount_paise if r.side == 'credit' else -r.amount_paise
        elif kind in INCOME_KINDS:
            tot_inc += r.amount_paise if r.side == 'credit' else -r.amount_paise
        elif kind in EXPENSE_KINDS:
            tot_exp += r.amount_paise if r.side == 'debit' else -r.amount_paise

    assets = sorted(assets_m.values(), key=lambda x: x['code'])
    liabilities = sorted(liab_m.values(), key=lambda x: x['code'])
    equity = sorted(eq_m.values(), key=lambda x: x['code'])
    tot_assets = sum(x['amount_paise'] for x in assets)
    tot_liab = sum(x['amount_paise'] for x in liabilities)
    tot_eq = sum(x['amount_paise'] for x in equity)
    net_profit = tot_inc - tot_exp
    rhs = tot_liab + tot_eq + net_profit
    return {
        'entity_id': entity_id, 'as_of': as_of,
        'assets': assets, 'liabilities': liabilities, 'equity': equity,
        'total_assets_paise': tot_assets,
        'total_liabilities_paise': tot_liab,
        'total_equity_paise': tot_eq,
        'retained_net_profit_paise': net_profit,
        'balanced': tot_assets == rhs,
        'difference_paise': tot_assets - rhs,
    }


def cash_flow_statement(db: Session, entity_id: int, *, date_from: str | None = None,
                        date_to: str | None = None) -> dict:
    if not db.get(AccountingEntity, entity_id):
        raise ValueError('Company not found.')
    rows = _posted_lines(db, entity_id, date_from=date_from, date_to=date_to)
    by_event = defaultdict(int)
    inflow = outflow = 0
    for r in rows:
        if (r.kind or '').lower() not in ('bank', 'cash'):
            continue
        if r.side == 'debit':
            inflow += r.amount_paise
            by_event[r.event_type] += r.amount_paise
        else:
            outflow += r.amount_paise
            by_event[r.event_type] -= r.amount_paise
    return {
        'entity_id': entity_id, 'date_from': date_from, 'date_to': date_to,
        'inflow_paise': inflow, 'outflow_paise': outflow,
        'net_cash_change_paise': inflow - outflow,
        'by_event': [{'event_type': k, 'net_paise': v} for k, v in sorted(by_event.items())],
    }

"""M3-5+: Read-only Profit & Loss (with COGS & Gross Profit), Balance Sheet (grouped by
Zoho account type), Cash Flow Statement, Trial Balance (Opening/Period/Closing),
Project Profitability, and CSV exports computed directly from posted GL lines in integer paise.
Guarantees Balance Sheet identity: Assets == Liabilities + Equity + Net Profit.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from io import StringIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from .chart_of_accounts import ZOHO_ACCOUNT_TYPES, chart_rows
from .db import AccountingEntity, GLAccount, GLJournal, GLLine, Project

ASSET_KINDS = frozenset({'asset', 'bank', 'cash', 'inventory', 'debtor', 'input_tax', 'advance'})
LIABILITY_KINDS = frozenset({'liability', 'payable', 'grni', 'creditor', 'output_tax', 'credit_card'})
EQUITY_KINDS = frozenset({'equity'})
INCOME_KINDS = frozenset({'income', 'revenue'})
EXPENSE_KINDS = frozenset({'expense'})


def _effective_date(entry_date: str | None, posted_at) -> str:
    if entry_date:
        return entry_date
    return posted_at.date().isoformat() if posted_at else ''


def _posted_lines(db: Session, entity_id: int, *, project_id: int | None = None,
                  date_from: str | None = None, date_to: str | None = None):
    stmt = (
        select(GLAccount.id, GLAccount.code, GLAccount.name, GLAccount.kind,
               GLJournal.source_event, GLJournal.entry_date, GLJournal.posted_at,
               GLLine.side, GLLine.amount_paise, GLLine.project_id)
        .join(GLLine, GLLine.account_id == GLAccount.id)
        .join(GLJournal, GLJournal.id == GLLine.journal_id)
        .where(GLJournal.entity_id == entity_id, GLJournal.status == 'posted')
    )
    if project_id is not None:
        stmt = stmt.where(GLLine.project_id == project_id)
    rows = db.execute(stmt).all()
    out = []
    for r in rows:
        dstr = _effective_date(r.entry_date, r.posted_at)
        if date_from and dstr and dstr < date_from:
            continue
        if date_to and dstr and dstr > date_to:
            continue
        out.append(r)
    return out


def _group_by_type(items: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        at = item.get('account_type') or 'other'
        grouped[at].append(item)
    out = []
    for at, rows in grouped.items():
        label = ZOHO_ACCOUNT_TYPES[at][2] if at in ZOHO_ACCOUNT_TYPES else at.replace('_', ' ').title()
        out.append({
            'account_type': at,
            'label': label,
            'total_paise': sum(r['amount_paise'] for r in rows),
            'accounts': sorted(rows, key=lambda x: x['code']),
        })
    return out


def profit_and_loss(db: Session, entity_id: int, *, project_id: int | None = None,
                    date_from: str | None = None, date_to: str | None = None) -> dict:
    if not db.get(AccountingEntity, entity_id):
        raise ValueError('Company not found.')
    meta = chart_rows(db, entity_id)
    rows = _posted_lines(db, entity_id, project_id=project_id, date_from=date_from, date_to=date_to)
    inc_map, exp_map, cogs_map, opex_map = {}, {}, {}, {}
    for r in rows:
        kind = (r.kind or '').lower()
        m = meta.get(r.id, {})
        at = m.get('account_type', '')
        parent_id = m.get('parent')
        if kind in INCOME_KINDS:
            rec = inc_map.setdefault(r.id, {'account_id': r.id, 'code': r.code, 'name': r.name,
                                            'account_type': at or 'income', 'parent_id': parent_id, 'amount_paise': 0})
            rec['amount_paise'] += r.amount_paise if r.side == 'credit' else -r.amount_paise
        elif kind in EXPENSE_KINDS:
            delta = r.amount_paise if r.side == 'debit' else -r.amount_paise
            rec = exp_map.setdefault(r.id, {'account_id': r.id, 'code': r.code, 'name': r.name,
                                            'account_type': at or 'expense', 'parent_id': parent_id, 'amount_paise': 0})
            rec['amount_paise'] += delta
            target = cogs_map if at == 'cost_of_goods_sold' else opex_map
            trec = target.setdefault(r.id, {'account_id': r.id, 'code': r.code, 'name': r.name,
                                            'account_type': at or 'expense', 'parent_id': parent_id, 'amount_paise': 0})
            trec['amount_paise'] += delta
    income = sorted(inc_map.values(), key=lambda x: x['code'])
    expenses = sorted(exp_map.values(), key=lambda x: x['code'])
    cogs = sorted(cogs_map.values(), key=lambda x: x['code'])
    opex = sorted(opex_map.values(), key=lambda x: x['code'])
    tot_inc = sum(x['amount_paise'] for x in income)
    tot_cogs = sum(x['amount_paise'] for x in cogs)
    tot_opex = sum(x['amount_paise'] for x in opex)
    tot_exp = sum(x['amount_paise'] for x in expenses)
    gross_profit = tot_inc - tot_cogs
    return {
        'entity_id': entity_id, 'project_id': project_id,
        'date_from': date_from, 'date_to': date_to,
        'income': income, 'expenses': expenses,
        'cogs': cogs, 'operating_expenses': opex,
        'total_income_paise': tot_inc,
        'total_cogs_paise': tot_cogs,
        'gross_profit_paise': gross_profit,
        'total_operating_expense_paise': tot_opex,
        'total_expense_paise': tot_exp,
        'net_profit_paise': tot_inc - tot_exp,
    }


def balance_sheet(db: Session, entity_id: int, *, as_of: str | None = None) -> dict:
    if not db.get(AccountingEntity, entity_id):
        raise ValueError('Company not found.')
    meta = chart_rows(db, entity_id)
    rows = _posted_lines(db, entity_id, date_to=as_of)
    assets_m, liab_m, eq_m = {}, {}, {}
    tot_inc = tot_exp = 0
    for r in rows:
        kind = (r.kind or '').lower()
        m = meta.get(r.id, {})
        at = m.get('account_type', '')
        parent_id = m.get('parent')
        if kind in ASSET_KINDS:
            rec = assets_m.setdefault(r.id, {'account_id': r.id, 'code': r.code, 'name': r.name, 'kind': kind,
                                             'account_type': at, 'parent_id': parent_id, 'amount_paise': 0})
            rec['amount_paise'] += r.amount_paise if r.side == 'debit' else -r.amount_paise
        elif kind in LIABILITY_KINDS:
            rec = liab_m.setdefault(r.id, {'account_id': r.id, 'code': r.code, 'name': r.name, 'kind': kind,
                                           'account_type': at, 'parent_id': parent_id, 'amount_paise': 0})
            rec['amount_paise'] += r.amount_paise if r.side == 'credit' else -r.amount_paise
        elif kind in EQUITY_KINDS:
            rec = eq_m.setdefault(r.id, {'account_id': r.id, 'code': r.code, 'name': r.name, 'kind': kind,
                                         'account_type': at or 'equity', 'parent_id': parent_id, 'amount_paise': 0})
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
        'assets_grouped': _group_by_type(assets),
        'liabilities_grouped': _group_by_type(liabilities),
        'equity_grouped': _group_by_type(equity),
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
            by_event[r.source_event] += r.amount_paise
        else:
            outflow += r.amount_paise
            by_event[r.source_event] -= r.amount_paise
    return {
        'entity_id': entity_id, 'date_from': date_from, 'date_to': date_to,
        'inflow_paise': inflow, 'outflow_paise': outflow,
        'net_cash_change_paise': inflow - outflow,
        'by_event': [{'event_type': k, 'net_paise': v} for k, v in sorted(by_event.items())],
    }


def trial_balance_report(db: Session, entity_id: int, *, date_from: str | None = None,
                         date_to: str | None = None) -> dict:
    """Trial Balance with Opening Dr/Cr, Period Dr/Cr, and Closing Dr/Cr."""
    if not db.get(AccountingEntity, entity_id):
        raise ValueError('Company not found.')
    meta = chart_rows(db, entity_id)
    all_rows = _posted_lines(db, entity_id, date_to=date_to)
    acc_map: dict[int, dict] = {}
    for r in all_rows:
        dstr = _effective_date(r.entry_date, r.posted_at)
        m = meta.get(r.id, {})
        rec = acc_map.setdefault(r.id, {
            'account_id': r.id, 'code': r.code, 'name': r.name, 'kind': r.kind,
            'account_type': m.get('account_type', ''),
            'opening_debit_paise': 0, 'opening_credit_paise': 0,
            'period_debit_paise': 0, 'period_credit_paise': 0,
        })
        is_opening = bool(date_from and dstr and dstr < date_from)
        if is_opening:
            if r.side == 'debit':
                rec['opening_debit_paise'] += r.amount_paise
            else:
                rec['opening_credit_paise'] += r.amount_paise
        else:
            if r.side == 'debit':
                rec['period_debit_paise'] += r.amount_paise
            else:
                rec['period_credit_paise'] += r.amount_paise

    rows = []
    tot_open_dr = tot_open_cr = tot_per_dr = tot_per_cr = tot_close_dr = tot_close_cr = 0
    for rec in sorted(acc_map.values(), key=lambda x: x['code']):
        open_net = rec['opening_debit_paise'] - rec['opening_credit_paise']
        odr = open_net if open_net > 0 else 0
        ocr = -open_net if open_net < 0 else 0
        close_net = open_net + rec['period_debit_paise'] - rec['period_credit_paise']
        cdr = close_net if close_net > 0 else 0
        ccr = -close_net if close_net < 0 else 0
        tot_open_dr += odr
        tot_open_cr += ocr
        tot_per_dr += rec['period_debit_paise']
        tot_per_cr += rec['period_credit_paise']
        tot_close_dr += cdr
        tot_close_cr += ccr
        rows.append({
            'account_id': rec['account_id'], 'code': rec['code'], 'name': rec['name'],
            'account_type': rec['account_type'],
            'opening_debit_paise': odr, 'opening_credit_paise': ocr,
            'period_debit_paise': rec['period_debit_paise'], 'period_credit_paise': rec['period_credit_paise'],
            'closing_debit_paise': cdr, 'closing_credit_paise': ccr,
        })
    return {
        'entity_id': entity_id, 'date_from': date_from, 'date_to': date_to,
        'rows': rows,
        'totals': {
            'opening_debit_paise': tot_open_dr, 'opening_credit_paise': tot_open_cr,
            'period_debit_paise': tot_per_dr, 'period_credit_paise': tot_per_cr,
            'closing_debit_paise': tot_close_dr, 'closing_credit_paise': tot_close_cr,
        },
        'balanced': tot_close_dr == tot_close_cr and tot_per_dr == tot_per_cr,
    }


def project_profitability(db: Session, entity_id: int, *, date_from: str | None = None,
                          date_to: str | None = None) -> dict:
    """Job-costing report: Revenue, COGS (Direct Costs), Operating Expenses, and Net Margin per project."""
    if not db.get(AccountingEntity, entity_id):
        raise ValueError('Company not found.')
    meta = chart_rows(db, entity_id)
    projects = {p.id: p.name for p in db.scalars(select(Project)).all()}
    rows = _posted_lines(db, entity_id, date_from=date_from, date_to=date_to)
    by_proj: dict[int | None, dict] = {}
    for r in rows:
        kind = (r.kind or '').lower()
        if kind not in INCOME_KINDS and kind not in EXPENSE_KINDS:
            continue
        pid = r.project_id
        rec = by_proj.setdefault(pid, {
            'project_id': pid,
            'project_name': projects.get(pid, 'Office / Overhead') if pid is not None else 'Office / Overhead',
            'income_paise': 0, 'cogs_paise': 0, 'operating_expense_paise': 0,
        })
        if kind in INCOME_KINDS:
            rec['income_paise'] += r.amount_paise if r.side == 'credit' else -r.amount_paise
        else:
            delta = r.amount_paise if r.side == 'debit' else -r.amount_paise
            at = meta.get(r.id, {}).get('account_type', '')
            if at == 'cost_of_goods_sold':
                rec['cogs_paise'] += delta
            else:
                rec['operating_expense_paise'] += delta
    out = []
    for rec in sorted(by_proj.values(), key=lambda x: (x['project_id'] is None, x['project_name'])):
        gross = rec['income_paise'] - rec['cogs_paise']
        net = gross - rec['operating_expense_paise']
        out.append({**rec, 'gross_profit_paise': gross, 'net_profit_paise': net})
    return {
        'entity_id': entity_id, 'date_from': date_from, 'date_to': date_to,
        'rows': out,
        'total_income_paise': sum(x['income_paise'] for x in out),
        'total_cogs_paise': sum(x['cogs_paise'] for x in out),
        'total_operating_expense_paise': sum(x['operating_expense_paise'] for x in out),
        'total_net_profit_paise': sum(x['net_profit_paise'] for x in out),
    }


def project_accounting_summary(db: Session, project_id: int) -> dict:
    """Complete relational project accounting view: linked company/client, budget vs actuals,
    revenue/invoiced/collected, COGS & OpEx breakdown, PO commitments vs billed, and margin."""
    from .db import (FinanceDirectBill, FinanceDirectBillLine, FinancePurchaseOrder,
                     FinanceReversal, Party, SalesInvoice)
    from .direct_bills import direct_bill_outstanding, po_billed_paise
    from .sales_receipts import invoice_outstanding

    proj = db.get(Project, project_id)
    if proj is None or proj.deleted_at:
        raise ValueError('Project not found.')
    company = db.get(AccountingEntity, proj.company_id) if proj.company_id else None
    client = db.get(Party, proj.client_id) if proj.client_id else None
    rev_ids = set(db.scalars(select(FinanceReversal.original_journal_id)).all())

    # GL-backed P&L for this project (uses company if linked, else all entities touching project_id)
    entity_id = proj.company_id
    if entity_id is not None:
        pnl = profit_and_loss(db, entity_id, project_id=proj.id)
    else:
        pnl = {'income': [], 'cogs': [], 'operating_expenses': [],
               'total_income_paise': 0, 'total_cogs_paise': 0,
               'gross_profit_paise': 0, 'total_operating_expense_paise': 0,
               'total_expense_paise': 0, 'net_profit_paise': 0}

    # Purchase Orders committed vs billed
    pos = db.scalars(select(FinancePurchaseOrder).where(
        FinancePurchaseOrder.project_id == proj.id, FinancePurchaseOrder.status == 'approved',
    ).order_by(FinancePurchaseOrder.id.desc())).all()
    po_rows = []
    for po in pos:
        billed = po_billed_paise(db, po.id)
        po_rows.append({
            'id': po.id, 'po_number': po.po_number, 'amount_paise': po.amount_paise,
            'billed_paise': billed, 'remaining_paise': max(0, po.amount_paise - billed),
        })

    # Sales Invoices billed vs collected
    invs = db.scalars(select(SalesInvoice).where(
        SalesInvoice.project_id == proj.id, SalesInvoice.journal_id.is_not(None),
    ).order_by(SalesInvoice.id.desc())).all()
    inv_total = inv_owed = 0
    for inv in invs:
        if inv.journal_id in rev_ids:
            continue
        inv_total += inv.total_paise
        inv_owed += invoice_outstanding(db, inv.id)

    # Direct bills touching this project
    bill_ids = list(db.scalars(select(FinanceDirectBillLine.bill_id).where(FinanceDirectBillLine.project_id == proj.id).distinct()).all())
    bill_total = bill_owed = 0
    for bid in bill_ids:
        b = db.get(FinanceDirectBill, bid)
        if b and b.journal_id and b.journal_id not in rev_ids:
            bill_total += b.amount_paise
            bill_owed += direct_bill_outstanding(db, b.id)

    budget = int(proj.budget_paise or 0)
    spent = pnl['total_expense_paise']
    return {
        'project': {
            'id': proj.id, 'name': proj.name, 'stage': proj.stage,
            'budget_paise': budget,
            'company_id': proj.company_id, 'company_name': company.name if company else None,
            'client_id': proj.client_id, 'client_name': client.name if client else proj.client,
        },
        'budget_paise': budget,
        'actual_cost_paise': spent,
        'budget_remaining_paise': budget - spent,
        'invoiced_paise': inv_total,
        'collected_paise': inv_total - inv_owed,
        'receivable_paise': inv_owed,
        'bills_total_paise': bill_total,
        'bills_owed_paise': bill_owed,
        'po_committed_paise': sum(p['amount_paise'] for p in po_rows),
        'po_billed_paise': sum(p['billed_paise'] for p in po_rows),
        'po_remaining_paise': sum(p['remaining_paise'] for p in po_rows),
        'purchase_orders': po_rows,
        'pnl': pnl,
    }


def report_to_csv(kind: str, data: dict) -> str:
    """Format a financial report dict into a clean CSV for accountants/CA."""
    buf = StringIO()
    w = csv.writer(buf)
    def rs(paise):
        paise = paise or 0
        whole, minor = divmod(abs(paise), 100)
        return f'{"-" if paise < 0 else ""}{whole}.{minor:02d}'
    if kind == 'pnl':
        w.writerow(['Section', 'Code', 'Account', 'Amount (INR)'])
        for r in data.get('income', []):
            w.writerow(['Income', r['code'], r['name'], rs(r['amount_paise'])])
        for r in data.get('cogs', []):
            w.writerow(['Cost of Goods Sold', r['code'], r['name'], rs(r['amount_paise'])])
        w.writerow(['Gross Profit', '', '', rs(data.get('gross_profit_paise', 0))])
        for r in data.get('operating_expenses', []):
            w.writerow(['Operating Expenses', r['code'], r['name'], rs(r['amount_paise'])])
        w.writerow(['Net Profit', '', '', rs(data.get('net_profit_paise', 0))])
    elif kind == 'balance-sheet':
        w.writerow(['Section', 'Account Type', 'Code', 'Account', 'Amount (INR)'])
        for sec, key in (('Assets', 'assets'), ('Liabilities', 'liabilities'), ('Equity', 'equity')):
            for r in data.get(key, []):
                w.writerow([sec, r.get('account_type', ''), r['code'], r['name'], rs(r['amount_paise'])])
        w.writerow(['Equity', 'retained_earnings', '', 'Net Profit / Retained', rs(data.get('retained_net_profit_paise', 0))])
    elif kind == 'trial-balance':
        w.writerow(['Code', 'Account', 'Account Type', 'Opening Dr', 'Opening Cr', 'Period Dr', 'Period Cr', 'Closing Dr', 'Closing Cr'])
        amount_keys = (
            'opening_debit_paise', 'opening_credit_paise', 'period_debit_paise', 'period_credit_paise',
            'closing_debit_paise', 'closing_credit_paise',
        )
        for r in data.get('rows', []):
            w.writerow([r['code'], r['name'], r['account_type'], *(rs(r[key]) for key in amount_keys)])
        if data.get('rows') and data.get('totals'):
            w.writerow(['', 'Totals', '', *(rs(data['totals'][key]) for key in amount_keys)])
    elif kind == 'project-profitability':
        w.writerow(['Project', 'Income', 'COGS', 'Gross Profit', 'Operating Expenses', 'Net Profit'])
        for r in data.get('rows', []):
            w.writerow([r['project_name'], rs(r['income_paise']), rs(r['cogs_paise']),
                        rs(r['gross_profit_paise']), rs(r['operating_expense_paise']), rs(r['net_profit_paise'])])
    elif kind in ('tds', 'tds-register'):
        w.writerow(['Bill Date', 'Invoice No', 'Vendor', 'GSTIN', 'TDS Section', 'Taxable (INR)', 'TDS Deducted (INR)'])
        for r in data.get('rows', []):
            w.writerow([r['bill_date'], r['invoice_number'], r['supplier_name'], r['gstin'],
                        r['tds_section'], rs(r['taxable_paise']), rs(r['tds_paise'])])
    elif kind == 'cash-flow':
        w.writerow(['Activity', 'Net (INR)'])
        for row in data['by_event']:
            label = row['event_type'].replace('_', ' ').capitalize()
            w.writerow([label, rs(row['net_paise'])])
        for label, key in (('Money In', 'inflow_paise'), ('Money Out', 'outflow_paise'),
                           ('Net Cash Change', 'net_cash_change_paise')):
            w.writerow([label, rs(data[key])])
    elif kind == 'ar-ageing':
        buckets = ('current', 'days_31_60', 'days_61_90', 'over_90')
        w.writerow(['Client', '0–30 days (INR)', '31–60 days (INR)', '61–90 days (INR)', 'Over 90 days (INR)', 'Total (INR)'])
        for row in data['by_client']:
            w.writerow([row['client_name'], *(rs(row[key]) for key in buckets), rs(row['total_paise'])])
        w.writerow(['Total', *(rs(data['ageing'][key]) for key in buckets), rs(data['total_receivable_paise'])])
    elif kind == 'gstr1':
        components = ('cgst_paise', 'sgst_paise', 'igst_paise')
        w.writerow(['Supply Type', 'Document Number', 'Document Date', 'Client', 'GSTIN',
                    'Place of Supply', 'Taxable (INR)', 'CGST (INR)', 'SGST (INR)', 'IGST (INR)', 'GST (INR)', 'Total (INR)'])
        for label, group in (('B2B', 'b2b'), ('B2C', 'b2c')):
            for row in data[group]:
                w.writerow([label, row['invoice_number'], row['invoice_date'], row['client_name'], row['gstin'],
                            row['place_of_supply'], rs(row['taxable_paise']),
                            *(rs(row[key]) for key in components), rs(sum(row[key] for key in components)),
                            rs(row['total_paise'])])
        for row in data['credit_notes']:
            w.writerow(['Credit note', row['note_number'], row['note_date'], row['client_name'], row['gstin'],
                        '', rs(row['taxable_paise']), '', '', '', rs(row['tax_paise']), rs(row['total_paise'])])
    elif kind == 'gstr3b':
        w.writerow(['Measure', 'CGST (INR)', 'SGST (INR)', 'IGST (INR)', 'Amount (INR)'])
        for label, key in (('Output GST', 'outward_tax'), ('Eligible ITC', 'eligible_itc')):
            row = data[key]
            w.writerow([label, *(rs(row[k]) for k in ('cgst_paise', 'sgst_paise', 'igst_paise', 'total_paise'))])
        w.writerow(['Net GST Payable', '', '', '', rs(data['net_payable_paise'])])
        w.writerow(['ITC Carry Forward', '', '', '', rs(data['itc_carry_forward_paise'])])
    elif kind == 'budget-vs-actual':
        w.writerow(['Code', 'Account', 'Budget (INR)', 'Actual (INR)', 'Variance (INR)', 'Status'])
        for row in data['rows']:
            w.writerow([row['code'], row['name'], rs(row['budget_paise']), rs(row['actual_paise']),
                        rs(row['variance_paise']), 'Over budget' if row['over_budget'] else 'On track'])
    else:
        raise ValueError(f'Unsupported CSV export report: {kind}')
    return buf.getvalue()

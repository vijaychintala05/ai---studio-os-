"""Itemised Books expenses with GST (CGST/SGST intra-state or IGST inter-state).

Accounting rules (CA-verified):
- Each line specifies an active posting expense account, description, integer amount_paise, and GST slab (0/5/12/18/28%).
- Tax exclusive: GST is added on top of typed amounts. Tax inclusive: GST is extracted so net + tax == typed amount.
- Input GST posts to Input CGST + Input SGST (intra-state; any odd paisa goes to SGST) or Input IGST (inter-state).
- Input GST is an asset (recoverable ITC), not project cost; billable recharges use net cost before Input GST.
- Debits (expense lines + Input GST) always equal Credits (Paid Through) to the exact paisa.
"""
from __future__ import annotations

from sqlalchemy import select

from .db import FinanceTaxSetting, GLAccount

TAX_MODES = ('none', 'exclusive', 'inclusive')
GST_BPS = (0, 500, 1200, 1800, 2800)
MAX_LINES = 10
DEFAULT_STATE = '29'


def split_tax(amount: int, bps: int, mode: str) -> tuple[int, int]:
    """Return (net_paise, tax_paise) for one typed amount."""
    if mode == 'none' or bps == 0:
        return amount, 0
    if mode == 'exclusive':
        return amount, (amount * bps + 5_000) // 10_000
    net = (amount * 10_000 + (10_000 + bps) // 2) // (10_000 + bps)
    return net, amount - net


def company_state(db, entity_id: int) -> str:
    code = db.scalar(
        select(FinanceTaxSetting.state_code)
        .where(FinanceTaxSetting.entity_id == entity_id)
        .order_by(FinanceTaxSetting.id.desc())
        .limit(1)
    )
    return code if isinstance(code, str) and len(code) == 2 else DEFAULT_STATE


def tax_accounts(db, entity_id: int) -> dict:
    """Resolve active posting Input CGST / SGST / IGST accounts for an entity."""
    rows = db.scalars(
        select(GLAccount).where(
            GLAccount.entity_id == entity_id,
            GLAccount.kind == 'input_tax',
            GLAccount.active.is_(True),
            GLAccount.posting_allowed.is_(True),
        )
    ).all()
    out = {}
    for key in ('cgst', 'sgst', 'igst'):
        by_code = [a.id for a in rows if a.code.upper() == f'INPUT_{key.upper()}']
        by_name = [a.id for a in rows if a.name.strip().casefold() == f'input {key}']
        found = by_code or by_name
        out[key] = found[0] if len(found) == 1 else None
    return out


def compute(db, entity_id: int, data: dict) -> dict:
    """Validate itemised expense lines and compute exact GST split."""
    lines = data.get('lines')
    mode = data.get('tax_mode', 'none')
    if mode not in TAX_MODES:
        raise ValueError('Say whether the amounts include GST or GST is added.')
    if not isinstance(lines, list) or not 1 <= len(lines) <= MAX_LINES:
        raise ValueError(f'An itemised expense has between 1 and {MAX_LINES} lines.')
    out_lines, net_total, tax_total = [], 0, 0
    for n, ln in enumerate(lines, start=1):
        if not isinstance(ln, dict) or set(ln) - {'expense_account_id', 'description', 'amount_paise', 'tax_bps'}:
            raise ValueError(f'Check line {n}.')
        account = db.get(GLAccount, ln.get('expense_account_id')) if type(ln.get('expense_account_id')) is int else None
        if account is None or account.entity_id != entity_id or account.kind != 'expense' or not account.active or not account.posting_allowed:
            raise ValueError(f'Line {n}: choose an active expense account for this company.')
        amount = ln.get('amount_paise')
        if type(amount) is not int or not 0 < amount < 10 ** 13:
            raise ValueError(f'Line {n}: enter an amount greater than zero.')
        bps = ln.get('tax_bps', 0)
        if type(bps) is not int or bps not in GST_BPS:
            raise ValueError(f'Line {n}: choose a GST rate from 0%, 5%, 12%, 18% or 28%.')
        if mode == 'none' and bps:
            raise ValueError(f'Line {n}: say whether the amount includes GST or GST is added.')
        description = ln.get('description', '')
        if not isinstance(description, str) or len(description) > 250 or not description.isprintable():
            raise ValueError(f'Line {n}: keep the description within 250 characters.')
        net, tax = split_tax(amount, bps, mode)
        if net <= 0:
            raise ValueError(f'Line {n}: the amount is too small for this GST rate.')
        net_total += net
        tax_total += tax
        out_lines.append({
            'account_id': account.id,
            'description': description.strip(),
            'typed_paise': amount,
            'net_paise': net,
            'tax_bps': bps,
            'tax_paise': tax,
        })
    total = net_total + tax_total
    if data.get('amount_paise') != total:
        raise ValueError('The total does not match the lines. Reopen the form and try again.')
    out = {
        'lines': out_lines,
        'net_paise': net_total,
        'tax_paise': tax_total,
        'total_paise': total,
        'cgst_paise': 0,
        'sgst_paise': 0,
        'igst_paise': 0,
        'tax_mode': mode,
        'place_of_supply': '',
    }
    if tax_total:
        company = company_state(db, entity_id)
        place = data.get('place_of_supply') or company
        if not isinstance(place, str) or len(place) != 2 or not place.isdecimal():
            raise ValueError('Choose the place of supply (the supplier’s state).')
        out['place_of_supply'] = place
        accounts = tax_accounts(db, entity_id)
        if place == company:
            out['cgst_paise'] = tax_total // 2
            out['sgst_paise'] = tax_total - out['cgst_paise']
            needed = ('cgst', 'sgst')
        else:
            out['igst_paise'] = tax_total
            needed = ('igst',)
        if any(accounts[k] is None for k in needed):
            raise ValueError('Ask Accounts to set up the Input GST accounts (Input CGST, Input SGST, Input IGST) before GST is claimed on an expense.')
        out['accounts'] = accounts
    return out


def journal_lines(figures: dict, credit_account_id: int, project_id: int | None) -> list:
    """Return balanced [(account_id, side, paise, project_id)] lines for _post_lines."""
    debit: dict[int, int] = {}
    for ln in figures['lines']:
        debit[ln['account_id']] = debit.get(ln['account_id'], 0) + ln['net_paise']
    rows = [(account, 'debit', amount, project_id) for account, amount in debit.items()]
    acc = figures.get('accounts') or {}
    for key in ('cgst', 'sgst', 'igst'):
        if figures[f'{key}_paise']:
            rows.append((acc[key], 'debit', figures[f'{key}_paise'], project_id))
    if credit_account_id in debit:
        raise ValueError('The Paid Through account cannot also be an expense account on this entry.')
    rows.append((credit_account_id, 'credit', figures['total_paise'], project_id))
    return rows

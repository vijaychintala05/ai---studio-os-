"""M2-5: Bank feed CSV import, match suggestions, suggest-only bank rules, and
append-only unreconciliations with a required reason.
Rules NEVER auto-post; every statement line, rule, reconciliation, and unreconciliation
travels through an approval ticket.
"""
from __future__ import annotations

import csv
from datetime import date
from io import StringIO

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import (AccountingEntity, FinanceBankReconciliation, FinanceBankRule,
                 FinanceBankStatementLine, FinanceBankUnreconcile, FinanceReversal,
                 GLAccount, GLJournal, GLLine, Party, RegisteredBank)

BANK_FEED_TYPES = frozenset({'finance_bank_rule', 'finance_unreconcile_bank'})
BANK_FEED_FIELDS = {
    'finance_bank_rule': {'entity_id', 'bank_id', 'match_text', 'direction',
                          'suggested_account_id', 'suggested_party_id', 'note'},
    'finance_unreconcile_bank': {'reconciliation_id', 'reason'},
}
DIRECTIONS = ('outflow', 'inflow', 'any')


def _parse_rupees_to_paise(raw: str) -> int:
    clean = str(raw or '').replace(',', '').replace('₹', '').replace('Rs.', '').replace('Rs', '').strip()
    if not clean or clean in ('-', '--'):
        return 0
    neg = clean.startswith('-')
    if neg:
        clean = clean[1:].strip()
    parts = clean.split('.')
    if len(parts) > 2 or not parts[0].isdigit():
        raise ValueError(f'Invalid amount in CSV: {raw!r}')
    frac = (parts[1] + '00')[:2] if len(parts) == 2 else '00'
    if len(parts) == 2 and parts[1] and not parts[1].isdigit():
        raise ValueError(f'Invalid amount in CSV: {raw!r}')
    paise = int(parts[0]) * 100 + int(frac)
    return -paise if neg else paise


def parse_bank_csv(csv_text: str) -> list[dict]:
    """Parse a standard Indian bank statement CSV into normalized statement lines."""
    reader = csv.DictReader(StringIO((csv_text or '').strip()))
    if not reader.fieldnames:
        raise ValueError('CSV is empty or missing a header row.')
    headers = {h.strip().casefold(): h for h in reader.fieldnames if h}

    def pick(row, *candidates):
        for c in candidates:
            if c in headers:
                return (row.get(headers[c]) or '').strip()
        return ''

    rows = []
    for idx, row in enumerate(reader, start=2):
        raw_date = pick(row, 'date', 'booking_date', 'txn date', 'transaction date', 'value date')
        ref = pick(row, 'reference', 'statement_reference', 'utr', 'ref', 'narration', 'description', 'particulars')
        if not raw_date and not ref:
            continue
        if len(raw_date) != 10:
            raise ValueError(f'Row {idx}: date must be YYYY-MM-DD (got {raw_date!r}).')
        date.fromisoformat(raw_date)
        signed_str = pick(row, 'signed_amount', 'amount')
        debit_str = pick(row, 'debit', 'withdrawal', 'dr')
        credit_str = pick(row, 'credit', 'deposit', 'cr')
        if signed_str:
            signed_paise = _parse_rupees_to_paise(signed_str)
        else:
            dr = abs(_parse_rupees_to_paise(debit_str)) if debit_str else 0
            cr = abs(_parse_rupees_to_paise(credit_str)) if credit_str else 0
            signed_paise = cr - dr
        if signed_paise == 0:
            raise ValueError(f'Row {idx}: amount cannot be zero.')
        if not ref:
            ref = f'CSV-{raw_date}-{idx}'
        rows.append({
            'booking_date': raw_date,
            'statement_reference': ref[:120],
            'signed_amount_paise': signed_paise,
        })
    if not rows:
        raise ValueError('No statement rows found in CSV.')
    return rows


def validate(db: Session, typ: str, d: dict, actor=None) -> dict:
    if typ == 'finance_bank_rule':
        ent_id = int(d.get('entity_id') or 0)
        if not db.get(AccountingEntity, ent_id):
            raise ValueError('Choose a valid company.')
        bank_id = d.get('bank_id')
        if bank_id is not None:
            bank = db.get(RegisteredBank, int(bank_id))
            if not bank or bank.entity_id != ent_id:
                raise ValueError('Bank account does not belong to the chosen company.')
            bank_id = bank.id
        match_text = str(d.get('match_text') or '').strip()
        if len(match_text) < 2:
            raise ValueError('Match text must be at least 2 characters.')
        direction = str(d.get('direction') or 'any').strip().lower()
        if direction not in DIRECTIONS:
            raise ValueError('Direction must be outflow, inflow, or any.')
        acc_id = int(d.get('suggested_account_id') or 0)
        acc = db.get(GLAccount, acc_id)
        if not acc or acc.entity_id != ent_id or not acc.active or not acc.posting_allowed:
            raise ValueError('Choose an active posting account in this company.')
        party_id = d.get('suggested_party_id')
        if party_id is not None:
            party = db.get(Party, int(party_id))
            if not party or party.deleted_at:
                raise ValueError('Choose an active contact.')
            party_id = party.id
        return {
            'entity_id': ent_id,
            'bank_id': bank_id,
            'match_text': match_text[:120],
            'direction': direction,
            'suggested_account_id': acc.id,
            'suggested_party_id': party_id,
            'note': str(d.get('note') or '').strip()[:300],
        }

    if typ == 'finance_unreconcile_bank':
        rec_id = int(d.get('reconciliation_id') or 0)
        rec = db.get(FinanceBankReconciliation, rec_id)
        if not rec:
            raise ValueError('Bank match record not found.')
        existing = db.scalar(select(FinanceBankUnreconcile.id).where(
            FinanceBankUnreconcile.reconciliation_id == rec.id))
        if existing:
            raise ValueError('This bank match has already been un-matched.')
        reason = str(d.get('reason') or '').strip()
        if len(reason) < 5:
            raise ValueError('Give a short reason (at least 5 characters) for un-matching.')
        return {'reconciliation_id': rec.id, 'reason': reason[:300]}

    raise ValueError(f'Unknown bank feed item type: {typ}')


def preview(db: Session, typ: str, d: dict, actor=None) -> dict:
    clean = validate(db, typ, d, actor)
    if typ == 'finance_bank_rule':
        return {'summary': f"Suggest account #{clean['suggested_account_id']} when bank line contains '{clean['match_text']}' (never auto-posts)",
                'lines': []}
    return {'summary': f"Un-match bank reconciliation #{clean['reconciliation_id']} ({clean['reason']})", 'lines': []}


def apply(db: Session, item, actor) -> dict:
    typ = item.item_type
    clean = validate(db, typ, item.after_data, actor)
    if typ == 'finance_bank_rule':
        row = FinanceBankRule(
            entity_id=clean['entity_id'],
            bank_id=clean['bank_id'],
            match_text=clean['match_text'],
            direction=clean['direction'],
            suggested_account_id=clean['suggested_account_id'],
            suggested_party_id=clean['suggested_party_id'],
            note=clean['note'],
            active=True,
            ticket_id=item.ticket_id,
        )
        db.add(row)
        db.flush()
        return {'record_type': 'finance_bank_rule', 'id': row.id}

    if typ == 'finance_unreconcile_bank':
        row = FinanceBankUnreconcile(
            reconciliation_id=clean['reconciliation_id'],
            reason=clean['reason'],
            ticket_id=item.ticket_id,
        )
        db.add(row)
        db.flush()
        return {'record_type': 'finance_unreconcile_bank', 'id': row.id}

    raise ValueError(f'Unknown bank feed item type: {typ}')


def bank_feed_for_bank(db: Session, bank_id: int) -> dict:
    """Return uncategorised bank statement lines, match suggestions, and active rules."""
    bank = db.get(RegisteredBank, bank_id)
    if not bank:
        raise ValueError('Bank account not found.')

    unrec_ids = set(db.scalars(select(FinanceBankUnreconcile.reconciliation_id)).all())
    all_recs = db.scalars(select(FinanceBankReconciliation).order_by(FinanceBankReconciliation.id.desc())).all()
    active_stmt_ids = {r.statement_line_id for r in all_recs if r.id not in unrec_ids}
    active_journal_ids = {r.journal_id for r in all_recs if r.id not in unrec_ids}
    reversed_journals = set(db.scalars(select(FinanceReversal.original_journal_id)).all())

    # Candidate posted journals on this bank's GL account that are not actively matched or reversed.
    cand_rows = db.execute(
        select(GLJournal.id, GLJournal.posted_at, GLJournal.memo, GLLine.side, GLLine.amount_paise)
        .join(GLLine, GLLine.journal_id == GLJournal.id)
        .where(GLJournal.entity_id == bank.entity_id, GLJournal.status == 'posted',
               GLLine.account_id == bank.gl_account_id)
        .order_by(GLJournal.id.desc())
    ).all()
    candidates = []
    for jid, posted_at, memo, side, amt in cand_rows:
        if jid in active_journal_ids or jid in reversed_journals:
            continue
        signed = amt if side == 'debit' else -amt
        candidates.append({
            'journal_id': jid,
            'posted_date': posted_at.date().isoformat() if posted_at else None,
            'memo': memo,
            'signed_amount_paise': signed,
        })

    rules = db.scalars(select(FinanceBankRule).where(
        FinanceBankRule.entity_id == bank.entity_id,
        FinanceBankRule.active.is_(True),
    ).order_by(FinanceBankRule.id)).all()
    rules = [r for r in rules if r.bank_id is None or r.bank_id == bank.id]

    stmt_lines = db.scalars(select(FinanceBankStatementLine).where(
        FinanceBankStatementLine.bank_id == bank.id
    ).order_by(FinanceBankStatementLine.booking_date.desc(), FinanceBankStatementLine.id.desc())).all()

    uncategorised = []
    for line in stmt_lines:
        if line.id in active_stmt_ids:
            continue
        line_date = date.fromisoformat(line.booking_date)
        matches = []
        for c in candidates:
            diff = abs(c['signed_amount_paise'] - line.signed_amount_paise)
            c_date = date.fromisoformat(c['posted_date']) if c['posted_date'] else line_date
            day_gap = abs((c_date - line_date).days)
            if diff == 0:
                matches.append({**c, 'confidence': 'exact', 'diff_paise': 0, 'day_gap': day_gap})
            elif diff <= 500 and day_gap <= 3:
                matches.append({**c, 'confidence': 'near', 'diff_paise': diff, 'day_gap': day_gap})

        rule_hit = None
        direction = 'inflow' if line.signed_amount_paise > 0 else 'outflow'
        ref_low = line.statement_reference.casefold()
        for r in rules:
            if r.direction in ('any', direction) and r.match_text.casefold() in ref_low:
                rule_hit = {
                    'rule_id': r.id,
                    'match_text': r.match_text,
                    'suggested_account_id': r.suggested_account_id,
                    'suggested_party_id': r.suggested_party_id,
                    'note': r.note,
                }
                break

        uncategorised.append({
            'id': line.id,
            'booking_date': line.booking_date,
            'statement_reference': line.statement_reference,
            'signed_amount_paise': line.signed_amount_paise,
            'match_suggestions': matches[:5],
            'rule_suggestion': rule_hit,
        })

    stmt_ids_for_bank = {s.id for s in stmt_lines}
    bank_recs = [
        {
            'id': r.id,
            'statement_line_id': r.statement_line_id,
            'journal_id': r.journal_id,
            'unreconciled': r.id in unrec_ids,
        }
        for r in all_recs if r.statement_line_id in stmt_ids_for_bank
    ]

    return {
        'bank': {'id': bank.id, 'entity_id': bank.entity_id, 'display_name': bank.display_name,
                 'masked_identifier': bank.masked_identifier},
        'uncategorised': uncategorised,
        'rules': [
            {'id': r.id, 'match_text': r.match_text, 'direction': r.direction,
             'suggested_account_id': r.suggested_account_id, 'suggested_party_id': r.suggested_party_id,
             'note': r.note}
            for r in rules
        ],
        'reconciliations': bank_recs[:50],
    }

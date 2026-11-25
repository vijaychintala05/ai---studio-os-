"""M2-3: Approved internal bank/cash transfers and multi-line manual journal entries.
Every movement goes through an approval ticket, enforces balanced debits/credits, checks
period locks, and protects reconciled movements from mutation or direct reversal.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import can_access_project
from .db import (
    AccountingEntity, ApprovalTicket, FinanceManualJournal, FinanceTransfer, GLAccount,
    Party, Project, User, add_audit,
)
from .security import FINANCE_WRITE

TRANSFER_JOURNAL_TYPES = {
    'finance_transfer', 'finance_reverse_transfer',
    'finance_manual_journal', 'finance_reverse_manual_journal',
}
TRANSFER_JOURNAL_FIELDS = {
    'finance_transfer': {
        'entity_id', 'from_account_id', 'to_account_id', 'amount_paise',
        'transfer_date', 'reference', 'note', 'idempotency_key',
    },
    'finance_reverse_transfer': {'transfer_id', 'reason'},
    'finance_manual_journal': {
        'entity_id', 'entry_date', 'reference', 'narration', 'lines', 'idempotency_key',
    },
    'finance_reverse_manual_journal': {'manual_journal_id', 'reason'},
}
TRANSFER_EVENT = 'INTERNAL_TRANSFER_POSTED'
MANUAL_JOURNAL_EVENT = 'MANUAL_JOURNAL_POSTED'


def submitter(db: Session, item):
    ticket = db.get(ApprovalTicket, item.ticket_id)
    actor = db.get(User, ticket.submitter_id) if ticket and ticket.submitter_id else None
    if actor is None or not actor.active or actor.role not in FINANCE_WRITE:
        raise ValueError('An active member of the money team must submit this entry.')
    return actor


def display_values(db: Session, data: dict) -> dict:
    out = {}
    for field, model in (('entity_id', AccountingEntity), ('from_account_id', GLAccount), ('to_account_id', GLAccount)):
        ident = data.get(field)
        row = db.get(model, ident) if type(ident) is int else None
        if row is not None:
            out[field] = row.name
    return out


def validate(db: Session, kind: str, data: dict, actor=None):
    from .accounting_kernel import (
        _calendar_date, _check_dated_posting, _is_reversed, _policy, _reconciled, positive_minor, required_text,
    )
    if not isinstance(data, dict) or set(data) - TRANSFER_JOURNAL_FIELDS[kind]:
        raise ValueError('Unrecognized journal or transfer details.')

    if kind == 'finance_reverse_transfer':
        if set(data) != {'transfer_id', 'reason'}:
            raise ValueError('Choose a posted transfer and give a reason to reverse it.')
        tid = data.get('transfer_id')
        tr = db.get(FinanceTransfer, tid) if type(tid) is int else None
        if tr is None or not tr.journal_id or _is_reversed(db, tr.journal_id):
            raise ValueError('Posted transfer required.')
        if _reconciled(db, tr.journal_id):
            raise ValueError('This transfer is already matched to your bank statement. Reverse the match first.')
        required_text(data.get('reason'), 'Reversal reason', 400)
        return tr

    if kind == 'finance_reverse_manual_journal':
        if set(data) != {'manual_journal_id', 'reason'}:
            raise ValueError('Choose a posted manual journal and give a reason to reverse it.')
        mid = data.get('manual_journal_id')
        mj = db.get(FinanceManualJournal, mid) if type(mid) is int else None
        if mj is None or not mj.journal_id or _is_reversed(db, mj.journal_id):
            raise ValueError('Posted manual journal required.')
        if _reconciled(db, mj.journal_id):
            raise ValueError('This journal is already matched to your bank statement. Reverse the match first.')
        required_text(data.get('reason'), 'Reversal reason', 400)
        return mj

    if kind == 'finance_transfer':
        required = {'entity_id', 'from_account_id', 'to_account_id', 'amount_paise', 'transfer_date', 'idempotency_key'}
        if not required <= set(data):
            raise ValueError('Choose company, From account, To account, amount, date and request key.')
        ent = db.get(AccountingEntity, data.get('entity_id')) if type(data.get('entity_id')) is int else None
        if ent is None:
            raise ValueError('Choose an existing company.')
        _, policy, _, _ = _policy(db, ent.id)
        src = db.get(GLAccount, data.get('from_account_id')) if type(data.get('from_account_id')) is int else None
        dst = db.get(GLAccount, data.get('to_account_id')) if type(data.get('to_account_id')) is int else None
        if src is None or src.entity_id != ent.id or src.kind not in ('bank', 'cash') or not src.active or not src.posting_allowed:
            raise ValueError('Choose an active bank or cash From account for this company.')
        if dst is None or dst.entity_id != ent.id or dst.kind not in ('bank', 'cash') or not dst.active or not dst.posting_allowed:
            raise ValueError('Choose an active bank or cash To account for this company.')
        if src.id == dst.id:
            raise ValueError('Choose two different accounts for a transfer.')
        positive_minor(data.get('amount_paise'))
        tdate = _calendar_date(data.get('transfer_date'), 'Transfer date')
        _check_dated_posting(db, ent.id, 'bank', tdate, 'Transfer date')
        ikey = required_text(data.get('idempotency_key'), 'Idempotency key', 120)
        if db.scalar(select(FinanceTransfer.id).where(FinanceTransfer.idempotency_key == ikey)):
            raise ValueError('This transfer was already posted.')
        ref = (data.get('reference') or '').strip()
        note = (data.get('note') or '').strip()
        if len(ref) > 120 or len(note) > 400:
            raise ValueError('Reference or note is too long.')
        return ent, policy, src, dst, tdate, ref, note, ikey

    # finance_manual_journal
    required = {'entity_id', 'entry_date', 'narration', 'lines', 'idempotency_key'}
    if not required <= set(data):
        raise ValueError('Manual journal requires company, date, narration, lines and request key.')
    ent = db.get(AccountingEntity, data.get('entity_id')) if type(data.get('entity_id')) is int else None
    if ent is None:
        raise ValueError('Choose an existing company.')
    _, policy, _, _ = _policy(db, ent.id)
    edate = _calendar_date(data.get('entry_date'), 'Journal date')
    narration = required_text(data.get('narration'), 'Narration', 400)
    ref = (data.get('reference') or '').strip()
    if len(ref) > 120:
        raise ValueError('Reference is too long.')
    ikey = required_text(data.get('idempotency_key'), 'Idempotency key', 120)
    if db.scalar(select(FinanceManualJournal.id).where(FinanceManualJournal.idempotency_key == ikey)):
        raise ValueError('This manual journal was already posted.')
    raw_lines = data.get('lines')
    if not isinstance(raw_lines, list) or not (2 <= len(raw_lines) <= 50):
        raise ValueError('A manual journal needs between 2 and 50 lines.')
    cleaned, debit_total, credit_total, touches_bank = [], 0, 0, False
    for idx, ln in enumerate(raw_lines, 1):
        if not isinstance(ln, dict) or set(ln) - {'account_id', 'side', 'amount_paise', 'project_id', 'supplier_id'}:
            raise ValueError(f'Journal line {idx} is not valid.')
        acc = db.get(GLAccount, ln.get('account_id')) if type(ln.get('account_id')) is int else None
        if acc is None or acc.entity_id != ent.id or not acc.active or not acc.posting_allowed:
            raise ValueError(f'Journal line {idx}: choose an active posting account for this company.')
        if acc.kind == 'bank':
            touches_bank = True
        side = ln.get('side')
        if side not in ('debit', 'credit'):
            raise ValueError(f'Journal line {idx}: side must be debit or credit.')
        amt = ln.get('amount_paise')
        positive_minor(amt)
        pid = ln.get('project_id')
        if pid is not None:
            proj = db.get(Project, pid) if type(pid) is int else None
            if proj is None or proj.deleted_at:
                raise ValueError(f'Journal line {idx}: project not found.')
            if actor is not None and not can_access_project(db, actor, proj.id):
                raise ValueError(f'Journal line {idx}: no access to that project.')
            from .project_links import require_project_company
            require_project_company(db, proj, ent.id)
        sid = ln.get('supplier_id')
        if sid is not None:
            party = db.get(Party, sid) if type(sid) is int else None
            if party is None or party.deleted_at:
                raise ValueError(f'Journal line {idx}: party not found.')
        if side == 'debit':
            debit_total += amt
        else:
            credit_total += amt
        cleaned.append({'account': acc, 'account_id': acc.id, 'side': side, 'amount_paise': amt,
                        'project_id': pid, 'supplier_id': sid})
    if debit_total != credit_total:
        diff = abs(debit_total - credit_total)
        raise ValueError(f'Debits and credits are different by ₹{diff / 100:,.2f}. They must match.')
    _check_dated_posting(db, ent.id, 'bank' if touches_bank else 'purchases', edate, 'Journal date')
    return ent, policy, edate, ref, narration, cleaned, debit_total, ikey


def preview(db: Session, kind: str, data: dict, actor=None) -> dict:
    if kind in ('finance_reverse_transfer', 'finance_reverse_manual_journal'):
        obj = validate(db, kind, data, actor)
        return {'type': kind, 'id': obj.id, 'reason': data['reason']}
    if kind == 'finance_transfer':
        ent, _, src, dst, tdate, ref, _, _ = validate(db, kind, data, actor)
        return {'type': kind, 'entity_id': ent.id, 'transfer_date': tdate, 'reference': ref,
                'amount_paise': data['amount_paise'],
                'lines': [{'side': 'debit', 'account': dst.name, 'amount_paise': data['amount_paise']},
                          {'side': 'credit', 'account': src.name, 'amount_paise': data['amount_paise']}]}
    ent, _, edate, ref, narration, lines, total, _ = validate(db, kind, data, actor)
    return {'type': kind, 'entity_id': ent.id, 'entry_date': edate, 'reference': ref,
            'narration': narration, 'total_paise': total,
            'lines': [{'side': ln['side'], 'account': ln['account'].name, 'amount_paise': ln['amount_paise']} for ln in lines]}


def apply(db: Session, item, actor: str) -> dict:
    from .accounting_kernel import _post_lines, _reverse_posted
    kind, data = item.item_type, item.after_data or {}
    if kind == 'finance_reverse_transfer':
        ref_obj = db.get(FinanceTransfer, data.get('transfer_id')) if type(data.get('transfer_id')) is int else None
        if ref_obj is None:
            raise ValueError('Posted transfer required.')
        db.scalar(select(AccountingEntity).where(AccountingEntity.id == ref_obj.entity_id).with_for_update())
        tr = db.scalar(select(FinanceTransfer).where(FinanceTransfer.id == ref_obj.id).with_for_update())
        db.info.pop('_period_locks', None)
        validate(db, kind, data)
        rev = _reverse_posted(db, tr.journal_id, data['reason'], item.ticket_id)
        add_audit(db, 'finance_reverse_transfer', 'transfer', tr.id, f'Reversed transfer #{tr.id} (journal #{rev.id})', actor=actor)
        return {'type': 'reversing_journal', 'id': rev.id, 'item_id': item.id}

    if kind == 'finance_reverse_manual_journal':
        ref_obj = db.get(FinanceManualJournal, data.get('manual_journal_id')) if type(data.get('manual_journal_id')) is int else None
        if ref_obj is None:
            raise ValueError('Posted manual journal required.')
        db.scalar(select(AccountingEntity).where(AccountingEntity.id == ref_obj.entity_id).with_for_update())
        mj = db.scalar(select(FinanceManualJournal).where(FinanceManualJournal.id == ref_obj.id).with_for_update())
        db.info.pop('_period_locks', None)
        validate(db, kind, data)
        rev = _reverse_posted(db, mj.journal_id, data['reason'], item.ticket_id)
        add_audit(db, 'finance_reverse_manual_journal', 'manual_journal', mj.id, f'Reversed manual journal #{mj.id} (journal #{rev.id})', actor=actor)
        return {'type': 'reversing_journal', 'id': rev.id, 'item_id': item.id}

    ent_id = data.get('entity_id')
    if type(ent_id) is not int or db.get(AccountingEntity, ent_id) is None:
        raise ValueError('Choose an existing company.')
    db.scalar(select(AccountingEntity).where(AccountingEntity.id == ent_id).with_for_update())
    db.info.pop('_period_locks', None)
    requester = submitter(db, item)

    if kind == 'finance_transfer':
        ent, policy, src, dst, tdate, ref, note, ikey = validate(db, kind, data, requester)
        tr = FinanceTransfer(
            entity_id=ent.id, from_account_id=src.id, to_account_id=dst.id,
            amount_paise=data['amount_paise'], transfer_date=tdate, reference=ref,
            note=note, idempotency_key=ikey, ticket_id=item.ticket_id,
        )
        db.add(tr)
        db.flush()
        j = _post_lines(
            db, entity_id=ent.id, event_kind=TRANSFER_EVENT, event_key=f'transfer:{tr.id}',
            source_id=tr.id,
            lines=[
                (dst.id, 'debit', tr.amount_paise, None),
                (src.id, 'credit', tr.amount_paise, None),
            ],
            ticket_id=item.ticket_id, policy_version=policy.policy_version,
        )
        tr.journal_id = j.id
        add_audit(db, 'finance_transfer', 'transfer', tr.id,
                  f'Transferred ₹{tr.amount_paise / 100:,.2f} from {src.name} to {dst.name}', actor=actor)
        db.flush()
        return {'type': 'transfer', 'id': tr.id, 'item_id': item.id}

    ent, policy, edate, ref, narration, lines, total, ikey = validate(db, kind, data, requester)
    mj = FinanceManualJournal(
        entity_id=ent.id, entry_date=edate, reference=ref, narration=narration,
        total_paise=total, idempotency_key=ikey, ticket_id=item.ticket_id,
    )
    db.add(mj)
    db.flush()
    j = _post_lines(
        db, entity_id=ent.id, event_kind=MANUAL_JOURNAL_EVENT, event_key=f'manual_journal:{mj.id}',
        source_id=mj.id,
        lines=[(ln['account_id'], ln['side'], ln['amount_paise'], ln['project_id']) for ln in lines],
        ticket_id=item.ticket_id, policy_version=policy.policy_version,
    )
    mj.journal_id = j.id
    add_audit(db, 'finance_manual_journal', 'manual_journal', mj.id,
              f'Posted manual journal #{mj.id} (₹{total / 100:,.2f}): {narration[:120]}', actor=actor)
    db.flush()
    return {'type': 'manual_journal', 'id': mj.id, 'item_id': item.id}

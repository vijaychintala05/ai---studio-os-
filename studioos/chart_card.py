"""v0.9.14: text entries in the chat. A sentence becomes a DRAFT journal entry (plus a
suggested account when none fits), shown on the chat card with the accounts chosen and
why; a person can change any value or account; approving the ticket posts it.

Nothing here writes to the ledger. Posting happens only in chart_of_accounts.apply,
called by the ticket commit after approval.
"""
from __future__ import annotations
import json
from datetime import timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import (ApprovalTicket, ApprovalTicketItem, ChatSession, FinanceStandardInstall, FinanceTextEntry, GLAccount,
                 Project, add_audit, now)
from . import chart_of_accounts as coa
from . import finance_text as T


# ------------------------------------------------------------------ from a sentence to drafts

def _company(db: Session):
    ids = sorted({x for (x,) in db.execute(select(FinanceStandardInstall.entity_id)).all()})
    return ids


def chat_turn(db: Session, session, user, original, msg: str):
    """None when the message is not a money sentence for the books."""
    from .security import FINANCE_WRITE
    from .access import visible_project_ids, filter_projects
    if user.role not in FINANCE_WRITE:
        return None
    companies = _company(db)
    if not companies:
        return None
    ticket = db.scalar(select(ApprovalTicket).where(ApprovalTicket.session_id == session.id))
    open_ticket = ticket is not None and ticket.status not in ('committed', 'reversed')
    if len(companies) > 1:
        return None   # several companies: entries are made from the Ledger screen, where the company is chosen
    entity_id = companies[0]
    recipes = {r.key: r for r in coa.recipes(db, entity_id)}
    if not recipes:
        return None
    from .main import project_data
    allowed = visible_project_ids(db, user)
    projects = filter_projects(project_data(db), allowed)
    slots = T.read_entry(msg, [p['name'] for p in projects], coa.local_today())
    chosen = T.choose_recipe([r.definition for r in recipes.values()], msg, slots)
    if chosen is None or type(slots.get('amount')) is not int:
        # not a new entry: perhaps the answer to the card's question ("Sri Ram Traders", "18%")
        return _typed_answer(db, user, ticket, msg) if open_ticket else None
    evidence = slots.pop('evidence', {})
    project = slots.pop('project', None)
    project_id = next((p['id'] for p in projects if p['name'] == project), None)
    data = {'entity_id': entity_id, 'recipe': chosen['key'], 'slots': {k: v for k, v in slots.items() if k in T.SLOT_NAMES},
            'accounts': {}, 'project_id': project_id, 'idempotency_key': f'text:{session.id}:{original.id}'[:120]}
    item = draft(db, session, data, original.id)
    marks = dict(item.field_evidence or {})
    for name, words in evidence.items():
        if name == 'project':
            marks['project_id'] = {'marker': 'sourced', 'source_words': str(words)[:200]}
        else:
            marks['slots.' + name] = {'marker': 'sourced', 'source_words': str(words)[:200]}
    item.field_evidence = marks
    db.commit()
    return {'text': summary(db, item), 'item': item}


def draft(db: Session, session, data: dict, source_message_id: int, keep=None):
    """Create (or rework) the entry draft and any new-account suggestions it needs."""
    from .tickets import add_proposal
    ticket = db.scalar(select(ApprovalTicket).where(ApprovalTicket.session_id == session.id))
    worked = coa.plan_entry(db, data, ticket.id if ticket else None)
    plan, rec = worked['plan'], worked['recipe']
    data = {**data, 'slots': worked['slots'], 'accounts': dict(data.get('accounts') or {})}
    tokens = {}
    rows = coa.chart_rows(db, data['entity_id'])
    for index, sug in enumerate(plan['suggestions']):
        group = coa.group_by_code(rows, sug['parent_code'])
        if group is None:
            continue
        details = {'entity_id': data['entity_id'], 'name': sug['name'][:180], 'parent_id': group['id'],
                   'aliases': [sug['phrase'][:60]] if sug['phrase'].casefold() != sug['name'].casefold() else [],
                   'why': (f'No account found for "{sug["phrase"]}".' + (f' Closest: {", ".join(sug["near"])}.' if sug['near'] else ''))[:400]}
        ticket, item = add_proposal(db, session, 'finance_open_account', details, source_message_id, provider='rules')
        item.flags = ['New account suggested']
        tokens[index] = f'@item:{item.id}'
    for line in plan['lines']:
        slot = line.get('slot')
        if not slot:
            continue
        account = line['account']
        if isinstance(account, dict):
            account = tokens.get(account['suggestion'])
        if account is not None:
            data['accounts'][slot] = account
    used = {l.get('slot') for l in plan['lines']}
    data['accounts'] = {k: v for k, v in data['accounts'].items() if k in used}   # only accounts this entry uses
    if keep is not None:
        keep.after_data = data
        item = keep
    else:
        ticket, item = add_proposal(db, session, 'finance_text_entry', data, source_message_id, provider='rules')
    item.flags = _flags(db, data, plan, rec)
    db.flush()
    _drop_unused(db, item.ticket_id)
    return item


def _flags(db: Session, data: dict, plan: dict, rec) -> list[str]:
    """A posted entry of the SAME kind (a purchase, a payment...) for the same amount and account,
    or with the same bill number, in the last 30 days. Paying a bill in full is not a duplicate of it."""
    total = sum(l['amount'] for l in plan['lines'] if l['side'] == 'debit')
    flags = []
    since = now() - timedelta(days=30)
    for e in db.scalars(select(FinanceTextEntry).where(FinanceTextEntry.entity_id == data['entity_id'],
                                                       FinanceTextEntry.created_at >= since,
                                                       FinanceTextEntry.recipe_id.in_(select(coa.GLPostingRecipe.id).where(
                                                           coa.GLPostingRecipe.entity_id == data['entity_id'], coa.GLPostingRecipe.key == rec.key)))).all():
        same_ref = data['slots'].get('reference') and e.reference == data['slots'].get('reference')
        same = e.total_paise == total and any(v in (e.accounts or {}).values() for v in data['accounts'].values() if type(v) is int and
                                                v not in _shared_accounts(db, data['entity_id']))
        if same_ref or same:
            flags.append(f'POSSIBLE_DUPLICATE: entry #{e.id} "{e.narration[:80]}" ({coa.inr(e.total_paise)}) on {e.entry_date}')
            break
    return flags


def _shared_accounts(db: Session, entity_id: int) -> set:
    """Bank and cash are on most entries; sharing them does not suggest a duplicate."""
    return {a.id for a in db.scalars(select(GLAccount).where(GLAccount.entity_id == entity_id, GLAccount.kind.in_(['bank', 'cash']))).all()}


def _drop_unused(db: Session, ticket_id: int) -> None:
    items = db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.ticket_id == ticket_id)).all()
    used = json.dumps([i.after_data for i in items if i.item_type == 'finance_text_entry' and i.status != 'rejected'], default=str)
    for i in items:
        if i.item_type == 'finance_open_account' and i.status == 'pending' and 'New account suggested' in (i.flags or []) \
                and f'"@item:{i.id}"' not in used:
            i.status, i.review_note = 'rejected', 'No longer needed after the entry was changed'


# ------------------------------------------------------------------ changing a draft

PARTY_SLOTS = ('from_party', 'to_party')


def change(db: Session, user, ticket, item, changes: dict, how='edited', said=None, note=''):
    """Apply typed or tapped changes (slots.x, accounts.x, project_id) to an entry draft."""
    from .main import check_proposal_access
    from .tickets import log_decision, item_changes
    if item.item_type != 'finance_text_entry':
        raise ValueError('That draft cannot be changed this way')
    old = json.loads(json.dumps(item.after_data or {}))
    data = json.loads(json.dumps(old))
    rec = coa.recipe(db, data['entity_id'], data['recipe'])
    if rec is None:
        raise ValueError('This kind of entry is no longer set up for the company')
    for field, value in changes.items():
        group, _, name = str(field).partition('.')
        if field == 'project_id':
            if value in (None, '', 'none'):
                data['project_id'] = None
            else:
                project = _project(db, value)
                if project is None:
                    raise ValueError('Project not found')
                data['project_id'] = project.id
        elif group == 'slots' and name:
            if name not in T.SLOT_NAMES or name in ('party', 'project'):
                raise ValueError('That detail does not apply to this entry')
            value = coa.coerce_slot(name, value)
            if value is None:
                data['slots'].pop(name, None)
            else:
                data['slots'][name] = value
            if name == 'item':
                data['accounts'].pop('item', None)
            if name in PARTY_SLOTS:
                data['accounts'].pop('party', None)
            if name == 'bank':
                data['accounts'].pop('bank', None)
        elif group == 'accounts' and name in ('item', 'party', 'bank'):
            choices = {str(c['id']): c['id'] for c in coa.candidates_for(db, data['entity_id'], rec.definition, name, item.ticket_id)}
            if str(value) not in choices:
                raise ValueError('Choose one of the accounts offered for this entry')
            data['accounts'][name] = choices[str(value)]
            if name == 'item' and not data['slots'].get('item'):
                # a recipe only consults a chosen account when there are words to look up
                data['slots']['item'] = next(c['name'] for c in coa.candidates_for(db, data['entity_id'], rec.definition, name, item.ticket_id)
                                             if c['id'] == choices[str(value)]).replace(' (new)', '')
        else:
            raise ValueError('That detail does not apply to this entry')
    check_proposal_access(db, user, 'finance_text_entry', data)
    session = db.get(ChatSession, ticket.session_id)
    draft(db, session, data, item.source_message_id, keep=item)
    marks = dict(item.field_evidence or {})
    for field in changes:
        marks[field] = {'marker': how, 'source_words': said, 'previous': _get(old, field)}
    item.field_evidence = marks
    item.status, item.decided_by, item.review_note = 'pending', None, note
    if how == 'edited':
        item.flags = list(item.flags or []) + ['Edited by reviewer; requires reapproval']
        ticket.status = 'in_review'
    add_audit(db, 'edit_ticket_item', 'ticket_item', item.id,
              f'Ticket #{ticket.id} entry draft changed ({", ".join(changes)}). Previous: {json.dumps(old, ensure_ascii=False, default=str)[:240]}',
              actor=user.username)
    lines = item_changes(db, 'finance_text_entry', old, item.after_data)
    if lines:
        log_decision(db, ticket, user, ('answered' if how == 'answered' else 'edited') + ' the entry: ' + '; '.join(lines))


def _get(d, field):
    group, _, name = field.partition('.')
    return (d.get(group) or {}).get(name) if name else d.get(field)


def _project(db: Session, value):
    if type(value) is int:
        return db.get(Project, value)
    return next((p for p in db.scalars(select(Project).where(Project.deleted_at.is_(None))).all()
                 if p.name.casefold() == str(value).strip().casefold()), None)


def edit(db: Session, user, ticket, item, after: dict, note: str):
    """The Details screen's edit: the whole new draft. Only values can change, never the kind."""
    from .tickets import log_decision, item_changes
    old = item.after_data or {}
    if item.item_type == 'finance_text_entry':
        if any(after.get(k) != old.get(k) for k in ('entity_id', 'recipe', 'idempotency_key')):
            raise ValueError('The company and kind of entry cannot be changed; choose "Not now" and enter it again')
        changes = {}
        for name in set(old.get('slots') or {}) | set(after.get('slots') or {}):
            if (old.get('slots') or {}).get(name) != (after.get('slots') or {}).get(name):
                changes['slots.' + name] = (after.get('slots') or {}).get(name)
        for name in set(old.get('accounts') or {}) | set(after.get('accounts') or {}):
            if (old.get('accounts') or {}).get(name) != (after.get('accounts') or {}).get(name) and name in (after.get('accounts') or {}):
                changes['accounts.' + name] = after['accounts'][name]
        if after.get('project_id') != old.get('project_id'):
            changes['project_id'] = after.get('project_id')
        if not changes:
            return
        change(db, user, ticket, item, changes, note=note)
        return
    if item.item_type == 'finance_open_account':
        if after.get('entity_id') != old.get('entity_id'):
            raise ValueError('The company cannot be changed')
        new = {k: v for k, v in after.items() if k in coa.ALLOWED_FIELDS['finance_open_account']}
        coa.validate(db, 'finance_open_account', new, item.ticket_id)
        item.after_data = new
        item.status, item.decided_by, item.review_note = 'pending', None, note
        item.flags = list(dict.fromkeys(list(item.flags or []) + ['Edited by reviewer; requires reapproval']))
        ticket.status = 'in_review'
        add_audit(db, 'edit_ticket_item', 'ticket_item', item.id, f'Ticket #{ticket.id} new account draft edited', actor=user.username)
        lines = item_changes(db, 'finance_open_account', old, new)
        if lines:
            log_decision(db, ticket, user, 'edited the new account: ' + '; '.join(lines))
        return
    raise ValueError('This is installed or reversed as it is. Choose "Not now" to leave it out.')


def _typed_answer(db: Session, user, ticket, msg: str):
    """A short reply to the card's question ("Sri Ram Traders", "18%") fills that detail."""
    if len(msg) > 120 or msg.strip().casefold() in ('cancel', 'discard', 'stop', 'yes', 'no', 'ok', 'save', 'approve', 'confirm'):
        return None
    for item in db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.ticket_id == ticket.id,
                                                            ApprovalTicketItem.item_type == 'finance_text_entry',
                                                            ApprovalTicketItem.status == 'pending').order_by(ApprovalTicketItem.id.desc())).all():
        rec = coa.recipe(db, item.after_data['entity_id'], item.after_data['recipe'])
        try:
            missing = coa.plan_entry(db, item.after_data, ticket.id)['plan']['missing']
        except ValueError:
            continue
        for name in missing:
            slot = {'party': coa._party_slot(rec.definition), 'amount': 'amount', 'item': 'item', 'gst_rate': 'gst_rate'}.get(name)
            if slot is None:
                continue
            value = msg.strip().rstrip('.')
            if slot == 'gst_rate':
                value = value.replace('%', '').strip()
            try:
                change(db, user, ticket, item, {'slots.' + slot: value}, how='sourced', said=msg[:200])
            except ValueError:
                return None
            db.commit()
            return {'text': summary(db, item), 'item': item}
    return None


# ------------------------------------------------------------------ the card

def fill(db: Session, item: dict) -> None:
    after, marks = item.get('after') or {}, item.get('field_evidence') or {}
    item['needs_confirmation'] = ['duplicate'] if any('possible_duplicate' in str(f).casefold() for f in item.get('flags') or []) else []
    typ = item['item_type']
    if typ == 'finance_install_chart':
        try:
            std, _ = coa.standard_file(after.get('standard'))
        except ValueError as ex:
            item.update(title='Chart of accounts', line='Chart of accounts', fields=[], problems=[str(ex)])
            return
        item['title'] = 'Install a chart of accounts'
        item['line'] = f'Chart of accounts · {std["title"]} v{std["version"]}'
        item['fields'] = [{'key': 'standard', 'label': 'Standard', 'display': f'{std["title"]} (version {std["version"]})', 'raw': std['key'],
                           'marker': 'sourced', 'locked': True}]
        item['notes'] = [f'{sum(1 for a in std["accounts"] if a.get("group"))} groups and {sum(1 for a in std["accounts"] if not a.get("group"))} accounts',
                         'Understands: ' + ', '.join(r['title'] for r in std['recipes']),
                         'Adds to what exists; no account already in the books is changed.',
                         'Have your accountant review the groups and GST accounts.']
        _problems(db, item)
        return
    if typ == 'finance_open_account':
        rows = coa.chart_rows(db, after.get('entity_id')) if type(after.get('entity_id')) is int else {}
        groups = [r for r in rows.values() if r['is_group'] and r['child_kind'] not in ('', 'bank', 'payable', 'group')]
        parent = rows.get(after.get('parent_id'))
        item['title'] = 'New account'
        item['line'] = f'New account · {after.get("name", "")}' + (f' in {parent["name"]}' if parent else '')
        item['fields'] = [
            {'key': 'name', 'label': 'Account name', 'display': after.get('name') or '—', 'raw': after.get('name'), 'type': 'text',
             'marker': (marks.get('name') or {}).get('marker') or 'guessed'},
            {'key': 'parent_id', 'label': 'Group', 'display': parent['name'] if parent else '—', 'raw': after.get('parent_id'), 'type': 'choice',
             'marker': (marks.get('parent_id') or {}).get('marker') or 'guessed',
             'choices': [{'value': g['id'], 'label': g['name']} for g in sorted(groups, key=lambda g: g['name'])]}]
        item['explain'] = [after['why']] if after.get('why') else []
        _problems(db, item)
        return
    if typ == 'finance_reverse_text_entry':
        entry = db.get(FinanceTextEntry, after.get('entry_id')) if type(after.get('entry_id')) is int else None
        item['title'] = 'Reverse an entry'
        item['line'] = f'Reverse · {entry.narration if entry else "entry"}'
        item['fields'] = [{'key': 'reason', 'label': 'Reason', 'display': after.get('reason') or '—', 'raw': after.get('reason'), 'marker': 'sourced', 'locked': True}]
        item['journal'] = [{'side': 'Cr' if l['side'] == 'Dr' else 'Dr', 'account': l['account'], 'amount': coa.inr(l['amount_paise']), 'new': False}
                           for l in coa.journal_lines(db, entry.journal_id)] if entry else []
        _problems(db, item)
        return
    # finance_text_entry
    try:
        worked = coa.plan_entry(db, after, item.get('ticket_id'))
    except ValueError as ex:
        item.update(title='Entry', line='Entry', fields=[], problems=[str(ex)])
        return
    rec, plan, slots = worked['recipe'].definition, worked['plan'], worked['slots']
    party = coa._party_slot(rec)
    item['title'] = rec['title']
    missing = set(plan['missing'])
    fields = []
    for key, label, kind in coa.SLOT_FIELDS:
        value = slots.get(key)
        if key in PARTY_SLOTS and key != party:
            continue
        wanted = key in missing or (key == party and ('party' in missing or 'choose:party' in missing)) or ('choose:' + key) in missing
        if value in (None, '') and not wanted and key not in ('date', 'settlement'):
            continue
        if key in ('gst_rate', 'gst_amount', 'gst_type') and slots.get('gst_mode') in (None, 'none') and not wanted:
            continue
        if key == 'bank' and len(coa.candidates_for(db, after['entity_id'], rec, 'bank')) < 2:
            continue
        display = '—' if value in (None, '') else coa.inr(value) if kind == 'money' else coa.CHOICE_LABELS.get(value, str(value)) if kind == 'choice' else str(value)
        f = {'key': 'slots.' + key, 'label': label, 'display': display, 'raw': value, 'type': kind,
             'marker': 'missing' if value in (None, '') or wanted else (marks.get('slots.' + key) or {}).get('marker') or 'guessed',
             'source': (marks.get('slots.' + key) or {}).get('source_words')}
        if kind == 'choice':
            f['choices'] = [{'value': c, 'label': coa.CHOICE_LABELS[c]} for c in coa.SLOT_CHOICES[key] if c != 'unknown']
        fields.append(f)
    from .main import project_data
    project = next((p for p in project_data(db) if p['id'] == after.get('project_id')), None)
    fields.append({'key': 'project_id', 'label': 'Project', 'display': project['name'] if project else 'Office (no project)',
                   'raw': project['name'] if project else None, 'type': 'project',
                   'marker': (marks.get('project_id') or {}).get('marker') or ('sourced' if project else 'guessed')})
    labels = {'item': f'Account for "{slots.get("item") or "the item"}"', 'party': f'Account for {slots.get(party) or "the party"}', 'bank': 'Bank account'}
    for line in plan['lines']:
        slot = line.get('slot')
        if not slot or any(f['key'] == 'accounts.' + slot for f in fields):
            continue
        choices = coa.candidates_for(db, after['entity_id'], rec, slot, item.get('ticket_id'))
        fields.append({'key': 'accounts.' + slot, 'label': labels[slot], 'display': line['account_name'] + (' (new)' if str(line['account']).startswith('@item') else ''),
                       'raw': line['account'], 'type': 'choice', 'choices': [{'value': c['id'], 'label': c['name']} for c in choices],
                       'marker': (marks.get('accounts.' + slot) or {}).get('marker') or 'guessed', 'source': line['how']})
    item['fields'] = fields
    item['journal'] = [{'side': 'Dr' if l['side'] == 'debit' else 'Cr', 'account': l['account_name'], 'amount': coa.inr(l['amount']),
                        'new': str(l['account']).startswith('@item') or isinstance(l['account'], dict)} for l in plan['lines']]
    item['explain'] = plan['explain']
    item['line'] = f'{rec["title"]} · ' + ' · '.join(f'{j["side"]} {j["account"]} {j["amount"]}' for j in item['journal'])
    _problems(db, item, skip_missing=True)


def _problems(db: Session, item: dict, skip_missing=False) -> None:
    if item.get('status') != 'pending':
        item['problems'] = []
        return
    try:
        coa.validate(db, item['item_type'], item.get('after') or {}, item.get('ticket_id'))
        item['problems'] = []
    except ValueError as ex:
        parts = [p.strip() for p in str(ex).split(';') if p.strip()]
        if skip_missing:
            parts = [p for p in parts if not p.startswith(('Still needed', 'More than one account', 'Choose which bank'))]
        item['problems'] = parts[:4]


def asks(db: Session, items: list[dict]) -> list[dict]:
    """Tap-to-answer questions for what an entry still needs."""
    out = []
    for item in items:
        after = item.get('after') or {}
        if item.get('item_type') != 'finance_text_entry' or item.get('status') != 'pending':
            continue
        try:
            worked = coa.plan_entry(db, after, item.get('ticket_id'))
        except ValueError:
            continue
        slots, plan, rec = worked['slots'], worked['plan'], worked['recipe'].definition
        party = coa._party_slot(rec)
        for name in plan['missing']:
            ask = None
            if name == 'gst_rate' and slots.get('gst_mode') == 'unknown':
                ask = {'text': 'Is GST included in that amount?', 'field': 'slots.gst_mode',
                       'choices': [{'label': 'Added on top', 'value': 'extra'}, {'label': 'Included', 'value': 'included'}, {'label': 'No GST', 'value': 'none'}]}
            elif name == 'gst_rate':
                ask = {'text': 'What GST rate applies?', 'field': 'slots.gst_rate', 'choices': [{'label': f'{r}%', 'value': r} for r in (5, 12, 18, 28)]}
            elif name.startswith('choose:'):
                slot = name[7:]
                what = 'Which bank was it?' if slot == 'bank' else f'More than one account fits "{slots.get(party if slot == "party" else slot, "")}". Which one?'
                ask = {'text': what, 'field': 'accounts.' + slot,
                       'choices': [{'label': c['name'], 'value': c['id']} for c in plan['choices'].get(slot, [])][:5]}
            elif name in ('amount', 'item', 'party'):
                slot = party if name == 'party' else name
                ask = {'text': {'amount': 'What was the amount?', 'item': 'What was it for?', 'party': 'Who was it with?'}[name],
                       'field': 'slots.' + slot, 'choices': []}
            if ask:
                out.append({'id': f'coa-{item["id"]}-{name}'[:60], 'item_id': item['id'], 'free_text': not ask['choices'], **ask})
    return out[:4]


def summary(db: Session, item) -> str:
    """What the assistant says about a new or changed entry draft."""
    after = item.after_data or {}
    try:
        worked = coa.plan_entry(db, after, item.ticket_id)
    except ValueError as ex:
        return str(ex)
    plan, rec = worked['plan'], worked['recipe'].definition
    parts = [f'I read this as **{rec["title"].lower()}**.']
    if plan['lines']:
        parts.append('It would be entered as: ' + '; '.join(
            f'{"Dr" if l["side"] == "debit" else "Cr"} {l["account_name"]} {coa.inr(l["amount"])}' for l in plan['lines']) + '.')
    new = [l['account_name'] for l in plan['lines'] if str(l['account']).startswith('@item')]
    if new:
        parts.append('There is no account for ' + ' or '.join(f'"{n}"' for n in dict.fromkeys(new)) +
                     ' yet, so I have suggested one for you to approve with the entry.')
    notes = [e for e in plan['explain'] if 'assumed' in e or 'used' in e]
    if notes:
        parts.append(' '.join(n + '.' for n in notes))
    if any('possible_duplicate' in str(f).casefold() for f in item.flags or []):
        parts.append('A similar entry was posted recently; check it is not the same one.')
    parts.append('I still need a detail before it can be posted.' if plan['missing'] else 'Nothing is posted until you approve.')
    return ' '.join(parts)


def describe(db: Session, old: dict, new: dict) -> list[str]:
    """'Amount: ₹21,000 → ₹20,000', 'Account for "cement": Cement → Plywood and Boards'."""
    lines = []
    labels = {k: (l, t) for k, l, t in coa.SLOT_FIELDS}
    os_, ns = (old or {}).get('slots') or {}, (new or {}).get('slots') or {}
    for k in dict.fromkeys([*os_, *ns]):
        if os_.get(k) != ns.get(k) and k in labels:
            show = lambda v: '—' if v in (None, '') else coa.inr(v) if labels[k][1] == 'money' else coa.CHOICE_LABELS.get(v, str(v))
            lines.append(f'{labels[k][0]}: {show(os_.get(k))} → {show(ns.get(k))}')
    oa, na = (old or {}).get('accounts') or {}, (new or {}).get('accounts') or {}
    for k in dict.fromkeys([*oa, *na]):
        if oa.get(k) != na.get(k):
            lines.append(f'Account for {k}: {_account_name(db, oa.get(k))} → {_account_name(db, na.get(k))}')
    if (old or {}).get('project_id') != (new or {}).get('project_id'):
        lines.append(f'Project: {_project_name(db, (old or {}).get("project_id"))} → {_project_name(db, (new or {}).get("project_id"))}')
    for k, label in (('name', 'Account name'), ('parent_id', 'Group')):
        if k in (old or {}) or k in (new or {}):
            if (old or {}).get(k) != (new or {}).get(k):
                show = (lambda v: _account_name(db, v)) if k == 'parent_id' else (lambda v: v or '—')
                lines.append(f'{label}: {show((old or {}).get(k))} → {show((new or {}).get(k))}')
    return lines


def _account_name(db: Session, value) -> str:
    if value is None:
        return '—'
    if isinstance(value, str) and value.startswith('@item:'):
        item = db.get(ApprovalTicketItem, int(value.split(':', 1)[1]))
        return ((item.after_data or {}).get('name') or 'new account') + ' (new)' if item else 'new account'
    a = db.get(GLAccount, value) if type(value) is int else None
    return a.name if a else '—'


def _project_name(db: Session, value) -> str:
    p = db.get(Project, value) if type(value) is int else None
    return p.name if p else 'Office (no project)'

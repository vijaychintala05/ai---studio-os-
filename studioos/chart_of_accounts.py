"""Chart of accounts in groups, approved posting recipes and text entries (v0.9.14).

Built on the v0.9.13 protected ledger, not beside it: accounts are GLAccount rows,
every entry is a GLJournal with GLLine rows posted by accounting_kernel._post_lines,
and every change arrives as an approved ticket item:

  finance_install_chart        install or update a standard (groups, accounts, recipes)
  finance_open_account         a new account, usually suggested because nothing matched
  finance_text_entry           "Bought 50 bags of cement from Sri Ram Traders ..." posted
                               through an approved recipe
  finance_reverse_text_entry   a linked reversing journal for a posted text entry

What the AI (or the offline reader) supplies is only VALUES: amount, item words, party
words, GST rate. Which accounts may be used, and how the lines are formed, comes from
the approved recipe; the chosen accounts are shown to a person and approved; and the
lines are worked out again from the recipe at the moment of posting.
"""
from __future__ import annotations
import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .db import (AccountingEntity, GLAccount, GLAccountProfile, GLJournal, GLLine, GLPostingRecipe,
                 FinanceStandardInstall, FinanceTextEntry, FinanceReversal, RegisteredBank, ClosedAccountingPeriod,
                 ApprovalTicketItem, Party, Project, add_audit)
from . import finance_text as T

STANDARDS = Path(__file__).resolve().parent / 'finance_standards'
KIND_NATURE = {'expense': 'expense', 'payable': 'liability', 'bank': 'asset', 'advance': 'asset', 'inventory': 'asset',
               'grni': 'liability', 'cash': 'asset', 'input_tax': 'asset', 'output_tax': 'liability', 'asset': 'asset',
               'liability': 'liability', 'equity': 'equity', 'income': 'income', 'creditor': 'liability', 'debtor': 'asset'}
NEW_ITEM_TYPES = ('finance_install_chart', 'finance_open_account', 'finance_text_entry', 'finance_reverse_text_entry', 'finance_opening_balances')
ALLOWED_FIELDS = {
    'finance_install_chart': {'entity_id', 'standard'},
    'finance_opening_balances': {'entity_id','as_of','balances'},
    'finance_open_account': {'entity_id', 'name', 'parent_id', 'aliases', 'why'},
    'finance_text_entry': {'entity_id', 'recipe', 'slots', 'accounts', 'project_id', 'idempotency_key'},
    'finance_reverse_text_entry': {'entry_id', 'reason'},
}
SLOT_FIELDS = [('amount', 'Amount', 'money'), ('item', 'For', 'text'), ('from_party', 'From', 'text'), ('to_party', 'To', 'text'),
               ('gst_mode', 'GST', 'choice'), ('gst_rate', 'GST rate %', 'decimal'), ('gst_amount', 'GST amount', 'money'),
               ('gst_type', 'GST type', 'choice'), ('settlement', 'Paid by', 'choice'), ('bank', 'Bank', 'text'),
               ('date', 'Date', 'date'), ('reference', 'Bill number', 'text'), ('quantity', 'Quantity', 'text')]
SLOT_CHOICES = {'gst_mode': ['none', 'extra', 'included', 'unknown'], 'settlement': ['credit', 'cash', 'bank'], 'gst_type': ['intra', 'inter']}
CHOICE_LABELS = {'none': 'No GST', 'extra': 'Added on top', 'included': 'Included in the amount', 'unknown': 'Not clear', 'credit': 'On credit',
                 'cash': 'Cash', 'bank': 'Bank', 'intra': 'Within the state (CGST + SGST)', 'inter': 'Other state (IGST)'}


def local_today() -> date:
    """The firm's calendar day (STUDIOOS_TIMEZONE, default India), not the server's UTC day."""
    import os
    try:
        from zoneinfo import ZoneInfo
        from .runtime_clock import utc_now
        return utc_now().astimezone(ZoneInfo(os.getenv('STUDIOOS_TIMEZONE', 'Asia/Kolkata'))).date()
    except Exception:
        if os.getenv('STUDIOOS_SIMULATION_CLOCK'):raise
        return datetime.now(timezone.utc).date()


def inr(paise) -> str:
    from .chat_ux import inr as _inr
    return _inr(paise)


# ------------------------------------------------------------------ standards (data files)

def standard_file(key: str) -> tuple[dict, str]:
    if not re.fullmatch(r'[a-z][a-z_]{1,40}', str(key or '')):
        raise ValueError('Unknown chart of accounts standard')
    path = STANDARDS / f'{key}.json'
    if not path.is_file():
        raise ValueError('Unknown chart of accounts standard')
    raw = path.read_bytes()
    try:
        return T.check_standard(json.loads(raw)), hashlib.sha256(raw).hexdigest()
    except T.StandardError as ex:
        raise ValueError(f'The standard file is not well formed: {ex}')


def installed(db: Session, entity_id: int) -> FinanceStandardInstall | None:
    return db.scalar(select(FinanceStandardInstall).where(FinanceStandardInstall.entity_id == entity_id)
                     .order_by(FinanceStandardInstall.version.desc(), FinanceStandardInstall.id.desc()).limit(1))


def available_standards(db: Session, entity_id: int) -> list[dict]:
    have = installed(db, entity_id)
    out = []
    for path in sorted(STANDARDS.glob('*.json')):
        std, _ = standard_file(path.stem)
        state = 'not installed' if have is None or have.standard_key != std['key'] else \
            'installed' if have.version >= std['version'] else 'update available'
        out.append({'key': std['key'], 'title': std['title'], 'version': std['version'], 'description': std['description'],
                    'accounts': sum(1 for a in std['accounts'] if not a.get('group')), 'groups': sum(1 for a in std['accounts'] if a.get('group')),
                    'recipes': [r['title'] for r in std['recipes']], 'state': state,
                    'installed_version': have.version if have and have.standard_key == std['key'] else None})
    return out


# ------------------------------------------------------------------ the chart as it stands

def chart_rows(db: Session, entity_id: int) -> dict[int, dict]:
    """Every account of the entity with its CURRENT place (newest profile row)."""
    accounts = db.scalars(select(GLAccount).where(GLAccount.entity_id == entity_id)).all()
    latest = {}
    for p in db.scalars(select(GLAccountProfile).join(GLAccount, GLAccount.id == GLAccountProfile.account_id)
                        .where(GLAccount.entity_id == entity_id).order_by(GLAccountProfile.id)).all():
        latest[p.account_id] = p
    rows = {}
    for a in accounts:
        p = latest.get(a.id)
        rows[a.id] = {'id': a.id, 'code': a.code, 'name': a.name, 'kind': a.kind, 'active': a.active,
                      'postable': bool(a.posting_allowed and a.active and not (p and p.is_group)),
                      'parent': p.parent_id if p else None, 'is_group': bool(p and p.is_group),
                      'nature': p.nature if p else KIND_NATURE.get(a.kind, 'asset'),
                      'child_kind': p.child_kind if p else '', 'aliases': list(p.aliases or []) if p else [],
                      'party_id': p.party_id if p else None}
    return rows


def _subtree(rows: dict, codes) -> set[int]:
    roots = {i for i, r in rows.items() if r['code'] in set(codes or ())}
    children = {}
    for i, r in rows.items():
        children.setdefault(r['parent'], []).append(i)
    out, stack = set(), list(roots)
    while stack:
        node = stack.pop()
        for child in children.get(node, []):
            if child not in out:
                out.add(child)
                stack.append(child)
    return out


def group_by_code(rows: dict, code: str) -> dict | None:
    return next((r for r in rows.values() if r['code'] == code and r['is_group']), None)


def _banks(db: Session, entity_id: int, rows: dict) -> list[dict]:
    out = []
    for b in db.scalars(select(RegisteredBank).where(RegisteredBank.entity_id == entity_id).order_by(RegisteredBank.id)).all():
        r = rows.get(b.gl_account_id)
        if r and r['postable'] and r['kind'] == 'bank':
            out.append({'id': r['id'], 'name': b.display_name, 'aliases': [b.masked_identifier] if b.masked_identifier else []})
    return out


def _pending_accounts(db: Session, ticket_id: int | None) -> list[dict]:
    """Accounts suggested earlier in the same ticket, so one draft can use another's suggestion."""
    if ticket_id is None:
        return []
    out = []
    for item in db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.ticket_id == ticket_id,
                                                            ApprovalTicketItem.item_type == 'finance_open_account',
                                                            ApprovalTicketItem.status != 'rejected').order_by(ApprovalTicketItem.id)).all():
        d = item.after_data or {}
        out.append({'id': f'@item:{item.id}', 'name': d.get('name', ''), 'aliases': d.get('aliases') or [], 'parent': d.get('parent_id')})
    return out


def finder(db: Session, entity_id: int, ticket_id: int | None, fixed: dict | None = None):
    """The account lookup a recipe uses. With `fixed` (the approved choices) it only
    checks those choices are allowed; without, it searches."""
    rows = chart_rows(db, entity_id)
    fixed = fixed or {}

    def allowed_ids(spec) -> set:
        return _subtree(rows, spec['under'])

    def find(spec):
        if spec.get('role') == 'bank':
            banks = _banks(db, entity_id, rows)
            if 'bank' in fixed:
                b = next((x for x in banks if x['id'] == fixed['bank']), None)
                return b
            if spec.get('choice'):
                r = T.search(banks, spec['choice'])
                if r['match']:
                    return r['match']
            if len(banks) == 1:
                return banks[0]
            return {'ambiguous': True, 'choices': banks} if banks else None
        if 'code' in spec:
            r = next((x for x in rows.values() if x['code'] == spec['code']), None)
            return {'id': r['id'], 'name': r['name']} if r and r['postable'] else None
        slot = spec.get('slot')
        pool_ids = allowed_ids(spec)
        create_group = group_by_code(rows, spec['create_under']) if spec.get('create_under') else None
        pending = [p for p in _pending_accounts(db, ticket_id)
                   if p['parent'] in pool_ids | {r['id'] for r in rows.values() if r['code'] in set(spec['under'])}
                   or (create_group and p['parent'] == create_group['id'])]
        if slot in fixed:
            choice = fixed[slot]
            if isinstance(choice, str):
                p = next((x for x in pending if x['id'] == choice), None)
                return {'match': {'id': p['id'], 'name': p['name'], 'how': 'new account, approved with this entry'} if p else None,
                        'ambiguous': False, 'choices': [], 'refused': p is None}
            r = rows.get(choice)
            ok = r is not None and r['postable'] and choice in pool_ids
            return {'match': {'id': r['id'], 'name': r['name'], 'how': 'chosen account'} if ok else None,
                    'ambiguous': False, 'choices': [], 'refused': not ok}
        pool = [r for i, r in rows.items() if i in pool_ids and r['postable']] + pending
        result = T.search(pool, spec['phrase'])
        return {'match': result['match'], 'ambiguous': result['ambiguous'], 'choices': [c for _, c in result['ranked']]}
    return find


def candidates_for(db: Session, entity_id: int, recipe: dict, slot: str, ticket_id=None) -> list[dict]:
    """Accounts a person may choose for this part of the entry (for the card's picker)."""
    rows = chart_rows(db, entity_id)
    if slot == 'bank':
        return _banks(db, entity_id, rows)
    groups = set()
    for ln in recipe['lines']:
        specs = [ln['account']] + list((ln['account'].get('settle') or {}).values())
        for spec in specs:
            if spec.get('find') == slot:
                groups |= {spec['under'], spec.get('also_under')} - {None}
    ids = _subtree(rows, groups)
    out = [{'id': r['id'], 'name': r['name']} for i, r in rows.items() if i in ids and r['postable']]
    out += [{'id': p['id'], 'name': p['name'] + ' (new)'} for p in _pending_accounts(db, ticket_id)]
    return sorted(out, key=lambda x: str(x['name']).casefold())[:200]


# ------------------------------------------------------------------ recipes

def recipes(db: Session, entity_id: int) -> list[GLPostingRecipe]:
    """The newest version of each recipe for the entity."""
    newest = {}
    for r in db.scalars(select(GLPostingRecipe).where(GLPostingRecipe.entity_id == entity_id).order_by(GLPostingRecipe.version)).all():
        newest[r.key] = r
    return list(newest.values())


def recipe(db: Session, entity_id: int, key: str) -> GLPostingRecipe | None:
    return db.scalar(select(GLPostingRecipe).where(GLPostingRecipe.entity_id == entity_id, GLPostingRecipe.key == key)
                     .order_by(GLPostingRecipe.version.desc()).limit(1))


def _clean_slots(slots) -> dict:
    if not isinstance(slots, dict):
        raise ValueError('Entry details must be a set of values')
    clean = {}
    for name, value in slots.items():
        if name not in T.SLOT_NAMES or name in ('party', 'project'):
            raise ValueError(f'"{name}" is not a detail of an entry')
        value = coerce_slot(name, value)
        if value is not None:
            clean[name] = value
    if clean.get('gst_mode') == 'none':
        clean.pop('gst_rate', None)
        clean.pop('gst_amount', None)
    return clean


def coerce_slot(name: str, value):
    kind = next((k for n, _, k in SLOT_FIELDS if n == name), 'text')
    if value in (None, ''):
        return None
    if kind == 'money':
        if isinstance(value,float):
            raise ValueError('Money uses whole paise as an integer or rupees as text, never a decimal JSON number')
        if type(value) is int:
            paise = value
        else:
            text = str(value).replace(',', '').replace('₹', '').strip()
            if not re.fullmatch(r'\d{1,13}(?:\.\d{1,2})?', text):
                raise ValueError('Give an amount like 21000 or 21,000.50')
            rupees, _, p = text.partition('.')
            paise = int(rupees) * 100 + int((p + '00')[:2])
        if not 0 < paise < 10 ** 14:
            raise ValueError('The amount must be more than zero')
        return paise
    if kind == 'decimal':
        try:
            number = float(str(value).replace('%', '').strip())
        except ValueError:
            raise ValueError('Give a rate like 18')
        if not 0 <= number <= 50:
            raise ValueError('GST rate must be between 0 and 50')
        return number
    if kind == 'choice':
        v = str(value).strip().casefold()
        if v not in SLOT_CHOICES[name]:
            raise ValueError('Choose one of: ' + ', '.join(CHOICE_LABELS[c] for c in SLOT_CHOICES[name] if c != 'unknown'))
        return v
    if kind == 'date':
        try:
            return date.fromisoformat(str(value)).isoformat()
        except ValueError:
            raise ValueError('Give the date as YYYY-MM-DD')
    text = str(value).strip()
    if len(text) > 120:
        raise ValueError('Keep it under 120 characters')
    return text or None


def plan_entry(db: Session, d: dict, ticket_id: int | None) -> dict:
    """Recipe + values (+ chosen accounts) -> lines and anything still missing."""
    rec = recipe(db, d.get('entity_id'), d.get('recipe')) if type(d.get('entity_id')) is int else None
    if rec is None:
        raise ValueError('This kind of entry is not set up for the company; install a chart of accounts standard first')
    slots = _clean_slots(d.get('slots') or {})
    accounts = d.get('accounts') or {}
    if not isinstance(accounts, dict) or any(k not in ('item', 'party', 'bank') for k in accounts) or \
            any(not (type(v) is int or (isinstance(v, str) and re.fullmatch(r'@item:\d+', v))) for v in accounts.values()):
        raise ValueError('Chosen accounts must be existing accounts or accounts suggested in this ticket')
    find = finder(db, d['entity_id'], ticket_id, accounts)
    plan = T.plan(rec.definition, slots, find)
    return {'recipe': rec, 'slots': slots, 'plan': plan}


# ------------------------------------------------------------------ validation

def _entity(db: Session, entity_id) -> AccountingEntity:
    entity = db.get(AccountingEntity, entity_id) if type(entity_id) is int else None
    if entity is None or entity.base_currency != 'INR':
        raise ValueError('An approved INR company (accounting entity) is required')
    return entity


def _month_closed(db: Session, entity_id: int, day: str) -> bool:
    return bool(db.scalar(select(ClosedAccountingPeriod.id).where(ClosedAccountingPeriod.entity_id == entity_id,
                                                                  ClosedAccountingPeriod.year_month == day[:7])))


def _same_name(rows: dict, name: str, exclude=None) -> dict | None:
    want = re.sub(r'\s+', ' ', name).strip().casefold()
    return next((r for r in rows.values() if r['name'].casefold() == want and r['id'] != exclude), None)


def opening_plan(db: Session, d: dict) -> list[dict]:
    if set(d) != {'entity_id','as_of','balances'}:
        raise ValueError('Opening balances need company, cutover date and signed integer-paise balances')
    _entity(db,d['entity_id'])
    try:
        opening_date=date.fromisoformat(d['as_of'])
        if opening_date.isoformat()!=d['as_of'] or opening_date>local_today():raise ValueError()
    except (ValueError,TypeError):raise ValueError('Opening date must be YYYY-MM-DD and not in the future')
    if installed(db,d['entity_id']) is None:raise ValueError('Install the approved chart first')
    if _month_closed(db,d['entity_id'],d['as_of']):raise ValueError('Opening period is closed')
    if db.scalar(select(GLJournal.id).where(GLJournal.entity_id==d['entity_id']).limit(1)):
        raise ValueError('Opening balances are allowed only once, before any journal is posted')
    balances=d['balances']
    if not isinstance(balances,list) or not 2<=len(balances)<=20:raise ValueError('Use 2 to 20 opening account balances')
    rows=chart_rows(db,d['entity_id']);seen=set();plan=[]
    for value in balances:
        if not isinstance(value,dict) or set(value)!={'account_id','signed_paise'}:raise ValueError('Each balance needs account_id and signed_paise')
        aid=value['account_id'];amount=value['signed_paise']
        if type(aid) is not int or type(amount) is not int or not 0<abs(amount)<=9_000_000_000_000_000:
            raise ValueError('Opening balances are exact nonzero integer paise within the supported range')
        if aid in seen:raise ValueError('An opening account appears more than once')
        seen.add(aid);account=rows.get(aid)
        if not account or account['is_group'] or not account['postable'] or not account['active']:
            raise ValueError('Opening account is inactive, nonpostable or belongs to another company')
        # The bill subledger cannot be invented by an opening GL entry. Text-path
        # supplier balances use their reviewed individual creditor accounts.
        if account['kind']=='payable':raise ValueError('Opening AP control needs a supported bill subledger; use reviewed supplier accounts on the text path')
        plan.append({'account_id':aid,'account':account['name'],'side':'debit' if amount>0 else 'credit','amount_paise':abs(amount)})
    if sum(v['signed_paise']for v in balances)!=0:raise ValueError('Opening debits and credits do not balance')
    return plan


def validate(db: Session, typ: str, d: dict, ticket_id: int | None = None, actor=None) -> None:
    if not isinstance(d, dict) or set(d) - ALLOWED_FIELDS[typ]:
        raise ValueError('Unrecognised details for this entry')
    if typ == 'finance_opening_balances':
        opening_plan(db,d)
        return
    if typ == 'finance_install_chart':
        if set(d) != {'entity_id', 'standard'}:
            raise ValueError('Name the company and the standard to install')
        _entity(db, d['entity_id'])
        std, _ = standard_file(d['standard'])
        have = installed(db, d['entity_id'])
        if have is not None and have.standard_key != std['key']:
            raise ValueError(f'The company already follows "{have.standard_key}"; changing standard is not supported')
        if have is not None and have.version >= std['version']:
            raise ValueError('This standard is already installed')
        rows = chart_rows(db, d['entity_id'])
        by_code = {r['code']: r for r in rows.values()}
        for a in std['accounts']:
            r = by_code.get(a['code'])
            if r is not None and r['is_group'] != bool(a.get('group')):
                raise ValueError(f'Account code {a["code"]} is already used for something else in this company')
        return
    if typ == 'finance_open_account':
        if not {'entity_id', 'name', 'parent_id'} <= set(d):
            raise ValueError('A new account needs a company, a name and the group it goes in')
        _entity(db, d['entity_id'])
        rows = chart_rows(db, d['entity_id'])
        name = d.get('name')
        if not isinstance(name, str) or not 2 <= len(name.strip()) <= 180:
            raise ValueError('Give the account a name (2 to 180 characters)')
        if _same_name(rows, name):
            raise ValueError(f'An account named "{name.strip()}" already exists; use it instead')
        parent = rows.get(d['parent_id']) if type(d.get('parent_id')) is int else None
        if parent is None or not parent['is_group']:
            raise ValueError('Choose the group the new account goes in')
        if not parent['child_kind'] or parent['child_kind'] in ('bank', 'payable', 'group'):
            raise ValueError(f'New accounts cannot be opened directly inside "{parent["name"]}"')
        aliases = d.get('aliases', [])
        if not isinstance(aliases, list) or len(aliases) > 30 or any(not isinstance(x, str) or not 1 <= len(x) <= 60 for x in aliases):
            raise ValueError('Other names must be up to 30 short words')
        if d.get('why') is not None and (not isinstance(d['why'], str) or len(d['why']) > 400):
            raise ValueError('The reason must be under 400 characters')
        return
    if typ == 'finance_text_entry':
        if not {'entity_id', 'recipe', 'slots', 'accounts', 'idempotency_key'} <= set(d):
            raise ValueError('An entry needs a company, what kind of entry it is, its details and the accounts used')
        _entity(db, d['entity_id'])
        key = d.get('idempotency_key')
        if not isinstance(key, str) or not 8 <= len(key) <= 120:
            raise ValueError('An entry needs a unique reference')
        if db.scalar(select(FinanceTextEntry.id).where(FinanceTextEntry.idempotency_key == key)):
            raise ValueError('This entry has already been posted')
        if d.get('project_id') is not None:
            project = db.get(Project, d['project_id']) if type(d['project_id']) is int else None
            if project is None or project.deleted_at:
                raise ValueError('Project not found')
            if actor is not None:
                from .access import require_project_access
                require_project_access(db, actor, project.id)
        worked = plan_entry(db, d, ticket_id)
        plan, slots = worked['plan'], worked['slots']
        problems = [describe_missing(m, slots, worked['recipe'].definition) for m in plan['missing']]
        refused = [s for s in ('item', 'party', 'bank') if s in (d.get('accounts') or {}) and not _account_used(plan, s)]
        unchosen = sorted({l['slot'] for l in plan['lines'] if l.get('slot') and l['slot'] not in (d.get('accounts') or {})})
        if unchosen:
            problems.append('The account for ' + ' and '.join(unchosen) + ' has not been confirmed on the draft')
        if refused:
            problems.append('An account chosen for this entry is not allowed for it any more; choose again')
        if plan['suggestions']:
            problems.append('An account still has to be chosen or suggested')
        if problems:
            raise ValueError('; '.join(dict.fromkeys(problems)))
        lines = plan['lines']
        if len(lines) < 2 or sum(l['amount'] for l in lines if l['side'] == 'debit') != sum(l['amount'] for l in lines if l['side'] == 'credit'):
            raise ValueError('The entry does not balance; nothing can be posted')
        day = slots.get('date') or local_today().isoformat()
        if day > local_today().isoformat():
            raise ValueError('An entry cannot be dated in the future')
        if _month_closed(db, d['entity_id'], day) or _month_closed(db, d['entity_id'], local_today().isoformat()):
            raise ValueError('That accounting month is closed')
        return
    if typ == 'finance_reverse_text_entry':
        if set(d) != {'entry_id', 'reason'}:
            raise ValueError('Name the entry and say why it is being reversed')
        entry = db.get(FinanceTextEntry, d['entry_id']) if type(d.get('entry_id')) is int else None
        if entry is None or entry.journal_id is None:
            raise ValueError('Only a posted entry can be reversed')
        if db.scalar(select(FinanceReversal.id).where(FinanceReversal.original_journal_id == entry.journal_id)):
            raise ValueError('This entry has already been reversed')
        if not isinstance(d['reason'], str) or not 3 <= len(d['reason'].strip()) <= 400:
            raise ValueError('Give a reason (3 to 400 characters)')
        if actor is not None and entry.project_id is not None:
            from .access import require_project_access
            require_project_access(db, actor, entry.project_id)
        return
    raise ValueError('Unsupported entry')


def _account_used(plan: dict, slot: str) -> bool:
    return any(l.get('slot') == slot for l in plan['lines'])


def describe_missing(name: str, slots: dict, rec: dict) -> str:
    if name.startswith('choose:'):
        what = name[7:]
        return 'Choose which bank' if what == 'bank' else f'More than one account fits "{slots.get(what) or slots.get(_party_slot(rec)) or what}"; choose one'
    if name.startswith('account:'):
        return 'No bank is registered for the company' if name == 'account:bank' else f'The standard account {name[8:]} is missing from the chart'
    return {'amount': 'Still needed: the amount', 'item': 'Still needed: what it was for', 'party': 'Still needed: who it was with',
            'gst_rate': 'Still needed: the GST rate', 'gst_amount': 'Still needed: the GST amount'}.get(name, f'Still needed: {name}')


def _party_slot(rec: dict) -> str:
    return (rec.get('party_word') or 'from') + '_party'


# ------------------------------------------------------------------ saving (only inside an approved ticket commit)

def _code_for(db: Session, entity_id: int, name: str) -> str:
    base = re.sub(r'[^A-Z0-9]+', '_', name.upper()).strip('_')[:24] or 'ACCOUNT'
    code, n = base, 1
    while db.scalar(select(GLAccount.id).where(GLAccount.entity_id == entity_id, GLAccount.code == code)):
        n += 1
        code = f'{base[:24]}_{n}'
    return code


def _resolve(db: Session, value):
    if isinstance(value, str) and value.startswith('@item:'):
        made = db.info.get('finance_created') or {}
        item_id = int(value.split(':', 1)[1])
        if item_id not in made:
            raise ValueError('This entry uses a suggested account that was not approved. Approve it, or choose an existing account.')
        return made[item_id]
    return value


def apply(db: Session, item, actor: str) -> dict:
    typ, d = item.item_type, item.after_data or {}
    from .accounting_kernel import _post_lines
    entity_id = d.get('entity_id')
    if typ == 'finance_reverse_text_entry':
        entry = db.scalar(select(FinanceTextEntry).where(FinanceTextEntry.id == d['entry_id']).with_for_update())
        entity_id = entry.entity_id if entry else None
    if type(entity_id) is int:
        db.scalar(select(AccountingEntity).where(AccountingEntity.id == entity_id).with_for_update())
    validate(db, typ, d, item.ticket_id)
    if typ=='finance_text_entry':
        if (item.field_evidence or {}).get('finance_source'):
            from .finance_intake import validate_source
            validate_source(db,item)
        from .finance_review import require_current_confirmation
        require_current_confirmation(db,item)
    if typ == 'finance_opening_balances':
        plan=opening_plan(db,d)
        journal=_post_lines(db,entity_id=entity_id,event_kind='OPENING_BALANCES',event_key=f'opening:{entity_id}',source_id=entity_id,ticket_id=item.ticket_id,policy_version=1,lines=[(x['account_id'],x['side'],x['amount_paise'],None) for x in plan])
        add_audit(db,'finance_opening_balances','gl_journal',journal.id,f'Ticket #{item.ticket_id}: opening trial balance as of {d["as_of"]}',actor=actor)
        return {'type':'opening_balances','id':journal.id,'item_id':item.id,'journal_id':journal.id}
    if typ == 'finance_install_chart':
        result = install(db, d['entity_id'], d['standard'], item.ticket_id, actor)
        return {'type': 'chart_of_accounts', 'id': d['entity_id'], 'item_id': item.id, 'journal_id': None, **result}
    if typ == 'finance_open_account':
        rows = chart_rows(db, d['entity_id'])
        parent = rows[d['parent_id']]
        name = re.sub(r'\s+', ' ', d['name']).strip()
        account = GLAccount(entity_id=d['entity_id'], code=_code_for(db, d['entity_id'], name), name=name,
                            kind=parent['child_kind'], active=True, posting_allowed=True)
        db.add(account)
        db.flush()
        party = db.scalar(select(Party).where(Party.deleted_at.is_(None), func.lower(Party.name) == name.casefold(),
                                              Party.kind == ('vendor' if parent['child_kind'] == 'creditor' else 'client'))) \
            if parent['child_kind'] in ('creditor', 'debtor') else None
        db.add(GLAccountProfile(account_id=account.id, parent_id=parent['id'], is_group=False, nature=parent['nature'],
                                child_kind='', aliases=list(d.get('aliases') or []), party_id=party.id if party else None,
                                ticket_id=item.ticket_id))
        db.flush()
        db.info.setdefault('finance_created', {})[item.id] = account.id
        add_audit(db, 'finance_open_account', 'gl_account', account.id,
                  f'Ticket #{item.ticket_id}: account "{name}" ({account.code}) opened under "{parent["name"]}"', actor=actor)
        return {'type': 'gl_account', 'id': account.id, 'item_id': item.id, 'journal_id': None}
    if typ == 'finance_text_entry':
        fixed = {k: _resolve(db, v) for k, v in (d.get('accounts') or {}).items()}
        worked = plan_entry(db, {**d, 'accounts': fixed}, item.ticket_id)
        plan, slots, rec = worked['plan'], worked['slots'], worked['recipe']
        if plan['missing'] or plan['suggestions']:
            raise ValueError('The entry is not complete; nothing was posted')
        total = sum(l['amount'] for l in plan['lines'] if l['side'] == 'debit')
        entry = FinanceTextEntry(entity_id=d['entity_id'], recipe_id=rec.id, slots=slots, accounts=fixed,
                                 narration=plan['narration'][:300] or rec.definition['title'], total_paise=total,
                                 project_id=d.get('project_id'), entry_date=slots.get('date') or local_today().isoformat(),
                                 reference=str(slots.get('reference') or '')[:60], idempotency_key=d['idempotency_key'],
                                 journal_id=None, ticket_id=item.ticket_id)
        db.add(entry)
        db.flush()
        journal = _post_lines(db, entity_id=d['entity_id'], event_kind='TEXT_ENTRY_POSTED', event_key=f'text-entry:{entry.id}',
                              source_id=entry.id, ticket_id=item.ticket_id, policy_version=rec.version,
                              lines=[(l['account'], l['side'], l['amount'], d.get('project_id')) for l in plan['lines']])
        entry.journal_id = journal.id
        db.flush()
        add_audit(db, 'finance_text_entry', 'finance_text_entry', entry.id,
                  f'Ticket #{item.ticket_id}: "{entry.narration[:120]}" posted as journal #{journal.id} through recipe {rec.key} v{rec.version}', actor=actor)
        return {'type': 'finance_text_entry', 'id': entry.id, 'item_id': item.id, 'journal_id': journal.id}
    if typ == 'finance_reverse_text_entry':
        from .accounting_kernel import _reverse_posted
        entry = db.get(FinanceTextEntry, d['entry_id'])
        reversal = _reverse_posted(db, entry.journal_id, d['reason'].strip(), item.ticket_id)
        add_audit(db, 'finance_reverse_text_entry', 'finance_text_entry', entry.id,
                  f'Ticket #{item.ticket_id}: entry reversed by journal #{reversal.id}: {d["reason"][:200]}', actor=actor)
        return {'type': 'reversing_journal', 'id': reversal.id, 'item_id': item.id, 'journal_id': reversal.id}
    raise ValueError('Unsupported entry')


def install(db: Session, entity_id: int, key: str, ticket_id: int, actor: str) -> dict:
    """Adds what the standard has and the company lacks. Never changes an existing
    account; places the setup accounts (bank, payables, expense ...) in their groups."""
    std, digest = standard_file(key)
    rows = chart_rows(db, entity_id)
    by_code = {r['code']: r for r in rows.values()}
    counts = {'groups_added': 0, 'accounts_added': 0, 'accounts_kept': 0, 'placed': 0, 'recipes': 0}
    ids = {}
    for a in std['accounts']:
        have = by_code.get(a['code'])
        if have is not None:
            ids[a['code']] = have['id']
            counts['accounts_kept'] += 1
            continue
        parent_id = ids.get(a.get('parent'))
        account = GLAccount(entity_id=entity_id, code=a['code'], name=a['name'], kind='group' if a.get('group') else a['kind'],
                            active=True, posting_allowed=not a.get('group'))
        db.add(account)
        db.flush()
        ids[a['code']] = account.id
        db.add(GLAccountProfile(account_id=account.id, parent_id=parent_id, is_group=bool(a.get('group')),
                                nature=_nature(std, a['code']), child_kind=a.get('child_kind', '') if a.get('group') else '',
                                aliases=list(a.get('aliases') or []), standard_key=std['key'], ticket_id=ticket_id))
        counts['groups_added' if a.get('group') else 'accounts_added'] += 1
    db.flush()
    placed = {r['id'] for r in rows.values() if r['parent'] is not None or r['is_group']}
    for r in rows.values():
        group = std['existing'].get(r['kind'])
        if group and r['id'] not in placed and r['code'] not in {a['code'] for a in std['accounts']}:
            db.add(GLAccountProfile(account_id=r['id'], parent_id=ids[group], is_group=False, nature=_nature(std, group),
                                    child_kind='', aliases=[], standard_key=std['key'], ticket_id=ticket_id))
            counts['placed'] += 1
    for r in std['recipes']:
        current = recipe(db, entity_id, r['key'])
        if current is not None and current.definition == r:
            continue
        db.add(GLPostingRecipe(entity_id=entity_id, key=r['key'], version=(current.version + 1) if current else 1,
                               definition=r, standard_key=std['key'], ticket_id=ticket_id))
        counts['recipes'] += 1
    db.add(FinanceStandardInstall(entity_id=entity_id, standard_key=std['key'], version=std['version'],
                                  definition_sha256=digest, ticket_id=ticket_id))
    db.flush()
    add_audit(db, 'finance_install_chart', 'accounting_entity', entity_id,
              f"Ticket #{ticket_id}: standard {std['key']} v{std['version']} (sha256 {digest[:12]}): "
              f"{counts['groups_added']} groups and {counts['accounts_added']} accounts added, {counts['accounts_kept']} kept, "
              f"{counts['placed']} setup accounts placed, {counts['recipes']} recipes", actor=actor)
    return counts


def _nature(std: dict, code: str) -> str:
    by = {a['code']: a for a in std['accounts']}
    a = by[code]
    while a.get('parent'):
        a = by[a['parent']]
    return a['nature']


# ------------------------------------------------------------------ reading back

def chart_report(db: Session, entity_id: int) -> dict:
    """Every account in its group with posted totals rolled up, plus income, expenses
    and profit. Derived from posted GL lines only: the ledger is the one source of truth."""
    _entity(db, entity_id)
    rows = chart_rows(db, entity_id)
    own = {}
    for account_id, side, amount in db.execute(
            select(GLLine.account_id, GLLine.side, func.coalesce(func.sum(GLLine.amount_paise), 0))
            .join(GLJournal, GLJournal.id == GLLine.journal_id)
            .where(GLJournal.entity_id == entity_id, GLJournal.status == 'posted')
            .group_by(GLLine.account_id, GLLine.side)).all():
        d, c = own.get(account_id, (0, 0))
        own[account_id] = (d + int(amount), c) if side == 'debit' else (d, c + int(amount))
    rolled = dict(own)
    for account_id, (d, c) in own.items():
        seen, parent = set(), rows.get(account_id, {}).get('parent')
        while parent is not None and parent not in seen:
            seen.add(parent)
            pd, pc = rolled.get(parent, (0, 0))
            rolled[parent] = (pd + d, pc + c)
            parent = rows.get(parent, {}).get('parent')
    out = []
    for r in rows.values():
        d, c = rolled.get(r['id'], (0, 0))
        net = d - c
        out.append({**{k: r[k] for k in ('id', 'code', 'name', 'kind', 'parent', 'is_group', 'nature', 'postable')},
                    'debit_paise': d, 'credit_paise': c, 'balance_paise': abs(net), 'side': 'Dr' if net > 0 else 'Cr' if net < 0 else ''})
    by_nature = {}
    for account_id, (d, c) in own.items():
        n = rows.get(account_id, {}).get('nature', 'asset')
        by_nature[n] = by_nature.get(n, 0) + d - c
    income, expense = -by_nature.get('income', 0), by_nature.get('expense', 0)
    total_d = sum(d for d, _ in own.values())
    total_c = sum(c for _, c in own.values())
    have = installed(db, entity_id)
    return {'entity_id': entity_id, 'currency': 'INR', 'standard': {'key': have.standard_key, 'version': have.version} if have else None,
            'accounts': sorted(out, key=lambda x: (x['code'])), 'total_debit_paise': total_d, 'total_credit_paise': total_c,
            'balanced': total_d == total_c, 'income_paise': income, 'expense_paise': expense, 'profit_paise': income - expense,
            'assets_paise': by_nature.get('asset', 0), 'liabilities_paise': -by_nature.get('liability', 0), 'equity_paise': -by_nature.get('equity', 0),
            'basis': 'Posted GL journals (reversals included, so a reversed entry nets to zero). Not statutory accounts; '
                     'opening balances, depreciation, closing stock and year-end adjustments are not covered.'}


def text_entries(db: Session, entity_id: int, allowed_projects=None, limit: int = 200) -> list[dict]:
    reversed_ids = {x for (x,) in db.execute(select(FinanceReversal.original_journal_id)).all()}
    out = []
    for e in db.scalars(select(FinanceTextEntry).where(FinanceTextEntry.entity_id == entity_id)
                        .order_by(FinanceTextEntry.id.desc()).limit(limit)).all():
        if allowed_projects is not None and e.project_id is not None and e.project_id not in allowed_projects:
            continue
        out.append({'id': e.id, 'date': e.entry_date, 'narration': e.narration, 'total_paise': e.total_paise, 'project_id': e.project_id,
                    'journal_id': e.journal_id, 'ticket_id': e.ticket_id, 'reversed': e.journal_id in reversed_ids,
                    'lines': journal_lines(db, e.journal_id)})
    return out


def journal_lines(db: Session, journal_id) -> list[dict]:
    if journal_id is None:
        return []
    out = []
    for line, account in db.execute(select(GLLine, GLAccount).join(GLAccount, GLAccount.id == GLLine.account_id)
                                    .where(GLLine.journal_id == journal_id).order_by(GLLine.id)).all():
        out.append({'side': 'Dr' if line.side == 'debit' else 'Cr', 'account': account.name, 'account_id': account.id,
                    'amount_paise': line.amount_paise})
    return out


def ideas(db: Session, entity_id: int) -> list[dict]:
    """Ways the chart could be better. Suggestions for a person; nothing changes by itself."""
    rows = chart_rows(db, entity_id)
    accounts = [{'id': r['id'], 'name': r['name'], 'is_group': r['is_group'] or not r['postable'], 'code': r['code']} for r in rows.values()]
    usage = dict(db.execute(select(GLLine.account_id, func.count()).join(GLJournal, GLJournal.id == GLLine.journal_id)
                            .where(GLJournal.entity_id == entity_id).group_by(GLLine.account_id)).all())
    edited = {}
    for item in db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.item_type == 'finance_text_entry')).all():
        if (item.after_data or {}).get('entity_id') != entity_id:
            continue
        for name in (item.after_data or {}).get('slots') or {}:
            fixed, total = edited.get(name, (0, 0))
            marker = ((item.field_evidence or {}).get('slots.' + name) or {}).get('marker')
            edited[name] = (fixed + (marker in ('edited', 'answered')), total + 1)
    return T.improvement_ideas(accounts, usage, edited)

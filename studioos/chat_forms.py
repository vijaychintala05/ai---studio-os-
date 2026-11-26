"""v66: the create forms inside the chat.

A draft made in the chat shows the SAME fields as the form on its own page (form_fields.py; for an expense, the Books
expense page): required ones first, each with the right control (a calendar for a date, a drop-down for a fixed choice
or an account, a people list for an owner). What the person typed fills what it can; the rest are blanks to fill in the card.
Afterwards they can keep chatting ("start date 5 December, manager Ravi") and the draft changes. Nothing is saved until
the draft is approved, exactly as before: this module only describes fields and edits a draft.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from sqlalchemy import select

from . import form_fields as ff

# not shown on a card: plumbing of the entry, not something a person fills in
HIDDEN = {'entity_id', 'bank_id', 'request_key', 'idempotency_key', 'no_vendor', 'no_vendor_name', 'personal_payment', 'site_expense', 'receipt_id',
          'receipt_intake_id', 'suggested_vendor_name', 'category_id', 'lines', 'tax_mode', 'place_of_supply', 'custom'}

WORDS = {
    # ticket key -> the words a person uses for it (the field's own label is always added)
    'name': ['project name', 'name'], 'client': ['client name', 'client', 'customer'], 'manager': ['project manager', 'manager'],
    'start_date': ['start date', 'starts', 'starting', 'start'], 'end_date': ['target end date', 'end date', 'finish date'],
    'stage': ['status', 'stage'], 'project_code': ['project code', 'code'], 'project_type': ['project type', 'type'],
    'location': ['site address', 'location', 'address'], 'client_phone': ['client phone', 'client mobile', 'phone', 'mobile'],
    'description': ['description', 'details'], 'amount_paise': ['budget', 'amount', 'cost', 'price', 'total'],
    'assignee': ['assigned to', 'assignee', 'assign to', 'owner'], 'due_date': ['due date', 'due', 'deadline'],
    'priority': ['priority'], 'title': ['task title', 'title', 'task'], 'project': ['project'],
    'date': ['date', 'on'], 'category': ['expense account', 'account', 'category'], 'payment_mode': ['paid through', 'paid by', 'payment mode'],
    'vendor': ['vendor', 'supplier', 'paid to'], 'reference_number': ['invoice number', 'invoice no', 'invoice #', 'invoice', 'reference'],
    'notes': ['notes', 'note', 'remarks'],
    'expense_account_id': ['expense account', 'account', 'category'], 'paid_through_id': ['paid through', 'paid from', 'paid by', 'pay from'],
    'vendor_id': ['vendor', 'supplier', 'paid to'], 'customer_id': ['customer name', 'customer', 'client', 'bill to'],
    'billable': ['billable'], 'markup_bps': ['mark-up', 'markup'], 'project_id': ['project'], 'note': ['notes', 'note', 'remarks'],
    # purchase orders and payments (v67)
    'supplier_id': ['vendor', 'supplier', 'paid to'], 'po_number': ['purchase order number', 'purchase order #', 'po number', 'po no', 'po #'],
    'bill_id': ['bill', 'invoice'], 'payment_date': ['payment date', 'paid on', 'date'],
    'payment_reference': ['payment reference', 'reference', 'utr', 'cheque number', 'cheque no'], 'cost_id': ['pay against', 'against', 'cost'],
}
_CHAT_TYPES = {'text': 'text', 'tel': 'text', 'email': 'text', 'textarea': 'text', 'date': 'date', 'select': 'select', 'person': 'person',
               'project': 'project', 'amount': 'money', 'checkbox': 'boolean', 'number': 'text'}
_MONTHS = {m: i for i, m in enumerate(('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'), 1)}
_DAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')


# ------------------------------------------------------------------ dates

def parse_date(text, today=None):
    t = ' '.join(str(text or '').lower().replace(',', ' ').split()).rstrip('.')
    today = today or date.today()
    if t in ('today', 'now'):
        return today.isoformat()
    if t == 'tomorrow':
        return (today + timedelta(days=1)).isoformat()
    if t == 'yesterday':
        return (today - timedelta(days=1)).isoformat()
    try:
        m = re.fullmatch(r'(\d{4})-(\d{1,2})-(\d{1,2})', t)
        if m:
            return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
        m = re.fullmatch(r'(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})', t)             # day first, as in India
        if m:
            year = int(m[3]) + (2000 if int(m[3]) < 100 else 0)
            return date(year, int(m[2]), int(m[1])).isoformat()
        for pattern, order in ((r'(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([a-z]{3,9})(?:\s+(\d{4}))?', 'dm'),
                               (r'([a-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(\d{4}))?', 'md')):
            m = re.fullmatch(pattern, t)
            if m:
                day, month = (m[1], m[2]) if order == 'dm' else (m[2], m[1])
                month = _MONTHS.get(month[:3])
                if month:
                    year = int(m[3]) if m[3] else today.year
                    found = date(year, month, int(day))
                    if not m[3] and (today - found).days > 183:                  # "5 January" said in December means next January
                        found = date(year + 1, month, int(day))
                    return found.isoformat()
        m = re.fullmatch(r'(?:next\s+|on\s+)?([a-z]+)', t)
        if m and m[1] in _DAYS:
            ahead = (_DAYS.index(m[1]) - today.weekday()) % 7 or 7
            return (today + timedelta(days=ahead)).isoformat()
    except ValueError:
        return None
    return None


# ------------------------------------------------------------------ what each draft's form looks like

def _people(db):
    from .db import User
    rows = db.scalars(select(User).where(User.active.is_(True), User.role != 'viewer').order_by(User.display_name, User.username)).all()
    return [{'value': u.display_name or u.username, 'label': f"{u.display_name or u.username} · {str(u.role).replace('_', ' ')}"} for u in rows]


def _entity_for(db, after):
    from .db import AccountingEntity, GLAccount
    ident = after.get('paid_through_id')
    account = db.get(GLAccount, ident) if type(ident) is int else None
    if account is not None:
        return account.entity_id
    return db.scalar(select(AccountingEntity.id).order_by(AccountingEntity.id).limit(1))


def _books_expense_specs(db, user, after, project_rows):
    from .db import Party
    from .chart_of_accounts import chart_rows
    from .paid_through import list_accounts
    entity = _entity_for(db, after)
    accounts, paying = [], []
    if entity is not None:
        accounts = sorted(({'value': a['id'], 'label': (f"{a['code']} · " if a['code'] else '') + a['name']} for a in chart_rows(db, entity).values()
                           if a['kind'] == 'expense' and a['postable']), key=lambda a: a['label'].casefold())
        paying = [{'value': a['id'], 'label': a['name']} for a in list_accounts(db, entity, user, for_expense=True)]
    people = lambda kind: [{'value': p.id, 'label': p.name} for p in db.scalars(
        select(Party).where(Party.kind == kind, Party.deleted_at.is_(None)).order_by(Party.name))]
    projects = [{'value': p['id'], 'label': p['name']} for p in project_rows]
    return [
        {'key': 'date', 'label': 'Date', 'type': 'date', 'required': True},
        {'key': 'expense_account_id', 'label': 'Expense Account', 'type': 'select', 'required': True, 'choices': accounts},
        {'key': 'amount_paise', 'label': 'Amount', 'type': 'money', 'required': True},
        {'key': 'paid_through_id', 'label': 'Paid Through', 'type': 'select', 'required': True, 'choices': paying},
        {'key': 'vendor_id', 'label': 'Vendor', 'type': 'select', 'required': after.get('no_vendor') is not True, 'choices': people('vendor')},
        {'key': 'reference_number', 'label': 'Invoice#', 'type': 'text', 'required': False},
        {'key': 'project_id', 'label': 'Project', 'type': 'select', 'required': False, 'choices': projects},
        {'key': 'customer_id', 'label': 'Customer Name', 'type': 'select', 'required': False, 'choices': people('client')},
        {'key': 'billable', 'label': 'Billable', 'type': 'boolean', 'required': False},
        {'key': 'markup_bps', 'label': 'Markup (%)', 'type': 'text', 'required': False},
        {'key': 'note', 'label': 'Notes', 'type': 'text', 'required': False},
    ]


def _vendors(db):
    from .db import Party
    return [{'value': p.id, 'label': p.name} for p in db.scalars(select(Party).where(Party.kind == 'vendor', Party.deleted_at.is_(None)).order_by(Party.name))]


def next_po_number(db, entity_id):
    """PO-0001, PO-0002...: the next free number for the company (Zoho Books numbers purchase orders the same way)."""
    from .db import FinancePurchaseOrder
    used = set(db.scalars(select(FinancePurchaseOrder.po_number).where(FinancePurchaseOrder.entity_id == entity_id)))
    n = len(used) + 1
    while f'PO-{n:04d}' in used:
        n += 1
    return f'PO-{n:04d}'


def _po_specs(db, user, after, project_rows):
    return [
        {'key': 'supplier_id', 'label': 'Vendor', 'type': 'select', 'required': True, 'choices': _vendors(db)},
        {'key': 'project_id', 'label': 'Project', 'type': 'select', 'required': True, 'choices': [{'value': p['id'], 'label': p['name']} for p in project_rows]},
        {'key': 'po_number', 'label': 'Purchase Order#', 'type': 'text', 'required': True},
        {'key': 'amount_paise', 'label': 'Order amount', 'type': 'money', 'required': True},
    ]


def open_bills(db, entity_id, direct):
    """Unpaid supplier bills of one kind (direct multi-line bills, or bills against a purchase order), newest first."""
    from .books_routes import bill_rows
    from .chart_of_accounts import local_today
    from .db import Party
    names = {p.id: p.name for p in db.scalars(select(Party).where(Party.kind == 'vendor'))}
    rows = [r for r in bill_rows(db, local_today(), entity_id=entity_id) if r['owed_paise'] > 0 and bool(r.get('direct_bill')) == bool(direct)]
    rows.sort(key=lambda r: r['id'], reverse=True)
    return [{**r, 'supplier': names.get(r['supplier_id'], '')} for r in rows[:60]]


def _payment_specs(db, user, item_type, after):
    from .db import GLAccount
    from .paid_through import list_accounts
    bill = None
    ident = after.get('bill_id')
    entity = None
    if type(ident) is int:
        from .db import FinanceDirectBill, FinanceSupplierBill
        bill = db.get(FinanceDirectBill if item_type == 'finance_direct_bill_payment' else FinanceSupplierBill, ident)
        entity = bill.entity_id if bill else None
    if entity is None:
        entity = _entity_for(db, after)
    bills = open_bills(db, entity, item_type == 'finance_direct_bill_payment') if entity else []
    if bill is not None and not any(b['id'] == bill.id for b in bills):
        bills.append({'id': bill.id, 'supplier': '', 'invoice_number': bill.invoice_number, 'owed_paise': 0, 'due_date': bill.due_date})
    choices = [{'value': b['id'], 'label': f"{b['supplier']} · {b['invoice_number']} · owes ₹{b['owed_paise'] / 100:,.2f}" + (f" · due {b['due_date']}" if b.get('due_date') else '')} for b in bills]
    paying = [{'value': a['id'], 'label': a['name']} for a in (list_accounts(db, entity, user) if entity else []) if a.get('kind') in ('bank', 'cash')]
    return [
        {'key': 'bill_id', 'label': 'Bill', 'type': 'select', 'required': True, 'choices': choices},
        {'key': 'amount_paise', 'label': 'Amount', 'type': 'money', 'required': True},
        {'key': 'payment_date', 'label': 'Payment Date', 'type': 'date', 'required': True},
        {'key': 'paid_through_id', 'label': 'Paid Through', 'type': 'select', 'required': True, 'choices': paying},
        {'key': 'payment_reference', 'label': 'Reference# (UTR or cheque no.)', 'type': 'text', 'required': True},
    ]


def open_costs(db):
    """Approved project costs with money still to pay (the older project tracker's payments)."""
    from .db import Cost
    from .main import cost_net, payment_sums
    paid = payment_sums(db, include_pending=True)
    out = []
    for c in db.scalars(select(Cost).where(Cost.status == 'approved', Cost.deleted_at.is_(None)).order_by(Cost.id.desc()).limit(80)):
        left = cost_net(db, c) - paid.get(c.id, 0)
        if left > 0:
            out.append({'value': c.id, 'label': f"#{c.id} {c.title} · ₹{left / 100:,.2f} left to pay"})
    return out


def specs_for(db, user, item_type, after, project_rows=()):
    """The fields of the form for this kind of draft, as the card shows them. [] when the draft has no form."""
    after = after or {}
    if item_type == 'finance_expense':
        return _books_expense_specs(db, user, after, list(project_rows))
    if item_type == 'finance_po':
        return _po_specs(db, user, after, list(project_rows))
    if item_type in ('finance_payment', 'finance_direct_bill_payment'):
        return _payment_specs(db, user, item_type, after)
    form = ff.form_for_ticket(item_type, after)
    if not form:
        return []
    rename = ff.TICKET_KEYS.get(form, {})
    out = []
    for f in ff.fields(db, form):
        if f['type'] == 'cost':                               # a payment names the cost it pays
            out.append({'key': 'cost_id', 'label': 'Pay against', 'type': 'select', 'required': True, 'choices': open_costs(db)})
            continue
        if f['type'] in ('files', 'password'):
            continue
        key = ('custom.' + f['name']) if f.get('custom') else rename.get(f['name'], f['name'])
        spec = {'key': key, 'label': f['label'].replace(' (₹)', ''), 'type': _CHAT_TYPES.get(f['type'], 'text'), 'required': bool(f['required'])}   # the rupee sign is in the value
        if f['type'] == 'select':
            spec['choices'] = [{'value': (o[0] if isinstance(o, (list, tuple)) else o), 'label': (o[1] if isinstance(o, (list, tuple)) else o)} for o in f.get('options', [])]
        elif f['type'] == 'person':
            spec['choices'] = _people(db)
        elif f['type'] == 'project' or f['name'] == 'project_id':
            spec['type'] = 'select'
            spec['choices'] = [{'value': p['name'], 'label': p['name']} for p in project_rows]
        out.append(spec)
    return out


def _label_of(spec, value):
    for c in spec.get('choices') or []:
        if str(c['value']) == str(value):
            return c['label']
    return None


def merge(db, user, item, fields, project_rows=()):
    """The card's field list: every field of the form (required first), with what the draft already says filled in."""
    after = item.get('after') or {}
    specs = specs_for(db, user, item.get('item_type'), after, project_rows)
    if not specs:
        return [f for f in fields if f['key'] not in HIDDEN]
    existing = {f['key']: f for f in fields}
    out = []
    for spec in sorted(specs, key=lambda s: not s['required']):
        key = spec['key']
        value = _read(after, key)
        base = existing.get(key)
        field = dict(base) if base else {'key': key, 'label': spec['label'], 'display': '—', 'raw': None, 'marker': 'missing', 'source': None}
        field.update({'label': spec['label'], 'type': spec['type'], 'required': spec['required']})
        if spec.get('choices') is not None:
            field['choices'] = spec['choices']
        if value in (None, '', []):
            field.update({'raw': None, 'display': '—', 'marker': 'missing'})
        else:
            field['raw'] = value
            shown = _label_of(spec, value)
            if shown:
                field['display'] = shown
            elif key == 'markup_bps' and isinstance(value, int):
                field['display'] = f'{value / 100:g}%'
        out.append(field)
    seen = {s['key'] for s in specs}
    out.extend(f for f in fields if f['key'] not in seen and f['key'] not in HIDDEN)
    return out


def _read(after, key):
    if key.startswith('custom.'):
        return (after.get('custom') or {}).get(key[7:])
    return after.get(key)


# ------------------------------------------------------------------ what is still missing

def missing_labels(db, item_type, data):
    """Labels of the required fields a draft still lacks (for the 'MISSING required' line and the card)."""
    data = data or {}
    if item_type == 'finance_expense':
        out = []
        for key, label in (('date', 'Date'), ('expense_account_id', 'Expense Account'), ('amount_paise', 'Amount')):
            if data.get(key) in (None, '', 0):
                out.append(label)
        if data.get('personal_payment') is not True and data.get('paid_through_id') in (None, ''):
            out.append('Paid Through')
        if data.get('no_vendor') is not True and data.get('vendor_id') in (None, ''):
            out.append('Vendor')
        return out
    if item_type == 'finance_po':
        pairs = (('supplier_id', 'Vendor'), ('project_id', 'Project'), ('po_number', 'Purchase Order#'), ('amount_paise', 'Order amount'))
        return [label for key, label in pairs if data.get(key) in (None, '', 0)]
    if item_type in ('finance_payment', 'finance_direct_bill_payment'):
        pairs = (('bill_id', 'Bill'), ('amount_paise', 'Amount'), ('payment_date', 'Payment Date'), ('paid_through_id', 'Paid Through'),
                 ('payment_reference', 'Reference#'))
        return [label for key, label in pairs if data.get(key) in (None, '', 0)]
    form = ff.form_for_ticket(item_type, data)
    return ff.missing(db, form, data, ticket_keys=True) if form else []


def missing_flag(db, item_type, data):
    if not ff.enforced():
        return []
    gaps = missing_labels(db, item_type, data)
    return ['MISSING required: ' + ', '.join(gaps) + ' (fill these in before approving)'] if gaps else []


def apply_defaults(kind, details):
    """What a form fills in by itself (Zoho: the date is today, a project starts as Planning, a task as Medium priority)."""
    if kind == 'create_project':
        details.setdefault('stage', 'Planning')
    elif kind == 'create_task':
        details.setdefault('priority', 'Medium')
    elif kind in ('record_cost', 'record_payment'):
        details.setdefault('date', date.today().isoformat())
    return details


# ------------------------------------------------------------------ editing a draft by chatting

_NEW_THING = re.compile(r'^\s*(?:please\s+)?(?:create|new|record|log|raise|book|start\s+(?:a\s+|an\s+|new\s+)?(?:project|task|expense|payment)|add\s+(?:a\s+|an\s+)?(?:new\s+)?(?:project|task|expense|payment|client|vendor|person))\b', re.I)
_LEAD = re.compile(r'^\s*(?:please\s+)?(?:also\s+|and\s+)?(?:set\s+|change\s+|update\s+|make\s+|put\s+|edit\s+|correct\s+|use\s+|add\s+|with\s+)?(?:the\s+|its\s+|his\s+|her\s+)?(?:not\s+|non[ -]|is\s+not\s+)?', re.I)
_SEP = re.compile(r'^\s*(?:is|to|as|=|:|should be|will be|-)\s*', re.I)


def _aliases(spec):
    words = [spec['label'].lower().rstrip('#').strip(), *WORDS.get(spec['key'].replace('custom.', ''), [])]
    if spec['key'].startswith('custom.'):
        words = [spec['label'].lower()]
    return [w for w in dict.fromkeys(words) if len(w) >= 2]


def _choice(spec, text):
    """The one choice a few words point to, or a message saying which are available."""
    t = text.strip().strip('.').casefold()
    choices = spec.get('choices') or []
    scored = []
    for c in choices:
        label, value = str(c['label']).casefold(), str(c['value']).casefold()
        names = {label, value, label.split(' · ', 1)[-1]}
        if t in names:
            scored.append((0, c))
        elif any(n.startswith(t) for n in names):
            scored.append((1, c))
        elif any(t in n for n in names):
            scored.append((2, c))
    if not scored:
        return None, 'Choose ' + spec['label'] + ' from: ' + ', '.join(str(c['label']) for c in choices[:8]) + ('…' if len(choices) > 8 else '') + '.'
    best = min(s for s, _ in scored)
    top = [c for s, c in scored if s == best]
    if len(top) > 1:
        return None, f"More than one {spec['label']} fits “{text.strip()}”: " + ', '.join(str(c['label']) for c in top[:6]) + '. Say which one.'
    return top[0]['value'], None


def _value(spec, text, today=None):
    kind = spec['type']
    text = text.strip().strip(',;').strip()
    if spec['key'] == 'markup_bps':
        m = re.fullmatch(r'(\d+(?:\.\d+)?)\s*%?', text)
        return (int(round(float(m[1]) * 100)), None) if m and float(m[1]) <= 100 else (None, 'Say the mark-up as a percentage from 0 to 100.')
    if kind == 'date':
        got = parse_date(text, today)
        return (got, None) if got else (None, f"I couldn’t read “{text}” as a date. Say it like 5 December 2026 or 2026-12-05.")
    if kind == 'money':
        from .providers import detect_money, parse_money
        paise = detect_money(text) or parse_money(text)
        return (paise, None) if paise else (None, 'Say the amount in rupees, like 12,500 or 2 lakh.')
    if kind == 'boolean':
        low = text.casefold()
        if low in ('yes', 'true', 'y', 'billable', 'on'):
            return True, None
        if low in ('no', 'false', 'n', 'not billable', 'non-billable', 'off'):
            return False, None
        return None, 'Say yes or no.'
    if kind in ('select', 'person', 'project'):
        return _choice(spec, text)
    return (text[:400], None) if text else (None, None)


def patch_from_text(db, user, item, message, project_rows=(), today=None):
    """Change a draft from a sentence such as "start date 5 December, manager Ravi".
    Returns None when the sentence is not an edit of this draft, else {'changes': {key: (old, new)}, 'after': dict, 'errors': [str]}."""
    if _NEW_THING.match(message):
        return None
    after = dict(item.after_data or {})
    specs = specs_for(db, user, item.item_type, after, project_rows)
    if not specs:
        return None
    pairs = sorted(((a, s) for s in specs for a in _aliases(s)), key=lambda p: -len(p[0]))
    pattern = re.compile(r'(?<![\w])(' + '|'.join(re.escape(a) for a, _ in pairs) + r')(?![\w])', re.I)
    hits = list(pattern.finditer(message))
    if not hits:
        return None
    lead = _LEAD.match(message).end()
    first_ok = message[lead:hits[0].start()].strip() == ''
    explicit = any(_SEP.match(message[h.end():]) for h in hits)
    if not (first_ok or explicit):
        return None
    by_alias = {a.casefold(): s for a, s in pairs}
    changes, errors, labels = {}, [], {}
    for i, h in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(message)
        chunk = _SEP.sub('', message[h.end():end], count=1).strip()
        chunk = re.sub(r'\s+(?:and|,|;)\s*$', '', chunk).strip(' ,;.')
        spec = by_alias[h.group(1).casefold()]
        if not chunk and spec['type'] == 'boolean':
            before = message[:h.start()]
            chunk = 'no' if re.search(r"(?:" + chr(92) + "bnot|" + chr(92) + "bnon|n't)[" + chr(92) + "s-]*$", before, re.I) else 'yes'   # "billable" is yes, "not billable" is no
        if not chunk:
            continue
        value, error = _value(spec, chunk, today)
        if error:
            errors.append(error)
            continue
        if value is None:
            continue
        key = spec['key']
        old = _read(after, key)
        if key.startswith('custom.'):
            after['custom'] = {**(after.get('custom') or {}), key[7:]: value}
        else:
            after[key] = value
        changes[key] = (old, value)
        labels[key] = spec['label']
    if not changes and not errors:
        return None
    return {'changes': changes, 'after': after, 'errors': errors, 'labels': labels}

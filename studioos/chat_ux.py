"""Conversational layer for the chat (v0.8.0). Standard library only.

Turns ticket drafts into short, natural replies, formats values the way people
read them (rupees, not paise), and turns the AI's follow-up questions into
tap-to-answer choices. It never decides what is saved; it only presents drafts.
"""
from __future__ import annotations
import re

ITEM_TITLES = {
    'finance_petty_cash_topup': 'Top up petty cash',
    'finance_reverse_petty_cash_topup': 'Reverse a petty cash top-up',
    'finance_migrate_expenses': 'Move reviewed historical expenses into Books',
    'finance_reverse_expense_migration': 'Reverse a historical expense migration batch',
    'finance_project_company': 'Set the company for site expenses',
    'create_project': 'New project', 'update_project': 'Project change',
    'create_client': 'New client', 'update_client': 'Client change',
    'create_vendor': 'New vendor', 'update_vendor': 'Vendor change',
    'create_task': 'Task', 'update_task': 'Task update',
    'record_cost': 'Expense', 'update_cost': 'Expense correction',
    'record_payment': 'Payment', 'site_update': 'Site note',
    'generic_record': 'Note', 'suggest_schema': 'Structure suggestion',
    'propose_data_type': 'New kind of information',
    'finance_install_chart': 'Chart of accounts', 'finance_open_account': 'New account',
    'finance_text_entry': 'Entry', 'finance_reverse_text_entry': 'Entry reversal',
    'finance_expense': 'Expense', 'finance_reverse_expense': 'Expense reversal',
    'finance_reimburse_staff': 'Staff reimbursement', 'finance_reverse_staff_payment': 'Staff reimbursement reversal',
    # v0.10.0
    'metadata_type': 'New kind of record', 'metadata_type_extend': 'More fields for a kind of record',
    'metadata_relation': 'New kind of link', 'metadata_record': 'Record', 'metadata_record_update': 'Record change',
    'metadata_record_delete': 'Record removal', 'metadata_edge': 'Link', 'metadata_edge_remove': 'Link removal',
    'metadata_view': 'Saved view', 'metadata_workflow': 'Rule', 'metadata_calculation': 'Formula',
    'metadata_document': 'Document template', 'metadata_report': 'Report',
    'metadata_pack_install': 'Business pack', 'metadata_type_adopt': 'Bring a type into the engine',
    # v0.11.0
    'metadata_type_options': 'Who may read or approve a kind of record', 'metadata_alias': 'Another name for something',
    # v0.12.0
    'metadata_dashboard': 'Dashboard', 'metadata_layout': 'Form layout',
    # v0.13.0
    'metadata_type_change': 'Change a kind of record', 'metadata_type_change_undo': 'Undo a change to a kind of record',
    'metadata_pack_upgrade': 'Business pack upgrade',
    # v0.14.0
    'metadata_import': 'Import rows from a file', 'metadata_summary': 'Scheduled summary', 'intake_file_accept': 'Keep a received file',
}

FIELD_LABELS = {
    'project': 'Project', 'name': 'Name', 'client': 'Client', 'client_phone': 'Client phone',
    'location': 'Location', 'start_date': 'Start date', 'amount_paise': 'Amount', 'stage': 'Stage',
    'phone': 'Phone', 'gstin': 'GSTIN', 'trade': 'Trade', 'title': 'What', 'assignee': 'Assigned to',
    'due_date': 'Due', 'progress': 'Progress', 'status': 'Status', 'kind': 'Type', 'vendor': 'Vendor',
    'payment_mode': 'Paid by', 'date': 'Date', 'gst_included': 'GST', 'category': 'Category',
    'cost_id': 'For bill', 'note': 'Note', 'record_type': 'Kind', 'data': 'Details', 'idea': 'Idea',
    'id': 'Record', 'vendor_id': 'Vendor', 'no_vendor': 'No vendor',
    'paid_through_id': 'Paid through', 'expense_account_id': 'Expense account', 'receipt_id': 'Receipt',
    'personal_payment': 'Paid personally', 'claim_id': 'Staff claim', 'payment_date': 'Payment date',
}

# Most important fields first; others follow in their own order.
FIELD_ORDER = ['amount_paise', 'vendor', 'client', 'project', 'name', 'title', 'payment_mode', 'date',
               'due_date', 'assignee', 'kind', 'gst_included', 'category', 'phone', 'client_phone',
               'location', 'start_date', 'progress', 'status', 'note', 'gstin', 'trade', 'cost_id']

PAYMENT_MODES = {'cash': 'Cash', 'upi': 'UPI', 'bank_transfer': 'Bank transfer', 'cheque': 'Cheque', 'card': 'Card'}
KINDS = {'expense': 'Already spent', 'commitment': 'Purchase order'}

BOILERPLATE = ('Draft preview ready. No business record was saved.',
               'Draft updated. No business record changed. Review the ticket preview.')


def inr(paise) -> str:
    """12,50,000 paise -> '₹12,500' using Indian digit grouping."""
    if not isinstance(paise, int) or isinstance(paise, bool):
        return '—'
    rupees, rem = divmod(abs(paise), 100)
    s = str(rupees)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = re.sub(r'(\d)(?=(\d\d)+$)', r'\1,', head)
        s = head + ',' + tail
    out = '₹' + s + (f'.{rem:02d}' if rem else '')
    return '-' + out if paise < 0 else out


def format_value(field: str, value) -> str:
    if value is None or value == '':
        return '—'
    if field.endswith('_paise'):
        return inr(value)
    if field == 'gst_included':
        return 'Included' if value is True else 'Not included' if value is False else str(value)
    if field == 'payment_mode':
        return PAYMENT_MODES.get(str(value), str(value).replace('_', ' ').title())
    if field == 'kind':
        return KINDS.get(str(value), str(value))
    if field in ('date', 'due_date', 'start_date') and isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        y, m, d = value.split('-')
        months = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()
        if 1 <= int(m) <= 12:
            return f'{int(d)} {months[int(m) - 1]} {y}'
    if field == 'progress' and isinstance(value, int):
        return f'{value}%'
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    if isinstance(value, dict):
        return ', '.join(f'{k.replace("_", " ")}: {v}' for k, v in value.items())
    return str(value)


def ordered_fields(after: dict) -> list[str]:
    keys = [k for k in FIELD_ORDER if k in after] + [k for k in after if k not in FIELD_ORDER]
    return [k for k in keys if k != 'id']


def item_line(item: dict) -> str:
    """One-line summary: 'Expense · ₹12,500 · Ravi Electricals · Sharma Residence'."""
    after = item.get('after') or {}
    parts = [ITEM_TITLES.get(item.get('item_type'), 'Draft')]
    for key in ('amount_paise', 'vendor', 'name', 'title', 'client', 'project', 'payment_mode', 'due_date', 'date'):
        v = after.get(key)
        if v not in (None, '') and len(parts) < 5:
            parts.append(format_value(key, v))
    return ' · '.join(dict.fromkeys(parts))


def draft_summary(items: list[dict], asks: list[dict]) -> str:
    pending = [i for i in items if i.get('status') == 'pending']
    if not pending:
        return ''
    if len(pending) == 1:
        lead = f"I've drafted this: **{pending[0].get('line') or item_line(pending[0])}**."
    else:
        lead = f"I've drafted {len(pending)} items from that. Check each one below."
    missing = [ask for ask in asks if ask.get('field')]
    if missing:
        return lead + ' ' + ('One thing to confirm.' if len(asks) == 1 else f'{len(asks)} things to confirm.')
    return lead + ' Check it and approve when it looks right. Nothing is saved until then.'


# --------------------------------------------------------------------- questions

KNOWN_QUESTIONS = {
    'gst_included': ('Was GST included in this amount?', 'gst_included',
                     [('GST included', True), ('Not included', False)]),
    'payment_mode': ('How was it paid?', 'payment_mode',
                     [('Cash', 'cash'), ('UPI', 'upi'), ('Bank transfer', 'bank_transfer')]),
    'payment_modes': ('How was it paid?', 'payment_mode',
                      [('Cash', 'cash'), ('UPI', 'upi'), ('Bank transfer', 'bank_transfer')]),
    'kind': ('Is this already spent, or a purchase order?', 'kind',
             [('Already spent', 'expense'), ('Purchase order', 'commitment')]),
    'is_this_a_new_payment': ('This looks like an entry you already have. Is it a new one?', None,
                              [("Yes, it's new", "Yes, this is a new payment."),
                               ("No, it's a duplicate", "No, that's a duplicate. Please don't save it.")]),
}
FREE_TEXT_QUESTIONS = {
    'project': 'Which project is this for?', 'title': 'What is it for?', 'name': 'What should it be called?',
    'amount_paise': 'What is the amount in rupees?', 'vendor': 'Who is the supplier?', 'note': 'What happened on site?',
    'cost_id': 'Which bill or expense is this payment for?', 'idea': 'What would you like to track?',
    'location': 'Where is the site?', 'handover_date': 'When is handover?', 'due_date': 'When is it due?',
}


def _target(field, items, allowed):
    for item in items:
        if item.get('status') == 'pending' and field in (allowed.get(item.get('item_type')) or set()):
            return item
    return None


def build_asks(questions, items, allowed_fields, visible_projects=()):
    """Questions -> [{'id','text','field','item_id','choices':[{'label','value'}],'free_text'}]."""
    asks, seen = [], set()
    for q in questions or []:
        q = str(q).strip()
        if not q or q in seen:
            continue
        seen.add(q)
        key = q.casefold().replace(' ', '_')
        if key in KNOWN_QUESTIONS:
            text, field, choices = KNOWN_QUESTIONS[key]
            target = _target(field, items, allowed_fields) if field else None
            if field and target is None:
                continue  # nothing left to answer on any draft
            asks.append({'id': key, 'text': text, 'field': field, 'item_id': target and target.get('id'),
                         'choices': [{'label': l, 'value': v} for l, v in choices], 'free_text': False})
            continue
        # "Sharma Residence or Sharma Showroom?" -> two choices for the project
        options = [o.strip(' ?.') for o in re.split(r',\s*|\s+or\s+', q) if o.strip(' ?.')]
        named = [o for o in options if o.casefold() in {p.casefold() for p in visible_projects}]
        if len(named) >= 2 and len(named) == len(options):
            target = _target('project', items, allowed_fields)
            asks.append({'id': 'project', 'text': 'Which project do you mean?', 'field': 'project' if target else None,
                         'item_id': target and target.get('id'),
                         'choices': [{'label': n, 'value': n} for n in named], 'free_text': False})
            continue
        if key in FREE_TEXT_QUESTIONS or key == 'which_project':
            field = 'project' if key == 'which_project' else key
            target = _target(field, items, allowed_fields)
            text = FREE_TEXT_QUESTIONS.get(key, 'Which project is this for?')
            choices = [{'label': p, 'value': p} for p in visible_projects][:6] if field == 'project' and 0 < len(visible_projects) <= 6 else []
            asks.append({'id': key, 'text': text, 'field': field if target else None, 'item_id': target and target.get('id'),
                         'choices': choices, 'free_text': not choices})
            continue
        if re.fullmatch(r'[a-z0-9_]+', q):  # an internal key the AI used: make it readable
            text = q.replace('_', ' ').capitalize() + '?'
        else:
            text = q
        asks.append({'id': key[:60], 'text': text, 'field': None, 'item_id': None, 'choices': [], 'free_text': True})
    unique, ids = [], set()
    for ask in asks:  # one question per topic; the specific one wins (it came first)
        if ask['id'] in ids or (ask['id'] == 'which_project' and 'project' in ids):
            continue
        ids.add(ask['id']); unique.append(ask)
    return unique


def coerce_answer(field: str, value, allowed: set):
    """Validate a tapped or typed answer for a draft field. Raises ValueError."""
    if field not in allowed:
        raise ValueError('That detail does not apply to this draft')
    if field in ('vendor_id', 'paid_through_id', 'expense_account_id', 'receipt_id', 'project_id') and 'paid_through_id' in allowed:
        if value is None and field in ('vendor_id', 'receipt_id', 'project_id'):
            return None
        if type(value) is not int or value <= 0:
            raise ValueError('Choose an existing record for this field.')
        return value
    if field == 'no_vendor' and 'paid_through_id' in allowed:
        if type(value) is not bool:
            raise ValueError('Choose Yes or No.')
        return value
    if field == 'gst_included':
        if not isinstance(value, bool):
            raise ValueError('GST answer must be included or not included')
        return value
    if field == 'payment_mode':
        if value not in PAYMENT_MODES:
            raise ValueError('Unknown payment method')
        return value
    if field == 'kind':
        if value not in KINDS:
            raise ValueError('Unknown type')
        return value
    if field.endswith('_paise') or field in ('cost_id', 'progress'):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError('A whole positive number is needed')
        return value
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValueError('Please give a short answer')
    return value.strip()


# --------------------------------------------------------------------- decisions (v0.9.0)

def when_text(moment) -> str:
    """'13 Nov 2026, 2:05 pm' in the studio's time zone (STUDIOOS_TIMEZONE, default India)."""
    import os
    import datetime as _dt
    try:
        from zoneinfo import ZoneInfo
        zone = ZoneInfo(os.getenv('STUDIOOS_TIMEZONE', 'Asia/Kolkata'))
    except Exception:
        zone = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_dt.timezone.utc)
    local = moment.astimezone(zone)
    hour = local.hour % 12 or 12
    return f"{local.day} {local.strftime('%b %Y')}, {hour}:{local.minute:02d} {'am' if local.hour < 12 else 'pm'}"


def describe_changes(old: dict, new: dict, data_labels: dict | None = None, data_display=None) -> list[str]:
    """['Amount: ₹12,500 → ₹12,000', 'Rating: — → 4'] for every value that changed."""
    old, new = dict(old or {}), dict(new or {})
    lines = []
    for key in ordered_fields({**old, **new}):
        if key == 'data':
            continue
        if old.get(key) != new.get(key):
            lines.append(f"{FIELD_LABELS.get(key, key.replace('_', ' ').capitalize())}: "
                         f"{format_value(key, old.get(key))} → {format_value(key, new.get(key))}")
    od, nd = old.get('data') or {}, new.get('data') or {}
    if isinstance(od, dict) and isinstance(nd, dict):
        for key in list(dict.fromkeys([*od, *nd])):
            if od.get(key) != nd.get(key):
                label = (data_labels or {}).get(key) or key.replace('_', ' ').capitalize()
                show = data_display or (lambda k, v: '—' if v in (None, '') else str(v))
                lines.append(f'{label}: {show(key, od.get(key))} → {show(key, nd.get(key))}')
    return lines

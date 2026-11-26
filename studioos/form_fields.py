"""The fields each "create" form asks for, and which of them are required.

One list per kind of record, so the form on screen, the server check and the AI chat all agree.

References:
- Money follows Zoho Books: an Expense needs a date, an expense account, an amount and the account it was paid
  through; a Purchase order needs a vendor and a date; a Payment made needs the bill, the amount, the date and the
  account it was paid through. Reference numbers and notes are optional there too.
- Projects and tasks follow the usual project-management tools (Zoho Projects, Asana, Jira): every project has a
  client, an owner (project manager), a start date and a status; every task has an owner and a due date.
- People follow Zoho's user screen: name, email and role are required; phone, designation and department are optional.

`locked` fields are needed by the system itself, so nobody (person or AI) can make them optional.
The owner can change the rest through an approved change request (ticket kind `field_rule_change`), which also lets
them add their own extra fields. Those rules live in the `field_rules` table and are read on every check.
"""
from __future__ import annotations

import os
import re

from sqlalchemy import select

PAYMENT_MODES = [('cash', 'Cash'), ('bank_transfer', 'Bank transfer / NEFT / RTGS'), ('upi', 'UPI'),
                 ('cheque', 'Cheque'), ('card', 'Card')]
EXPENSE_ACCOUNTS = ['Materials', 'Labour', 'Subcontractor', 'Consultant and professional fees', 'Equipment hire',
                    'Site expenses', 'Travel and conveyance', 'Fuel', 'Rent', 'Utilities', 'Office supplies',
                    'Printing and stationery', 'Repairs and maintenance', 'Telephone and internet', 'Other expenses']
PROJECT_STAGES = ['Planning', 'Design', 'Approvals', 'Construction', 'Handover', 'On hold', 'Completed']
PROJECT_TYPES = ['Residential', 'Commercial', 'Interior', 'Hospitality', 'Institutional', 'Landscape', 'Other']
PRIORITIES = ['Low', 'Medium', 'High', 'Urgent']
ROLES = [('architect', 'Architect'), ('site_engineer', 'Site engineer'), ('accounts', 'Accounts'),
         ('manager', 'Manager'), ('viewer', 'Viewer')]


def _f(name, label, kind='text', required=False, locked=False, **extra):
    return {'name': name, 'label': label, 'type': kind, 'required': required, 'locked': locked, **extra}


# name -> list of fields, in the order the form shows them
FORMS: dict[str, list[dict]] = {
    'project': [
        _f('name', 'Project name', required=True, locked=True, maxlength=200),
        _f('client', 'Client', required=True, maxlength=200),
        _f('manager', 'Project manager', 'person', required=True),
        _f('start_date', 'Start date', 'date', required=True),
        _f('stage', 'Status', 'select', required=True, options=PROJECT_STAGES, default='Planning'),
        _f('project_code', 'Project code', maxlength=40, placeholder='e.g. VLA-2026-01'),
        _f('project_type', 'Project type', 'select', options=PROJECT_TYPES),
        _f('end_date', 'Target end date', 'date'),
        _f('budget', 'Approved budget (₹)', 'amount'),
        _f('location', 'Site address', maxlength=200),
        _f('client_phone', 'Client phone', 'tel', maxlength=10, placeholder='10-digit mobile'),
        _f('description', 'Description', 'textarea', maxlength=2000),
    ],
    'task': [
        _f('project_id', 'Project', 'project', required=True, locked=True),
        _f('title', 'Task title', required=True, locked=True, maxlength=400),
        _f('assignee', 'Owner (assigned to)', 'person', required=True),
        _f('due_date', 'Due date', 'date', required=True),
        _f('priority', 'Priority', 'select', required=True, options=PRIORITIES, default='Medium'),
        _f('start_date', 'Start date', 'date'),
        _f('description', 'Description', 'textarea', maxlength=2000),
    ],
    'person': [
        _f('display_name', 'Full name', required=True, locked=True, maxlength=150),
        _f('username', 'Username (for signing in)', required=True, locked=True, maxlength=100),
        _f('email', 'Email', 'email', required=True, maxlength=200),
        _f('role', 'Role', 'select', required=True, locked=True, options=ROLES),
        _f('password', 'First password (12+ characters)', 'password', required=True, locked=True),
        _f('phone', 'Mobile', 'tel', maxlength=10, placeholder='10-digit mobile'),
        _f('designation', 'Designation', maxlength=100, placeholder='e.g. Senior architect'),
        _f('department', 'Department', maxlength=100),
        _f('joining_date', 'Date of joining', 'date'),
    ],
    # Zoho Books: Expense. Date, Expense account, Amount and Paid through are required.
    'expense': [
        _f('date', 'Date', 'date', required=True, default='today'),
        _f('project_id', 'Project', 'project', required=True, locked=True),
        _f('category', 'Expense account', 'select', required=True, options=EXPENSE_ACCOUNTS),
        _f('amount', 'Amount (₹)', 'amount', required=True, locked=True),
        _f('payment_mode', 'Paid through', 'select', required=True, options=PAYMENT_MODES),
        _f('title', 'Description', required=True, locked=True, maxlength=400),
        _f('vendor', 'Vendor', maxlength=200),
        _f('reference_number', 'Invoice / reference #', maxlength=80),
        _f('gst_included', 'Amount includes GST', 'checkbox'),
        _f('attachment_ids', 'Receipt / bill images', 'files'),
        _f('notes', 'Notes', 'textarea', maxlength=1000),
    ],
    # Zoho Books: Purchase order. Vendor and date are required; the PO number is the reference.
    'commitment': [
        _f('date', 'Order date', 'date', required=True, default='today'),
        _f('project_id', 'Project', 'project', required=True, locked=True),
        _f('vendor', 'Vendor', required=True, maxlength=200),
        _f('title', 'What is being ordered', required=True, locked=True, maxlength=400),
        _f('amount', 'Order amount (₹)', 'amount', required=True, locked=True),
        _f('reference_number', 'Purchase order #', maxlength=80),
        _f('attachment_ids', 'Order copy / bill images', 'files'),
        _f('notes', 'Notes', 'textarea', maxlength=1000),
    ],
    # Zoho Books: Payments made. Bill, amount, payment date and Paid through are required.
    'payment': [
        _f('cost_id', 'Pay against', 'cost', required=True, locked=True),
        _f('amount', 'Payment amount (₹)', 'amount', required=True, locked=True),
        _f('date', 'Payment date', 'date', required=True, default='today'),
        _f('payment_mode', 'Paid through', 'select', required=True, options=PAYMENT_MODES),
        _f('reference_number', 'Reference # (UTR / cheque no.)', maxlength=80),
        _f('attachment_ids', 'Payment proof (image)', 'files'),
    ],
}
FORM_LABELS = {'project': 'Project', 'task': 'Task', 'person': 'Person', 'expense': 'Expense',
               'commitment': 'Purchase order', 'payment': 'Payment'}
ALIASES = {'project': 'project', 'projects': 'project', 'task': 'task', 'tasks': 'task', 'person': 'person',
           'people': 'person', 'user': 'person', 'users': 'person', 'staff': 'person', 'team member': 'person',
           'expense': 'expense', 'expenses': 'expense', 'cost': 'expense', 'costs': 'expense',
           'purchase order': 'commitment', 'purchase orders': 'commitment', 'po': 'commitment', 'commitment': 'commitment',
           'payment': 'payment', 'payments': 'payment', 'vendor payment': 'payment'}
CUSTOM_TYPES = ('text', 'number', 'date', 'amount', 'textarea')

# which ticket draft carries which form, and the name each form field has inside the ticket data
TICKET_FORMS = {'create_project': 'project', 'create_task': 'task', 'record_payment': 'payment'}
TICKET_KEYS = {'project': {'budget': 'amount_paise'}, 'task': {'project_id': 'project'},
               'expense': {'project_id': 'project', 'amount': 'amount_paise'},
               'commitment': {'project_id': 'project', 'amount': 'amount_paise'},
               'payment': {'amount': 'amount_paise'}}


def enforced() -> bool:
    """Required fields are checked unless this copy is explicitly run without them (the older test suite does)."""
    return os.getenv('STUDIOOS_ENFORCE_REQUIRED_FIELDS', 'true').strip().lower() not in ('0', 'false', 'off', 'no')


def form_for_ticket(kind: str, data: dict) -> str | None:
    if kind == 'record_cost':
        return 'commitment' if (data or {}).get('kind') == 'commitment' else 'expense'
    return TICKET_FORMS.get(kind)


def slug(label: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', str(label or '').casefold()).strip('_')[:60]


def _rules(db, form):
    from .db import FieldRule
    return db.scalars(select(FieldRule).where(FieldRule.form == form, FieldRule.active.is_(True)).order_by(FieldRule.id)).all()


def fields(db, form: str) -> list[dict]:
    """The form's fields with the owner's approved changes applied (required switched, extra fields added)."""
    base = [dict(f) for f in FORMS.get(form, [])]
    by_name = {f['name']: f for f in base}
    for rule in _rules(db, form):
        if rule.custom:
            if rule.field not in by_name:
                f = _f(rule.field, rule.label, rule.field_type or 'text', required=bool(rule.required), custom=True)
                base.append(f); by_name[rule.field] = f
            else:
                by_name[rule.field]['required'] = bool(rule.required)
        elif rule.field in by_name and not by_name[rule.field]['locked']:
            by_name[rule.field]['required'] = bool(rule.required)
    return base


def all_forms(db) -> dict:
    return {name: {'label': FORM_LABELS[name], 'fields': fields(db, name)} for name in FORMS}


def missing(db, form: str, data: dict, ticket_keys: bool = False) -> list[str]:
    """Labels of required fields that are empty. With ticket_keys the data uses the ticket's names
    (project, amount_paise), and extra fields sit under data['custom']."""
    out = []
    data = data or {}
    custom = data.get('custom') if isinstance(data.get('custom'), dict) else {}
    rename = TICKET_KEYS.get(form, {}) if ticket_keys else {}
    for f in fields(db, form):
        if not f['required'] or f['type'] in ('password', 'checkbox'):
            continue
        key = rename.get(f['name'], f['name'])
        value = custom.get(f['name']) if f.get('custom') else data.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            out.append(f['label'])
    return out


def check(db, form: str, data: dict, ticket_keys: bool = False) -> None:
    if not enforced():
        return
    gaps = missing(db, form, data, ticket_keys)
    if gaps:
        raise ValueError('Fill in the required fields: ' + ', '.join(gaps) + '.')


def clean_custom(db, form: str, raw) -> dict:
    """Only the owner-approved extra fields, as short strings."""
    if not isinstance(raw, dict):
        return {}
    allowed = {f['name'] for f in fields(db, form) if f.get('custom')}
    return {k: str(v).strip()[:500] for k, v in raw.items() if k in allowed and v not in (None, '')}


# --- the field_rule_change ticket: make a field required/optional, or add a field --------------------------------

RULE_FIELDS = {'form', 'field', 'label', 'field_type', 'required', 'add', 'reason'}


def resolve_form(word) -> str | None:
    w = ' '.join(str(word or '').casefold().split())
    return ALIASES.get(w) or (w if w in FORMS else None)


def find_field(db, form, word) -> dict | None:
    w = str(word or '').casefold().strip()
    for f in fields(db, form):
        if w in (f['name'].casefold(), f['label'].casefold(), slug(f['label'])) or slug(w) == f['name']:
            return f
    for f in fields(db, form):   # a looser match on the words of the label ("paid through" -> "Paid through")
        if w and w in f['label'].casefold():
            return f
    return None


def validate_rule(db, d: dict) -> dict:
    if not isinstance(d, dict) or set(d) - RULE_FIELDS:
        raise ValueError('Unrecognized field change')
    form = resolve_form(d.get('form'))
    if not form:
        raise ValueError('Say which form to change: project, task, person, expense, purchase order or payment.')
    if not isinstance(d.get('required'), bool):
        raise ValueError('Say whether the field should be required or optional.')
    if d.get('add'):
        label = ' '.join(str(d.get('label') or d.get('field') or '').split())
        if not 2 <= len(label) <= 60:
            raise ValueError('Give the new field a name of 2 to 60 characters.')
        if find_field(db, form, label) and slug(label) in {f['name'] for f in fields(db, form)}:
            raise ValueError(f'The {FORM_LABELS[form]} form already has a field called {label}.')
        kind = d.get('field_type') or 'text'
        if kind not in CUSTOM_TYPES:
            raise ValueError('A new field can be text, number, date, amount or long text.')
        return {'form': form, 'field': slug(label), 'label': label, 'field_type': kind, 'required': d['required'], 'custom': True}
    f = find_field(db, form, d.get('field'))
    if not f:
        raise ValueError(f'The {FORM_LABELS[form]} form has no field called {d.get("field")!r}.')
    if f['locked'] and not d['required']:
        raise ValueError(f'{f["label"]} is needed by StudioOS itself and cannot be made optional.')
    if f['required'] == d['required']:
        raise ValueError(f'{f["label"]} is already {"required" if f["required"] else "optional"}.')
    return {'form': form, 'field': f['name'], 'label': f['label'], 'field_type': f['type'], 'required': d['required'],
            'custom': bool(f.get('custom'))}


def apply_rule(db, d: dict, ticket_id: int | None, actor: str):
    from .db import FieldRule, add_audit
    r = validate_rule(db, d)
    for old in db.scalars(select(FieldRule).where(FieldRule.form == r['form'], FieldRule.field == r['field'],
                                                  FieldRule.active.is_(True))).all():
        old.active = False
    rule = FieldRule(form=r['form'], field=r['field'], label=r['label'], field_type=r['field_type'],
                     required=r['required'], custom=r['custom'], active=True, ticket_id=ticket_id, created_by=actor)
    db.add(rule)
    db.flush()
    add_audit(db, 'field_rule', 'field_rule', rule.id,
              f'{FORM_LABELS[r["form"]]} form: {r["label"]} is now {"required" if r["required"] else "optional"}'
              + (' (new field)' if d.get('add') else ''), actor=actor)
    return rule


def describe(d: dict) -> str:
    form = FORM_LABELS.get(resolve_form(d.get('form')) or '', str(d.get('form')))
    what = 'required' if d.get('required') else 'optional'
    if d.get('add'):
        return f'Add a {what} field "{d.get("label") or d.get("field")}" to the {form} form'
    return f'Make "{d.get("field")}" {what} on the {form} form'


_ADD = re.compile(r'\badd (?:an? )?(?:new )?(?:(mandatory|required|compulsory|optional) )?field\s+(?:called |named )?["\']?(.+?)["\']?'
                  r'\s+(?:to|on|in|for)\s+(?:the\s+)?(.+?)(?:\s+form)?(?:\s+as\s+(mandatory|required|optional))?\s*[.!]?$', re.I)
_MAKE = re.compile(r'\bmake\s+(?:the\s+)?["\']?(.+?)["\']?\s+(?:field\s+)?(mandatory|required|compulsory|optional|not required|not mandatory)'
                   r'\s+(?:for|on|in|when creating|while creating)\s+(?:an?\s+|the\s+)?(.+?)(?:\s+form)?\s*[.!]?$', re.I)


def parse_request(text: str) -> dict | None:
    """'make client phone mandatory for projects', 'add a required field GST number to expenses'."""
    s = ' '.join(str(text or '').split())
    m = _ADD.search(s)
    if m and resolve_form(m.group(3)):
        word = (m.group(1) or m.group(4) or 'optional').casefold()
        return {'form': resolve_form(m.group(3)), 'label': m.group(2).strip(), 'field': m.group(2).strip(), 'add': True,
                'required': word in ('mandatory', 'required', 'compulsory'), 'field_type': 'text'}
    m = _MAKE.search(s)
    if m and resolve_form(m.group(3)):
        word = m.group(2).casefold()
        return {'form': resolve_form(m.group(3)), 'field': m.group(1).strip(), 'add': False,
                'required': word in ('mandatory', 'required', 'compulsory')}
    return None

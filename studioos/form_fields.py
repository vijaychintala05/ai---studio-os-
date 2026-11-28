"""Definitions and validation for the additional fields on create forms."""
from datetime import date
import re

from sqlalchemy import select

from .db import CustomFieldValue, FieldRule, add_audit


PROJECT_FIELDS = {
    'start_date': ('Start date', 'date', 30),
    'end_date': ('Target end date', 'date', 30),
    'project_code': ('Project code', 'text', 40),
    'project_type': ('Project type', 'text', 60),
    'manager': ('Project manager', 'text', 150),
    'description': ('Description', 'textarea', 2000),
}
TASK_FIELDS = {
    'priority': ('Priority', 'select', 20),
    'start_date': ('Start date', 'date', 30),
    'description': ('Description', 'textarea', 2000),
}
PERSON_FIELDS = {
    'email': ('Email', 'email', 200),
    'phone': ('Phone', 'tel', 20),
    'designation': ('Designation', 'text', 100),
    'department': ('Department', 'text', 100),
    'joining_date': ('Joining date', 'date', 30),
}
PRIORITIES = ('Low', 'Medium', 'High', 'Urgent')
PROJECT_TYPES = ('Residential', 'Commercial', 'Interior', 'Hospitality', 'Institutional', 'Landscape', 'Other')
RULE_TYPE = 'field_rule_change'
RULE_FIELDS = {'form', 'field', 'label', 'required', 'add'}
TICKET_FORMS = {'create_project': 'project', 'create_task': 'task'}
_FORMS = {'project': PROJECT_FIELDS, 'task': TASK_FIELDS, 'person': PERSON_FIELDS}
_FORM_NAMES = {'projects': 'project', 'tasks': 'task', 'people': 'person'}

_CORE_FIELDS = {
    'project': (
        ('name', 'Project name', 'text', True),
        ('location', 'Location', 'text', False),
        ('client_phone', 'Client phone', 'tel', False),
    ),
    'task': (
        ('project_id', 'Project', 'project', True),
        ('title', 'Task title', 'text', True),
        ('assignee', 'Owner', 'person', False),
        ('due_date', 'Due date', 'date', False),
    ),
    'person': (
        ('username', 'Username', 'text', True),
        ('display_name', 'Display name', 'text', True),
        ('role', 'Role', 'select', True),
        ('password', 'Password', 'password', True),
    ),
}


def form_specs(db):
    """Define controls once for typed forms and the review editor."""
    choices = {'project_type': PROJECT_TYPES, 'priority': PRIORITIES}
    result = {}
    for form, fields in _FORMS.items():
        core = [{'name': name, 'label': label, 'type': kind, 'required': required, 'locked': required}
                for name, label, kind, required in _CORE_FIELDS[form]]
        extras = []
        for name, (label, kind, length) in fields.items():
            field = {'name': name, 'label': label, 'type': kind, 'maxlength': length,
                     'required': False, 'extra': True}
            if name in choices:
                field.update(type='select', options=choices[name])
            extras.append(field)
        result[form] = {'fields': core + extras}
    active_rules = db.scalars(select(FieldRule).where(FieldRule.active.is_(True)).order_by(FieldRule.id))
    for rule in active_rules:
        if rule.form not in result:
            continue
        fields = result[rule.form]['fields']
        field = next((value for value in fields if value['name'] == rule.field), None)
        if field is None and rule.custom:
            fields.append({
                'name': rule.field, 'label': rule.label, 'type': rule.field_type,
                'maxlength': 500, 'required': rule.required, 'extra': True, 'custom': True,
            })
        elif field is not None and not field.get('locked'):
            field['required'] = rule.required
    return result


def details(data, fields):
    """Clean the additional values for an approved record, keeping blanks nullable."""
    out = {}
    for key, (label, kind, length) in fields.items():
        raw = data.get(key)
        if raw is None or raw == '':
            continue
        if not isinstance(raw, str) or len(raw) > length:
            raise ValueError(f'{label} must be text of at most {length} characters.')
        value = raw.strip()
        if not value:
            continue
        if kind == 'date':
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError()
            except ValueError:
                raise ValueError(f'{label} must be a valid calendar date.') from None
        elif kind == 'select' and key == 'priority' and value not in PRIORITIES:
            raise ValueError('Choose a valid task priority.')
        elif kind == 'email' and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            raise ValueError('Enter a valid email address.')
        elif kind == 'tel' and not re.fullmatch(r'\+?[\d ()-]+', value):
            raise ValueError('Enter a valid phone number.')
        out[key] = value
    return out


def record_details(record, fields):
    return {key: getattr(record, key) for key in fields}


def _slug(value):
    return re.sub(r'[^a-z0-9]+', '_', str(value or '').casefold()).strip('_')[:60]


_ADD_FIELD = re.compile(
    r'^add (?:an? )?(?:(required|optional|mandatory) )?(?:new )?field (?:called )?(.+?)'
    r' (?:to|on) (?:the )?(project|projects|task|tasks|person|people)(?: form)?[.!]?$', re.I,
)
_CHANGE_FIELD = re.compile(
    r'^make (?:the )?(.+?) (required|optional|mandatory) (?:for|on|in) (?:the )?'
    r'(project|projects|task|tasks|person|people)(?: form)?[.!]?$', re.I,
)


def parse_rule_request(message):
    text = ' '.join(message.split())
    if match := _ADD_FIELD.fullmatch(text):
        required, label, form = match.groups()
        label = label.strip().strip('"').strip("'").strip()
        return {'form': _FORM_NAMES.get(form.casefold(), form.casefold()), 'field': _slug(label),
                'label': label, 'required': bool(required and required.casefold() != 'optional'), 'add': True}
    if match := _CHANGE_FIELD.fullmatch(text):
        field, required, form = match.groups()
        return {'form': _FORM_NAMES.get(form.casefold(), form.casefold()), 'field': _slug(field),
                'required': required.casefold() != 'optional'}
    return None


def validate_rule(db, data):
    form, required, name = data.get('form'), data.get('required'), data.get('field')
    if not isinstance(form, str) or form not in _FORMS or type(required) is not bool or not isinstance(name, str):
        raise ValueError('Choose a project, task or person field and say whether it should be required.')
    fields = form_specs(db)[form]['fields']
    field = next((value for value in fields if name in (value['name'], _slug(value['label']))), None)
    if data.get('add') is True:
        if form == 'person':
            raise ValueError('You can change which existing person fields are required.')
        label = data.get('label')
        if not isinstance(label, str) or not 2 <= len(label.strip()) <= 60 or not name or _slug(label) != name:
            raise ValueError('Give the new field a name of 2 to 60 characters.')
        reserved = {'id', 'client', 'client_id', 'company_id', 'budget', 'stage', 'custom', 'request_key',
                    'start_date', 'amount_paise', 'project', 'progress', 'status'}
        if field or name in reserved:
            raise ValueError('This name is already used by the form.')
        return {'form': form, 'field': name, 'label': label.strip(), 'field_type': 'text',
                'required': required, 'custom': True}
    if not field:
        raise ValueError('That field is not on this form.')
    if field.get('locked') and not required:
        raise ValueError(f"{field['label']} must stay required.")
    if field['required'] == required:
        raise ValueError(f"{field['label']} is already {'required' if required else 'optional'}.")
    return {'form': form, 'field': field['name'], 'label': field['label'], 'field_type': field['type'],
            'required': required, 'custom': bool(field.get('custom'))}


def apply_rule(db, item, actor):
    rule_data = validate_rule(db, item.after_data)
    previously_active = db.scalars(select(FieldRule).where(
        FieldRule.form == rule_data['form'], FieldRule.field == rule_data['field'], FieldRule.active.is_(True),
    ))
    for rule in previously_active:
        rule.active = False
    rule = FieldRule(**rule_data, ticket_id=item.ticket_id, created_by=actor)
    db.add(rule)
    db.flush()
    add_audit(db, 'field_rule', 'field_rule', rule.id, f'Changed {rule.label} on the {rule.form} form', actor=actor)
    return {'type': 'field_rule', 'id': rule.id, 'item_id': item.id}


def checked_custom_values(db, form, data):
    fields = form_specs(db)[form]['fields']
    custom = data.get('custom', {})
    allowed = {field['name'] for field in fields if field.get('custom')}
    if not isinstance(custom, dict) or set(custom) - allowed:
        raise ValueError('Use only extra fields approved for this form.')
    clean = {}
    for key, value in custom.items():
        if not isinstance(value, str) or len(value) > 500:
            raise ValueError('Extra field values must be text of at most 500 characters.')
        if value.strip():
            clean[key] = value.strip()
    missing = []
    for field in fields:
        key = 'project' if field['name'] == 'project_id' else field['name']
        value = clean.get(key) if field.get('custom') else data.get(key)
        if field['required'] and (value is None or (isinstance(value, str) and not value.strip())):
            missing.append(field['label'])
    if missing:
        raise ValueError('Fill in the required fields: ' + ', '.join(missing) + '.')
    return clean


def save_custom_values(db, form, record_id, values):
    db.add_all(CustomFieldValue(form=form, record_id=record_id, field=key, value=value) for key, value in values.items())

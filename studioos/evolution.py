"""Conservative, declarative capability blueprints for unfamiliar information.

A blueprint is a *proposal*, never executable code. The StudioOS backend owns
all validation and all writes. Source text is evidence, not instructions.
The first slice intentionally has no arbitrary SQL, expressions, JS, Python,
custom HTTP actions, migration runner, or generated application deployment.
"""
from __future__ import annotations

from copy import deepcopy

BLUEPRINT_VERSION = 1
FORM_TYPES = {
    'text': 'text', 'integer': 'number', 'decimal': 'number',
    'date': 'date', 'boolean': 'checkbox', 'timestamp': 'datetime',
    'jsonb': 'json-editor',
}
PROTECTED_FIELDS = frozenset({
    'id', 'reference', 'created_by', 'created_at', 'updated_at',
    'source_ticket_id', 'source_conversation_id', 'deleted_at',
    'reversed_at', 'reversal_reason',
})
STRATEGIES = {
    'new_type': 'propose_new_capability',
    'existing_fit': 'reuse_existing_capability',
    'partial_fit': 'extend_existing_capability',
    'reuse_proposal': 'reuse_pending_proposal',
    'blocked_destructive': 'blocked_for_admin_plan',
}


def build_blueprint(source_text: str, design: dict, fit: dict, answers: dict | None = None) -> dict:
    """Compile a *fixed vocabulary* of record, workflow and view definitions.

    No model-authored code is evaluated. Missing business semantics stay unknown.
    Changes to the design automatically regenerate dependent workflow and UI.
    """
    answers = answers or {}
    fields = design.get('fields') or []
    field_by_name = {f['name']: f for f in fields}
    names = set(field_by_name)
    strategy = STRATEGIES.get(fit.get('decision'), 'park_and_ask')
    unit = answers.get('record_unit') or design.get('record_unit') or None
    purpose = answers.get('purpose') or design.get('purpose') or None
    questions = [
        {'id': key, 'question': question} for key, question in (
            ('purpose', 'What decision or activity will these records support?'),
            ('record_unit', 'What does one record represent?'),
            ('links', 'Which existing records should it connect to?'),
            ('required_fields', 'What must be known before a record is useful?'),
            ('changes_over_time', 'Does it need updates or a close-out stage?'),
        ) if not answers.get(key)
    ]
    # These are generic *suggestions*. Business-specific transitions need answers.
    transitions = [
        {'from': 'draft', 'to': 'active', 'action': 'request_record_approval',
         'required_level': 'approve', 'review_roles': ['admin', 'manager'],
         'execution': 'not_enabled'},
        {'from': 'active', 'to': 'closed', 'action': 'request_record_closure',
         'required_level': 'close', 'review_roles': ['admin', 'manager'],
         'execution': 'not_enabled'},
        {'from': 'closed', 'to': 'reversed', 'action': 'request_record_reversal',
         'required_level': 'close', 'review_roles': ['admin'],
         'execution': 'not_enabled'},
    ]
    def ui_field(field):
        return {
            'field': field['name'], 'label': (field.get('meaning') or field.get('description') or field['name']),
            'control': FORM_TYPES.get(field.get('type'), 'text'),
            'required_level': field.get('required_level', 'optional'),
            'read_only': field['name'] in PROTECTED_FIELDS,
            'allowed_values': field.get('allowed_values'),
            'format': field.get('format'),
            'link': field.get('link'),
            'requires_approval': bool(field.get('change_requires_approval')),
        }
    form_fields = [ui_field(f) for f in fields]
    list_fields = [f for f in ('reference', 'project_id', 'status', 'created_at') if f in names]
    list_fields += [f['name'] for f in fields if f['name'] not in PROTECTED_FIELDS
                    and f['name'] not in list_fields and f['name'] not in ('extra_attributes',)
                    ][:3]
    risks = list(dict.fromkeys([
        'workflow_is_generic_until_business_meaning_confirmed' if questions else None,
        'record_lifecycle_requires_human_confirmation' if not answers.get('changes_over_time') else None,
        'no_runtime_actions_or_migrations_enabled',
        *(design.get('risks') or []),
    ]))
    risks = [r for r in risks if r]
    return {
        'blueprint_version': BLUEPRINT_VERSION,
        'status': 'proposal_only',
        'strategy': strategy,
        'record_type': design.get('table_name'),
        'source_evidence': {'original_words': source_text, 'trusted_as_instructions': False},
        'purpose': purpose,
        'record_unit': unit,
        'existing_reuse': [
            {'table': f['table'], 'score': f.get('score')}
            for f in (fit.get('near_fits') or [])[:4]
        ],
        'data_model': {
            'record_type': design.get('table_name'),
            'fields': [f['name'] for f in fields],
            'relationships': deepcopy(design.get('links') or []),
            'flexible_field': 'extra_attributes' if 'extra_attributes' in names else None,
        },
        'workflow': {
            'states': ['draft', 'active', 'closed', 'reversed'],
            'transitions': transitions,
            'confirm_lifecycle': not bool(answers.get('changes_over_time')),
            'mode': 'proposal_only',
        },
        'interface': {
            'form': {'title': (design.get('description') or 'Record') + ' — entry',
                     'fields': form_fields, 'source': 'approved_record_type_definition',
                     'mode': 'preview_only'},
            'list': {'columns': list_fields, 'filters': [f for f in ('project_id', 'status') if f in names],
                     'mode': 'preview_only'},
            'dashboards': [
                {'title': 'Records by status', 'metric': 'record_count',
                 'group_by': 'status', 'chart': 'bar', 'mode': 'preview_only'},
                {'title': 'Records by project', 'metric': 'record_count',
                 'group_by': 'project_id', 'chart': 'bar', 'mode': 'preview_only'}
            ],
        },
        'rules': {
            'requirement_source': 'field_specifications',
            'all_ai_writes': 'existing_approval_ticket_backend',
            'financial_changes': 'approval_required',
            'no_arbitrary_queries_or_code': True,
        },
        'questions': questions,
        'risks': risks,
        'execution': {
            'workflow_enabled': False, 'new_table_created': False,
            'migration_executed': False, 'custom_code_executed': False,
            'dashboard_queries_executed': False, 'deploy_enabled': False,
        },
    }


def validate_blueprint(design: dict, source_text: str, fit: dict, answers: dict | None = None) -> bool:
    """Fail closed on any model/client substitution, stale fields or unsafe actions.

    The server regenerates a canonical plan from inspected schema metadata. A
    submitted plan can't supply arbitrary endpoints, SQL, JS or workflow roles.
    """
    candidate = design.get('capability_blueprint')
    if candidate is None:
        raise ValueError('Capability blueprint is required for an evolving design')
    generated = build_blueprint(source_text, design, fit, answers)
    if candidate != generated:
        raise ValueError('Capability blueprint differs from backend-generated safe definitions')
    return True


def preview_blueprint(blueprint: dict, hypothetical_record: dict | None = None) -> dict:
    """Safe render data only: no business query, write, code or migration."""
    fields = blueprint['interface']['form']['fields']
    supplied = hypothetical_record or {}
    if not isinstance(supplied, dict) or len(supplied) > 100:
        raise ValueError('Preview record must be an object with at most 100 values')
    accepted = {f['field'] for f in fields}
    if set(supplied) - accepted:
        raise ValueError('Preview record includes unknown fields')
    return {
        'form': deepcopy(blueprint['interface']['form']),
        'list': deepcopy(blueprint['interface']['list']),
        'dashboards': deepcopy(blueprint['interface']['dashboards']),
        'fields_provided': [f for f in supplied if supplied[f] is not None],
        'incomplete_fields': [f['field'] for f in fields if f['required_level'] != 'optional'
                              and f['field'] not in supplied],
        'synthetic_preview': True,
        'data_loaded': False,
        'execution': deepcopy(blueprint['execution']),
    }

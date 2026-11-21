"""The owner's turnkey template is valid, in the owner's stage order, and publishes and applies through tickets. Fictional data."""
from studioos import work_rules_core as core
from studioos.work_template_turnkey import TURNKEY_STAGES, TURNKEY_TEMPLATE
from tests.conftest import approved_form
from tests.test_v017_work_rules_app import save


def test_the_definition_is_valid_and_in_the_owners_order():
    core.validate_template_definition(TURNKEY_TEMPLATE['definition'])
    assert [s['name'] for s in TURNKEY_TEMPLATE['definition']['stages']] == ['Redesign', 'Design', 'Working drawings', 'Execution', 'Handover']
    assert TURNKEY_STAGES == ('Redesign', 'Design', 'Working drawings', 'Execution', 'Handover')
    assert len(TURNKEY_TEMPLATE['definition']['links']) == 4


def test_publishes_and_applies_through_tickets(admin):
    p = approved_form(admin, 'post', '/api/projects', {'name': 'Villa Turnkey', 'budget': '100000'}).json()
    save(admin, 'work_template_publish', TURNKEY_TEMPLATE)
    save(admin, 'work_apply_template', {'template_key': 'turnkey', 'project_id': p['id'], 'start_date': '2026-12-01'})
    s = admin.get(f"/api/work/projects/{p['id']}/structure").json()
    assert [x['name'] for x in s['stages']] == ['Redesign', 'Design', 'Working drawings', 'Execution', 'Handover']
    assert len(s['tasks']) == 5 and len(s['links']) == 4

import pytest
from sqlalchemy import select

from studioos.db import Base, SessionLocal, User, WriteJournal
from studioos.time_models import TimeEntry
from .test_v018_time_app import log
from .conftest import approved_form
from .test_v093_mcp_app import call, key, on


# These tables hold sign-in state, messages, the draft and intake workflow,
# service settings, and infrastructure logs. Their own lifecycle rules apply.
OPERATIONAL_TABLES = {
    'ai_call_log', 'ai_corrections', 'approval_ticket_items', 'approval_tickets',
    'asked_questions', 'audit_events', 'chat_messages', 'chat_sessions',
    'connector_tokens', 'context_summaries', 'improve_suggestions', 'intake_items',
    'job_runs', 'login_attempts', 'login_sessions', 'mcp_calls', 'new_type_inbox',
    'schema_migrations', 'settings', 'summary_deliveries', 'time_timers', 'users',
    'write_journal',
}


def test_every_business_model_has_both_write_guards(admin):
    from studioos import db as models

    expected = set(Base.metadata.tables) - OPERATIONAL_TABLES
    assert OPERATIONAL_TABLES <= set(Base.metadata.tables)
    tracked = {entry if isinstance(entry, str) else entry.__tablename__ for entry in models._TRACKED}
    missing_orm = expected - tracked
    missing_sql = set()
    for table in sorted(expected):
        with SessionLocal() as db:
            db.info.update(write_source='ai:fictional-guard-check', ai_origin=True)
            # A zero-row write checks the connection guard without mutating a record.
            identifier = db.bind.dialect.identifier_preparer.quote(table)
            try:
                db.connection().exec_driver_sql(f'DELETE FROM {identifier} WHERE 1=0')
            except PermissionError:
                continue
            missing_sql.add(table)
    assert not (missing_orm or missing_sql), (
        f'Missing from ORM or journal: {sorted(missing_orm)}. Missing from SQL guard: {sorted(missing_sql)}.'
    )


def test_ai_time_write_requires_approval_and_approved_time_is_logged(admin):
    with SessionLocal() as db:
        user_id = db.scalar(select(User.id).where(User.username == 'admin'))
        db.info.update(write_source='ai:fictional-time', ai_origin=True)
        db.add(TimeEntry(user_id=user_id, activity='Fictional measuring', work_date='2026-01-05', minutes=25))
        with pytest.raises(PermissionError, match='approved ticket item'):
            db.flush()
        db.rollback()

    entry_id = log(admin, admin, minutes=25, activity='Fictional measuring')
    with SessionLocal() as db:
        event = db.scalar(select(WriteJournal).where(
            WriteJournal.entity_type == 'timeentry', WriteJournal.entity_id == entry_id,
            WriteJournal.operation == 'insert',
        ))
        assert event is not None and event.source == 'ai:ticket-commit' and event.original_chat_message_id


@pytest.mark.parametrize('tool', ['list_projects', 'get_project_status', 'get_budget_summary'])
def test_connector_summaries_display_1999_paise(admin, monkeypatch, tool):
    on(monkeypatch)
    name = 'Fictional Paise Site'
    approved = approved_form(admin, 'post', '/api/projects', {'name': name, 'budget': '19.99'})
    assert approved.status_code == 200, approved.text
    token = key(admin).json()['token']
    args = {} if tool == 'list_projects' else {'project': name}
    result = call(admin, token, tool, args)
    assert '₹19.99' in result['content'][0]['text']
    assert '₹19.98' not in result['content'][0]['text']
    structured = result['structuredContent']
    row = structured['budget'] if tool == 'get_project_status' else structured['projects'][0]
    assert row['approved_budget'] == 19.99
    assert row['approved_budget_paise'] == 1999


@pytest.mark.parametrize(('paise', 'display'), [
    (0, '₹0'), (1, '₹0.01'), (29, '₹0.29'), (57, '₹0.57'), (99, '₹0.99'),
    (100, '₹1'), (113, '₹1.13'), (1999, '₹19.99'), (2000, '₹20'),
    (1249999, '₹12,499.99'), (100000001, '₹10,00,000.01'),
])
def test_connector_formats_whole_paise(admin, monkeypatch, paise, display):
    on(monkeypatch)
    project = approved_form(admin, 'post', '/api/projects', {
        'name': 'Fictional Round Trip', 'budget': f'{paise // 100}.{paise % 100:02d}',
    })
    assert project.status_code == 200, project.text
    token = key(admin).json()['token']
    result = call(admin, token, 'get_budget_summary')
    assert f'budget {display},' in result['content'][0]['text']
    assert result['structuredContent']['totals']['approved_budget_paise'] == paise


def test_connector_finance_totals_use_exact_costs_and_payments(admin, monkeypatch):
    on(monkeypatch)
    project = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Cost Site', 'budget': '19.99'}).json()
    expense = approved_form(admin, 'post', '/api/costs', {
        'project_id': project['id'], 'kind': 'expense', 'title': 'Fictional material', 'amount': '0.57',
    }).json()
    paid = approved_form(admin, 'post', '/api/payments', {
        'cost_id': expense['id'], 'amount': '0.29', 'idempotency_key': 'fictional-paise-payment',
    })
    assert paid.status_code == 200, paid.text
    token = key(admin).json()['token']
    result = call(admin, token, 'get_budget_summary')
    assert 'known costs ₹0.57, paid ₹0.29, budget left ₹19.42' in result['content'][0]['text']
    totals = result['structuredContent']['totals']
    assert totals['known_costs_paise'] == 57
    assert totals['paid_to_vendors_paise'] == 29
    assert totals['still_payable_paise'] == 28
    assert totals['remaining_budget_paise'] == 1942

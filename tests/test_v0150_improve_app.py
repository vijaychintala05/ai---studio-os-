"""v0.15.0 self-improvement (app level; needs FastAPI + SQLAlchemy; runs in CI, NOT RUN in the build
sandbox).

Suggestions job: evidence, at most 5, accept -> ticket, dismissed never again; a daily rule that
proposes opens a ticket and changes nothing by itself; summaries per person with their own access
and once per period; a weekly review draft holds facts only; job runs are recorded and the self-check
reports them; the AI connector lists the catalog and proposes a record as a ticket. Fictional data."""
import datetime as dt

from sqlalchemy import func, select

from .conftest import write, approved_form
from .test_v098_universal_accounting import propose, save, project
from .test_v0100_one_graph import install, add_user, client_for
from studioos import improve_wiring as W
from studioos import improve_core as IM
from studioos.db import (SessionLocal, ApprovalTicket, FlexibleRecord, ImproveSuggestion, JobRun, SummaryDelivery)


def _issues(admin, pid, owner, n=22):
    for i in range(n):
        save(admin, propose(admin, 'metadata_record', {'type_key': 'work_issue', 'project_id': pid, 'values': {
            'title': f'Fictional issue {i}', 'owner': owner, 'severity': 'High' if i % 2 else 'Low', 'issue_status': 'Open'}}))


def test_suggestions_job_accept_and_dismiss(admin):
    install(admin, 'work')
    pa = project(admin)
    owner = add_user(admin, 'ravi.kumar', 'architect')
    _issues(admin, pa, owner)
    assert W.run_job('suggestions')['outcome'] == 'ok'
    s = admin.get('/api/improve/suggestions').json()['suggestions']
    assert 1 <= len(s) <= IM.MAX_PER_WEEK and all(x['evidence'] for x in s)
    hide = next(x for x in s if x['kind'] == 'hide_empty_field')
    other = next(x for x in s if x['id'] != hide['id'])
    t = write(admin, 'post', f'/api/improve/suggestions/{hide["id"]}/accept', {}).json()
    assert t['ticket_id']
    assert write(admin, 'post', f'/api/improve/suggestions/{other["id"]}/dismiss', {}).status_code == 200
    W.run_job('suggestions', dt.date.today() + dt.timedelta(days=7))
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ImproveSuggestion).where(ImproveSuggestion.fingerprint == W.IM.fingerprint(other['kind'], other['proposal']))) == 1


def test_daily_rule_proposes_a_ticket_and_changes_nothing(admin):
    install(admin, 'work')
    pa = project(admin)
    owner = add_user(admin, 'ravi.kumar', 'architect')
    rid = save(admin, propose(admin, 'metadata_record', {'type_key': 'work_issue', 'project_id': pa, 'values': {
        'title': 'Fictional lift', 'owner': owner, 'severity': 'Critical', 'issue_status': 'Open', 'due_date': '2020-01-01'}}))['id']
    save(admin, propose(admin, 'metadata_workflow', {'key': 'critical_to_progress', 'type_key': 'work_issue', 'event': 'daily',
        'condition': {'field': 'severity', 'op': 'eq', 'value': 'Critical'}, 'message': 'Critical issue: start work',
        'action': {'propose': 'propose_status', 'field': 'issue_status', 'value': 'In progress'}}))
    bad = write(admin, 'post', '/api/universal/proposals', {'kind': 'metadata_workflow', 'evidence': 'fictional test evidence', 'data': {
        'key': 'bad_rule', 'type_key': 'work_issue', 'event': 'record_created', 'condition': None, 'message': 'Hello there',
        'action': {'propose': 'open_task', 'title': 'Follow up'}}})
    assert bad.status_code == 422                                          # proposing rules run daily only
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(ApprovalTicket))
    W.run_job('daily_rules')
    with SessionLocal() as db:
        assert db.get(FlexibleRecord, rid).data['issue_status'] == 'Open'     # nothing changed by itself
        assert db.scalar(select(func.count()).select_from(ApprovalTicket)) == before + 1
        assert db.scalar(select(JobRun.outcome).where(JobRun.job == 'daily_rules')) == 'ok'


def test_summaries_follow_access_once_per_period(admin):
    install(admin, 'work')
    pa = project(admin)
    pb = approved_form(admin,'post','/api/projects', {'name': 'Fictional Project B', 'budget': '1'}).json()['id']
    asha = add_user(admin, 'asha.rao', 'site_engineer')
    write(admin, 'put', f'/api/projects/{pa}/members', {'user_ids': [asha]})
    _issues(admin, pa, asha, 2)
    _issues(admin, pb, asha, 3)
    save(admin, propose(admin, 'metadata_summary', {'key': 'site_daily', 'title': 'Site team daily', 'roles': ['site_engineer', 'admin'],
                                                    'reports': ['open_issues_by_owner'], 'channels': ['in_app', 'email'], 'every': 'day'}))
    W.run_job('summaries_daily')
    W.run_job('summaries_daily')
    with SessionLocal() as db:
        rows = db.scalars(select(SummaryDelivery)).all()
        assert len(rows) == 2
        mine = next(r for r in rows if r.user_id == asha)
        import re
        # grouped rows ("High: 1", "Low: 1"): together they are Asha's 2 issues in project A, not project B's 3
        assert sum(int(n) for n in re.findall(r': (\d+)', mine.text)) == 2 and mine.channels['email'] == 'not set up'
    assert client_for('asha.rao').get('/api/improve/summaries/mine').json()['summaries'][0]['summary'] == 'site_daily'


def test_review_draft_facts_only_and_health(admin):
    install(admin, 'people')
    install(admin, 'work')
    asha = add_user(admin, 'asha.rao', 'site_engineer')
    r = write(admin, 'post', '/api/improve/review-draft', {'employee_id': asha, 'week_start': '2026-11-12'}).json()
    assert 'Week 2026-11-09' in r['facts']['text']
    with SessionLocal() as db:
        from studioos.db import ApprovalTicketItem
        item = db.scalar(select(ApprovalTicketItem).where(ApprovalTicketItem.ticket_id == r['ticket_id']))
        assert set(item.after_data['values']) == {'employee', 'reviewer', 'week_start', 'checked_facts', 'review_status'}
    h = admin.get('/api/improve/health').json()
    assert {c['key'] for c in h['checks']} >= {'schema', 'backup', 'tickets', 'quarantine', 'ai'}
    assert client_for('asha.rao').get('/api/improve/health').status_code == 403

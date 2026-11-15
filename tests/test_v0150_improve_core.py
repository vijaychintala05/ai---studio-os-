"""v0.15.0 self-improvement, database-free part (standard library only). Fictional data only."""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stdlib_loader import load, ROOT  # noqa: E402
from views_world import build_records, packs, Resolver, catalog, TODAY  # noqa: E402

G, IM, L, V = load('graph_core', 'improve_core', 'ai_learning', 'views_core')
ALIASES = {k: t.get('aliases', []) for k, t in packs()[0].items()}
TYPES = {k: {'title': t['title'], 'fields': t['fields'], 'label_field': t.get('label_field')} for k, t in packs()[0].items()}


def recs():
    return [{'id': i, 'type': r['type'], 'data': dict(r['values'])} for i, r in build_records().items()]


# ------------------------------------------------------------------ suggestions

def test_repeated_notes_suggest_an_option_field_with_evidence():
    rs = recs()
    ts = [r for r in rs if r['type'] == 'timesheet_entry']
    for i, r in enumerate(ts[:12]):
        r['data']['note'] = ['Waiting for client approval', 'waiting for client approval!', 'Material delay'][i % 3]
    s = IM.note_field_suggestions(TYPES, rs)
    hit = next(x for x in s if x['type_key'] == 'timesheet_entry' and x['field'] == 'note')
    assert hit['evidence']['values'] == {'waiting for client approval': 8}          # "Material delay" only 4 times
    f = hit['proposal']['data']['fields'][0]
    assert hit['proposal']['kind'] == 'metadata_type_extend' and f['type'] == 'enum' and f['options'] == ['Waiting for client approval']
    G.check_field_specs([f])


def test_mostly_empty_fields_suggest_hiding_never_required_or_label():
    rs = recs()
    s = IM.empty_field_suggestions(TYPES, rs)
    fields = {(x['type_key'], x['field']) for x in s}
    assert ('work_issue', 'resolution') in fields and ('work_issue', 'raised_by') in fields
    assert all(not next(f for f in TYPES[t]['fields'] if f['name'] == n).get('required') for t, n in fields)
    one = next(x for x in s if x['field'] == 'resolution')
    assert one['proposal'] == {'kind': 'metadata_type_change', 'data': {'op': 'remove_field', 'type_key': 'work_issue', 'field': 'resolution'}}
    assert one['evidence']['empty'] == one['evidence']['records'] == 30


def test_repeated_questions_and_corrections():
    cat = catalog()
    q = V.offline_question('Open issues by owner', cat, TODAY, ALIASES)
    qs = [{'text': t, 'report': q} for t in ('Open issues by owner', 'open issues by owner?', 'Open issues by owner')]
    s = IM.question_suggestions(qs)
    assert len(s) == 1 and s[0]['proposal']['kind'] == 'metadata_report' and s[0]['proposal']['data']['key'] == 'open_issues_by_owner'
    G.check_report(cat, {k: v for k, v in s[0]['proposal']['data'].items() if k in G.REPORT_KEYS})
    assert IM.question_suggestions(qs[:2]) == []
    assert IM.question_suggestions(qs, saved_titles=['Open issues by owner']) == []
    rows = [{'id': i, **L.correction_row('t', {'name': 'staff', 'type': 'reference', 'target': 'system.user'}, 'RK', 12, 11)} for i in range(4)]
    a = IM.alias_suggestions(L.alias_suggestions(rows))
    assert a[0]['proposal'] == {'kind': 'metadata_alias', 'data': {'kind': 'staff', 'alias': 'RK', 'target_id': 11}}


def test_at_most_five_a_week_and_dismissed_never_again():
    cands = [{'kind': 'hide_empty_field', 'title': str(i), 'evidence': {}, 'weight': i,
              'proposal': {'kind': 'x', 'data': {'i': i}}} for i in range(9)]
    week = IM.weekly_suggestions(cands)
    assert len(week) == 5 and [w['weight'] for w in week] == [8, 7, 6, 5, 4]
    gone = {week[0]['fingerprint']}
    nxt = IM.weekly_suggestions(cands, dismissed=gone, already={week[1]['fingerprint']})
    assert week[0]['fingerprint'] not in [w['fingerprint'] for w in nxt] and week[1]['fingerprint'] not in [w['fingerprint'] for w in nxt]


# ------------------------------------------------------------------ summaries

def test_summary_definitions_and_text_follow_access():
    d = IM.check_summary({'key': 'site_daily', 'title': 'Site team daily', 'roles': ['site_engineer'], 'reports': ['open_issues_by_owner'],
                          'channels': ['in_app', 'email'], 'every': 'day'}, {'open_issues_by_owner'})
    for bad in ({**d, 'reports': ['nope']}, {**d, 'channels': ['sms']}, {**d, 'roles': [], 'user_ids': []}, {**d, 'every': 'hour'}, {**d, 'sql': 1}):
        with pytest.raises(G.GraphError):
            IM.check_summary(bad, {'open_issues_by_owner'})
    users = [{'id': 1, 'role': 'site_engineer', 'active': True}, {'id': 2, 'role': 'site_engineer', 'active': False},
             {'id': 3, 'role': 'architect', 'active': True}]
    assert [u['id'] for u in IM.recipients(d, users)] == [1]
    cat, res, records = catalog(), None, build_records()
    full = Resolver(records, cat)
    mine = Resolver({i: r for i, r in records.items() if r.get('project_id') == 1}, cat)   # a person on project 1 only
    rep = V.offline_question('Open issues by owner', cat, TODAY, ALIASES)
    a, b = V.run(full, cat, rep, TODAY), V.run(mine, cat, rep, TODAY)
    text_all, text_mine = IM.summary_text('Daily', 'Admin', [a], TODAY), IM.summary_text('Daily', 'Asha', [b], TODAY)
    assert a['matched'] > b['matched'] and text_all != text_mine and 'Only what you are allowed to see' in text_mine
    s = IM.FakeSender()
    s.send('asha@fictional.example', 'Daily', text_mine)
    assert s.sent[0]['to'] == 'asha@fictional.example'
    assert not IM.SmtpSender(environ={}).configured()


# ------------------------------------------------------------------ weekly review draft

def test_weekly_review_draft_has_facts_only():
    rs = build_records()
    data = lambda t: [{'data': r['values']} for r in rs.values() if r['type'] == t]
    start, _ = IM.week_of(TODAY)
    sop = [{'data': {'performed_by': 14, 'run_date': '2026-11-11', 'outcome': 'Completed with deviations'}},
           {'data': {'performed_by': 14, 'run_date': '2026-11-12', 'outcome': 'Completed'}},
           {'data': {'performed_by': 11, 'run_date': '2026-11-12', 'outcome': 'Completed'}}]
    f = IM.review_facts(14, start, data('attendance_entry'), data('timesheet_entry'), data('work_issue'), sop, TODAY)
    want_hours = sum(G.as_number(r['values']['hours']) for r in rs.values() if r['type'] == 'timesheet_entry'
                     and r['values']['employee'] == 14 and start.isoformat() <= r['values']['work_date'] <= TODAY.isoformat())
    assert G.as_number(f['numbers']['hours']) == want_hours
    assert f['numbers']['attendance_days'] == 6 and f['numbers']['sop_runs'] == 2 and f['numbers']['sop_deviations'] == 1
    v = IM.review_draft_values(14, 1, start, f)
    assert set(v) == {'employee', 'reviewer', 'week_start', 'checked_facts', 'review_status'} and v['review_status'] == 'Draft'
    for word in ('good', 'poor', 'excellent', 'rating'):
        assert word not in f['text'].lower()


# ------------------------------------------------------------------ rules that propose

def test_rule_actions_are_proposals_never_writes():
    fields = G.field_map(TYPES['work_issue']['fields'])
    for ok in ('notify', {'propose': 'propose_status', 'field': 'issue_status', 'value': 'In progress'},
               {'propose': 'open_task', 'title': 'Follow up: {title}', 'due_in_days': 2},
               {'propose': 'draft_record', 'type_key': 'meeting_note', 'values': {'decisions': '{title}', 'meeting_type': 'Site'}}):
        IM.check_rule_action(ok, fields, TYPES)
    for bad in ({'propose': 'delete_record'}, {'propose': 'propose_status', 'field': 'issue_status', 'value': 'Gone'},
                {'propose': 'open_task', 'title': 'x {nope}'}, {'propose': 'draft_record', 'type_key': 'gl_lines', 'values': {}},
                {'propose': 'open_task', 'title': 'Call', 'due_in_days': 400}, 'run_sql'):
        with pytest.raises(G.GraphError):
            IM.check_rule_action(bad, fields, TYPES)
    rec = {'id': 7, 'type': 'work_issue', 'version': 2, 'project_id': 1, 'project_name': 'Fictional Tower',
           'data': {'title': 'Lift not working', 'issue_status': 'Open', 'severity': 'High', 'owner': 11}}
    st = IM.rule_proposal({'propose': 'propose_status', 'field': 'issue_status', 'value': 'In progress'}, rec, TODAY)
    assert st['kind'] == 'metadata_record_update' and st['data']['values']['issue_status'] == 'In progress' and st['data']['expected_version'] == 2
    assert IM.rule_proposal({'propose': 'propose_status', 'field': 'issue_status', 'value': 'Open'}, rec, TODAY) is None
    t = IM.rule_proposal({'propose': 'open_task', 'title': 'Follow up: {title}', 'due_in_days': 2}, rec, TODAY)
    assert t == {'kind': 'create_task', 'data': {'project': 'Fictional Tower', 'title': 'Follow up: Lift not working', 'due_date': '2026-11-16'}}
    dr = IM.rule_proposal({'propose': 'draft_record', 'type_key': 'meeting_note', 'values': {'decisions': '{title}', 'meeting_type': 'Site'}}, rec, TODAY)
    assert dr['data']['values'] == {'decisions': 'Lift not working', 'meeting_type': 'Site'}


# ------------------------------------------------------------------ scheduler and self-check

def test_scheduler_runs_each_job_once_per_period():
    mon7 = dt.datetime(2026, 11, 16, 7, 5)
    assert set(IM.due_jobs(mon7, {})) == set(IM.JOBS)
    done = {j: mon7 for j in IM.JOBS}
    assert IM.due_jobs(mon7 + dt.timedelta(minutes=30), done) == []
    assert IM.due_jobs(mon7 + dt.timedelta(hours=1), done) == ['email_poll']
    tue6 = dt.datetime(2026, 11, 17, 6, 0)
    assert IM.due_jobs(tue6, done) == ['email_poll']                    # daily jobs wait for 07:00
    tue8 = dt.datetime(2026, 11, 17, 8, 0)
    assert set(IM.due_jobs(tue8, done)) == {'email_poll', 'daily_rules', 'summaries_daily'}
    sun = dt.datetime(2026, 11, 15, 9, 0)
    assert 'suggestions' not in IM.due_jobs(sun, {'suggestions': dt.datetime(2026, 11, 9, 7, 30)})
    assert 'suggestions' in IM.due_jobs(dt.datetime(2026, 11, 16, 9, 0), {'suggestions': dt.datetime(2026, 11, 9, 7, 30)})


def test_self_check_levels():
    now = dt.datetime(2026, 11, 14, 10, 0)
    good = {'schema_version': 26, 'latest_version': 26, 'backup': {'overall': 'pass', 'summary': 'Backed up 2 hours ago'},
            'job_runs': {j: now - dt.timedelta(hours=1) for j in IM.JOBS}, 'email_configured': True, 'tickets_waiting': 2,
            'tickets_waiting_over_3_days': 0, 'quarantined': 0, 'ai': {'on': False}, 'disk_free_mb': 50000, 'ocr': True}
    assert {c['level'] for c in IM.health(good, now)} == {'ok'}
    bad = {**good, 'schema_version': 25, 'backup': {}, 'job_runs': {'daily_rules': now - dt.timedelta(days=3)}, 'quarantined': 2,
           'ai': {'on': True, 'spent_usd': '4.90', 'cap_usd': '5'}, 'disk_free_mb': 100, 'ocr': False, 'tickets_waiting_over_3_days': 4}
    levels = {c['key']: c['level'] for c in IM.health(bad, now)}
    assert levels['schema'] == 'fail' and levels['backup'] == 'fail' and levels['job_daily_rules'] == 'fail'
    assert levels['job_suggestions'] == 'warn' and levels['quarantine'] == 'warn' and levels['ai'] == 'warn'
    assert levels['disk'] == 'fail' and levels['ocr'] == 'warn' and levels['tickets'] == 'warn'
    assert all(c['action'] for c in IM.health(bad, now) if c['level'] == 'fail')

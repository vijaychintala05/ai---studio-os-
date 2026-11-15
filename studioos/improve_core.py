"""v0.15.0 self-improvement. Standard library only (the app hands it plain data).

* Weekly suggestions with evidence: repeated note values -> a new option field; mostly empty fields
  -> hide the field; repeated questions -> a saved report; repeated corrections -> another name.
  At most 5 a week; a dismissed suggestion is never shown again. Every suggestion only opens a
  ticket when a person accepts it.
* Summaries per person or role, built with that person's access, delivered in the app and (when
  set up) by e-mail or WhatsApp through pluggable senders.
* A weekly review draft from the week's attendance, timesheets, issues and SOP runs. Only checked
  facts are filled; achievements, improvements and rating are left to the manager.
* Rules may PROPOSE: a draft record, a status change or a follow-up task, each as a ticket.
* A server-side scheduler decides which jobs are due; a self-check lists what needs attention.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections import Counter, defaultdict
from decimal import Decimal

try:
    from . import graph_core as G
except ImportError:                       # stand-alone (stdlib tests)
    import graph_core as G                # type: ignore

MAX_PER_WEEK = 5
NOTE_REPEAT = 5            # the same short note this often -> suggest an option field
EMPTY_SHARE = Decimal('0.9')
EMPTY_MIN_RECORDS = 20
QUESTION_REPEAT = 3


def fingerprint(kind: str, data: dict) -> str:
    return hashlib.sha256((kind + '\x00' + json.dumps(data, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()[:40]


def _norm(s) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', str(s or '').casefold())).strip()


# ------------------------------------------------------------------ weekly suggestions

def note_field_suggestions(types: dict, records: list[dict]) -> list[dict]:
    """types: {key: {'title','fields'}}; records: [{'id','type','data'}]."""
    out = []
    for key, t in types.items():
        recs = [r for r in records if r['type'] == key]
        for f in t['fields']:
            if f['type'] != 'text':
                continue
            vals = [_norm(r['data'].get(f['name'])) for r in recs if r['data'].get(f['name'])]
            vals = [v for v in vals if 2 <= len(v) <= 40]
            common = [(v, n) for v, n in Counter(vals).most_common(8) if n >= NOTE_REPEAT]
            if len(common) >= 1:
                options = [v.capitalize() for v, _ in common][:8]
                ids = [r['id'] for r in recs if _norm(r['data'].get(f['name'])) in {v for v, _ in common}][:20]
                out.append({'kind': 'note_to_field', 'type_key': key, 'field': f['name'],
                            'title': f'{t["title"]}: "{f.get("meaning") or f["name"]}" often says the same thing',
                            'evidence': {'values': {v: n for v, n in common}, 'record_ids': ids},
                            'proposal': {'kind': 'metadata_type_extend', 'data': {'type_key': key, 'fields': [
                                {'name': (f['name'] + '_kind')[:60], 'type': 'enum', 'required': False,
                                 'meaning': f'{(f.get("meaning") or f["name"]).capitalize()} (choice)', 'options': options}]}},
                            'weight': sum(n for _, n in common)})
    return out


def empty_field_suggestions(types: dict, records: list[dict]) -> list[dict]:
    out = []
    for key, t in types.items():
        recs = [r for r in records if r['type'] == key]
        if len(recs) < EMPTY_MIN_RECORDS:
            continue
        for f in t['fields']:
            if f.get('required') or f['name'] == t.get('label_field'):
                continue
            empty = sum(1 for r in recs if r['data'].get(f['name']) in (None, '', [], {}))
            if Decimal(empty) / len(recs) >= EMPTY_SHARE:
                out.append({'kind': 'hide_empty_field', 'type_key': key, 'field': f['name'],
                            'title': f'{t["title"]}: "{f.get("meaning") or f["name"]}" is almost never filled in',
                            'evidence': {'empty': empty, 'records': len(recs)},
                            'proposal': {'kind': 'metadata_type_change', 'data': {'op': 'remove_field', 'type_key': key, 'field': f['name']}},
                            'weight': empty})
    return out


def question_suggestions(questions: list[dict], saved_titles=()) -> list[dict]:
    """questions: [{'text', 'report'}] — the report definition each answered question became."""
    groups = defaultdict(list)
    for q in questions:
        if q.get('report'):
            groups[json.dumps({k: v for k, v in q['report'].items() if k not in ('key', 'title')}, sort_keys=True)].append(q)
    saved = {_norm(t) for t in saved_titles}
    out = []
    for sig, qs in groups.items():
        if len(qs) < QUESTION_REPEAT:
            continue
        title = qs[-1]['text'].strip().rstrip('?')[:120]
        if _norm(title) in saved:
            continue
        rep = dict(qs[-1]['report'])
        rep['key'] = re.sub(r'[^a-z0-9]+', '_', title.casefold()).strip('_')[:50] or 'saved_question'
        if not re.match(r'^[a-z]', rep['key']):
            rep['key'] = 'q_' + rep['key']
        rep['title'] = title[:1].upper() + title[1:]
        out.append({'kind': 'question_to_report', 'title': f'"{rep["title"]}" was asked {len(qs)} times',
                    'evidence': {'asked': len(qs), 'examples': [q['text'] for q in qs[-3:]]},
                    'proposal': {'kind': 'metadata_report', 'data': rep}, 'weight': len(qs)})
    return out


def alias_suggestions(alias_items: list[dict]) -> list[dict]:
    """alias_items: ai_learning.alias_suggestions output."""
    return [{'kind': 'correction_to_alias', 'title': f'"{a["data"]["alias"]}" was corrected the same way {a["times"]} times',
             'evidence': {'times': a['times'], 'correction_ids': a.get('evidence_ids', [])[:20]},
             'proposal': {'kind': 'metadata_alias', 'data': a['data']}, 'weight': a['times']} for a in alias_items]


def weekly_suggestions(candidates: list[dict], dismissed=frozenset(), already=frozenset(), limit: int = MAX_PER_WEEK) -> list[dict]:
    """The strongest suggestions not dismissed and not already open, at most ``limit``."""
    out = []
    for c in sorted(candidates, key=lambda c: -c['weight']):
        fp = fingerprint(c['kind'], c['proposal'])
        if fp in dismissed or fp in already or any(o['fingerprint'] == fp for o in out):
            continue
        out.append({**c, 'fingerprint': fp})
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------ summaries

SUMMARY_KEYS = {'key', 'title', 'roles', 'user_ids', 'reports', 'channels', 'every'}
CHANNELS = ('in_app', 'email', 'whatsapp')


def check_summary(d: dict, report_keys) -> dict:
    if not isinstance(d, dict) or set(d) - SUMMARY_KEYS or not {'key', 'title', 'reports', 'channels', 'every'} <= set(d):
        raise G.GraphError('A summary needs key, title, reports, channels and how often')
    G.check_key(d['key'], 'Summary key')
    if not isinstance(d['title'], str) or not 2 <= len(d['title']) <= 80:
        raise G.GraphError('Summary title 2–80 characters')
    roles, users = d.get('roles') or [], d.get('user_ids') or []
    if not roles and not users:
        raise G.GraphError('Say who receives it (roles or people)')
    if any(r not in G.ROLES for r in roles) or any(type(u) is not int for u in users):
        raise G.GraphError('Unknown role or person')
    if not isinstance(d['reports'], list) or not 1 <= len(d['reports']) <= 6 or any(r not in report_keys for r in d['reports']):
        raise G.GraphError('1–6 saved reports')
    if not isinstance(d['channels'], list) or not d['channels'] or any(c not in CHANNELS for c in d['channels']):
        raise G.GraphError('Channels: in_app, email, whatsapp')
    if d['every'] not in ('day', 'week'):
        raise G.GraphError('Every day or every week')
    return d


def summary_text(title: str, person: str, results: list[dict], today: dt.date) -> str:
    """Plain text built from report results (already limited to the person's access)."""
    lines = [f'{title} — {today.strftime("%d %b %Y")}', f'For {person}', '']
    for r in results:
        lines.append(r['title'])
        if r.get('error'):
            lines.append('  (could not be prepared: ' + r['error'][:120] + ')')
        elif r.get('mode') == 'figure':
            lines += [f'  {f["label"]}: {f["value"]}' for f in r['figures']]
        elif r.get('mode') == 'grouped':
            lines += [f'  {" · ".join(x["group"])}: {", ".join(x["values"])}' for x in r['rows'][:10]]
            if len(r['rows']) > 10:
                lines.append(f'  … and {len(r["rows"]) - 10} more')
            if not r['rows']:
                lines.append('  nothing')
        else:
            lines += [f'  {x["label"]}' for x in r.get('rows', [])[:10]] or ['  nothing']
        lines.append('')
    lines.append('Only what you are allowed to see. Open StudioOS for details.')
    return '\n'.join(lines)[:4000]


def recipients(d: dict, users: list[dict]) -> list[dict]:
    """users: [{'id','role','active','name','email','phone'}]"""
    return [u for u in users if u['active'] and (u['role'] in (d.get('roles') or []) or u['id'] in (d.get('user_ids') or []))]


class FakeSender:
    """E-mail or WhatsApp sender for tests."""

    def __init__(self, ok=True):
        self.sent, self.ok = [], ok

    def configured(self):
        return True

    def send(self, to: str, subject: str, text: str):
        if not self.ok:
            raise OSError('fictional delivery failure')
        self.sent.append({'to': to, 'subject': subject, 'text': text})


class SmtpSender:
    """E-mail through the firm's SMTP server (STUDIOOS_SMTP_HOST/_PORT/_USER/_PASSWORD/_FROM, TLS).
    Off unless configured. Not exercised in the sandbox (no network)."""

    def __init__(self, environ=None):
        import os
        env = os.environ if environ is None else environ
        self.host, self.port = env.get('STUDIOOS_SMTP_HOST', ''), int(env.get('STUDIOOS_SMTP_PORT', '587') or 587)
        self.user, self.password, self.sender = env.get('STUDIOOS_SMTP_USER', ''), env.get('STUDIOOS_SMTP_PASSWORD', ''), env.get('STUDIOOS_SMTP_FROM', '')

    def configured(self):
        return bool(self.host and self.sender)

    def send(self, to, subject, text):
        import smtplib
        from email.message import EmailMessage
        m = EmailMessage()
        m['From'], m['To'], m['Subject'] = self.sender, to, subject
        m.set_content(text)
        with smtplib.SMTP(self.host, self.port, timeout=20) as s:
            s.starttls()
            if self.user:
                s.login(self.user, self.password)
            s.send_message(m)


class NoSender:
    def configured(self):
        return False

    def send(self, to, subject, text):
        raise OSError('Not set up')


# ------------------------------------------------------------------ weekly review draft

def week_of(day: dt.date) -> tuple[dt.date, dt.date]:
    start = day - dt.timedelta(days=day.weekday())
    return start, start + dt.timedelta(days=6)


def review_facts(employee_id: int, week_start: dt.date, attendance: list[dict], timesheets: list[dict], issues: list[dict],
                 sop_runs: list[dict], today: dt.date) -> dict:
    """Checked facts for one person and one week, from records (each list: [{'data': {...}}]).
    Returns {'text': plain facts, 'numbers': {...}}. No judgement words are produced here."""
    end = week_start + dt.timedelta(days=6)
    inweek = lambda d: d and week_start.isoformat() <= str(d)[:10] <= end.isoformat()
    att = [a['data'] for a in attendance if a['data'].get('employee') == employee_id and inweek(a['data'].get('attendance_date'))]
    status = Counter(a.get('attendance_status') for a in att)
    ts = [t['data'] for t in timesheets if t['data'].get('employee') == employee_id and inweek(t['data'].get('work_date'))]
    hours = sum((G.as_number(t.get('hours')) or Decimal(0) for t in ts), Decimal(0))
    by_act = defaultdict(Decimal)
    for t in ts:
        by_act[t.get('activity') or 'Other'] += G.as_number(t.get('hours')) or Decimal(0)
    mine = [i['data'] for i in issues if i['data'].get('owner') == employee_id]
    open_ = [i for i in mine if i.get('issue_status') in ('Open', 'In progress')]
    overdue = [i for i in open_ if i.get('due_date') and str(i['due_date']) < today.isoformat()]
    closed = [i for i in mine if i.get('issue_status') in ('Resolved', 'Closed')]
    runs = [r['data'] for r in sop_runs if r['data'].get('performed_by') == employee_id and inweek(r['data'].get('run_date'))]
    devi = [r for r in runs if 'deviation' in (r.get('outcome') or '').casefold() or r.get('deviations')]
    fmt = lambda n: format(n.normalize() if n == n.to_integral() else n, 'f')
    lines = [f'Week {week_start.isoformat()} to {end.isoformat()} (facts from StudioOS records):',
             f'- Attendance: {len(att)} day(s) recorded' + (': ' + ', '.join(f'{k} {v}' for k, v in sorted(status.items(), key=lambda x: str(x[0]))) if att else ''),
             f'- Timesheets: {fmt(hours)} hour(s) in {len(ts)} entr{"y" if len(ts) == 1 else "ies"}' +
             (' (' + ', '.join(f'{k} {fmt(v)}' for k, v in sorted(by_act.items())) + ')' if ts else ''),
             f'- Issues owned: {len(open_)} open ({len(overdue)} past due), {len(closed)} resolved or closed',
             f'- SOP runs: {len(runs)}, with deviations: {len(devi)}']
    return {'text': '\n'.join(lines), 'numbers': {'attendance_days': len(att), 'hours': fmt(hours), 'timesheet_entries': len(ts),
                                                  'issues_open': len(open_), 'issues_overdue': len(overdue),
                                                  'issues_closed': len(closed), 'sop_runs': len(runs), 'sop_deviations': len(devi)}}


def review_draft_values(employee_id: int, reviewer_id: int, week_start: dt.date, facts: dict) -> dict:
    """The weekly_review draft: facts only; judgement fields stay empty for the manager."""
    return {'employee': employee_id, 'reviewer': reviewer_id, 'week_start': week_start.isoformat(),
            'checked_facts': facts['text'], 'review_status': 'Draft'}


# ------------------------------------------------------------------ rules that propose

PROPOSE_KINDS = ('draft_record', 'propose_status', 'open_task')


def check_rule_action(action, fields: dict, types: dict) -> dict:
    """'notify' (v0.10.0) or {'propose': kind, ...}:
       draft_record   {'type_key', 'values': {field: value or '{field}' copied from the record}}
       propose_status {'field': option field of the record, 'value': option}
       open_task      {'title': text with {field} placeholders, 'due_in_days': 0-60}"""
    if action == 'notify' or action is None:
        return {'kind': 'notify'}
    if not isinstance(action, dict) or action.get('propose') not in PROPOSE_KINDS:
        raise G.GraphError('A rule notifies, or proposes a draft record, a status change or a follow-up task')
    k = action['propose']
    if k == 'propose_status':
        if set(action) != {'propose', 'field', 'value'}:
            raise G.GraphError('A status proposal names the field and the new value')
        f = fields.get(action['field'])
        if not f or f['type'] != 'enum' or action['value'] not in f['options']:
            raise G.GraphError('Choose an option field and one of its options')
    elif k == 'open_task':
        if set(action) - {'propose', 'title', 'due_in_days'} or not isinstance(action.get('title'), str) or not 3 <= len(action['title']) <= 200:
            raise G.GraphError('A follow-up task needs a title (3–200 characters)')
        for name in re.findall(r'\{(\w+)\}', action['title']):
            if name not in fields:
                raise G.GraphError(f'Unknown field in the title: {name}')
        d = action.get('due_in_days', 3)
        if type(d) is not int or not 0 <= d <= 60:
            raise G.GraphError('due_in_days is 0–60')
    else:
        if set(action) != {'propose', 'type_key', 'values'} or action['type_key'] not in types or not isinstance(action['values'], dict):
            raise G.GraphError('A draft record names an existing type and its values')
        target = G.field_map(types[action['type_key']]['fields'])
        for name, v in action['values'].items():
            if name not in target:
                raise G.GraphError(f'{name} is not a field of {action["type_key"]}')
            if isinstance(v, str) and re.fullmatch(r'\{(\w+)\}', v) and v[1:-1] not in fields:
                raise G.GraphError(f'Unknown field to copy: {v}')
    return dict(action)


def rule_proposal(action: dict, record: dict, today: dt.date) -> dict | None:
    """The ticket item a matching record leads to (never a direct write)."""
    k = action.get('propose')
    data = record['data']
    if k == 'propose_status':
        if data.get(action['field']) == action['value']:
            return None
        return {'kind': 'metadata_record_update', 'data': {'record_id': record['id'], 'type_key': record['type'],
                'expected_version': record.get('version', 1), 'project_id': record.get('project_id'),
                'values': {**data, action['field']: action['value']}}}
    if k == 'open_task':
        title = re.sub(r'\{(\w+)\}', lambda m: str(data.get(m.group(1), ''))[:60], action['title'])[:200]
        return {'kind': 'create_task', 'data': {'project': record.get('project_name') or '', 'title': title,
                'due_date': (today + dt.timedelta(days=action.get('due_in_days', 3))).isoformat()}}
    if k == 'draft_record':
        vals = {n: (data.get(v[1:-1]) if isinstance(v, str) and re.fullmatch(r'\{(\w+)\}', v) else v) for n, v in action['values'].items()}
        return {'kind': 'metadata_record', 'data': {'type_key': action['type_key'], 'project_id': record.get('project_id'),
                'values': {k2: v for k2, v in vals.items() if v is not None}}}
    return None


# ------------------------------------------------------------------ the scheduler

JOBS = {'daily_rules': 'day', 'email_poll': 'hour', 'summaries_daily': 'day', 'summaries_weekly': 'week', 'suggestions': 'week'}


def due_jobs(now: dt.datetime, last_runs: dict, hour: int = 7) -> list[str]:
    """Which jobs should run now. Daily jobs after ``hour`` (local time) once a day; weekly jobs on
    Monday after ``hour``; e-mail every hour. last_runs: {job: datetime of the last finished run}."""
    out = []
    for job, every in JOBS.items():
        last = last_runs.get(job)
        if every == 'hour':
            if last is None or now - last >= dt.timedelta(minutes=55):
                out.append(job)
        elif every == 'day':
            if now.hour >= hour and (last is None or last.date() < now.date()):
                out.append(job)
        else:
            monday = (now - dt.timedelta(days=now.weekday())).date()
            if (now.weekday() > 0 or now.hour >= hour) and (last is None or last.date() < monday):
                out.append(job)
    return out


# ------------------------------------------------------------------ self-check

def health(facts: dict, now: dt.datetime) -> list[dict]:
    """facts: the numbers the app gathers. Returns checks with level ok / warn / fail and what to do."""
    out = []

    def add(key, title, level, detail, action=''):
        out.append({'key': key, 'title': title, 'level': level, 'detail': detail, 'action': action})
    sv, lv = facts.get('schema_version'), facts.get('latest_version')
    add('schema', 'Database version', 'ok' if sv == lv else 'fail', f'{sv} of {lv}', '' if sv == lv else 'Restart StudioOS to finish the upgrade')
    b = facts.get('backup') or {}
    ok_b = b.get('overall') in ('ok', 'pass')
    add('backup', 'Backups', 'ok' if ok_b else ('warn' if b.get('overall') == 'warn' else 'fail'), b.get('summary') or 'No backup status',
        '' if ok_b else 'Open Data safety')
    for job, every in JOBS.items():
        last = (facts.get('job_runs') or {}).get(job)
        limit = {'hour': dt.timedelta(hours=3), 'day': dt.timedelta(hours=30), 'week': dt.timedelta(days=8)}[every]
        if job == 'email_poll' and not facts.get('email_configured'):
            continue
        if last is None:
            add('job_' + job, f'Scheduled job: {job.replace("_", " ")}', 'warn', 'Has not run yet', 'Check that the scheduler is on')
        else:
            age = now - last
            add('job_' + job, f'Scheduled job: {job.replace("_", " ")}', 'ok' if age <= limit else 'fail',
                f'Last run {int(age.total_seconds() // 3600)} hour(s) ago', '' if age <= limit else 'Check the scheduler and the server clock')
    failed = facts.get('job_failures') or 0
    add('job_errors', 'Job errors this week', 'ok' if not failed else 'warn', f'{failed} failed run(s)', 'See the list below' if failed else '')
    old = facts.get('tickets_waiting_over_3_days') or 0
    add('tickets', 'Tickets waiting', 'ok' if old == 0 else 'warn', f'{facts.get("tickets_waiting", 0)} waiting, {old} for more than 3 days',
        'Open Approvals' if old else '')
    q = facts.get('quarantined') or 0
    add('quarantine', 'Unknown senders', 'ok' if q == 0 else 'warn', f'{q} message(s) in quarantine', 'Open Inbox' if q else '')
    ai = facts.get('ai') or {}
    if ai.get('on'):
        spent, cap = Decimal(ai.get('spent_usd', '0')), Decimal(ai.get('cap_usd', '0'))
        level = 'ok' if cap and spent < cap * Decimal('0.8') else ('warn' if spent < cap else 'fail')
        add('ai', 'AI spending this month', level, f'${spent} of ${cap}', '' if level == 'ok' else 'Raise the cap or expect the offline reader')
    else:
        add('ai', 'AI model', 'ok', 'Off: the offline reader is used')
    free = facts.get('disk_free_mb')
    if free is not None:
        add('disk', 'Free disk space', 'ok' if free >= 2048 else ('warn' if free >= 512 else 'fail'), f'{free:,} MB free',
            '' if free >= 2048 else 'Free space on the NAS')
    add('ocr', 'Reading photos (OCR)', 'ok' if facts.get('ocr') else 'warn', 'Available' if facts.get('ocr') else 'Not installed: photos wait for a person')
    s = facts.get('open_suggestions') or 0
    add('suggestions', 'Suggestions to look at', 'ok', f'{s} open')
    return out

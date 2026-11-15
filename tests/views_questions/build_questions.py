"""Writes questions_v1.json: 50 fictional questions about the firm in tests/views_world.py, each with
its expected answer computed HERE by plain Python over the records (not by the report planner), so
the planner is checked against an independent count. 'ask' means the right answer is to ask back.

Answer forms: {'figure': '12'}, {'groups': {'Asha Rao': '5', ...}} (a group of two parts is joined
with ' · '), {'ids': [record ids]} for lists, {'ask': True}."""
import datetime as dt
import json
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from views_world import world, STAFF, PROJECTS, TODAY  # noqa: E402

cat, res, R = world()
WEEK = (TODAY - dt.timedelta(days=TODAY.weekday())).isoformat()
MONTH = TODAY.replace(day=1).isoformat()
T = TODAY.isoformat()
YEST = (TODAY - dt.timedelta(days=1)).isoformat()
L7 = (TODAY - dt.timedelta(days=7)).isoformat()


def recs(t, **eq):
    return [(i, r) for i, r in R.items() if r['type'] == t and all(r['values'].get(k) == v for k, v in eq.items())]


def num(x):
    q = Decimal(x).normalize()
    return format(q if q == q.to_integral() else Decimal(x), 'f')


def figure(n):
    return {'figure': num(n)}


def groups(rows, key, value=lambda r: 1):
    out = defaultdict(Decimal)
    for i, r in rows:
        out[key(r)] += Decimal(value(r))
    return {'groups': {k: num(v) for k, v in out.items()}}


def avg_groups(rows, key, value):
    acc = defaultdict(list)
    for i, r in rows:
        acc[key(r)].append(Decimal(value(r)))
    return {'groups': {k: num(sum(v) / len(v)) for k, v in acc.items()}}


staff = lambda f: (lambda r: STAFF[r['values'][f]])
proj = lambda r: PROJECTS[r['project_id']] if r.get('project_id') else '(none)'
opt = lambda f: (lambda r: r['values'].get(f) or '(none)')
hours = lambda r: r['values']['hours']
between = lambda f, a, b: (lambda ir: a <= ir[1]['values'].get(f, '') <= b)
Q = []


def q(text, answer, lang='en'):
    Q.append({'id': len(Q) + 1, 'lang': lang, 'question': text, 'expected': answer})


ts, iss, att, lv, ms = 'timesheet_entry', 'work_issue', 'attendance_entry', 'leave_request', 'milestone'
TS = recs(ts)
ISS = recs(iss)
ATT = recs(att)
LV = recs(lv)
MS = recs(ms)
open_iss = [x for x in ISS if x[1]['values']['issue_status'] == 'Open']
# --- counts (12)
q('How many work issues are there?', figure(len(ISS)))
q('How many open issues?', figure(len(open_iss)))
q('How many critical issues?', figure(len(recs(iss, severity='Critical'))))
q('How many issues are resolved?', figure(len(recs(iss, issue_status='Resolved'))))
q('How many timesheet entries this week?', figure(len([x for x in TS if WEEK <= x[1]['values']['work_date'] <= T])))
q('How many timesheet entries today?', figure(len([x for x in TS if x[1]['values']['work_date'] == T])))
q('How many leave requests are approved?', figure(len(recs(lv, decision='Approved'))))
q('How many milestones are delayed?', figure(len(recs(ms, milestone_status='Delayed'))))
q('How many attendance entries are absent?', figure(len(recs(att, attendance_status='Absent'))))
q('How many overdue issues?', figure(len([x for x in ISS if x[1]['values'].get('due_date') and x[1]['values']['due_date'] < T])))
q('How many overdue milestones?', figure(len([x for x in MS if x[1]['values']['due_date'] < T])))
q('kitne open issues hain?', figure(len(open_iss)), 'hi')
# --- sums and averages (10)
q('Total hours this week', figure(sum(Decimal(hours(r)) for i, r in TS if WEEK <= r['values']['work_date'] <= T)))
q('Total hours this month', figure(sum(Decimal(hours(r)) for i, r in TS if MONTH <= r['values']['work_date'] <= T)))
q('Total hours today', figure(sum((Decimal(hours(r)) for i, r in TS if r['values']['work_date'] == T), Decimal(0))))
q('Total hours by person this week', groups([x for x in TS if WEEK <= x[1]['values']['work_date'] <= T], staff('employee'), hours))
q('Total hours by project this month', groups([x for x in TS if MONTH <= x[1]['values']['work_date'] <= T], proj, hours))
q('Total hours by activity', groups(TS, opt('activity'), hours))
q('Average hours by person', avg_groups(TS, staff('employee'), hours))
q('Total hours in the last 7 days by person', groups([x for x in TS if L7 <= x[1]['values']['work_date'] <= T], staff('employee'), hours))
q('Total hours for Asha Rao this month', figure(sum((Decimal(hours(r)) for i, r in TS if r['values']['employee'] == 14 and MONTH <= r['values']['work_date'] <= T), Decimal(0))))
q('Total hours of Drawings by person', groups(recs(ts, activity='Drawings'), staff('employee'), hours))
# --- grouped counts (14)
q('Open issues by owner', groups(open_iss, staff('owner')))
q('Issues by severity', groups(ISS, opt('severity')))
q('Issues by status', groups(ISS, opt('issue_status')))
q('Issues by owner and severity', groups(ISS, lambda r: STAFF[r['values']['owner']] + ' · ' + r['values']['severity']))
q('Open issues by project', groups(open_iss, proj))
q('High issues by owner', groups(recs(iss, severity='High'), staff('owner')))
q('Attendance by status', groups(ATT, opt('attendance_status')))
q('Attendance by employee and status today', groups([x for x in ATT if x[1]['values']['attendance_date'] == T],
                                                    lambda r: STAFF[r['values']['employee']] + ' · ' + r['values']['attendance_status']))
q('Absent attendance by employee this week', groups([x for x in recs(att, attendance_status='Absent') if WEEK <= x[1]['values']['attendance_date'] <= T], staff('employee')))
q('Leave requests by leave type', groups(LV, opt('leave_type')))
q('Leave requests by employee', groups(LV, staff('employee')))
q('Milestones by status', groups(MS, opt('milestone_status')))
q('Timesheet entries by activity this week', groups([x for x in TS if WEEK <= x[1]['values']['work_date'] <= T], opt('activity')))
q('owner wise open issues', groups(open_iss, staff('owner')), 'hi')
# --- lists (8)
ids = lambda rows: {'ids': sorted(i for i, r in rows)}
q('List open critical issues', ids([x for x in open_iss if x[1]['values']['severity'] == 'Critical']))
q('Show overdue milestones', ids([x for x in MS if x[1]['values']['due_date'] < T]))
q('List leave requests that are requested', ids(recs(lv, decision='Requested')))
q('Show absent attendance today', ids([x for x in recs(att, attendance_status='Absent') if x[1]['values']['attendance_date'] == T]))
q('List delayed milestones', ids(recs(ms, milestone_status='Delayed')))
q('Show issues for Ravi Kumar', ids(recs(iss, owner=11)))
q('List sick leave requests', ids(recs(lv, leave_type='Sick')))
q('Show work issues', ids(ISS))
# --- should ask back (6)
q('How are we doing?', {'ask': True})
q('What is the profit this month?', {'ask': True})
q('Total cost by supplier', {'ask': True})
q('How many?', {'ask': True})
q('Issues by colour', {'ask': True})
q('Which project is most delayed and why', {'ask': True})
assert len(Q) == 50, len(Q)
(HERE / 'questions_v1.json').write_text(json.dumps({'version': 1, 'today': T, 'questions': Q}, indent=1) + '\n')
print('wrote', len(Q))
# ---- hold-out: written after the offline patterns were tuned on the 50 above; scored once, not tuned
Q.clear()
q('How many medium issues?', figure(len(recs(iss, severity='Medium'))))
q('How many leave requests are rejected?', figure(len(recs(lv, decision='Rejected'))))
q('Total hours yesterday', figure(sum((Decimal(hours(r)) for i, r in TS if r['values']['work_date'] == YEST), Decimal(0))))
q('Closed issues by owner', groups(recs(iss, issue_status='Closed'), staff('owner')))
q('Milestones by owner', groups(MS, staff('owner')))
q('Attendance by status this week', groups([x for x in ATT if WEEK <= x[1]['values']['attendance_date'] <= T], opt('attendance_status')))
q('Total hours of Procurement by project', groups(recs(ts, activity='Procurement'), proj, hours))
q('List planned milestones', ids(recs(ms, milestone_status='Planned')))
q('Show leave requests for Deepak Joshi', ids(recs(lv, employee=13)))
q('What did the client say?', {'ask': True})
(HERE / 'questions_holdout.json').write_text(json.dumps({'version': 1, 'today': T, 'questions': Q}, indent=1) + '\n')
print('wrote holdout', len(Q))

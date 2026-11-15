"""Writes messages_holdout.json: 20 more fictional messages, written AFTER the offline rules were
tuned on messages_v1.json and scored once, with no tuning afterwards. Same staff, projects, today."""
import json
from pathlib import Path

base = json.loads(Path(__file__).with_name('messages_v1.json').read_text())
Y, T, TM = '2026-11-13', '2026-11-14', '2026-11-15'
rows = []


def m(lang, typ, text, project=None, ask=(), **exp):
    rows.append({'id': 1000 + len(rows) + 1, 'lang': lang, 'type': typ, 'text': text, 'expected': exp, 'project': project, 'ask': list(ask)})


m('en', 'timesheet_entry', 'Please log 5.5 hours of procurement for Mohammed Irfan on 11 Nov', None, employee=16, hours='5.5', activity='Procurement', work_date='2026-11-11')
m('en', 'timesheet_entry', 'Yesterday Vijay Patil put in 7 hours on drawings for Lakeview Flat 4B', 'Lakeview Flat 4B', employee=18, hours='7', activity='Drawings', work_date=Y)
m('en', 'attendance_entry', 'Mark Shreya Nair absent for 10 Nov', None, employee=13, attendance_status='Absent', attendance_date='2026-11-10')
m('en', 'leave_request', 'Lakshmi Iyer requests sick leave 2026-11-24 to 2026-11-26', None, employee=17, leave_type='Sick', from_date='2026-11-24', to_date='2026-11-26', decision='Requested')
m('en', 'work_issue', 'Open issue, severity critical: water seepage in master bath at Sample Villa Mehta, owner Vijay Patil', 'Sample Villa Mehta', owner=18, severity='Critical', issue_status='Open')
m('en', 'milestone', 'Milestone for Demo Office Kapoor: workstations installed by 5 Dec, planned, owner Deepak Joshi', 'Demo Office Kapoor', due_date='2026-12-05', milestone_status='Planned', owner=14)
m('en', 'meeting_note', 'Vendor meeting on 13 Nov: decided to switch hinge supplier', None, meeting_date=Y, meeting_type='Vendor')
m('hi', 'timesheet_entry', 'Deepak ne kal 4 ghante procurement kiya', None, employee=14, hours='4', activity='Procurement', work_date=Y)
m('hi', 'timesheet_entry', 'Laxmi Iyer aaj 6 hours design Demo Office Kapoor', 'Demo Office Kapoor', employee=17, hours='6', activity='Design', work_date=T)
m('hi', 'attendance_entry', 'Ravi Kumar aaj site visit pe gaya', None, employee=11, attendance_status='Site visit', attendance_date=T)
m('hi', 'leave_request', 'Vijay ko 25 Nov se 27 Nov tak casual leave chahiye', None, employee=18, leave_type='Casual', from_date='2026-11-25', to_date='2026-11-27')
m('hi', 'work_issue', 'Lakeview Flat 4B me switchboard loose hai, medium, Irfan dekhega, open', 'Lakeview Flat 4B', owner=16, severity='Medium', issue_status='Open')
m('hi', 'attendance_entry', 'Ravi kal absent tha', None, ['employee'], attendance_status='Absent', attendance_date=Y)
m('hi', 'meeting_note', 'kal client meeting hui Demo Office Kapoor, carpet grey final hua', 'Demo Office Kapoor', meeting_date=Y, meeting_type='Client')
m('sh', 'timesheet_entry', 'asha 3.5 hrs drawings yday', None, employee=15, hours='3.5', activity='Drawings', work_date=Y)
m('sh', 'attendance_entry', 'deepak half day tdy', None, employee=14, attendance_status='Half day', attendance_date=T)
m('sh', 'work_issue', 'low snag lakshmi open skirting gap', None, owner=17, severity='Low', issue_status='Open')
m('sh', 'leave_request', 'shreya comp off tmrw', None, employee=13, leave_type='Comp off', from_date=TM, to_date=TM)
m('sh', 'timesheet_entry', 'irfan 2h admin today', None, employee=16, hours='2', activity='Admin', work_date=T)
m('sh', 'milestone', 'tiling delayed due 12 nov Fictional Tower', 'Fictional Tower', due_date='2026-11-12', milestone_status='Delayed')
assert len(rows) == 20
Path(__file__).with_name('messages_holdout.json').write_text(json.dumps({**base, 'messages': rows}, indent=1, ensure_ascii=False) + '\n')
print('wrote', len(rows))

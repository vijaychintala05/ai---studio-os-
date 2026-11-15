"""A fictional firm in memory (work + people packs), shaped exactly as graph_query hands nodes and
links to the report planner. Deterministic: the same records every run. Used by the v0.12.0
question set and display tests. Today is Saturday 2026-11-14."""
import datetime as dt
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stdlib_loader import ROOT, load  # noqa: E402

G = load('graph_core')
TODAY = dt.date(2026, 11, 14)
STAFF = {11: 'Ravi Kumar', 12: 'Shreya Nair', 13: 'Deepak Joshi', 14: 'Asha Rao', 15: 'Mohammed Irfan', 16: 'Lakshmi Iyer'}
PROJECTS = {1: 'Fictional Tower', 2: 'Sample Villa', 3: 'Demo Office'}


def packs():
    types, rels = {}, {}
    for pack in ('work', 'people'):
        p = json.loads((ROOT / 'studioos' / 'business_packs' / f'{pack}.json').read_text())
        for t in p['types']:
            types[t['key']] = t
        for r in p.get('relations', []):
            rels[r['key']] = {'source_type': r['source_type'], 'target_type': r['target_type']}
    return types, rels


def catalog():
    types, rels = packs()
    return G.catalog_from(types, rels)


def build_records():
    rnd = random.Random(20261114)
    recs = {}
    rid = 1000
    acts = ['Design', 'Drawings', 'Site supervision', 'Procurement', 'Client meeting', 'Admin']
    for day in range(0, 30):                                  # 2026-10-16 .. 2026-11-14
        d = (TODAY - dt.timedelta(days=day)).isoformat()
        for emp in rnd.sample(sorted(STAFF), 3):
            rid += 1
            recs[rid] = {'type': 'timesheet_entry', 'project_id': rnd.choice(sorted(PROJECTS)),
                         'values': {'employee': emp, 'work_date': d, 'hours': rnd.choice(['2', '3.5', '4', '6', '7.5', '8']),
                                    'activity': rnd.choice(acts)}}
    sev, st = ['Low', 'Medium', 'High', 'Critical'], ['Open', 'In progress', 'Resolved', 'Closed']
    for i in range(30):
        rid += 1
        due = (TODAY + dt.timedelta(days=rnd.randint(-12, 15))).isoformat() if i % 4 else None
        v = {'title': f'Fictional issue {i}', 'owner': rnd.choice(sorted(STAFF)), 'severity': rnd.choice(sev), 'issue_status': rnd.choice(st)}
        if due:
            v['due_date'] = due
        recs[rid] = {'type': 'work_issue', 'project_id': rnd.choice(sorted(PROJECTS)), 'values': v}
    for day in range(0, 10):
        d = (TODAY - dt.timedelta(days=day)).isoformat()
        for emp in sorted(STAFF):
            rid += 1
            recs[rid] = {'type': 'attendance_entry', 'project_id': None,
                         'values': {'employee': emp, 'attendance_date': d,
                                    'attendance_status': rnd.choice(['Present', 'Present', 'Present', 'Absent', 'Half day', 'Site visit', 'Work from home'])}}
    for i in range(10):
        rid += 1
        a = TODAY + dt.timedelta(days=rnd.randint(-5, 20))
        recs[rid] = {'type': 'leave_request', 'project_id': None,
                     'values': {'employee': rnd.choice(sorted(STAFF)), 'from_date': a.isoformat(),
                                'to_date': (a + dt.timedelta(days=rnd.randint(0, 3))).isoformat(),
                                'leave_type': rnd.choice(['Casual', 'Sick', 'Earned']), 'decision': rnd.choice(['Requested', 'Approved', 'Rejected'])}}
    for i in range(8):
        rid += 1
        recs[rid] = {'type': 'milestone', 'project_id': rnd.choice(sorted(PROJECTS)),
                     'values': {'title': f'Fictional milestone {i}', 'due_date': (TODAY + dt.timedelta(days=rnd.randint(-20, 40))).isoformat(),
                                'owner': rnd.choice(sorted(STAFF)), 'milestone_status': rnd.choice(['Planned', 'In progress', 'Done', 'Delayed'])}}
    return recs


class Resolver:
    def __init__(self, records, cat):
        self.records, self.cat = records, cat

    def node(self, kind, obj_id):
        if kind == 'system.user':
            return {'type': kind, 'id': obj_id, 'values': {'display_name': STAFF[obj_id]}, 'label': STAFF[obj_id]}
        if kind == 'system.project':
            return {'type': kind, 'id': obj_id, 'values': {'name': PROJECTS[obj_id]}, 'label': PROJECTS[obj_id]}
        if kind == 'system.task':
            return None
        r = self.records[obj_id]
        t = self.cat['types'][r['type']]
        lf = t.get('label_field')
        label = r['values'].get(lf) if lf else None
        if lf and t['fields'][lf]['type'] == 'reference' and label is not None:
            label = self.node(t['fields'][lf]['target'], label)['label']
        return {'type': r['type'], 'id': obj_id, 'values': r['values'], 'label': str(label or f'#{obj_id}'), 'project_id': r.get('project_id')}

    def base_rows(self, base):
        return [self.node(base, i) for i, r in self.records.items() if r['type'] == base]

    def follow(self, node, step):
        if step[0] == 'ref':
            v = (node.get('values') or {}).get(step[1])
            n = self.node(step[2], v) if v is not None else None
            return [n] if n else []
        if step[0] == 'project':
            return [self.node('system.project', node['project_id'])] if node.get('project_id') else []
        return []


def world():
    cat = catalog()
    recs = build_records()
    return cat, Resolver(recs, cat), recs

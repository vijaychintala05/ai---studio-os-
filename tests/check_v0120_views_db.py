"""v0.12.0 on real databases, without the web app.

1. Schema v23 (dashboards and layouts, append-only) on SQLite and PostgreSQL 16, run twice.
2. Report expression indexes (views_core.index_statement): created twice without error and USED by
   the query planner for the same expression graph_query.json_field writes.
3. An honest speed measurement on PostgreSQL: 200,000 fictional records of one type, a report
   filter (status = Open) and grouping (owner), with and without the expression index. Also the
   pure-Python planner over 50,000 in-memory records (the new row cap).

Run:  python3 tests/check_v0120_views_db.py
      STUDIOOS_GUARD_PSQL='psql -h /tmp -p 55432 -U studioos' STUDIOOS_GUARD_DB=<empty db> python3 tests/check_v0120_views_db.py
Writes test-evidence-v0120/views_db.json.
"""
import datetime as dt
import json
import os
import shlex
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stdlib_loader import load, ROOT  # noqa: E402

gm, G, V = load('graph_migration', 'graph_core', 'views_core')
RESULTS, BENCH = [], {}


def check(name, ok, detail=''):
    RESULTS.append({'check': name, 'passed': bool(ok), 'detail': str(detail)[:300]})
    print('PASS' if ok else 'FAIL', name, '' if ok else detail)


def refused(fn):
    try:
        fn()
    except Exception:
        return True
    return False


def sqlite_part():
    c = sqlite3.connect(':memory:')
    c.execute('CREATE TABLE approval_tickets (id INTEGER PRIMARY KEY)')
    c.execute('INSERT INTO approval_tickets VALUES (1)')
    for _ in range(2):
        c.execute(gm.V23_TABLE_SQLITE)
        for st in gm.sqlite_v23_guard_statements():
            c.execute(st)
    c.execute("INSERT INTO universal_view_definitions (kind, key, version, definition, ticket_id, created_at) VALUES ('dashboard', 'site_home', 1, '{}', 1, CURRENT_TIMESTAMP)")
    c.execute("INSERT INTO universal_view_definitions (kind, key, version, definition, ticket_id, created_at) VALUES ('dashboard', 'site_home', 2, '{}', 1, CURRENT_TIMESTAMP)")
    check('sqlite: dashboard versions kept side by side', c.execute('SELECT COUNT(*) FROM universal_view_definitions').fetchone()[0] == 2)
    check('sqlite: same version twice refused', refused(lambda: c.execute("INSERT INTO universal_view_definitions (kind, key, version, definition, ticket_id, created_at) VALUES ('dashboard', 'site_home', 2, '{}', 1, CURRENT_TIMESTAMP)")))
    check('sqlite: update refused', refused(lambda: c.execute("UPDATE universal_view_definitions SET key = 'x'")))
    check('sqlite: delete refused', refused(lambda: c.execute('DELETE FROM universal_view_definitions')))
    c.execute('CREATE TABLE flexible_records (id INTEGER PRIMARY KEY, record_type TEXT, data JSON, deleted_at TEXT)')
    c.executemany('INSERT INTO flexible_records (record_type, data) VALUES (?, ?)',
                  [('work_issue', json.dumps({'issue_status': ['Open', 'Closed', 'Resolved'][i % 3], 'owner': i % 7})) for i in range(20000)])
    for _ in range(2):
        for f in ('issue_status', 'owner'):
            c.execute(V.index_statement('sqlite', 'work_issue', f))
    plan = c.execute("EXPLAIN QUERY PLAN SELECT id FROM flexible_records WHERE record_type = 'work_issue' AND deleted_at IS NULL "
                     "AND json_extract(data, '$.issue_status') = 'Open'").fetchall()
    check('sqlite: report index used by the planner', any(V.index_name('work_issue', 'issue_status') in str(r) for r in plan), plan)


def pg_part():
    psql, dbname = os.environ.get('STUDIOOS_GUARD_PSQL'), os.environ.get('STUDIOOS_GUARD_DB')
    if not psql or not dbname:
        print('SKIP PostgreSQL part (set STUDIOOS_GUARD_PSQL and STUDIOOS_GUARD_DB)')
        return False

    def run(sql, ok=True):
        p = subprocess.run(shlex.split(psql) + ['-d', dbname, '-X', '-q', '-A', '-t', '-v', 'ON_ERROR_STOP=1', '-c', sql],
                           capture_output=True, text=True)
        if ok and p.returncode:
            raise RuntimeError(p.stderr.strip())
        return p
    run("CREATE OR REPLACE FUNCTION studioos_forbid_immutable_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION "
        "'Protected journal and metadata history is immutable'; END $$ LANGUAGE plpgsql")
    run('CREATE TABLE IF NOT EXISTS approval_tickets (id INTEGER PRIMARY KEY)')
    run('INSERT INTO approval_tickets VALUES (1) ON CONFLICT DO NOTHING')
    for _ in range(2):
        run(gm.V23_TABLE_PG)
        for t in gm.postgres_v23_guard_tables():
            run(f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'guard_{t}_mutation') THEN "
                f"CREATE TRIGGER guard_{t}_mutation BEFORE UPDATE OR DELETE ON {t} FOR EACH ROW EXECUTE FUNCTION "
                "studioos_forbid_immutable_mutation(); END IF; END $$")
    run("INSERT INTO universal_view_definitions (kind, key, version, definition, ticket_id, created_at) VALUES ('layout', 'work_issue', 1, '{}', 1, now())")
    check('pg: layout version stored', run('SELECT COUNT(*) FROM universal_view_definitions').stdout.strip() == '1')
    check('pg: same version twice refused', run("INSERT INTO universal_view_definitions (kind, key, version, definition, ticket_id, created_at) VALUES ('layout', 'work_issue', 1, '{}', 1, now())", ok=False).returncode != 0)
    check('pg: update refused', run("UPDATE universal_view_definitions SET key = 'x'", ok=False).returncode != 0)
    check('pg: delete refused', run('DELETE FROM universal_view_definitions', ok=False).returncode != 0)
    # speed: 200,000 fictional records
    run('DROP TABLE IF EXISTS flexible_records')
    run('CREATE TABLE flexible_records (id SERIAL PRIMARY KEY, record_type VARCHAR(60), project_id INTEGER, data JSON, deleted_at TIMESTAMPTZ)')
    run("INSERT INTO flexible_records (record_type, project_id, data) SELECT CASE WHEN g % 4 = 0 THEN 'work_issue' ELSE 'timesheet_entry' END, "
        "g % 20, json_build_object('issue_status', (ARRAY['Open','Closed','Resolved','In progress'])[1 + (g / 4) % 4], "
        "'owner', g % 40, 'hours', (g % 9)::text) FROM generate_series(1, 200000) g")
    run('ANALYZE flexible_records')
    q = ("SELECT data ->> 'owner' AS owner, COUNT(*) FROM flexible_records WHERE record_type = 'work_issue' AND deleted_at IS NULL "
         "AND (data ->> 'issue_status') = 'Open' GROUP BY 1")

    def timed(label):
        best = None
        for _ in range(5):
            out = run('EXPLAIN (ANALYZE, FORMAT JSON) ' + q).stdout
            plan = json.loads(out)[0]
            ms = plan['Execution Time']
            best = ms if best is None or ms < best else best
        BENCH[label] = {'best_of_5_ms': round(best, 2), 'plan_top': plan['Plan']['Node Type'],
                        'uses_index': V.index_name('work_issue', 'issue_status') in out}
        return BENCH[label]
    before = timed('pg_200k_without_index')
    for _ in range(2):
        run(V.index_statement('postgresql', 'work_issue', 'issue_status'))
    run('ANALYZE flexible_records')
    after = timed('pg_200k_with_index')
    check('pg: report index created twice without error and used', after['uses_index'], BENCH)
    check('pg: same answer with and without the index',
          run(q + ' ORDER BY 1').stdout == run('SET enable_indexscan = off; SET enable_bitmapscan = off; ' + q + ' ORDER BY 1').stdout)
    print('PG timings (ms):', before['best_of_5_ms'], '->', after['best_of_5_ms'])
    run('DROP TABLE flexible_records')
    return True


def python_planner_part():
    """The Python planner over 50,000 in-memory records: what a report costs at the new cap."""
    cat = G.catalog_from({'work_issue': {'title': 'Work issue', 'fields': [
        {'name': 'title', 'type': 'text'}, {'name': 'owner', 'type': 'reference', 'target': 'system.user'},
        {'name': 'severity', 'type': 'enum', 'options': ['Low', 'High']}, {'name': 'issue_status', 'type': 'enum', 'options': ['Open', 'Closed']},
        {'name': 'cost', 'type': 'money'}]}}, {})
    users = {i: f'Fictional Person {i}' for i in range(40)}

    class Res:
        def __init__(self, n):
            self.rows = [{'type': 'work_issue', 'id': i, 'label': f'#{i}', 'values': {
                'owner': i % 40, 'severity': 'High' if i % 3 else 'Low', 'issue_status': 'Open' if i % 2 else 'Closed',
                'cost': {'amount': f'{i % 997}.25', 'currency': 'INR'}}} for i in range(n)]

        def base_rows(self, base):
            return self.rows

        def follow(self, node, step):
            v = node['values'].get(step[1])
            return [{'type': 'system.user', 'id': v, 'values': {}, 'label': users[v]}] if v is not None else []
    d = {'key': 'bench', 'title': 'Bench', 'base': 'work_issue', 'filters': [{'path': 'issue_status', 'op': 'eq', 'value': 'Open'}],
         'group_by': ['owner', 'severity'], 'measures': [{'agg': 'count'}, {'agg': 'sum', 'path': 'cost'}]}
    for n in (10000, 50000):
        r = Res(n)
        t = time.perf_counter()
        out = G.run_report(r, cat, d, dt.date(2026, 11, 14))
        BENCH[f'python_planner_{n}_records_s'] = round(time.perf_counter() - t, 3)
        want = {(i % 40, 'High' if i % 3 else 'Low') for i in range(n) if i % 2}
        check(f'python planner: {n} records grouped exactly', out['matched'] == n // 2 and out['groups'] == len(want), out['groups'])


if __name__ == '__main__':
    sqlite_part()
    pg = pg_part()
    python_planner_part()
    out = {'passed': sum(r['passed'] for r in RESULTS), 'total': len(RESULTS), 'postgres_ran': pg, 'benchmark': BENCH,
           'machine_note': 'Build sandbox (shared CPU); timings are indicative only, not the NAS.', 'results': RESULTS}
    (ROOT / 'test-evidence-v0120').mkdir(exist_ok=True)
    (ROOT / 'test-evidence-v0120' / 'views_db.json').write_text(json.dumps(out, indent=1) + '\n')
    print(f"{out['passed']}/{out['total']} passed", json.dumps(BENCH))
